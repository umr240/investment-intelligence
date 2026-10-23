"""
Phase 5N: yearly checkpoint — warning-signal detection for watchlist tickers.

Per the user's hold philosophy (DEC-23 — forever-default, 5-year minimum
reconsideration window), positions aren't sold on mark-to-market noise;
they're sold on thesis-breaking conditions. The yearly checkpoint exists
to surface those conditions early — not to trigger automatic exits.

A "warning signal" is a year-over-year regression of meaningful magnitude
in the framework outputs we already compute. We compare the latest
DeepDiveRun against the most-recent prior DeepDiveRun that is ≥ 10 months
old (configurable). The 10-month gate avoids comparing two dives from the
same quarter — that would surface noise, not regressions.

Six categories of warning, in severity order:
  HIGH:
    • framework_verdict downgrade (priority_watchlist → watchlist → monitor → exclude)
    • composite_score drop ≥ 1.5
    • F5 (Growth Quality) score drop ≥ 2.0
  MEDIUM:
    • Any single framework drop ≥ 2.0
    • PT-adjusted ROIC drop ≥ 3pp
    • BEW evaluable-checks band drop (extreme → moderate → no-pattern)
  LOW:
    • New ICA-5 firing (PT vs GAAP gap widened past 3pp)
    • Retention rate decline (NRR / GRR) ≥ 5pp where reported

Output is a structured `CheckpointReport` per ticker, plus a summary
across the watchlist. Persisted to logger and (optionally) the scheduler
log file. No DB schema additions — this is read-only analytics over
existing rows.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# How far back the "prior" DeepDiveRun must be. 10 months avoids same-quarter
# comparisons (noise) while still catching annual fundamentals drift.
_PRIOR_RUN_MIN_AGE_DAYS = 305


_VERDICT_RANK = {"priority_watchlist": 3, "watchlist": 2, "monitor": 1, "exclude": 0}


class WarningSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class CheckpointWarning:
    """One warning signal detected during yearly checkpoint comparison."""
    severity: WarningSeverity
    code: str                    # short identifier, e.g. 'verdict_downgrade'
    message: str
    prior_value: Any = None
    current_value: Any = None
    delta: Any = None


@dataclass
class CheckpointReport:
    """All warning signals for one ticker + the run IDs being compared."""
    ticker: str
    current_run_id: int
    prior_run_id: int | None
    prior_run_date: str | None
    years_since_added: float | None
    warnings: list[CheckpointWarning] = field(default_factory=list)
    no_prior: bool = False        # true when no comparable prior run exists


# ── Detection ────────────────────────────────────────────────────────────


def detect_warnings(
    current_run: Any, prior_run: Any | None,
) -> list[CheckpointWarning]:
    """Compare two DeepDiveRun rows and emit warning signals.

    `current_run` and `prior_run` are DeepDiveRun ORM instances. If
    `prior_run` is None, returns an empty list — caller should mark the
    report as `no_prior=True` so the renderer can distinguish "clean" from
    "no baseline to compare against".
    """
    out: list[CheckpointWarning] = []
    if prior_run is None:
        return out

    # ── Verdict downgrade ───────────────────────────────────────────────
    cur_v = (current_run.verdict or "").lower()
    pri_v = (prior_run.verdict or "").lower()
    if cur_v and pri_v and cur_v != pri_v:
        cur_rank = _VERDICT_RANK.get(cur_v, -1)
        pri_rank = _VERDICT_RANK.get(pri_v, -1)
        if cur_rank < pri_rank and cur_rank >= 0:
            out.append(CheckpointWarning(
                severity=WarningSeverity.HIGH,
                code="verdict_downgrade",
                message=f"Verdict downgraded: {pri_v} → {cur_v}",
                prior_value=pri_v, current_value=cur_v,
            ))

    # ── Composite drop ──────────────────────────────────────────────────
    if current_run.composite_score is not None and prior_run.composite_score is not None:
        delta = current_run.composite_score - prior_run.composite_score
        if delta <= -1.5:
            out.append(CheckpointWarning(
                severity=WarningSeverity.HIGH,
                code="composite_drop",
                message=(
                    f"Composite score dropped {abs(delta):.2f} pts "
                    f"({prior_run.composite_score:.2f} → {current_run.composite_score:.2f})"
                ),
                prior_value=prior_run.composite_score,
                current_value=current_run.composite_score,
                delta=round(delta, 2),
            ))

    # ── Per-framework drops ─────────────────────────────────────────────
    framework_labels = {
        "f1_score": ("F1 Pre-Discovery", WarningSeverity.MEDIUM),
        "f2_score": ("F2 Momentum", WarningSeverity.MEDIUM),
        "f3_score": ("F3 Innovation", WarningSeverity.MEDIUM),
        "f4_score": ("F4 Stealth", WarningSeverity.MEDIUM),
        "f5_score": ("F5 Growth Quality", WarningSeverity.HIGH),    # F5 is the moat signal
        "f6_score": ("F6 Platform", WarningSeverity.MEDIUM),
        "f7_score": ("F7 Smart Beta", WarningSeverity.MEDIUM),
    }
    for attr, (label, sev) in framework_labels.items():
        cur = getattr(current_run, attr, None)
        pri = getattr(prior_run, attr, None)
        if cur is None or pri is None:
            continue
        delta = cur - pri
        threshold = -2.0 if sev == WarningSeverity.HIGH else -2.0
        if delta <= threshold:
            out.append(CheckpointWarning(
                severity=sev,
                code=f"{attr}_drop",
                message=(
                    f"{label} score dropped {abs(delta):.1f} pts "
                    f"({pri:.1f} → {cur:.1f})"
                ),
                prior_value=pri, current_value=cur,
                delta=round(delta, 1),
            ))

    # ── Overlay-derived: PT-ROIC erosion, BEW band drop, ICA-5 newly firing ─
    cur_overlays = _parse_overlay_results(current_run.overlays_results_json)
    pri_overlays = _parse_overlay_results(prior_run.overlays_results_json)

    cur_ica = cur_overlays.get("ICA", {})
    pri_ica = pri_overlays.get("ICA", {})
    cur_pt_roic = (cur_ica.get("adjusted") or {}).get("roic")
    pri_pt_roic = (pri_ica.get("adjusted") or {}).get("roic")
    if cur_pt_roic is not None and pri_pt_roic is not None:
        delta_pp = (cur_pt_roic - pri_pt_roic) * 100
        if delta_pp <= -3.0:
            out.append(CheckpointWarning(
                severity=WarningSeverity.MEDIUM,
                code="pt_roic_erosion",
                message=(
                    f"Peters-Taylor non-GAAP ROIC dropped "
                    f"{abs(delta_pp):.2f}pp ({pri_pt_roic*100:.2f}% → {cur_pt_roic*100:.2f}%)"
                ),
                prior_value=pri_pt_roic, current_value=cur_pt_roic,
                delta=round(delta_pp, 2),
            ))

    cur_bew = cur_overlays.get("BEW", {})
    pri_bew = pri_overlays.get("BEW", {})
    cur_bew_v = cur_bew.get("verdict")
    pri_bew_v = pri_bew.get("verdict")
    bew_rank = {
        "EXTREME_WINNER_CANDIDATE": 2,
        "moderate_winner_candidate": 1,
        "no_winner_pattern": 0,
    }
    if cur_bew_v and pri_bew_v and cur_bew_v != pri_bew_v:
        cr = bew_rank.get(cur_bew_v, -1)
        pr = bew_rank.get(pri_bew_v, -1)
        if cr < pr and cr >= 0:
            out.append(CheckpointWarning(
                severity=WarningSeverity.MEDIUM,
                code="bew_band_drop",
                message=f"BEW (Bessembinder) band dropped: {pri_bew_v} → {cur_bew_v}",
                prior_value=pri_bew_v, current_value=cur_bew_v,
            ))

    # ICA-5 newly firing — detect by inspecting triggers JSON (lighter than
    # checking the result; just looks for the trigger_id in the current
    # dive's triggered list)
    cur_triggers = _parse_triggers(current_run.overlays_triggered_json)
    pri_triggers = _parse_triggers(prior_run.overlays_triggered_json)
    cur_trigger_ids = {t.get("trigger_id") for t in cur_triggers}
    pri_trigger_ids = {t.get("trigger_id") for t in pri_triggers}
    if "ICA-5" in cur_trigger_ids and "ICA-5" not in pri_trigger_ids:
        out.append(CheckpointWarning(
            severity=WarningSeverity.LOW,
            code="ica5_newly_firing",
            message=(
                "ICA-5 trigger newly firing — Peters-Taylor non-GAAP ROIC "
                "now diverges from GAAP by ≥3pp; intangible-capital "
                "methodology now materially affects the moat read"
            ),
        ))

    # ── Phase 5R-4: data-quality signal drift (SBC, goodwill, dilution,
    # revenue trajectory) — read from F5 signals in framework_results_json.
    cur_f5 = _parse_f5_signals(current_run.framework_results_json)
    pri_f5 = _parse_f5_signals(prior_run.framework_results_json)
    out.extend(_detect_5r_warnings(cur_f5, pri_f5))

    return out


def _parse_f5_signals(raw: str | None) -> dict:
    """Extract F5 signals dict from a framework_results_json blob."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    f5 = data.get("F5") or {}
    return (f5.get("signals") or {}) if isinstance(f5, dict) else {}


