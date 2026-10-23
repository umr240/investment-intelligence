"""EDGAR supplies every figure; yfinance only identifies its split basis."""
from __future__ import annotations

from datetime import date

from data.share_basis import remaining_split_factor, shares_on_current_basis

CSGP_SPLIT = [(date(2021, 6, 28), 10.0)]
NVDA_SPLITS = [(date(2021, 7, 20), 4.0), (date(2024, 6, 10), 10.0)]


# ── remaining_split_factor ──────────────────────────────────────────────────


def test_no_pending_split_owes_nothing() -> None:
    assert remaining_split_factor(416_800_000, 423_800_000, []) == 1.0


def test_as_filed_pre_split_value_owes_the_full_factor() -> None:
    """CSGP FY2018: EDGAR 36.1M agrees with point-in-time 36.4M."""
    assert remaining_split_factor(36_058_000, 36_400_000, CSGP_SPLIT) == 10.0


def test_already_restated_value_owes_nothing() -> None:
    """CSGP FY2019: EDGAR 363.1M matches 36.6M x 10 — the filing restated it."""
    assert remaining_split_factor(363_096_000, 36_600_000, CSGP_SPLIT) == 1.0


def test_intermediate_basis_owes_only_the_later_splits() -> None:
    """NVDA FY2020: restated for the 2021 4:1 but not the 2024 10:1.

    Matching only as-filed or fully-restated left this unresolved, gating F7 on
    a company whose basis is perfectly determinable.
    """
    assert remaining_split_factor(2_439_000_000, 612_000_000, NVDA_SPLITS) == 10.0


def test_fully_unrestated_across_two_splits_owes_the_product() -> None:
    assert remaining_split_factor(608_000_000, 610_000_000, NVDA_SPLITS) == 40.0


def test_fully_restated_across_two_splits_owes_nothing() -> None:
    assert remaining_split_factor(24_400_000_000, 610_000_000, NVDA_SPLITS) == 1.0


def test_basis_matching_no_candidate_is_a_gap() -> None:
    assert remaining_split_factor(150_000_000, 36_600_000, CSGP_SPLIT) is None


def test_missing_point_in_time_blocks_resolution_when_a_split_pends() -> None:
    assert remaining_split_factor(36_058_000, None, CSGP_SPLIT) is None
    assert remaining_split_factor(36_058_000, 0, CSGP_SPLIT) is None


def test_missing_edgar_value_yields_nothing() -> None:
    for bad in (None, 0, -1):
        assert remaining_split_factor(bad, 36_400_000, CSGP_SPLIT) is None


def test_buyback_drift_within_tolerance_still_resolves() -> None:
    """A 10% gap between period end and the sample date is not a basis change."""
    assert remaining_split_factor(90_000_000, 100_000_000, CSGP_SPLIT) == 10.0


# ── shares_on_current_basis ─────────────────────────────────────────────────


def test_restatement_multiplies_edgars_own_number() -> None:
    out = shares_on_current_basis(36_058_000, 10.0)
    assert out == 360_580_000
    assert out != 36_400_000 * 10, "must never substitute the yfinance figure"


def test_unknown_factor_is_undecidable_not_no_split() -> None:
    assert shares_on_current_basis(610_000_000, None) is None
    assert shares_on_current_basis(610_000_000, 0) is None


def test_missing_edgar_count_yields_nothing() -> None:
    assert shares_on_current_basis(None, 10.0) is None
    assert shares_on_current_basis(0, 10.0) is None
