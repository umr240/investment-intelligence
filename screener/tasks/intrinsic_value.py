"""Damodaran intrinsic value warehouse task (ADR-027 Phase D).

Computes per-ticker intrinsic value using `valuation/damodaran/` and
persists to Company columns:
    intrinsic_value_per_share, margin_of_safety_pct,
    intrinsic_value_tier, intrinsic_value_fetched_at

Refresh interval: 30 days. IV is slow-moving relative to composite_score
(1d) because the inputs (annual fundamentals + reference data) update on
quarterly / annual cadence.

Scope: $100M+ companies the active exclusion policy confirms (all of them
under `none`). Smaller filers are filtered at select_pending() to keep bulk
runs focused.

Per ADR-017: this is an in-memory task (no HTTP) — DB-only data
assembly + pure-math IV computation. Concurrency = 1 because the IV
calc is fast enough sequentially (~50ms/ticker) and concurrency adds
SQLite-write contention for no gain.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.models.schema import Company
from screener.policies import get_policy
from screener.tasks.base import FilterResult
from valuation.damodaran import (
    CompanyNotFoundError,
    InsufficientDataError,
    compute_intrinsic_value,
    load_inputs,
)

if TYPE_CHECKING:
    from data.rate_limit import TokenBucket


CAP_MIN = 100_000_000   # $100M; matches the warehouse mid-cap universe


class IntrinsicValueTask:
    name = "intrinsic_value"
    source = "in-memory"
    refresh_interval = timedelta(days=30)
    concurrency_override = 1     # SQLite write contention; sequential is fine

    def select_pending(self, db: Session) -> list[Company]:
        """Policy-eligible, $100M+ tickers due for IV refresh."""
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            .where(get_policy().eligible())
            .where(Company.market_cap_usd.is_not(None))
            .where(Company.market_cap_usd >= CAP_MIN)
            .where(
                or_(
                    Company.intrinsic_value_fetched_at.is_(None),
                    Company.intrinsic_value_fetched_at < cutoff,
                )
            )
        )
        return list(db.execute(stmt).scalars().all())

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        """Compute IV for each company in the chunk. No HTTP — pure DB +
        in-memory math, but the FilterTask runner expects an async signature."""
        results: list[FilterResult] = []
        for company in companies:
            ticker = company.ticker
            try:
                inputs = load_inputs(ticker)
                ivr = compute_intrinsic_value(inputs)
            except (CompanyNotFoundError, InsufficientDataError):
                # Recoverable — leave warehouse as-is (NULL or stale)
                continue
            except Exception:                             # noqa: BLE001
                # Any other failure: skip this ticker but keep the chunk going
                continue
            results.append(
                FilterResult(
                    cik=company.cik or company.ticker,
                    values={
                        "intrinsic_value_per_share": ivr.intrinsic_value_per_share,
                        "margin_of_safety_pct": ivr.margin_of_safety_pct,
                        "intrinsic_value_tier": ivr.tier,
                    },
                )
            )
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            company.intrinsic_value_per_share = r.values["intrinsic_value_per_share"]
            company.margin_of_safety_pct = r.values["margin_of_safety_pct"]
            company.intrinsic_value_tier = r.values["intrinsic_value_tier"]
            company.intrinsic_value_fetched_at = now

        db.commit()


__all__ = ["IntrinsicValueTask", "CAP_MIN"]
