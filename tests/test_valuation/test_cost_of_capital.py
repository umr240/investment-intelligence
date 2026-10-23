"""Phase A acceptance tests for Damodaran cost-of-capital module (ADR-027).

These verify the math + the data wiring. They do NOT verify that our WACC
matches Damodaran's company-level page values to the basis point — his data
moves daily, his betas update quarterly, his ERP monthly. Our targets are
range-based: WACC within ±200bps of his ballpark for each test ticker.
"""
from __future__ import annotations

import pytest

from valuation.damodaran.cost_of_capital import (
    WACCResult,
    compute_after_tax_cost_of_debt,
    compute_cost_of_equity,
    compute_wacc,
    relevel_beta,
)


# ── Unit tests on the primitives ─────────────────────────────────────────


class TestRelevelBeta:
    """Damodaran formula: β_levered = β_unlevered × (1 + (1-t) × D/E)."""

    def test_zero_debt_returns_unlevered(self):
        assert relevel_beta(1.0, 0.0, 0.25) == 1.0

    def test_standard_levering(self):
        # β_u=1.0, D/E=0.5, t=25% → 1.0 × (1 + 0.75 × 0.5) = 1.375
        assert relevel_beta(1.0, 0.5, 0.25) == pytest.approx(1.375)

    def test_high_leverage(self):
        # β_u=0.8, D/E=2.0, t=25% → 0.8 × (1 + 0.75 × 2.0) = 0.8 × 2.5 = 2.0
        assert relevel_beta(0.8, 2.0, 0.25) == pytest.approx(2.0)

    def test_negative_de_treats_as_zero(self):
        """Net-cash filers (negative book D/E) are handled gracefully — no
        spurious de-levering below unlevered."""
        assert relevel_beta(1.0, -0.3, 0.25) == 1.0

    def test_none_de_treats_as_zero(self):
        assert relevel_beta(1.0, None, 0.25) == 1.0


class TestCostOfEquity:
    """CAPM with optional country risk premium."""

    def test_us_filer_basic_capm(self):
        # rf=4.35%, β=1.0, ERP=4.6%, CRP=0 → cost_of_equity = 4.35 + 1.0×4.6 = 8.95%
        coe = compute_cost_of_equity(0.0435, 1.0, 0.046, 0.0)
        assert coe == pytest.approx(0.0895)

    def test_country_premium_adds_to_erp(self):
        # rf=4.35%, β=1.0, ERP=4.6%, CRP=2.0% → coe = 4.35 + 1.0×6.6 = 10.95%
        coe = compute_cost_of_equity(0.0435, 1.0, 0.046, 0.02)
        assert coe == pytest.approx(0.1095)

    def test_high_beta_amplifies_risk(self):
        # rf=4%, β=1.5, ERP=5% → coe = 4 + 1.5×5 = 11.5%
        coe = compute_cost_of_equity(0.04, 1.5, 0.05)
        assert coe == pytest.approx(0.115)


class TestCostOfDebt:
    """Effective-rate preferred; synthetic spread fallback."""

    def test_effective_rate_when_data_present(self):
        # interest=$50M on $1B debt = 5% pre-tax × (1-25% tax) = 3.75% after-tax
        gaps: list[str] = []
        cod, source = compute_after_tax_cost_of_debt(
            interest_expense=50_000_000,
            total_debt=1_000_000_000,
            risk_free_rate=0.0435,
            marginal_tax_rate=0.25,
            data_gaps=gaps,
            ticker="TEST",
        )
        assert source == "effective_interest_rate"
        assert cod == pytest.approx(0.05 * 0.75)
        assert gaps == []

    def test_synthetic_spread_when_no_interest_expense(self):
        gaps: list[str] = []
        cod, source = compute_after_tax_cost_of_debt(
            interest_expense=None,
            total_debt=None,
            risk_free_rate=0.0435,
            marginal_tax_rate=0.25,
            data_gaps=gaps,
            ticker="TEST",
        )
        assert source == "synthetic_spread"
        # rf 4.35% + 200bps spread = 6.35% pre-tax × (1-25%) = 4.7625% after-tax
        assert cod == pytest.approx(0.0635 * 0.75)
        assert len(gaps) == 1
        assert "synthetic" in gaps[0].lower()

    def test_unreasonable_rate_falls_back_to_synthetic(self):
        # Interest expense $300M on $1B debt = 30% — flagged as data anomaly
        gaps: list[str] = []
        cod, source = compute_after_tax_cost_of_debt(
            interest_expense=300_000_000,
            total_debt=1_000_000_000,
            risk_free_rate=0.0435,
            marginal_tax_rate=0.25,
            data_gaps=gaps,
            ticker="TEST",
        )
        assert source == "synthetic_spread"


# ── Integration tests with real reference data ──────────────────────────


