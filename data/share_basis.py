"""Which split basis an EDGAR share count is expressed on.

SEC EDGAR is authoritative for the count itself (SECURITY & PRIVACY §4). The
problem is not the value but its basis: filings report as-filed, and our
restatement rule keeps the latest-filed value per fiscal year, so a year whose
comparatives appeared in a post-split filing carries a restated count while
earlier years do not. CSGP's FY2019/FY2020 read 363M/381M against an actual
~37M/39M because the 2021-06-28 10:1 split restated exactly those two years.

A mixed-basis series paired with split-adjusted prices misstates historical
market cap by the split ratio — CSGP produced EV/Revenue of 0.101 and -0.184.

With several splits pending, a value can sit on any INTERMEDIATE basis: NVDA's
FY2020 count is restated for the 2021 4:1 but not the 2024 10:1, so it matches
neither as-filed nor fully-restated. Bases are therefore matched against the
running products of the pending split sequence.

yfinance contributes no values here. Its point-in-time series and split calendar
only identify which basis EDGAR's number already carries; the figure used is
always EDGAR's.
"""
from __future__ import annotations

from datetime import date

# Point-in-time counts are sampled on different dates than a fiscal period end,
# and buybacks move the count between them, so exact agreement is not expected.
# 15% separates "same basis" from a split ratio (smallest common split is 2:1).
_BASIS_TOLERANCE = 0.15


def remaining_split_factor(
    edgar_shares: float | None,
    point_in_time_shares: float | None,
    splits_after_period: list[tuple[date, float]],
) -> float | None:
    """Factor still to apply to `edgar_shares` to reach today's split basis.

    1.0 means the as-filed value already is today's basis. None means the basis
    could not be identified — an explicit gap, never a guess, because guessing
    wrong misstates market cap by the split ratio.
    """
    if not edgar_shares or edgar_shares <= 0:
        return None
    ratios = [r for _d, r in sorted(splits_after_period) if r > 0]
    if not ratios:
        return 1.0
    if not point_in_time_shares or point_in_time_shares <= 0:
        return None

    # Candidate bases: none of the pending splits applied, the first applied,
    # the first two, and so on. The matching prefix is what the filing reflects;
    # whatever remains is still owed.
    applied = 1.0
    total = 1.0
    for r in ratios:
        total *= r
    for idx in range(len(ratios) + 1):
        if idx:
            applied *= ratios[idx - 1]
        if _within_tolerance(edgar_shares, point_in_time_shares * applied):
            return total / applied
    return None


def shares_on_current_basis(
    edgar_shares: float | None, remaining_factor: float | None
) -> float | None:
    """EDGAR's count restated onto today's basis, or None when undecidable.

    A missing factor is undecidable, NOT "no split": defaulting it to 1.0 left
    NVDA's pre-2021 years unadjusted against split-adjusted prices, giving
    EV/Revenue of 0.15 where the series ran 20-27x.
    """
    if not edgar_shares or edgar_shares <= 0:
        return None
    if remaining_factor is None or remaining_factor <= 0:
        return None
    return edgar_shares * remaining_factor


def _within_tolerance(a: float, b: float) -> bool:
    return abs(a / b - 1.0) <= _BASIS_TOLERANCE if b else False
