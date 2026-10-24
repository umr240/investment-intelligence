"""SQLAlchemy 2.0 ORM — persistence schema for the lab.

All financial data is sourced deterministically (EDGAR XBRL/text, yfinance).
No LLM-derived values are written to any column. The `extraction_confidence`
column on `Financial` records the source quality (1.0 = XBRL/HTML verbatim,
0.6 = regex on filing text, 0.0 = missing — never extracted).
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, Text, UniqueConstraint, func,
)
from sqlalchemy import REAL, TIMESTAMP, Dialect, TypeDecorator, false, text, true
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.schema import Index

from config.verdicts import canonical_verdict


def _state_indexes(table: str, *columns: str, names: tuple[str, ...]) -> list[Index]:
    """Partial indexes over `<field>_state` columns: only attempted rows are indexed."""
    return [
        Index(
            f"idx_{table}_{name}_state",
            column,
            sqlite_where=text(f"{column} IS NOT NULL"),
            postgresql_where=text(f"{column} IS NOT NULL"),
        )
        for column, name in zip(columns, names, strict=True)
    ]


class VerdictLabel(TypeDecorator[str]):
    """Composite verdict column: legacy labels read back as ADR-054 labels."""

    impl = Text
    cache_ok = True

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return canonical_verdict(value)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(Text, nullable=False, unique=True)
    cik = Column(Text, index=True)             # zero-padded 10-digit CIK; key into SEC frames
    exchange = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    sector = Column(Text)
    industry = Column(Text)
    # ADR-043: market_cap_usd means USD. For non-USD filers it previously held
    # the NATIVE figure under a USD name, which silently disarmed every
    # USD-denominated threshold (the $300m liquidity floor most importantly).
    market_cap_usd = Column(Float)
    market_cap_native = Column(Float)      # as reported, in market_cap_currency
    market_cap_currency = Column(Text)     # ISO-4217 of market_cap_native
    currency = Column(Text, default="USD")
    # ADR-039: which FundamentalsSource supplied this row's financials.
    # 'sec_edgar' (Tier-1A, default) | 'sedar_plus' (Tier-1B) | 'yfinance_only'
    # (Tier-3). Drives the dive methodology panel + data_completeness so a
    # yfinance-sourced ticker is never silently treated as SEC-grade.
    data_source_tier = Column(Text, default="sec_edgar", server_default=text("'sec_edgar'"))
    # ADR-041: Legal Entity Identifier — the join key between a ticker and its
    # EU/EEA regulatory filings. Resolved once via GLEIF (country-scoped, must
    # be unambiguous) then cached here, so subsequent ESEF refreshes skip the
    # identity hop. NULL for US/SEC issuers, which join on CIK instead.
    lei = Column(Text)
    ipo_date = Column(Date)
    parent_ticker = Column(Text)               # spinoff tracking (PSA overlay)
    listing_type = Column(Text)                # 'spinoff' | 'demerger' | 'ipo' | 'standard'
    # Fiscal calendar — needed to derive fiscal_year/period from period_end_date
    # without falling back to SEC's filing-year `fy` field (which is the year
    # OF the filing, not the year the period ends — caused INTA's FY2022/FY2023
    # duplicate-label bug). Populated from EDGAR submissions.json `fiscalYearEnd`
    # (e.g. "0630" → 6 for June year-end). Default 12 (December year-end).
    fiscal_year_end_month = Column(Integer, default=12, server_default=text("12"))
    # ── Screener lifecycle (docs/architecture/SCREENER_PIPELINE.md §2) ──────────
    status = Column(
        Text, nullable=False, default="screener_candidate"
    )  # 'screener_candidate' | 'watchlist' | 'dive_history' | 'archived'
    retention_days = Column(Integer, nullable=False, default=30)
    # CEO / management — F6 signals (deterministic: yfinance + DEF 14A HTML / regex)
    ceo_name = Column(Text)
    ceo_equity_pct = Column(Float)           # % of shares outstanding held by CEO
    ceo_total_pay = Column(Float)            # CEO total annual compensation (yfinance)
    is_founder_ceo = Column(Boolean)         # True if CEO is also a company founder
    ceo_tenure_years = Column(Float)         # years serving as CEO
    # ADR-018 three-state columns: 'disclosed_exact' | 'not_disclosed' |
    # 'parser_uncertain' | NULL (not yet attempted). The dive output uses
    # these to distinguish "value missing because no source had it" from
    # "value absent because the company doesn't disclose it" from "we
    # couldn't reliably extract a candidate value".
    ceo_name_state = Column(Text)
    ceo_name_fetched_at = Column(TIMESTAMP)
    ceo_equity_pct_state = Column(Text)
    ceo_equity_pct_fetched_at = Column(TIMESTAMP)
    is_founder_ceo_state = Column(Text)
    is_founder_ceo_fetched_at = Column(TIMESTAMP)
    ipo_date_state = Column(Text)
    ipo_date_fetched_at = Column(TIMESTAMP)
    # Ownership / float — F4 signals (yfinance snapshot)
    shares_float = Column(Float)             # float shares (yfinance floatShares)
    insider_pct_latest = Column(Float)       # most recent insider ownership % (yfinance)
    institution_pct_latest = Column(Float)   # most recent institutional ownership % (yfinance)
    short_pct_float_latest = Column(Float)   # most recent short interest % float (yfinance)
    # Trailing valuation snapshots (yfinance — supplementary cross-check)
    pe_trailing = Column(Float)
    pb_ratio = Column(Float)
    ev_ebitda = Column(Float)
    beta = Column(Float)
    last_screened = Column(DateTime)
    # ── Warehouse columns (Phase 4a / ADR-017) ─────────────────────────────
    # Each filter dimension is a column on this wide table; each column has
    # a paired *_fetched_at for freshness-driven select_pending(). The
    # warehouse view is denormalised; per-period truth lives on Financial.
    market_cap_fetched_at = Column(DateTime)
    sector_fetched_at = Column(DateTime)
    industry_fetched_at = Column(DateTime)
    # Source-precedence audit. Per Tier-1.1 substitution (2026-05-15) the
    # canonical priority inverted: 'sec_sic' is now PRIMARY (verifiable GAAP-
    # consistent classification), 'yfinance' is fallback only. The change
    # was motivated by HIMS misclassification (yfinance "Software" vs SEC
    # SIC "Offices & Clinics of Doctors of Medicine"). Values: 'sec_sic' |
    # 'yfinance' | 'polygon-sic' | NULL.
    sector_source = Column(Text)
    # ── SEC classification fields (Tier-2.4, 2026-05-15) ──────────────────
    # Sourced via edgartools.Company surfaces; populated by
    # data/edgar_fetcher.py:fetch_sec_industry_classification(). Enables
    # SIC-filtered peer comparison through data/sec_frames.py.
    sic_code = Column(Integer)                      # SEC 4-digit SIC (e.g. 8011)
    filer_category = Column(Text)                   # "Large accelerated filer" / etc.
    is_smaller_reporting_company = Column(Boolean)  # SEC SRC threshold flag
    is_financial_institution = Column(Boolean)      # skip for non-bank frameworks
    is_fund = Column(Boolean)                       # exclude from operating-company screener
    # ── Per-field source provenance (Phase 1, 2026-05-16) ─────────────────
    # API_FIELD_AUDIT.md §F.1 — every API/SEC-sourced column has a paired
    # `_source` column recording origin. Values are constants from
    # `config/source_tags.py` (sec_xbrl / sec_dei / sec_def14a / sec_sc13d /
    # sec_form4 / sec_text / edgartools / self_computed / yfinance /
    # polygon / fmp / llm / manual). NULL = pre-migration, treated as 0.80
    # weight (slightly below yfinance) by compute_data_completeness.
    # `sector_source` (above) already covers industry+sector classification.
    market_cap_usd_source = Column(Text)
    ipo_date_source = Column(Text)
    roic_source = Column(Text)
    fcf_margin_source = Column(Text)
    debt_to_equity_source = Column(Text)
    revenue_growth_source = Column(Text)
    pe_trailing_source = Column(Text)
    pb_ratio_source = Column(Text)
    ev_ebitda_source = Column(Text)
    beta_source = Column(Text)
    shares_float_source = Column(Text)
    ceo_total_pay_source = Column(Text)
    insider_pct_latest_source = Column(Text)
    institution_pct_latest_source = Column(Text)
    short_pct_float_latest_source = Column(Text)
    exchange_source = Column(Text)
    currency_source = Column(Text)
    pretax_roic_source = Column(Text)
    pt_adjusted_roic_source = Column(Text)
    # Latest-period rollups (annual or TTM) for sub-second screener queries.
    # roic = NOPAT / (Equity + Debt − Cash). NOPAT = EBIT × (1 − ETR) where
    # ETR is derived from income_tax_expense / pretax_income (statutory 21%
    # fallback). Total Debt includes ASC 842 operating leases. Goodwill
    # retained in IC via Total Equity per Stewart/McKinsey/Mauboussin.
    # See data/pipeline.py:_apply_financial_row + _effective_tax_rate (DEC-31).
    roic = Column(Float)
    roic_fetched_at = Column(DateTime)
    # FundamentalsTask's own freshness: set whether or not a ROIC came out, so
    # banks and filers without annuals are not re-read on every run.
    fundamentals_fetched_at = Column(DateTime)
    pretax_roic = Column(Float)              # EBIT / IC_excl_cash (Phase 5k / DEC-31)
    pretax_roic_fetched_at = Column(DateTime)
    debt_to_equity = Column(Float)
    debt_to_equity_fetched_at = Column(DateTime)
    fcf_margin = Column(Float)
    fcf_margin_fetched_at = Column(DateTime)
    revenue_growth = Column(Float)
    revenue_growth_fetched_at = Column(DateTime)
    # Peters-Taylor adjusted ROIC (Phase 5i / ADR-021). Computed by
    # FundamentalsTask rollup using the same KC + OC perpetual-inventory
    # formula as overlays/ica.py — academically defensible economic
    # adjustment, NOT management non-GAAP add-back.
    pt_adjusted_roic = Column(Float)
    pt_adjusted_roic_fetched_at = Column(DateTime)
    # Composite score + data completeness (CompositeScoreTask output)
    composite_score = Column(Float)
    composite_score_fetched_at = Column(DateTime)
    data_completeness = Column(Float)        # 0.0–1.0; fraction of warehouse columns populated
    # Damodaran intrinsic value (Phase 5T / ADR-027). Computed by
    # screener/tasks/intrinsic_value.py using valuation/damodaran/.
    # NULL when Tier C (loss-maker after R&D rescue) or insufficient inputs.
    # tier values: 'A_gaap' | 'B_pt_rescued' | 'C_insufficient'
    intrinsic_value_per_share = Column(Float)
    margin_of_safety_pct = Column(Float)
    intrinsic_value_tier = Column(Text)
    intrinsic_value_fetched_at = Column(DateTime)
    # Framework score rollup (FrameworkScoreTask output, Phase 4d).
    # Mode-resolved 0–10 composite + verdict; per-framework breakdown lives
    # on the FrameworkScore table (full history is preserved there).
    framework_composite_score = Column(Float)
    framework_verdict = Column(VerdictLabel)
    framework_scored_at = Column(DateTime)
    framework_mode_used = Column(Text)       # 'A' | 'B' | 'C' resolved at score time
    framework_unfeasible_count = Column(Integer)   # how many of F1..F7 couldn't run
    # ── Polygon plugin rollups (Phase 5a / ADR-019) ────────────────────────
    # Current-price snapshot from PolygonCurrentPriceTask (/v2/aggs/prev).
    latest_close = Column(Float)
    latest_close_at = Column(DateTime)
    weekly_prices_fetched_at = Column(DateTime)  # PolygonWeeklyPriceTask's own freshness
    # Technical indicators from PolygonRSI / SMA / MACD tasks. Latest values
    # only — historical series stays in PriceHistory; tasks recompute the
    # latest snapshot on each refresh.
    latest_rsi_14 = Column(Float)
    latest_rsi_14_fetched_at = Column(DateTime)
    latest_sma_50 = Column(Float)
    latest_sma_50_fetched_at = Column(DateTime)
    latest_sma_200 = Column(Float)
    latest_sma_200_fetched_at = Column(DateTime)
    latest_macd_line = Column(Float)
    latest_macd_signal = Column(Float)
    latest_macd_histogram = Column(Float)
    latest_macd_fetched_at = Column(DateTime)
    # ── BEW overlay rollup (warehouse-level Bessembinder Extreme Winners) ─
    # BEWOverlayTask writes these by running overlays/bew.py:run_bew()
    # against persisted Financial + PriceHistory + market_cap + sector.
    # Decouples winner-screen pre-filter from per-ticker dive cost.
    bew_verdict = Column(Text)               # 'extreme_winner_candidate' | 'moderate_winner_candidate' | 'no_signal'
    bew_score = Column(Integer)              # 0..6 (n_checks passed)
    bew_n_checks = Column(Integer)           # n_checks_evaluable (denominator)
    bew_scored_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_companies_status_score", "status", "composite_score"),
        Index("idx_companies_framework_score", "status", "framework_composite_score"),
        Index("idx_companies_pt_adjusted_roic", "status", "pt_adjusted_roic"),
        *_state_indexes(
            "companies",
            "ceo_name_state",
            "ceo_equity_pct_state",
            "is_founder_ceo_state",
            "ipo_date_state",
            names=("ceo_name", "ceo_equity", "founder", "ipo"),
        ),
    )

    financials = relationship("Financial", back_populates="company", cascade="all, delete-orphan")
    price_history = relationship("PriceHistory", back_populates="company", cascade="all, delete-orphan")
    insider_transactions = relationship("InsiderTransactionRecord", back_populates="company", cascade="all, delete-orphan")
    analyst_coverage = relationship("AnalystCoverageRecord", back_populates="company", cascade="all, delete-orphan")
    earnings_history = relationship("EarningsHistory", back_populates="company", cascade="all, delete-orphan")
    short_interest = relationship("ShortInterestRecord", back_populates="company", cascade="all, delete-orphan")
    institutional_holders = relationship("InstitutionalHolderRecord", back_populates="company", cascade="all, delete-orphan")
    framework_scores = relationship("FrameworkScore", back_populates="company", cascade="all, delete-orphan")
    watchlist = relationship("WatchlistEntry", back_populates="company")
    # Lazy by default; listings that show a status per row use selectinload.
    exclusion_verdicts = relationship(
        "ExclusionVerdict", back_populates="company", cascade="all, delete-orphan"
    )


class ExclusionVerdict(Base):
    """One exclusion policy's stored verdict on one company (screener/policies/verdicts.py)."""

    __tablename__ = "exclusion_verdicts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    policy = Column(Text, nullable=False)
    status = Column(Text, nullable=False)  # vocabulary is the policy's own
    reason = Column(Text)
    source = Column(Text)
    classified_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "policy", name="uq_exclusion_verdict_company_policy"),
        Index("ix_exclusion_verdicts_policy_status", "policy", "status"),
    )

    company = relationship("Company", back_populates="exclusion_verdicts")


