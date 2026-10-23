"""Greenwald ladder (ADR-042) — asset value, earnings power, franchise test.

Pure tests: no DB, no network. Emphasis on the FAILURE modes, per CLAUDE.md —
the ways this framework produces a confidently wrong answer are specific and
known, and each one is pinned here.
"""
from __future__ import annotations

import pytest

from valuation.greenwald import (
    EPV_APPLICABLE,
    EPV_INFLECTING,
    EPV_NOT_APPLICABLE,
    GreenwaldValuation,
    assess_epv_applicability,
)
from valuation.greenwald.asset_value import compute_asset_value
from valuation.greenwald.earnings_power import compute_earnings_power
from valuation.greenwald.franchise import (
    FRANCHISE,
    INDETERMINATE,
    NO_FRANCHISE,
    VALUE_DESTRUCTION,
    assess_franchise,
)

# ── Asset reproduction value ──────────────────────────────────────────────

def _av(**over):
    base = dict(
        current_assets=1000.0, current_liabilities=300.0, total_assets=2000.0,
        goodwill=None, cash_and_equivalents=200.0, total_debt=100.0,
        short_term_investments=0.0, rd_expense_history=[50.0, 60.0, 70.0],
        sga_expense=400.0, shares_outstanding=100.0,
    )
    base.update(over)
    return compute_asset_value(**base)


def test_goodwill_is_excluded_from_reproduction_cost():
    """Goodwill is a prior acquirer's price, not a competitor's build cost.

    Including it would double-count the very franchise the test is measuring.
    """
    without = _av(goodwill=None)
    with_gw = _av(goodwill=500.0)
    # PP&E proxy subtracts goodwill, so total falls by exactly the goodwill.
    assert with_gw.asset_value_total == pytest.approx(without.asset_value_total - 500.0)
    assert with_gw.goodwill_excluded == 500.0
    assert any("goodwill" in n.lower() for n in with_gw.notes)


def test_excess_cash_excluded_from_working_capital():
    """A competitor rebuilds the operating float, not the war chest."""
    lean = _av(cash_and_equivalents=0.0)
    rich = _av(cash_and_equivalents=400.0)
    assert rich.working_capital == pytest.approx(lean.working_capital - 400.0)


def test_rd_is_capitalised_not_expensed():
    """An R&D-heavy filer costs more to reproduce than its balance sheet shows."""
    no_rd = _av(rd_expense_history=[])
    with_rd = _av(rd_expense_history=[100.0, 100.0, 100.0])
    assert with_rd.rd_capital == pytest.approx(667.0, rel=1e-2)
    assert with_rd.asset_value_total > no_rd.asset_value_total


def test_missing_rd_becomes_a_gap_not_a_zero():
    r = _av(rd_expense_history=None)
    assert r.rd_capital is None
    assert any("R&D" in g for g in r.data_gaps)


def test_ppe_approximation_is_always_flagged():
    """The weakest leg must never look precise — it biases toward 'franchise'."""
    r = _av()
    assert any("PP&E" in g and "UNDERSTATES" in g for g in r.data_gaps)


# ── Earnings power ────────────────────────────────────────────────────────

def _ep(**over):
    base = dict(
        op_margin_history=[0.20, 0.22, 0.21], current_revenue=1000.0,
        depreciation=50.0, capex=80.0, tax_rate=0.25, wacc=0.10,
        cash_and_equivalents=100.0, short_term_investments=0.0,
        total_debt=200.0, shares_outstanding=100.0, current_price=10.0,
    )
    base.update(over)
    return compute_earnings_power(**base)


def test_growth_capex_is_added_back():
    """The adjustment the naive NOPAT/WACC shortcut omits entirely.

    A firm at zero growth spends only maintenance capex. Capex above D&A is
    growth spending and must not be charged against earnings power.
    """
    r = _ep(depreciation=50.0, capex=80.0)
    assert r.maintenance_capex == 50.0
    assert r.growth_capex_added_back == pytest.approx(30.0)
    # normalised EBIT = median(0.20,0.22,0.21) × 1000 = 210; +30 growth capex
    assert r.adjusted_ebit == pytest.approx(240.0)


def test_no_addback_when_capex_below_depreciation():
    r = _ep(depreciation=100.0, capex=40.0)
    assert r.growth_capex_added_back == pytest.approx(0.0)
    assert any("under-investing" in n for n in r.notes)


def test_median_not_mean_resists_a_single_blowout_year():
    """One write-off year must not drag the normalised anchor."""
    steady = _ep(op_margin_history=[0.20, 0.21, 0.22])
    with_shock = _ep(op_margin_history=[0.20, 0.21, 0.22, -0.50])
    # Median moves only modestly; a mean would collapse.
    assert with_shock.normalized_op_margin == pytest.approx(0.205, abs=1e-3)
    assert steady.normalized_op_margin == pytest.approx(0.21, abs=1e-3)


def test_negative_earnings_power_is_reported_with_a_gap():
    r = _ep(op_margin_history=[-0.10, -0.12, -0.08])
    assert r.adjusted_nopat < 0
    assert any("no positive earnings power" in g for g in r.data_gaps)


def test_zero_wacc_refuses_rather_than_dividing():
    r = _ep(wacc=0.0)
    assert r.epv_operations is None
    assert any("WACC" in g for g in r.data_gaps)


def test_implausible_tax_rate_is_clamped_and_flagged():
    r = _ep(tax_rate=0.95)
    assert r.tax_rate == 0.25
    assert any("tax rate" in g for g in r.data_gaps)


# ── Applicability gate — the ADR-030 analogue ─────────────────────────────

