"""Reverse DCF — solve for the growth rate the market is pricing in (ADR-029).

Inverts the forward DCF: given current price (= market equity value), all
other fundamental inputs held constant, solve for the high-growth rate
that makes the DCF output equal market cap.

Mathematically: given f(g) = DCF_equity_value(growth=g, ...), find g such
that f(g) = target_equity_value. Bisection in [-5%, +40%] converges in
~40 iterations.

Output: implied growth rate + feasibility flag.

Feasibility bands (Damodaran's published caps):
  plausible:  0% - 15%  — defensible for most growth-stage companies
  aggressive: 15% - 25% — possible for elite execution
  extreme:    > 25%     — historically rare beyond 5-7 years

Per ADR-029:
  - Universal sibling output for Tier A/B
  - Tier C reverse-DCF deferred (different equation; needs scenario context)
  - Deterministic (no LLM, no network)

Public API:
    reverse_solve_growth(target_equity_value, ...) -> ReverseDCFResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from valuation.damodaran.fcff import project_fcff
from valuation.damodaran.terminal import compute_terminal_value


_BISECT_LOW = -0.05               # -5%
_BISECT_HIGH = 0.40               # +40%
_BISECT_ITERATIONS = 40           # ~sub-bp precision
_PLAUSIBLE_MAX = 0.15
_AGGRESSIVE_MAX = 0.25


@dataclass(frozen=True)
class ReverseDCFResult:
    target_equity_value: float
    target_price_per_share: float
    nopat_base: float
    wacc: float
    reinvestment_rate: float
    growth_terminal: float
    high_growth_years: int
    shares_outstanding: float
    net_debt: float

    implied_growth_rate: float | None         # None if no bracketed solution
    implied_growth_feasibility: str           # 'plausible' | 'aggressive' | 'extreme' | 'unsolvable_below' | 'unsolvable_above'

    converged: bool
    iterations_used: int

    notes: list[str] = field(default_factory=list)


def _quick_forward_iv_equity(
    *,
    nopat_base: float,
    growth: float,
    reinvestment_rate: float,
    high_growth_years: int,
    wacc: float,
    growth_terminal: float,
    risk_free_rate: float,
    net_debt: float,
) -> float | None:
    """Quick forward DCF equity value at a given growth rate. Returns None
    when the math is degenerate (WACC ≤ g, etc.)."""
    try:
        if growth >= wacc:
            return None
        proj = project_fcff(
            nopat_base=nopat_base,
            growth_rate=growth,
            reinvestment_rate=reinvestment_rate,
            high_growth_years=high_growth_years,
            wacc=wacc,
        )
        term = compute_terminal_value(
            nopat_high_growth_final=proj.nopat_projections[-1],
            growth_rate_terminal=growth_terminal,
            high_growth_years=high_growth_years,
            wacc=wacc,
            risk_free_rate=risk_free_rate,
        )
        enterprise_value = proj.pv_high_growth_fcff_total + term.terminal_value_pv
        return enterprise_value - net_debt
    except (ValueError, ZeroDivisionError):
        return None


def _classify(growth: float) -> str:
    if growth < 0:
        return "negative"  # market implies decline
    if growth <= _PLAUSIBLE_MAX:
        return "plausible"
    if growth <= _AGGRESSIVE_MAX:
        return "aggressive"
    return "extreme"


def reverse_solve_growth(
    *,
    target_equity_value: float,
    nopat_base: float,
    wacc: float,
    reinvestment_rate: float,
    growth_terminal: float,
    high_growth_years: int,
    risk_free_rate: float,
    net_debt: float,
    shares_outstanding: float,
) -> ReverseDCFResult:
    """Bisect on growth_rate_high to find the value implied by current price.

    Holds all other DCF inputs constant; varies only growth_rate_high.

    Args:
        target_equity_value: Current market equity value (price × shares).
        nopat_base: Same NOPAT used by the forward DCF.
        wacc: Same WACC.
        reinvestment_rate: Same reinvestment rate.
        growth_terminal: Same terminal growth (capped at risk-free).
        high_growth_years: Same projection horizon.
        risk_free_rate: For sanity bounds.
        net_debt: For equity-value conversion.
        shares_outstanding: For per-share target.

    Returns:
        ReverseDCFResult with implied growth + feasibility flag.
    """
    notes: list[str] = []

    if target_equity_value <= 0:
        notes.append(f"target_equity_value = {target_equity_value} ≤ 0; cannot bisect")
        return ReverseDCFResult(
            target_equity_value=target_equity_value,
            target_price_per_share=target_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0,
            nopat_base=nopat_base, wacc=wacc, reinvestment_rate=reinvestment_rate,
            growth_terminal=growth_terminal, high_growth_years=high_growth_years,
            shares_outstanding=shares_outstanding, net_debt=net_debt,
            implied_growth_rate=None, implied_growth_feasibility="unsolvable_below",
            converged=False, iterations_used=0, notes=notes,
        )

    # Sanity: WACC must exceed bisection lower bracket
    if wacc <= _BISECT_LOW:
        notes.append(f"WACC {wacc:.2%} too low for bisection bracket")
        return ReverseDCFResult(
            target_equity_value=target_equity_value,
            target_price_per_share=target_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0,
            nopat_base=nopat_base, wacc=wacc, reinvestment_rate=reinvestment_rate,
            growth_terminal=growth_terminal, high_growth_years=high_growth_years,
            shares_outstanding=shares_outstanding, net_debt=net_debt,
            implied_growth_rate=None, implied_growth_feasibility="unsolvable_below",
            converged=False, iterations_used=0, notes=notes,
        )

    # Effective upper bound: min(_BISECT_HIGH, wacc − 50bps) — past this, DCF math breaks
    hi = min(_BISECT_HIGH, wacc - 0.005)
    lo = _BISECT_LOW

    # Evaluate at endpoints
    iv_lo = _quick_forward_iv_equity(
        nopat_base=nopat_base, growth=lo, reinvestment_rate=reinvestment_rate,
        high_growth_years=high_growth_years, wacc=wacc, growth_terminal=growth_terminal,
        risk_free_rate=risk_free_rate, net_debt=net_debt,
    )
    iv_hi = _quick_forward_iv_equity(
        nopat_base=nopat_base, growth=hi, reinvestment_rate=reinvestment_rate,
        high_growth_years=high_growth_years, wacc=wacc, growth_terminal=growth_terminal,
        risk_free_rate=risk_free_rate, net_debt=net_debt,
    )

    if iv_lo is None or iv_hi is None:
        notes.append("forward DCF degenerate at endpoints — cannot bracket")
        return ReverseDCFResult(
            target_equity_value=target_equity_value,
            target_price_per_share=target_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0,
            nopat_base=nopat_base, wacc=wacc, reinvestment_rate=reinvestment_rate,
            growth_terminal=growth_terminal, high_growth_years=high_growth_years,
            shares_outstanding=shares_outstanding, net_debt=net_debt,
            implied_growth_rate=None, implied_growth_feasibility="unsolvable_below",
            converged=False, iterations_used=0, notes=notes,
        )

    # Check bracket: market value should be between IV(g_lo) and IV(g_hi)
    if target_equity_value < iv_lo:
        notes.append(
            f"Market value ${target_equity_value/1e9:.2f}B is BELOW IV at g={lo:.0%} "
            f"(${iv_lo/1e9:.2f}B). Market is implying growth < {lo:.0%} — economic decline."
        )
        return ReverseDCFResult(
            target_equity_value=target_equity_value,
            target_price_per_share=target_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0,
            nopat_base=nopat_base, wacc=wacc, reinvestment_rate=reinvestment_rate,
            growth_terminal=growth_terminal, high_growth_years=high_growth_years,
            shares_outstanding=shares_outstanding, net_debt=net_debt,
            implied_growth_rate=lo, implied_growth_feasibility="unsolvable_below",
            converged=False, iterations_used=0, notes=notes,
        )

    if target_equity_value > iv_hi:
        notes.append(
            f"Market value ${target_equity_value/1e9:.2f}B is ABOVE IV at g={hi:.0%} "
            f"(${iv_hi/1e9:.2f}B). Market is implying growth > {hi:.0%}. Bracket exhausted."
        )
        return ReverseDCFResult(
            target_equity_value=target_equity_value,
            target_price_per_share=target_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0,
            nopat_base=nopat_base, wacc=wacc, reinvestment_rate=reinvestment_rate,
            growth_terminal=growth_terminal, high_growth_years=high_growth_years,
            shares_outstanding=shares_outstanding, net_debt=net_debt,
            implied_growth_rate=hi, implied_growth_feasibility="extreme",
            converged=False, iterations_used=0, notes=notes,
        )

    # Bisection — monotonic-increasing IV(g) (assumed) means we narrow on target
    iterations = 0
    for _ in range(_BISECT_ITERATIONS):
        iterations += 1
        mid = (lo + hi) / 2
        iv_mid = _quick_forward_iv_equity(
            nopat_base=nopat_base, growth=mid, reinvestment_rate=reinvestment_rate,
            high_growth_years=high_growth_years, wacc=wacc, growth_terminal=growth_terminal,
            risk_free_rate=risk_free_rate, net_debt=net_debt,
        )
        if iv_mid is None:
            hi = mid  # treat degenerate as "too high"
            continue
        if iv_mid > target_equity_value:
            hi = mid
        else:
            lo = mid
        if abs(hi - lo) < 1e-5:
            break

    implied_g = (lo + hi) / 2
    feasibility = _classify(implied_g)

    return ReverseDCFResult(
        target_equity_value=target_equity_value,
        target_price_per_share=target_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0,
        nopat_base=nopat_base, wacc=wacc, reinvestment_rate=reinvestment_rate,
        growth_terminal=growth_terminal, high_growth_years=high_growth_years,
        shares_outstanding=shares_outstanding, net_debt=net_debt,
        implied_growth_rate=implied_g, implied_growth_feasibility=feasibility,
        converged=True, iterations_used=iterations, notes=notes,
    )
