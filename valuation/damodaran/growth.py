"""Fundamental growth rate (ADR-027 Phase B).

Damodaran's core identity:

    g = ROIC × reinvestment_rate

where ROIC = NOPAT / invested_capital. This says growth is EARNED by
reinvesting at the company's return on capital — companies cannot grow
faster than what their capital base + return rate support.

Sanity caps (Damodaran's discipline — surface, don't silently clamp):
  - g_max for high-growth phase: 25% (his published cap for most industries)
  - g_min: -10% (companies can shrink in mature phase but not perpetually)
  - When ROIC is extremely high (>40%), the formula can suggest g > 20%
    even with modest reinvestment. Story-discipline test: would the market
    really tolerate 25% growth for 5+ years? Usually no — surface as a flag.

Public API:
  compute_fundamental_growth(roic, reinvestment_rate) -> GrowthResult
"""
from __future__ import annotations

from dataclasses import dataclass, field


_HIGH_GROWTH_CAP = 0.25       # 25%/yr — Damodaran's general high-growth cap
_HIGH_GROWTH_FLOOR = -0.10    # -10%/yr — can't shrink forever
_PERPETUITY_SUSPECT = 0.20    # >20% sustained for 5+ years is rare; flag


@dataclass(frozen=True)
class GrowthResult:
    roic: float
    reinvestment_rate: float
    fundamental_growth_rate: float            # ROIC × reinvestment_rate
    growth_rate_capped: float                  # after sanity caps
    cap_applied: str | None                    # "max" / "min" / None
    notes: list[str] = field(default_factory=list)


def compute_fundamental_growth(
    roic: float | None,
    reinvestment_rate: float | None,
    high_growth_cap: float = _HIGH_GROWTH_CAP,
    high_growth_floor: float = _HIGH_GROWTH_FLOOR,
) -> GrowthResult:
    """Fundamental growth = ROIC × reinvestment_rate, clipped to sanity bounds.

    Args:
        roic: NOPAT / invested_capital. Can be from PT-adjusted ROIC in Tier B.
        reinvestment_rate: From reinvestment.compute_reinvestment().
        high_growth_cap: Default 25%/yr. Override per industry if needed.
        high_growth_floor: Default -10%/yr.

    Returns:
        GrowthResult with raw + capped values.
    """
    notes: list[str] = []

    if roic is None:
        raise ValueError(
            "compute_fundamental_growth requires non-None ROIC. "
            "Tier C filers should not reach this function."
        )
    if reinvestment_rate is None:
        raise ValueError(
            "compute_fundamental_growth requires non-None reinvestment_rate."
        )

    raw = roic * reinvestment_rate

    # Apply sanity caps
    cap_applied: str | None = None
    capped = raw
    if raw > high_growth_cap:
        capped = high_growth_cap
        cap_applied = "max"
        notes.append(
            f"Fundamental g = ROIC × reinv = {roic:.1%} × {reinvestment_rate:.1%} "
            f"= {raw:.1%}; capped at high-growth ceiling {high_growth_cap:.1%}. "
            f"Damodaran's discipline: sustained >25% growth is rare and should "
            f"be defended in the narrative story, not assumed."
        )
    elif raw < high_growth_floor:
        capped = high_growth_floor
        cap_applied = "min"
        notes.append(
            f"Fundamental g = {raw:.1%} below floor {high_growth_floor:.1%}; "
            f"clamped. Narrative attention: company is liquidating or in "
            f"structural decline."
        )

    if cap_applied is None and raw > _PERPETUITY_SUSPECT:
        notes.append(
            f"Fundamental g = {raw:.1%} is sustainable per the formula, but "
            f">20% growth maintained over 5+yr is historically rare. Verify "
            f"the story supports it (TAM headroom, moat width, competitive "
            f"dynamics)."
        )

    return GrowthResult(
        roic=roic,
        reinvestment_rate=reinvestment_rate,
        fundamental_growth_rate=raw,
        growth_rate_capped=capped,
        cap_applied=cap_applied,
        notes=notes,
    )