class Financial(Base):
    __tablename__ = "financials"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    period = Column(Text, nullable=False)       # 'annual' | 'Q1'..'Q4'
    # Canonical calendar time anchor (docs/architecture/SCREENER_PIPELINE.md §3).
    # `period_end_date` is the AUTHORITATIVE time anchor for cross-company
    # decile ranking — always groupBy(year(period_end_date), quarter(...)).
    # `fiscal_year`/`period` remain for per-company / report-as-filed analysis.
    # TTM is NEVER persisted; computed on demand by reader.ttm_at(date).
    period_end_date = Column(Date)
    period_start_date = Column(Date)
    filed_date = Column(Date)
    # Separated time concepts (TradingView/Finviz pattern): the catalyst date
    # the market reacts to (`event_date`/`event_time`) is distinct from the
    # accounting period (`period_*`) and the SEC filing date (`filed_date`).
    # `event_date` mirrors SEC's reportDate for 10-K/10-Q rows; for earnings
    # rows it's the press-release date. `event_time` is "BMO" | "AMC" |
    # "intraday" | None. `fiscal_year_label_basis` documents which convention
    # produced the fiscal_year column ("end" = year the period ends in;
    # "start" = year the period starts in). `source_timezone` records the
    # exchange/registrant timezone for accurate intraday rendering.
    event_date = Column(Date)
    event_time = Column(Text)            # 'BMO' | 'AMC' | 'intraday' | None
    fiscal_year_label_basis = Column(Text, default="end", server_default=text("'end'"))
    source_timezone = Column(Text, default="US/Eastern", server_default=text("'US/Eastern'"))
    revenue = Column(Float)
    cost_of_revenue = Column(Float)
    gross_profit = Column(Float)
    gross_margin = Column(Float)
    operating_income = Column(Float)
    operating_expenses = Column(Float)
    net_income = Column(Float)
    ebitda = Column(Float)
    rd_expense = Column(Float)
    # Phase 5S-2 (post-recompute): R&D disclosure state. Distinguishes
    # "rd_expense is NULL because the filer doesn't do R&D" from
    # "rd_expense is NULL because the filer bundles R&D into 'Operations
    # & Support' / 'Other OpEx' and never tags ResearchAndDevelopmentExpense
    # in XBRL". HIMS is the canonical example — the 10-K narrative
    # describes R&D activity and the tax footnote claims R&D credits
    # ($19.5M FY2025) and capitalized R&D DTAs, but no separate income-
    # statement R&D line exists. F3 treats `bundled_in_opex` as an
    # informational gap (no penalty), not a hard data miss.
    # Values: disclosed_exact | bundled_in_opex | NULL (unknown / not applicable)
    rd_disclosure_state = Column(Text)
    sga_expense = Column(Float)
    operating_cash_flow = Column(Float)
    free_cash_flow = Column(Float)
    capex = Column(Float)
    total_assets = Column(Float)
    total_equity = Column(Float)
    total_debt = Column(Float)
    long_term_debt = Column(Float)
    cash_and_equivalents = Column(Float)
    # Phase 5S-5: marketable securities + ST investments. Companies park
    # excess cash in T-bills, commercial paper, AFS debt securities. McKinsey
    # / Stewart / Mauboussin all treat this as "excess capital" and exclude
    # from invested capital (it doesn't deserve a cost-of-capital charge —
    # it's earning the risk-free rate, not operating returns). Captured
    # from both current (AvailableForSaleSecuritiesDebtSecuritiesCurrent,
    # ShortTermInvestments) and noncurrent (AvailableForSaleSecuritiesDebtSecuritiesNoncurrent)
    # XBRL tags, summed at materialize time. HIMS FY2025: $700M; NVDA: ~$32B.
    short_term_investments = Column(Float)
    accounts_receivable = Column(Float)
    current_assets = Column(Float)
    current_liabilities = Column(Float)
    inventory = Column(Float)
    shares_outstanding = Column(Float)
    # Split-basis reference for the EDGAR count above (never a substitute for it
    # — SECURITY §4). See data/share_basis.py; filings report as-filed, and
    # restated comparatives put neighbouring fiscal years on different bases.
    shares_outstanding_pit = Column(Float)      # yfinance point-in-time near period end
    share_split_factor = Column(Float)          # split ratios effective after period end
    eps_diluted = Column(Float)
    eps_basic = Column(Float)
    revenue_per_share = Column(Float)
    interest_expense = Column(Float)
    income_tax_expense = Column(Float)
    # Phase 5k / DEC-31 / 5k-5: float-related disclosures (payroll/payments/
    # insurance tickers). funds_held_for_clients sits separately from cash
    # on most filers' balance sheets; investment_income_interest captures
    # the float-interest revenue line that ADP-style filers expose
    # discretely. ROIC numerator subtracts the latter for non-insurers.
    funds_held_for_clients = Column(Float)
    investment_income_interest = Column(Float)
    # Phase 5R-1: data-quality signals.
    share_based_compensation = Column(Float)        # SBC in USD
    sbc_pct_of_revenue = Column(Float)              # derived: SBC / revenue
    goodwill = Column(Float)                        # goodwill on balance sheet, USD
    goodwill_pct_of_assets = Column(Float)          # derived: goodwill / total_assets
    # Phase 5k-7: SaaS retention metrics extracted from 10-K MD&A free-text.
    # F6 PROJECT_SPEC weights NRR + GRR at 2/10. No XBRL tag exists; companies
    # disclose in MD&A narrative when they choose to.
    nrr_pct = Column(Float)                  # net (revenue|dollar) retention
    grr_pct = Column(Float)                  # gross (revenue|dollar) retention
    retention_state = Column(Text)           # disclosed_exact|parser_uncertain|not_disclosed
    retention_fetched_at = Column(DateTime)
    # ADR-026 / 5Q-5: Cloud ARR + Total ARR metrics from MD&A free-text.
    # Cloud ARR is the forward-looking SaaS revenue commitment metric;
    # Total ARR includes both SaaS and on-prem. Read from latest 10-Q
    # (or 10-K if 10-Q absent). Distinct from `revenue` which is
    # backward-looking realised revenue.
    cloud_arr_usd = Column(Float)            # USD (e.g. 459_300_000 for $459.3M)
    cloud_arr_growth_yoy_pct = Column(Float)
    total_arr_usd = Column(Float)
    total_arr_growth_yoy_pct = Column(Float)
    arr_state = Column(Text)                 # disclosed_exact|parser_uncertain|not_disclosed
    arr_fetched_at = Column(DateTime)
    # Phase 5k-6 (partial): patent count disclosed in 10-K narrative.
    # Full Hirshleifer-Hsu-Li ★★★ Innovative Efficiency requires citation
    # graph from USPTO API (api.uspto.gov, requires user-side API key —
    # tracked as 5k-6b). This text-extracted absolute count is a coarse
    # fallback that fires for tech / biotech tickers that explicitly
    # disclose portfolio size in their 10-K.
    patent_count_disclosed = Column(Float)
    patent_disclosure_state = Column(Text)
    patent_disclosure_fetched_at = Column(DateTime)
    depreciation_amortization = Column(Float)
    dividends_paid = Column(Float)
    share_repurchases = Column(Float)
    # Computed quality metrics (derived on write — avoids repeated re-calculation).
    # ROIC formula updated Phase 5k / DEC-31: NOPAT / (Equity + Debt − Cash).
    # Total Debt already includes ASC 842 operating-lease liabilities (rolled
    # in by edgar_companyfacts.py). Goodwill remains in IC via Total Equity
    # per Stewart/Mauboussin/McKinsey standard. See pipeline.py for full doc.
    roic = Column(Float)                     # NOPAT / (E + D − Cash)
    pretax_roic = Column(Float)              # EBIT / (E + D − Cash)
    roe = Column(Float)                      # net_income / total_equity
    roa = Column(Float)                      # net_income / total_assets
    gp_a = Column(Float)                     # gross_profit / total_assets (Novy-Marx)
    net_margin = Column(Float)               # net_income / revenue
    operating_margin = Column(Float)         # operating_income / revenue
    fcf_margin = Column(Float)               # free_cash_flow / revenue
    rd_intensity = Column(Float)             # rd_expense / revenue
    asset_turnover = Column(Float)           # revenue / total_assets
    debt_to_equity = Column(Float)           # total_debt / total_equity
    # Phase 5S-5: net debt = total_debt − cash − short_term_investments.
    # Companies sitting on more liquid assets than debt are net-cash (negative
    # net_debt). Surfaced as a separate column for renderer/F5 use without
    # rewriting the gross total_debt provenance.
    net_debt = Column(Float)
    # debt_to_ebitda now uses NET DEBT (was gross total_debt before 5S-5).
    # When net_debt ≤ 0 (net-cash position), debt_to_ebitda = 0.0 by
    # convention — the ratio is undefined for the cash-rich case and
    # interpreting a negative ratio as "leverage" is misleading.
    debt_to_ebitda = Column(Float)
    current_ratio = Column(Float)            # current_assets / current_liabilities
    interest_coverage = Column(Float)        # operating_income / interest_expense
    accruals_ratio = Column(Float)           # (net_income - operating_cf) / total_assets (Sloan)
    buyback_yield = Column(Float)            # share_repurchases / market_cap (filled by yf step)
    # F6 customer-relationship signals (deterministic — XBRL → regex on 10-K text)
    customer_concentration_pct = Column(Float)    # top customer as % of revenue
    customer_relationship_years = Column(Float)   # years of key customer relationship(s)
    extraction_confidence = Column(Float)    # 1.0=XBRL/HTML verbatim, 0.5=regex, 0.0=missing
    # ADR-018 §2.3 — receivables concentration is a separate SEC disclosure
    # (FASB ASC 825 credit-risk concentration) from revenue concentration
    # (Reg S-K Item 101(c) customer concentration). They must NOT be
    # silently merged. F6 consumes customer_concentration_pct only;
    # receivables_concentration_pct is a credit-risk signal for future use.
    receivables_concentration_pct = Column(Float().with_variant(REAL(), "sqlite"))
    customer_concentration_state = Column(Text)         # disclosed_exact | not_disclosed | parser_uncertain
    customer_concentration_fetched_at = Column(TIMESTAMP)
    receivables_concentration_state = Column(Text)
    receivables_concentration_fetched_at = Column(TIMESTAMP)
    source = Column(Text, default="edgar")
    # ADR-039: period-end FX rate to USD for non-USD (non-SEC) filers. NULL for
    # native-USD rows. Ratios (ROIC, margins, growth) are currency-neutral and
    # ignore this; absolute-value consumers (e.g. Damodaran IV) multiply by it.
    fx_rate_to_usd = Column(Float)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", "period", name="uq_financial_period"),
        *_state_indexes(
            "financials",
            "customer_concentration_state",
            "receivables_concentration_state",
            names=("cust_conc", "recv_conc"),
        ),
    )

    company = relationship("Company", back_populates="financials")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    adj_close = Column(Float)
    source = Column(Text, default="yfinance")

    __table_args__ = (
        UniqueConstraint("company_id", "date", name="uq_price_date"),
    )

    company = relationship("Company", back_populates="price_history")


