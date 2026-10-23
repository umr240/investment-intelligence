"""DB → IntrinsicValueInputs adapter (ADR-027 Phase D).

Bridges the existing Company + Financial schema to the pure-math
intrinsic_value calc. Caller passes a ticker; loader does:

  1. Resolve Company by ticker (raises CompanyNotFoundError if absent)
  2. Load latest annual Financial row (for stock items + most recent flows)
  3. Load prior annual Financial row (for ΔWC computation)
  4. Load up to 5y of R&D history from annuals (newest-last, for Tier B amortization)
  5. Resolve current price from Polygon snapshot OR latest PriceHistory row
  6. Build IntrinsicValueInputs and return

Per ADR-027 §Resolutions, this loader:
  - Uses **latest annual** for the base year (audited, most rigorous).
    LTM-based version is a future enhancement (ADR-026 three-tier model).
  - Falls back gracefully when any input is None (the calc downstream
    surfaces data_gaps).
  - Does NOT compute the IV — pure data assembly.

Public API:
    load_inputs(ticker, as_of_date=...) -> IntrinsicValueInputs | None
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.db import get_session
from data.models.schema import Company, Financial, PriceHistory
from valuation.damodaran.intrinsic import IntrinsicValueInputs, IVResult


class CompanyNotFoundError(Exception):
    """Raised when ticker is absent from companies table."""


class InsufficientDataError(Exception):
    """Raised when ticker has no annual Financial rows at all — IV not loadable."""


# ── Helpers ───────────────────────────────────────────────────────────────


def _resolve_current_price(session: Session, company: Company, latest_annual: Financial | None) -> float:
    """Best-effort current price.

    Priority:
      1. Company.latest_close (Polygon snapshot, refreshed daily)
      2. Most-recent PriceHistory.close (any date)
      3. Derived: market_cap_usd / Financial.shares_outstanding (filing-date
         shares — slightly stale for buybacks/issuance since the annual,
         but typically within 1-3% for mature companies)
      4. Falls back to 0.0 — caller's data_gaps[] picks up via "current_price ≤ 0" check

    The #3 fallback is critical: Polygon's polygon_current_price warehouse
    task only runs on watchlist/portfolio tickers (5/min free tier), so
    most screened candidates have NULL latest_close. Without the
    derived-price fallback, margin_of_safety_pct can only be computed for
    the tiny subset Polygon has covered.
    """
    if company.latest_close and company.latest_close > 0:
        return float(company.latest_close)
    row = session.execute(
        select(PriceHistory.close)
        .where(PriceHistory.company_id == company.id)
        .order_by(PriceHistory.date.desc())
        .limit(1)
    ).first()
    if row and row[0] is not None:
        return float(row[0])
    # Derive from market_cap / shares_outstanding (filing date)
    # Apply same XBRL thousands-units normalization as _resolve_shares_outstanding
    if (
        company.market_cap_usd
        and company.market_cap_usd > 0
        and latest_annual
        and latest_annual.shares_outstanding
        and latest_annual.shares_outstanding > 0
    ):
        shares = float(latest_annual.shares_outstanding)
        if shares < 1_000_000 and company.market_cap_usd > 100_000_000:
            shares *= 1000.0
        return float(company.market_cap_usd / shares)
    return 0.0


def _resolve_shares_outstanding(company: Company, latest_annual: Financial) -> float:
    """Derive shares outstanding.

    Priority:
      1. market_cap_usd / latest_close — most authoritative when both present
      2. Financial.shares_outstanding — XBRL filing value, with unit normalization

    XBRL filing-unit gotcha: some filers (TEM, etc.) report shares with
    `decimals=-3` (thousands). The DB stores the literal number, so a
    company with 174M actual shares is stored as 174264 not 174_264_000.
    Detection: if shares < 1M AND market_cap > $100M, multiply by 1000.

    Verified via: market_cap_usd / shares = implied_price; sane range
    typically $5-$5000. If implied_price > $5000 with shares < 1M, we're
    in thousands-units territory. Same fix for Financial.shares_outstanding
    being in thousands.
    """
    if (
        company.market_cap_usd
        and company.market_cap_usd > 0
        and company.latest_close
        and company.latest_close > 0
    ):
        return float(company.market_cap_usd / company.latest_close)
    if latest_annual and latest_annual.shares_outstanding:
        raw = float(latest_annual.shares_outstanding)
        # XBRL thousands-units detection
        if (
            raw > 0
            and raw < 1_000_000
            and company.market_cap_usd
            and company.market_cap_usd > 100_000_000
        ):
            return raw * 1000.0
        return raw
    return 0.0


def _rd_history_newest_last(annuals: list[Financial]) -> list[float | None]:
    """Convert annuals (newest-first per reader convention) to R&D history
    in newest-LAST order, since amortization uses sliding window with newest
    at the end."""
    rd = [a.rd_expense for a in reversed(annuals)]
    return rd


def _compute_normalized_reinvestment_rate(
    annuals: list[Financial],
    marginal_tax_rate: float,
    rd_capitalization_for_tier_b: bool = True,
) -> tuple[float | None, str]:
    """Phase C — multi-year averaged reinvestment rate.

    Damodaran's textbook prescription for lumpy reinvestment (M&A-heavy,
    capacity build-outs, working-capital swings): average capex, D&A, and
    ΔWC over 3-5 years, divide by average NOPAT in the same window.

    Returns (rate, notes_string). Returns (None, reason) when window is too
    short or NOPAT sum non-positive — caller falls back to single-period
    compute_reinvestment().

    Args:
        annuals: Newest-first list of Financial rows (loader provides up to 6).
        marginal_tax_rate: For computing NOPAT = EBIT × (1 − t) per period.
        rd_capitalization_for_tier_b: When True and a year is GAAP-loss-but-
            R&D-rescued (EBIT < 0 but EBIT + R&D > 0), use R&D-adjusted EBIT
            for that period's NOPAT. Otherwise that period's NOPAT is 0
            (won't contribute to the average meaningfully).
    """
    if len(annuals) < 3:
        return None, f"only {len(annuals)} annual rows available — need ≥3 for averaging"

    # Use most-recent 3-5 years (skip the 6th which is only for prior-WC)
    window = annuals[:min(5, len(annuals) - 1)]

    capex_sum = 0.0
    da_sum = 0.0
    delta_wc_sum = 0.0
    nopat_sum = 0.0
    valid_periods = 0

    for i, fin in enumerate(window):
        if fin.operating_income is None:
            continue
        ebit = fin.operating_income
        # Optional R&D rescue per ADR-027 Tier B
        if rd_capitalization_for_tier_b and ebit <= 0 and fin.rd_expense and fin.rd_expense > 0:
            ebit_economic = ebit + fin.rd_expense
        else:
            ebit_economic = ebit
        if ebit_economic <= 0:
            continue   # this period contributes nothing usable

        nopat_period = ebit_economic * (1.0 - marginal_tax_rate)
        nopat_sum += nopat_period

        capex_sum += fin.capex or 0.0
        da_sum += fin.depreciation_amortization or 0.0

        # ΔWC for this period — needs the prior-period WC. Annuals are
        # newest-first, so the "prior" for window[i] is window[i+1]
        # (which exists for i < len(annuals) - 1).
        if i + 1 < len(annuals):
            wc_now = (
                (fin.current_assets or 0.0) - (fin.current_liabilities or 0.0)
                if fin.current_assets is not None and fin.current_liabilities is not None
                else None
            )
            wc_prior = (
                (annuals[i + 1].current_assets or 0.0)
                - (annuals[i + 1].current_liabilities or 0.0)
                if annuals[i + 1].current_assets is not None
                and annuals[i + 1].current_liabilities is not None
                else None
            )
            if wc_now is not None and wc_prior is not None:
                delta_wc_sum += wc_now - wc_prior

        valid_periods += 1

    if valid_periods < 2:
        return None, f"only {valid_periods} period(s) with positive NOPAT — need ≥2 for averaging"

    if nopat_sum <= 0:
        return None, f"summed NOPAT across {valid_periods} periods is non-positive"

    reinvestment_sum = (capex_sum - da_sum) + delta_wc_sum
    rate = reinvestment_sum / nopat_sum

    note = (
        f"reinvestment rate normalized over {valid_periods} years: "
        f"Σ(capex − D&A + ΔWC) / Σ NOPAT = "
        f"${reinvestment_sum/1e6:,.0f}M / ${nopat_sum/1e6:,.0f}M = {rate:.1%}"
    )
    return rate, note


# ── Main public function ─────────────────────────────────────────────────


def load_inputs(
    ticker: str,
    as_of_date: str | None = None,
    high_growth_years: int = 8,
    growth_rate_terminal: float | None = None,
    smooth_reinvestment: bool = True,
    marginal_tax_rate_for_smoothing: float = 0.25,
    young_company_scenario: Any | None = None,
) -> IntrinsicValueInputs:
    """Pull a ticker's data from the DB and construct IntrinsicValueInputs.

    Args:
        ticker: Company ticker (case-insensitive — uppercased internally).
        as_of_date: ISO date string (YYYY-MM-DD); defaults to today.
        high_growth_years: Override the default 8yr high-growth phase.
        growth_rate_terminal: Override the default (= risk-free rate cap).

    Returns:
        IntrinsicValueInputs ready for `compute_intrinsic_value(...)`.

    Raises:
        CompanyNotFoundError: ticker absent from companies table.
        InsufficientDataError: ticker has no annual Financial rows.

    Notes:
        - Uses latest annual Financial as the base year.
        - Loads up to 5 prior annuals for R&D history (Tier B amortization).
        - Prior-period working capital comes from the SECOND-most-recent annual.
    """
    ticker = ticker.upper()
    as_of = as_of_date or date.today().isoformat()

    # Snapshot ALL needed fields inside the session block — avoids
    # DetachedInstanceError when ORM attrs are accessed after session close.
    with get_session() as session:
        company = session.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if company is None:
            raise CompanyNotFoundError(f"Company {ticker} not in DB")

        annuals = session.execute(
            select(Financial)
            .where(Financial.company_id == company.id, Financial.period == "annual")
            .order_by(Financial.fiscal_year.desc())
            .limit(10)  # cyclical detection needs ≥5; pull 10 to span a full cycle
        ).scalars().all()

        if not annuals:
            raise InsufficientDataError(
                f"{ticker} has no annual Financial rows — refresh fundamentals first"
            )

        latest = annuals[0]
        prior = annuals[1] if len(annuals) >= 2 else None

        current_price = _resolve_current_price(session, company, latest)
        shares_out = _resolve_shares_outstanding(company, latest)

        # Snapshot R&D history (newest-last) — must read attrs inside session
        rd_hist: list[float | None] = [a.rd_expense for a in reversed(annuals[:5])]

        # ADR-030 — ROIC history (newest-last). Maturity classifier needs
        # ≥3 years to evaluate the 3yr floor + CoV stability test. We pull
        # up to 5 annuals; classify_maturity downgrades to history_pass=False
        # when <min_history_years observations are present, which correctly
        # surfaces "we can't tell" companies as young rather than mature.
        roic_hist: list[float | None] = [a.roic for a in reversed(annuals[:5])]

        # Cyclical detection history (newest-last). Pull up to 9 prior annuals
        # so we span a full cycle for cyclical_mature classification.
        rev_hist: list[float | None] = [a.revenue for a in reversed(annuals)]
        margin_hist: list[float | None] = [
            (a.operating_income / a.revenue) if a.revenue and a.operating_income is not None else None
            for a in reversed(annuals)
        ]

        # ADR-043 §2.3: `country` was hardcoded to "United States" for every
        # ticker, which is what made a Swedish filer receive a US tax rate and
        # CRP=0.0. It is no longer a future enhancement — ADR-041's
        # jurisdiction registry knows every ticker's country, so pass None and
        # let compute_wacc resolve it there (one resolution site, not two).
        sector = company.sector
        country = None
        # ADR-043 §2.2: the currency the filer REPORTS in selects the risk-free
        # rate. Set by the ESEF/yfinance adapters; None for US filers → USD.
        reporting_currency = company.currency
        market_cap = float(company.market_cap_usd or 0.0)

        # Snapshot latest-period Financial fields
        latest_data = {
            "operating_income": latest.operating_income,
            "rd_expense": latest.rd_expense,
            "capex": latest.capex,
            "depreciation_amortization": latest.depreciation_amortization,
            "interest_expense": latest.interest_expense,
            "total_equity": float(latest.total_equity or 0.0),
            "total_debt": float(latest.total_debt or 0.0),
            "cash_and_equivalents": latest.cash_and_equivalents,
            "short_term_investments": latest.short_term_investments,
            "current_assets": latest.current_assets,
            "current_liabilities": latest.current_liabilities,
            # ADR-028 fields
            "revenue": latest.revenue,
            "operating_cash_flow": latest.operating_cash_flow,
        }

        # Snapshot prior-period working capital for ΔWC + OCF for burn trajectory
        prior_data = {
            "current_assets": prior.current_assets if prior else None,
            "current_liabilities": prior.current_liabilities if prior else None,
            "operating_cash_flow": prior.operating_cash_flow if prior else None,
        }

        # ADR-028 — industry snapshot for peer-benchmark lookup
        industry = company.industry

        # Phase C — multi-year reinvestment smoothing inside the session
        reinv_override: float | None = None
        if smooth_reinvestment:
            rate, _note = _compute_normalized_reinvestment_rate(
                list(annuals), marginal_tax_rate_for_smoothing
            )
            if rate is not None:
                reinv_override = rate

    return IntrinsicValueInputs(
        ticker=ticker,
        sector=sector,
        country=country,
        market_cap=market_cap,
        current_price=current_price,
        shares_outstanding=shares_out,
        operating_income=latest_data["operating_income"],
        rd_expense_current=latest_data["rd_expense"],
        rd_history=rd_hist,
        roic_history=roic_hist,
        revenue_history=rev_hist,
        op_margin_history=margin_hist,
        capex=latest_data["capex"],
        depreciation_amortization=latest_data["depreciation_amortization"],
        interest_expense=latest_data["interest_expense"],
        total_equity=latest_data["total_equity"],
        total_debt=latest_data["total_debt"],
        cash_and_equivalents=latest_data["cash_and_equivalents"],
        short_term_investments=latest_data["short_term_investments"],
        current_assets=latest_data["current_assets"],
        current_liabilities=latest_data["current_liabilities"],
        current_assets_prior=prior_data["current_assets"],
        current_liabilities_prior=prior_data["current_liabilities"],
        high_growth_years=high_growth_years,
        growth_rate_terminal=growth_rate_terminal,
        as_of_date=as_of,
        reinvestment_rate_override=reinv_override,
        # ADR-028 fields
        operating_cash_flow=latest_data.get("operating_cash_flow"),
        prior_operating_cash_flow=prior_data.get("operating_cash_flow"),
        industry=industry,
        reporting_currency=reporting_currency,
        revenue=latest_data.get("revenue"),
        young_company_scenario=young_company_scenario,
    )


# ── Warehouse persistence ─────────────────────────────────────────────────


def persist_intrinsic_value(ticker: str, result: IVResult) -> None:
    """Write the IV result to the Company warehouse columns (4 fields).

    Updates:
        Company.intrinsic_value_per_share
        Company.margin_of_safety_pct
        Company.intrinsic_value_tier
        Company.intrinsic_value_fetched_at  (= UTC now)

    Tier C results write NULL for value + MoS but still record the tier
    (`C_insufficient`) so the screener can filter out Tier C tickers
    distinctly from "never computed".
    """
    ticker = ticker.upper()
    with get_session() as session:
        company = session.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if company is None:
            raise CompanyNotFoundError(f"Cannot persist IV for unknown ticker {ticker}")
        company.intrinsic_value_per_share = result.intrinsic_value_per_share
        company.margin_of_safety_pct = result.margin_of_safety_pct
        company.intrinsic_value_tier = result.tier
        company.intrinsic_value_fetched_at = datetime.utcnow()
        session.commit()


def compute_and_persist(
    ticker: str,
    as_of_date: str | None = None,
    high_growth_years: int = 8,
    growth_rate_terminal: float | None = None,
    young_company_scenario: Any | None = None,
    log_run: bool = True,
) -> IVResult:
    """One-shot convenience: load inputs, compute IV (with optional ADR-028
    young-company scenario for Tier C rescue), persist to warehouse, and
    append a JSONL log record per ADR-030 §Instrumentation."""
    from valuation.damodaran.intrinsic import compute_intrinsic_value
    from valuation.damodaran.instrumentation import log_iv_run

    inputs = load_inputs(
        ticker,
        as_of_date=as_of_date,
        high_growth_years=high_growth_years,
        growth_rate_terminal=growth_rate_terminal,
        young_company_scenario=young_company_scenario,
    )
    result = compute_intrinsic_value(inputs)
    persist_intrinsic_value(ticker, result)

    if log_run:
        log_iv_run(
            ticker,
            result,
            extras={
                "high_growth_years": high_growth_years,
                "scenario_supplied": young_company_scenario is not None,
            },
        )
    return result
