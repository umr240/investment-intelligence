"""ADR-032 — /audit-completeness skill handler.

Implementation of the workflow declared in `.claude/skills/audit-completeness.md`.
Read-only; no DB writes (other than the SkillInvocation telemetry row written
by the runtime).

Fixes shipped in v1.0.1 (vs the smoke-test v1.0.0):

  - **FPI detection**: was checking FinancialSourceLog for 40-F/20-F rows,
    which only logs accessions our parser has TOUCHED (not the full filing
    history). Now probes SEC submissions.json via edgar.fetch_filer_metadata
    + a 5-year scan of the issuer's filings list. SHOP correctly classified
    as former-FPI now.
  - **R&D display**: was showing `Financial.rd_expense` (absolute, $1.536B)
    labelled as `rd_intensity`. Now computes the ratio
    (rd_expense / revenue) and labels both correctly.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import desc, func, select

from cli.skills.runtime import PostCondition, SkillContext, SkillResult, register
from config.settings import require_edgar_identity
from data.db import SessionLocal
from data.models.schema import (
    Company,
    ExternalSignalRecord,
    Financial,
)

logger = logging.getLogger(__name__)


# ── Field-classification taxonomy (ADR-031 §1.1 root causes) ──────────────

_COMPANY_FIELDS: list[tuple[str, str, str]] = [
    # (column_name, label_for_user, category_if_missing)
    # ceo_equity_pct is upgraded to D for FPIs at runtime
    ("ceo_equity_pct", "F5 ceo_equity_pct", "C"),
    ("is_founder_ceo", "F5 is_founder_ceo", "C"),
    ("beta", "Company meta beta", "C"),
    ("pe_trailing", "Company meta pe_trailing", "C"),
    ("pb_ratio", "Company meta pb_ratio", "C"),
    ("roic", "F5 roic", "C"),
    ("pt_adjusted_roic", "F5 pt_adjusted_roic", "C"),
    ("shares_float", "Company meta shares_float", "C"),
]

# Financial-row fields (latest annual). rd_intensity is computed, not raw.
_FINANCIAL_FIELDS: list[tuple[str, str, str]] = [
    ("nrr_pct", "F6 nrr_pct", "A"),
    ("grr_pct", "F6 grr_pct", "A"),
    ("customer_concentration_pct", "F6 customer_concentration_pct", "A"),
    ("arr_state", "F6 arr_state", "A"),
    ("share_based_compensation", "F5 sbc", "C"),
    ("goodwill", "Financial goodwill", "C"),
]

# Conceptual fields that don't map to a single column. F1 90d buyers is
# upgraded to D for FPIs at runtime.
_CONCEPTUAL_FIELDS: list[tuple[str, str]] = [
    ("F4 options put/call ratio", "B"),
    ("F4 13F institutional delta", "C"),
    ("BEW TAM estimate", "A"),
    ("F1 90d open-market buyers", "C"),
]

_CATEGORY_DESCRIPTIONS = {
    "A": "issuer non-disclosure",
    "B": "source-policy exclusion",
    "C": "parser miss / engineering",
    "D": "FPI structural",
    "E": "insufficient history",
}


# ── FPI detection (Finding 1 fix — v1.0.1) ────────────────────────────────


def _is_former_fpi(ticker: str, cik: str | None) -> tuple[bool, str]:
    """Detect Foreign Private Issuer history — current or former.

    Two-tier check (per Tier 1.3 upgrade 2026-05-15):
      1. **edgartools.Company.is_foreign** — current FPI status. If True,
         the issuer is currently filing as an FPI. One-call, fast.
      2. **40-F/20-F filing history (last 5yr)** — catches ex-FPIs that
         redomiciled to US-domestic status (SHOP pattern: filed 40-F
         through 2024, became domestic 10-K filer in 2026). The
         Section-16-exemption window matters for F1 90d-buyers
         classification even after the conversion.

    Returns (is_former_fpi, evidence_string).
    """
    if not cik:
        return False, "no CIK on Company row"

    # Tier 1: current FPI status via edgartools
    try:
        from edgar import set_identity, Company as EdgarCo
        set_identity(require_edgar_identity())
        co = EdgarCo(ticker)
        if getattr(co, "is_foreign", False):
            return True, f"current FPI per edgartools.is_foreign=True (filer_type={getattr(co, 'filer_type', '?')})"
    except Exception as exc:
        logger.debug("is_foreign probe failed (%s): %s", ticker, exc)

    # Tier 2: 40-F/20-F filing history (catches ex-FPIs like SHOP)
    try:
        cik_int = int(cik.lstrip("0") or "0")
    except ValueError:
        return False, f"malformed CIK={cik!r}"

    try:
        from data.edgar_companyfacts import fetch_latest_filings
    except ImportError:
        return False, "edgar_companyfacts module unavailable"

    identity = require_edgar_identity()
    try:
        # Probe for any 40-F/20-F in the last 30 filings (covers ~5yr for most issuers)
        rows = fetch_latest_filings(
            cik=cik_int,
            identity=identity,
            forms=frozenset({"40-F", "40-F/A", "20-F", "20-F/A"}),
            limit=30,
        )
    except Exception as exc:  # noqa: BLE001 — defensive against network errors
        return False, f"submissions probe failed: {exc}"

    if not rows:
        return False, "no 40-F/20-F in last 30 filings"

    cutoff_year = date.today().year - 5
    recent = [
        r for r in rows
        if r.get("filing_date") and r["filing_date"] >= f"{cutoff_year}-01-01"
    ]
    if recent:
        latest = recent[0]
        return True, (
            f"{len(recent)} {latest['form']}/20-F filing(s) in last 5yr "
            f"(most recent: {latest['filing_date']})"
        )
    return False, f"40-F/20-F exist but all pre-{cutoff_year} (no longer applicable)"


# ── Main handler ──────────────────────────────────────────────────────────


@register("audit-completeness")
def audit_completeness(ctx: SkillContext) -> SkillResult:
    """Run the audit-completeness workflow for one ticker.

    Postconditions:
      - returns_structured_inventory (total > 0)
      - every_missing_field_classified (each ∈ {A,B,C,D,E})
      - no_silent_fallback (no present field carries None as its value)
    """
    ticker = (ctx.args.get("ticker") or "").upper()
    postconditions: list[PostCondition] = []
    anomalies: list[dict[str, Any]] = []
    lines: list[str] = []

    if not ticker:
        return SkillResult(
            success=False,
            error_message="ticker argument required",
        )

    # Pre-flight
    with SessionLocal() as s:
        c = s.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if c is None:
            return SkillResult(
                success=False,
                error_message=f"No Company row for {ticker}; cannot audit.",
            )
        fin_count = s.execute(
            select(func.count(Financial.id)).where(Financial.company_id == c.id)
        ).scalar() or 0
        if fin_count < 1:
            return SkillResult(
                success=False,
                error_message=(
                    f"{ticker} has no Financial rows. "
                    f"Run /dive-complete first."
                ),
            )

    # FPI detection (Finding 1 — v1.0.1 fix)
    is_fpi, fpi_evidence = _is_former_fpi(ticker, c.cik)

    lines.append("== Pre-flight ==")
    lines.append(f"  Company: {c.name} ({c.ticker})  exchange={c.exchange}  CIK={c.cik}")
    lines.append(f"  Financial rows: {fin_count}")
    lines.append(f"  Former-FPI: {is_fpi} ({fpi_evidence})")
    lines.append("")

    # Field-level audit
    audit_rows = []
    with SessionLocal() as s:
        c = s.execute(select(Company).where(Company.ticker == ticker)).scalar_one()

        for col, label, category in _COMPANY_FIELDS:
            val = getattr(c, col, None)
            present = val is not None
            if col == "ceo_equity_pct":
                # Promote to D for FPIs (Finding 1 → cascading classification fix)
                category = "D" if is_fpi else category
                if present:
                    state = c.ceo_equity_pct_state
                    present = state == "disclosed_exact"
            audit_rows.append({
                "scope": "Company",
                "field": col,
                "label": label,
                "present": present,
                "value": val if present else None,
                "category_if_missing": category,
            })

        latest = s.execute(
            select(Financial)
            .where(Financial.company_id == c.id, Financial.period == "annual")
            .order_by(desc(Financial.fiscal_year))
            .limit(1)
        ).scalar_one()

        for col, label, category in _FINANCIAL_FIELDS:
            val = getattr(latest, col, None)
            present = val is not None
            audit_rows.append({
                "scope": "Financial",
                "field": col,
                "label": label,
                "present": present,
                "value": val if present else None,
                "category_if_missing": category,
            })

        # F3 rd_intensity as a computed ratio (v1.0.1) + R&D-disclosure-aware
        # classification (v1.0.2 — HIMS bundled-in-opex case)
        rev = latest.revenue
        rd = latest.rd_expense
        rd_state = latest.rd_disclosure_state
        if rev and rd is not None and rev > 0:
            rd_intensity = rd / rev
            audit_rows.append({
                "scope": "Computed",
                "field": "rd_intensity",
                "label": "F3 rd_intensity (rd_expense / revenue)",
                "present": True,
                "value": rd_intensity,
                "category_if_missing": "C",
            })
        else:
            # Missing — classify by rd_disclosure_state (v1.0.2 fix)
            # 'bundled_in_opex' → A (issuer's choice to commingle in opex;
            #    tax-footnote signal proves R&D activity exists but can't
            #    be isolated from prose alone — see ADR-031 §1.2 F3 row)
            # 'not_disclosed' → A (issuer doesn't separately disclose; some
            #    consumer/services filers don't break out R&D)
            # None / anything else → C (we genuinely didn't detect; parser miss)
            if rd_state == "bundled_in_opex":
                category = "A"
                label_suffix = " [bundled_in_opex; XBRL does not separate]"
            elif rd_state == "not_disclosed":
                category = "A"
                label_suffix = " [not_disclosed by issuer]"
            else:
                category = "C"
                label_suffix = ""
            audit_rows.append({
                "scope": "Computed",
                "field": "rd_intensity",
                "label": f"F3 rd_intensity (rd_expense / revenue){label_suffix}",
                "present": False,
                "value": None,
                "category_if_missing": category,
            })

        # External signals (separate channel — informational, never in F1-F7)
        ext_rows = s.execute(
            select(ExternalSignalRecord).where(ExternalSignalRecord.company_id == c.id)
        ).scalars().all()
        ext_disclosed = [
            r for r in ext_rows if r.extraction_confidence != "not_disclosed"
        ]
        ext_not_disclosed = [
            r for r in ext_rows if r.extraction_confidence == "not_disclosed"
        ]

    # Conceptual fields (FPI promotion for F1 90d buyers — cascading fix)
    for label, category in _CONCEPTUAL_FIELDS:
        if label.startswith("F1 90d") and is_fpi:
            category = "D"
        audit_rows.append({
            "scope": "Conceptual",
            "field": label,
            "label": label,
            "present": False,
            "value": None,
            "category_if_missing": category,
        })

    # Render
    total = len(audit_rows)
    present_count = sum(1 for r in audit_rows if r["present"])
    missing = [r for r in audit_rows if not r["present"]]

    lines.append(f"== Data Completeness Audit -- {ticker} ==")
    lines.append(f"Present: {present_count} / {total} canonical fields")
    lines.append("")

    by_cat: dict[str, list[Any]] = defaultdict(list)
    for r in missing:
        by_cat[r["category_if_missing"]].append(r)

    lines.append("By root-cause category (ADR-031 sec 1.1):")
    for cat in sorted(by_cat.keys()):
        rows = by_cat[cat]
        cat_desc = _CATEGORY_DESCRIPTIONS.get(cat, "?")
        lines.append(f"  {cat} ({cat_desc}): {len(rows)} field(s)")
        for r in rows:
            lines.append(f"      - {r['label']}")
    lines.append("")

    lines.append(f"External signals channel ({len(ext_rows)} total rows):")
    lines.append(
        f"  Disclosed (LLM confidence high/medium/low): {len(ext_disclosed)}"
    )
    for r in ext_disclosed:
        lines.append(
            f"      - {r.signal_name} = {r.signal_value_numeric} {r.signal_unit}  "
            f"({r.extraction_confidence})"
        )
    lines.append(f"  Confirmed not_disclosed by LLM: {len(ext_not_disclosed)}")

    lines.append("")
    lines.append("Present fields (informational):")
    for r in audit_rows:
        if r["present"]:
            v = r["value"]
            if r["field"] == "rd_intensity":
                # Display ratio as percentage (v1.0.1 fix)
                v_str = f"{v * 100:.2f}%"
            elif isinstance(v, float):
                v_str = f"{v:.4f}"
            else:
                v_str = str(v)
            lines.append(f"  [{r['scope']:11s}] {r['label']:48s} = {v_str}")

    # Postconditions
    postconditions.append(PostCondition(
        name="returns_structured_inventory",
        pass_=total > 0,
        observed=total,
        expected=">0",
    ))
    postconditions.append(PostCondition(
        name="every_missing_field_classified",
        pass_=all(r["category_if_missing"] in {"A", "B", "C", "D", "E"} for r in missing),
        observed=(
            "all classified" if all(
                r["category_if_missing"] in {"A", "B", "C", "D", "E"}
                for r in missing
            ) else "drift"
        ),
        expected="all in {A,B,C,D,E}",
    ))
    postconditions.append(PostCondition(
        name="no_silent_fallback",
        pass_=all(r["value"] is not None for r in audit_rows if r["present"]),
        observed="checked",
        expected="no None passed as 'present'",
    ))

    success = all(p.pass_ for p in postconditions)
    return SkillResult(
        success=success,
        postconditions=postconditions,
        anomalies=anomalies,
        render_output="\n".join(lines),
        tool_calls_count=2,  # one Company query + one Financial query (counted broadly)
        cost_usd=0.0,
    )