class InsiderTransactionRecord(Base):
    __tablename__ = "insider_transactions"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    filing_date = Column(Date, nullable=False)
    transaction_date = Column(Date)
    insider_name = Column(Text)
    insider_title = Column(Text)
    transaction_type = Column(Text)            # 'P' purchase | 'S' sale | 'A' award
    shares = Column(Float)
    price_per_share = Column(Float)
    value_usd = Column(Float)
    is_open_market = Column(Boolean, default=True)
    form_type = Column(Text, default="4")
    source = Column(Text, default="edgar")

    company = relationship("Company", back_populates="insider_transactions")


class AnalystCoverageRecord(Base):
    __tablename__ = "analyst_coverage"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    as_of_date = Column(Date, nullable=False)
    analyst_count = Column(Integer)
    consensus_rating = Column(Text)            # 'buy' | 'hold' | 'sell'
    price_target_mean = Column(Float)
    price_target_high = Column(Float)
    price_target_low = Column(Float)
    eps_estimate_next_q = Column(Float)
    rev_estimate_next_q = Column(Float)
    source = Column(Text, default="yfinance")

    company = relationship("Company", back_populates="analyst_coverage")


class EarningsHistory(Base):
    __tablename__ = "earnings_history"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_quarter = Column(Text, nullable=False)  # '2026Q1'
    report_date = Column(Date)
    eps_actual = Column(Float)
    eps_estimate = Column(Float)
    eps_surprise_pct = Column(Float)
    revenue_actual = Column(Float)
    revenue_estimate = Column(Float)
    rev_surprise_pct = Column(Float)
    source = Column(Text, default="yfinance")

    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_quarter", name="uq_earnings_quarter"),
    )

    company = relationship("Company", back_populates="earnings_history")


