"""BEW overlay warehouse rollup task.

Runs `overlays.bew.run_bew()` against persisted Financial + PriceHistory
+ market_cap + sector + latest F3 score for every framework-scored
ticker. Persists `bew_verdict` / `bew_score` / `bew_n_checks` /
`bew_scored_at` onto the `companies` table.

Why a warehouse task and not a dive-time overlay only:
  The dive-time path is unchanged — `deepdive/orchestrator.py` still
  calls `run_bew()` inline and writes it into `DeepDiveRun.overlays_results_json`.
  This task ADDS a parallel cheap-rollup path so the winner-screen
  pre-filter can read a persisted BEW verdict without paying the dive
  cost (~145s/ticker). The two writers don't race — the warehouse
  rollup writes `companies.bew_*` columns; the dive writes the run-row
  JSON. They're independent records.

Source: ``in-memory`` — `run_bew()` reads SQLite only (Financial,
PriceHistory, FrameworkScore) plus already-warehoused Company columns
(market_cap_usd, sector). No upstream API calls.

Refresh interval: 14 days. BEW inputs change slowly — price history
updates daily but the 3yr skewness window damps it; framework scores
refresh weekly; market_cap drifts continuously but the <$2B threshold
is binary. 14d is a sensible middle ground.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.models.schema import Company
from screener.policies import not_excluded
from screener.tasks.base import FilterResult

if TYPE_CHECKING:
    from data.rate_limit import TokenBucket

logger = logging.getLogger("task-runner")


class BEWOverlayTask:
    name = "bew_overlay"
    source = "in-memory"
    refresh_interval = timedelta(days=14)
    concurrency_override = None

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            # Needs F3 score → framework_scored_at must be populated
            .where(Company.framework_scored_at.isnot(None))
            .where(not_excluded())
            .where(
                or_(
                    Company.bew_scored_at.is_(None),
                    Company.bew_scored_at < cutoff,
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
        # In-memory — BEW reads SQLite via CompanyDataReader.
        from data.reader import CompanyDataReader
        from overlays.bew import run_bew

        results: list[FilterResult] = []
        for c in companies:
            try:
                reader = CompanyDataReader(c.ticker)
                bew = await run_bew(c.ticker, reader=reader, f3_score=None)
            except Exception as exc:
                logger.warning(
                    "[%s] %s run_bew threw: %s",
                    self.name, c.ticker, exc,
                )
                continue
            if not isinstance(bew, dict) or not bew.get("ok"):
                # Run yielded no verdict (e.g., no Company row, no data) —
                # leave bew_scored_at NULL so we retry later.
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "company_id": c.id,
                    "verdict": (bew.get("verdict") or "").lower() or None,
                    "score": bew.get("score"),
                    "n_checks": bew.get("n_checks_evaluable"),
                },
            ))
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

        n_persisted = 0
        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            v = r.values
            company.bew_verdict = v["verdict"]
            company.bew_score = v["score"]
            company.bew_n_checks = v["n_checks"]
            company.bew_scored_at = now
            n_persisted += 1

        db.flush()
        logger.info("[%s] persisted %d rows", self.name, n_persisted)