class TestComputeWACCRealReferenceData:
    """End-to-end WACC computation against vendored Damodaran reference data.

    Target ranges (not exact) since reference data updates monthly/quarterly
    and Damodaran's published values move continuously. Sanity checks: WACC
    should land in the right neighborhood for each archetype.
    """

    def test_nvda_megacap_tech_net_cash(self):
        """NVDA: $4T+ market cap, ~$12B debt, ~$10B cash, ~$32B short-term
        investments. Tech sector, very low D/E. Expected WACC: 9-11% range
        (low debt, high-beta sector)."""
        result = compute_wacc(
            ticker="NVDA",
            sector="Technology",
            country="United States",
            market_cap=4_000_000_000_000,   # $4T mkt cap (approximate May 2026)
            total_debt=12_411_000_000,
            cash_and_equivalents=10_605_000_000,
            short_term_investments=39_520_000_000,
            interest_expense=None,            # net-cash, minimal real interest
        )
        assert isinstance(result, WACCResult)
        assert 0.085 <= result.wacc <= 0.115, f"NVDA WACC {result.wacc:.2%} outside expected 8.5-11.5% range"
        assert result.weight_equity > 0.99, "NVDA should be ~100% equity weighted"
        assert result.industry == "Software (System & Application)"  # default Technology mapping
        # Synthetic spread expected since net-cash (no real interest expense)
        assert result.cost_of_debt_pretax_source == "synthetic_spread"

    def test_cost_retail_consumer(self):
        """COST: large retailer. Sector=Consumer Defensive maps to Food & Beverage
        (β_u ~0.62). Expected WACC: 6-9% range (low-beta consumer staple)."""
        result = compute_wacc(
            ticker="COST",
            sector="Consumer Defensive",
            country="United States",
            market_cap=400_000_000_000,
            total_debt=8_456_000_000,
            cash_and_equivalents=14_161_000_000,
            short_term_investments=1_123_000_000,
            interest_expense=170_000_000,    # approximate
        )
        assert 0.06 <= result.wacc <= 0.095, f"COST WACC {result.wacc:.2%} outside expected 6-9.5% range"
        assert result.industry == "Food & Beverage"

    def test_hims_smallcap_healthcare(self):
        """HIMS: $5-7B mkt cap, ~$1.1B debt (convertibles + leases), ~$929M cash+STI.
        Sector=Healthcare. Expected WACC: 9-12% range (smaller company, healthcare
        beta around 1.0)."""
        result = compute_wacc(
            ticker="HIMS",
            sector="Healthcare",
            country="United States",
            market_cap=5_770_000_000,        # ~$5.8B from earlier session data
            total_debt=1_121_000_000,
            cash_and_equivalents=228_600_000,
            short_term_investments=700_000_000,
            interest_expense=None,            # convertibles are mostly low/zero coupon
        )
        assert 0.085 <= result.wacc <= 0.12, f"HIMS WACC {result.wacc:.2%} outside expected 8.5-12% range"
        # HIMS has real debt → D weight should be meaningful
        assert result.weight_debt > 0.10

    def test_data_gaps_populated_on_unknown_sector(self):
        """Unknown sector → fallback beta + data_gap entry."""
        result = compute_wacc(
            ticker="WEIRD",
            sector="Some Sector That Does Not Exist",
            country="United States",
            market_cap=1_000_000_000,
            total_debt=100_000_000,
        )
        assert any("not in Damodaran industry taxonomy" in g for g in result.data_gaps)
        assert result.industry == "_fallback_default"

    def test_non_us_filer_picks_up_country_premium(self):
        """A Brazilian filer should have CRP added to the ERP. Sanity-check the
        CRP propagation; don't assert exact WACC."""
        result_us = compute_wacc(
            ticker="USTEST",
            sector="Technology",
            country="United States",
            market_cap=1_000_000_000,
            total_debt=100_000_000,
        )
        result_br = compute_wacc(
            ticker="BRTEST",
            sector="Technology",
            country="Brazil",
            market_cap=1_000_000_000,
            total_debt=100_000_000,
        )
        # Brazil should produce a materially higher cost-of-equity (CRP added)
        assert result_br.cost_of_equity > result_us.cost_of_equity + 0.02
        assert result_br.country_risk_premium > 0.02

    def test_provenance_fields_populated(self):
        """Every WACCResult must carry full provenance for ADR-022 disclosure."""
        result = compute_wacc(
            ticker="NVDA",
            sector="Technology",
            country="United States",
            market_cap=4_000_000_000_000,
            total_debt=12_000_000_000,
        )
        # Inputs propagated
        assert result.risk_free_rate > 0
        assert result.mature_market_erp > 0
        assert result.industry_beta_unlevered > 0
        assert result.marginal_tax_rate > 0
        # Outputs sensible
        assert 0 < result.cost_of_equity < 0.30
        assert 0 < result.wacc < 0.20
        # Provenance
        assert result.reference_data_staleness_days >= 0
        assert isinstance(result.data_gaps, list)
