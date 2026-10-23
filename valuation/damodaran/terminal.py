"""Terminal value via Gordon growth (ADR-027 Phase B).

Damodaran's terminal value formula:

    TV = FCFF_{N+1} / (WACC − g_terminal)

where FCFF_{N+1} is the first stable-growth year's FCFF. The discipline:

  1. **g_terminal ≤ risk_free_rate** (HARD CAP per ADR-027)
     - No business can grow faster than the economy forever
     - Risk-free rate is the long-run nominal economy growth proxy
     - This caps the terminal value to a reasonable multiple

  2. **Stable-phase reinvestment ties to terminal growth**:
     - If g_terminal = ROIC × reinvest_rate_terminal, then for steady state:
     - reinvest_rate_terminal = g_terminal / ROIC_terminal
     - For mature firms, ROIC_terminal often = cost of capital (no excess
       returns in equilibrium), making reinvest_rate_terminal = g_terminal / WACC
     - But for moaty firms with sustainable ROIC > WACC, terminal ROIC can
       be higher; we take that as caller's choice.

  3. **Discount TV back to present**: TV / (1 + WACC)^N

  4. **Terminal value share of total IV**: Damodaran requires this be
     surfaced — when TV is >80% of total IV, the valuation is essentially
     all about the terminal assumption, and the high-growth phase is window
     dressing. Caller must verify the terminal assumption holds.

Public API:
    compute_terminal_value(...) -> TerminalValueResult
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TerminalValueResult:
    nopat_terminal: float                       # NOPAT in year N+1
    growth_rate_terminal: float
    reinvestment_rate_terminal: float
    fcff_terminal: float                        # FCFF in year N+1 (first stable year)
    wacc: float
    terminal_value: float                        # TV at end of year N (undiscounted)
    discount_factor_n: float                     # 1 / (1+WACC)^N
    terminal_value_pv: float                     # TV discounted to present

    # Diagnostics
    risk_free_rate: float
    g_capped_at_rf: bool                          # True if g_terminal hit Rf ceiling
    notes: list[str] = field(default_factory=list)


def compute_terminal_value(
    *,
    nopat_high_growth_final: float,              # NOPAT at end of year N (high-growth final)
    growth_rate_terminal: float,
    high_growth_years: int,
    wacc: float,
    risk_free_rate: float,
    reinvestment_rate_terminal: float | None = None,
    roic_terminal: float | None = None,
) -> TerminalValueResult:
    """Compute Gordon-growth terminal value, discounted to present.

    Args:
        nopat_high_growth_final: NOPAT in year N (the last high-growth year).
                                  Year N+1 NOPAT = this × (1 + g_terminal).
        growth_rate_terminal: Stable-phase growth rate. Capped at risk_free_rate.
        high_growth_years: Length of high-growth phase (for discounting TV back).
        wacc: Cost of capital.
        risk_free_rate: HARD CEILING on terminal growth.
        reinvestment_rate_terminal: Optional explicit terminal reinvestment rate.
                                     If None, computed from g_terminal / roic_terminal.
        roic_terminal: Optional terminal ROIC. If None, defaults to WACC (no
                       excess returns in stable phase — Damodaran's typical
                       assumption for mature firms).

    Returns:
        TerminalValueResult with full breakdown.

    Notes:
        - g_terminal is HARD-CAPPED at risk_free_rate. If caller passes a
          higher value, we cap it and flag in notes.
        - If WACC ≤ g_terminal after capping, formula explodes — we error.
          Caller should adjust.
    """
    if wacc <= 0:
        raise ValueError(f"wacc must be > 0, got {wacc}")
    if high_growth_years <= 0:
        raise ValueError(f"high_growth_years must be > 0, got {high_growth_years}")
    if nopat_high_growth_final <= 0:
        raise ValueError(
            f"nopat_high_growth_final must be > 0, got {nopat_high_growth_final}"
        )

    notes: list[str] = []

    # Hard cap on terminal growth at risk-free rate
    g_capped = False
    g_term = growth_rate_terminal
    if g_term > risk_free_rate:
        notes.append(
            f"Terminal growth {growth_rate_terminal:.2%} exceeds risk-free rate "
            f"{risk_free_rate:.2%}; capped at Rf per Damodaran's discipline. "
            f"No business grows faster than the economy forever."
        )
        g_term = risk_free_rate
        g_capped = True

    if wacc <= g_term:
        raise ValueError(
            f"After capping, terminal growth ({g_term:.2%}) >= WACC ({wacc:.2%}). "
            f"Gordon growth formula breaks. Reduce terminal growth (or revisit "
            f"WACC inputs)."
        )

    # Terminal reinvestment rate
    if reinvestment_rate_terminal is None:
        # Damodaran's typical default: ROIC_terminal = WACC (no excess returns),
        # so reinvest_rate_terminal = g_terminal / WACC.
        # For moaty firms with sustainable ROIC > WACC, caller should pass
        # roic_terminal explicitly.
        roic_t = roic_terminal if roic_terminal is not None else wacc
        if roic_t <= 0:
            raise ValueError(
                f"Computed terminal ROIC = {roic_t} ≤ 0; cannot derive "
                "terminal reinvestment rate."
            )
        reinvest_t = g_term / roic_t
        notes.append(
            f"Terminal reinvestment rate derived: g_term/ROIC_term = "
            f"{g_term:.2%}/{roic_t:.2%} = {reinvest_t:.2%}. "
            f"Assumes ROIC_terminal = {'WACC (no excess returns)' if roic_terminal is None else 'caller-specified'}."
        )
    else:
        reinvest_t = reinvestment_rate_terminal

    if reinvest_t < 0 or reinvest_t > 1.0:
        notes.append(
            f"Terminal reinvestment rate {reinvest_t:.1%} outside [0, 100%]. "
            f"Sanity check inputs."
        )

    # FCFF in year N+1
    nopat_terminal = nopat_high_growth_final * (1.0 + g_term)
    fcff_terminal = nopat_terminal * (1.0 - reinvest_t)

    # Gordon growth: TV at end of year N = FCFF_{N+1} / (WACC − g_terminal)
    tv = fcff_terminal / (wacc - g_term)

    # Discount TV back to present
    df_n = 1.0 / ((1.0 + wacc) ** high_growth_years)
    tv_pv = tv * df_n

    return TerminalValueResult(
        nopat_terminal=nopat_terminal,
        growth_rate_terminal=g_term,
        reinvestment_rate_terminal=reinvest_t,
        fcff_terminal=fcff_terminal,
        wacc=wacc,
        terminal_value=tv,
        discount_factor_n=df_n,
        terminal_value_pv=tv_pv,
        risk_free_rate=risk_free_rate,
        g_capped_at_rf=g_capped,
        notes=notes,
    )
