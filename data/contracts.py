"""Data contracts over persisted rows (ADR-044).

Each contract counts failing units out of total units against a threshold, the
largest failing share allowed, or none for a reported-only contract; a result
keeps its first SAMPLE_SIZE failing keys (§2.2). DB-only: no network, no LLM.
Thresholds change only by amending ADR-044 (§3).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from data.models.schema import (
    Company,
    DataContractRun,
    DeepDiveRun,
    ExclusionVerdict,
    Financial,
    ScreenerRun,
    ScreenerStage,
)

logger = logging.getLogger(__name__)

SAMPLE_SIZE = 20
SPLIT_JUMP = 2.0  # C4: the smallest common split is 2:1
COMPLETENESS_FLOOR = 0.5  # C6
OVERRIDE_SOURCE = "override"  # C5: the explicit override record
# C1: banks, insurers and IFRS filers whose revenue no concept chain reads; grows by review (§2.6).
C1_EXEMPT: frozenset[str] = frozenset()

ALL, DIVED = "all", "dived"


@dataclass(frozen=True)
class Measurement:
    failing: int
    total: int
    keys: list[str]  # the failing units: tickers, run ids for C7, none for C8
    note: str | None = None


@dataclass(frozen=True)
class Contract:
    id: str
    title: str
    unit: str
    severity: str  # "block" | "warn"
    # Universe-wide scope -> largest failing share allowed; None reports only.
    thresholds: dict[str, float | None]
    measure: Callable[[Session, str], Measurement]
    per_ticker: bool = False  # also checked after refresh_ticker (§2.3)


@dataclass(frozen=True)
class ContractResult:
    contract: Contract
    scope: str  # "all", "dived" or a ticker
    failing: int
    total: int
    keys: list[str]
    threshold: float | None
    note: str | None = None

    @property
    def share(self) -> float | None:
        return self.failing / self.total if self.total else None

    @property
    def passed(self) -> bool | None:
        if self.threshold is None:
            return None
        return self.share is None or self.share <= self.threshold

    @property
    def sample(self) -> list[str]:
        return sorted(self.keys)[:SAMPLE_SIZE]


def _in_scope(scope: str) -> Any:
    """Company ids a scope covers; None for every company."""
    if scope == ALL:
        return None
    if scope == DIVED:
        return select(DeepDiveRun.company_id).distinct()
    return select(Company.id).where(Company.ticker == scope)


def _scoped(q: Any, company_id: Any, scope: str) -> Any:
    ids = _in_scope(scope)
    return q if ids is None else q.where(company_id.in_(ids))


def _per_company(session: Session, q: Any) -> Measurement:
    """`q` yields (ticker, failed) per company in scope."""
    rows = session.execute(q).all()
    keys = [str(t) for t, failed in rows if failed]
    return Measurement(len(keys), len(rows), keys)


def _c1_revenue(session: Session, scope: str) -> Measurement:
    has_revenue = func.max(case((Financial.revenue.is_not(None), 1), else_=0))
    q: Any = (
        select(Company.ticker, has_revenue == 0)
        .join(Financial, Financial.company_id == Company.id)
        .where(Financial.period == "annual", Company.ticker.not_in(C1_EXEMPT))
        .group_by(Company.id, Company.ticker)
    )
    return _per_company(session, _scoped(q, Company.id, scope))


def _c2_quarters(session: Session, scope: str) -> Measurement:
    quarterly = func.sum(case((Financial.period != "annual", 1), else_=0))
    annual = func.sum(case((Financial.period == "annual", 1), else_=0))
    q: Any = (
        select(Company.ticker, quarterly == 0)
        .join(Financial, Financial.company_id == Company.id)
        .group_by(Company.id, Company.ticker)
        .having(annual > 0)
    )
    return _per_company(session, _scoped(q, Company.id, scope))


def _c3_split_factor(session: Session, scope: str) -> Measurement:
    latest: Any = (
        select(Financial.company_id, func.max(Financial.fiscal_year).label("fy"))
        .where(Financial.period == "annual")
        .group_by(Financial.company_id)
        .subquery()
    )
    q: Any = (
        select(Company.ticker, Financial.share_split_factor.is_(None))
        .join(latest, latest.c.company_id == Company.id)
        .join(
            Financial,
            (Financial.company_id == Company.id)
            & (Financial.fiscal_year == latest.c.fy)
            & (Financial.period == "annual"),
        )
    )
    return _per_company(session, _scoped(q, Company.id, scope))


def _c4_share_jumps(session: Session, scope: str) -> Measurement:
    # Quarterly rows carry no split factor today, so every >2x jump counts (ADR-044 §2.1).
    window = {"partition_by": Financial.company_id, "order_by": Financial.period_end_date}
    factor: Any = func.coalesce(Financial.share_split_factor, 1.0)
    pairs: Any = _scoped(
        select(
            Financial.company_id,
            Financial.shares_outstanding.label("s"),
            func.lag(Financial.shares_outstanding).over(**window).label("prev"),
            factor.label("k"),
            func.lag(factor).over(**window).label("prev_k"),
        ).where(
            Financial.period != "annual",
            Financial.shares_outstanding > 0,  # type: ignore[arg-type]  # Column-style model
            Financial.period_end_date.is_not(None),
        ),
        Financial.company_id,
        scope,
    ).subquery()
    jump: Any = (pairs.c.k == pairs.c.prev_k) & (
        (pairs.c.s > SPLIT_JUMP * pairs.c.prev) | (pairs.c.prev > SPLIT_JUMP * pairs.c.s)
    )
    q: Any = (
        select(Company.ticker, func.max(case((jump, 1), else_=0)) == 1)
        .join(pairs, pairs.c.company_id == Company.id)
        .where(pairs.c.prev.is_not(None))
        .group_by(Company.id, Company.ticker)
    )
    return _per_company(session, q)


def _c5_exclusions(session: Session, scope: str) -> Measurement:
    from screener.policies import get_policy

    policy = get_policy()
    if policy.name == "none":
        return Measurement(0, 0, [], "policy 'none' classifies nothing")
    excluded: Any = ~policy.not_excluded()
    classified = excluded | policy.eligible()
    overridden: Any = Company.id.in_(
        select(ExclusionVerdict.company_id).where(
            ExclusionVerdict.policy == policy.name, ExclusionVerdict.source == OVERRIDE_SOURCE
        )
    )
    q = _scoped(
        select(
            Company.ticker,
            Company.sector,
            Company.industry,
            case((excluded, True), else_=False),
            case((classified, True), else_=False),
            case((overridden, True), else_=False),
        ),
        Company.id,
        scope,
    )
    failing: list[str] = []
    total = unclassified = 0
    for ticker, sector, industry, is_excluded, is_classified, is_overridden in session.execute(q):
        if not is_classified:
            unclassified += 1
            continue
        total += 1
        if not is_overridden and policy.classify(sector, industry).excluded != bool(is_excluded):
            failing.append(str(ticker))
    note = f"policy {policy.name}; {unclassified} never classified"
    return Measurement(len(failing), total, failing, note)


def _c6_completeness(session: Session, scope: str) -> Measurement:
    low: Any = (Company.data_completeness < COMPLETENESS_FLOOR) | Company.data_completeness.is_(
        None
    )
    q = select(Company.ticker, case((low, True), else_=False))
    return _per_company(session, _scoped(q, Company.id, scope))


def _c7_screener_runs(session: Session, scope: str) -> Measurement:
    def stage_with(*conds: Any) -> Any:
        return select(ScreenerStage.screener_run_id).where(*conds)

    finished: Any = (
        ScreenerRun.id.in_(
            stage_with(ScreenerStage.stage == "C", ScreenerStage.status == "completed")
        )
        | ScreenerRun.id.in_(stage_with(ScreenerStage.status == "failed"))
        | ScreenerRun.id.not_in(stage_with())
    )
    rows = session.execute(select(ScreenerRun.id, ScreenerRun.universe_count).where(finished)).all()
    keys = [f"run {rid}" for rid, n in rows if not n]
    return Measurement(len(keys), len(rows), keys)


def _c8_frames_revenue(session: Session, scope: str) -> Measurement:
    row: Any = session.execute(
        select(ScreenerStage.screener_run_id, ScreenerStage.state_json)
        .where(ScreenerStage.stage == "B", ScreenerStage.status == "completed")
        .order_by(ScreenerStage.completed_at.desc().nulls_last(), ScreenerStage.id.desc())
        .limit(1)
    ).first()
    funnel = json.loads(row[1] or "{}").get("gate_funnel", {}) if row else {}
    if row is None or not {"T4_frames_filers", "T4_frames_revenue"} <= funnel.keys():
        return Measurement(0, 0, [], "no completed Stage B has recorded frames counts")
    filers, resolved = int(funnel["T4_frames_filers"]), int(funnel["T4_frames_revenue"])
    # Frames filers are CIKs, mostly not stored companies: counted, not listed.
    return Measurement(filers - resolved, filers, [], f"Stage B of run {row[0]}")


CONTRACTS: tuple[Contract, ...] = (
    Contract("C1", "Annual revenue present", "companies with annual rows", "block",
             {ALL: 0.05}, _c1_revenue, per_ticker=True),
    Contract("C2", "Quarterly rows present", "companies with annual rows", "block",
             {DIVED: 0.0, ALL: None}, _c2_quarters, per_ticker=True),
    Contract("C3", "Latest annual split factor known", "companies with annual rows", "warn",
             {DIVED: 0.0}, _c3_split_factor, per_ticker=True),
    Contract("C4", "No unexplained >2x quarterly share jump", "companies with quarterly shares",
             "warn", {ALL: 0.0}, _c4_share_jumps, per_ticker=True),
    Contract("C5", "Exclusion verdict matches the classifier", "classified companies", "block",
             {ALL: 0.0}, _c5_exclusions),
    Contract("C6", f"data_completeness >= {COMPLETENESS_FLOOR}", "companies", "warn",
             {ALL: None}, _c6_completeness),
    Contract("C7", "Finished screener run has a universe", "finished screener runs", "block",
             {ALL: 0.0}, _c7_screener_runs),
    Contract("C8", "Tier-4 revenue resolvable", "frames filers", "warn",
             {ALL: None}, _c8_frames_revenue),
)  # fmt: skip
BY_ID = {c.id: c for c in CONTRACTS}
SCREENER_CONTRACTS = ("C5", "C7", "C8")  # checked after each screener stage (§2.3)


def evaluate(session: Session, contract: Contract, scope: str) -> ContractResult:
    m = contract.measure(session, scope)
    threshold = contract.thresholds.get(scope, 0.0)  # a ticker: any failure is a gap
    return ContractResult(contract, scope, m.failing, m.total, m.keys, threshold, m.note)


def evaluate_all(session: Session, ids: Iterable[str] | None = None) -> list[ContractResult]:
    """Every universe-wide scope of the given contracts (all of them by default)."""
    chosen = [BY_ID[i] for i in ids] if ids is not None else list(CONTRACTS)
    return [evaluate(session, c, scope) for c in chosen for scope in c.thresholds]


def _write(rows: list[dict[str, Any]]) -> None:
    try:
        from data.db import get_session

        with get_session() as session:
            session.add_all(DataContractRun(**row) for row in rows)
    except Exception as exc:  # noqa: BLE001 - a check must never fail the work it watches
        logger.warning("data_contract_runs not written: %s", type(exc).__name__)


def record(results: list[ContractResult], trigger: str) -> None:
    """Persist results to `data_contract_runs`; `trigger` names what ran them."""
    now = datetime.now(UTC).replace(tzinfo=None)
    _write([
        {
            "contract_id": r.contract.id,
            "scope": r.scope,
            "trigger": trigger,
            "severity": r.contract.severity,
            "failing": r.failing,
            "total": r.total,
            "threshold": r.threshold,
            "passed": r.passed,
            "sample_json": json.dumps(r.sample),
            "note": r.note,
            "created_at": now,
        }
        for r in results
    ])  # fmt: skip


def check_ticker(ticker: str) -> list[str]:
    """C1–C4 for one ticker after a refresh: each violation as a data_gaps entry."""
    from data.db import get_session

    with get_session() as session:
        results = [evaluate(session, c, ticker) for c in CONTRACTS if c.per_ticker]
    record(results, "refresh")
    return [
        f"{ticker}: data contract {r.contract.id} ({r.contract.severity}) not met: "
        f"{r.contract.title.lower()}"
        for r in results
        if r.passed is False
    ]


def check_after_screener_stage() -> None:
    """C5, C7 and C8 after a screener stage finishes; failures are logged, never raised."""
    try:
        from data.db import get_session

        with get_session() as session:
            results = evaluate_all(session, SCREENER_CONTRACTS)
        record(results, "screener")
    except Exception as exc:  # noqa: BLE001 - a check must never fail the stage it watches
        logger.warning("screener data contracts not checked: %s", type(exc).__name__)
        return
    for r in results:
        if r.passed is False:
            logger.warning(
                "data contract %s (%s) failed: %d of %d %s", r.contract.id,
                r.contract.severity, r.failing, r.total, r.contract.unit,
            )  # fmt: skip
