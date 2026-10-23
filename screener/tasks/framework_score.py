"""Framework-score warehouse rollup task — Phase 4d.

Now that F1–F7 score functions are implemented, the warehouse needs a
ranking column the screener can sort on. This task:

  1. Selects companies whose ``FundamentalsTask`` has run (so there's
     enough Financial data for at least F1's 2-year requirement) and
     whose ``framework_scored_at`` is missing or stale.
  2. For each, runs all 7 frameworks via the existing dive orchestrator
     (``deepdive.orchestrator.run_frameworks``) — IPO-aware feasibility
     skips frameworks that lack the data they need.
  3. Computes the mode-resolved composite score + verdict via
     ``frameworks.composite.compute_composite_score``.
  4. Persists the rollup to ``Company.framework_*`` columns AND inserts
     a ``FrameworkScore`` row so per-framework history is preserved.

Source: ``in-memory`` — frameworks read from ``CompanyDataReader`` which
hits SQLite only. No upstream API calls.

Refresh interval: 7 days. Frameworks change with new fundamentals
(quarterly cadence at most); 7d gives slack while still picking up
quarterly filings within a week or two.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.models.schema import Company, FrameworkScore
from deepdive.orchestrator import run_frameworks
from frameworks.base import FrameworkResult, known_frameworks
from frameworks.composite import classify_company_stage, compute_composite_score
from screener.policies import not_excluded
from screener.tasks.base import FilterResult

if TYPE_CHECKING:
    from data.rate_limit import TokenBucket

logger = logging.getLogger("task-runner")


class FrameworkScoreTask:
    name = "framework_score"
    source = "in-memory"
    refresh_interval = timedelta(days=7)
    concurrency_override = None

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            # Need fundamentals fetched at least once — frameworks need
            # Financial rows to read from.
            .where(Company.roic_fetched_at.isnot(None))
            .where(not_excluded())
            .where(
                or_(
                    Company.framework_scored_at.is_(None),
                    Company.framework_scored_at < cutoff,
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
        # In-memory: no upstream calls; frameworks read SQLite via CompanyDataReader.
        from data.reader import CompanyDataReader

        results: list[FilterResult] = []
        all_frameworks = known_frameworks()  # ['F1', 'F2', ..., 'F7']

        for c in companies:
            try:
                framework_results, unfeasible = await run_frameworks(
                    c.ticker, all_frameworks
                )
            except Exception as exc:
                logger.warning(
                    "[%s] %s run_frameworks threw: %s",
                    self.name, c.ticker, exc,
                )
                continue

            scores: dict[str, float | None] = {
                name: framework_results[name].score
                if name in framework_results else None
                for name in all_frameworks
            }

            try:
                stage = classify_company_stage(CompanyDataReader(c.ticker))
            except Exception as exc:
                logger.warning(
                    "[%s] %s classify_company_stage failed: %s",
                    self.name, c.ticker, exc,
                )
                continue

            composite = compute_composite_score(
                scores, mode="default", stage=stage.stage,
            )

            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "company_id": c.id,
                    "framework_results": framework_results,
                    "unfeasible": unfeasible,
                    "stage": stage.stage,
                    "composite_score": composite.score,
                    "verdict": composite.verdict,
                    "mode_used": composite.mode_resolved,
                    "weights_used": composite.weights_used,
                    "scores": scores,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)

        # 1) Roll up onto Company warehouse columns
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
            v = r.values
            company.framework_composite_score = v["composite_score"]
            company.framework_verdict = v["verdict"]
            company.framework_mode_used = v["mode_used"]
            company.framework_unfeasible_count = len(v["unfeasible"])
            company.framework_scored_at = now

        # 2) Append a FrameworkScore history row per result
        run_today = date.today()
        for r in results:
            v = r.values
            company_id = v["company_id"]
            framework_results: dict[str, FrameworkResult] = v["framework_results"]
            scores: dict[str, float | None] = v["scores"]

            # framework_scores has UNIQUE (company_id, run_date, mode) — UPSERT shape
            existing = db.execute(
                select(FrameworkScore).where(
                    FrameworkScore.company_id == company_id,
                    FrameworkScore.run_date == run_today,
                    FrameworkScore.mode == v["mode_used"],
                )
            ).scalar_one_or_none()

            payload = {
                name: {
                    "score": fr.score,
                    "verdict": fr.verdict,
                    "signals": fr.signals,
                    "data_gaps": fr.data_gaps,
                    "notes": fr.notes,
                }
                for name, fr in framework_results.items()
            }

            if existing is not None:
                row = existing
            else:
                row = FrameworkScore(
                    company_id=company_id,
                    run_date=run_today,
                    mode=v["mode_used"],
                )
                db.add(row)

            row.company_stage = v["stage"]
            row.f1_score = scores.get("F1")
            row.f2_score = scores.get("F2")
            row.f3_score = scores.get("F3")
            row.f4_score = scores.get("F4")
            row.f5_score = scores.get("F5")
            row.f6_score = scores.get("F6")
            row.f7_score = scores.get("F7")
            row.composite_score = v["composite_score"]
            row.verdict = v["verdict"]
            row.scorecard_json = json.dumps(payload, default=str)

        db.commit()


__all__ = ["FrameworkScoreTask"]
