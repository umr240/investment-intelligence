"""ADR-039 — FundamentalsSource port: routing, wrong-company guard, contract.

These tests are pure (no network): they exercise resolve_source's routing
table, the Liskov substitutability of every registered adapter, and the
yfinance adapter's frame-mapping on a hand-built DataFrame. The motivating
failure — `VHI` resolving to Valhi Inc while `VHI.TO` (VitalHub) must never
touch EDGAR — is pinned as a regression test (ADR-039 §6 acceptance #2).
"""
from __future__ import annotations

import pandas as pd
import pytest

from data.sources import resolve_source
from data.sources.base import (
    TAG_ESEF,
    TAG_SEC,
    TAG_SEDAR,
    TIER_YFINANCE,
    FundamentalsResult,
    FundamentalsSource,
    get_source,
)


# ── Routing ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ticker,expected",
    [
        ("NVDA", TAG_SEC),
        ("AAPL", TAG_SEC),
        ("VHI", TAG_SEC),        # bare ticker → SEC (correctly Valhi's ticker)
        ("BRK.B", TAG_SEC),      # US class-share dotted ticker is NOT a foreign suffix
        ("VHI.TO", TIER_YFINANCE),
        ("TOI.V", TIER_YFINANCE),
        ("JDG.L", TIER_YFINANCE),   # UK: Companies House adapter not built yet
        ("KPG.AX", TIER_YFINANCE),  # ASX: genuinely no structured source
        # ADR-041: EU/EEA venues whose OAM syndicates to filings.xbrl.org now
        # route to the Tier-1B ESEF adapter instead of the Tier-3 bridge.
        ("TEQ.ST", TAG_ESEF),
        ("BONEX.ST", TAG_ESEF),
        ("KEMPOWR.HE", TAG_ESEF),
        ("ASML.AS", TAG_ESEF),
        ("RACE.MI", TAG_ESEF),
        # …but German venues do NOT: the regime is ESEF, the filings are not
        # syndicated. Regime != reachability (see jurisdiction.py .DE note).
        ("AG1.DE", TIER_YFINANCE),
        ("VOW3.F", TIER_YFINANCE),
    ],
)
def test_resolve_routes_by_suffix(ticker, expected):
    assert resolve_source(ticker, None).name == expected


def test_brk_b_routes_to_sec_not_foreign():
    # 'B' is not in the foreign-suffix set; US class shares must stay on SEC.
    assert resolve_source("BRK.B", None).name == TAG_SEC


# ── Wrong-company guard (the motivating failure) ───────────────────────────

def test_vhi_to_never_routes_to_sec():
    src = resolve_source("VHI.TO", None)
    assert src.name != TAG_SEC
    assert src.name == TIER_YFINANCE


def test_sec_adapter_rejects_canadian_ticker():
    sec = get_source(TAG_SEC)
    assert sec.supports("NVDA", None) is True
    assert sec.supports("VHI.TO", None) is False
    assert sec.supports("TOI.V", None) is False


# ── SEDAR+ scaffold: registered but unavailable → resolver skips it ────────

def test_sedar_scaffold_unavailable_falls_through_to_yfinance():
    sedar = get_source(TAG_SEDAR)
    assert sedar.available is False
    assert sedar.supports("VHI.TO", None) is True   # it *would* serve TSX
    # …but because it's unavailable, Canadian tickers route to yfinance today.
    assert resolve_source("VHI.TO", None).name == TIER_YFINANCE


# ── Liskov: every registered adapter satisfies the port ────────────────────

@pytest.mark.parametrize("name", [TAG_SEC, TAG_SEDAR, TAG_ESEF, TIER_YFINANCE])
def test_registered_adapters_satisfy_protocol(name):
    src = get_source(name)
    assert isinstance(src, FundamentalsSource)
    assert isinstance(src.name, str) and src.name
    assert isinstance(src.tier, str) and src.tier
    assert isinstance(src.available, bool)


# ── yfinance frame mapping (pure, no network) ──────────────────────────────

def test_yfinance_rows_from_frames_maps_and_computes_margin():
    from data.sources.yfinance_fund import _rows_from_frames

    col = pd.Timestamp("2024-12-31")
    is_df = pd.DataFrame(
        {col: {"Total Revenue": 100.0, "Cost Of Revenue": 20.0, "Net Income": 12.0,
               "Operating Income": 15.0, "Research And Development": 11.0}}
    )
    bs_df = pd.DataFrame(
        {col: {"Total Assets": 200.0, "Stockholders Equity": 120.0, "Total Debt": 30.0,
               "Cash And Cash Equivalents": 10.0}}
    )
    cf_df = pd.DataFrame(
        {col: {"Operating Cash Flow": 18.0, "Capital Expenditure": -3.0}}
    )

    rows = _rows_from_frames("VHI.TO", "CAD", "annual", is_df, bs_df, cf_df)
    assert len(rows) == 1
    r = rows[0]
    assert r.fiscal_year == 2024
    assert r.period == "annual"
    assert r.source == "yfinance"
    assert r.revenue == 100.0
    assert r.gross_profit == 80.0           # computed from revenue - COGS
    assert r.gross_margin == pytest.approx(0.80)
    assert r.free_cash_flow == pytest.approx(15.0)   # OCF - |capex| fallback


def test_yfinance_period_label_quarter_from_month():
    from data.sources.yfinance_fund import _period_label
    assert _period_label(3, "annual") == "annual"
    assert _period_label(3, "quarterly") == "Q1"
    assert _period_label(6, "quarterly") == "Q2"
    assert _period_label(12, "quarterly") == "Q4"


def test_fundamentals_result_default_tier_is_sec():
    # A bare result must never over-claim a non-SEC tier by default.
    assert FundamentalsResult(ticker="X").source_tier == TAG_SEC
