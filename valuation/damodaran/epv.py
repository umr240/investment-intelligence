"""Earnings Power Value (EPV) — Greenwald's no-growth floor anchor (ADR-029).

EPV is the value of a company assuming:
  - No growth (g = 0)
  - No reinvestment (capex = D&A, ΔWC = 0)
  - Current NOPAT continues in perpetuity

The math reduces to Gordon perpetuity:

    EPV_total = NOPAT × (1 / WACC)
    EPV_equity = EPV_total − net_debt
    EPV_per_share = EPV_equity / shares_outstanding

This is the FLOOR of fundamental valuation. ADR-027's forward DCF (with
g = ROIC × reinvestment_rate) sits above EPV when the company creates
value through reinvestment; it sits BELOW EPV when current reinvestment
is value-destroying (ROIC < WACC × reinvestment_rate). The latter is a
diagnostic signal worth surfacing (HIMS-class: ADR-027 IV < EPV means
"current reinvest plan is destroying value vs steady-state").

Per ADR-029:
  - Universal sibling output — fires on every IV computation regardless of tier
  - Deterministic (no LLM, no network)
  - data_gaps surface when NOPAT < 0 (EPV becomes negative — narrative trade)

Public API:
    compute_epv(nopat, wacc, net_debt, shares_outstanding) -> EPVResult
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EPVResult:
    """Greenwald EPV — earnings power value at zero growth."""

    nopat: float                        # current normalized NOPAT
    wacc: float                         # discount rate
    epv_total: float                    # NOPAT / WACC — enterprise-value perpetuity
    net_debt: float                     # total debt − cash − ST investments
    epv_equity: float                   # epv_total − net_debt
    shares_outstanding: float
    epv_per_share: float                # epv_equity / shares_outstanding

    current_price: float                # for MoS calc
    mos_vs_epv_pct: float | None        # (epv_per_share − price) / price; None when price ≤ 0

    notes: list[str] = field(default_factory=list)


def compute_epv(
    *,
    nopat: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float,
) -> EPVResult:
    """Compute EPV from current NOPAT capitalized at WACC.

    Args:
        nopat: Current-period NOPAT (EBIT × (1 − tax)). May be negative;
               we report it through but flag in notes.
        wacc: Cost of capital (decimal).
        net_debt: total_debt − cash − short_term_investments. Negative for
                  net-cash filers.
        shares_outstanding: For per-share conversion. Must be > 0.
        current_price: For margin-of-safety calc.

    Returns:
        EPVResult with full breakdown + notes for edge cases.

    Notes:
        - When NOPAT ≤ 0, EPV is negative. We report the negative number
          and flag "EPV negative — narrative is the only anchor."
        - When WACC ≤ 0 (degenerate), we return EPV = 0 with a data gap.
        - When shares_outstanding ≤ 0, epv_per_share = 0 and we flag.
    """
    notes: list[str] = []

    if wacc <= 0:
        notes.append(f"WACC = {wacc:.2%} ≤ 0 — EPV undefined; returning 0")
        return EPVResult(
            nopat=nopat, wacc=wacc, epv_total=0.0, net_debt=net_debt,
            epv_equity=0.0, shares_outstanding=shares_outstanding,
            epv_per_share=0.0, current_price=current_price,
            mos_vs_epv_pct=None, notes=notes,
        )

    epv_total = nopat / wacc
    epv_equity = epv_total - net_debt

    if shares_outstanding <= 0:
        notes.append("shares_outstanding ≤ 0 — per-share EPV not computable")
        return EPVResult(
            nopat=nopat, wacc=wacc, epv_total=epv_total, net_debt=net_debt,
            epv_equity=epv_equity, shares_outstanding=shares_outstanding,
            epv_per_share=0.0, current_price=current_price,
            mos_vs_epv_pct=None, notes=notes,
        )

    epv_per_share = epv_equity / shares_outstanding

    if nopat <= 0:
        notes.append(
            f"EPV negative (NOPAT = ${nopat/1e6:,.0f}M ≤ 0). Current cash-flow "
            f"floor is below zero — narrative is the only anchor. For Tier C "
            f"tickers, use the young-company scenario IV (ADR-028) as the "
            f"valuation anchor; EPV is informative only as 'how far below "
            f"break-even is this filer today?'"
        )

    mos_vs_epv = None
    if current_price > 0:
        mos_vs_epv = (epv_per_share - current_price) / current_price

    return EPVResult(
        nopat=nopat,
        wacc=wacc,
        epv_total=epv_total,
        net_debt=net_debt,
        epv_equity=epv_equity,
        shares_outstanding=shares_outstanding,
        epv_per_share=epv_per_share,
        current_price=current_price,
        mos_vs_epv_pct=mos_vs_epv,
        notes=notes,
    )
