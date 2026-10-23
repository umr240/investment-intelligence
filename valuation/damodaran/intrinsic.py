"""Damodaran intrinsic value — top-level orchestration (ADR-027 Phase B).

Assembles cost-of-capital → NOPAT → reinvestment → growth → FCFF projection
→ terminal value → sensitivity matrix into the canonical `IVResult`.

The function `compute_intrinsic_value` takes **already-prepared inputs**
(no DB coupling at this layer — the caller is responsible for pulling
Financial rows, computing R&D history, etc.). This keeps the math layer
pure and unit-testable; the DB-coupled wrapper lives in Phase B-3 or
later (CLI / dive integration).

Public API:
    compute_intrinsic_value(IntrinsicValueInputs) -> IVResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Sequence

from valuation.damodaran.cost_of_capital import WACCResult, compute_wacc
from valuation.damodaran.fcff import project_fcff
from valuation.damodaran.growth import compute_fundamental_growth
from valuation.damodaran.nopat import NOPATResult, Tier, compute_nopat
from valuation.damodaran.reinvestment import compute_reinvestment
from valuation.damodaran.sensitivity import SensitivityResult, sensitivity_grid
from valuation.damodaran.terminal import compute_terminal_value


# ── Input + result types ─────────────────────────────────────────────────


@dataclass(frozen=True)
class IntrinsicValueInputs:
    """All inputs the calc needs. Caller (CLI / dive) is responsible for
    pulling these from the DB and constructing the dataclass."""

    ticker: str
    sector: str | None
    country: str | None

    # Market data
    market_cap: float
    current_price: float
    shares_outstanding: float

    # Latest annual / LTM financials
    operating_income: float | None              # EBIT_gaap
    rd_expense_current: float | None
    rd_history: Sequence[float | None]         # newest-last, for amortization
    capex: float | None
    depreciation_amortization: float | None
    interest_expense: float | None

    # Balance sheet (current period)
    total_equity: float
    total_debt: float
    cash_and_equivalents: float | None
    short_term_investments: float | None
    current_assets: float | None
    current_liabilities: float | None

    # Balance sheet (prior period — for ΔWC)
    current_assets_prior: float | None
    current_liabilities_prior: float | None

    # Modeling assumptions (with sensible defaults)
    high_growth_years: int = 8                  # 5-10 typical; 8 default
    growth_rate_terminal: float | None = None   # None → use risk-free rate
    as_of_date: str = "2026-05-13"

    # Phase C — multi-year smoothing override. When provided, the calc uses
    # this value instead of computing reinvestment from single-period capex
    # + ΔWC. Damodaran's textbook prescribes 3-5yr averaging for lumpy
    # reinvestment (M&A-heavy filers, capacity buildouts, etc.). Loader
    # computes this from a multi-year window and passes it in.
    reinvestment_rate_override: float | None = None

    # ADR-028 — optional young-company scenario for Tier C rescue.
    # When provided AND nopat tier resolves to C_insufficient, the calc
    # delegates to valuation.damodaran.young_company.compute_young_iv()
    # instead of returning a Tier C data-gap. Result is converted back to
    # IVResult with tier="C_yc_resolved" and young_company_* fields populated.
    # Per ADR-028 §Constraints: the scenario is the user-stated story —
    # never auto-generated.
    young_company_scenario: Any | None = None        # ScenarioInputs from young_company.py

    # ADR-028 — fields needed by young-company calc (OCF trajectory for
    # survival-probability derivation, industry for peer-benchmark lookup,
    # revenue as the year-0 anchor for top-down trajectory).
    # Optional because ADR-027 (Tier A/B) doesn't need them.
    operating_cash_flow: float | None = None
    prior_operating_cash_flow: float | None = None
    industry: str | None = None
    # ADR-043 §2.2 — reporting currency selects the risk-free rate.
    reporting_currency: str | None = None
    revenue: float | None = None

    # ADR-030 — ROIC history (newest-last) for the maturity classifier.
    # Default empty — single-period fallback in _classify_ticker_maturity.
    roic_history: Sequence[float | None] = ()

    # Cyclical detection history (newest-last). Used by classify_maturity to
    # distinguish cyclical_mature from young when ROIC stability fails.
    revenue_history: Sequence[float | None] = ()
    op_margin_history: Sequence[float | None] = ()


@dataclass(frozen=True)
class IVResult:
    ticker: str
    tier: Literal["A_gaap", "B_pt_rescued", "C_insufficient"]

    # The headline number
    intrinsic_value_per_share: float | None     # None when tier == C
    current_price: float
    margin_of_safety_pct: float | None          # None when tier == C

    # Source attribution
    nopat_source: str                            # "gaap" | "pt_adjusted" | "n/a"

    # Cost of capital
    wacc_result: WACCResult | None

    # Cash flow projections (Year 1..N)
    nopat_base: float | None
    reinvestment_rate: float | None
    growth_rate_high: float | None
    growth_period_years: int
    growth_rate_terminal: float | None
    fcff_projections: list[float]                # year 1..N
    pv_high_growth_fcff_total: float | None

    # Terminal value
    terminal_value: float | None
    terminal_value_pv: float | None
    terminal_value_pct_of_total: float | None    # TV_PV / (TV_PV + PV_high)

    # Enterprise → equity bridge
    enterprise_value: float | None
    net_debt: float | None
    equity_value: float | None

    # Sensitivity
    sensitivity: SensitivityResult | None

    # Provenance
    reference_data_staleness_days: int
    data_gaps: list[str] = field(default_factory=list)
    inversion_questions: list[str] = field(default_factory=list)

    # ADR-028 — young-company DCF fields. None for Tier A / B / unresolved C.
    # Populated when tier == "C_yc_resolved" (Tier C rescued via young-company
    # target-margin DCF with a user-supplied scenario).
    young_company_scenario_name: str | None = None
    young_company_peer_ticker: str | None = None
    young_company_target_margin: float | None = None
    young_company_sales_to_capital: float | None = None
    young_company_survival_probability: float | None = None
    young_company_survival_source: str | None = None
    young_company_cash_runway_years: float | None = None
    young_company_revenue_projections: list[float] | None = None
    young_company_op_margin_projections: list[float] | None = None
    young_company_sensitivity_matrix: list[list[float]] | None = None
    young_company_iv_p25: float | None = None
    young_company_iv_median: float | None = None
    young_company_iv_p75: float | None = None

    # ADR-029 — universal sibling outputs. Populated on every IV computation
    # regardless of tier. None when not computable (e.g., negative NOPAT for
    # EPV, no current price for narrative premium).
    epv_per_share: float | None = None              # Greenwald no-growth floor
    epv_total: float | None = None                  # enterprise-value perpetuity
    mos_vs_epv_pct: float | None = None             # (epv − price) / price
    reverse_implied_growth_rate: float | None = None    # market-implied g_high
    reverse_implied_growth_feasibility: str | None = None  # 'plausible'|'aggressive'|'extreme'|'unsolvable_*'
    narrative_premium_pct: float | None = None      # (price − forward_IV) / price
    narrative_premium_vs_epv_pct: float | None = None  # (price − EPV) / price

    # ADR-030 — maturity classification (informational; tier sub-classification
    # baked into the `tier` field as A_mature / A_young / B_mature / B_young).
    # None when classifier not run (e.g., Tier C path bypasses it).
    maturity_classification: Any | None = None

    # Cyclical-mature normalization (when maturity_classification.tier ==
    # "cyclical_mature"): the DCF NOPAT base is overridden to mid-cycle
    # normalized values instead of trailing. These fields surface what was
    # used so the audit trail shows why the IV differs from a naive standard
    # DCF on the same ticker.
    cyclical_normalization_applied: bool = False
    normalized_margin_used: float | None = None       # median op margin over cycle
    normalized_revenue_used: float | None = None      # mean revenue over cycle

    # Cluster detector — when EPV ≈ DCF ≈ Forward IV AND growth_rate_high ≈ 0,
    # the standard DCF has no growth lever to use. The model is reporting a
    # zero-growth EPV as if it were a fundamental IV. Set tier="C_growth_invalid"
    # and surface model_gap_pct in place of narrative_premium_pct, which
    # otherwise mislabels model error as market irrationality.
    growth_input_invalid: bool = False
    model_gap_pct: float | None = None                 # (price − EPV) / price when cluster fires


# ── Helper: full pipeline as a callable for the sensitivity grid ────────


def _build_iv_computation(inputs: IntrinsicValueInputs, wacc_result: WACCResult, nopat_base: float, reinvest_rate: float, growth_high: float):
    """Closure that re-runs FCFF + terminal at perturbed (wacc, g_term) — used
    by sensitivity_grid to produce the 5x5 matrix. Returns
    (iv_per_share, iv_total) or None when inputs are degenerate."""
    high_growth_years = inputs.high_growth_years
    shares = inputs.shares_outstanding
    risk_free = wacc_result.risk_free_rate
    net_debt = (
        inputs.total_debt
        - (inputs.cash_and_equivalents or 0.0)
        - (inputs.short_term_investments or 0.0)
    )

    def _run(wacc: float, g_term: float) -> tuple[float, float] | None:
        # Guard rails for this cell
        if wacc <= 0 or wacc <= growth_high or shares <= 0:
            return None
        try:
            proj = project_fcff(
                nopat_base=nopat_base,
                growth_rate=growth_high,
                reinvestment_rate=reinvest_rate,
                high_growth_years=high_growth_years,
                wacc=wacc,
            )
            term = compute_terminal_value(
                nopat_high_growth_final=proj.nopat_projections[-1],
                growth_rate_terminal=g_term,
                high_growth_years=high_growth_years,
                wacc=wacc,
                risk_free_rate=risk_free,
            )
        except (ValueError, ZeroDivisionError):
            return None

        ev = proj.pv_high_growth_fcff_total + term.terminal_value_pv
        equity = ev - net_debt
        iv_ps = equity / shares
        return iv_ps, ev

    return _run


# ── Main public function ─────────────────────────────────────────────────


def compute_intrinsic_value(inputs: IntrinsicValueInputs) -> IVResult:
    """End-to-end Damodaran intrinsic value.

    Returns an `IVResult` with `intrinsic_value_per_share = None` and a
    `data_gap` entry when the ticker falls into Tier C (loss-maker after
    R&D rescue).
    """
    data_gaps: list[str] = []

    # ── 1. Cost of capital ────────────────────────────────────────────────
    wacc_res = compute_wacc(
        ticker=inputs.ticker,
        sector=inputs.sector,
        country=inputs.country,
        market_cap=inputs.market_cap,
        total_debt=inputs.total_debt,
        cash_and_equivalents=inputs.cash_and_equivalents,
        short_term_investments=inputs.short_term_investments,
        interest_expense=inputs.interest_expense,
        as_of_date=inputs.as_of_date,
        # ADR-043: currency selects the risk-free rate; industry beats sector
        # for the industry beta.
        reporting_currency=inputs.reporting_currency,
        industry=inputs.industry,
    )
    data_gaps.extend(wacc_res.data_gaps)

    # ── 2. NOPAT (Tier A / B / C selection) ──────────────────────────────
    nopat_res = compute_nopat(
        ebit_gaap=inputs.operating_income,
        marginal_tax_rate=wacc_res.marginal_tax_rate,
        rd_current=inputs.rd_expense_current,
        rd_history=inputs.rd_history,
    )
    for n in nopat_res.notes:
        data_gaps.append(f"{inputs.ticker}: {n}")

    if nopat_res.tier == Tier.C_INSUFFICIENT:
        # ADR-028: if user provided a young-company scenario, delegate to the
        # target-margin DCF path. Otherwise emit the standard Tier-C data-gap
        # result.
        if inputs.young_company_scenario is not None:
            return _delegate_to_young_company(inputs, wacc_res, data_gaps)

        # Tier C: emit a clean "insufficient inputs" result. EPV still attempted
        # (will be negative — that's the diagnostic). Reverse DCF not run
        # because there's no fundamental anchor to bisect against.
        # Compute net_debt for the EPV sibling.
        tier_c_net_debt = (
            (inputs.total_debt or 0.0)
            - (inputs.cash_and_equivalents or 0.0)
            - (inputs.short_term_investments or 0.0)
        )
        primary_c = IVResult(
            ticker=inputs.ticker,
            tier=Tier.C_INSUFFICIENT.value,
            intrinsic_value_per_share=None,
            current_price=inputs.current_price,
            margin_of_safety_pct=None,
            nopat_source=nopat_res.nopat_source,
            wacc_result=wacc_res,
            nopat_base=None,
            reinvestment_rate=None,
            growth_rate_high=None,
            growth_period_years=inputs.high_growth_years,
            growth_rate_terminal=None,
            fcff_projections=[],
            pv_high_growth_fcff_total=None,
            terminal_value=None,
            terminal_value_pv=None,
            terminal_value_pct_of_total=None,
            enterprise_value=None,
            net_debt=tier_c_net_debt,
            equity_value=None,
            sensitivity=None,
            reference_data_staleness_days=wacc_res.reference_data_staleness_days,
            data_gaps=data_gaps,
            inversion_questions=[
                "Is this company genuinely structurally unprofitable, or at a "
                "cyclical bottom? If cyclical, what mid-cycle margin is justified?",
                "What target operating margin (mature peer) could this company "
                "plausibly reach, and how long to get there?",
                "What is the cash runway? Does the company have time to reach "
                "profitability before needing dilutive financing?",
            ],
        )
        # Tier C: NOPAT is negative (or 0). Use GAAP NOPAT for EPV calc — will
        # be negative and surface "EPV negative — narrative is only anchor" flag.
        tier_c_nopat = (
            (inputs.operating_income or 0.0) * (1.0 - wacc_res.marginal_tax_rate)
            if inputs.operating_income is not None else None
        )
        return _attach_sibling_outputs(
            primary_c, wacc_res=wacc_res, nopat=tier_c_nopat,
            reinvestment_rate=None, growth_terminal=None,
            high_growth_years=inputs.high_growth_years, net_debt=tier_c_net_debt,
            shares_outstanding=inputs.shares_outstanding, current_price=inputs.current_price,
        )

    # ── 2.5. Maturity classifier (ADR-030) ──────────────────────────────
    # Inserted between Tier A/B determination and fundamental DCF execution.
    # If the filer is classified as YOUNG (ROIC below WACC×1.3 floor OR
    # erratic CoV) AND a scenario is provided, delegate to ADR-028. Otherwise
    # continue with fundamental DCF but tag the result as young (data_gap).
    maturity = _classify_ticker_maturity(inputs, wacc_res, nopat_res)

    # ── 2.5a. Cyclical-mature normalization ─────────────────────────────────
    # When the classifier identifies a cyclical_mature pattern (KLIC archetype:
    # 9yr history, revenue 1.5× peak-to-trough, margin stdev >10pp), the
    # trailing NOPAT anchor is structurally wrong — it's a trough snapshot.
    # Override the NOPAT base with normalized values: median margin × mean
    # revenue × (1 − ETR). Same DCF math runs downstream; only the base
    # changes. Result is tagged A_cyclical / B_cyclical instead of *_young.
    cyclical_norm_applied = False
    if (
        maturity is not None
        and maturity.tier == "cyclical_mature"
        and maturity.normalized_margin is not None
        and maturity.normalized_revenue is not None
    ):
        normalized_op_income = maturity.normalized_margin * maturity.normalized_revenue
        normalized_nopat = normalized_op_income * (1.0 - wacc_res.marginal_tax_rate)
        from dataclasses import replace as _replace_nopat
        nopat_res = _replace_nopat(nopat_res, nopat=normalized_nopat)
        cyclical_norm_applied = True
        data_gaps.append(
            f"{inputs.ticker}: cyclical-mature detected. NOPAT base overridden "
            f"from trailing ${(inputs.operating_income or 0)*(1-wacc_res.marginal_tax_rate)/1e6:.0f}M "
            f"to normalized ${normalized_nopat/1e6:.0f}M "
            f"(median margin {maturity.normalized_margin*100:.1f}% × cycle-mean revenue "
            f"${maturity.normalized_revenue/1e6:.0f}M × ETR {wacc_res.marginal_tax_rate*100:.0f}%)."
        )

    if maturity is not None and not maturity.is_mature and not cyclical_norm_applied:
        # Standard young-company path (unchanged from prior behaviour)
        if inputs.young_company_scenario is not None:
            # Young + scenario → delegate to ADR-028 path
            result = _delegate_to_young_company(inputs, wacc_res, data_gaps)
            # Patch tier label to surface the maturity sub-classification
            from dataclasses import replace
            new_tier = (
                "A_young_yc_resolved" if nopat_res.tier == Tier.A_GAAP
                else "B_young_yc_resolved"
            )
            return replace(result, tier=new_tier, maturity_classification=maturity)
        else:
            data_gaps.append(
                f"{inputs.ticker}: Maturity classifier flagged this filer as YOUNG. "
                f"ROIC floor = {maturity.roic_floor:.2%}; "
                f"floor_pass={maturity.floor_pass}; stability_pass={maturity.stability_pass}; "
                f"history_pass={maturity.history_pass}. "
                f"Forward DCF using fundamental growth (ROIC × reinvestment_rate) "
                f"may structurally understate valuation for still-scaling filers. "
                f"Provide a young-company scenario (ADR-028) for a target-margin DCF, "
                f"or interpret the IV below as a CONSERVATIVE FLOOR."
            )
            # Continue with fundamental DCF below; tier label will be re-stamped
            # at the return statement to A_young / B_young.

    # ── 3. Invested capital + ROIC (uses 5S-5 formula: E + D − cash − STI) ─
    invested_capital = (
        inputs.total_equity
        + inputs.total_debt
        - (inputs.cash_and_equivalents or 0.0)
        - (inputs.short_term_investments or 0.0)
    )
    if invested_capital <= 0:
        data_gaps.append(
            f"{inputs.ticker}: invested_capital = ${invested_capital:,.0f} ≤ 0 "
            f"(cash + STI exceeds equity + debt). ROIC undefined; intrinsic "
            f"value not computable from this framework."
        )
        return IVResult(
            ticker=inputs.ticker,
            tier=nopat_res.tier.value,
            intrinsic_value_per_share=None,
            current_price=inputs.current_price,
            margin_of_safety_pct=None,
            nopat_source=nopat_res.nopat_source,
            wacc_result=wacc_res,
            nopat_base=nopat_res.nopat,
            reinvestment_rate=None,
            growth_rate_high=None,
            growth_period_years=inputs.high_growth_years,
            growth_rate_terminal=None,
            fcff_projections=[],
            pv_high_growth_fcff_total=None,
            terminal_value=None,
            terminal_value_pv=None,
            terminal_value_pct_of_total=None,
            enterprise_value=None,
            net_debt=None,
            equity_value=None,
            sensitivity=None,
            reference_data_staleness_days=wacc_res.reference_data_staleness_days,
            data_gaps=data_gaps,
            inversion_questions=[],
        )

    roic = nopat_res.nopat / invested_capital

    # ── 4. Reinvestment rate ─────────────────────────────────────────────
    # Phase C: when caller supplies a multi-year-averaged override, use it
    # directly (Damodaran's normalization for lumpy capex / M&A spikes).
    # Otherwise compute from single-period capex + ΔWC.
    if inputs.reinvestment_rate_override is not None:
        # Build a minimal ReinvestmentResult for downstream provenance
        from valuation.damodaran.reinvestment import ReinvestmentResult
        reinv_res = ReinvestmentResult(
            capex=inputs.capex or 0.0,
            depreciation_amortization=inputs.depreciation_amortization or 0.0,
            net_capex=(inputs.capex or 0.0) - (inputs.depreciation_amortization or 0.0),
            working_capital_current=None,
            working_capital_prior=None,
            delta_working_capital=None,
            reinvestment_total=inputs.reinvestment_rate_override * nopat_res.nopat,
            nopat=nopat_res.nopat,
            reinvestment_rate=inputs.reinvestment_rate_override,
            notes=[
                f"Reinvestment rate = {inputs.reinvestment_rate_override:.1%} from "
                f"multi-year averaging (Phase C smoothing). Single-period capex/ΔWC "
                f"discarded for projection purposes."
            ],
        )
    else:
        reinv_res = compute_reinvestment(
            capex=inputs.capex,
            depreciation_amortization=inputs.depreciation_amortization,
            current_assets=inputs.current_assets,
            current_liabilities=inputs.current_liabilities,
            current_assets_prior=inputs.current_assets_prior,
            current_liabilities_prior=inputs.current_liabilities_prior,
            nopat=nopat_res.nopat,
        )
    for n in reinv_res.notes:
        data_gaps.append(f"{inputs.ticker}: {n}")

    # ── ICA → DCF reinvestment wire-up (Phase 5) ────────────────────────
    # When NOPAT path is PT-adjusted (Peters-Taylor R&D capitalized as an
    # asset), the reinvestment denominator/numerator must also include R&D
    # net-capex. Otherwise we add R&D back to NOPAT (numerator inflated) but
    # the reinvestment rate stays GAAP-only (denominator unchanged) → ratio
    # is artificially LOW, implied growth is artificially HIGH. The fix
    # adds (R&D_current − R&D_amortization_current) to reinvestment_total.
    if nopat_res.nopat_source == "pt_adjusted":
        from valuation.damodaran.nopat import _rd_amortization
        rd_amort_current = _rd_amortization(inputs.rd_history) or 0.0
        rd_current = inputs.rd_expense_current or 0.0
        rd_net_capex = rd_current - rd_amort_current
        if rd_net_capex != 0:
            new_total = reinv_res.reinvestment_total + rd_net_capex
            new_rate = new_total / nopat_res.nopat
            from dataclasses import replace as _replace_reinv
            reinv_res = _replace_reinv(
                reinv_res,
                reinvestment_total=new_total,
                reinvestment_rate=new_rate,
            )
            data_gaps.append(
                f"{inputs.ticker}: PT-adjusted reinvestment — added R&D net-capex "
                f"${rd_net_capex/1e6:+.0f}M (R&D current ${rd_current/1e6:.0f}M − "
                f"R&D amortization ${rd_amort_current/1e6:.0f}M) to reinvestment "
                f"so the R&D treatment is consistent with PT NOPAT add-back."
            )

    # Clamp reinvestment rate to [0, 1.2] for projection sanity. A negative
    # rate means "no reinvestment" (which suggests no growth); >120% pushes
    # near-term FCFF deeply negative. We keep the RAW value in the result
    # but use a sanitised version for projection.
    reinv_for_projection = max(0.0, min(1.2, reinv_res.reinvestment_rate))
    if reinv_for_projection != reinv_res.reinvestment_rate:
        data_gaps.append(
            f"{inputs.ticker}: reinvestment rate {reinv_res.reinvestment_rate:.1%} "
            f"clamped to {reinv_for_projection:.1%} for projection. Verify the "
            f"underlying capex/D&A/ΔWC figures."
        )

    # ── 5. Fundamental growth ────────────────────────────────────────────
    growth_res = compute_fundamental_growth(roic, reinv_for_projection)
    for n in growth_res.notes:
        data_gaps.append(f"{inputs.ticker}: {n}")
    growth_high = growth_res.growth_rate_capped

    # Sanity: growth_high must be < WACC for the high-growth DCF to converge
    if growth_high >= wacc_res.wacc:
        # Cap growth_high to WACC − 50bps minimum
        new_g = wacc_res.wacc - 0.005
        data_gaps.append(
            f"{inputs.ticker}: fundamental growth {growth_high:.2%} >= WACC "
            f"{wacc_res.wacc:.2%}. Capped to WACC − 50bps = {new_g:.2%} for "
            f"projection. Implies the high-growth phase can't last long at "
            f"this ROIC × reinvestment combo."
        )
        growth_high = new_g

    # ── 6. Terminal growth (default = risk-free rate cap) ────────────────
    g_terminal = inputs.growth_rate_terminal
    if g_terminal is None:
        g_terminal = wacc_res.risk_free_rate  # Damodaran's default ceiling

    # ── 7. FCFF projection over high-growth phase ────────────────────────
    proj = project_fcff(
        nopat_base=nopat_res.nopat,
        growth_rate=growth_high,
        reinvestment_rate=reinv_for_projection,
        high_growth_years=inputs.high_growth_years,
        wacc=wacc_res.wacc,
    )
    for n in proj.notes:
        data_gaps.append(f"{inputs.ticker}: {n}")

    # ── 8. Terminal value ────────────────────────────────────────────────
    term = compute_terminal_value(
        nopat_high_growth_final=proj.nopat_projections[-1],
        growth_rate_terminal=g_terminal,
        high_growth_years=inputs.high_growth_years,
        wacc=wacc_res.wacc,
        risk_free_rate=wacc_res.risk_free_rate,
    )
    for n in term.notes:
        data_gaps.append(f"{inputs.ticker}: {n}")

    # ── 9. Assemble enterprise → equity ──────────────────────────────────
    enterprise_value = proj.pv_high_growth_fcff_total + term.terminal_value_pv
    net_debt = (
        inputs.total_debt
        - (inputs.cash_and_equivalents or 0.0)
        - (inputs.short_term_investments or 0.0)
    )
    equity_value = enterprise_value - net_debt
    iv_per_share = equity_value / inputs.shares_outstanding if inputs.shares_outstanding > 0 else None

    if iv_per_share is None:
        data_gaps.append(f"{inputs.ticker}: shares_outstanding ≤ 0; per-share IV not computable")
        mos = None
    elif inputs.current_price > 0:
        mos = (iv_per_share - inputs.current_price) / iv_per_share
    else:
        mos = None
        data_gaps.append(f"{inputs.ticker}: current_price ≤ 0; margin of safety not computable")

    # ── 10. Sensitivity grid ──────────────────────────────────────────────
    iv_callback = _build_iv_computation(
        inputs, wacc_res, nopat_res.nopat, reinv_for_projection, growth_high
    )
    sens = sensitivity_grid(
        base_wacc=wacc_res.wacc,
        base_growth_terminal=term.growth_rate_terminal,
        risk_free_rate=wacc_res.risk_free_rate,
        compute_iv_per_share=iv_callback,
    )

    # ── 11. Terminal-value share + inversion questions ───────────────────
    total_pv = proj.pv_high_growth_fcff_total + term.terminal_value_pv
    tv_pct = term.terminal_value_pv / total_pv if total_pv > 0 else None
    if tv_pct is not None and tv_pct > 0.80:
        data_gaps.append(
            f"{inputs.ticker}: terminal value is {tv_pct:.0%} of total IV — "
            f"valuation is essentially all about the terminal assumption. "
            f"Verify the terminal growth + cost-of-capital inputs are defensible."
        )

    inversion_questions = [
        f"What WACC + growth combination would have to be true for IV to be "
        f"30% LOWER than ${iv_per_share:.2f}? "
        f"(Check the P5 corner of the sensitivity grid.)",
        f"Terminal value is {tv_pct*100:.0f}% of total IV. "
        f"If terminal growth = 0 instead of {g_terminal:.1%}, what's IV?",
        "What would have to be true about the moat / competitive position "
        f"for this company to maintain {growth_high:.1%} growth for "
        f"{inputs.high_growth_years} years?",
    ]

    # ADR-030 — stamp sub-tier label based on maturity classification.
    # cyclical_norm_applied takes precedence over young/mature labelling so
    # the audit trail shows the cyclical normalization branch was used.
    if maturity is not None:
        if cyclical_norm_applied:
            if nopat_res.tier == Tier.A_GAAP:
                tier_label = "A_cyclical"
            elif nopat_res.tier == Tier.B_PT_RESCUED:
                tier_label = "B_cyclical"
            else:
                tier_label = nopat_res.tier.value
        elif nopat_res.tier == Tier.A_GAAP:
            tier_label = "A_mature" if maturity.is_mature else "A_young"
        elif nopat_res.tier == Tier.B_PT_RESCUED:
            tier_label = "B_mature" if maturity.is_mature else "B_young"
        else:
            tier_label = nopat_res.tier.value
    else:
        tier_label = nopat_res.tier.value

    primary_ab = IVResult(
        ticker=inputs.ticker,
        tier=tier_label,
        intrinsic_value_per_share=iv_per_share,
        current_price=inputs.current_price,
        margin_of_safety_pct=mos,
        nopat_source=nopat_res.nopat_source,
        wacc_result=wacc_res,
        nopat_base=nopat_res.nopat,
        reinvestment_rate=reinv_res.reinvestment_rate,
        growth_rate_high=growth_high,
        growth_period_years=inputs.high_growth_years,
        growth_rate_terminal=term.growth_rate_terminal,
        fcff_projections=proj.fcff_projections,
        pv_high_growth_fcff_total=proj.pv_high_growth_fcff_total,
        terminal_value=term.terminal_value,
        terminal_value_pv=term.terminal_value_pv,
        terminal_value_pct_of_total=tv_pct,
        enterprise_value=enterprise_value,
        net_debt=net_debt,
        equity_value=equity_value,
        sensitivity=sens,
        reference_data_staleness_days=wacc_res.reference_data_staleness_days,
        data_gaps=data_gaps,
        inversion_questions=inversion_questions,
    )
    # ADR-030 — attach maturity classification + cyclical normalization
    # diagnostics before sibling outputs
    from dataclasses import replace as _replace
    if maturity is not None:
        primary_ab = _replace(
            primary_ab,
            maturity_classification=maturity,
            cyclical_normalization_applied=cyclical_norm_applied,
            normalized_margin_used=maturity.normalized_margin if cyclical_norm_applied else None,
            normalized_revenue_used=maturity.normalized_revenue if cyclical_norm_applied else None,
        )

    # ADR-029 — populate universal sibling outputs (EPV + reverse DCF + narrative %)
    return _attach_sibling_outputs(
        primary_ab, wacc_res=wacc_res, nopat=nopat_res.nopat,
        reinvestment_rate=reinv_for_projection, growth_terminal=term.growth_rate_terminal,
        high_growth_years=inputs.high_growth_years, net_debt=net_debt,
        shares_outstanding=inputs.shares_outstanding, current_price=inputs.current_price,
    )


# ── ADR-029 universal sibling outputs ────────────────────────────────────


def _attach_sibling_outputs(
    primary: IVResult,
    *,
    wacc_res: WACCResult,
    nopat: float | None,
    reinvestment_rate: float | None,
    growth_terminal: float | None,
    high_growth_years: int,
    net_debt: float | None,
    shares_outstanding: float,
    current_price: float,
) -> IVResult:
    """Compute EPV + reverse DCF + narrative premium % and attach to IVResult.

    Universal sibling outputs (ADR-029):
      - EPV — Greenwald no-growth floor. Always attempted; flagged when NOPAT < 0.
      - Reverse DCF — bisection over growth_rate_high until DCF = market cap.
        Only fires for Tier A/B (positive NOPAT + valid reinvestment rate).
      - Narrative premium % — (price − forward_IV) / price; also EPV variant.

    Per ADR-029: this fires on EVERY IV computation. Sibling fields are
    None when uncomputable; the rest of the result is untouched.
    """
    from dataclasses import replace
    from valuation.damodaran.epv import compute_epv
    from valuation.damodaran.reverse_dcf import reverse_solve_growth

    nd = net_debt or 0.0

    # ── EPV ───────────────────────────────────────────────────────────────
    epv_per_share = None
    epv_total = None
    mos_vs_epv = None
    if nopat is not None and shares_outstanding > 0:
        try:
            epv = compute_epv(
                nopat=nopat,
                wacc=wacc_res.wacc,
                net_debt=nd,
                shares_outstanding=shares_outstanding,
                current_price=current_price,
            )
            epv_per_share = epv.epv_per_share
            epv_total = epv.epv_total
            mos_vs_epv = epv.mos_vs_epv_pct
            # EPVResult.notes carries the diagnostics that matter most for
            # reading the number — "EPV negative, narrative is the only
            # anchor", "WACC <= 0, EPV undefined". They were computed and then
            # dropped on the floor, so a negative EPV surfaced as a bare
            # number with no explanation. Route them into the gap register.
            for note in epv.notes:
                primary.data_gaps.append(f"EPV: {note}")
        except Exception as exc:                                # noqa: BLE001
            primary.data_gaps.append(
                f"EPV unavailable ({exc.__class__.__name__}: {exc}) — "
                f"no-growth floor could not be computed"
            )

    # ── Reverse DCF (Tier A/B only; Tier C deferred to ADR-029 v2) ───────
    implied_g = None
    implied_feasibility = None
    # Tier gate. ADR-029 originally matched the raw nopat tiers ("A_gaap" /
    # "B_pt_rescued"), but ADR-030 re-stamped `tier` with maturity sub-labels
    # (A_mature / A_young / B_mature / B_young / A_cyclical / B_cyclical), so
    # the literal match could only ever be true when maturity classification
    # was absent. Reverse DCF was therefore silently dead for every classified
    # ticker from ADR-030 onward — invisible because the block below swallowed
    # everything and `None` is a legal value for the field.
    #
    # Match on the tier FAMILY instead, so future sub-tier labels do not
    # silently re-break this (illegal_states_unrepresentable would be better
    # still — a structured tier object rather than a string — but that is a
    # wider refactor than this fix should carry).
    tier_family_ok = str(primary.tier).split("_", 1)[0] in ("A", "B")
    if (
        tier_family_ok
        and nopat is not None
        and nopat > 0
        and reinvestment_rate is not None
        and growth_terminal is not None
        and current_price > 0
        and shares_outstanding > 0
    ):
        target_equity = current_price * shares_outstanding
        try:
            rev = reverse_solve_growth(
                target_equity_value=target_equity,
                nopat_base=nopat,
                wacc=wacc_res.wacc,
                reinvestment_rate=reinvestment_rate,
                growth_terminal=growth_terminal,
                high_growth_years=high_growth_years,
                risk_free_rate=wacc_res.risk_free_rate,
                net_debt=nd,
                shares_outstanding=shares_outstanding,
            )
            if rev.implied_growth_rate is not None:
                implied_g = rev.implied_growth_rate
            implied_feasibility = rev.implied_growth_feasibility
        except Exception as exc:                                # noqa: BLE001
            # CLAUDE.md: no silent failures. A reverse DCF that cannot solve is
            # a data gap the reader must see, not a None that reads as "not
            # applicable".
            primary.data_gaps.append(
                f"reverse DCF unsolved ({exc.__class__.__name__}: {exc}) — "
                f"market-implied growth unavailable"
            )
    elif not tier_family_ok:
        primary.data_gaps.append(
            f"reverse DCF skipped — tier {primary.tier!r} has no positive NOPAT "
            f"base to solve against"
        )

    # ── Narrative premium ────────────────────────────────────────────────
    narrative_pct = None
    if (
        primary.intrinsic_value_per_share is not None
        and primary.intrinsic_value_per_share > 0
        and current_price > 0
    ):
        narrative_pct = (current_price - primary.intrinsic_value_per_share) / current_price

    narrative_vs_epv_pct = None
    if epv_per_share is not None and current_price > 0:
        narrative_vs_epv_pct = (current_price - epv_per_share) / current_price

    # ── Cluster detector: EPV ≈ DCF IV ≈ Forward IV with no growth ──────
    # When the three values cluster within 5% AND the high-growth rate is
    # essentially zero, the standard DCF has lost its growth lever — it's
    # reporting a zero-growth EPV as if it were a fundamental IV. This is
    # the trailing-NOPAT-anchor pathology that misvalues cyclicals in
    # troughs and SaaS post-buyback. Tag tier=C_growth_invalid, blank the
    # IV, and surface model_gap_pct instead of narrative_premium_pct so
    # the gap isn't mislabelled as market irrationality.
    growth_input_invalid = False
    model_gap = None
    iv_for_check = primary.intrinsic_value_per_share
    g_high = primary.growth_rate_high
    if (
        iv_for_check is not None
        and epv_per_share is not None
        and iv_for_check > 0
        and abs(epv_per_share - iv_for_check) / abs(iv_for_check) < 0.05
        and g_high is not None
        and g_high < 0.01
        and not primary.cyclical_normalization_applied
    ):
        growth_input_invalid = True
        if current_price > 0 and epv_per_share is not None:
            model_gap = (current_price - epv_per_share) / current_price
        # Tag tier and blank the IV — but keep nopat_base/epv visible for audit
        existing_gaps = list(primary.data_gaps)
        existing_gaps.append(
            f"{primary.ticker}: cluster signal — EPV ≈ DCF IV ≈ Forward IV "
            f"with growth_rate_high={g_high:.2%}. Standard DCF has no growth "
            f"lever; the IV reported would just be the no-growth EPV. Tier "
            f"forced to C_growth_invalid. Re-classify ticker (likely cyclical "
            f"at trough, post-buyback SaaS, or otherwise needs scenario-based "
            f"DCF — ADR-028 young-company method or cyclical normalization)."
        )
        primary = replace(
            primary,
            tier="C_growth_invalid",
            intrinsic_value_per_share=None,
            margin_of_safety_pct=None,
            data_gaps=existing_gaps,
        )

    return replace(
        primary,
        epv_per_share=epv_per_share,
        epv_total=epv_total,
        mos_vs_epv_pct=mos_vs_epv,
        reverse_implied_growth_rate=implied_g,
        reverse_implied_growth_feasibility=implied_feasibility,
        # When the cluster fires, the "narrative premium" is actually model
        # error — relabel to model_gap_pct and null out narrative_premium_pct.
        narrative_premium_pct=None if growth_input_invalid else narrative_pct,
        narrative_premium_vs_epv_pct=narrative_vs_epv_pct,
        growth_input_invalid=growth_input_invalid,
        model_gap_pct=model_gap,
    )


# ── ADR-030 maturity classifier integration ─────────────────────────────


def _classify_ticker_maturity(
    inputs: IntrinsicValueInputs,
    wacc_res: WACCResult,
    nopat_res: NOPATResult,
) -> Any | None:
    """Run the maturity classifier using ROIC history from the caller's
    inputs. Returns None when classification isn't applicable (Tier C —
    the maturity gate doesn't add information for loss-makers).

    For Tier A: classify on GAAP ROIC history.
    For Tier B: classify on PT-adjusted ROIC history (since Tier B's
                fundamental DCF runs on PT-adjusted NOPAT).

    Source priority:
      1. `inputs.roic_history` if populated (loader-supplied multi-year ROIC,
         newest-LAST). Enables the 3yr floor + CoV stability test the ADR
         actually calls for.
      2. Fallback: single-period ROIC derived from current NOPAT/IC.
         Stability cannot be evaluated → caller will typically land in
         `_young` since history_pass=False with only one observation.
    """
    from valuation.damodaran.maturity import classify_maturity

    if nopat_res.tier.value not in ("A_gaap", "B_pt_rescued"):
        return None
    if nopat_res.nopat is None:
        return None

    # Prefer loader-supplied multi-year history (ADR-030 §Validation requires
    # 3yr floor + CoV < 0.4, which is unverifiable from a single observation).
    roic_seq: list[float | None]
    if inputs.roic_history:
        roic_seq = [r for r in inputs.roic_history if r is not None]
    else:
        roic_seq = []

    if not roic_seq:
        invested_capital = (
            (inputs.total_equity or 0.0)
            + (inputs.total_debt or 0.0)
            - (inputs.cash_and_equivalents or 0.0)
            - (inputs.short_term_investments or 0.0)
        )
        if invested_capital <= 0:
            return None
        roic_seq = [nopat_res.nopat / invested_capital]

    rev_seq = [r for r in (inputs.revenue_history or ()) if r is not None]
    margin_seq = [m for m in (inputs.op_margin_history or ()) if m is not None]

    return classify_maturity(
        roic_history=roic_seq,
        wacc=wacc_res.wacc,
        revenue_history=rev_seq or None,
        op_margin_history=margin_seq or None,
    )


# ── ADR-028 young-company delegation ─────────────────────────────────────


def _delegate_to_young_company(
    inputs: IntrinsicValueInputs,
    wacc_res: WACCResult,
    data_gaps_so_far: list[str],
) -> IVResult:
    """Convert ADR-028 YoungCompanyResult → IVResult (lossless on key fields).

    Called from compute_intrinsic_value() when:
      - nopat_res.tier == Tier.C_INSUFFICIENT, AND
      - inputs.young_company_scenario is not None

    Builds the FinancialInputs from IntrinsicValueInputs, calls compute_young_iv,
    and packages the result with tier='C_yc_resolved'. Young-company-specific
    fields are surfaced through the young_company_* attributes on IVResult.
    """
    from valuation.damodaran.young_company import FinancialInputs, compute_young_iv

    fin = FinancialInputs(
        ticker=inputs.ticker,
        sector=inputs.sector,
        industry=inputs.industry,
        country=inputs.country,
        revenue=float(0.0),                              # rev derived from inputs below
        operating_income=float(inputs.operating_income or 0.0),
        cash_and_equivalents=float(inputs.cash_and_equivalents or 0.0),
        short_term_investments=inputs.short_term_investments,
        total_debt=float(inputs.total_debt or 0.0),
        total_equity=float(inputs.total_equity or 0.0),
        operating_cash_flow=float(inputs.operating_cash_flow or 0.0),
        prior_operating_cash_flow=inputs.prior_operating_cash_flow,
        market_cap=float(inputs.market_cap or 0.0),
        current_price=float(inputs.current_price or 0.0),
        shares_outstanding=float(inputs.shares_outstanding or 0.0),
        interest_expense=inputs.interest_expense,
    )
    # Revenue is read from operating_income / operating_margin? No — we
    # need actual revenue. IntrinsicValueInputs doesn't carry it directly
    # because Tier A/B path uses operating_income only. For young-company
    # path the caller MUST attach revenue via scenario or extend inputs.
    # For now, the scenario provides revenue_year_N; we backfill year-0
    # revenue from operating_income / current op margin if EBIT margin
    # isn't trivially zero — but cleanest is to require caller to attach.
    #
    # The loader is responsible for setting fin.revenue. Since FinancialInputs
    # is frozen, we use dataclasses.replace to inject revenue from inputs.
    # IntrinsicValueInputs doesn't have a revenue field today — add via
    # operating_income / (implied margin from scenario current state).
    # ACTUAL FIX: extend IntrinsicValueInputs with `revenue`. Done below as
    # an attribute lookup with fallback.
    revenue_value = getattr(inputs, "revenue", None)
    if revenue_value is None:
        # No revenue on inputs — flag and use scenario's revenue_year_N / e^(N×0.20) as
        # a rough back-cast. Caller should attach revenue explicitly.
        data_gaps_so_far.append(
            f"{inputs.ticker}: revenue not attached to IntrinsicValueInputs for young-company "
            f"path. Caller (loader) should set inputs.revenue. Back-casting from scenario."
        )
        revenue_value = inputs.young_company_scenario.revenue_year_N / (1.20 ** inputs.high_growth_years)

    from dataclasses import replace
    fin = replace(fin, revenue=float(revenue_value))

    yc_result = compute_young_iv(fin, inputs.young_company_scenario)

    # Convert to IVResult — preserve Tier C provenance + young-company fields.
    combined_gaps = list(data_gaps_so_far) + list(yc_result.data_gaps)
    primary_yc = IVResult(
        ticker=yc_result.ticker,
        tier=yc_result.tier,                                # "C_yc_resolved"
        intrinsic_value_per_share=yc_result.intrinsic_value_per_share,
        current_price=yc_result.current_price,
        margin_of_safety_pct=yc_result.margin_of_safety_pct,
        nopat_source="young_company_target_margin",
        wacc_result=yc_result.wacc_result,
        nopat_base=yc_result.nopat_projections[0] if yc_result.nopat_projections else None,
        reinvestment_rate=None,                              # young-company uses sales-to-capital, not a single rate
        growth_rate_high=yc_result.growth_rate_projections[0] if yc_result.growth_rate_projections else None,
        growth_period_years=len(yc_result.fcff_projections),
        growth_rate_terminal=yc_result.growth_rate_terminal,
        fcff_projections=yc_result.fcff_projections,
        pv_high_growth_fcff_total=yc_result.pv_high_growth_fcff_total,
        terminal_value=yc_result.terminal_value,
        terminal_value_pv=yc_result.terminal_value_pv,
        terminal_value_pct_of_total=yc_result.terminal_value_pct_of_total,
        enterprise_value=yc_result.enterprise_value_post_survival,    # survival-adjusted
        net_debt=yc_result.net_debt,
        equity_value=yc_result.equity_value,
        sensitivity=None,                                    # ADR-028 sensitivity has different schema
        reference_data_staleness_days=wacc_res.reference_data_staleness_days,
        data_gaps=combined_gaps,
        inversion_questions=yc_result.inversion_questions,
        # Young-company-specific fields
        young_company_scenario_name=yc_result.scenario_name,
        young_company_peer_ticker=yc_result.peer_ticker,
        young_company_target_margin=yc_result.target_op_margin_used,
        young_company_sales_to_capital=yc_result.sales_to_capital_ratio_used,
        young_company_survival_probability=yc_result.survival_probability_used,
        young_company_survival_source=yc_result.survival_probability_source,
        young_company_cash_runway_years=yc_result.cash_runway_years,
        young_company_revenue_projections=yc_result.revenue_projections,
        young_company_op_margin_projections=yc_result.op_margin_projections,
        young_company_sensitivity_matrix=yc_result.sensitivity_matrix,
        young_company_iv_p25=yc_result.iv_per_share_p25,
        young_company_iv_median=yc_result.iv_per_share_median,
        young_company_iv_p75=yc_result.iv_per_share_p75,
    )
    # ADR-029 sibling outputs for young-company path. EPV uses GAAP NOPAT
    # (will be negative — confirms "narrative is only anchor"). Reverse DCF
    # not yet supported for Tier C (different equation; deferred to v2).
    yc_nopat_for_epv = (
        (inputs.operating_income or 0.0) * (1.0 - wacc_res.marginal_tax_rate)
        if inputs.operating_income is not None else None
    )
    return _attach_sibling_outputs(
        primary_yc, wacc_res=wacc_res, nopat=yc_nopat_for_epv,
        reinvestment_rate=None,  # Tier C reverse DCF not supported in v1
        growth_terminal=yc_result.growth_rate_terminal,
        high_growth_years=len(yc_result.fcff_projections),
        net_debt=yc_result.net_debt,
        shares_outstanding=inputs.shares_outstanding,
        current_price=inputs.current_price,
    )
