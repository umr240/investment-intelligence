"""Monthly Bessembinder-style extreme-winner screen across the universe.

Per user direction 2026-05-17. Builds a ranked list of tickers passing:
  - F1 (Pre-Discovery Alpha)     score >= 7.0 (strong_fit)
  - F3 (Innovation Compounder)    score >= 7.0 (strong_fit)
  - BEW overlay verdict in {extreme_winner_candidate, moderate_winner_candidate}

Pipeline (5 phases):
  1. Refresh stale Fundamentals + FrameworkScore data (deterministic, no LLM)
  2. SQL pre-filter for F1+F3 strong_fit candidates
  3. Run Tier 2 dive on each candidate (deterministic, --auto-overlays)
  4. Filter by BEW verdict from overlays_results_json
  5. Write markdown report + auto-add passers to watchlist

No narrative LLM calls. No Damodaran IV computation.
Cost: $0. Wall-clock: ~5 hours universe-scope.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from data.db import get_session
from data.models.schema import (
    Company,
    DeepDiveRun,
    Financial,
    FrameworkScore,
    WatchlistEntry,
)

logger = logging.getLogger(__name__)

# Filter thresholds (user revision 2026-05-17: partial pass works for F1/F3;
# BEW is the HARD filter — moderate or extreme only). The earlier "strong_fit"
# (≥7.0) threshold was too tight — it missed loss-making companies on the
# verge of extreme-winner profile (the BFLY case). Lower-bound 4.0 admits
# "partial" verdicts: companies where the signal is present but not perfect.
F1_PARTIAL_MIN: float = 4.0
F3_PARTIAL_MIN: float = 4.0

# Legacy strong_fit thresholds (kept for tighter sub-screens if needed)
F1_STRONG_FIT_MIN: float = 7.0
F3_STRONG_FIT_MIN: float = 7.0

# Accepted BEW verdicts (HARD filter — user direction 2026-05-17:
# "BEW overlay has hard filter (moderate to extreme winners)").
# BEW is what actually qualifies a winner; F1/F3 are confirmatory.
ACCEPTED_BEW_VERDICTS: frozenset[str] = frozenset({
    "extreme_winner_candidate",
    "moderate_winner_candidate",
})


@dataclass
class WinnerCandidate:
    """One ticker that passed pre-filter and got a BEW dive."""
    ticker: str
    name: str
    market_cap_usd: float | None
    sector: str | None
    industry: str | None
    f1_score: float | None
    f3_score: float | None
    framework_composite: float | None
    bew_verdict: str | None = None
    bew_score: int | None = None
    bew_n_checks: int | None = None
    bew_passes: bool = False
    # ICA upward-gap flag (BFLY-style loss-maker bypass — catches tickers
    # where GAAP looks bad but Peters-Taylor intangible-capital restatement
    # reveals real economic productivity). Set when ICA-5 fired with
    # upward direction (PT-ROIC > GAAP-ROIC).
    ica5_upward_gap: bool = False
    # Path that admitted this candidate to the screen:
    #   "f1f3"      — passed F1 partial AND F3 partial (standard)
    #   "lossmaker" — failed F1 but F3 partial + ICA-5 upward (BFLY bypass)
    admit_path: str = "f1f3"
    dive_run_id: int | None = None
    composite_score: float | None = None
    dive_verdict: str | None = None
    error: str | None = None


@dataclass
class ScreenResult:
    """Summary of one monthly screen run."""
    run_date: date
    universe_size: int
    candidates_pre_filter: int
    candidates_dived: int
    winners_count: int
    winners: list[WinnerCandidate] = field(default_factory=list)
    report_path: str | None = None
    duration_seconds: float | None = None


# ── Phase 2: SQL pre-filter ───────────────────────────────────────────────


def _latest_framework_score_per_company_subquery():
    """Subquery returning the latest run_date per company_id."""
    return (
        select(
            FrameworkScore.company_id,
            func.max(FrameworkScore.run_date).label("max_date"),
        )
        .group_by(FrameworkScore.company_id)
        .subquery()
    )


def find_f1_f3_candidates(
    session: Session,
    f1_min: float = F1_PARTIAL_MIN,
    f3_min: float = F3_PARTIAL_MIN,
    sample_limit: int | None = None,
) -> list[WinnerCandidate]:
    """Path A — SQL pre-filter for F1+F3 (partial-or-better) candidates.

    Uses latest FrameworkScore per company. Skips archived companies.
    Returns WinnerCandidate stubs (BEW fields not yet populated).

    Combined with find_lossmaker_bypass_candidates() in run_winner_screen
    to widen the funnel for BFLY-style loss-makers.
    """
    latest = _latest_framework_score_per_company_subquery()
    stmt = (
        select(
            Company.ticker,
            Company.name,
            Company.market_cap_usd,
            Company.sector,
            Company.industry,
            FrameworkScore.f1_score,
            FrameworkScore.f3_score,
            FrameworkScore.composite_score,
        )
        .join(FrameworkScore, FrameworkScore.company_id == Company.id)
        .join(
            latest,
            and_(
                latest.c.company_id == FrameworkScore.company_id,
                latest.c.max_date == FrameworkScore.run_date,
            ),
        )
        .where(FrameworkScore.f1_score >= f1_min)
        .where(FrameworkScore.f3_score >= f3_min)
        .where(Company.status != "archived")
        .order_by(FrameworkScore.composite_score.desc())
        .distinct()
    )
    if sample_limit:
        stmt = stmt.limit(sample_limit)

    seen: set[str] = set()
    candidates: list[WinnerCandidate] = []
    for row in session.execute(stmt).all():
        if row.ticker in seen:
            continue
        seen.add(row.ticker)
        candidates.append(
            WinnerCandidate(
                ticker=row.ticker,
                name=row.name or row.ticker,
                market_cap_usd=row.market_cap_usd,
                sector=row.sector,
                industry=row.industry,
                f1_score=row.f1_score,
                f3_score=row.f3_score,
                framework_composite=row.composite_score,
                admit_path="f1f3",
            )
        )
    return candidates


def find_lossmaker_bypass_candidates(
    session: Session,
    f3_min: float = F3_PARTIAL_MIN,
    sample_limit: int | None = None,
) -> list[WinnerCandidate]:
    """Path B — Loss-maker bypass: catches tickers that FAIL F1 (Piotroski
    thin due to GAAP losses) but have:
      - F3 partial-or-better (innovation compounder signal alive)
      - Most-recent DeepDiveRun had ICA-5 fire with UPWARD direction
        (Peters-Taylor non-GAAP ROIC > GAAP ROIC; intangible capital is
        making the GAAP picture worse than economic reality)

    This is the BFLY archetype: GAAP loss-maker, R&D-heavy, BEW extreme
    candidate. F1's Piotroski-driven gate kicks them out under Path A —
    Path B rescues them.

    Returns the F1-failing subset only (Path A would already have caught
    those passing F1). The screen merges results and tags each candidate's
    `admit_path` so the report distinguishes Path A from Path B.
    """
    import json as _json

    latest = _latest_framework_score_per_company_subquery()

    # Pull all F3-passing candidates regardless of F1, then filter in Python
    # for ICA-5 upward (the JSON inspection is too gnarly for SQL).
    stmt = (
        select(
            Company.id,
            Company.ticker,
            Company.name,
            Company.market_cap_usd,
            Company.sector,
            Company.industry,
            FrameworkScore.f1_score,
            FrameworkScore.f3_score,
            FrameworkScore.composite_score,
        )
        .join(FrameworkScore, FrameworkScore.company_id == Company.id)
        .join(
            latest,
            and_(
                latest.c.company_id == FrameworkScore.company_id,
                latest.c.max_date == FrameworkScore.run_date,
            ),
        )
        .where(FrameworkScore.f3_score >= f3_min)
        .where(FrameworkScore.f1_score < F1_PARTIAL_MIN)  # Path B is F1-fail-only
        .where(Company.status != "archived")
        .order_by(FrameworkScore.composite_score.desc())
        .distinct()
    )
    if sample_limit:
        stmt = stmt.limit(sample_limit * 3)  # over-fetch since we'll filter further

    seen: set[str] = set()
    candidates: list[WinnerCandidate] = []
    for row in session.execute(stmt).all():
        if row.ticker in seen:
            continue
        seen.add(row.ticker)

        # ICA-5 upward check from latest DeepDiveRun
        run = session.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.ticker == row.ticker.upper())
            .order_by(desc(DeepDiveRun.run_date))
            .limit(1)
        ).scalar_one_or_none()
        ica5_upward = False
        if run and run.overlays_triggered_json:
            try:
                triggers = _json.loads(run.overlays_triggered_json)
                for t in triggers:
                    if (
                        t.get("trigger_id") == "ICA-5"
                        and "upward" in (t.get("trigger_condition") or "").lower()
                    ):
                        ica5_upward = True
                        break
            except (_json.JSONDecodeError, TypeError):
                pass
        if not ica5_upward:
            continue

        candidates.append(
            WinnerCandidate(
                ticker=row.ticker,
                name=row.name or row.ticker,
                market_cap_usd=row.market_cap_usd,
                sector=row.sector,
                industry=row.industry,
                f1_score=row.f1_score,
                f3_score=row.f3_score,
                framework_composite=row.composite_score,
                ica5_upward_gap=True,
                admit_path="lossmaker",
            )
        )
        if sample_limit and len(candidates) >= sample_limit:
            break
    return candidates


# ── Phase 3: BEW dive on each candidate ───────────────────────────────────


def _read_bew_from_latest_dive(session: Session, ticker: str) -> dict | None:
    """Read BEW result from the most-recent DeepDiveRun for a ticker.

    Returns the BEW dict (with verdict, score, n_checks_evaluable) or None
    if no dive exists OR overlays_results_json is empty.
    """
    run = session.execute(
        select(DeepDiveRun)
        .where(DeepDiveRun.ticker == ticker.upper())
        .order_by(desc(DeepDiveRun.run_date))
        .limit(1)
    ).scalar_one_or_none()
    if run is None or not run.overlays_results_json:
        return None
    try:
        results = json.loads(run.overlays_results_json)
    except (json.JSONDecodeError, TypeError):
        return None
    bew = results.get("BEW")
    if not isinstance(bew, dict) or not bew.get("ok"):
        return None
    return bew


def _run_dive_for_bew(ticker: str, timeout_sec: int = 180) -> tuple[bool, str | None]:
    """Run `invest dive <ticker> --tier 2 --force --auto-overlays` synchronously.

    Returns (success, error_msg). On success, the DeepDiveRun row is
    persisted with overlays_results_json containing BEW.
    """
    cmd = [
        "uv", "run", "invest", "dive", ticker,
        "--tier", "2", "--force", "--auto-overlays",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout_sec,
        )
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")[:200]
            return False, f"dive exit {result.returncode}: {err}"
        return True, None
    except subprocess.TimeoutExpired:
        return False, f"dive timed out after {timeout_sec}s"
    except FileNotFoundError as exc:
        return False, f"invest CLI not found: {exc}"


def enrich_with_persisted_bew(
    session: Session,
    candidates: list[WinnerCandidate],
) -> list[WinnerCandidate]:
    """Phase 3 (warehouse path) — read BEW verdict from `companies.bew_verdict`.

    Populated by BEWOverlayTask running as part of the warehouse-rollup-tasks
    cron group. Skips the dive entirely. Tickers without persisted BEW get
    `cand.error` set so the report flags them as un-evaluated.
    """
    if not candidates:
        return candidates
    tickers = [c.ticker.upper() for c in candidates]
    rows = session.execute(
        select(
            Company.ticker, Company.bew_verdict, Company.bew_score,
            Company.bew_n_checks, Company.bew_scored_at,
        ).where(Company.ticker.in_(tickers))
    ).all()
    by_ticker = {r.ticker.upper(): r for r in rows}

    for cand in candidates:
        row = by_ticker.get(cand.ticker.upper())
        if row is None or row.bew_scored_at is None:
            cand.error = "no persisted BEW verdict (bew_overlay task hasn't run yet)"
            continue
        cand.bew_verdict = (row.bew_verdict or "").lower() or None
        cand.bew_score = row.bew_score
        cand.bew_n_checks = row.bew_n_checks
        cand.bew_passes = cand.bew_verdict in ACCEPTED_BEW_VERDICTS

        # Also pull the latest dive_run_id + composite_score if a dive exists
        # (informational only — not required for verdict).
        run = session.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.ticker == cand.ticker.upper())
            .order_by(desc(DeepDiveRun.run_date))
            .limit(1)
        ).scalar_one_or_none()
        if run is not None:
            cand.dive_run_id = run.id
            cand.composite_score = run.composite_score
            cand.dive_verdict = run.verdict

    return candidates


def enrich_with_bew(
    session: Session,
    candidates: list[WinnerCandidate],
    force_redive: bool = True,
    progress_every: int = 5,
) -> list[WinnerCandidate]:
    """For each candidate, run a Tier 2 dive (if needed) and extract BEW.

    Sets `bew_*` fields + `bew_passes` flag based on ACCEPTED_BEW_VERDICTS.
    Records dive_run_id, composite_score, dive_verdict for the report.
    """
    n = len(candidates)
    for i, cand in enumerate(candidates, 1):
        if i % progress_every == 0 or i == n:
            logger.info(f"  BEW dive {i}/{n}: {cand.ticker}")

        if force_redive:
            ok, err = _run_dive_for_bew(cand.ticker)
            if not ok:
                cand.error = err
                continue

        bew = _read_bew_from_latest_dive(session, cand.ticker)
        if bew is None:
            cand.error = "no BEW result in latest DeepDiveRun"
            continue

        # Normalize case (BFLY uses EXTREME_WINNER_CANDIDATE all-caps;
        # ILMN/TEM/etc use moderate_winner_candidate lowercase — overlay
        # code inconsistency, handle in filter).
        raw_verdict = bew.get("verdict") or ""
        cand.bew_verdict = raw_verdict.lower() if raw_verdict else None
        cand.bew_score = bew.get("score")
        cand.bew_n_checks = bew.get("n_checks_evaluable")
        cand.bew_passes = cand.bew_verdict in ACCEPTED_BEW_VERDICTS

        # Pull composite + verdict from the dive run we just inspected
        run = session.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.ticker == cand.ticker.upper())
            .order_by(desc(DeepDiveRun.run_date))
            .limit(1)
        ).scalar_one_or_none()
        if run is not None:
            cand.dive_run_id = run.id
            cand.composite_score = run.composite_score
            cand.dive_verdict = run.verdict

    return candidates


# ── Phase 4 + 5: Report + Watchlist ───────────────────────────────────────


def write_markdown_report(
    output_path: Path,
    result: ScreenResult,
    f1_min: float = F1_STRONG_FIT_MIN,
    f3_min: float = F3_STRONG_FIT_MIN,
) -> None:
    """Write a markdown report of screen results."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    winners = [c for c in result.winners if c.bew_passes]
    extreme = [c for c in winners if c.bew_verdict == "extreme_winner_candidate"]
    moderate = [c for c in winners if c.bew_verdict == "moderate_winner_candidate"]

    lines: list[str] = []
    lines.append(f"# Extreme-Winner Screen — {result.run_date.isoformat()}")
    lines.append("")
    lines.append(f"**{len(winners)} winners** found across {result.universe_size:,} universe tickers.")
    lines.append("")
    lines.append(f"- {len(extreme)} **EXTREME** (BEW 6/6)")
    lines.append(f"- {len(moderate)} moderate_winner_candidate")
    lines.append("")
    lines.append(f"## Methodology")
    lines.append("")
    band = "strong_fit-only" if f1_min >= 7.0 else "partial-or-better"
    lines.append(f"**Path A — Standard**: F1 ≥ {f1_min} AND F3 ≥ {f3_min} ({band}) AND BEW ∈ {{extreme, moderate}}")
    lines.append("")
    lines.append(
        f"**Path B — Loss-maker bypass**: F3 ≥ {f3_min} ({band}) AND F1 < {F1_PARTIAL_MIN} "
        f"AND ICA-5 fired UPWARD AND BEW ∈ {{extreme, moderate}}. Catches BFLY-style "
        f"profiles where GAAP is thin (Piotroski-driven F1 fail) but Peters-Taylor "
        f"intangible-capital restatement reveals real economic productivity."
    )
    lines.append("")
    lines.append(
        f"Pipeline: SQL pre-filter ({result.candidates_pre_filter} candidates) → "
        f"Tier-2 dive ({result.candidates_dived} run) → BEW verdict filter ({len(winners)} pass)"
    )
    if result.duration_seconds:
        lines.append(f"Run duration: {result.duration_seconds:.1f}s")
    lines.append("")

    if winners:
        lines.append("## Winners (ranked by BEW verdict then composite)")
        lines.append("")
        lines.append("| Rank | Path | Ticker | Name | Cap | F1 | F3 | BEW | Composite | Verdict |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        sorted_winners = sorted(
            winners,
            key=lambda c: (
                c.bew_verdict == "extreme_winner_candidate",
                c.composite_score or 0,
                (c.f1_score or 0) + (c.f3_score or 0),
            ),
            reverse=True,
        )
        for rank, c in enumerate(sorted_winners, 1):
            cap = f"${c.market_cap_usd / 1e9:.1f}B" if c.market_cap_usd else "—"
            bew_str = f"{c.bew_score}/{c.bew_n_checks}" if c.bew_score is not None else "—"
            bew_label = "EXTREME" if c.bew_verdict == "extreme_winner_candidate" else "moderate"
            comp = f"{c.composite_score:.2f}" if c.composite_score is not None else "—"
            verdict = c.dive_verdict or "—"
            path = "🔄 LM" if c.admit_path == "lossmaker" else "A"
            f1_str = f"{c.f1_score:.1f}" if c.f1_score is not None else "—"
            f3_str = f"{c.f3_score:.1f}" if c.f3_score is not None else "—"
            lines.append(
                f"| {rank} | {path} | **{c.ticker}** | {c.name[:35]} | {cap} | "
                f"{f1_str} | {f3_str} | {bew_str} {bew_label} | {comp} | {verdict} |"
            )
        lines.append("")
        lines.append("*Path A = F1+F3 partial; LM = Loss-maker bypass (BFLY profile — F1 fails, F3 strong, ICA-5 upward).*")
        lines.append("")

    # Errors / unable-to-evaluate section
    errors = [c for c in result.winners if c.error]
    if errors:
        lines.append("## Errors / Unable to evaluate")
        lines.append("")
        for c in errors:
            lines.append(f"- **{c.ticker}**: {c.error}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Generated by `invest screen winners`. No LLM calls. Source: SEC EDGAR + deterministic frameworks.*")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote {output_path} ({len(winners)} winners)")


