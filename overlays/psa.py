"""
PSA — Post-Spinoff Alpha.

Cusatis, Miles & Woolridge (1993, JFE ★★★) and Desai & Jain (1999, JFE ★★★)
document that newly-listed spinoffs and demergers outperform during the
first 36 months when:

  - Parent forced selling (separate sector/index → mandate-driven exits)
  - Size mandate (small post-spinoff vs parent) drives institutional sales
  - Information asymmetry persists (low analyst coverage)
  - Index trackers eject the new entity

Plus the Desai-Jain "focus test": same SIC-2-digit as parent → focus_neutral
(documented +18% excess); different SIC-2-digit → focus_increasing (+33%).

Adjusted Piotroski: PSA replaces the pure YoY change signals (P3 ROA up,
L5 LT debt down, L6 current ratio up, O8 GM up, O9 asset turnover up) with
INDUSTRY-MEDIAN comparatives. We don't have industry-median data
warehoused; that step is flagged as a data gap and the original Piotroski
is reported alongside.

Per CLAUDE.md the overlay never auto-runs — only after explicit confirmation
of a PSA-1..4 trigger from `overlays/detector.py`.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any


SPINOFF_TYPES = frozenset({"spinoff", "demerger", "carve_out"})
PSA_HOLDING_WINDOW_MONTHS = 36
DOCUMENTED_EXCESS_FOCUS_NEUTRAL = 0.18      # Desai-Jain
DOCUMENTED_EXCESS_FOCUS_INCREASING = 0.33   # Desai-Jain


async def run_psa(
    ticker: str,
    *,
    reader: Any,
) -> dict[str, Any]:
    """Compute Post-Spinoff Alpha diagnostic for `ticker`.

    Many checks require parent-company data (parent_market_cap, parent_sic,
    parent_sector) we don't currently warehouse. They surface as data_gaps
    rather than crashing — typical PSA candidate isn't in our universe yet.
    """
    company = reader.company_or_none()
    annuals = reader.annuals(last_n=2)
    analyst = reader.latest_analyst_coverage() if hasattr(reader, "latest_analyst_coverage") else None
    if not company:
        return {"ok": False, "reason": "no Company row"}

    listing_type = (company.listing_type or "").lower()
    months_since_listing = _months_since(company.ipo_date) if company.ipo_date else None

    is_recent_spinoff = (
        listing_type in SPINOFF_TYPES
        and months_since_listing is not None
        and months_since_listing < PSA_HOLDING_WINDOW_MONTHS
    )

    # ── Step 1. Adjusted Piotroski (industry-median deltas) ──────────────
    # We don't yet warehouse industry medians; surface as gap and report the
    # original 9-signal Piotroski for context.
    original_piotroski = None
    piotroski_gap = (
        "Industry-median comparatives not warehoused — adjusted Piotroski "
        "(P3/L5/L6/O8/O9 vs sector) skipped; original 9-signal score reported"
    )

    # ── Step 2. Structural mispricing — 4 binary checks ──────────────────
    parent_ticker = company.parent_ticker
    parent_market_cap = None         # not warehoused
    parent_sector = None             # not warehoused
    parent_sic_2digit = None         # not warehoused

    # PSA-A: parent_sector != company.sector (forced selling)
    psa_a = None
    if parent_sector is not None:
        psa_a = (parent_sector or "").lower() != (company.sector or "").lower()

    # PSA-B: market_cap < 10% × parent_market_cap (size mandate trigger)
    psa_b = None
    if parent_market_cap and company.market_cap_usd:
        psa_b = company.market_cap_usd < parent_market_cap * 0.10

    # PSA-C: analyst_count < 3 (information asymmetry)
    analyst_count = analyst.analyst_count if analyst else None
    psa_c = (analyst_count is not None) and analyst_count < 3

    # PSA-D: ejected from index — not warehoused
    psa_d = None

    structural_checks = {
        "A_forced_selling_sector_diff": psa_a,
        "B_size_mandate_under_10pct_parent": psa_b,
        "C_analyst_coverage_under_3": psa_c,
        "D_ejected_from_index": psa_d,
    }
    mispricing_score = sum(1 for v in structural_checks.values() if v is True)
    n_checks_evaluable = sum(1 for v in structural_checks.values() if v is not None)

    # ── Step 3. Desai-Jain focus test ────────────────────────────────────
    sic_2 = (company.sic[:2] if (company.cik and getattr(company, "sic", None)) else None)
    same_sic2 = (
        sic_2 is not None and parent_sic_2digit is not None
        and sic_2 == parent_sic_2digit
    )
    focus_type: str | None = None
    documented_excess = None
    if parent_sic_2digit is not None:
        focus_type = "focus_neutral" if same_sic2 else "focus_increasing"
        documented_excess = (
            DOCUMENTED_EXCESS_FOCUS_NEUTRAL if same_sic2
            else DOCUMENTED_EXCESS_FOCUS_INCREASING
        )

    # ── Verdict ──────────────────────────────────────────────────────────
    if not is_recent_spinoff:
        verdict = "not_a_spinoff_candidate"
        verdict_note = (
            f"PSA universe is recent spinoffs/demergers (<36mo). "
            f"This ticker: listing_type='{listing_type}', months_listed="
            f"{months_since_listing}. PSA does not apply."
        )
    elif n_checks_evaluable == 0:
        verdict = "data_gaps_block_verdict"
        verdict_note = (
            "Recent spinoff but parent-company comparatives not warehoused; "
            "structural mispricing checks unscoreable"
        )
    elif mispricing_score >= 3:
        verdict = "strong_psa_candidate"
        verdict_note = (
            f"{mispricing_score}/{n_checks_evaluable} structural mispricing "
            "checks fired — Cusatis-Desai-Jain conditions strongly met"
        )
    elif mispricing_score >= 2:
        verdict = "moderate_psa_candidate"
        verdict_note = f"{mispricing_score}/{n_checks_evaluable} checks fired"
    else:
        verdict = "weak_psa_candidate"
        verdict_note = f"only {mispricing_score}/{n_checks_evaluable} checks fired"

    return {
        "ok": True,
        "ticker": ticker,
        "company_state": {
            "listing_type": listing_type,
            "months_since_listing": months_since_listing,
            "ipo_date": company.ipo_date,
            "parent_ticker": parent_ticker,
            "is_recent_spinoff": is_recent_spinoff,
        },
        "adjusted_piotroski": {
            "value": original_piotroski,
            "data_gap": piotroski_gap,
        },
        "structural_mispricing": {
            "checks": structural_checks,
            "score": mispricing_score,
            "n_evaluable": n_checks_evaluable,
        },
        "desai_jain_focus_test": {
            "company_sic_2digit": sic_2,
            "parent_sic_2digit": parent_sic_2digit,
            "same_sic2": same_sic2,
            "focus_type": focus_type,
            "documented_excess_return": documented_excess,
        },
        "data_gaps": [
            g for g in (
                "parent_market_cap not warehoused" if parent_market_cap is None else None,
                "parent_sector not warehoused" if parent_sector is None else None,
                "parent_sic not warehoused" if parent_sic_2digit is None else None,
                "index_membership not warehoused" if psa_d is None else None,
                piotroski_gap,
            )
            if g is not None
        ],
        "verdict": verdict,
        "interpretation": verdict_note,
        "academic_anchors": [
            "Cusatis, Miles & Woolridge (1993) JFE ★★★",
            "Desai & Jain (1999) JFE ★★★",
        ],
    }


def _months_since(d: Any) -> int | None:
    if d is None:
        return None
    try:
        today = _date.today()
        return (today.year - d.year) * 12 + (today.month - d.month)
    except (AttributeError, TypeError):
        return None
