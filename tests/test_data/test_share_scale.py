"""Share-count scale repair against the cover-page anchor.

XBRL values are supposed to be absolute, but filers get this wrong: McDonald's
tags `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` as 713.4 — in
millions — while its cover-page `dei:EntityCommonStockSharesOutstanding` reads
710,398,642. The parser preferred the us-gaap concept, so MCD was stored with
713 shares against $26.9B of revenue, corrupting P/B and every per-share metric
derived from it. Measured: 137 annual rows held fewer than 1,000 shares.
"""
from __future__ import annotations

from data.edgar_companyfacts import dei_share_anchors, repair_share_scale

# ── repair_share_scale ──────────────────────────────────────────────────────


def test_value_reported_in_millions_is_repaired() -> None:
    """MCD's real numbers."""
    assert repair_share_scale(713.4, 710_398_642.0) == 710_398_642.0


def test_value_reported_in_thousands_is_repaired() -> None:
    assert repair_share_scale(713_400.0, 710_398_642.0) == 710_398_642.0


def test_plausible_value_is_left_alone() -> None:
    """None means 'no repair needed' — the caller keeps the original."""
    assert repair_share_scale(710_000_000.0, 710_398_642.0) is None


def test_single_share_class_is_not_treated_as_a_units_error() -> None:
    """A filer tagging one class of several still lands far above the floor.

    Guards against the repair firing on legitimate multi-class filers, where
    the us-gaap concept covers Class A and the cover page covers all classes.
    """
    assert repair_share_scale(150_000_000.0, 710_398_642.0) is None


def test_missing_or_zero_inputs_never_repair() -> None:
    assert repair_share_scale(None, 710_398_642.0) is None
    assert repair_share_scale(713.4, None) is None
    assert repair_share_scale(0.0, 710_398_642.0) is None
    assert repair_share_scale(713.4, 0.0) is None
    assert repair_share_scale(-5.0, 710_398_642.0) is None


# ── dei_share_anchors ───────────────────────────────────────────────────────


def _payload(entries: list[dict]) -> dict:
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {
        "units": {"shares": entries}}}}}


def test_anchors_read_annual_cover_page_counts() -> None:
    p = _payload([
        {"fy": 2025, "fp": "FY", "form": "10-K", "val": 710_398_642, "filed": "2026-02-20"},
        {"fy": 2024, "fp": "FY", "form": "10-K", "val": 714_461_139, "filed": "2025-02-21"},
    ])
    assert dei_share_anchors(p) == {2025: 710_398_642.0, 2024: 714_461_139.0}


def test_anchors_ignore_quarterly_and_non_annual_forms() -> None:
    p = _payload([
        {"fy": 2025, "fp": "Q3", "form": "10-Q", "val": 1, "filed": "2025-11-01"},
        {"fy": 2025, "fp": "FY", "form": "8-K", "val": 2, "filed": "2025-12-01"},
    ])
    assert dei_share_anchors(p) == {}


def test_anchors_accept_10k_variants() -> None:
    """10-K405 was the annual form 1996-2002."""
    p = _payload([
        {"fy": 1999, "fp": "FY", "form": "10-K405", "val": 5_000_000, "filed": "2000-03-01"},
    ])
    assert dei_share_anchors(p) == {1999: 5_000_000.0}


def test_anchors_prefer_the_latest_filing_for_a_year() -> None:
    """Restatements: the most recently filed value wins."""
    p = _payload([
        {"fy": 2024, "fp": "FY", "form": "10-K", "val": 111, "filed": "2025-02-21"},
        {"fy": 2024, "fp": "FY", "form": "10-K", "val": 222, "filed": "2025-08-01"},
    ])
    assert dei_share_anchors(p) == {2024: 222.0}


def test_anchors_tolerate_a_missing_dei_namespace() -> None:
    assert dei_share_anchors({"facts": {"us-gaap": {}}}) == {}
    assert dei_share_anchors({}) == {}
    assert dei_share_anchors(None) == {}