def test_inflecting_company_is_caught():
    """BONESUPPORT's real margin history. Median is -9%, latest is +24%.

    Without this gate, EPV capitalises a loss the business no longer incurs and
    returns 'value destruction' for a profitable company.
    """
    margins = [-0.545, -0.379, -0.196, 0.024, 0.185, 0.236]
    verdict, reason = assess_epv_applicability(margins)
    assert verdict == EPV_INFLECTING
    assert "loss to profit" in reason


def test_stable_company_is_applicable():
    verdict, _ = assess_epv_applicability([0.30, 0.32, 0.31, 0.33])
    assert verdict == EPV_APPLICABLE


def test_consistently_lossmaking_is_applicable_not_inflecting():
    """A company that has always lost money is not inflecting — EPV genuinely
    says its earning power is negative, and that IS the finding."""
    verdict, _ = assess_epv_applicability([-0.20, -0.15, -0.10, -0.05])
    assert verdict == EPV_APPLICABLE


def test_margin_doubling_flags_operating_leverage_still_arriving():
    verdict, reason = assess_epv_applicability([0.05, 0.06, 0.07, 0.20])
    assert verdict == EPV_INFLECTING
    # Assert the SEMANTICS, not the phrasing. This test previously required the
    # literal word "double" and broke when ADR-030-A1 moved the test into
    # valuation/regime.py and reworded it to "more than 2x" — an identical
    # judgement. A test that fails on rewording without a behaviour change is
    # testing prose (`test_behaviour_not_implementation`).
    assert "operating leverage is still arriving" in reason
    assert "20.0%" in reason and "6.5%" in reason      # latest vs median surfaced


def test_too_little_history_is_not_applicable():
    verdict, _ = assess_epv_applicability([0.20, 0.22])
    assert verdict == EPV_NOT_APPLICABLE


# ── Franchise test ────────────────────────────────────────────────────────

@pytest.mark.parametrize("epv,av,expected", [
    (400.0, 100.0, FRANCHISE),           # 4.0x — NVDA-like
    (130.0, 100.0, FRANCHISE),           # exactly at the 1.3 threshold
    (100.0, 100.0, NO_FRANCHISE),        # commodity economics
    (85.0, 100.0, NO_FRANCHISE),
    (50.0, 100.0, VALUE_DESTRUCTION),
    (-50.0, 100.0, VALUE_DESTRUCTION),   # negative earning power
])
def test_franchise_bands(epv, av, expected):
    assert assess_franchise(epv_operations=epv, asset_value_total=av).verdict == expected


def test_no_franchise_means_growth_is_worthless():
    """The result a DCF will not tell you: in commodity economics, growth adds
    nothing, yet a forward DCF still prices it because g is an input."""
    r = assess_franchise(epv_operations=100.0, asset_value_total=100.0)
    assert r.growth_is_worth_paying_for is False
    assert "worth approximately ZERO" in r.interpretation


def test_franchise_means_growth_has_value():
    r = assess_franchise(epv_operations=400.0, asset_value_total=100.0)
    assert r.growth_is_worth_paying_for is True


def test_missing_leg_is_indeterminate_not_no_moat():
    """Absent data must never be reported as an absence of moat."""
    r = assess_franchise(epv_operations=None, asset_value_total=100.0)
    assert r.verdict == INDETERMINATE
    assert r.growth_is_worth_paying_for is None
    assert any("UNEVAL" in g for g in r.data_gaps)


def test_non_positive_asset_value_is_indeterminate():
    r = assess_franchise(epv_operations=100.0, asset_value_total=-5.0)
    assert r.verdict == INDETERMINATE


# ── Share basis: as-filed counts vs split-adjusted price ──────────────────


class _Annual:
    """Annual row stub: unset fields read as None, like a sparse Financial."""

    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)

    def __getattr__(self, _name: str) -> None:
        return None


def _valued(monkeypatch: pytest.MonkeyPatch, factor: float | None) -> GreenwaldValuation:
    import data.reader
    from valuation.greenwald import compute_greenwald_valuation

    rows = [
        _Annual(fiscal_year=2026 - i, revenue=1e9, operating_income=2e8, total_assets=3e9,
                current_assets=1.2e9, current_liabilities=6e8,
                cash_and_equivalents=5e8, total_debt=0.0, shares_outstanding=250e6,
                share_split_factor=factor)
        for i in range(5)
    ]

    class _Reader:
        def __init__(self, _t: str) -> None: ...
        def annuals(self, last_n: int) -> list[_Annual]: return rows[:last_n]
        def price_history(self, last_n: int) -> list[_Annual]: return [_Annual(close=50.0)]

    monkeypatch.setattr(data.reader, "CompanyDataReader", _Reader)
    return compute_greenwald_valuation("X", wacc=0.09, tax_rate=0.25)


def test_known_split_factor_restates_the_share_count(monkeypatch: pytest.MonkeyPatch) -> None:
    # CRWD: FY2026 10-K filed at 250M shares, 4:1 split after it, price post-split.
    before, after = _valued(monkeypatch, 1.0), _valued(monkeypatch, 4.0)
    for leg in ("asset_value.asset_value_per_share", "earnings_power.epv_per_share"):
        part, attr = leg.split(".")
        b, a = getattr(getattr(before, part), attr), getattr(getattr(after, part), attr)
        assert b and a and a == pytest.approx(b / 4), leg


def test_unknown_split_factor_keeps_the_as_filed_count(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _valued(monkeypatch, None).asset_value.asset_value_per_share == pytest.approx(
        _valued(monkeypatch, 1.0).asset_value.asset_value_per_share
    )
