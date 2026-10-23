"""Reinvestment computation (ADR-027 Phase B).

Damodaran's reinvestment formula:

    reinvestment = (capex − D&A) + ΔWC
                 = net new capital spent on PP&E + change in working capital

    reinvestment_rate = reinvestment / NOPAT

The reinvestment rate ties to fundamental growth via:
    g = ROIC × reinvestment_rate

So a 20% ROIC company reinvesting 50% of NOPAT grows at 10%/yr fundamentally.
This is the discipline that says growth must be EARNED with capital.

Notes on conventions:
  - capex in our Financial table is stored as ABS value (positive). Source:
    `data/pipeline.py:709` capex_abs = abs(capex). We use that directly.
  - D&A is the depreciation_amortization field on Financial.
  - ΔWC = (current_assets_t − current_liabilities_t) − (CA_{t-1} − CL_{t-1})
    Operating WC change. Damodaran sometimes uses non-cash-WC = CA − cash −
    CL + short-term-debt; we use the simpler total-WC for first pass.

Sanity flags (not hard caps — surface in notes):
  - reinvestment_rate < 0 → company is liquidating (negative net capex or
    shrinking WC). For DCF, treat as "no reinvestment" but the implication
    is g ≤ 0.
  - reinvestment_rate > 1.5 → spending more on reinvestment than earning.
    Common for high-growth firms; the DCF will show very low/negative
    near-term FCFF. Surface for narrative attention.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReinvestmentResult:
    capex: float
    depreciation_amortization: float
    net_capex: float                          # capex − D&A
    working_capital_current: float | None     # CA_t − CL_t
    working_capital_prior: float | None       # CA_{t-1} − CL_{t-1}
    delta_working_capital: float | None       # may be None if prior period missing
    reinvestment_total: float                 # net_capex + ΔWC (treats ΔWC=0 if missing)
    nopat: float
    reinvestment_rate: float                  # reinvestment_total / NOPAT
    notes: list[str] = field(default_factory=list)


def compute_reinvestment(
    *,
    capex: float | None,
    depreciation_amortization: float | None,
    current_assets: float | None,
    current_liabilities: float | None,
    current_assets_prior: float | None,
    current_liabilities_prior: float | None,
    nopat: float,
) -> ReinvestmentResult:
    """Damodaran reinvestment from a single Financial period + prior period WC.

    Args:
        capex: From cash flow statement (positive value — already abs'd by
               the parser at materialize time).
        depreciation_amortization: From CFS.
        current_assets / current_liabilities: From balance sheet, current period.
        current_assets_prior / current_liabilities_prior: From balance sheet,
            prior period (for ΔWC).
        nopat: From compute_nopat() — must be positive (caller's responsibility;
               we error if not).

    Returns:
        ReinvestmentResult with full breakdown.
    """
    if nopat is None or nopat <= 0:
        raise ValueError(
            f"compute_reinvestment requires positive NOPAT (got {nopat}). "
            f"For Tier C filers, caller should not call this — IV is not "
            f"computable from this framework."
        )

    notes: list[str] = []

    capex_v = capex or 0.0
    da_v = depreciation_amortization or 0.0
    if capex is None:
        notes.append("capex missing — defaulted to 0")
    if depreciation_amortization is None:
        notes.append("D&A missing — defaulted to 0")

    net_capex = capex_v - da_v

    # Working capital change
    wc_now = None
    wc_prior = None
    delta_wc = None

    if current_assets is not None and current_liabilities is not None:
        wc_now = current_assets - current_liabilities

    if current_assets_prior is not None and current_liabilities_prior is not None:
        wc_prior = current_assets_prior - current_liabilities_prior

    if wc_now is not None and wc_prior is not None:
        delta_wc = wc_now - wc_prior
    else:
        notes.append(
            "ΔWC not computable (current or prior period working capital missing); "
            "treating ΔWC as 0 in reinvestment total"
        )

    reinvestment_total = net_capex + (delta_wc or 0.0)
    reinvestment_rate = reinvestment_total / nopat

    # Sanity surfacing
    if reinvestment_rate < 0:
        notes.append(
            f"Reinvestment rate {reinvestment_rate:.1%} is negative — company is "
            f"liquidating capital (capex < D&A and/or WC shrinking). Fundamental "
            f"growth will be ≤ 0. Verify capex / D&A sign convention if unexpected."
        )
    elif reinvestment_rate > 1.5:
        notes.append(
            f"Reinvestment rate {reinvestment_rate:.1%} > 150% — company spending more "
            f"on reinvestment than NOPAT. Common for high-growth firms; near-term "
            f"FCFF will be very low or negative. Narrative attention recommended."
        )

    return ReinvestmentResult(
        capex=capex_v,
        depreciation_amortization=da_v,
        net_capex=net_capex,
        working_capital_current=wc_now,
        working_capital_prior=wc_prior,
        delta_working_capital=delta_wc,
        reinvestment_total=reinvestment_total,
        nopat=nopat,
        reinvestment_rate=reinvestment_rate,
        notes=notes,
    )
