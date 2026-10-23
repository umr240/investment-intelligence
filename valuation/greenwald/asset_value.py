"""Asset Reproduction Value — the first Greenwald pillar (ADR-042).

Greenwald's method is a LADDER of three values, each more speculative than
the last, and the discipline is to read them in order:

    1. Asset Reproduction Value (AV)   — what a competitor must spend to rebuild
    2. Earnings Power Value (EPV)      — what current earnings are worth at zero growth
    3. Growth Value                    — worth counting ONLY when EPV > AV

The comparison AV vs EPV is the whole point. Damodaran's forward DCF has no
equivalent — it produces one number whose inputs are a story. Greenwald
produces two numbers computed from the balance sheet and the income statement
and asks what their RELATIONSHIP implies about competitive position:

    EPV >> AV   franchise — barriers to entry exist; a competitor would have to
                spend AV to earn EPV, and cannot, or would have already
    EPV ≈ AV    no franchise — commodity economics; returns compete to cost of capital
    EPV << AV   value destruction — the assets earn less than they cost to assemble;
                management should liquidate or the business is impaired

This is a genuinely different question from "what is the DCF". It is a moat
test denominated in currency, which is why running both engines and comparing
is worth more than either alone (`moat/munger_dorsey_five_sources`).

── Reproduction cost, not book value ─────────────────────────────────────
Book value understates reproduction cost for exactly the assets that matter.
Greenwald's adjustments, and what this module can and cannot do with SEC/ESEF
line items:

  * Working capital       → at book. Receivables/inventory reproduce ~at carrying value.
  * PP&E                  → at book (net). A true reproduction estimate needs gross
                            PP&E and replacement-cost inflation; not available as a
                            canonical field, so this is a KNOWN understatement and
                            is surfaced as a data gap, never silently.
  * Goodwill              → EXCLUDED. Goodwill is what a prior acquirer paid, not what
                            a competitor must spend. Including it double-counts the
                            franchise being tested for.
  * R&D                   → CAPITALISED. A competitor must fund years of R&D to reach
                            parity. Reuses the Peters-Taylor knowledge-capital
                            treatment already in the codebase (ADR-021) so the two
                            engines share one definition of intangible capital.
  * SG&A (brand/customer) → PARTIALLY CAPITALISED. Greenwald reproduces the customer
                            base with 1-3 years of SG&A. Uses the same 25% share the
                            Peters-Taylor organisation-capital treatment uses, for
                            internal consistency.
  * Non-interest-bearing  → SUBTRACTED. A buyer inherits payables/accruals; they
    liabilities             reduce what must be funded.

Deterministic. No LLM, no network. Missing inputs become data gaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Years of SG&A a competitor must spend to reproduce the customer base /
# brand. Greenwald uses 1-3 depending on customer stickiness; 3 is the
# franchise-friendly end. Held at the codebase's existing organisation-capital
# convention rather than invented fresh (ADR-021 uses 25% of SG&A as the
# capitalisable share, amortised over 5 years → 3 years of the 25% slice).
_SGA_CAPITALISABLE_SHARE = 0.25
_SGA_REPRODUCTION_YEARS = 3.0

# R&D knowledge-capital life, matching ADR-021's Peters-Taylor treatment
# (15%/yr amortisation ⇒ ~6.7yr effective life). Using the same number in both
# engines is deliberate: a reader comparing AV to the PT-adjusted invested
# capital should not have to reconcile two intangible conventions.
_RD_CAPITAL_YEARS = 6.67


@dataclass(frozen=True)
class AssetValueResult:
    """Reproduction cost of the asset base a competitor would have to assemble."""

    # Tangible legs
    working_capital: float | None
    net_ppe_proxy: float | None
    # Intangible legs (reproduction cost, not book)
    rd_capital: float | None
    sga_customer_capital: float | None
    # Deductions
    non_interest_liabilities: float | None
    goodwill_excluded: float | None

    asset_value_total: float | None          # enterprise-level reproduction cost
    asset_value_equity: float | None         # after net debt
    asset_value_per_share: float | None

    shares_outstanding: float | None
    net_debt: float | None
    data_gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compute_asset_value(
    *,
    current_assets: float | None,
    current_liabilities: float | None,
    total_assets: float | None,
    goodwill: float | None,
    cash_and_equivalents: float | None,
    total_debt: float | None,
    short_term_investments: float | None,
    rd_expense_history: list[float | None] | None,
    sga_expense: float | None,
    shares_outstanding: float | None,
) -> AssetValueResult:
    """Reproduction-cost asset value. Every missing leg becomes a data gap.

    Args:
        rd_expense_history: newest-last annual R&D. Capitalised over
            ``_RD_CAPITAL_YEARS``; more history = better estimate.
    """
    gaps: list[str] = []
    notes: list[str] = []

    # ── Working capital (reproduces at ~book) ──
    working_capital = None
    if current_assets is not None and current_liabilities is not None:
        # Exclude excess cash: a competitor rebuilding the business does not
        # need to reproduce the war chest, only the operating float.
        excess = (cash_and_equivalents or 0.0) + (short_term_investments or 0.0)
        operating_ca = current_assets - excess
        working_capital = operating_ca - current_liabilities
        if working_capital < 0:
            notes.append(
                f"negative operating working capital ({working_capital:,.0f}) — "
                f"supplier-financed model; reproduction cost is genuinely lower"
            )
    else:
        gaps.append("working capital: current_assets or current_liabilities missing")

    # ── Non-current operating assets (PP&E proxy) ──
    # Canonical schema has no PP&E field, so derive the residual. This is the
    # weakest leg and is flagged as such rather than presented as precise.
    net_ppe = None
    if total_assets is not None and current_assets is not None:
        net_ppe = total_assets - current_assets - (goodwill or 0.0)
        gaps.append(
            "PP&E reproduction cost approximated as (total_assets − current_assets "
            "− goodwill) at NET BOOK value. True reproduction cost needs gross PP&E "
            "at replacement prices — this UNDERSTATES asset value, so the franchise "
            "verdict is biased toward 'franchise'"
        )
    else:
        gaps.append("PP&E proxy: total_assets or current_assets missing")

    if goodwill:
        notes.append(
            f"goodwill {goodwill:,.0f} EXCLUDED — it is a prior acquirer's price, "
            f"not a competitor's reproduction cost"
        )

    # ── R&D knowledge capital ──
    rd_capital = None
    if rd_expense_history:
        valid = [r for r in rd_expense_history if r is not None and r > 0]
        if valid:
            recent = valid[-min(len(valid), int(_RD_CAPITAL_YEARS) + 1):]
            avg_rd = sum(recent) / len(recent)
            rd_capital = avg_rd * _RD_CAPITAL_YEARS
            notes.append(
                f"R&D capitalised: {len(recent)}yr avg {avg_rd:,.0f} × "
                f"{_RD_CAPITAL_YEARS}yr life = {rd_capital:,.0f}"
            )
    if rd_capital is None:
        gaps.append(
            "R&D knowledge capital not computed — no R&D disclosed. For an "
            "R&D-intensive filer this understates reproduction cost materially"
        )

    # ── SG&A customer/brand capital ──
    sga_capital = None
    if sga_expense is not None and sga_expense > 0:
        sga_capital = sga_expense * _SGA_CAPITALISABLE_SHARE * _SGA_REPRODUCTION_YEARS
        notes.append(
            f"customer/brand capital: {_SGA_CAPITALISABLE_SHARE:.0%} of SG&A "
            f"× {_SGA_REPRODUCTION_YEARS:.0f}yr = {sga_capital:,.0f}"
        )
    else:
        gaps.append("SG&A customer capital not computed — SG&A not disclosed separately")

    # ── Total ──
    legs = [working_capital, net_ppe, rd_capital, sga_capital]
    present = [x for x in legs if x is not None]
    av_total = sum(present) if present else None
    if av_total is not None and len(present) < len(legs):
        gaps.append(
            f"asset value computed from {len(present)}/{len(legs)} legs — "
            f"it is a FLOOR on reproduction cost, not a complete estimate"
        )

    net_debt = None
    if total_debt is not None:
        net_debt = total_debt - (cash_and_equivalents or 0.0) - (short_term_investments or 0.0)

    av_equity = None
    if av_total is not None and net_debt is not None:
        av_equity = av_total - net_debt

    av_per_share = None
    if av_equity is not None and shares_outstanding:
        av_per_share = av_equity / shares_outstanding
    elif av_equity is not None:
        gaps.append("asset value per share unavailable — shares outstanding missing")

    return AssetValueResult(
        working_capital=working_capital,
        net_ppe_proxy=net_ppe,
        rd_capital=rd_capital,
        sga_customer_capital=sga_capital,
        non_interest_liabilities=current_liabilities,
        goodwill_excluded=goodwill,
        asset_value_total=av_total,
        asset_value_equity=av_equity,
        asset_value_per_share=av_per_share,
        shares_outstanding=shares_outstanding,
        net_debt=net_debt,
        data_gaps=gaps,
        notes=notes,
    )