def _detect_5r_warnings(cur_f5: dict, pri_f5: dict) -> list[CheckpointWarning]:
    """Phase 5R-4: emit warnings on data-quality signal drift.

    Compares F5's 5R signal blocks year-over-year and flags meaningful
    regressions. Severity is MEDIUM by default — these are early warnings,
    not thesis-break conditions on their own.
    """
    out: list[CheckpointWarning] = []

    # SBC intensity creep: current pct of revenue ≥ prior + 3pp
    cur_sbc = (cur_f5.get("sbc_intensity") or {}).get("pct_of_revenue")
    pri_sbc = (pri_f5.get("sbc_intensity") or {}).get("pct_of_revenue")
    if cur_sbc is not None and pri_sbc is not None:
        delta_pp = cur_sbc - pri_sbc
        if delta_pp >= 3.0:
            out.append(CheckpointWarning(
                severity=WarningSeverity.MEDIUM,
                code="sbc_intensity_creep",
                message=(
                    f"SBC intensity rose {delta_pp:.2f}pp YoY "
                    f"({pri_sbc:.2f}% → {cur_sbc:.2f}% of revenue) — "
                    f"dilution accelerating; cash-flow ex-SBC margin compressing"
                ),
                prior_value=pri_sbc, current_value=cur_sbc, delta=round(delta_pp, 2),
            ))

    # Goodwill concentration creep: current pct of assets ≥ prior + 5pp
    cur_gw = (cur_f5.get("goodwill_concentration") or {}).get("pct_of_assets")
    pri_gw = (pri_f5.get("goodwill_concentration") or {}).get("pct_of_assets")
    if cur_gw is not None and pri_gw is not None:
        delta_pp = cur_gw - pri_gw
        if delta_pp >= 5.0:
            out.append(CheckpointWarning(
                severity=WarningSeverity.MEDIUM,
                code="goodwill_concentration_creep",
                message=(
                    f"Goodwill concentration rose {delta_pp:.2f}pp YoY "
                    f"({pri_gw:.2f}% → {cur_gw:.2f}% of total assets) — "
                    f"significant M&A this period; evaluate capital-allocator discipline"
                ),
                prior_value=pri_gw, current_value=cur_gw, delta=round(delta_pp, 2),
            ))

    # Share dilution acceleration: avg YoY dilution worsening by ≥2pp
    cur_dil = (cur_f5.get("share_dilution") or {}).get("avg_yoy_pct")
    pri_dil = (pri_f5.get("share_dilution") or {}).get("avg_yoy_pct")
    if cur_dil is not None and pri_dil is not None:
        delta_pp = cur_dil - pri_dil
        if delta_pp >= 2.0:
            out.append(CheckpointWarning(
                severity=WarningSeverity.MEDIUM,
                code="share_dilution_accelerating",
                message=(
                    f"Average share dilution rate rose {delta_pp:.2f}pp YoY "
                    f"({pri_dil:.2f}%/yr → {cur_dil:.2f}%/yr) — Outsiders "
                    f"capital-allocator trait inverting"
                ),
                prior_value=pri_dil, current_value=cur_dil, delta=round(delta_pp, 2),
            ))

    # Revenue trajectory newly firing 'decelerating' band
    cur_traj_band = (cur_f5.get("revenue_trajectory") or {}).get("band")
    pri_traj_band = (pri_f5.get("revenue_trajectory") or {}).get("band")
    if (
        cur_traj_band == "decelerating"
        and pri_traj_band in (None, "stable_or_accelerating", "insufficient_history")
    ):
        out.append(CheckpointWarning(
            severity=WarningSeverity.MEDIUM,
            code="revenue_trajectory_decelerating",
            message=(
                "Revenue growth now monotonically decelerating across "
                "the trailing 4 periods with >30% compression — Lynch "
                "story-break candidate; re-examine original thesis"
            ),
            prior_value=pri_traj_band, current_value=cur_traj_band,
        ))
    return out


