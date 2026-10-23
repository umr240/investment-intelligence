"""The companyfacts coverage gate must account for quarters, not only years.

Annual-only coverage used to pass the gate with a year filter (or skip the
fetch outright), so recent quarters were never parsed: CRWD dived with 10
annual rows, 0 quarterly, and F1–F5 unfeasible. 812 companies in the author
DB had the same shape (2026-10-19).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import data.pipeline as pipeline
from data.pipeline import _decide_companyfacts_fetch

_YEAR = date.today().year
_FULL = set(range(_YEAR - 9, _YEAR + 1))


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"years": set(), "quarters": 0, "stale": 0}
    monkeypatch.setattr(pipeline, "_existing_annual_years", lambda _t: state["years"])
    monkeypatch.setattr(pipeline, "_existing_quarter_count", lambda _t: state["quarters"])
    monkeypatch.setattr(pipeline, "_stale_parse_count", lambda _t, since_year=None: state["stale"])
    monkeypatch.setattr(pipeline, "_probe_new_filings", lambda _t, _k: False)
    return state


def _decide(quarters: int) -> pipeline.CoverageDecision:
    return _decide_companyfacts_fetch(
        "X",
        years=10,
        force_refresh=False,
        known_accessions=frozenset(),
        quarters=quarters,
    )


def test_annual_gap_with_no_quarters_parses_everything(db: dict[str, Any]) -> None:
    db["years"] = _FULL - {_YEAR - 9}
    d = _decide(12)
    assert (d.fetch_fundamentals, d.keep_only_years) == (True, None)
    assert d.reason == "quarterly gap: have 0Q, need 12Q"


def test_full_annuals_with_no_quarters_still_fetches(db: dict[str, Any]) -> None:
    db["years"] = _FULL
    d = _decide(12)
    assert (d.fetch_fundamentals, d.keep_only_years) == (True, None)


def test_enough_quarters_keeps_the_year_filter(db: dict[str, Any]) -> None:
    db["years"], db["quarters"] = _FULL - {_YEAR - 9}, 12
    d = _decide(12)
    assert d.keep_only_years == frozenset({_YEAR - 9})


def test_full_coverage_skips_the_fetch(db: dict[str, Any]) -> None:
    db["years"], db["quarters"] = _FULL, 40
    assert _decide(12).fetch_fundamentals is False


def test_no_quarter_requirement_behaves_as_before(db: dict[str, Any]) -> None:
    db["years"] = _FULL
    assert _decide(0).fetch_fundamentals is False


def test_cold_cache_wins_over_the_quarter_check(db: dict[str, Any]) -> None:
    assert _decide(12).reason == "cold cache (no Financial rows for ticker)"


def test_filings_from_an_older_parser_are_fetched_again(db: dict[str, Any]) -> None:
    # CRWD: rows parsed before the revenue-concept fix kept revenue NULL, and with
    # full coverage the gate skipped the fetch, so a dive never repaired them.
    db["years"], db["quarters"], db["stale"] = _FULL, 40, 22
    d = _decide(12)
    assert (d.fetch_fundamentals, d.keep_only_years) == (True, None)
    assert d.reason == "parser upgraded: 22 filings were read by an older parser"
    # Reading only the stale filings would rebuild rows from superseded ones.
    assert d.reparse is True


def test_only_the_cold_cache_counts_as_cold(db: dict[str, Any]) -> None:
    assert _decide(12).cold is True
    db["years"] = _FULL - {_YEAR - 9}
    assert _decide(12).cold is False


def test_current_parser_with_full_coverage_settles(db: dict[str, Any]) -> None:
    # A filer with genuinely no revenue must not re-fetch on every refresh.
    db["years"], db["quarters"], db["stale"] = _FULL, 40, 0
    assert _decide(12).fetch_fundamentals is False


def test_a_parser_upgrade_wins_over_a_quarterly_gap(db: dict[str, Any]) -> None:
    # The quarterly path reads incrementally; with stale filings that would
    # rebuild rows from superseded filings alone.
    db["years"], db["quarters"], db["stale"] = _FULL, 0, 3
    assert _decide(12).reparse is True


def test_stale_filings_are_counted_only_inside_the_window(
    db: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int | None] = []

    def count(_t: str, since_year: int | None = None) -> int:
        seen.append(since_year)
        return 0

    monkeypatch.setattr(pipeline, "_stale_parse_count", count)
    db["years"], db["quarters"] = _FULL, 40
    _decide(12)
    assert seen == [_YEAR - 9]