class ShortInterestRecord(Base):
    __tablename__ = "short_interest"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    settlement_date = Column(Date, nullable=False)
    short_interest = Column(Integer)
    short_pct_float = Column(Float)
    days_to_cover = Column(Float)
    float_shares = Column(Integer)
    source = Column(Text, default="yfinance")

    __table_args__ = (
        UniqueConstraint("company_id", "settlement_date", name="uq_short_date"),
    )

    company = relationship("Company", back_populates="short_interest")


class InstitutionalHolderRecord(Base):
    __tablename__ = "institutional_holders"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    report_date = Column(Date, nullable=False)
    holder_name = Column(Text)
    shares_held = Column(Integer)
    value_usd = Column(Float)
    pct_of_shares_out = Column(Float)
    change_in_shares = Column(Integer)         # positive = buying, negative = selling
    source = Column(Text, default="yfinance")

    company = relationship("Company", back_populates="institutional_holders")


class FrameworkScore(Base):
    __tablename__ = "framework_scores"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    run_date = Column(Date, nullable=False)
    mode = Column(Text, nullable=False)        # 'A' | 'B' | 'C' | 'D'
    company_stage = Column(Text)               # 'pre_profitability' | 'mid_cap' | 'established'
    f1_score = Column(Float)
    f2_score = Column(Float)
    f3_score = Column(Float)
    f4_score = Column(Float)
    f5_score = Column(Float)
    f6_score = Column(Float)
    f7_score = Column(Float)
    composite_score = Column(Float)
    verdict = Column(VerdictLabel)
    piotroski_score = Column(Integer)
    overlay_ica_run = Column(Boolean, default=False)
    overlay_psa_run = Column(Boolean, default=False)
    overlay_bew_run = Column(Boolean, default=False)
    overlay_notes = Column(Text)               # JSON string of overlay results
    disqualified = Column(Boolean, default=False)
    disqualification_reasons = Column(Text)    # JSON array
    scorecard_json = Column(Text)              # full pre-computed scorecard for AI layer
    narrative_json = Column(Text)              # AI-generated narrative sections
    created_at = Column(DateTime, server_default=func.now())

    company = relationship("Company", back_populates="framework_scores")


