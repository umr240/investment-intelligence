"""
ScreenerRun + ScreenerResult persistence (docs/architecture/SCREENER_PIPELINE.md §1 Tier 6).

Single-transaction write per screener run. Stages and gate funnel are
serialised onto the run; per-ticker results land in `screener_results`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from data.db import get_session
from data.models.api_models import ScreenerParams
from data.models.schema import Company, ScreenerResult, ScreenerRun
from screener.policies import get_policy
from screener.policies.verdicts import reason_of

logger = logging.getLogger(__name__)


def persist_screener_run(
    params: ScreenerParams,
    mode: str,
    universe_count: int,
    gate_funnel: dict[str, int],
    scored_tickers: list,                       # list[ScoredTicker]
    run_id: int | None = None,
) -> int:
    """
    Persist final screener results.
      run_id=None  → INSERT new ScreenerRun (legacy single-shot path)
      run_id=int   → UPDATE existing ScreenerRun (staged path: Stage A
                     created the row at start, Stage C fills it in)
    Either way, ScreenerResult rows are INSERTed under the run id.
    """
    passed_gates = sum(1 for s in scored_tickers if s.clean)
    results_json = json.dumps({
        "gate_funnel": gate_funnel,
        "top_n": [
            {
                "ticker": s.ticker,
                "composite_score": s.total_score,
                "verdict": s.verdict,
                "clean": s.clean,
            }
            for s in scored_tickers[:50]
        ],
    })

    with get_session() as session:
        if run_id is None:
            run = ScreenerRun(
                run_date=datetime.now(),
                region=params.region,
                market_cap_min=params.cap_min,
                market_cap_max=params.cap_max,
                sector_filter=params.sector,
                ethics_filter=get_policy(params.exclusion_policy).name,
                mode=mode,
                universe_count=universe_count,
                passed_gates=passed_gates,
                results_json=results_json,
            )
            session.add(run)
            session.flush()    # get run.id
        else:
            run = session.query(ScreenerRun).filter_by(id=run_id).first()
            if run is None:
                raise RuntimeError(f"ScreenerRun id={run_id} not found for staged update")
            run.universe_count = universe_count
            run.passed_gates = passed_gates
            run.results_json = results_json

        # Map tickers → company_id
        tickers = {s.ticker for s in scored_tickers}
        company_id_by_ticker = {
            t: cid
            for t, cid in (
                session.query(Company.ticker, Company.id)
                .filter(Company.ticker.in_(tickers))
                .all()
            )
        }

        for s in scored_tickers:
            session.add(ScreenerResult(
                screener_run_id=run.id,
                company_id=company_id_by_ticker.get(s.ticker),
                ticker=s.ticker,
                hard_gate_passed=s.clean,
                gate_failures=json.dumps(s.gate_failures) if s.gate_failures else None,
                f1_proxy=s.f_scores.get("F1"),
                f2_proxy=s.f_scores.get("F2"),
                f3_proxy=s.f_scores.get("F3"),
                f4_proxy=s.f_scores.get("F4"),
                f5_proxy=s.f_scores.get("F5"),
                f6_proxy=s.f_scores.get("F6"),
                f7_proxy=s.f_scores.get("F7"),
                composite_score=s.total_score,
                verdict=s.verdict,
            ))

        run_id = run.id

    logger.info(
        "screener_run id=%d persisted: %d results, %d clean",
        run_id, len(scored_tickers), passed_gates,
    )
    return run_id


def list_recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return summary of recent screener runs (for `invest screen ls`)."""
    with get_session() as session:
        runs = (
            session.query(ScreenerRun)
            .order_by(ScreenerRun.run_date.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "run_date": str(r.run_date)[:19] if r.run_date else "",
                "region": r.region or "us",
                "mode": r.mode or "—",
                "universe": r.universe_count or 0,
                "passed_gates": r.passed_gates or 0,
            }
            for r in runs
        ]


def load_run_results(
    run_id: int,
    tier: str = "all",                 # 'all' | 'clean' | 'flagged'
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return ScreenerResult rows for a given run (for `invest screen show ID`)."""
    with get_session() as session:
        q = (
            session.query(ScreenerResult)
            .filter_by(screener_run_id=run_id)
            .order_by(ScreenerResult.composite_score.desc().nullslast())
        )
        if tier == "clean":
            q = q.filter(ScreenerResult.hard_gate_passed.is_(True))
        elif tier == "flagged":
            q = q.filter(ScreenerResult.hard_gate_passed.is_(False))
        if limit is not None:
            q = q.limit(limit)
        rows = q.all()
        return [
            {
                "ticker": r.ticker,
                "clean": bool(r.hard_gate_passed),
                "composite": r.composite_score or 0.0,
                "verdict": r.verdict or "",
                "f_scores": {
                    "F1": r.f1_proxy, "F2": r.f2_proxy, "F3": r.f3_proxy,
                    "F4": r.f4_proxy, "F5": r.f5_proxy,
                    "F6": r.f6_proxy, "F7": r.f7_proxy,
                },
                "gate_failures": (
                    json.loads(r.gate_failures) if r.gate_failures else []
                ),
            }
            for r in rows
        ]


def list_screener_candidates(sector: str | None = None) -> list[dict[str, Any]]:
    """Return current screener_candidate Company rows (for `invest screen candidates`)."""
    with get_session() as session:
        policy = get_policy()
        # The policy's own predicate decides "excluded"; its status words are its own.
        excluded = set(
            session.execute(
                select(Company.id).where(
                    Company.status == "screener_candidate", ~policy.not_excluded()
                )
            ).scalars()
        )
        q = (
            session.query(Company)
            .options(selectinload(Company.exclusion_verdicts))
            .filter(Company.status == "screener_candidate")
        )
        if sector:
            q = q.filter(Company.sector.ilike(f"%{sector}%"))
        rows = q.order_by(Company.last_screened.desc()).all()
        return [
            {
                "ticker": c.ticker,
                "name": c.name,
                "sector": c.sector or "",
                "industry": c.industry or "",
                "market_cap_b": (c.market_cap_usd or 0) / 1e9,
                "last_screened": str(c.last_screened) if c.last_screened else "",
                "exclusion_status": policy.status_of(c),
                "exclusion_reason": reason_of(c, policy.name),
                "excluded": c.id in excluded,
                "retention_days": c.retention_days,
            }
            for c in rows
        ]
