"""Tier 4 must read revenue from either us-gaap concept.

With `Revenues` alone, 68% of SEC frames filers (live, 2026-10-19) had no
revenue and were hard-failed as "revenue<$10M or missing" — Braze among them.
"""
from __future__ import annotations

from datetime import date

from data.edgar_frames import FrameEntry
from screener.tier4_frames import (
    build_tier4_snapshots,
    evaluate_tier4,
    screener_concepts_periods,
)

TODAY = date(2026, 10, 19)  # → CY2025 / CY2024
ASC606 = "RevenueFromContractWithCustomerExcludingAssessedTax"
ASC606_INC = "RevenueFromContractWithCustomerIncludingAssessedTax"


def _e(val: float, end: date = date(2026, 1, 31)) -> FrameEntry:
    return FrameEntry(cik=1, entity_name="X", val=val, end=end, accn="a")


def test_both_revenue_concepts_are_fetched_for_both_years() -> None:
    cps = screener_concepts_periods(TODAY)
    for concept in ("Revenues", ASC606, ASC606_INC):
        for period in ("CY2025", "CY2024"):
            assert (concept, period, "USD") in cps
    assert len(cps) == 17


def test_asc606_only_filer_gets_revenue_and_period_end() -> None:
    snap = build_tier4_snapshots(
        {1: {f"{ASC606}@CY2025": _e(600e6), f"{ASC606}@CY2024": _e(500e6, date(2025, 1, 31))}},
        TODAY,
    )[1]
    assert (snap.revenue, snap.revenue_prior, snap.period_end) == (600e6, 500e6, date(2026, 1, 31))


def test_including_assessed_tax_is_the_last_fallback() -> None:
    snap = build_tier4_snapshots({1: {f"{ASC606_INC}@CY2025": _e(4.8e9)}}, TODAY)[1]
    assert snap.revenue == 4.8e9
    snap = build_tier4_snapshots(
        {1: {f"{ASC606}@CY2025": _e(4.5e9), f"{ASC606_INC}@CY2025": _e(4.8e9)}}, TODAY,
    )[1]
    assert snap.revenue == 4.5e9


def test_revenues_wins_when_both_are_tagged() -> None:
    snap = build_tier4_snapshots(
        {1: {"Revenues@CY2025": _e(700e6), f"{ASC606}@CY2025": _e(650e6)}}, TODAY,
    )[1]
    assert snap.revenue == 700e6


def test_no_revenue_concept_still_hard_fails() -> None:
    snaps = build_tier4_snapshots({1: {"Assets@CY2025Q4I": _e(1e9)}}, TODAY)
    assert snaps[1].revenue is None and snaps[1].period_end is None


def test_asc606_filer_is_not_hard_failed_on_revenue() -> None:
    class _T:
        ticker, cik = "BRZE", "0000000001"

    snaps = build_tier4_snapshots(
        {1: {f"{ASC606}@CY2025": _e(600e6), "Assets@CY2025Q4I": _e(1e9)}}, TODAY,
    )
    (r,) = evaluate_tier4([_T()], snaps)
    assert r.hard_failure_reason is None or "revenue" not in r.hard_failure_reason