class ScreenerRun(Base):
    __tablename__ = "screener_runs"

    id = Column(Integer, primary_key=True)
    run_date = Column(DateTime, server_default=func.now())
    region = Column(Text)
    market_cap_min = Column(Float)
    market_cap_max = Column(Float)
    sector_filter = Column(Text)
    ethics_filter = Column(Text)
    mode = Column(Text)
    universe_count = Column(Integer)
    passed_gates = Column(Integer)
    results_json = Column(Text)                # full ranked table as JSON (legacy / summary)

    ticker_results = relationship("ScreenerResult", back_populates="screener_run", cascade="all, delete-orphan")
    stages = relationship("ScreenerStage", back_populates="screener_run", cascade="all, delete-orphan")


class ScreenerStage(Base):
    """
    Checkpoint per stage of the staggered screener (docs/architecture/SCREENER_PIPELINE.md §4).
    Stages: 'A' (universe + Tier 1-3), 'B' (Tier 4 frames), 'C' (Tier 5-6 shortlist).
    A failed stage records its error so the next stage can decide to skip
    or proceed; resumable via `invest screen run --stage X --run-id Y`.
    """
    __tablename__ = "screener_stages"

    id = Column(Integer, primary_key=True)
    screener_run_id = Column(Integer, ForeignKey("screener_runs.id"), nullable=False)
    stage = Column(Text, nullable=False)             # 'A' | 'B' | 'C'
    status = Column(Text, nullable=False)            # 'running' | 'completed' | 'failed'
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    input_count = Column(Integer)
    output_count = Column(Integer)
    error = Column(Text)
    # Stage's output state — handoff to the next stage. JSON-serialised
    # tickers/flags/funnel. Stage B reads stage A's state, etc.
    state_json = Column(Text)

    __table_args__ = (
        UniqueConstraint("screener_run_id", "stage", name="uq_screener_stage"),
    )

    screener_run = relationship("ScreenerRun", back_populates="stages")


