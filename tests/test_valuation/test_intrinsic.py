"""End-to-end intrinsic value (ADR-027 Phase B).

Integration tests that exercise the full pipeline: cost-of-capital → NOPAT
(Tier A/B/C selection) → reinvestment → growth → FCFF projection → terminal
value → sensitivity grid → IVResult.

These don't touch the DB — synthetic inputs only. DB integration is Phase C.
"""
from __future__ import annotations

import pytest

from valuation.damodaran.intrinsic import (
    IntrinsicValueInputs,
    compute_intrinsic_value,
)
from valuation.damodaran.nopat import Tier


def _nvda_inputs() -> IntrinsicValueInputs:
    """NVDA-shaped Tier A (huge GAAP profit, net-cash, semis)."""
    return IntrinsicValueInputs(
        ticker="NVDA",
        sector="Technology",
        country="United States",
        market_cap=4_000_000_000_000,
        current_price=160.0,            # rough May 2026 price
        shares_outstanding=25_000_000_000,
        operating_income=105_000_000_000,    # FY26 ~$105B EBIT
        rd_expense_current=18_500_000_000,   # 8.6% intensity
        rd_history=[10_000_000_000, 12_000_000_000, 15_000_000_000, 18_500_000_000],
        capex=6_042_000_000,
        depreciation_amortization=2_000_000_000,
        interest_expense=300_000_000,
        total_equity=200_000_000_000,
        total_debt=12_411_000_000,
        cash_and_equivalents=10_605_000_000,
        short_term_investments=39_520_000_000,
        current_assets=80_000_000_000,
        current_liabilities=15_000_000_000,
        current_assets_prior=60_000_000_000,
        current_liabilities_prior=12_000_000_000,
        high_growth_years=8,
    )


def _hims_inputs() -> IntrinsicValueInputs:
    """HIMS-shaped Tier A (just turned GAAP-profitable FY25)."""
    return IntrinsicValueInputs(
        ticker="HIMS",
        sector="Healthcare",
        country="United States",
        market_cap=5_770_000_000,
        current_price=24.95,
        shares_outstanding=231_500_000,
        operating_income=105_613_000,       # FY25 actual
        rd_expense_current=None,             # bundled in opex (rd_disclosure_state)
        rd_history=[],
        capex=242_600_000,
        depreciation_amortization=80_000_000,
        interest_expense=None,                # convertible, low coupon
        total_equity=540_928_000,
        total_debt=1_121_000_000,
        cash_and_equivalents=228_600_000,
        short_term_investments=700_000_000,
        current_assets=900_000_000,
        current_liabilities=200_000_000,
        current_assets_prior=600_000_000,
        current_liabilities_prior=180_000_000,
        high_growth_years=8,
    )


def _inta_tier_b_inputs() -> IntrinsicValueInputs:
    """INTA-shaped Tier B (GAAP loss, R&D-heavy SaaS — rescued by R&D add-back)."""
    return IntrinsicValueInputs(
        ticker="INTA",
        sector="Information Services",       # Damodaran exact industry name
        country="United States",
        market_cap=2_500_000_000,
        current_price=55.0,
        shares_outstanding=45_000_000,
        operating_income=-10_000_000,        # Small GAAP loss
        rd_expense_current=150_000_000,      # ~30% R&D intensity (current year)
        rd_history=[50_000_000, 70_000_000, 90_000_000, 110_000_000, 150_000_000],
        capex=1_673_000,                      # tiny capex (SaaS)
        depreciation_amortization=20_000_000,
        interest_expense=None,
        total_equity=400_000_000,
        total_debt=23_000_000,
        cash_and_equivalents=313_000_000,
        short_term_investments=None,
        current_assets=500_000_000,
        current_liabilities=200_000_000,
        current_assets_prior=420_000_000,
        current_liabilities_prior=170_000_000,
        high_growth_years=8,
    )


def _tier_c_inputs() -> IntrinsicValueInputs:
    """Pre-revenue / structural loss-maker — even after R&D add-back, EBIT < 0."""
    return IntrinsicValueInputs(
        ticker="LOSE",
        sector="Healthcare",
        country="United States",
        market_cap=500_000_000,
        current_price=10.0,
        shares_outstanding=50_000_000,
        operating_income=-200_000_000,
        rd_expense_current=50_000_000,        # R&D too small to rescue
        rd_history=[40_000_000, 45_000_000, 50_000_000],
        capex=10_000_000,
        depreciation_amortization=5_000_000,
        interest_expense=None,
        total_equity=100_000_000,
        total_debt=20_000_000,
        cash_and_equivalents=50_000_000,
        short_term_investments=None,
        current_assets=70_000_000,
        current_liabilities=30_000_000,
        current_assets_prior=80_000_000,
        current_liabilities_prior=25_000_000,
    )


