"""A parser upgrade re-reads every filing, not just the stale ones.

Skipping filings already stamped current left only superseded filings in the
parse, and their partial rows overwrote good Financial values.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

import data.edgar_fetcher as edgar_fetcher
import data.pipeline as pipeline
from data.edgar_fetcher import EdgarFetchResult
from data.pipeline import CoverageDecision
from data.sources.base import FundamentalsResult
from data.sources.sec_edgar import SecEdgarSource


@dataclass
class _Requirement:
    annual_years: int = 10
    quarterly_count: int = 12


def _fetch(
    monkeypatch: pytest.MonkeyPatch, decision: CoverageDecision
) -> tuple[frozenset[str], FundamentalsResult]:
    seen: dict[str, frozenset[str]] = {}

    def fake_fetch(
        ticker: str, years: int, quarters: int, skip: frozenset[str], *_a: Any, **_k: Any
    ) -> EdgarFetchResult:
        seen["skip"] = skip
        return EdgarFetchResult(ticker=ticker)

    monkeypatch.setattr(pipeline, "_load_known_accessions", lambda _t: frozenset({"cur"}))
    monkeypatch.setattr(pipeline, "_resolve_filer_metadata", lambda _t: None)
    monkeypatch.setattr(pipeline, "_decide_companyfacts_fetch", lambda *_a, **_k: decision)
    monkeypatch.setattr(edgar_fetcher, "fetch_edgar_fundamentals", fake_fetch)
    result = asyncio.run(SecEdgarSource().fetch("X", _Requirement()))
    return seen["skip"], result


def test_parser_upgrade_reads_every_filing(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = CoverageDecision(True, None, "parser upgraded", reparse=True)
    skip, result = _fetch(monkeypatch, decision)
    assert skip == frozenset()
    assert result.reparsed is True


def test_incremental_fetch_skips_known_filings(monkeypatch: pytest.MonkeyPatch) -> None:
    skip, result = _fetch(monkeypatch, CoverageDecision(True, None, "new filing"))
    assert skip == frozenset({"cur"})
    assert result.reparsed is False


def test_spelling_hint_only_on_a_cold_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    _, warm = _fetch(monkeypatch, CoverageDecision(True, None, "new filing"))
    _, cold = _fetch(monkeypatch, CoverageDecision(True, None, "cold cache", cold=True))
    assert not any("spelling" in g for g in warm.gaps)
    assert any("spelling" in g for g in cold.gaps)