def add_winners_to_watchlist(
    session: Session,
    winners: list[WinnerCandidate],
    reason_prefix: str = "winner_screen",
    retention_days: int = 60,
) -> int:
    """Auto-add winners to watchlist. Idempotent — updates `notes` if entry exists.

    WatchlistEntry schema (from data/models/schema.py:896):
      company_id, added_date, entry_triggers (JSON), stop_loss_note,
      role ('core' / 'satellite' / 'monitor'), notes, is_active.

    For winners we set:
      role = 'satellite' for moderate_winner_candidate (BEW concentration note
                          says "Moderate evidence; consider as a satellite position"),
             'core' for extreme_winner_candidate.
      entry_triggers = JSON list of grounded signals (F1, F3, BEW verdict).
      notes = human-readable reason string.

    Returns count of entries added/updated.
    """
    today = date.today()
    count = 0
    for c in winners:
        if not c.bew_passes:
            continue
        company = session.execute(
            select(Company).where(Company.ticker == c.ticker.upper())
        ).scalar_one_or_none()
        if company is None:
            continue

        role = "core" if c.bew_verdict == "extreme_winner_candidate" else "satellite"
        triggers = [
            f"F1={c.f1_score:.1f} (strong_fit)",
            f"F3={c.f3_score:.1f} (strong_fit)",
            f"BEW={c.bew_score}/{c.bew_n_checks} {c.bew_verdict}",
        ]
        notes = (
            f"{reason_prefix} {today.isoformat()}: "
            f"F1={c.f1_score:.1f} F3={c.f3_score:.1f} "
            f"BEW={c.bew_score}/{c.bew_n_checks} ({c.bew_verdict})"
        )

        existing = session.execute(
            select(WatchlistEntry).where(WatchlistEntry.company_id == company.id)
        ).scalar_one_or_none()
        if existing is None:
            entry = WatchlistEntry(
                company_id=company.id,
                added_date=today,
                entry_triggers=json.dumps(triggers),
                role=role,
                notes=notes,
                is_active=True,
            )
            session.add(entry)
        else:
            existing.notes = notes
            existing.entry_triggers = json.dumps(triggers)
            existing.role = role
            existing.is_active = True
        # Also bump company.status to 'watchlist' + extend retention
        if company.status != "watchlist":
            company.status = "watchlist"
        company.retention_days = max(company.retention_days or 30, retention_days)
        count += 1
    session.commit()
    return count