class TestTierAEnterpriseValue:
    def test_nvda_tier_a_produces_iv(self):
        result = compute_intrinsic_value(_nvda_inputs())
        # ADR-030: Tier A now sub-classifies as A_mature or A_young
        assert result.tier in ("A_gaap", "A_mature", "A_young")
        assert result.intrinsic_value_per_share is not None
        assert result.intrinsic_value_per_share > 0
        assert result.nopat_source == "gaap"
        assert result.wacc_result is not None
        assert result.wacc_result.wacc > 0
        assert len(result.fcff_projections) == 8

    def test_nvda_has_sensitivity_grid(self):
        result = compute_intrinsic_value(_nvda_inputs())
        assert result.sensitivity is not None
        assert len(result.sensitivity.iv_per_share_grid) == 5
        assert len(result.sensitivity.iv_per_share_grid[0]) == 5
        # P5 < median < P95
        s = result.sensitivity
        assert s.iv_per_share_p5 <= s.iv_per_share_median <= s.iv_per_share_p95

    def test_nvda_margin_of_safety_computed(self):
        result = compute_intrinsic_value(_nvda_inputs())
        assert result.margin_of_safety_pct is not None
        # MoS = (IV − price) / IV; sign depends on whether IV > price
        if result.intrinsic_value_per_share > result.current_price:
            assert result.margin_of_safety_pct > 0
        else:
            assert result.margin_of_safety_pct < 0

    def test_hims_tier_a_produces_iv(self):
        result = compute_intrinsic_value(_hims_inputs())
        # ADR-030: Tier A now sub-classifies as A_mature or A_young
        assert result.tier in ("A_gaap", "A_mature", "A_young")
        assert result.intrinsic_value_per_share is not None
        assert result.nopat_source == "gaap"

    def test_terminal_value_share_diagnosed(self):
        result = compute_intrinsic_value(_nvda_inputs())
        assert result.terminal_value_pct_of_total is not None
        assert 0 < result.terminal_value_pct_of_total < 1
        # NVDA at 8yr horizon — terminal should dominate
        assert result.terminal_value_pct_of_total > 0.40


class TestTierBRescued:
    def test_inta_tier_b_uses_pt_adjusted(self):
        result = compute_intrinsic_value(_inta_tier_b_inputs())
        # ADR-030: Tier B now sub-classifies as B_mature or B_young
        assert result.tier in ("B_pt_rescued", "B_mature", "B_young")
        assert result.nopat_source == "pt_adjusted"
        # Should produce a positive IV (rescue worked)
        assert result.intrinsic_value_per_share is not None
        assert result.intrinsic_value_per_share > 0

    def test_inta_data_gaps_explain_tier_b(self):
        result = compute_intrinsic_value(_inta_tier_b_inputs())
        # Tier B should leave a note about R&D capitalization
        notes_combined = " ".join(result.data_gaps).lower()
        assert "tier b" in notes_combined or "r&d" in notes_combined


class TestTierCInsufficient:
    def test_tier_c_returns_none_iv(self):
        result = compute_intrinsic_value(_tier_c_inputs())
        assert result.tier == Tier.C_INSUFFICIENT.value
        assert result.intrinsic_value_per_share is None
        assert result.margin_of_safety_pct is None
        assert result.fcff_projections == []
        assert result.terminal_value is None

    def test_tier_c_emits_clean_data_gap(self):
        result = compute_intrinsic_value(_tier_c_inputs())
        notes = " ".join(result.data_gaps).lower()
        assert "tier c" in notes or "adr-028" in notes or "young-company" in notes

    def test_tier_c_provides_inversion_questions(self):
        result = compute_intrinsic_value(_tier_c_inputs())
        # Tier C should still give inversion questions (target margin, runway, etc.)
        assert len(result.inversion_questions) >= 3
        joined = " ".join(result.inversion_questions).lower()
        assert "target" in joined or "runway" in joined or "margin" in joined


class TestInversionQuestions:
    def test_inversion_questions_populated(self):
        result = compute_intrinsic_value(_nvda_inputs())
        assert len(result.inversion_questions) >= 3
        # First question should reference the 30%-lower sensitivity ask
        assert any("30%" in q or "LOWER" in q for q in result.inversion_questions)

    def test_inversion_references_terminal_share(self):
        result = compute_intrinsic_value(_nvda_inputs())
        joined = " ".join(result.inversion_questions).lower()
        assert "terminal" in joined


class TestProvenanceFields:
    def test_wacc_result_propagated(self):
        result = compute_intrinsic_value(_nvda_inputs())
        assert result.wacc_result is not None
        assert result.wacc_result.ticker == "NVDA"
        assert result.wacc_result.cost_of_equity > 0
        assert result.wacc_result.weight_equity + result.wacc_result.weight_debt == pytest.approx(1.0)

    def test_data_gaps_collected_from_all_layers(self):
        """data_gaps from cost_of_capital + nopat + reinvestment all merge."""
        result = compute_intrinsic_value(_nvda_inputs())
        # At minimum the implied_erp staleness gap should be present
        assert any("erp" in g.lower() or "staleness" in g.lower() for g in result.data_gaps)