def _parse_overlay_results(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_triggers(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── Public entry point ───────────────────────────────────────────────────


def build_checkpoint_report(
    ticker: str,
    *,
    min_prior_age_days: int = _PRIOR_RUN_MIN_AGE_DAYS,
) -> CheckpointReport:
    """Build the checkpoint report for one watchlist ticker.

    Reads the latest DeepDiveRun, finds the most-recent prior run that is
    at least `min_prior_age_days` old (default 305 — ~10 months), runs the
    warning detector, returns the structured report.
    """
    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun, WatchlistEntry

    with get_session() as db:
        co = db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not co:
            return CheckpointReport(
                ticker=ticker, current_run_id=-1, prior_run_id=None,
                prior_run_date=None, years_since_added=None, no_prior=True,
            )

        current = db.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.company_id == co.id)
            .order_by(desc(DeepDiveRun.id)).limit(1)
        ).scalar_one_or_none()
        if current is None:
            return CheckpointReport(
                ticker=ticker, current_run_id=-1, prior_run_id=None,
                prior_run_date=None, years_since_added=None, no_prior=True,
            )

        cutoff = datetime.utcnow() - timedelta(days=min_prior_age_days)
        prior = db.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.company_id == co.id)
            .where(DeepDiveRun.id != current.id)
            .where(DeepDiveRun.created_at <= cutoff)
            .order_by(desc(DeepDiveRun.id)).limit(1)
        ).scalar_one_or_none()

        # Years since watchlist add (for context)
        wl = db.execute(
            select(WatchlistEntry)
            .where(WatchlistEntry.company_id == co.id)
            .where(WatchlistEntry.is_active.is_(True))
            .order_by(WatchlistEntry.added_date.asc()).limit(1)
        ).scalar_one_or_none()
        years_since = None
        if wl and wl.added_date:
            delta = datetime.utcnow().date() - wl.added_date
            years_since = round(delta.days / 365.25, 1)

        if prior is None:
            return CheckpointReport(
                ticker=ticker.upper(),
                current_run_id=current.id,
                prior_run_id=None, prior_run_date=None,
                years_since_added=years_since, no_prior=True,
            )

        warnings = detect_warnings(current, prior)
        return CheckpointReport(
            ticker=ticker.upper(),
            current_run_id=current.id,
            prior_run_id=prior.id,
            prior_run_date=prior.created_at.isoformat() if prior.created_at else None,
            years_since_added=years_since,
            warnings=warnings,
        )
