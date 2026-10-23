"""Greenwald valuation engine (ADR-042) — the three-pillar ladder.

    Asset Reproduction Value  →  Earnings Power Value  →  Franchise test

Distinct from ``valuation/damodaran/`` by intent, not just by formula.
Damodaran forecasts explicitly and prices the story. Greenwald refuses to
forecast, and instead asks whether current earnings exceed what it would cost
a competitor to reproduce the business. Running both and comparing is the
point: agreement is confirmation, disagreement is the finding.

The pre-existing ``valuation/damodaran/epv.py`` remains — it is the *anchor*
EPV (``NOPAT / WACC``) computed inside the Damodaran engine as a sibling
output. This package computes EPV properly: cycle-normalised margin, growth
capex added back, maintenance capex charged. The two numbers differing is
expected and diagnostic.

Deterministic end to end. No LLM, no network.

Public API:
    compute_greenwald_valuation(ticker) -> GreenwaldValuation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from data.share_basis import shares_on_current_basis
from valuation.greenwald.asset_value import AssetValueResult, compute_asset_value
from valuation.greenwald.earnings_power import (
    EarningsPowerResult,
    compute_earnings_power,
)
from valuation.greenwald.franchise import (
    FRANCHISE,
    INDETERMINATE,
    NO_FRANCHISE,
    VALUE_DESTRUCTION,
    FranchiseResult,
    assess_franchise,
)

__all__ = [
    "AssetValueResult",
    "EarningsPowerResult",
    "FranchiseResult",
    "GreenwaldValuation",
    "compute_asset_value",
    "compute_earnings_power",
    "compute_greenwald_valuation",
    "assess_franchise",
    "FRANCHISE",
    "NO_FRANCHISE",
    "VALUE_DESTRUCTION",
    "INDETERMINATE",
    "EPV_APPLICABLE",
    "EPV_INFLECTING",
    "EPV_NOT_APPLICABLE",
    "assess_epv_applicability",
]


# ADR-030 Amendment A1 — the regime test now lives in valuation/regime.py so
# F7 and this module cannot drift into two different standards. These aliases
# keep the ADR-042 names working for existing callers and tests.
from valuation.regime import APPLICABLE as EPV_APPLICABLE
from valuation.regime import INFLECTING as EPV_INFLECTING
from valuation.regime import NOT_APPLICABLE as EPV_NOT_APPLICABLE
from valuation.regime import assess_margin_regime


def assess_epv_applicability(margins: list[float | None]) -> tuple[str, str]:
    """Is Greenwald EPV the right tool here? Delegates to the shared test.

    Kept as a named function because the EPV-specific *consequence* of an
    inflecting verdict (fall back to a recent-regime EPV) is this module's
    business, while the *detection* is not.
    """
    return assess_margin_regime(margins)


@dataclass(frozen=True)
class GreenwaldValuation:
    """All three pillars plus the ladder reading."""

    ticker: str
    asset_value: AssetValueResult
    earnings_power: EarningsPowerResult
    franchise: FranchiseResult
    current_price: float | None
    wacc_used: float
    wacc_source: str
    # Applicability gate — the Greenwald analogue of ADR-030's maturity routing.
    epv_applicability: str = EPV_APPLICABLE
    epv_applicability_reason: str = ""
    # Recent-regime EPV: same math on post-inflection years only. Populated
    # ONLY when the full-history EPV was judged inflecting, so the reader gets
    # a usable second reading instead of a bare refusal.
    epv_recent_regime: EarningsPowerResult | None = None
    data_gaps: list[str] = field(default_factory=list)

    @property
    def value_ladder(self) -> list[tuple[str, float | None]]:
        """The three rungs, in Greenwald's mandated reading order."""
        return [
            ("Asset reproduction value", self.asset_value.asset_value_per_share),
            ("Earnings power value", self.earnings_power.epv_per_share),
            ("Market price", self.current_price),
        ]


