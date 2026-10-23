"""Damodaran young-company target-margin DCF (ADR-028).

Resolves the Tier C gap in ADR-027 — companies whose economic EBIT is
negative even after R&D capitalization, where the fundamental DCF
(`g = ROIC × reinvestment_rate`) breaks down.

Substitutes four inputs that fail for loss-makers:

  ADR-027 (fundamental)                      → ADR-028 (top-down young-company)
  ────────────────────────────────────────────  ──────────────────────────────────────
  g = ROIC × reinvestment_rate                  Top-down revenue projection (story-anchored)
  Reinvestment from capex + ΔWC − D&A           Reinvestment from sales-to-capital ratio
  NOPAT = EBIT × (1−t)                          Target op margin from mature peer, interpolated
  (face value)                                  × Survival probability (from runway + burn)

Per ADR-028 §Constraints:
  - Deterministic math (scenario is user-stated, never auto-generated)
  - Inversion form mandatory (3 baseline questions auto-populated)
  - Story-discipline — calc REFUSES to run on defaults; user must supply
    ScenarioInputs or load a named archetype.

Public API:
    compute_young_iv(financial_inputs, scenario) -> YoungCompanyResult
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from valuation.damodaran.cost_of_capital import WACCResult, compute_wacc


# ── Constants ────────────────────────────────────────────────────────────

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference" / "damodaran"
PEER_BENCHMARK_FILE = "young_company_peers.json"

# Sanity bounds (per ADR-028 §Risks)
_MIN_SURVIVAL = 0.20            # below this, the company is essentially distressed
_MAX_SURVIVAL = 0.98            # nothing is 100% certain
_MIN_TARGET_MARGIN = -0.30      # even mature peers can have negative margins (rare)
_MAX_TARGET_MARGIN = 0.70       # >70% op margin is extreme even for Visa-class
_MIN_SALES_TO_CAPITAL = 0.3     # very capital-heavy (e.g. utilities)
_MAX_SALES_TO_CAPITAL = 8.0     # very capital-light (e.g. mature SaaS)


# ── Inputs ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FinancialInputs:
    """Existing-state financials for the company being valued — pulled from
    the DB. Distinct from ScenarioInputs (the user's stated story)."""

    # Required (no defaults) — must come first per dataclass rules
    ticker: str
    sector: str | None
    industry: str | None
    revenue: float                         # current revenue (year 0)
    operating_income: float                # likely negative for young company
    cash_and_equivalents: float            # for runway calc
    short_term_investments: float | None
    total_debt: float
    total_equity: float
    operating_cash_flow: float             # likely negative

    # Optional — defaults
    country: str = "United States"
    prior_operating_cash_flow: float | None = None    # for trajectory direction
    market_cap: float = 0.0
    current_price: float = 0.0
    shares_outstanding: float = 0.0
    interest_expense: float | None = None


@dataclass(frozen=True)
class ScenarioInputs:
    """The 'story' — explicit assumptions the user MUST state. The calc
    refuses to run on defaults.

    Per ADR-028: every input here is a stated business hypothesis. The
    inversion-form output forces the user to consider what would have to
    be wrong for the IV to flip 30% lower.
    """

    # Scenario attribution (mandatory)
    scenario_name: str                     # e.g. "tem-ai-platform-aggressive"

    # Revenue trajectory
    revenue_year_N: float                  # target revenue at end of horizon
    high_growth_years: int = 8             # length of high-growth phase
    growth_decay: Literal["linear", "scurve"] = "linear"

    # Margin trajectory
    target_op_margin: float | None = None  # None → load from peer benchmark
    years_to_target_margin: int = 8        # ≤ high_growth_years

    # Capital efficiency
    sales_to_capital_ratio: float | None = None    # None → load from peer benchmark

    # Survival probability (None → derive from runway + burn)
    survival_probability: float | None = None

    # Terminal
    growth_rate_terminal: float | None = None   # None → use risk-free rate

    # Peer attribution
    peer_ticker_override: str | None = None     # None → load from industry table

    # Story justification (free text — not used in math, but persisted)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.scenario_name:
            raise ValueError(
                "scenario_name is mandatory — name your story. The calc "
                "refuses to run on anonymous defaults (ADR-028 story discipline)."
            )
        if self.revenue_year_N <= 0:
            raise ValueError(f"revenue_year_N must be > 0, got {self.revenue_year_N}")
        if self.high_growth_years < 3 or self.high_growth_years > 15:
            raise ValueError(
                f"high_growth_years must be 3-15, got {self.high_growth_years}. "
                "Damodaran's standard range is 5-10."
            )
        if self.years_to_target_margin > self.high_growth_years:
            raise ValueError(
                "years_to_target_margin must be <= high_growth_years"
            )


# ── Output ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class YoungCompanyResult:
    """Output dataclass — assembled from financial inputs + scenario + WACC."""

    ticker: str
    tier: str = "C_yc_resolved"

    # Scenario provenance
    scenario_name: str = ""
    peer_ticker: str = ""
    target_op_margin_used: float = 0.0
    sales_to_capital_ratio_used: float = 0.0
    survival_probability_used: float = 0.0
    survival_probability_source: str = ""     # "derived" | "user_override"
    cash_runway_years: float = 0.0

    # WACC
    wacc: float = 0.0
    wacc_result: WACCResult | None = None
    growth_rate_terminal: float = 0.0

    # Projections (year 1..N)
    revenue_projections: list[float] = field(default_factory=list)
    growth_rate_projections: list[float] = field(default_factory=list)
    op_margin_projections: list[float] = field(default_factory=list)
    ebit_projections: list[float] = field(default_factory=list)
    nopat_projections: list[float] = field(default_factory=list)
    reinvestment_projections: list[float] = field(default_factory=list)
    fcff_projections: list[float] = field(default_factory=list)

    # Aggregates
    pv_high_growth_fcff_total: float = 0.0
    terminal_value: float = 0.0
    terminal_value_pv: float = 0.0
    terminal_value_pct_of_total: float = 0.0
    enterprise_value_pre_survival: float = 0.0
    enterprise_value_post_survival: float = 0.0   # × P(survival)
    net_debt: float = 0.0
    equity_value: float = 0.0
    intrinsic_value_per_share: float = 0.0
    current_price: float = 0.0
    margin_of_safety_pct: float = 0.0

    # Sensitivity
    sensitivity_matrix: list[list[float]] = field(default_factory=list)
    iv_per_share_p25: float = 0.0
    iv_per_share_median: float = 0.0
    iv_per_share_p75: float = 0.0

    # Provenance
    data_gaps: list[str] = field(default_factory=list)
    inversion_questions: list[str] = field(default_factory=list)


# ── Reference data loader ────────────────────────────────────────────────


def _load_peer_benchmarks() -> dict:
    """Load peer benchmark JSON."""
    path = REFERENCE_DIR / PEER_BENCHMARK_FILE
    if not path.exists():
        raise FileNotFoundError(f"Young-company peer benchmarks missing: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_peer_benchmark(industry: str | None) -> dict:
    """Industry → mature peer benchmark.

    Returns dict with keys: mature_peer_ticker, mature_peer_name,
    target_op_margin, sales_to_capital_ratio, notes.
    Falls back to "_fallback_default" with a data-gap flag.
    """
    benchmarks = _load_peer_benchmarks()["industries"]
    if industry and industry in benchmarks:
        b = benchmarks[industry].copy()
        b["_used_industry"] = industry
        b["_is_fallback"] = False
        return b
    b = benchmarks["_fallback_default"].copy()
    b["_used_industry"] = "_fallback_default"
    b["_is_fallback"] = True
    return b


# ── Survival probability derivation ──────────────────────────────────────


def derive_survival_prob(
    cash_position: float,
    annual_op_cash_burn: float,
    burn_trajectory_pct: float | None = None,
) -> tuple[float, str, float]:
    """Damodaran-style survival probability from cash runway + burn trajectory.

    Args:
        cash_position: cash + short-term investments (USD)
        annual_op_cash_burn: ABSOLUTE annual operating cash outflow.
                              For a company with OCF = -$200M, pass 200M.
                              For a company with positive OCF, pass 0 (well-funded).
        burn_trajectory_pct: (current_burn - prior_burn) / prior_burn.
                              Negative = burn decelerating (good).
                              None = unknown.

    Returns:
        (probability, source_label, runway_years)
    """
    if annual_op_cash_burn <= 0:
        # Company is cash-flow positive — no burn. Survival ≈ certain.
        return 0.95, "derived_cf_positive", float("inf")

    runway_years = cash_position / annual_op_cash_burn

    # Default trajectory: assume stable burn (improving = negative trajectory)
    improving = burn_trajectory_pct is not None and burn_trajectory_pct < 0

    if runway_years > 4 and improving:
        return 0.90, "derived_long_runway_improving", runway_years
    elif runway_years > 4:
        return 0.85, "derived_long_runway", runway_years
    elif runway_years > 2 and improving:
        return 0.80, "derived_moderate_runway_improving", runway_years
    elif runway_years > 2:
        return 0.70, "derived_moderate_runway", runway_years
    elif runway_years > 1:
        return 0.55, "derived_tight_runway", runway_years
    else:
        return 0.35, "derived_near_distress", runway_years


# ── Trajectory helpers ───────────────────────────────────────────────────


def _interpolate_margin(
    current: float,
    target: float,
    year: int,
    years_to_target: int,
    decay: Literal["linear", "scurve"] = "linear",
) -> float:
    """Margin trajectory from current → target over `years_to_target`."""
    if year >= years_to_target:
        return target
    if year <= 0:
        return current
    frac = year / years_to_target
    if decay == "scurve":
        # Logistic S-curve: slow start, fast middle, slow end
        # Maps frac in [0,1] through sigmoid centered at 0.5
        sig = 1.0 / (1.0 + math.exp(-10 * (frac - 0.5)))
        frac = sig
    return current + (target - current) * frac


def _interpolate_growth(
    high_growth: float,
    terminal_growth: float,
    year: int,
    high_growth_years: int,
    decay: Literal["linear", "scurve"] = "linear",
) -> float:
    """Revenue-growth trajectory from high → terminal over high_growth_years.

    For young companies, growth rate decays over time as revenue scale
    increases (mathematically inevitable). Decay shape is user-selectable.
    """
    if year >= high_growth_years:
        return terminal_growth
    if year <= 1:
        return high_growth
    frac = (year - 1) / (high_growth_years - 1)
    if decay == "scurve":
        sig = 1.0 / (1.0 + math.exp(-10 * (frac - 0.5)))
        frac = sig
    return high_growth + (terminal_growth - high_growth) * frac


# ── Main public function ─────────────────────────────────────────────────


def compute_young_iv(
    financial: FinancialInputs,
    scenario: ScenarioInputs,
) -> YoungCompanyResult:
    """End-to-end Damodaran young-company target-margin DCF.

    Pulls peer benchmark for target_op_margin and sales_to_capital_ratio
    when not specified in scenario. Derives survival probability from
    runway + burn unless overridden. Builds revenue + margin trajectories,
    projects FCFF, discounts at WACC, multiplies by P(survival), returns
    per-share equity IV with sensitivity matrix.
    """
    data_gaps: list[str] = []

    # ── 1. Load peer benchmark ────────────────────────────────────────────
    bench = load_peer_benchmark(financial.industry)
    peer_ticker = scenario.peer_ticker_override or bench["mature_peer_ticker"]
    target_margin = scenario.target_op_margin or bench["target_op_margin"]
    s2c = scenario.sales_to_capital_ratio or bench["sales_to_capital_ratio"]

    if bench.get("_is_fallback"):
        data_gaps.append(
            f"{financial.ticker}: industry '{financial.industry}' not in peer benchmark; "
            f"using fallback (target_op_margin={target_margin:.0%}, s2c={s2c}). "
            f"Override peer_ticker_override in scenario for ticker-specific assumption."
        )

    # Sanity-clamp scenario inputs
    if not (_MIN_TARGET_MARGIN <= target_margin <= _MAX_TARGET_MARGIN):
        data_gaps.append(
            f"target_op_margin {target_margin:.0%} outside sanity bounds; verify input"
        )
    if not (_MIN_SALES_TO_CAPITAL <= s2c <= _MAX_SALES_TO_CAPITAL):
        data_gaps.append(
            f"sales_to_capital_ratio {s2c} outside sanity bounds; verify input"
        )

    # ── 2. Cost of capital (reuse Phase A) ────────────────────────────────
    wacc_res = compute_wacc(
        ticker=financial.ticker,
        sector=financial.sector,
        country=financial.country,
        market_cap=financial.market_cap,
        total_debt=financial.total_debt,
        cash_and_equivalents=financial.cash_and_equivalents,
        short_term_investments=financial.short_term_investments,
        interest_expense=financial.interest_expense,
    )
    data_gaps.extend(wacc_res.data_gaps)

    # Terminal growth — default = risk-free rate (hard cap)
    g_terminal = scenario.growth_rate_terminal
    if g_terminal is None:
        g_terminal = wacc_res.risk_free_rate

    # ── 3. Survival probability ───────────────────────────────────────────
    if scenario.survival_probability is not None:
        p_survival = scenario.survival_probability
        survival_source = "user_override"
        cash_pool = (financial.cash_and_equivalents or 0.0) + (financial.short_term_investments or 0.0)
        runway = cash_pool / abs(financial.operating_cash_flow) if financial.operating_cash_flow < 0 else float("inf")
    else:
        # Derive from runway + burn trajectory
        cash_pool = (financial.cash_and_equivalents or 0.0) + (financial.short_term_investments or 0.0)
        burn = abs(financial.operating_cash_flow) if financial.operating_cash_flow < 0 else 0.0
        trajectory = None
        if financial.prior_operating_cash_flow is not None and financial.prior_operating_cash_flow < 0:
            prior_burn = abs(financial.prior_operating_cash_flow)
            if prior_burn > 0:
                trajectory = (burn - prior_burn) / prior_burn
        p_survival, survival_source, runway = derive_survival_prob(cash_pool, burn, trajectory)

    p_survival = max(_MIN_SURVIVAL, min(_MAX_SURVIVAL, p_survival))

    # ── 4. Build revenue + margin trajectories ────────────────────────────
    high_growth = (scenario.revenue_year_N / financial.revenue) ** (1.0 / scenario.high_growth_years) - 1.0
    current_op_margin = (financial.operating_income / financial.revenue) if financial.revenue else 0.0

    revenue_proj: list[float] = []
    growth_proj: list[float] = []
    margin_proj: list[float] = []
    ebit_proj: list[float] = []
    nopat_proj: list[float] = []
    reinvest_proj: list[float] = []
    fcff_proj: list[float] = []
    discount_factors: list[float] = []

    rev_t = financial.revenue
    for year in range(1, scenario.high_growth_years + 1):
        g_t = _interpolate_growth(high_growth, g_terminal, year, scenario.high_growth_years, scenario.growth_decay)
        rev_next = rev_t * (1.0 + g_t)
        margin_t = _interpolate_margin(current_op_margin, target_margin, year, scenario.years_to_target_margin, scenario.growth_decay)
        ebit_t = rev_next * margin_t
        # Tax only when EBIT > 0
        if ebit_t > 0:
            nopat_t = ebit_t * (1.0 - wacc_res.marginal_tax_rate)
        else:
            nopat_t = ebit_t       # losses carry forward — no tax shield realized here
        reinvest_t = (rev_next - rev_t) / s2c if s2c > 0 else 0.0
        fcff_t = nopat_t - reinvest_t
        df = 1.0 / ((1.0 + wacc_res.wacc) ** year)

        revenue_proj.append(rev_next)
        growth_proj.append(g_t)
        margin_proj.append(margin_t)
        ebit_proj.append(ebit_t)
        nopat_proj.append(nopat_t)
        reinvest_proj.append(reinvest_t)
        fcff_proj.append(fcff_t)
        discount_factors.append(df)
        rev_t = rev_next

    pv_fcff_total = sum(fcff * df for fcff, df in zip(fcff_proj, discount_factors))

    # ── 5. Terminal value ─────────────────────────────────────────────────
    # Use last-year NOPAT × (1 + g_terminal) × (1 − reinvest_rate_terminal)
    # Reinvest_rate at terminal = g_terminal / WACC (no excess returns assumption)
    nopat_last = nopat_proj[-1]
    nopat_terminal = nopat_last * (1.0 + g_terminal)
    reinvest_rate_terminal = g_terminal / wacc_res.wacc if wacc_res.wacc > 0 else 0.0
    fcff_terminal = nopat_terminal * (1.0 - reinvest_rate_terminal)
    if wacc_res.wacc > g_terminal:
        tv = fcff_terminal / (wacc_res.wacc - g_terminal)
    else:
        tv = 0.0
        data_gaps.append(f"{financial.ticker}: WACC ≤ g_terminal; terminal value set to 0")
    tv_pv = tv * discount_factors[-1]

    # ── 6. Enterprise → equity → per-share ────────────────────────────────
    ev_pre = pv_fcff_total + tv_pv
    ev_post = ev_pre * p_survival
    net_debt = (financial.total_debt or 0.0) - (financial.cash_and_equivalents or 0.0) - (financial.short_term_investments or 0.0)
    equity_value = ev_post - net_debt
    iv_per_share = equity_value / financial.shares_outstanding if financial.shares_outstanding > 0 else 0.0
    mos = (iv_per_share - financial.current_price) / iv_per_share if iv_per_share > 0 and financial.current_price > 0 else 0.0

    tv_pct = tv_pv / (pv_fcff_total + tv_pv) if (pv_fcff_total + tv_pv) > 0 else 0.0
    if tv_pct > 0.85:
        data_gaps.append(
            f"{financial.ticker}: terminal value is {tv_pct:.0%} of total IV — "
            f"valuation is overwhelmingly about year-N+ assumption. Verify target "
            f"margin + terminal growth are defensible."
        )

    # ── 7. Sensitivity over target_margin × revenue_year_N ────────────────
    # Grid: ±200bps margin × ±25% revenue_year_N
    sens_matrix: list[list[float]] = []
    margin_axis = [target_margin + d for d in (-0.04, -0.02, 0, 0.02, 0.04)]
    rev_axis = [scenario.revenue_year_N * m for m in (0.75, 0.875, 1.0, 1.125, 1.25)]

    for m in margin_axis:
        row = []
        for rv in rev_axis:
            row.append(_quick_iv(financial, scenario, wacc_res, p_survival, g_terminal,
                                   target_margin=m, revenue_year_N=rv, s2c=s2c))
        sens_matrix.append(row)

    flat = sorted([v for row in sens_matrix for v in row])
    p25 = flat[len(flat) // 4]
    median = flat[len(flat) // 2]
    p75 = flat[3 * len(flat) // 4]

    # ── 8. Inversion questions ────────────────────────────────────────────
    inversion = [
        f"What revenue trajectory and target operating margin would have to be "
        f"true for IV to be 30% BELOW the base case of ${iv_per_share:.2f}? "
        f"(Check sensitivity matrix P25 corner = ${p25:.2f})",
        f"Survival probability is {p_survival:.0%} ({survival_source}). "
        f"What if it's actually 50% (worst-case dilution scenario)? "
        f"Re-run with survival_probability=0.50 to see the effect.",
        f"Is the chosen mature peer '{peer_ticker}' a fair benchmark? "
        f"What if the long-run margin is closer to the median industry peer "
        f"(say {target_margin*0.6:.0%}) rather than this top-decile assumption?",
    ]

    return YoungCompanyResult(
        ticker=financial.ticker,
        tier="C_yc_resolved",
        scenario_name=scenario.scenario_name,
        peer_ticker=peer_ticker,
        target_op_margin_used=target_margin,
        sales_to_capital_ratio_used=s2c,
        survival_probability_used=p_survival,
        survival_probability_source=survival_source,
        cash_runway_years=runway,
        wacc=wacc_res.wacc,
        wacc_result=wacc_res,
        growth_rate_terminal=g_terminal,
        revenue_projections=revenue_proj,
        growth_rate_projections=growth_proj,
        op_margin_projections=margin_proj,
        ebit_projections=ebit_proj,
        nopat_projections=nopat_proj,
        reinvestment_projections=reinvest_proj,
        fcff_projections=fcff_proj,
        pv_high_growth_fcff_total=pv_fcff_total,
        terminal_value=tv,
        terminal_value_pv=tv_pv,
        terminal_value_pct_of_total=tv_pct,
        enterprise_value_pre_survival=ev_pre,
        enterprise_value_post_survival=ev_post,
        net_debt=net_debt,
        equity_value=equity_value,
        intrinsic_value_per_share=iv_per_share,
        current_price=financial.current_price,
        margin_of_safety_pct=mos,
        sensitivity_matrix=sens_matrix,
        iv_per_share_p25=p25,
        iv_per_share_median=median,
        iv_per_share_p75=p75,
        data_gaps=data_gaps,
        inversion_questions=inversion,
    )


def _quick_iv(
    financial: FinancialInputs,
    scenario: ScenarioInputs,
    wacc_res: WACCResult,
    p_survival: float,
    g_terminal: float,
    *,
    target_margin: float,
    revenue_year_N: float,
    s2c: float,
) -> float:
    """Quick IV computation for sensitivity grid — same math as main calc
    but no logging / data_gaps tracking. Returns IV per share."""
    current_op_margin = (financial.operating_income / financial.revenue) if financial.revenue else 0.0
    high_growth = (revenue_year_N / financial.revenue) ** (1.0 / scenario.high_growth_years) - 1.0

    rev_t = financial.revenue
    pv = 0.0
    nopat_last = 0.0
    for year in range(1, scenario.high_growth_years + 1):
        g_t = _interpolate_growth(high_growth, g_terminal, year, scenario.high_growth_years, scenario.growth_decay)
        rev_next = rev_t * (1.0 + g_t)
        margin_t = _interpolate_margin(current_op_margin, target_margin, year, scenario.years_to_target_margin, scenario.growth_decay)
        ebit_t = rev_next * margin_t
        nopat_t = ebit_t * (1.0 - wacc_res.marginal_tax_rate) if ebit_t > 0 else ebit_t
        reinvest_t = (rev_next - rev_t) / s2c if s2c > 0 else 0.0
        fcff_t = nopat_t - reinvest_t
        df = 1.0 / ((1.0 + wacc_res.wacc) ** year)
        pv += fcff_t * df
        nopat_last = nopat_t
        rev_t = rev_next

    reinvest_terminal_rate = g_terminal / wacc_res.wacc if wacc_res.wacc > 0 else 0.0
    fcff_terminal = nopat_last * (1.0 + g_terminal) * (1.0 - reinvest_terminal_rate)
    if wacc_res.wacc > g_terminal:
        tv = fcff_terminal / (wacc_res.wacc - g_terminal)
    else:
        tv = 0.0
    tv_pv = tv * (1.0 / ((1.0 + wacc_res.wacc) ** scenario.high_growth_years))

    ev = (pv + tv_pv) * p_survival
    net_debt = (financial.total_debt or 0.0) - (financial.cash_and_equivalents or 0.0) - (financial.short_term_investments or 0.0)
    equity_value = ev - net_debt
    return equity_value / financial.shares_outstanding if financial.shares_outstanding > 0 else 0.0