# ── Top-level orchestrator ────────────────────────────────────────────────


def run_winner_screen(
    f1_min: float = F1_PARTIAL_MIN,
    f3_min: float = F3_PARTIAL_MIN,
    sample_limit: int | None = None,
    auto_watchlist: bool = True,
    output_dir: Path | None = None,
    force_redive: bool = True,
    use_persisted_bew: bool = False,
) -> ScreenResult:
    """Run the monthly extreme-winner screen.

    Synchronous orchestrator over the 5-phase pipeline. Caller is responsible
    for refreshing fundamentals + framework scores universe-wide BEFORE this
    runs (use the existing FundamentalsTask + FrameworkScoreTask cron jobs).

    Args:
        f1_min, f3_min: pre-filter thresholds
        sample_limit: if set, only process top N candidates from pre-filter
            (used for fast validation runs)
        auto_watchlist: if True, promote passing tickers to watchlist status
        output_dir: directory to write markdown report (default: exports/)
        force_redive: re-run `invest dive` on each candidate even if a recent
            DeepDiveRun exists. Recommended for monthly runs to capture
            latest 10-K filings.
    """
    start = datetime.now(UTC)
    today = start.date()
    out_dir = output_dir or Path("exports")

    print(f"=== Winner Screen — {today.isoformat()} ===")

    with get_session() as s:
        # Phase 2: SQL pre-filter — DUAL-PATH funnel
        # Path A: F1+F3 partial pass (standard screen)
        # Path B: F3 partial AND F1-fail BUT ICA-5 upward fired
        #         (BFLY-style loss-maker bypass — Peters-Taylor reveals
        #          intangible-capital uplift hidden by GAAP loss optics)
        print(f"Phase 2A: SQL pre-filter (F1>={f1_min}, F3>={f3_min})")
        path_a = find_f1_f3_candidates(
            s, f1_min=f1_min, f3_min=f3_min, sample_limit=sample_limit,
        )
        print(f"  → {len(path_a)} F1+F3 candidates (Path A)")

        print(f"Phase 2B: Loss-maker bypass (F3>={f3_min} AND F1-fail AND ICA-5 upward)")
        path_b = find_lossmaker_bypass_candidates(
            s, f3_min=f3_min, sample_limit=sample_limit,
        )
        print(f"  → {len(path_b)} loss-maker candidates (Path B)")

        # Combine — dedup by ticker (Path A wins if both)
        seen = {c.ticker for c in path_a}
        candidates = list(path_a) + [c for c in path_b if c.ticker not in seen]
        print(f"  → {len(candidates)} total unique candidates")

        if not candidates:
            duration = (datetime.now(UTC) - start).total_seconds()
            universe = s.execute(
                select(func.count(Company.id))
                .where(Company.status != "archived")
            ).scalar() or 0
            result = ScreenResult(
                run_date=today,
                universe_size=universe,
                candidates_pre_filter=0,
                candidates_dived=0,
                winners_count=0,
                winners=[],
                duration_seconds=duration,
            )
            report_path = out_dir / f"extreme_winner_screen_{today.isoformat()}.md"
            write_markdown_report(report_path, result, f1_min=f1_min, f3_min=f3_min)
            result.report_path = str(report_path)
            return result

        # Phase 3: BEW enrichment — either read persisted warehouse rollup OR
        # run the per-ticker dive. Persisted path (BEWOverlayTask) is the
        # default for universe-scale runs; dive path is for ad-hoc cases.
        if use_persisted_bew:
            print(f"Phase 3: read persisted BEW for {len(candidates)} candidates (warehouse rollup)")
            candidates = enrich_with_persisted_bew(s, candidates)
        else:
            print(f"Phase 3: BEW dive on {len(candidates)} candidates (force_redive={force_redive})")
            candidates = enrich_with_bew(s, candidates, force_redive=force_redive)

        # Phase 4: Filter passers
        winners = [c for c in candidates if c.bew_passes]
        print(f"  → {len(winners)} pass BEW verdict filter")

        # Phase 5a: Watchlist promotion
        if auto_watchlist and winners:
            count = add_winners_to_watchlist(s, winners)
            print(f"  → {count} added/updated in watchlist")

        # Phase 5b: Markdown report
        universe = s.execute(
            select(func.count(Company.id))
            .where(Company.status != "archived")
        ).scalar() or 0
        duration = (datetime.now(UTC) - start).total_seconds()
        result = ScreenResult(
            run_date=today,
            universe_size=universe,
            candidates_pre_filter=len(candidates),
            candidates_dived=len(candidates),
            winners_count=len(winners),
            winners=candidates,    # full list (with bew_passes flag on each)
            duration_seconds=duration,
        )
        report_path = out_dir / f"extreme_winner_screen_{today.isoformat()}.md"
        write_markdown_report(report_path, result, f1_min=f1_min, f3_min=f3_min)
        result.report_path = str(report_path)
        print(f"\nReport written: {report_path}")
        return result


__all__ = [
    "F1_STRONG_FIT_MIN",
    "F3_STRONG_FIT_MIN",
    "ACCEPTED_BEW_VERDICTS",
    "WinnerCandidate",
    "ScreenResult",
    "find_f1_f3_candidates",
    "enrich_with_bew",
    "write_markdown_report",
    "add_winners_to_watchlist",
    "run_winner_screen",
]
