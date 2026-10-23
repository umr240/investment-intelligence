"""Shard traversal and provenance-based state for the IPO-date task.

`filings.recent` caps at ~1000 filings. Without traversing `filings.files[]`, a
long-history filer reports whichever 10-K fits in that page — CSGP resolved to
2012 against a 1998 listing, and the wrong date then drove archetype selection
and the PSA listing-window trigger.

Pure functions only; the HTTP shell is exercised end-to-end separately.
"""
from __future__ import annotations

from datetime import date

from screener.tasks.ipo_date import (
    _filing_pairs,
    _state_rank,
    classify_listing_state,
    earliest_10k,
    shard_urls,
)


def test_earliest_10k_ignores_other_forms() -> None:
    pairs = [
        ("8-K", "1999-01-04"),
        ("10-Q", "1999-05-10"),
        ("10-K", "2001-03-15"),
        ("10-K", "1999-03-31"),
        ("S-1", "1998-06-01"),
    ]
    assert earliest_10k(pairs) == date(1999, 3, 31)


def test_earliest_10k_tolerates_malformed_dates() -> None:
    pairs = [("10-K", "not-a-date"), ("10-K", ""), ("10-K", "2005-02-02")]
    assert earliest_10k(pairs) == date(2005, 2, 2)


def test_earliest_10k_returns_none_without_an_annual_report() -> None:
    assert earliest_10k([("8-K", "2020-01-01"), ("6-K", "2021-01-01")]) is None


def test_earliest_10k_counts_10k405_variants() -> None:
    """NVDA's first three annual reports are 10-K405 (the 1996-2002 form).

    An exact "10-K" match skipped them and reported 2002 against a 1999
    listing, confidently labelled disclosed_exact.
    """
    pairs = [
        ("10-K", "2002-05-14"),
        ("10-K405", "1999-04-29"),
        ("10-K405", "2000-03-13"),
        ("10-K405/A", "2001-05-25"),
    ]
    assert earliest_10k(pairs) == date(1999, 4, 29)


def test_earliest_10k_counts_small_business_and_transition_forms() -> None:
    assert earliest_10k([("10-KSB", "2003-04-01")]) == date(2003, 4, 1)
    assert earliest_10k([("10-KT", "2004-04-01")]) == date(2004, 4, 1)


def test_earliest_10k_counts_foreign_annual_forms() -> None:
    """Shopify listed 2015 and filed 40-F until converting to domestic forms.

    Counting only 10-K variants dates it from its first 10-K in 2025 — a decade
    late. A foreign annual report is equally good evidence of being listed.
    """
    pairs = [("10-K", "2025-02-11"), ("40-F", "2016-02-17"), ("20-F", "2018-01-01")]
    assert earliest_10k(pairs) == date(2016, 2, 17)


def test_earliest_10k_still_ignores_non_annual_forms() -> None:
    assert earliest_10k([("6-K", "2010-01-01"), ("S-1", "2009-01-01")]) is None


def test_filing_pairs_reads_main_payload_shape() -> None:
    payload = {
        "filings": {
            "recent": {"form": ["10-K", "8-K"], "filingDate": ["2020-02-01", "2020-03-01"]}
        }
    }
    assert _filing_pairs(payload) == [("10-K", "2020-02-01"), ("8-K", "2020-03-01")]


def test_filing_pairs_reads_flat_shard_shape() -> None:
    """Shard files carry the arrays at top level, not under filings.recent."""
    shard = {"form": ["10-K"], "filingDate": ["1999-03-31"]}
    assert _filing_pairs(shard) == [("10-K", "1999-03-31")]


def test_shard_urls_are_absolute_and_oldest_first() -> None:
    payload = {
        "filings": {
            "files": [
                {"name": "CIK0000320193-submissions-001.json"},
                {"name": "CIK0000320193-submissions-002.json"},
            ]
        }
    }
    assert shard_urls(payload) == [
        "https://data.sec.gov/submissions/CIK0000320193-submissions-002.json",
        "https://data.sec.gov/submissions/CIK0000320193-submissions-001.json",
    ]


def test_shard_urls_empty_when_no_older_filings() -> None:
    assert shard_urls({"filings": {"recent": {}}}) == []


# ── State classification ────────────────────────────────────────────────────


def test_no_10k_is_not_disclosed() -> None:
    assert classify_listing_state(None, shards_exhausted=True) == "not_disclosed"


def test_unfetched_shards_leave_the_date_uncertain() -> None:
    assert (
        classify_listing_state(date(2012, 2, 23), shards_exhausted=False)
        == "parser_uncertain"
    )


def test_fully_traversed_post_edgar_filer_is_exact() -> None:
    """CSGP: first 10-K 1999, listed 1998 — EDGAR carries its whole life."""
    assert (
        classify_listing_state(date(1999, 3, 31), shards_exhausted=True)
        == "disclosed_exact"
    )


def test_filer_predating_edgar_stays_uncertain() -> None:
    """AAPL: oldest EDGAR filing 1994, listed 1980 — a floor, not a date."""
    assert (
        classify_listing_state(date(1994, 1, 26), shards_exhausted=True)
        == "parser_uncertain"
    )


def test_state_does_not_depend_on_wall_clock_age() -> None:
    """The prior rule flipped to disclosed_exact once the date passed 10 years old.

    A recent and an old post-EDGAR date must classify identically, or the same
    payload yields different states depending on when the task ran.
    """
    recent = classify_listing_state(date(2024, 5, 1), shards_exhausted=True)
    old = classify_listing_state(date(2001, 5, 1), shards_exhausted=True)
    assert recent == old == "disclosed_exact"


# ── Provenance must never be downgraded ─────────────────────────────────────


def test_state_rank_orders_provenance() -> None:
    assert (
        _state_rank("disclosed_exact")
        > _state_rank("parser_uncertain")
        > _state_rank("not_disclosed")
        > _state_rank(None)
    )


def test_edgar_floor_must_not_displace_a_stronger_existing_date() -> None:
    """MSFT holds a correct 1986-03-13 from a non-SEC source.

    EDGAR's earliest MSFT filing is 1994, so this task can only produce
    parser_uncertain — which must lose to the existing disclosed_exact.
    """
    incoming = classify_listing_state(date(1994, 9, 27), shards_exhausted=True)
    assert incoming == "parser_uncertain"
    assert _state_rank(incoming) < _state_rank("disclosed_exact")


def test_shard_resolved_date_does_displace_an_uncertain_one() -> None:
    """CSGP/NVDA: recent-page guesses were parser_uncertain; shards give exact."""
    incoming = classify_listing_state(date(1999, 4, 29), shards_exhausted=True)
    assert incoming == "disclosed_exact"
    assert _state_rank(incoming) >= _state_rank("parser_uncertain")
