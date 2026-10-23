"""F7 must not z-score across a stock split.

EDGAR reports share counts as-filed; yfinance prices are split-adjusted
throughout. Any window spanning a split therefore reconstructs market cap wrong
by the split ratio for the pre-split years. CSGP (10:1 in 2019) produced
EV/Revenue of 0.101 and -0.184 for FY2015-FY2018 against 7-20x for later years,
and still returned 8.0/10 strong_fit — a confident buy signal measuring the
split rather than the valuation.
"""
from __future__ import annotations

from types import SimpleNamespace

from frameworks.f7_smart_beta import SPLIT_RATIO_THRESHOLD, _detect_share_split


def _annuals(pairs: list[tuple[int, float | None]]) -> list[SimpleNamespace]:
    return [SimpleNamespace(fiscal_year=fy, shares_outstanding=so) for fy, so in pairs]


def test_organic_dilution_is_not_a_split() -> None:
    """Share counts drifting up a few percent a year must not gate F7."""
    series = _annuals([(y, 100e6 * (1.04 ** (y - 2015))) for y in range(2015, 2026)])
    assert _detect_share_split(series) == (None, 11)


def test_csgp_ten_for_one_split_is_detected() -> None:
    """Real CSGP counts: ~32-36M through FY2018, ~363M+ from FY2019."""
    series = _annuals([
        (2015, 31_950_000), (2016, 32_167_000), (2017, 33_200_000),
        (2018, 36_058_000), (2019, 363_096_000), (2020, 380_726_000),
        (2021, 392_200_000), (2022, 396_300_000), (2023, 405_300_000),
        (2024, 406_300_000), (2025, 416_800_000),
    ])
    split_year, clean_run = _detect_share_split(series)
    assert split_year == 2019
    assert clean_run == 7, "FY2019-FY2025 is the longest usable window"


def test_two_for_one_split_is_detected() -> None:
    """The smallest common split must still trip the gate."""
    series = _annuals([(2020, 50e6), (2021, 50e6), (2022, 100e6), (2023, 101e6)])
    assert _detect_share_split(series)[0] == 2022


def test_reverse_split_is_detected() -> None:
    series = _annuals([(2020, 100e6), (2021, 100e6), (2022, 10e6)])
    assert _detect_share_split(series)[0] == 2022


def test_large_buyback_is_not_mistaken_for_a_reverse_split() -> None:
    """A 15%/yr buyback is aggressive but far below the split threshold."""
    series = _annuals([(y, 100e6 * (0.85 ** (y - 2018))) for y in range(2018, 2026)])
    assert _detect_share_split(series)[0] is None


def test_threshold_sits_between_dilution_and_the_smallest_split() -> None:
    assert 1.0 < SPLIT_RATIO_THRESHOLD < 2.0


def test_longest_run_spans_the_later_segment_when_it_is_bigger() -> None:
    series = _annuals([
        (2016, 10e6), (2017, 10e6), (2018, 100e6),
        (2019, 101e6), (2020, 102e6), (2021, 103e6),
    ])
    assert _detect_share_split(series) == (2018, 4)


def test_missing_share_counts_are_skipped_not_treated_as_jumps() -> None:
    series = _annuals([(2020, 100e6), (2021, None), (2022, 102e6)])
    assert _detect_share_split(series)[0] is None


def test_empty_series_is_handled() -> None:
    assert _detect_share_split([]) == (None, 0)
