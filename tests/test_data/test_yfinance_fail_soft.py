"""A Yahoo outage is a data gap, not a failed refresh (CLAUDE.md API RATE LIMITS).

On 2026-10-26 a DNS failure for query2.finance.yahoo.com raised out of
`yticker.info` and aborted three golden-set dives (GEV, KFS, LICN), SEC
fundamentals included.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from data.api import yfinance_client


class _Offline:
    def __getattr__(self, name: str) -> Any:
        raise ConnectionError(f"Could not resolve host while reading {name}")

    def history(self, *_a: Any, **_k: Any) -> Any:
        raise ConnectionError("Could not resolve host")


def test_an_unreachable_yahoo_gives_gaps_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ModuleType("yfinance")
    fake.Ticker = lambda _t: _Offline()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    snap = yfinance_client.fetch_yfinance_snapshot("GEV", 1)
    assert snap.info.ticker == "GEV" and snap.info.market_cap is None
    assert any("yfinance .info unavailable (ConnectionError)" in g for g in snap.gaps)
    assert snap.price_history == [] and snap.institutional_holders == []


def test_info_is_still_read_when_yahoo_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ModuleType("yfinance")
    fake.Ticker = lambda _t: SimpleNamespace(info={"longName": "GE Vernova", "marketCap": 1e11})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    snap = yfinance_client.fetch_yfinance_snapshot("GEV", 1)
    assert snap.info.name == "GE Vernova" and snap.info.market_cap == 1e11
