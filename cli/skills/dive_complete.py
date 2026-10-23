"""ADR-032 — /dive-complete skill handler.

Wraps the canonical Tier-2 dive cycle (`invest dive --tier 2 --force
--auto-overlays`) with:

  - Pre-flight: Company row + CIK present; 10-K/A within 30 days
    requires --force (always enforced by this skill)
  - Workflow: subprocess invocation of `invest dive`
  - Postcondition: a NEW DeepDiveRun row exists for the ticker, with
    composite_score not null
  - Shadow-mode delta-check: if a prior DeepDiveRun within 24h had
    |Δcomposite| > 1.0 vs this run, fire anomaly with hypothesis text

No new Anthropic call sites; no new persistence paths. The skill is
strictly a checklist over the existing CLI.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc, select

from cli.skills.runtime import PostCondition, SkillContext, SkillResult, register
from data.db import SessionLocal
from data.models.schema import Company, DeepDiveRun, FinancialSourceLog

logger = logging.getLogger(__name__)


@register("dive-complete")
def dive_complete(ctx: SkillContext) -> SkillResult:
    ticker = (ctx.args.get("ticker") or "").upper()
    tier = int(ctx.args.get("tier") or 2)
    postconditions: list[PostCondition] = []
    anomalies: list[dict[str, Any]] = []
    lines: list[str] = []

    if not ticker:
        return SkillResult(success=False, error_message="ticker argument required")

    # ── Pre-flight ────────────────────────────────────────────────────────
    with SessionLocal() as s:
        c = s.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if c is None:
            return SkillResult(
                success=False,
                error_message=(
                    f"No Company row for {ticker}. Add to universe before diving."
                ),
            )
        if not c.cik:
            return SkillResult(
                success=False,
                error_message=f"{ticker} has no CIK — EDGAR XBRL fetch will fail.",
            )

        # 10-K/A amendment check (ADR-031 §1.2 category C parser-bug protection)
        recent_amendment = s.execute(
            select(FinancialSourceLog)
            .where(FinancialSourceLog.ticker == ticker)
            .where(FinancialSourceLog.form_type == "10-K/A")
            .order_by(desc(FinancialSourceLog.fetched_at))
            .limit(1)
        ).scalar_one_or_none()
        if recent_amendment and recent_amendment.fetched_at:
            days_old = (datetime.utcnow() - recent_amendment.fetched_at).days
            if days_old < 30:
                lines.append(
                    f"  NOTE: 10-K/A amendment fetched {days_old}d ago "
                    f"(accn {recent_amendment.accession_number}). "
                    f"--force is mandatory; skill body already enforces it."
                )

        # Snapshot the prior most-recent DeepDiveRun BEFORE the new dive
        prior = s.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.ticker == ticker)
            .order_by(desc(DeepDiveRun.run_date))
            .limit(1)
        ).scalar_one_or_none()
        prior_id = prior.id if prior else None
        prior_composite = prior.composite_score if prior else None
        prior_run_date = prior.run_date if prior else None

    lines.append(f"== Pre-flight ==")
    lines.append(f"  Company: {c.name} ({ticker})  CIK={c.cik}")
    if prior:
        lines.append(
            f"  Prior DeepDiveRun #{prior_id} at {prior_run_date} composite={prior_composite}"
        )
    else:
        lines.append("  No prior DeepDiveRun for this ticker.")
    lines.append("")

    # ── Workflow: invoke `invest dive` ────────────────────────────────────
    lines.append(f"== Workflow ==")
    lines.append(
        f"  Running: invest dive {ticker} --tier {tier} --force --auto-overlays"
    )
    cmd = [
        "uv", "run", "invest", "dive", ticker,
        "--tier", str(tier), "--force", "--auto-overlays",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=600,
        )
        dive_stdout = result.stdout.decode("utf-8", errors="replace")
        dive_rc = result.returncode
    except subprocess.TimeoutExpired:
        return SkillResult(
            success=False,
            error_message=f"`invest dive {ticker}` timed out after 10 minutes",
        )

    if dive_rc != 0:
        return SkillResult(
            success=False,
            error_message=(
                f"`invest dive {ticker}` exited with code {dive_rc}. "
                f"stdout-tail: {dive_stdout[-500:]}"
            ),
        )
    lines.append(f"  exit code: {dive_rc}")

    # ── Post-flight: verify a new DeepDiveRun exists ──────────────────────
    with SessionLocal() as s:
        new_run = s.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.ticker == ticker)
            .order_by(desc(DeepDiveRun.run_date))
            .limit(1)
        ).scalar_one_or_none()
        if new_run is None or new_run.id == prior_id:
            return SkillResult(
                success=False,
                error_message=(
                    f"`invest dive` returned 0 but no new DeepDiveRun row created "
                    f"for {ticker}. Persistence path may have failed silently."
                ),
            )
        new_composite = new_run.composite_score
        new_verdict = new_run.verdict
        # Unfeasible count derived from per-framework score columns on the
        # DeepDiveRun (DeepDiveRun has f1_score..f7_score; null score = unfeasible).
        # NOTE: framework_unfeasible_count lives on Company, not DeepDiveRun;
        # we cannot use it directly per-run.
        new_unfeasible = sum(
            1 for col in ("f1_score", "f2_score", "f3_score", "f4_score",
                          "f5_score", "f6_score", "f7_score")
            if getattr(new_run, col, None) is None
        )

    lines.append(f"")
    lines.append(f"== Post-flight ==")
    lines.append(f"  New DeepDiveRun #{new_run.id} composite={new_composite} verdict={new_verdict}")
    lines.append(f"  Frameworks unfeasible: {new_unfeasible}/7")

    # ── Delta-anomaly check (shadow-mode primary signal) ──────────────────
    delta = None
    if prior_composite is not None and new_composite is not None and prior_run_date:
        delta = new_composite - prior_composite
        elapsed = datetime.utcnow() - prior_run_date
        if elapsed < timedelta(hours=24) and abs(delta) > 1.0:
            hypothesis = (
                "10-K/A amendment may have overwritten prior-period income statement "
                "(ADR-031 §1.2 category C parser bug)"
                if recent_amendment and (datetime.utcnow() - (recent_amendment.fetched_at or datetime.utcnow())).days < 30
                else "investigate framework input changes"
            )
            anomalies.append({
                "type": "composite_delta",
                "delta": round(delta, 4),
                "prior_run_id": prior_id,
                "prior_composite": prior_composite,
                "new_run_id": new_run.id,
                "new_composite": new_composite,
                "elapsed_hours": round(elapsed.total_seconds() / 3600, 2),
                "hypothesis": hypothesis,
            })
            lines.append(
                f"\n  [SHADOW-MODE ANOMALY] dive-complete v{ctx.version}: "
                f"composite changed by Δ={delta:+.2f} from prior run within "
                f"{elapsed.total_seconds() / 3600:.1f}h. "
                f"Hypothesis: {hypothesis}."
            )
        else:
            lines.append(f"  Δcomposite vs prior run: {delta:+.4f} (within tolerance)")

    # ── Postconditions ────────────────────────────────────────────────────
    postconditions.append(PostCondition(
        name="new_deepdive_run_created",
        pass_=new_run.id != prior_id,
        observed=new_run.id,
        expected=f"!= {prior_id}",
    ))
    postconditions.append(PostCondition(
        name="composite_score_not_null",
        pass_=new_composite is not None,
        observed=new_composite,
        expected="not None",
    ))
    postconditions.append(PostCondition(
        name="data_completeness_or_gaps_logged",
        pass_=(new_run.data_gaps_json is not None) or (new_run.composite_score is not None),
        observed=bool(new_run.data_gaps_json),
        expected="data_gaps_json populated OR composite computed",
    ))
    postconditions.append(PostCondition(
        name="no_unexplained_delta_anomaly",
        pass_=len(anomalies) == 0,
        observed=len(anomalies),
        expected=0,
    ))

    success = all(p.pass_ for p in postconditions)

    # Surface the dive's own scorecard tail in the output
    lines.append("\n== Dive output (last 30 lines) ==")
    dive_tail = "\n".join(dive_stdout.splitlines()[-30:])
    lines.append(dive_tail)

    return SkillResult(
        success=success,
        postconditions=postconditions,
        anomalies=anomalies,
        render_output="\n".join(lines),
        tool_calls_count=4,  # 1 pre-flight + subprocess + 1 post-flight + 1 delta
        cost_usd=0.0,
    )
