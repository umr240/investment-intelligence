"""
APScheduler job registry and daemon runner.
Jobs must be explicitly registered via 'invest scheduler add-job'.
No job auto-starts on import or application launch.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_JOBS_FILE = Path(".ii_jobs.json")


def _load() -> dict[str, Any]:
    if _JOBS_FILE.exists():
        return json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
    return {}


def _save(jobs: dict[str, Any]) -> None:
    _JOBS_FILE.write_text(json.dumps(jobs, indent=2, default=str), encoding="utf-8")


def register_job(name: str, cron: str) -> None:
    """Register a built-in job (quarterly-screener / monthly-signal-refresh / annual-full-rerun)."""
    jobs = _load()
    jobs[name] = {
        "name": name,
        "type": "builtin",
        "cron": cron,
        "registered_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
    }
    _save(jobs)
    logger.info("Job '%s' registered (builtin, cron: %s)", name, cron)


def register_portfolio_reassessment_job(name: str, cron: str) -> None:
    """Phase 5P / DEC-35: register the annual portfolio reassessment job.

    Dives every active PortfolioPosition once a year using ALL frameworks
    + auto-overlays (BEW mandatory per DEC-33, ICA/PSA trigger-gated, SIM
    soft overlay for tech). Compares year-over-year via the same warning
    detector as DEC-34's watchlist checkpoint, and additionally surfaces
    per-position context: years held, DEC-23 reconsideration-window status,
    original thesis (for Lynch story-break comparison).

    Default cron: '0 8 1 3 *' = Mar 1 08:00 (earliest after most 10-K
    filings; portfolio gets reassessed BEFORE watchlist's Mar 15 to keep
    holdings highest-priority).
    """
    jobs = _load()
    jobs[name] = {
        "name": name,
        "type": "portfolio_reassessment",
        "cron": cron,
        "registered_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
    }
    _save(jobs)
    logger.info("Portfolio reassessment '%s' registered (cron=%s)", name, cron)


def register_checkpoint_job(name: str, cron: str) -> None:
    """Phase 5N: register the yearly watchlist checkpoint job (DEC-34).

    Dives every active WatchlistEntry, compares against the prior dive
    ≥ 10 months old, surfaces warning signals (composite drops, verdict
    downgrades, ROIC erosion, BEW band drops). Per the user's hold
    philosophy (forever-default, 5-year minimum reconsideration), warnings
    are SURFACED not actioned — they're flags for the human, not automatic
    exit triggers.

    Recommended cron: '0 8 15 3 *' (Mar 15 08:00, after 10-K season).
    """
    jobs = _load()
    jobs[name] = {
        "name": name,
        "type": "checkpoint",
        "cron": cron,
        "registered_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
    }
    _save(jobs)
    logger.info("Checkpoint '%s' registered (cron=%s)", name, cron)


def register_deepdive_job(
    name: str,
    cron: str,
    tickers: list[str],
    framework_names: list[str] | None = None,
    tier: int = 1,
) -> None:
    """
    Register a recurring deep-dive job.

    framework_names=None  → run ALL 7 (default deep-dive)
    framework_names=['F1', 'F5']  → user-defined narrow dive
    """
    jobs = _load()
    jobs[name] = {
        "name": name,
        "type": "deepdive",
        "cron": cron,
        "tickers": [t.upper() for t in tickers],
        "frameworks": [f.upper() for f in framework_names] if framework_names else None,
        "tier": tier,
        "registered_at": datetime.now().isoformat(),
        "last_run": None,
        "next_run": None,
    }
    _save(jobs)
    logger.info(
        "Deepdive '%s' registered (cron=%s, tickers=%s, frameworks=%s, tier=%d)",
        name, cron, tickers, framework_names or "ALL", tier,
    )


def list_jobs() -> list[dict[str, Any]]:
    return list(_load().values())


def remove_job(name: str) -> None:
    jobs = _load()
    if name in jobs:
        del jobs[name]
        _save(jobs)
        logger.info("Job '%s' removed", name)
    else:
        logger.warning("Job '%s' not found", name)


def start_daemon() -> None:
    """
    Start APScheduler BlockingScheduler with all registered jobs.
    Called only when user explicitly runs 'invest scheduler start'.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    jobs = _load()
    if not jobs:
        print("No jobs registered. Use 'invest scheduler add-job' first.")
        return

    scheduler = BlockingScheduler()
    for name, job_def in jobs.items():
        try:
            trigger = CronTrigger.from_crontab(job_def["cron"])
            scheduler.add_job(
                func=_dispatch,
                trigger=trigger,
                args=[name],
                id=name,
                name=name,
                replace_existing=True,
            )
            print(f"  ✓ {name} [{job_def['cron']}]")
        except Exception as exc:
            logger.error("Failed to register job '%s': %s", name, exc)

    print(f"\nDaemon running with {len(jobs)} job(s). Ctrl+C to stop.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


def _dispatch(name: str) -> None:
    """Dispatch a named job. Runs async jobs via asyncio.run()."""
    logger.info("Dispatching job: %s", name)
    jobs = _load()
    if name in jobs:
        jobs[name]["last_run"] = datetime.now().isoformat()
        _save(jobs)

    job_def = jobs.get(name, {})
    job_type = job_def.get("type", "builtin")

    if job_type == "deepdive":
        asyncio.run(_run_deepdive_job(job_def))
        return

    if job_type == "checkpoint":
        asyncio.run(_run_checkpoint_job(job_def))
        return

    if job_type == "portfolio_reassessment":
        asyncio.run(_run_portfolio_reassessment_job(job_def))
        return

    # Built-in jobs (legacy entry by name — keep working without a 'type' field)
    if name == "quarterly-screener":
        asyncio.run(_quarterly_screener())
    elif name == "monthly-signal-refresh":
        asyncio.run(_monthly_signal_refresh())
    elif name == "annual-full-rerun":
        asyncio.run(_annual_full_rerun())
    elif name in ("screener-stage-A", "screener-stage-B", "screener-stage-C"):
        asyncio.run(_run_screener_stage(name, job_def))
    elif name == "screener-cleanup":
        _run_screener_cleanup()
    elif name in (
        "warehouse-yf-tasks",
        "warehouse-sec-tasks",
        "warehouse-rollup-tasks",
        "polygon-watchlist-tasks",
    ):
        asyncio.run(_run_warehouse_group(name))
    elif name == "winner-screen-monthly":
        _run_winner_screen_monthly()
    else:
        logger.warning("Unknown job name: '%s'. No handler registered.", name)


def _run_winner_screen_monthly() -> None:
    """Monthly Bessembinder-style extreme-winner screen.

    Pipeline (per ADR 2026-05-17 plan):
      1. Refresh stale Fundamentals + FrameworkScores via warehouse rollup
         (handled by the warehouse-sec-tasks + warehouse-rollup-tasks cron
         groups which run on their own monthly cadence — winner-screen
         consumes whatever's fresh in the warehouse at run time).
      2-5. Pre-filter → BEW dive → watchlist promote → markdown export
           (implemented in screener/tasks/winner_screen.py).

    Output: exports/extreme_winner_screen_YYYY-MM-DD.md
    + watchlist entries for passers (role=core for EXTREME, satellite for moderate).

    No LLM calls. No Damodaran IV. Deterministic only.
    """
    from screener.tasks.winner_screen import run_winner_screen
    logger.info("Starting monthly winner-screen…")
    result = run_winner_screen(
        # Partial-or-better F1/F3 + BEW hard filter (moderate/extreme).
        # Catches loss-makers with intangible-capital uplift profile (BFLY case)
        # who'd otherwise miss the strong_fit gate.
        f1_min=4.0, f3_min=4.0,
        auto_watchlist=True,
        force_redive=True,
    )
    logger.info(
        "Winner-screen complete: %d candidates, %d winners (report: %s)",
        result.candidates_pre_filter, result.winners_count, result.report_path,
    )


# ── Staged screener jobs (docs/architecture/SCREENER_PIPELINE.md §4) ─────────────────────


async def _run_screener_stage(name: str, job_def: dict[str, Any]) -> None:
    """
    Dispatch a staged screener job.
      screener-stage-A — universe + Tier 1-3
      screener-stage-B — Tier 4 frames
      screener-stage-C — Tier 5-6 + persist

    Job def carries (optional) `screen_params`. Stage A creates a new
    ScreenerRun row; B and C resume the most-recent INCOMPLETE run for this
    region/mode.
    """
    from data.models.api_models import ScreenerParams
    from screener.stages import (
        create_screener_run,
        run_stage_a,
        run_stage_b,
        run_stage_c,
    )

    stage_letter = name.split("-")[-1].upper()
    params_dict = job_def.get("screen_params") or {}
    mode = job_def.get("mode") or "B"

    params = ScreenerParams(
        region=params_dict.get("region") or "us",
        cap_min=float(params_dict.get("cap_min") or 50_000_000),
        cap_max=float(params_dict.get("cap_max") or 10_000_000_000),
        sector=params_dict.get("sector"),
        exchange=params_dict.get("exchange"),
        exclusion_policy=params_dict.get("exclusion_policy"),
    )
    retention = int(params_dict.get("retention_days") or 30)

    if stage_letter == "A":
        # Only Stage A reads screen_params; B and C resume the run's policy.
        if "ethics_filter" in params_dict:
            # Retired key: running under the default policy would silently
            # screen in what the job excluded.
            raise ValueError(
                f"job {name!r}: screen_params uses the retired key 'ethics_filter'; "
                "rename it to 'exclusion_policy' and give a registered policy name"
            )
        run_id = create_screener_run(params, mode)
        logger.info("Stage A: created ScreenerRun id=%d", run_id)
        await run_stage_a(run_id, params, retention)
    elif stage_letter == "B":
        run_id = _resume_most_recent_run(stage="A")
        if run_id is None:
            logger.warning("Stage B: no completed Stage A to resume — skipping")
            return
        logger.info("Stage B: resuming run_id=%d", run_id)
        await run_stage_b(run_id)
    elif stage_letter == "C":
        run_id = _resume_most_recent_run(stage="B")
        if run_id is None:
            logger.warning("Stage C: no completed Stage B to resume — skipping")
            return
        logger.info("Stage C: resuming run_id=%d", run_id)
        await run_stage_c(run_id, mode)


def _resume_most_recent_run(stage: str) -> int | None:
    """
    Find the most recent ScreenerRun whose given stage completed but where the
    NEXT stage hasn't started. This is the run we should resume.
    """
    from data.db import get_session
    from data.models.schema import ScreenerStage

    next_stage = {"A": "B", "B": "C"}.get(stage)
    with get_session() as session:
        completed = (
            session.query(ScreenerStage.screener_run_id)
            .filter_by(stage=stage, status="completed")
            .order_by(ScreenerStage.completed_at.desc())
            .all()
        )
        for (run_id,) in completed:
            if next_stage is None:
                return run_id
            already_started = (
                session.query(ScreenerStage)
                .filter_by(screener_run_id=run_id, stage=next_stage)
                .first()
            )
            if already_started and already_started.status == "completed":
                continue   # next stage already done, not resumable
            return run_id
    return None


def _run_screener_cleanup() -> None:
    from screener.cleanup import archive_stale_candidates
    report = archive_stale_candidates(dry_run=False)
    logger.info(
        "screener-cleanup: %d archived (%d evaluated, %d protected). "
        "Rows deleted: %s",
        len(report.archived_tickers), report.candidates_evaluated,
        len(report.skipped_protected), report.rows_deleted_by_table,
    )


# ── Warehouse cron groups (Phase 4c, ADR-017 §6) ─────────────────────────


async def _run_warehouse_group(name: str) -> None:
    """Run a named cron group from screener.tasks.registry.CRON_GROUPS.

    Independent of the legacy ``screener-stage-*`` jobs. Each task in the
    group runs through the universal :func:`screener.tasks.runner.run_task`;
    per-task failures don't block the rest of the group.

    The yf group also calls :func:`refresh_universe` first to bootstrap any
    new tickers from SEC's company_tickers_exchange.json before metadata
    fans out across them.
    """
    from data.db import get_session
    from screener.tasks.registry import CRON_GROUPS, get_task
    from screener.tasks.runner import run_task
    from screener.tasks.universe import refresh_universe

    task_names = CRON_GROUPS.get(name)
    if not task_names:
        logger.warning("warehouse group '%s' is empty — nothing to run", name)
        return

    if name == "warehouse-yf-tasks":
        with get_session() as db:
            try:
                summary = refresh_universe(db, region="us")
                logger.info(
                    "[%s] universe refresh: fetched=%d inserted=%d updated=%d in %.2fs",
                    name, summary.fetched, summary.inserted, summary.updated,
                    summary.duration_seconds,
                )
            except Exception as exc:
                logger.exception("[%s] universe refresh failed: %s", name, exc)

    for task_name in task_names:
        with get_session() as db:
            try:
                task = get_task(task_name)
                result = await run_task(task, db)
                logger.info(
                    "[%s] %s: status=%s processed=%d failed=%d duration=%.2fs",
                    name, task_name, result.status, result.processed,
                    result.failed, result.duration_seconds,
                )
            except Exception as exc:
                logger.exception("[%s] %s threw: %s", name, task_name, exc)


async def _run_deepdive_job(job_def: dict[str, Any]) -> None:
    """
    Execute a registered deep-dive job. Fans out across the configured tickers
    using the configured framework set (None → all 7 → IPO-aware feasibility).
    """
    from deepdive.orchestrator import run_tier1, run_tier2

    tickers: list[str] = job_def.get("tickers") or []
    framework_names: list[str] | None = job_def.get("frameworks") or None
    tier: int = int(job_def.get("tier", 1))
    runner = run_tier1 if tier == 1 else run_tier2

    if not tickers:
        logger.warning("deepdive '%s': no tickers configured", job_def.get("name"))
        return

    for ticker in tickers:
        try:
            outcome = await runner(ticker, mode=None, framework_names=framework_names)
            logger.info(
                "deepdive '%s' %s: %d ran, %d unfeasible",
                job_def.get("name"), ticker,
                len(outcome.framework_results), len(outcome.framework_unfeasible),
            )
            for name, reason in outcome.framework_unfeasible.items():
                logger.info("  %s: %s — %s", ticker, name, reason)
        except Exception as exc:    # noqa: BLE001
            logger.error("deepdive '%s' %s failed: %s", job_def.get("name"), ticker, exc)


async def _run_checkpoint_job(job_def: dict[str, Any]) -> None:
    """Phase 5N: yearly checkpoint dive across the active watchlist.

    For each active WatchlistEntry:
      1. Run a fresh tier-1 deep-dive (all 7 frameworks, BEW mandatory)
      2. Compare against the most-recent prior DeepDiveRun ≥ 10 months old
      3. Emit warning signals to the logger as a structured health report

    Warnings are SURFACED, not actioned. Per DEC-23 hold philosophy
    (forever-default, 5-year minimum reconsideration), this is an
    early-warning system, not an exit-trigger system.
    """
    from data.db import get_session
    from data.models.schema import Company, WatchlistEntry
    from deepdive.checkpoint import build_checkpoint_report
    from deepdive.orchestrator import run_tier1

    job_name = job_def.get("name", "checkpoint")
    logger.info("[%s] yearly checkpoint starting", job_name)

    with get_session() as session:
        rows = (
            session.query(WatchlistEntry, Company)
            .join(Company, WatchlistEntry.company_id == Company.id)
            .filter(WatchlistEntry.is_active.is_(True))
            .all()
        )
        tickers = [c.ticker for _, c in rows]

    if not tickers:
        logger.info("[%s] no active watchlist tickers — nothing to check", job_name)
        return

    logger.info("[%s] %d watchlist tickers queued", job_name, len(tickers))

    summary: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            outcome = await run_tier1(ticker, mode=None)
            n_ran = len(outcome.framework_results)
            n_unfeas = len(outcome.framework_unfeasible)
            logger.info(
                "[%s] %s: dive complete (%d ran, %d unfeasible)",
                job_name, ticker, n_ran, n_unfeas,
            )
        except Exception as exc:    # noqa: BLE001
            logger.error("[%s] %s: dive failed — %s", job_name, ticker, exc)
            summary.append({"ticker": ticker, "status": "dive_failed", "error": str(exc)})
            continue

        try:
            report = build_checkpoint_report(ticker)
        except Exception as exc:    # noqa: BLE001
            logger.error("[%s] %s: checkpoint comparison failed — %s", job_name, ticker, exc)
            summary.append({"ticker": ticker, "status": "compare_failed", "error": str(exc)})
            continue

        if report.no_prior:
            logger.info(
                "[%s] %s: no prior dive ≥10 months old — baseline established for next year",
                job_name, ticker,
            )
            summary.append({
                "ticker": ticker, "status": "baseline_only",
                "current_run_id": report.current_run_id,
                "years_since_added": report.years_since_added,
            })
            continue

        if not report.warnings:
            logger.info(
                "[%s] %s: clean — no warning signals (compared run #%d vs #%d)",
                job_name, ticker, report.current_run_id, report.prior_run_id,
            )
            summary.append({
                "ticker": ticker, "status": "clean",
                "current_run_id": report.current_run_id,
                "prior_run_id": report.prior_run_id,
                "warnings": 0,
            })
            continue

        sev_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for w in report.warnings:
            sev_counts[w.severity.value] = sev_counts.get(w.severity.value, 0) + 1
        logger.warning(
            "[%s] %s: %d warning signals (H:%d M:%d L:%d) — review the thesis",
            job_name, ticker, len(report.warnings),
            sev_counts["high"], sev_counts["medium"], sev_counts["low"],
        )
        for w in report.warnings:
            level = logger.warning if w.severity.value == "high" else logger.info
            level("[%s] %s  [%s] %s", job_name, ticker, w.severity.value.upper(), w.message)

        summary.append({
            "ticker": ticker, "status": "warnings",
            "current_run_id": report.current_run_id,
            "prior_run_id": report.prior_run_id,
            "warning_count": len(report.warnings),
            "severity_counts": sev_counts,
        })

    n_clean = sum(1 for s in summary if s.get("status") == "clean")
    n_baseline = sum(1 for s in summary if s.get("status") == "baseline_only")
    n_warn = sum(1 for s in summary if s.get("status") == "warnings")
    n_fail = sum(1 for s in summary if s.get("status") in ("dive_failed", "compare_failed"))
    logger.info(
        "[%s] DONE  watchlist=%d  clean=%d  warnings=%d  baseline=%d  failed=%d",
        job_name, len(tickers), n_clean, n_warn, n_baseline, n_fail,
    )


async def _run_portfolio_reassessment_job(job_def: dict[str, Any]) -> None:
    """Phase 5P / DEC-35: annual reassessment of every active PortfolioPosition.

    For each holding:
      1. Run a fresh tier-1 deep-dive (all 7 frameworks, BEW mandatory,
         SIM if tech-sector). Mental-model latticework is invoked at the
         narrative layer when the user runs ``score-card --narrate``.
      2. Build a warning-signal report comparing to the most-recent prior
         DeepDiveRun ≥ 10 months old (same detector as DEC-34).
      3. Compute DEC-23 hold-window status (years_held, 5yr-window-open status,
         years-until-window-opens).
      4. Log per-position summary including the original `thesis` text from
         PortfolioPosition (Lynch story-break baseline).

    Warnings are SURFACED; no automatic exits. Per DEC-23, even a high-severity
    warning is a checkpoint, not a trigger. The human reviews the logs and
    decides per name.
    """
    from datetime import date as _date

    from data.db import get_session
    from data.models.schema import Company, PortfolioPosition
    from deepdive.checkpoint import build_checkpoint_report
    from deepdive.orchestrator import run_tier1

    job_name = job_def.get("name", "portfolio-reassessment")
    logger.info("[%s] annual portfolio reassessment starting", job_name)

    today = _date.today()
    with get_session() as session:
        positions = (
            session.query(PortfolioPosition, Company)
            .join(Company, PortfolioPosition.company_id == Company.id)
            .filter(PortfolioPosition.is_active.is_(True))
            .order_by(PortfolioPosition.entry_date)
            .all()
        )
        # Snapshot the data we need; SQLAlchemy sessions don't survive the
        # async dive loop cleanly.
        snapshots = [
            {
                "ticker": c.ticker,
                "entry_date": p.entry_date,
                "role": p.role,
                "thesis": p.thesis,
                "shares": p.shares,
                "cost_basis_usd": p.cost_basis_usd,
            }
            for p, c in positions
        ]

    if not snapshots:
        logger.info("[%s] no active portfolio positions — nothing to reassess", job_name)
        return

    logger.info("[%s] %d active positions queued for annual reassessment", job_name, len(snapshots))

    summary: list[dict[str, Any]] = []
    for snap in snapshots:
        ticker = snap["ticker"]
        years_held = (today - snap["entry_date"]).days / 365.25
        d22_status = (
            "reconsideration_window_OPEN"
            if years_held >= 5 else
            f"year_{int(years_held) + 1}_of_5_monitoring"
        )
        logger.info(
            "[%s] %s (held %.1fy, %s, role=%s) — diving…",
            job_name, ticker, years_held, d22_status, snap["role"] or "n/a",
        )

        try:
            outcome = await run_tier1(ticker, mode=None)
            n_ran = len(outcome.framework_results)
            n_unfeas = len(outcome.framework_unfeasible)
            logger.info(
                "[%s] %s: dive complete (%d ran, %d unfeasible)",
                job_name, ticker, n_ran, n_unfeas,
            )
        except Exception as exc:    # noqa: BLE001
            logger.error("[%s] %s: dive failed — %s", job_name, ticker, exc)
            summary.append({
                "ticker": ticker, "status": "dive_failed",
                "years_held": years_held, "error": str(exc),
            })
            continue

        try:
            report = build_checkpoint_report(ticker)
        except Exception as exc:    # noqa: BLE001
            logger.error("[%s] %s: warning detection failed — %s", job_name, ticker, exc)
            summary.append({
                "ticker": ticker, "status": "compare_failed",
                "years_held": years_held, "error": str(exc),
            })
            continue

        if report.no_prior:
            logger.info(
                "[%s] %s: baseline year (no ≥10mo prior dive) — DEC-23=%s",
                job_name, ticker, d22_status,
            )
            summary.append({
                "ticker": ticker, "status": "baseline_only",
                "years_held": years_held, "d22_status": d22_status,
            })
            continue

        if not report.warnings:
            logger.info(
                "[%s] %s: CLEAN — no warning signals year-over-year. "
                "DEC-23=%s. Thesis baseline preserved.",
                job_name, ticker, d22_status,
            )
            summary.append({
                "ticker": ticker, "status": "clean",
                "years_held": years_held, "d22_status": d22_status,
                "warnings": 0,
            })
            continue

        sev_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for w in report.warnings:
            sev_counts[w.severity.value] = sev_counts.get(w.severity.value, 0) + 1
        logger.warning(
            "[%s] %s: %d warning signals (H:%d M:%d L:%d)  "
            "DEC-23=%s  years_held=%.1f",
            job_name, ticker, len(report.warnings),
            sev_counts["high"], sev_counts["medium"], sev_counts["low"],
            d22_status, years_held,
        )
        if snap["thesis"]:
            logger.info(
                "[%s] %s: original thesis (compare for Lynch story-break): %s",
                job_name, ticker,
                snap["thesis"][:300] + ("…" if len(snap["thesis"]) > 300 else ""),
            )
        for w in report.warnings:
            level = logger.warning if w.severity.value == "high" else logger.info
            level("[%s] %s  [%s] %s", job_name, ticker, w.severity.value.upper(), w.message)
        summary.append({
            "ticker": ticker, "status": "warnings",
            "years_held": years_held, "d22_status": d22_status,
            "warning_count": len(report.warnings),
            "severity_counts": sev_counts,
        })

    n_clean = sum(1 for s in summary if s.get("status") == "clean")
    n_baseline = sum(1 for s in summary if s.get("status") == "baseline_only")
    n_warn = sum(1 for s in summary if s.get("status") == "warnings")
    n_fail = sum(1 for s in summary if s.get("status") in ("dive_failed", "compare_failed"))
    logger.info(
        "[%s] DONE  portfolio=%d  clean=%d  warnings=%d  baseline=%d  failed=%d",
        job_name, len(snapshots), n_clean, n_warn, n_baseline, n_fail,
    )


async def _quarterly_screener() -> None:
    """
    Refresh fundamentals for all active watchlist tickers, then re-run screener.
    Fires: mid-Feb, mid-May, mid-Aug, mid-Nov (post quarterly filings).
    Cron: '0 9 15 */3 *'
    Phase 3: screener pipeline not yet implemented — refreshes data only.
    """
    from data.db import get_session
    from data.models.schema import Company, WatchlistEntry
    from data.pipeline import refresh_ticker

    logger.info("quarterly-screener: starting data refresh for watchlist tickers")
    with get_session() as session:
        entries = (
            session.query(WatchlistEntry)
            .join(Company)
            .filter(WatchlistEntry.is_active.is_(True))
            .all()
        )
        tickers = [
            session.query(Company).filter_by(id=e.company_id).first().ticker
            for e in entries
        ]

    if not tickers:
        logger.info("quarterly-screener: no active watchlist tickers — nothing to refresh")
        return

    all_gaps: dict[str, list[str]] = {}
    for ticker in tickers:
        try:
            gaps = await refresh_ticker(ticker)
            all_gaps[ticker] = gaps
            if gaps:
                logger.warning("%s: %d data gaps: %s", ticker, len(gaps), gaps)
            else:
                logger.info("%s: refreshed successfully", ticker)
        except Exception as exc:
            all_gaps[ticker] = [str(exc)]
            logger.error("%s: refresh failed — %s", ticker, exc)

    logger.info(
        "quarterly-screener: data refresh complete. %d tickers. Screener pipeline pending Phase 3.",
        len(tickers),
    )
    # TODO Phase 3: call run_screener() here with last saved params


async def _monthly_signal_refresh() -> None:
    """
    Refresh short interest + 13F holder counts for watchlist tickers only.
    No re-scoring. Cron: '0 8 1 * *'
    """
    from data.pipeline import refresh_watchlist_signals
    gaps = await refresh_watchlist_signals()
    total_gaps = sum(len(v) for v in gaps.values())
    logger.info(
        "monthly-signal-refresh complete. %d tickers, %d gaps.",
        len(gaps), total_gaps,
    )
    if total_gaps:
        for ticker, ticker_gaps in gaps.items():
            for gap in ticker_gaps:
                logger.warning("%s: %s", ticker, gap)


async def _annual_full_rerun() -> None:
    """
    Refresh fundamentals from EDGAR 10-K for all watchlist tickers.
    Fires: mid-March (post 10-K filing season). Cron: '0 9 15 3 *'
    """
    from data.db import get_session
    from data.models.schema import Company, WatchlistEntry
    from data.pipeline import refresh_ticker

    logger.info("annual-full-rerun: refreshing annual fundamentals from EDGAR 10-K")
    with get_session() as session:
        entries = (
            session.query(WatchlistEntry)
            .join(Company)
            .filter(WatchlistEntry.is_active.is_(True))
            .all()
        )
        tickers = [
            session.query(Company).filter_by(id=e.company_id).first().ticker
            for e in entries
        ]

    for ticker in tickers:
        try:
            gaps = await refresh_ticker(ticker, force_refresh=True)
            logger.info("%s: annual refresh complete. Gaps: %s", ticker, gaps)
        except Exception as exc:
            logger.error("%s: annual refresh failed — %s", ticker, exc)

    logger.info("annual-full-rerun: complete for %d tickers", len(tickers))
