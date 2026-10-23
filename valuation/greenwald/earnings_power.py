"""Greenwald Earnings Power Value — normalised, maintenance-capex adjusted (ADR-042).

This is EPV as Greenwald actually defines it, which is NOT
``current_NOPAT / WACC``. That shortcut (the pre-existing
``valuation/damodaran/epv.py``) is a no-growth *anchor* computed from whatever
NOPAT the forward-DCF engine happened to produce. Greenwald's EPV is a
separately-derived number with three deliberate adjustments:

  1. **Normalise the margin over a full cycle.** Current-year EBIT embeds
     wherever the company sits in its cycle. Greenwald averages the operating
     margin across the available history and applies it to current revenue, so
     a peak-cycle year does not get capitalised into perpetuity.

  2. **Add back growth capex; charge only MAINTENANCE capex.** This is the
     adjustment that matters most and the one the shortcut omits entirely. A
     company spending heavily to grow shows depressed earnings. At zero growth
     it would spend only enough to hold the asset base flat. Greenwald's
     estimate: maintenance capex ≈ D&A, with the growth portion of capex
     (capex − D&A, when positive) added back to earnings.

  3. **Capitalise at WACC, add back excess cash, subtract debt.** Zero growth
     means no reinvestment, so the perpetuity is simply E/r.

The result differs from the shortcut EPV, sometimes by a lot, and the
difference is informative: a large gap means the company's reported earnings
are being suppressed by growth spending.

Deterministic. No LLM, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

# Shared with valuation/greenwald/__init__.py's implied-rate screen so the two
# places cannot drift on what counts as a plausible effective tax rate.
_MAX_PLAUSIBLE_TAX_RATE = 0.60
_DEFAULT_TAX_RATE = 0.25


@dataclass(frozen=True)
class EarningsPowerResult:
    """Greenwald EPV with the full normalisation chain exposed for audit."""

    # Normalisation chain — every intermediate is surfaced so a reader can
    # see WHERE the number came from rather than trusting one output.
    op_margin_history: list[float]
    normalized_op_margin: float | None
    current_revenue: float | None
    normalized_ebit: float | None

    depreciation: float | None
    capex: float | None
    maintenance_capex: float | None
    growth_capex_added_back: float | None

    adjusted_ebit: float | None
    tax_rate: float
    adjusted_nopat: float | None

    wacc: float
    epv_operations: float | None            # adjusted NOPAT / WACC
    excess_cash: float | None
    net_debt: float | None
    epv_equity: float | None
    epv_per_share: float | None

    current_price: float | None
    mos_vs_epv_pct: float | None

    data_gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compute_earnings_power(
    *,
    op_margin_history: list[float | None],   # newest-last
    current_revenue: float | None,
    depreciation: float | None,
    capex: float | None,
    tax_rate: float,
    wacc: float,
    cash_and_equivalents: float | None,
    short_term_investments: float | None,
    total_debt: float | None,
    shares_outstanding: float | None,
    current_price: float | None,
    min_history_years: int = 3,
) -> EarningsPowerResult:
    """Compute Greenwald EPV. Missing inputs become gaps, never assumptions."""
    gaps: list[str] = []
    notes: list[str] = []

    def _empty(reason: str) -> EarningsPowerResult:
        gaps.append(reason)
        return EarningsPowerResult(
            op_margin_history=[], normalized_op_margin=None,
            current_revenue=current_revenue, normalized_ebit=None,
            depreciation=depreciation, capex=capex, maintenance_capex=None,
            growth_capex_added_back=None, adjusted_ebit=None, tax_rate=tax_rate,
            adjusted_nopat=None, wacc=wacc, epv_operations=None,
            excess_cash=None, net_debt=None, epv_equity=None,
            epv_per_share=None, current_price=current_price,
            mos_vs_epv_pct=None, data_gaps=gaps, notes=notes,
        )

    if wacc <= 0:
        return _empty(f"WACC {wacc:.2%} <= 0 — EPV undefined")

    # ── 1. Normalise the operating margin over the cycle ──
    margins = [m for m in op_margin_history if m is not None]
    if not margins:
        return _empty("no operating-margin history — EPV cannot be normalised")
    if len(margins) < min_history_years:
        gaps.append(
            f"only {len(margins)}yr of margin history (want >={min_history_years}) — "
            f"normalisation is weak; a single cycle position may dominate"
        )
    # Median, not mean: Greenwald's concern is the typical year, and the median
    # is robust to one blowout or one write-off year distorting the anchor.
    norm_margin = median(margins)
    notes.append(
        f"normalised margin = median of {len(margins)}yr "
        f"[{', '.join(f'{m:.1%}' for m in margins)}] = {norm_margin:.2%}"
    )

    if current_revenue is None or current_revenue <= 0:
        return _empty("current revenue missing — cannot apply normalised margin")

    normalized_ebit = norm_margin * current_revenue

    # ── 2. Maintenance capex ──
    # Greenwald: at zero growth the firm spends only to hold capacity flat.
    # D&A is the standard proxy. Capex above D&A is growth spending and is
    # added back to earnings, because a no-growth firm would not incur it.
    maint_capex = None
    growth_capex = None
    if depreciation is not None:
        maint_capex = depreciation
        if capex is not None:
            growth_capex = max(0.0, abs(capex) - depreciation)
            if growth_capex > 0:
                notes.append(
                    f"growth capex added back: |capex| {abs(capex):,.0f} − D&A "
                    f"{depreciation:,.0f} = {growth_capex:,.0f}. At zero growth this "
                    f"spend would not occur, so it is not a charge against earnings power"
                )
            else:
                notes.append(
                    f"capex {abs(capex):,.0f} <= D&A {depreciation:,.0f} — no growth "
                    f"capex to add back; the firm is under-investing vs depreciation"
                )
        else:
            gaps.append("capex missing — growth-capex add-back not applied (EPV understated)")
    else:
        gaps.append(
            "D&A missing — maintenance capex cannot be estimated; EPV falls back "
            "to unadjusted normalised EBIT"
        )

    adjusted_ebit = normalized_ebit + (growth_capex or 0.0)

    # ── 3. Capitalise ──
    # Plausibility ceiling, not just an arithmetic one. A 95% effective rate is
    # a valid number and a nonsense input — it usually means the denominator
    # (operating income) was near zero, not that the filer pays 95% tax. The
    # 60% bound matches the orchestrator's implied-rate screen so both places
    # agree on what "plausible" means.
    if not 0.0 <= tax_rate < _MAX_PLAUSIBLE_TAX_RATE:
        gaps.append(
            f"implausible tax rate {tax_rate:.1%} (outside 0-{_MAX_PLAUSIBLE_TAX_RATE:.0%}) "
            f"— clamped to {_DEFAULT_TAX_RATE:.0%}. Usually means operating income was "
            f"near zero, inflating the implied rate"
        )
        tax_rate = _DEFAULT_TAX_RATE
    adjusted_nopat = adjusted_ebit * (1.0 - tax_rate)
    epv_operations = adjusted_nopat / wacc

    if adjusted_nopat <= 0:
        gaps.append(
            f"normalised NOPAT {adjusted_nopat:,.0f} <= 0 — the business has no "
            f"positive earnings power at its median margin. EPV is negative and "
            f"the only remaining anchors are asset value and an explicit story"
        )

    excess_cash = (cash_and_equivalents or 0.0) + (short_term_investments or 0.0)
    net_debt = None
    if total_debt is not None:
        net_debt = total_debt - excess_cash
    else:
        gaps.append("total debt missing — EPV equity bridge incomplete")

    epv_equity = None
    if net_debt is not None:
        epv_equity = epv_operations - net_debt

    epv_per_share = None
    mos = None
    if epv_equity is not None and shares_outstanding:
        epv_per_share = epv_equity / shares_outstanding
        if current_price and current_price > 0:
            mos = (epv_per_share - current_price) / current_price
    elif epv_equity is not None:
        gaps.append("shares outstanding missing — per-share EPV unavailable")

    return EarningsPowerResult(
        op_margin_history=margins,
        normalized_op_margin=norm_margin,
        current_revenue=current_revenue,
        normalized_ebit=normalized_ebit,
        depreciation=depreciation,
        capex=capex,
        maintenance_capex=maint_capex,
        growth_capex_added_back=growth_capex,
        adjusted_ebit=adjusted_ebit,
        tax_rate=tax_rate,
        adjusted_nopat=adjusted_nopat,
        wacc=wacc,
        epv_operations=epv_operations,
        excess_cash=excess_cash,
        net_debt=net_debt,
        epv_equity=epv_equity,
        epv_per_share=epv_per_share,
        current_price=current_price,
        mos_vs_epv_pct=mos,
        data_gaps=gaps,
        notes=notes,
    )
