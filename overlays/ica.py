"""
ICA — Intangible Capital Adjustment.

Peters & Taylor (2017, JFE ★★★) and Eisfeldt & Papanikolaou (2013, JF ★★★)
document that GAAP under-reports capital efficiency for companies whose
true productive assets are R&D-derived knowledge capital and SG&A-derived
organisational capital — neither shows up on the balance sheet.

Two perpetual-inventory components:

  1. Knowledge capital KC: capitalise R&D with 15% annual depreciation
     KC_t = (1 - 0.15) × KC_{t-1} + R&D_t

  2. Organisational capital OC: capitalise 25% of SG&A with 20% depreciation
     OC_t = (1 - 0.20) × OC_{t-1} + 0.25 × SG&A_t

These add to GAAP book equity AND invested capital to compute an "adjusted
ROIC" that more honestly reflects the marginal productivity of intangible-
heavy companies.

Per CLAUDE.md "Overlay detector is always passive": this function is
called ONLY after explicit user confirmation following a detector trigger.
It never runs auto-magically.
"""
from __future__ import annotations

from typing import Any


# Peters-Taylor parameters (paper defaults)
KC_DEPRECIATION_RATE = 0.15           # R&D amortises at 15%/yr
OC_DEPRECIATION_RATE = 0.20           # SG&A organisational at 20%/yr
OC_SGA_FRACTION = 0.25                # 25% of SG&A treated as organisational capital
DEFAULT_GROWTH_RATE = 0.05            # initial-stock growth assumption (5%)
DEFAULT_TAX_RATE = 0.21               # US corporate effective rate fallback