class ScreenerResult(Base):
    """Normalised per-ticker result row within a screener run."""
    __tablename__ = "screener_results"

    id = Column(Integer, primary_key=True)
    screener_run_id = Column(Integer, ForeignKey("screener_runs.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)  # NULL if company not yet in DB
    ticker = Column(Text, nullable=False)
    hard_gate_passed = Column(Boolean, default=False)
    gate_failures = Column(Text)               # JSON array of gate names that failed
    # Proxy scores used for screener ranking (lighter-weight than full framework scores)
    f1_proxy = Column(Float)
    f2_proxy = Column(Float)
    f3_proxy = Column(Float)
    f4_proxy = Column(Float)
    f5_proxy = Column(Float)
    f6_proxy = Column(Float)
    f7_proxy = Column(Float)
    composite_score = Column(Float)
    verdict = Column(Text)                     # 'deep_dive' | 'watch' | 'bench'
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("screener_run_id", "ticker", name="uq_screener_result_run_ticker"),
    )

    screener_run = relationship("ScreenerRun", back_populates="ticker_results")
    deepdive_runs = relationship("DeepDiveRun", back_populates="screener_result")


class DeepDiveRun(Base):
    """
    Per-ticker full deep-dive result.
    Optionally linked to a ScreenerResult (screener_result_id=NULL for standalone dives).
    Stores all framework signals, overlay results, and AI narrative once computed.
    """
    __tablename__ = "deepdive_runs"

    id = Column(Integer, primary_key=True)
    screener_result_id = Column(Integer, ForeignKey("screener_results.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    ticker = Column(Text, nullable=False)
    tier = Column(Integer, default=1)          # 1 = quick (F1+F2+F3), 2 = full
    mode = Column(Text, nullable=False)        # 'A' | 'B' | 'C' | 'D'
    run_date = Column(DateTime, server_default=func.now())
    composite_score = Column(Float)
    verdict = Column(VerdictLabel)
    # Per-framework scores (full computation, not proxies)
    f1_score = Column(Float)
    f2_score = Column(Float)
    f3_score = Column(Float)
    f4_score = Column(Float)
    f5_score = Column(Float)
    f6_score = Column(Float)
    f7_score = Column(Float)
    # Detailed framework signal data (stored as JSON — referenced by export + AI layer)
    framework_results_json = Column(Text)      # {f1: {score, signals, data_points}, ...}
    # Overlay tracking
    overlays_triggered_json = Column(Text)     # [{overlay, condition, triggered: bool}, ...]
    overlays_results_json = Column(Text)       # {ICA: {...result...}, PSA: {...}, ...}
    # AI-generated narrative (stored once, not recomputed)
    bull_narrative = Column(Text)
    bear_narrative = Column(Text)
    risk_factors = Column(Text)
    # Data quality log
    data_gaps_json = Column(Text)              # JSON array of gap strings
    # SEC EDGAR reference
    edgar_10k_accession = Column(Text)         # accession number of 10-K used as primary source
    # DEC-46: what the dive read, and whether that has since been superseded.
    parser_version = Column(Integer)           # newest parser that wrote the ticker's rows; NULL = unversioned
    scorecard_view_json = Column(Text)         # ScorecardView.to_llm_context() at dive time
    scorecard_view_sha256 = Column(Text)
    stale_reason = Column(Text)                # set once inputs are superseded; stale dives are never deleted
    stale_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    screener_result = relationship("ScreenerResult", back_populates="deepdive_runs")
    company = relationship("Company")


class DeepDiveConversation(Base):
    """Phase 5L: persistent conversational dive turns.

    One row per turn (user OR assistant), keyed by deep_dive_run_id +
    turn_index. Append-only — no edits, no deletes (so audit trail of
    what the LLM actually said is preserved). The CLI's `invest chat
    TICKER` REPL writes here and reads back across sessions.

    Conversation history is replayed (sliding window of last 8 turns)
    on each new turn so the LLM has continuity. The ScorecardView the
    conversation grounds in is *frozen* at the linked DeepDiveRun's
    snapshot — re-dive creates a new run + a fresh conversation, while
    old conversations stay queryable as historical artifacts.
    """
    __tablename__ = "deep_dive_conversations"

    id = Column(Integer, primary_key=True)
    deep_dive_run_id = Column(Integer, ForeignKey("deepdive_runs.id"), nullable=False)
    ticker = Column(Text, nullable=False)
    turn_index = Column(Integer, nullable=False)        # 0, 1, 2, ...
    role = Column(Text, nullable=False)                  # 'user' | 'assistant'
    content = Column(Text, nullable=False)               # the user message OR assistant reply text
    numeric_claims_json = Column(Text)                   # assistant turns only — list[NumericClaim]
    guard_warnings_json = Column(Text)                   # validator output (empty list = clean)
    provider = Column(Text)                              # 'anthropic' | 'openai'
    model = Column(Text)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    cost_usd = Column(Float)                             # estimated turn cost
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "deep_dive_run_id", "turn_index",
            name="uq_dive_conversation_turn",
        ),
        Index("idx_dive_conversation_run", "deep_dive_run_id"),
        Index("idx_dive_conversation_ticker", "ticker"),
    )

    deep_dive_run = relationship("DeepDiveRun")


class FinancialSourceLog(Base):
    """
    Tier-0 EDGAR cache gate — tracks accession numbers already fetched.
    Check this table BEFORE any EDGAR download; if accession exists, skip entirely.
    Prevents redundant EDGAR requests across refresh_ticker() calls.
    """
    __tablename__ = "financial_source_log"

    id = Column(Integer, primary_key=True)
    ticker = Column(Text, nullable=False)
    accession_number = Column(Text, nullable=False, unique=True)
    form_type = Column(Text, nullable=False)    # '10-K' | '10-Q' | '4' | 'DEF 14A'
    fiscal_year = Column(Integer)
    period = Column(Text)                       # 'annual' | 'Q1'..'Q4' | None
    fetched_at = Column(DateTime, server_default=func.now())
    # PARSER_VERSION (data/edgar_companyfacts.py) that read it; NULL = before versioning.
    parser_version = Column(Integer)
    parsing_status = Column(Text, default="success")  # 'success' | 'partial' | 'failed'

    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_source_log_accession"),
    )


