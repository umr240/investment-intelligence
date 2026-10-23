"""Stage A's test-ticker path must carry the SEC CIK.

Stage B joins SEC frames on CIK, so a CIK-less ticker is hard-failed as
"no CIK (not SEC-filer)". Every test-ticker run used to stop at Stage B.
"""
from __future__ import annotations

from data.universe.base import UniverseTicker
from screener.stages import _test_universe

_REGION = [
    UniverseTicker(ticker="BRZE", name="Braze, Inc.", exchange="Nasdaq",
                   cik="0001676238", source="sec_us"),
    UniverseTicker(ticker="DCBO", name="Docebo Inc.", exchange="Nasdaq",
                   cik="0001829959", source="sec_us"),
]


def test_known_tickers_resolve_to_the_region_entry() -> None:
    got = _test_universe(["brze", "DCBO"], _REGION)
    assert [(u.ticker, u.cik, u.source) for u in got] == [
        ("BRZE", "0001676238", "sec_us"),
        ("DCBO", "0001829959", "sec_us"),
    ]


def test_unknown_ticker_keeps_the_stub() -> None:
    (u,) = _test_universe(["BONEX.ST"], _REGION)
    assert (u.ticker, u.cik, u.source) == ("BONEX.ST", None, "test_list")


def test_order_follows_the_request() -> None:
    assert [u.ticker for u in _test_universe(["DCBO", "ZZZZ", "BRZE"], _REGION)] == [
        "DCBO", "ZZZZ", "BRZE",
    ]
