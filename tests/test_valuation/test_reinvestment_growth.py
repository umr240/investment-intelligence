"""Reinvestment + growth modules (ADR-027 Phase B)."""
from __future__ import annotations

import pytest

from valuation.damodaran.growth import compute_fundamental_growth
from valuation.damodaran.reinvestment import compute_reinvestment


class TestReinvestment:
    def test_basic_reinvestment(self):
        # Capex $500M, D&A $300M, ΔWC $100M, NOPAT $1B
        # Reinvestment = (500 − 300) + 100 = $300M
        # Rate = 300 / 1000 = 30%
        r = compute_reinvestment(
            capex=500_000_000,
            depreciation_amortization=300_000_000,
            current_assets=2_000_000_000,
            current_liabilities=1_500_000_000,    # WC_now = 500M
            current_assets_prior=1_800_000_000,
            current_liabilities_prior=1_400_000_000,  # WC_prior = 400M, ΔWC = +100M
            nopat=1_000_000_000,
        )
        assert r.net_capex == 200_000_000
        assert r.delta_working_capital == 100_000_000
        assert r.reinvestment_total == 300_000_000
        assert r.reinvestment_rate == pytest.approx(0.30)

    def test_missing_prior_wc_defaults_to_zero(self):
        r = compute_reinvestment(
            capex=500_000_000,
            depreciation_amortization=300_000_000,
            current_assets=2_000_000_000,
            current_liabilities=1_500_000_000,
            current_assets_prior=None,
            current_liabilities_prior=None,
            nopat=1_000_000_000,
        )
        assert r.delta_working_capital is None
        assert r.reinvestment_total == 200_000_000   # just net_capex
        assert any("ΔWC not computable" in n for n in r.notes)

    def test_negative_nopat_raises(self):
        with pytest.raises(ValueError, match="positive NOPAT"):
            compute_reinvestment(
                capex=100_000_000,
                depreciation_amortization=50_000_000,
                current_assets=None,
                current_liabilities=None,
                current_assets_prior=None,
                current_liabilities_prior=None,
                nopat=-1_000_000,
            )

    def test_extreme_reinvestment_rate_flagged(self):
        # Reinvestment $2B on NOPAT $1B = 200% — flag
        r = compute_reinvestment(
            capex=2_000_000_000,
            depreciation_amortization=0,
            current_assets=1_000_000_000,
            current_liabilities=1_000_000_000,
            current_assets_prior=1_000_000_000,
            current_liabilities_prior=1_000_000_000,
            nopat=1_000_000_000,
        )
        assert r.reinvestment_rate == 2.0
        assert any("> 150%" in n or "> 100%" in n for n in r.notes)


class TestFundamentalGrowth:
    def test_basic_growth(self):
        # ROIC 20%, reinvest 50% → g = 10%
        g = compute_fundamental_growth(0.20, 0.50)
        assert g.fundamental_growth_rate == pytest.approx(0.10)
        assert g.growth_rate_capped == pytest.approx(0.10)
        assert g.cap_applied is None

    def test_cap_at_25_pct(self):
        # ROIC 40%, reinvest 80% → g = 32% → capped at 25%
        g = compute_fundamental_growth(0.40, 0.80)
        assert g.fundamental_growth_rate == pytest.approx(0.32)
        assert g.growth_rate_capped == 0.25
        assert g.cap_applied == "max"

    def test_floor_at_minus_10_pct(self):
        # ROIC 10%, reinvest −150% → g = −15% → clamped to −10%
        g = compute_fundamental_growth(0.10, -1.5)
        assert g.growth_rate_capped == -0.10
        assert g.cap_applied == "min"

    def test_perpetuity_suspect_flag(self):
        # 22% growth — sustainable per formula but flag for narrative
        g = compute_fundamental_growth(0.30, 0.75)
        assert g.fundamental_growth_rate == pytest.approx(0.225)
        assert g.cap_applied is None
        # Note text uses "maintained" / "rare" — flexible match on "rare"
        assert any("rare" in n.lower() for n in g.notes)

    def test_none_roic_raises(self):
        with pytest.raises(ValueError, match="ROIC"):
            compute_fundamental_growth(None, 0.5)
