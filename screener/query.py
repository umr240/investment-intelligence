"""Screener query — SELECT against the warehouse, not a pipeline run (ADR-017 §5).

The 6-tier linear pipeline (``screener/pipeline.py``, ``screener/stages.py``)
is replaced by this single SQL builder. Whatever data lives in the
``Company`` warehouse at the moment of the call is what gets ranked. The
warehouse is filled asynchronously by the per-filter tasks under
:mod:`screener.tasks` running on staggered crons.

Adding a new filter:

  1. add a column to ``Company`` (+ ``*_fetched_at``) in a migration
  2. write a ``FilterTask`` that maintains it
  3. add a ``where()`` clause and CLI arg here

No tier renumbering. No pipeline rework. Filters compose via SQL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select

from data.models.schema import Company

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(slots=True)
class ScreenerQuery:
    """Composable filter parameters for :func:`run_screener`.

    All fields are optional; ``None`` means "no constraint on this column".
    The result is ranked by ``Company.composite_score`` descending and
    truncated to ``top_n``.
    """

    cap_min: float | None = None
    cap_max: float | None = None
    ipo_after: date | None = None
    sector_in: list[str] | None = None
    exclude_policy_failures: bool = True  # keep only rows the policy confirmed
    policy: str | None = None  # registered policy name; None = settings
    min_roic: float | None = None
    max_debt_equity: float | None = None
    min_fcf_margin: float | None = None
    min_revenue_growth: float | None = None
    min_completeness: float = 0.8        # require 80%+ of warehouse columns populated
    min_framework_score: float | None = None       # framework composite (0–10)
    framework_verdict_in: tuple[str, ...] | None = None  # ('priority_watchlist', 'watchlist')
    top_n: int = 30
    statuses: tuple[str, ...] = ("screener_candidate",)
    order_by: str = "composite_score"           # 'composite_score' | 'framework_composite_score'


def run_screener(db: Session, q: ScreenerQuery | None = None) -> list[Company]:
    """Execute a warehouse-only screener query.

    This function does NO network I/O. It assumes per-filter tasks have
    populated the relevant columns. Tickers with stale/missing data are
    excluded by ``data_completeness < min_completeness``.
    """
    q = q or ScreenerQuery()

    stmt = select(Company).where(Company.status.in_(q.statuses))

    if q.cap_min is not None:
        stmt = stmt.where(Company.market_cap_usd >= q.cap_min)
    if q.cap_max is not None:
        stmt = stmt.where(Company.market_cap_usd <= q.cap_max)
    if q.ipo_after is not None:
        stmt = stmt.where(Company.ipo_date >= q.ipo_after)
    if q.sector_in:
        stmt = stmt.where(Company.sector.in_(q.sector_in))
    if q.exclude_policy_failures:
        from screener.policies import get_policy

        stmt = stmt.where(get_policy(q.policy).eligible())
    if q.min_roic is not None:
        stmt = stmt.where(Company.roic >= q.min_roic)
    if q.max_debt_equity is not None:
        stmt = stmt.where(Company.debt_to_equity <= q.max_debt_equity)
    if q.min_fcf_margin is not None:
        stmt = stmt.where(Company.fcf_margin >= q.min_fcf_margin)
    if q.min_revenue_growth is not None:
        stmt = stmt.where(Company.revenue_growth >= q.min_revenue_growth)
    if q.min_completeness > 0:
        stmt = stmt.where(Company.data_completeness >= q.min_completeness)
    if q.min_framework_score is not None:
        stmt = stmt.where(Company.framework_composite_score >= q.min_framework_score)
    if q.framework_verdict_in:
        from config.verdicts import stored_forms

        stmt = stmt.where(Company.framework_verdict.in_(stored_forms(q.framework_verdict_in)))

    order_col = (
        Company.framework_composite_score
        if q.order_by == "framework_composite_score"
        else Company.composite_score
    )
    stmt = stmt.order_by(order_col.desc().nullslast()).limit(q.top_n)

    return list(db.execute(stmt).scalars().all())


__all__ = ["ScreenerQuery", "run_screener"]