def compute_greenwald_valuation(
    ticker: str,
    *,
    wacc: float | None = None,
    tax_rate: float | None = None,
    max_history_years: int = 10,
) -> GreenwaldValuation:
    """Load persisted fundamentals and run the full Greenwald ladder.

    Reuses the Damodaran engine's WACC when not supplied, deliberately: the two
    valuations must be discounted at the SAME rate or their comparison is
    meaningless. WACC is a property of the company, not of the framework
    (``single_source_of_truth``).
    """
    from data.reader import CompanyDataReader

    gaps: list[str] = []
    reader = CompanyDataReader(ticker)
    annuals = reader.annuals(last_n=max_history_years)
    if not annuals:
        raise ValueError(f"{ticker}: no annual financials persisted — refresh first")

    latest = annuals[0]
    # Filed counts predate any later split; price history is split-adjusted.
    # Without a known factor the as-filed count stands (see share_basis).
    filed = cast("float | None", latest.shares_outstanding)
    shares = shares_on_current_basis(
        filed, cast("float | None", latest.share_split_factor),
    ) or filed
    oldest_first = list(reversed(annuals))

    # ── WACC + tax: borrow from the Damodaran engine so both ladders discount
    # at the same rate. Falls back to explicit defaults with a loud gap.
    wacc_source = "supplied"
    if wacc is None:
        try:
            from valuation.damodaran.cost_of_capital import compute_wacc
            from valuation.damodaran.loader import load_inputs
            iv_inputs = load_inputs(ticker)
            wacc_res = compute_wacc(
                ticker=ticker,
                sector=getattr(iv_inputs, "sector", None),
                market_cap=iv_inputs.market_cap,
                total_debt=iv_inputs.total_debt,
                cash_and_equivalents=latest.cash_and_equivalents,
                short_term_investments=latest.short_term_investments,
                interest_expense=latest.interest_expense,
                # ADR-043: both ladders must use the same currency-correct rate.
                reporting_currency=getattr(iv_inputs, "reporting_currency", None),
                industry=getattr(iv_inputs, "industry", None),
            )
            wacc = wacc_res.wacc
            wacc_source = "Damodaran engine (shared — both ladders discount at one rate)"
            gaps.extend(getattr(wacc_res, "data_gaps", []) or [])
        except Exception as exc:  # noqa: BLE001
            wacc = 0.09
            wacc_source = "fallback 9.0% placeholder"
            gaps.append(
                f"WACC unavailable from the Damodaran engine "
                f"({exc.__class__.__name__}: {exc}) — using a 9.0% placeholder. "
                f"Every capitalised value below inherits this assumption, and the "
                f"franchise ratio is only as good as the discount rate"
            )

    if tax_rate is None:
        tax_rate = 0.25
        if latest.income_tax_expense is not None and latest.operating_income:
            implied = latest.income_tax_expense / latest.operating_income
            if 0.0 <= implied < 0.60:
                tax_rate = implied
            else:
                gaps.append(
                    f"implied tax rate {implied:.1%} outside plausible range — "
                    f"using 25% statutory placeholder"
                )
        else:
            gaps.append("tax expense or operating income missing — using 25% placeholder")

    # ── Operating-margin history (oldest → newest) for normalisation ──
    margins: list[float | None] = []
    for row in oldest_first:
        if row.operating_income is not None and row.revenue:
            margins.append(row.operating_income / row.revenue)
        else:
            margins.append(None)

    rd_history: list[float | None] = [r.rd_expense for r in oldest_first]

    av = compute_asset_value(
        current_assets=latest.current_assets,
        current_liabilities=latest.current_liabilities,
        total_assets=latest.total_assets,
        goodwill=latest.goodwill,
        cash_and_equivalents=latest.cash_and_equivalents,
        total_debt=latest.total_debt,
        short_term_investments=latest.short_term_investments,
        rd_expense_history=rd_history,
        sga_expense=latest.sga_expense,
        shares_outstanding=shares,
    )

    price = None
    prices = reader.price_history(last_n=1)
    if prices:
        price = prices[0].close

    ep = compute_earnings_power(
        op_margin_history=margins,
        current_revenue=latest.revenue,
        depreciation=latest.depreciation_amortization,
        capex=latest.capex,
        tax_rate=tax_rate,
        wacc=wacc,
        cash_and_equivalents=latest.cash_and_equivalents,
        short_term_investments=latest.short_term_investments,
        total_debt=latest.total_debt,
        shares_outstanding=shares,
        current_price=price,
    )

    # ── Applicability gate + recent-regime fallback ──
    applicability, reason = assess_epv_applicability(margins)
    ep_recent: EarningsPowerResult | None = None
    if applicability == EPV_INFLECTING:
        # Recompute on the post-inflection run only: the trailing block of
        # consecutive profitable years. This is not a forecast — it is the same
        # deterministic EPV math applied to the regime that actually obtains.
        recent: list[float | None] = []
        for m in reversed(margins):
            if m is None or m < 0:
                break
            recent.append(m)
        recent.reverse()
        if len(recent) >= 2:
            ep_recent = compute_earnings_power(
                op_margin_history=list(recent),
                current_revenue=latest.revenue,
                depreciation=latest.depreciation_amortization,
                capex=latest.capex,
                tax_rate=tax_rate,
                wacc=wacc,
                cash_and_equivalents=latest.cash_and_equivalents,
                short_term_investments=latest.short_term_investments,
                total_debt=latest.total_debt,
                shares_outstanding=shares,
                current_price=price,
                min_history_years=2,
            )
            gaps.append(
                f"recent-regime EPV computed on the last {len(recent)} profitable "
                f"year(s) only — a narrower base than Greenwald intends, so treat it "
                f"as an upper reading of current earning power, not a cycle average"
            )

    # The franchise test runs on whichever EPV is defensible. Testing a
    # pre-inflection EPV against reproduction cost would return
    # "value destruction" for a business that is currently profitable.
    epv_for_franchise = ep.epv_operations
    if ep_recent is not None and ep_recent.epv_operations is not None:
        epv_for_franchise = ep_recent.epv_operations

    fr = assess_franchise(
        epv_operations=epv_for_franchise,
        asset_value_total=av.asset_value_total,
    )

    gaps.extend(av.data_gaps)
    gaps.extend(ep.data_gaps)
    gaps.extend(fr.data_gaps)
    if applicability != EPV_APPLICABLE:
        gaps.append(f"EPV applicability = {applicability}: {reason}")

    return GreenwaldValuation(
        ticker=ticker,
        asset_value=av,
        earnings_power=ep,
        franchise=fr,
        current_price=price,
        wacc_used=wacc,
        wacc_source=wacc_source,
        epv_applicability=applicability,
        epv_applicability_reason=reason,
        epv_recent_regime=ep_recent,
        data_gaps=gaps,
    )
