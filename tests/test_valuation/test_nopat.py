"""Tier classification + NOPAT computation (ADR-027 Phase B)."""
from __future__ import annotations

import pytest

from valuation.damodaran.nopat import (
    Tier,
    classify_tier,
    compute_economic_ebit,
    compute_nopat,
)


class TestClassifyTier:
    def test_tier_a_gaap_profitable(self):
        # EBIT $1B → Tier A
        assert classify_tier(1_000_000_000, 100_000_000) == Tier.A_GAAP

    def test_tier_b_rd_rescue(self):
        # EBIT −$50M, R&D $200M → EBIT+R&D = $150M > 0 → Tier B
        assert classify_tier(-50_000_000, 200_000_000) == Tier.B_PT_RESCUED

    def test_tier_c_unrescuable(self):
        # EBIT −$300M, R&D $100M → EBIT+R&D = −$200M → Tier C
        assert classify_tier(-300_000_000, 100_000_000) == Tier.C_INSUFFICIENT

    def test_tier_c_no_rd(self):
        # GAAP loss-maker with no R&D → Tier C
        assert classify_tier(-100_000_000, None) == Tier.C_INSUFFICIENT
        assert classify_tier(-100_000_000, 0) == Tier.C_INSUFFICIENT

    def test_tier_c_missing_ebit(self):
        assert classify_tier(None, 100_000_000) == Tier.C_INSUFFICIENT

    def test_zero_ebit_with_rd_is_tier_b(self):
        # Exactly breakeven on GAAP but rescued by R&D
        assert classify_tier(0, 50_000_000) == Tier.B_PT_RESCUED


class TestComputeEconomicEBIT:
    def test_tier_a_returns_gaap_ebit(self):
        r = compute_economic_ebit(ebit_gaap=1_000_000_000, rd_current=100_000_000)
        assert r.tier == Tier.A_GAAP
        assert r.ebit_economic == 1_000_000_000
        assert r.nopat_source == "gaap"

    def test_tier_b_no_history_zero_amort(self):
        # EBIT −$50M, R&D $200M, no history → amort defaults to 0
        # Economic EBIT = −50 + 200 − 0 = $150M
        r = compute_economic_ebit(
            ebit_gaap=-50_000_000, rd_current=200_000_000, rd_history=()
        )
        assert r.tier == Tier.B_PT_RESCUED
        assert r.ebit_economic == 150_000_000
        assert r.rd_amortization_current == 0.0
        assert any("defaulted to 0" in n for n in r.notes)

    def test_tier_b_with_history_uses_amort(self):
        # 5-year history of R&D = 100, 120, 150, 180, 200 (newest last)
        # Amortization = avg = 750 / 5 = 150
        # Economic EBIT = −50 + 200 − 150 = $0
        # Still Tier B since EBIT + R&D > 0 (the simpler gate)
        r = compute_economic_ebit(
            ebit_gaap=-50_000_000,
            rd_current=200_000_000,
            rd_history=[100_000_000, 120_000_000, 150_000_000, 180_000_000, 200_000_000],
        )
        assert r.tier == Tier.B_PT_RESCUED
        assert r.rd_amortization_current == 150_000_000
        assert r.ebit_economic == pytest.approx(0)

    def test_tier_c_emits_no_ebit(self):
        r = compute_economic_ebit(ebit_gaap=-300_000_000, rd_current=100_000_000)
        assert r.tier == Tier.C_INSUFFICIENT
        assert r.ebit_economic is None
        assert r.nopat_source == "n/a"
        assert any("ADR-028" in n for n in r.notes)


class TestComputeNOPAT:
    def test_tier_a_nopat(self):
        # EBIT $1B, tax 25% → NOPAT = $750M
        r = compute_nopat(ebit_gaap=1_000_000_000, marginal_tax_rate=0.25)
        assert r.tier == Tier.A_GAAP
        assert r.nopat == 750_000_000

    def test_tier_b_nopat_with_history(self):
        # EBIT −$50M + R&D $200M − amort $150M = $0 economic EBIT
        # NOPAT = 0
        r = compute_nopat(
            ebit_gaap=-50_000_000,
            marginal_tax_rate=0.25,
            rd_current=200_000_000,
            rd_history=[100_000_000, 120_000_000, 150_000_000, 180_000_000, 200_000_000],
        )
        assert r.tier == Tier.B_PT_RESCUED
        assert r.nopat == pytest.approx(0)
        assert r.nopat_source == "pt_adjusted"

    def test_tier_c_returns_none_nopat(self):
        r = compute_nopat(
            ebit_gaap=-300_000_000,
            marginal_tax_rate=0.25,
            rd_current=100_000_000,
        )
        assert r.tier == Tier.C_INSUFFICIENT
        assert r.nopat is None
