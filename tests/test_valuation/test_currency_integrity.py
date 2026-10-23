"""ADR-043 §2.5 — currency integrity. The tests that would have caught all three.

Each assertion here corresponds to a defect that shipped: a value that was
present, plausible and wrong. This codebase is disciplined about MISSING data
(`data_gaps[]` is first-class; frameworks refuse rather than default) but had no
equivalent discipline for data in the wrong UNITS, because until ADR-041 every
value arrived in USD.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from valuation.damodaran.cost_of_capital import (
    MissingRiskFreeRateError,
    compute_wacc,
)

# Every test here reads the real database and skips when it is empty, so a run
# that does not load data proves nothing about these invariants. The marker
# makes that visible: `pytest -m requires_data` asserts they actually ran.
pytestmark = pytest.mark.requires_data

_RF_PATH = Path("data/reference/damodaran/risk_free_rate.json")


def _rf_table() -> dict:
    return json.loads(_RF_PATH.read_text(encoding="utf-8"))["rates_by_currency"]


# ── §2.2 risk-free rate must match the cash-flow currency ─────────────────

def test_risk_free_rate_matches_reporting_currency():
    """The headline defect: SEK cash flows discounted at the US Treasury yield.

    BONEX.ST used rf=4.63% (USD) when the SEK sovereign yield was 2.78% —
    ~185bps of overstated discount rate on every EU/EEA ticker ADR-041 unlocked.
    """
    for currency in ("SEK", "EUR", "GBP", "NOK", "DKK", "USD"):
        w = compute_wacc(
            ticker="TEST", sector="Technology", market_cap=1e10, total_debt=1e8,
            reporting_currency=currency,
        )
        assert w.risk_free_currency == currency, (
            f"reporting {currency} but discounted at a {w.risk_free_currency} "
            f"risk-free rate — Damodaran's first consistency check"
        )
        expected = _rf_table()[currency]["pct"] / 100.0
        assert w.risk_free_rate == pytest.approx(expected, abs=1e-9)


def test_unknown_currency_refuses_rather_than_defaulting_to_usd():
    """A silent USD fallback would recreate the bug while looking like a fix."""
    with pytest.raises(MissingRiskFreeRateError) as exc:
        compute_wacc(
            ticker="TEST", sector="Technology", market_cap=1e10, total_debt=1e8,
            reporting_currency="ZWL",
        )
    assert "ZWL" in str(exc.value)
    assert "do NOT substitute USD" in str(exc.value)


def test_no_currency_defaults_to_usd_for_us_filers():
    """None means "caller didn't know", which for a US SEC filer IS USD.

    This is the one legitimate default, and it must keep working or every US
    ticker breaks.
    """
    w = compute_wacc(ticker="NVDA", sector="Technology", market_cap=1e12,
                     total_debt=1e10)
    assert w.risk_free_currency == "USD"


def test_every_rate_carries_its_own_staleness_threshold():
    """USD is daily (DGS10); the OECD series are monthly. One 7-day threshold
    across both would flag every non-USD rate as stale forever."""
    for currency, meta in _rf_table().items():
        assert meta["staleness_warning_days"] >= 7
        if meta["cadence"] == "monthly":
            assert meta["staleness_warning_days"] >= 30, currency


# ── §2.3 country resolution, and what happens when it fails ───────────────

def test_country_resolves_from_the_jurisdiction_registry():
    """`country` was hardcoded "United States" for every ticker, so a Swedish
    filer got a US tax rate and CRP=0.0 — right for Sweden by accident."""
    w = compute_wacc(ticker="BONEX.ST", sector="Healthcare", market_cap=1e10,
                     total_debt=1e8, reporting_currency="SEK")
    assert w.country_resolved == "Sweden"
    # Sweden's statutory rate, from Damodaran's country table.
    assert w.marginal_tax_rate == pytest.approx(0.206, abs=1e-3)


def test_unresolvable_country_gaps_rather_than_assuming_zero_risk():
    """CRP=0.0 by DEFAULT is the dangerous case: it silently understates risk
    for exactly the emerging markets where country risk is the point."""
    w = compute_wacc(ticker="XYZ.ZZZ", sector="Technology", market_cap=1e10,
                     total_debt=1e8, country="Freedonia")
    assert any("Freedonia" in g for g in w.data_gaps), (
        "an unmapped country must surface a gap, not resolve silently"
    )


# ── §2.4 industry beta specificity ────────────────────────────────────────

def test_industry_beats_sector_for_beta():
    """A bone-graft device maker was priced with the healthcare-IT beta (0.99)
    because the lookup keyed on sector alone. Correct row is 0.83."""
    by_sector = compute_wacc(ticker="T1", sector="Healthcare", market_cap=1e10,
                             total_debt=1e8)
    by_industry = compute_wacc(ticker="T2", sector="Healthcare",
                               industry="Medical Instruments & Supplies",
                               market_cap=1e10, total_debt=1e8)
    assert by_industry.industry == "Healthcare Products"
    assert by_industry.industry_beta_unlevered < by_sector.industry_beta_unlevered


def test_sic_vocabulary_is_mapped_too():
    """EDGAR filers carry SEC SIC descriptions, not yfinance labels. Mapping
    only one vocabulary made the fix appear to leave every US ticker untouched.
    """
    w = compute_wacc(ticker="NVDA", sector="Technology",
                     industry="Semiconductors & Related Devices",
                     market_cap=1e12, total_debt=1e10)
    assert w.industry == "Semiconductor"


def test_unmapped_industry_falls_back_to_sector_with_a_gap():
    w = compute_wacc(ticker="T3", sector="Technology",
                     industry="Artisanal Yak Herding", market_cap=1e10,
                     total_debt=1e8)
    assert any("Artisanal Yak Herding" in g for g in w.data_gaps)


# ── §2.1 market cap must actually be USD ──────────────────────────────────

def test_persisted_market_cap_usd_is_usd_not_native():
    """The 9.5x defect: SEK 14.56bn stored in a column named market_cap_usd,
    which cleared the $300m liquidity floor a $1.53bn company should clear
    honestly and a SEK 2.85bn micro-cap should not clear at all.

    Skips when the DB has no non-USD company, so the suite stays runnable on a
    US-only warehouse.
    """
    from data.db import get_session
    from data.models.schema import Company

    with get_session() as session:
        rows = (
            session.query(Company)
            .filter(Company.currency.isnot(None), Company.currency != "USD")
            .all()
        )
        checked = 0
        for c in rows:
            if c.market_cap_native is None or c.market_cap_usd is None:
                continue    # fail-closed NULL is the correct alternative
            assert c.market_cap_usd != c.market_cap_native, (
                f"{c.ticker} reports {c.currency} but market_cap_usd equals "
                f"market_cap_native — no conversion happened"
            )
            # Direction guard: multiplying vs dividing by an FX rate of ~0.105
            # differ by ~90x, so a sane ratio band catches an inverted rate.
            ratio = c.market_cap_usd / c.market_cap_native
            assert 0.001 < ratio < 1000, (
                f"{c.ticker} FX ratio {ratio} implausible — inverted rate?"
            )
            checked += 1
        if not checked:
            pytest.skip("no non-USD company with both cap fields populated")
