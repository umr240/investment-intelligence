"""FCFF projection + terminal value (ADR-027 Phase B)."""
from __future__ import annotations

import pytest

from valuation.damodaran.fcff import project_fcff
from valuation.damodaran.terminal import compute_terminal_value


class TestProjectFCFF:
    def test_basic_projection(self):
        # NOPAT $1B, g 10%, reinvest 50%, 5yr, WACC 10%
        # Year 1: NOPAT = 1.1B, FCFF = 0.55B, DF = 1/1.1 ≈ 0.909
        # PV_1 = 0.55 × 0.909 ≈ 0.5
        p = project_fcff(
            nopat_base=1_000_000_000,
            growth_rate=0.10,
            reinvestment_rate=0.50,
            high_growth_years=5,
            wacc=0.12,
        )
        assert len(p.nopat_projections) == 5
        assert len(p.fcff_projections) == 5
        assert p.nopat_projections[0] == pytest.approx(1_100_000_000)
        assert p.fcff_projections[0] == pytest.approx(550_000_000)
        assert p.pv_high_growth_fcff_total > 0

    def test_wacc_less_than_g_raises(self):
        with pytest.raises(ValueError, match="WACC > g"):
            project_fcff(
                nopat_base=1_000_000_000,
                growth_rate=0.10,
                reinvestment_rate=0.50,
                high_growth_years=5,
                wacc=0.08,
            )

    def test_negative_nopat_base_raises(self):
        with pytest.raises(ValueError, match="nopat_base"):
            project_fcff(
                nopat_base=-100_000_000,
                growth_rate=0.05,
                reinvestment_rate=0.5,
                high_growth_years=5,
                wacc=0.10,
            )

    def test_high_reinvestment_flagged(self):
        # Reinvestment 110% — FCFF goes negative
        p = project_fcff(
            nopat_base=1_000_000_000,
            growth_rate=0.10,
            reinvestment_rate=1.10,
            high_growth_years=5,
            wacc=0.12,
        )
        # All years should have negative FCFF
        for fcff in p.fcff_projections:
            assert fcff < 0
        assert any("> 100%" in n for n in p.notes)


class TestTerminalValue:
    def test_basic_terminal_value(self):
        # NOPAT_N $1.6B (year 5 of growth from earlier test)
        # g_term = 4%, WACC = 10%, Rf = 4%
        # reinvest_t = g/WACC = 4%/10% = 40% (default roic_t = wacc)
        # NOPAT_{N+1} = 1.6B × 1.04 = 1.664B
        # FCFF_{N+1} = 1.664B × (1 − 0.40) = 998.4M
        # TV = 998.4M / (0.10 − 0.04) = 16.64B
        # DF_5 = 1/1.1^5 = 0.6209
        # TV_PV = 16.64B × 0.6209 = 10.33B
        t = compute_terminal_value(
            nopat_high_growth_final=1_600_000_000,
            growth_rate_terminal=0.04,
            high_growth_years=5,
            wacc=0.10,
            risk_free_rate=0.04,
        )
        assert t.growth_rate_terminal == 0.04
        assert not t.g_capped_at_rf
        assert t.terminal_value == pytest.approx(998_400_000 / 0.06, rel=1e-3)
        assert t.terminal_value_pv > 0

    def test_growth_capped_at_risk_free(self):
        # User passes g_term = 6% but Rf = 4% → cap at 4%
        t = compute_terminal_value(
            nopat_high_growth_final=1_000_000_000,
            growth_rate_terminal=0.06,
            high_growth_years=5,
            wacc=0.10,
            risk_free_rate=0.04,
        )
        assert t.growth_rate_terminal == 0.04
        assert t.g_capped_at_rf
        assert any("capped" in n.lower() for n in t.notes)

    def test_wacc_below_g_terminal_raises(self):
        # WACC 3%, Rf 4%, g_term auto-cap to 4% — but WACC < g → error
        with pytest.raises(ValueError, match="Gordon"):
            compute_terminal_value(
                nopat_high_growth_final=1_000_000_000,
                growth_rate_terminal=0.04,
                high_growth_years=5,
                wacc=0.03,
                risk_free_rate=0.04,
            )

    def test_custom_terminal_roic(self):
        # Moaty firm — ROIC_terminal = 15% > WACC 10%
        # reinvest_t = g/ROIC = 4%/15% = 26.67%
        t = compute_terminal_value(
            nopat_high_growth_final=1_000_000_000,
            growth_rate_terminal=0.04,
            high_growth_years=5,
            wacc=0.10,
            risk_free_rate=0.04,
            roic_terminal=0.15,
        )
        assert t.reinvestment_rate_terminal == pytest.approx(0.04 / 0.15)
