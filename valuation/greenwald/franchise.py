"""The franchise test — EPV vs Asset Value (ADR-042).

This is the payload of the Greenwald framework and the thing no DCF produces.

A competitor contemplating entry must spend the Asset Reproduction Value (AV)
to build an equivalent business. If they do, they earn — at best — the
Earnings Power Value (EPV). So the RATIO tells you whether entry is rational:

    EPV / AV > 1.3   FRANCHISE. Earnings power materially exceeds what it costs
                     to recreate the assets. Either barriers to entry exist, or
                     competitors are irrational. Growth here is worth something,
                     because incremental capital earns above its cost.

    0.8 - 1.3        NO FRANCHISE. Commodity economics: returns have competed
                     down to roughly the cost of assembling the assets. This is
                     the DEFAULT state of business and the null hypothesis.
                     Growth is worth approximately ZERO — a critical result,
                     because a DCF will happily assign it value anyway.

    < 0.8            VALUE DESTRUCTION. The assets earn less than they cost to
                     assemble. Either the industry is impaired, or management is
                     reinvesting below the cost of capital. Growth is NEGATIVE
                     value: every dollar retained destroys wealth.

Why this matters next to Damodaran: a forward DCF prices growth by assumption.
It will assign large value to a fast-growing commodity business, because g is
an input. The franchise test asks whether that growth is defensible before it
is valued (`moat/challenger_inversion_test`, `core/inversion`). When the two
engines disagree — high DCF, no franchise — the disagreement IS the finding.

Deterministic. No LLM, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FRANCHISE = "franchise"
NO_FRANCHISE = "no_franchise"
VALUE_DESTRUCTION = "value_destruction"
INDETERMINATE = "indeterminate"

_FRANCHISE_RATIO = 1.30
_DESTRUCTION_RATIO = 0.80


@dataclass(frozen=True)
class FranchiseResult:
    verdict: str
    epv_to_av_ratio: float | None
    epv_operations: float | None
    asset_value_total: float | None
    excess_earnings: float | None          # EPV − AV, the franchise's dollar value
    growth_is_worth_paying_for: bool | None
    interpretation: str
    data_gaps: list[str] = field(default_factory=list)


def assess_franchise(
    *,
    epv_operations: float | None,
    asset_value_total: float | None,
) -> FranchiseResult:
    """Compare earnings power to reproduction cost. Refuses on missing inputs."""
    gaps: list[str] = []

    if epv_operations is None or asset_value_total is None:
        missing = []
        if epv_operations is None:
            missing.append("EPV")
        if asset_value_total is None:
            missing.append("asset value")
        gaps.append(
            f"franchise test unavailable — {' and '.join(missing)} could not be "
            f"computed. Without both legs the moat question is UNEVAL, not 'no moat'"
        )
        return FranchiseResult(
            verdict=INDETERMINATE, epv_to_av_ratio=None,
            epv_operations=epv_operations, asset_value_total=asset_value_total,
            excess_earnings=None, growth_is_worth_paying_for=None,
            interpretation="Insufficient data to test for a franchise.",
            data_gaps=gaps,
        )

    if asset_value_total <= 0:
        gaps.append(
            f"asset value {asset_value_total:,.0f} <= 0 — reproduction cost is "
            f"non-positive, so the ratio is meaningless. Typically an asset-light "
            f"filer whose reproduction cost sits almost entirely in intangibles "
            f"this module could not measure"
        )
        return FranchiseResult(
            verdict=INDETERMINATE, epv_to_av_ratio=None,
            epv_operations=epv_operations, asset_value_total=asset_value_total,
            excess_earnings=None, growth_is_worth_paying_for=None,
            interpretation="Asset value non-positive — franchise ratio undefined.",
            data_gaps=gaps,
        )

    ratio = epv_operations / asset_value_total
    excess = epv_operations - asset_value_total

    if epv_operations <= 0:
        verdict = VALUE_DESTRUCTION
        interp = (
            f"EPV is negative ({epv_operations:,.0f}) against an asset base costing "
            f"{asset_value_total:,.0f} to reproduce. At its median historical margin "
            f"this business does not earn. Growth destroys value; only an explicit "
            f"turnaround or scaling story can justify a valuation."
        )
        growth_ok = False
    elif ratio >= _FRANCHISE_RATIO:
        verdict = FRANCHISE
        interp = (
            f"Earnings power is {ratio:.2f}x reproduction cost — a franchise worth "
            f"{excess:,.0f} above the cost of its assets. A competitor spending "
            f"{asset_value_total:,.0f} could not replicate these earnings, which "
            f"implies a barrier to entry. Growth is worth paying for here, because "
            f"incremental capital earns above its cost. Now invert: what would have "
            f"to change for the barrier to fall?"
        )
        growth_ok = True
    elif ratio >= _DESTRUCTION_RATIO:
        verdict = NO_FRANCHISE
        interp = (
            f"Earnings power is {ratio:.2f}x reproduction cost — inside the commodity "
            f"band. Returns have competed down to roughly the cost of assembling the "
            f"assets, which is the NORMAL state of business, not an indictment. "
            f"Critically: growth is worth approximately ZERO here. A DCF will still "
            f"assign it value, so treat a high forward IV on this name with suspicion."
        )
        growth_ok = False
    else:
        verdict = VALUE_DESTRUCTION
        interp = (
            f"Earnings power is only {ratio:.2f}x reproduction cost — the assets earn "
            f"less than it costs to assemble them ({excess:,.0f} shortfall). Either "
            f"the industry is impaired or capital is being reinvested below its cost. "
            f"Retained earnings destroy value; the honest questions are liquidation "
            f"value and whether management will stop reinvesting."
        )
        growth_ok = False

    return FranchiseResult(
        verdict=verdict,
        epv_to_av_ratio=ratio,
        epv_operations=epv_operations,
        asset_value_total=asset_value_total,
        excess_earnings=excess,
        growth_is_worth_paying_for=growth_ok,
        interpretation=interp,
        data_gaps=gaps,
    )