class ExternalSignalRecord(Base):
    """LLM-extracted or third-party-sourced signals — strictly isolated from
    the deterministic SEC-XBRL data path.

    Architectural contract:
      - Frameworks F1-F7 MUST NOT read this table. The deterministic data
        pipeline owns the canonical Company/Financial columns. This table
        is supplementary, narrative-only, and rendered in the dive display
        as a separately-labelled "External Signals" panel.
      - Every row carries a full audit trail: source URL, verbatim quote,
        extraction confidence, method, model. If the trail is missing, the
        value is missing (no silent fallback).
      - extraction_method='llm_anthropic' rows are produced by the
        deepdive/external_signals.py module — the second permitted Anthropic
        call site after deepdive/narrative.py. Both live within the dive
        layer; data/screener/framework layers remain LLM-free.
      - extraction_confidence is a categorical band, never a numeric score
        (no false precision).

    Common signal_name values: 'nrr_pct', 'grr_pct', 'mrr_usd', 'arr_usd',
    'gmv_usd', 'merchant_count', 'take_rate_pct'. New signals added as
    needed — the schema is intentionally flexible because LLM extraction
    targets a much wider field set than XBRL.
    """
    __tablename__ = "external_signals"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    signal_name = Column(Text, nullable=False, index=True)
    signal_value_numeric = Column(Float)
    signal_value_text = Column(Text)
    signal_unit = Column(Text)                 # 'pct' | 'usd' | 'count' | 'ratio'
    as_of_date = Column(Date)                  # period the signal refers to

    # Audit trail — every field is mandatory for llm_anthropic rows
    source_url = Column(Text)
    source_quote = Column(Text)                # verbatim from source
    source_document = Column(Text)             # e.g. 'Q1_2026_8K_earnings_press_release'
    source_accession = Column(Text)            # SEC accession number when applicable
    extraction_method = Column(Text, nullable=False)   # 'llm_anthropic' | 'regex' | 'manual'
    extraction_confidence = Column(Text, nullable=False)   # 'high' | 'medium' | 'low' | 'not_disclosed'
    extracted_at = Column(DateTime, server_default=func.now())
    extracted_model = Column(Text)             # e.g. 'claude-opus-4-7'

    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint(
            "company_id", "signal_name", "as_of_date",
            name="uq_external_signal",
        ),
    )


