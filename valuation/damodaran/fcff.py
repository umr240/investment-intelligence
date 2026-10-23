"""FCFF projection over the high-growth period (ADR-027 Phase B).

Free Cash Flow to Firm:
    FCFF_t = NOPAT_t × (1 − reinvestment_rate_t)

In a constant-growth high-growth phase:
    NOPAT_{t+1} = NOPAT_t × (1 + g)
    reinvestment_rate is constant (or trends toward terminal)
    FCFF_t = NOPAT_t × (1 − reinvestment_rate)

Damodaran's discipline (ADR-027 §Context):
    - High-growth period: 5-10yr depending on competitive position (default 8)
    - Constant g during high-growth phase (simpler, defensible)
    - Reinvestment rate transitions: if terminal g < high g, terminal
      reinvestment rate = g_terminal / ROIC_terminal (lower than high-growth)

This module produces:
    1. Project NOPAT and FCFF for years 1..N at constant g
    2. Discount each year's FCFF back to present at WACC
    3. Return per-year FCFF and PV-of-FCFF

Terminal-value computation is in terminal.py — separate module because
the "transition to stable growth" assumption requires its own discipline.

Public API:
    project_fcff(...) -> FCFFProjection
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FCFFProjection:
    nopat_base: float                          # starting NOPAT (year 0)
    growth_rate: float                          # high-growth g per year
    reinvestment_rate: float                    # high-growth reinvestment rate
    high_growth_years: int                      # N years of explicit projection
    wacc: float                                 # discount rate

    # Per-year projections (length = high_growth_years)
    nopat_projections: list[float]
    fcff_projections: list[float]
    discount_factors: list[float]
    fcff_pv_projections: list[float]            # FCFF × discount_factor

    # Aggregates
    pv_high_growth_fcff_total: float            # Σ(FCFF_t × DF_t)
    notes: list[str] = field(default_factory=list)


def project_fcff(
    *,
    nopat_base: float,
    growth_rate: float,
    reinvestment_rate: float,
    high_growth_years: int,
    wacc: float,
) -> FCFFProjection:
    """Project FCFF over the high-growth phase and discount to present.

    Args:
        nopat_base: NOPAT for year 0 (most recent fiscal year or LTM).
        growth_rate: Constant g during high-growth phase (decimal).
        reinvestment_rate: Constant reinvestment rate (decimal).
        high_growth_years: Length of high-growth phase (typically 5-10).
        wacc: Cost of capital (decimal).

    Returns:
        FCFFProjection with per-year values + aggregates.

    Notes:
        - If reinvestment_rate > 1.0, the early-year FCFF will be negative.
          That is correct — companies that reinvest more than they earn have
          negative free cash flow in the near term. The terminal value carries
          most of the IV in that case.
        - If WACC < growth_rate, the DCF formula breaks (discounting fails).
          We raise ValueError; caller should adjust assumptions.
    """
    if high_growth_years <= 0:
        raise ValueError(f"high_growth_years must be > 0, got {high_growth_years}")
    if wacc <= 0:
        raise ValueError(f"wacc must be > 0, got {wacc}")
    if growth_rate >= wacc:
        raise ValueError(
            f"growth_rate ({growth_rate:.2%}) >= wacc ({wacc:.2%}). "
            "DCF requires WACC > g during high-growth phase. Reduce growth "
            "or revisit cost-of-capital inputs."
        )
    if nopat_base <= 0:
        raise ValueError(
            f"nopat_base must be > 0, got {nopat_base}. Tier C filers should "
            "not reach this projection."
        )

    notes: list[str] = []
    if reinvestment_rate > 1.0:
        notes.append(
            f"reinvestment_rate {reinvestment_rate:.1%} > 100% — FCFF will be "
            f"negative during high-growth phase. Most of IV will come from "
            f"terminal value."
        )

    nopats: list[float] = []
    fcffs: list[float] = []
    dfs: list[float] = []
    pvs: list[float] = []

    nopat_t = nopat_base
    for year in range(1, high_growth_years + 1):
        nopat_t = nopat_t * (1.0 + growth_rate)
        fcff_t = nopat_t * (1.0 - reinvestment_rate)
        df = 1.0 / ((1.0 + wacc) ** year)
        pv = fcff_t * df

        nopats.append(nopat_t)
        fcffs.append(fcff_t)
        dfs.append(df)
        pvs.append(pv)

    return FCFFProjection(
        nopat_base=nopat_base,
        growth_rate=growth_rate,
        reinvestment_rate=reinvestment_rate,
        high_growth_years=high_growth_years,
        wacc=wacc,
        nopat_projections=nopats,
        fcff_projections=fcffs,
        discount_factors=dfs,
        fcff_pv_projections=pvs,
        pv_high_growth_fcff_total=sum(pvs),
        notes=notes,
    )
