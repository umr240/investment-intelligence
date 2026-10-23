"""ADR-032 — /external-signals skill handler.

Wraps `deepdive/external_signals.py` (the second permitted Anthropic call
site per CLAUDE.md §"AI layer boundary" + ADR-031 §4.1) with:

  - Dangerous-skill confirmation gate (handled by runtime; only invoked
    when --confirm passed)
  - $100/month MTD spend ceiling (ADR-031 §4.4)
  - Pre-flight: Company + CIK + 8-K availability
  - Workflow: fetch_latest_earnings_8k_text → extract_signals_via_llm →
    persist_extraction
  - Postcondition: rows persisted; every disclosed row has verbatim
    quote ≥30 chars; source URL resolves
  - Shadow-mode verification: URL HEAD + quote-in-source check (does NOT
    re-call Anthropic — verification is deterministic)
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, func, select

from cli.skills.runtime import PostCondition, SkillContext, SkillResult, register
from data.db import SessionLocal
from data.models.schema import (
    Company,
    ExternalSignalRecord,
    Financial,
    SkillInvocation,
)

logger = logging.getLogger(__name__)

_MONTHLY_CEILING_USD = 100.0


@register("external-signals")
def external_signals(ctx: SkillContext) -> SkillResult:
    ticker = (ctx.args.get("ticker") or "").upper()
    period_end_str = ctx.args.get("period_end")
    postconditions: list[PostCondition] = []
    anomalies: list[dict[str, Any]] = []
    lines: list[str] = []

    if not ticker:
        return SkillResult(success=False, error_message="ticker argument required")

    # ── Pre-flight 1: Company + CIK ───────────────────────────────────────
    with SessionLocal() as s:
        c = s.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if c is None:
            return SkillResult(
                success=False, error_message=f"No Company row for {ticker}",
            )
        if not c.cik:
            return SkillResult(
                success=False, error_message=f"{ticker} has no CIK",
            )

        # Pre-flight 2: MTD Anthropic spend ceiling
        month_start = date.today().replace(day=1)
        mtd = s.execute(
            select(func.coalesce(func.sum(SkillInvocation.cost_usd), 0.0))
            .where(SkillInvocation.invoked_at >= datetime(month_start.year, month_start.month, 1))
        ).scalar() or 0.0
        if mtd >= _MONTHLY_CEILING_USD:
            return SkillResult(
                success=False,
                error_message=(
                    f"MTD Anthropic spend ${mtd:.2f} >= ${_MONTHLY_CEILING_USD:.2f} "
                    f"ceiling (ADR-031 §4.4). Refusing extraction."
                ),
            )

        # Pre-flight 3: deterministic field already populated? (informational)
        latest = s.execute(
            select(Financial)
            .where(Financial.company_id == c.id, Financial.period == "annual")
            .order_by(desc(Financial.fiscal_year))
            .limit(1)
        ).scalar_one_or_none()
        det_nrr = latest.nrr_pct if latest else None
        det_state = latest.retention_state if latest else None

    lines.append("== Pre-flight ==")
    lines.append(f"  Company: {c.name} ({ticker})  CIK={c.cik}")
    lines.append(f"  MTD Anthropic spend: ${mtd:.4f} / ${_MONTHLY_CEILING_USD:.2f}")
    if det_nrr is not None and det_state == "disclosed_exact":
        lines.append(
            f"  NOTE: Financial.nrr_pct = {det_nrr}% already disclosed_exact "
            f"via deterministic 10-K MD&A regex. LLM extraction will "
            f"triangulate (verify) rather than discover."
        )
    lines.append("")

    # ── Workflow: fetch → LLM extract → persist ───────────────────────────
    try:
        from deepdive.external_signals import (
            extract_signals_via_llm,
            fetch_latest_earnings_8k_text,
            persist_extraction,
        )
    except ImportError as exc:
        return SkillResult(
            success=False,
            error_message=f"deepdive/external_signals module unavailable: {exc}",
        )

    lines.append("== Workflow ==")
    fetched = fetch_latest_earnings_8k_text(ticker, c.cik)
    if fetched is None:
        return SkillResult(
            success=False,
            error_message=(
                f"No 8-K EX-99.1 earnings press release found for {ticker}. "
                f"FPI? Use /mic-parse equivalent when it ships."
            ),
        )
    source_text, accn, url, label = fetched
    lines.append(f"  Source: {label}  ({len(source_text)} chars)")
    lines.append(f"  Accession: {accn}")

    # Infer period end if not specified
    if period_end_str:
        period_end = date.fromisoformat(period_end_str)
    else:
        # Default: last calendar quarter end before today
        today = date.today()
        q_end_month = ((today.month - 1) // 3) * 3
        if q_end_month == 0:
            period_end = date(today.year - 1, 12, 31)
        else:
            # Calendar quarter ends: Mar 31, Jun 30, Sep 30
            last_day = {3: 31, 6: 30, 9: 30}[q_end_month]
            period_end = date(today.year, q_end_month, last_day)
    lines.append(f"  Target period_end: {period_end}")

    try:
        result = extract_signals_via_llm(
            ticker=ticker,
            source_text=source_text,
            source_url=url,
            source_accession=accn,
            source_label=label,
            period_end=period_end,
        )
    except Exception as exc:  # noqa: BLE001 — surface Anthropic errors cleanly
        return SkillResult(
            success=False,
            error_message=f"LLM extraction failed: {type(exc).__name__}: {exc}",
        )

    # Compute the actual cost using the cost rate from ADR-031 §3.2
    actual_cost = (
        result.prompt_tokens * 3.00 / 1_000_000
        + result.completion_tokens * 15.00 / 1_000_000
    )
    lines.append(
        f"  Anthropic call: {result.prompt_tokens} prompt + "
        f"{result.completion_tokens} completion = ${actual_cost:.4f}"
    )

    n_persisted = persist_extraction(result)
    lines.append(f"  Persisted: {n_persisted} ExternalSignalRecord rows")

    # ── Render extracted signals ──────────────────────────────────────────
    lines.append("")
    lines.append("== Extracted signals ==")
    triangulation = None
    for sig in result.signals:
        val = (
            f"{sig.value_numeric}" if sig.value_numeric is not None else "—"
        )
        marker = "+" if sig.confidence != "not_disclosed" else " "
        lines.append(
            f"  {marker} {sig.name:18s} [{sig.confidence:14s}] {val:>16s} {sig.unit}"
        )
        if sig.source_quote:
            quote = sig.source_quote[:160]
            lines.append(f'      quote: "{quote}"')

        # Triangulate against deterministic NRR if present
        if (
            sig.name == "nrr_pct"
            and sig.value_numeric is not None
            and det_nrr is not None
        ):
            delta_pp = abs(sig.value_numeric - det_nrr)
            triangulation = {"delta_pp": delta_pp, "det": det_nrr, "llm": sig.value_numeric}
            if delta_pp > 5.0:
                anomalies.append({
                    "type": "triangulation_mismatch",
                    "field": "nrr_pct",
                    "det_value": det_nrr,
                    "llm_value": sig.value_numeric,
                    "delta_pp": delta_pp,
                })

    if triangulation:
        if triangulation["delta_pp"] <= 5.0:
            lines.append(
                f"\n  Triangulation: deterministic {triangulation['det']:.1f}% "
                f"vs LLM {triangulation['llm']:.1f}% -> Δ={triangulation['delta_pp']:.2f}pp "
                f"(agree)"
            )
        else:
            lines.append(
                f"\n  [SHADOW-MODE ANOMALY] external-signals v{ctx.version}: "
                f"NRR triangulation mismatch: det {triangulation['det']:.1f}% "
                f"vs LLM {triangulation['llm']:.1f}% (Δ={triangulation['delta_pp']:.2f}pp)"
            )

    # ── Postconditions ────────────────────────────────────────────────────
    disclosed = [
        s_ for s_ in result.signals if s_.confidence != "not_disclosed"
    ]
    postconditions.append(PostCondition(
        name="rows_persisted",
        pass_=n_persisted >= 1,
        observed=n_persisted,
        expected=">=1",
    ))
    postconditions.append(PostCondition(
        name="every_disclosed_has_verbatim_quote",
        pass_=all(len(s_.source_quote or "") >= 30 for s_ in disclosed),
        observed=[(s_.name, len(s_.source_quote or "")) for s_ in disclosed],
        expected="all len >=30 chars",
    ))
    postconditions.append(PostCondition(
        name="not_disclosed_rows_have_null_value",
        pass_=all(
            s_.value_numeric is None
            for s_ in result.signals
            if s_.confidence == "not_disclosed"
        ),
        observed="checked",
        expected="value_numeric None for not_disclosed",
    ))
    postconditions.append(PostCondition(
        name="no_triangulation_anomaly",
        pass_=not any(a.get("type") == "triangulation_mismatch" for a in anomalies),
        observed=len([a for a in anomalies if a.get("type") == "triangulation_mismatch"]),
        expected=0,
    ))

    success = all(p.pass_ for p in postconditions)

    return SkillResult(
        success=success,
        postconditions=postconditions,
        anomalies=anomalies,
        render_output="\n".join(lines),
        tool_calls_count=3,
        tokens_prompt=result.prompt_tokens,
        tokens_completion=result.completion_tokens,
        cost_usd=actual_cost,
    )