class SkillInvocation(Base):
    """ADR-032 §9.1.1 — telemetry log for project-local skill invocations.

    Architectural role: this table is the shadow-mode verification ledger.
    Every invocation of any skill from `.claude/skills/` MUST append one row.
    Shadow-mode exits depend on querying this table:
      - >=10 invocations with success=True
      - 100% postcondition pass rate (postconditions_json all pass)
      - 0 unexplained anomalies (anomalies_json null OR false_positive_annotation set)

    Read-only from the F1-F7 framework path. Skills write; the human author
    + automation review. Composite scoring never touches this.

    `args_json` is the serialised invocation arguments (e.g., {"ticker": "SHOP"}).
    `postconditions_json` is a list of {name, pass: bool, observed, expected} entries.
    `anomalies_json` is delta-check results — null when none fired.

    Indexed on (skill_name, invoked_at) for the common queries:
      - "how many invocations of /dive-complete this month?"
      - "any anomalies in /external-signals over the last 14 days?"
    """
    __tablename__ = "skill_invocations"

    id = Column(Integer, primary_key=True)
    skill_name = Column(Text, nullable=False, index=True)
    skill_version = Column(Text, nullable=False)
    invoked_at = Column(DateTime, server_default=func.now(), index=True)
    args_json = Column(Text)
    success = Column(Boolean, nullable=False)
    duration_seconds = Column(Float)
    tool_calls_count = Column(Integer)
    tokens_prompt = Column(Integer)
    tokens_completion = Column(Integer)
    cost_usd = Column(Float)
    postconditions_json = Column(Text)
    shadow_mode_active = Column(Boolean, nullable=False, default=False, server_default=false())
    anomalies_json = Column(Text)
    false_positive_annotation = Column(Text)
    error_message = Column(Text)


class TaskFailure(Base):
    """
    Per-(task, cik) latest-failure log written by the universal task runner
    (Phase 4a / ADR-017 §7). Latest failure REPLACES older row via UPSERT
    on (task_name, cik). `retry_count` increments on each failure; the
    runner skips tickers with retry_count > MAX_TASK_RETRIES until a
    successful task run resets the count.
    """
    __tablename__ = "task_failures"

    id = Column(Integer, primary_key=True)
    task_name = Column(Text, nullable=False)
    cik = Column(Text, nullable=False)
    failed_at = Column(DateTime, server_default=func.now(), nullable=False)
    error = Column(Text)
    retry_count = Column(Integer, server_default="0", nullable=False)

    __table_args__ = (
        UniqueConstraint("task_name", "cik", name="uq_task_failures_task_cik"),
    )


class TaskRun(Base):
    """ADR-019 §5: visibility for "did task X succeed today?" in SQL.

    One row per task invocation (success, failure, or skip). Indexed on
    (task_name, started_at DESC) for fast "latest run of task X" queries.
    Used to drive next-run cadence decisions (warehouse-task pattern).
    """
    __tablename__ = "task_runs"

    # Created by raw SQL as `id INTEGER PRIMARY KEY`, which SQLite reports as nullable.
    id = Column(Integer, primary_key=True, nullable=True)
    task_name = Column(Text, nullable=False)
    ticker = Column(Text)                       # NULL for non-ticker-scoped tasks
    started_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    completed_at = Column(TIMESTAMP)
    status = Column(Text, nullable=False)       # 'success' | 'failed' | 'skipped'
    error = Column(Text)                        # populated when status='failed'
    rows_written = Column(Integer, default=0, server_default=text("0"))

    __table_args__ = (
        Index("idx_task_runs_name_time", task_name, started_at.desc()),
        Index("idx_task_runs_task", "task_name", "started_at"),
        Index("idx_task_runs_ticker", ticker, started_at.desc()),
    )


class PortfolioPosition(Base):
    """Phase 5P / DEC-35: actual portfolio holdings (positions you own).

    Structurally distinct from WatchlistEntry. WatchlistEntry tracks
    CANDIDATES — names you're researching, may buy. PortfolioPosition
    tracks HOLDINGS — names you actually own, with cost basis and entry
    date that anchor the DEC-23 5-year reconsideration window.

    Per DEC-23 hold philosophy, the entry_date is load-bearing: years
    1-4 are warning-monitoring-only; reconsideration window opens at
    year 5. The annual reassessment scheduler (5P-3) reads from this
    table, not from WatchlistEntry.

    Append-only audit trail: `remove` operations set `is_active=False`
    rather than deleting rows. A position that was held for 3 years
    then sold should still appear in queries asking "what did I learn
    from this position".
    """
    __tablename__ = "portfolio_positions"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    ticker = Column(Text, nullable=False)
    # Entry date — anchor for the DEC-23 5-year reconsideration window.
    # Required at add time; cannot be NULL for an active position.
    entry_date = Column(Date, nullable=False)
    # Role classification — affects sizing logic and prioritisation but not
    # the reassessment cron (which dives all active positions equally).
    role = Column(Text)                        # 'core' | 'satellite' | 'hedge'
    # Position-level economics. Optional — if you don't track in this system,
    # leave NULL and the dive output simply won't render position-level math.
    shares = Column(Float)
    cost_basis_usd = Column(Float)             # total cost basis in USD
    cost_basis_per_share = Column(Float)       # convenience field for display
    # Thesis — why you bought. Used by the annual reassessment as the
    # "original story" baseline that Lynch's story-break test compares
    # against. Free text, intentionally not structured.
    thesis = Column(Text)
    notes = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False, server_default=true())
    added_to_portfolio_at = Column(DateTime, server_default=func.now())
    exited_at = Column(DateTime)               # set when is_active flipped to False

    company = relationship("Company")

    __table_args__ = (
        UniqueConstraint(
            "company_id", "entry_date",
            name="uq_portfolio_position_entry",
        ),
        Index("idx_portfolio_ticker", "ticker"),
        Index("idx_portfolio_active", "is_active"),
    )


class WatchlistEntry(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    added_date = Column(Date, server_default=func.current_date())
    entry_triggers = Column(Text)              # JSON array of trigger conditions
    stop_loss_note = Column(Text)
    role = Column(Text)                        # 'core' | 'satellite' | 'monitor'
    notes = Column(Text)
    is_active = Column(Boolean, default=True)

    company = relationship("Company", back_populates="watchlist")
