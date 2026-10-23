"""WACC × terminal-growth sensitivity matrix (ADR-027 Phase B).

Per ADR-027 §Risks, **every IV output ships with a sensitivity matrix**
because terminal value typically dominates (60-80% of total IV) and is
highly sensitive to both inputs.

Default grid:
    WACC: base ± 100bps in 50bps steps → 5 values
    g_terminal: base ± 50bps in 25bps steps → 5 values

Output is a 5×5 list-of-lists of intrinsic-value-per-share values. The
dive renderer presents:
    - IV range (P5 / median / P95 of the grid)
    - Margin of safety uses P25 (conservative lower bound)
    - The full grid is in the JSON for narrative reasoning

Public API:
    sensitivity_grid(...) -> SensitivityResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class SensitivityResult:
    wacc_axis: list[float]                       # 5 values
    growth_terminal_axis: list[float]             # 5 values
    iv_per_share_grid: list[list[float]]          # 5×5, [wacc_idx][g_idx]
    iv_total_grid: list[list[float]]              # 5×5 enterprise-value version

    # Summary statistics across the grid
    iv_per_share_p5: float
    iv_per_share_p25: float
    iv_per_share_median: float
    iv_per_share_p75: float
    iv_per_share_p95: float

    base_wacc: float
    base_growth_terminal: float
    notes: list[str] = field(default_factory=list)


def _percentile(sorted_values: list[float], p: float) -> float:
    """Simple percentile (linear interpolation). p in [0, 100]."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = (p / 100.0) * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def sensitivity_grid(
    *,
    base_wacc: float,
    base_growth_terminal: float,
    risk_free_rate: float,
    compute_iv_per_share: Callable[[float, float], tuple[float, float] | None],
    wacc_step_bps: int = 50,
    wacc_steps_each_side: int = 2,
    growth_step_bps: int = 25,
    growth_steps_each_side: int = 2,
) -> SensitivityResult:
    """Build a sensitivity grid by re-running the IV calc at perturbed inputs.

    Args:
        base_wacc: Base case WACC (decimal).
        base_growth_terminal: Base case terminal growth (decimal).
        risk_free_rate: Used as hard ceiling on the growth axis.
        compute_iv_per_share: Callback (wacc, g_term) -> (iv_per_share, iv_total)
                              OR None if that grid cell breaks (e.g., WACC < g).
                              Caller wires this to the full intrinsic_value calc.
        wacc_step_bps / wacc_steps_each_side: WACC axis configuration.
                                              Default = 5 cells, ±100bps in 50bps.
        growth_step_bps / growth_steps_each_side: Growth axis configuration.
                                                  Default = 5 cells, ±50bps in 25bps.

    Returns:
        SensitivityResult. Cells that broke (None from callback) get the
        median of the valid cells as a placeholder, with a note flagged.
    """
    # Build axes
    wacc_axis = [
        base_wacc + (i - wacc_steps_each_side) * (wacc_step_bps / 10000.0)
        for i in range(2 * wacc_steps_each_side + 1)
    ]
    g_axis_raw = [
        base_growth_terminal + (i - growth_steps_each_side) * (growth_step_bps / 10000.0)
        for i in range(2 * growth_steps_each_side + 1)
    ]
    # Apply Rf cap to growth axis (no growth cell above Rf)
    g_axis = [min(g, risk_free_rate) for g in g_axis_raw]

    iv_per_share_grid: list[list[float]] = []
    iv_total_grid: list[list[float]] = []
    valid_values: list[float] = []
    broken_cells = 0

    notes: list[str] = []

    for w in wacc_axis:
        row_ps: list[float] = []
        row_total: list[float] = []
        for g in g_axis:
            try:
                result = compute_iv_per_share(w, g)
            except (ValueError, ZeroDivisionError):
                result = None
            if result is None:
                # Cell broke (e.g., WACC < g). Use placeholder; replace at end.
                row_ps.append(float("nan"))
                row_total.append(float("nan"))
                broken_cells += 1
            else:
                ivps, ivt = result
                row_ps.append(ivps)
                row_total.append(ivt)
                valid_values.append(ivps)
        iv_per_share_grid.append(row_ps)
        iv_total_grid.append(row_total)

    if broken_cells > 0:
        notes.append(
            f"Sensitivity grid: {broken_cells}/{len(wacc_axis) * len(g_axis)} "
            f"cells broke (WACC < g or invalid inputs at the corners); using "
            f"median of valid cells as placeholders. Verify base case is well "
            f"away from the WACC ≈ g boundary."
        )

    # Replace NaN with median of valid values
    if valid_values:
        median = sorted(valid_values)[len(valid_values) // 2]
        iv_per_share_grid = [
            [median if (v != v) else v for v in row]
            for row in iv_per_share_grid
        ]
        iv_total_grid = [
            [median if (v != v) else v for v in row]
            for row in iv_total_grid
        ]
    else:
        notes.append(
            "Sensitivity grid: ALL cells broke. IV cannot be bracketed. "
            "Base case inputs are degenerate."
        )

    # Percentile stats across the grid (flatten)
    flat = sorted([
        v for row in iv_per_share_grid for v in row if v == v  # filter NaN
    ])

    return SensitivityResult(
        wacc_axis=wacc_axis,
        growth_terminal_axis=g_axis,
        iv_per_share_grid=iv_per_share_grid,
        iv_total_grid=iv_total_grid,
        iv_per_share_p5=_percentile(flat, 5),
        iv_per_share_p25=_percentile(flat, 25),
        iv_per_share_median=_percentile(flat, 50),
        iv_per_share_p75=_percentile(flat, 75),
        iv_per_share_p95=_percentile(flat, 95),
        base_wacc=base_wacc,
        base_growth_terminal=base_growth_terminal,
        notes=notes,
    )