async def run_ica(
    ticker: str,
    *,
    reader: Any,
    growth_rate: float = DEFAULT_GROWTH_RATE,
    effective_tax_rate: float = DEFAULT_TAX_RATE,
) -> dict[str, Any]:
    """Compute Peters-Taylor adjusted ROIC for `ticker`.

    Reads R&D + SG&A history from `Financial.rd_expense` and `sga_expense`,
    plus the latest annual's balance-sheet items. Returns
    `{"ok": False, "reason": ...}` when inputs are missing.
    """
    annuals = reader.annuals(last_n=10)   # most-recent first
    company = reader.company_or_none()
    if not annuals or not company:
        return {"ok": False, "reason": "no annual financials persisted"}

    # The TRUE latest annual — current-period balance sheet / income items
    # must always anchor here, never to whichever year last happened to
    # disclose R&D separately (companies routinely fold R&D into OpEx after
    # early filings; anchoring "latest" to a stale rd_expense year silently
    # ages the whole ROIC calc by however many years disclosure has lapsed).
    true_latest = annuals[0]

    # Oldest → newest (perpetual-inventory builds forward in time)
    all_chrono = list(reversed(annuals))

    rd_years = [a for a in all_chrono if a.rd_expense is not None]
    if len(rd_years) < 2:
        return {
            "ok": False,
            "reason": (
                f"insufficient R&D history — need ≥2 annuals with rd_expense, "
                f"got {len(rd_years)}"
            ),
            "n_annuals_total": len(annuals),
        }

    gaps: list[str] = []

    # ── 1. Knowledge capital KC perpetual inventory ──────────────────────
    # Build from the first year R&D was disclosed through the TRUE latest
    # year. Years where R&D disclosure has lapsed still depreciate the
    # existing stock (no new capitalisation) rather than freezing KC at
    # its last-disclosed value — a knowledge stock decays whether or not
    # the company keeps tagging R&D separately in XBRL.
    first_rd_idx = next(i for i, a in enumerate(all_chrono) if a.rd_expense is not None)
    kc_chrono = all_chrono[first_rd_idx:]
    kc_init = kc_chrono[0].rd_expense / (growth_rate + KC_DEPRECIATION_RATE)
    kc_series: list[float] = [kc_init]
    for a in kc_chrono[1:]:
        kc_prev = kc_series[-1]
        kc_t = (1 - KC_DEPRECIATION_RATE) * kc_prev + (a.rd_expense or 0.0)
        kc_series.append(kc_t)

    last_disclosed_rd_year = max(a.fiscal_year for a in rd_years)
    if true_latest.fiscal_year != last_disclosed_rd_year:
        gaps.append(
            f"R&D not separately disclosed in XBRL since FY{last_disclosed_rd_year} "
            f"(latest annual is FY{true_latest.fiscal_year}) — knowledge capital "
            f"carried forward via depreciation-only (no new capitalisation) for "
            f"FY{last_disclosed_rd_year + 1}–FY{true_latest.fiscal_year}"
        )

    # ── 2. Organisational capital OC perpetual inventory ─────────────────
    # Independent of R&D availability — build across every year SG&A is
    # disclosed, through the TRUE latest year, not gated by whether that
    # same year also had R&D.
    sga_chrono = [a for a in all_chrono if a.sga_expense is not None]
    if len(sga_chrono) < 2:
        return {
            "ok": False,
            "reason": (
                f"insufficient SG&A history for organisational capital — "
                f"need ≥2 annuals, got {len(sga_chrono)}"
            ),
            "n_annuals_total": len(annuals),
        }
    oc_init = (
        OC_SGA_FRACTION * sga_chrono[0].sga_expense
        / (growth_rate + OC_DEPRECIATION_RATE)
    )
    oc_series: list[float] = [oc_init]
    for a in sga_chrono[1:]:
        oc_prev = oc_series[-1]
        oc_t = (
            (1 - OC_DEPRECIATION_RATE) * oc_prev
            + OC_SGA_FRACTION * (a.sga_expense or 0.0)
        )
        oc_series.append(oc_t)

    knowledge_capital = kc_series[-1]
    organisational_capital = oc_series[-1]
    total_intangible_stack = knowledge_capital + organisational_capital

    # ── 3. Adjusted financials — always anchored to the TRUE latest annual ──
    total_equity = true_latest.total_equity or 0.0
    total_debt = true_latest.total_debt or 0.0
    cash = true_latest.cash_and_equivalents or 0.0
    operating_income = true_latest.operating_income or 0.0
    rd_current = true_latest.rd_expense or 0.0   # naturally 0 if not currently disclosed
    market_cap = company.market_cap_usd

    adj_book_equity = total_equity + total_intangible_stack
    kc_prior = kc_series[-2] if len(kc_series) >= 2 else 0.0
    rd_amortisation = KC_DEPRECIATION_RATE * kc_prior
    adj_nopat = (
        operating_income * (1 - effective_tax_rate)
        + rd_current
        - rd_amortisation
    )
    adj_invested_capital = total_equity + total_debt - cash + total_intangible_stack
    if adj_invested_capital <= 0:
        return {
            "ok": False,
            "reason": "adjusted invested capital ≤ 0 — cannot compute ROIC",
            "intangible_stack": total_intangible_stack,
        }
    adj_roic = adj_nopat / adj_invested_capital

    gaap_roic = true_latest.roic
    gaap_pb = (market_cap / total_equity) if (market_cap and total_equity) else None
    adj_pb = (market_cap / adj_book_equity) if (market_cap and adj_book_equity) else None

    f5_threshold = 0.15
    f5_verdict_revised = "pass" if adj_roic >= f5_threshold else "fail"

    return {
        "ok": True,
        "ticker": ticker,
        "components": {
            "knowledge_capital": round(knowledge_capital, 0),
            "organisational_capital": round(organisational_capital, 0),
            "total_intangible_stack": round(total_intangible_stack, 0),
            "kc_series": [round(v, 0) for v in kc_series],
            "oc_series": [round(v, 0) for v in oc_series],
            "kc_fiscal_years": [a.fiscal_year for a in kc_chrono],
            "oc_fiscal_years": [a.fiscal_year for a in sga_chrono],
            "n_annuals_used": len(kc_chrono),
            "fiscal_years": [a.fiscal_year for a in kc_chrono],
            "latest_fiscal_year": true_latest.fiscal_year,
            "last_disclosed_rd_year": last_disclosed_rd_year,
        },
        "gaap": {
            "roic": round(gaap_roic, 4) if gaap_roic is not None else None,
            "book_equity": total_equity,
            "pb_ratio": round(gaap_pb, 3) if gaap_pb is not None else None,
        },
        "adjusted": {
            "nopat": round(adj_nopat, 0),
            "rd_amortisation": round(rd_amortisation, 0),
            "invested_capital": round(adj_invested_capital, 0),
            "book_equity": round(adj_book_equity, 0),
            "roic": round(adj_roic, 4),
            "pb_ratio": round(adj_pb, 3) if adj_pb is not None else None,
        },
        "f5_verdict_revised": f5_verdict_revised,
        "interpretation": (
            "ICA-adjusted ROIC PASSES the 15% threshold — F5 quality signal "
            "would flip from fail to pass after intangible adjustment"
            if f5_verdict_revised == "pass"
            else "ICA-adjusted ROIC still below 15% — even with intangible "
                 "capitalisation, capital efficiency is weak"
        ),
        "parameters": {
            "kc_depreciation_rate": KC_DEPRECIATION_RATE,
            "oc_depreciation_rate": OC_DEPRECIATION_RATE,
            "oc_sga_fraction": OC_SGA_FRACTION,
            "growth_rate_assumption": growth_rate,
            "effective_tax_rate": effective_tax_rate,
        },
        "academic_anchors": [
            "Peters & Taylor (2017) JFE ★★★",
            "Eisfeldt & Papanikolaou (2013) JF ★★★",
        ],
        "data_gaps": gaps,
    }
