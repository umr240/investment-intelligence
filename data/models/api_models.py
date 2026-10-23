"""
Pydantic v2 models for FMP and Alpha Vantage API responses.

Uses alias_generator=to_camel so snake_case field names automatically accept
camelCase JSON keys (FMP's format). populate_by_name=True allows both:
  - model.gross_profit (Python attribute access)
  - construction from {"grossProfit": ...} JSON
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _FMPBase(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        extra="ignore",
    )


# ── Financial Statements ──────────────────────────────────────────────────

class IncomeStatement(_FMPBase):
    symbol: str = ""
    date: str = ""
    period: str = ""
    revenue: float = 0.0
    cost_of_revenue: float = 0.0
    gross_profit: float = 0.0
    gross_profit_ratio: float = 0.0
    research_and_development_expenses: float | None = None
    selling_general_and_administrative_expenses: float | None = None
    operating_expenses: float = 0.0
    operating_income: float = 0.0
    operating_income_ratio: float = 0.0
    interest_expense: float | None = None
    ebitda: float | None = None
    net_income: float = 0.0
    net_income_ratio: float = 0.0
    eps: float | None = None
    # FMP returns this as "epsdiluted" (not camelCase), handle with explicit alias
    epsdiluted: float | None = Field(default=None, alias="epsdiluted")
    weighted_average_shs_out_dil: float | None = None
    income_tax_expense: float | None = None

    @property
    def rd_expense(self) -> float | None:
        return self.research_and_development_expenses

    @property
    def sga_expense(self) -> float | None:
        return self.selling_general_and_administrative_expenses

    @property
    def gross_margin(self) -> float:
        return self.gross_profit / self.revenue if self.revenue else 0.0

    @property
    def effective_tax_rate(self) -> float:
        if self.income_tax_expense and (self.net_income + self.income_tax_expense) > 0:
            return self.income_tax_expense / (self.net_income + self.income_tax_expense)
        return 0.21  # fallback corporate rate


class BalanceSheet(_FMPBase):
    symbol: str = ""
    date: str = ""
    period: str = ""
    cash_and_cash_equivalents: float = 0.0
    net_receivables: float = 0.0
    inventory: float | None = None
    total_current_assets: float = 0.0
    property_plant_equipment_net: float | None = None
    goodwill: float | None = None
    intangible_assets: float | None = None
    total_non_current_assets: float = 0.0
    total_assets: float = 0.0
    account_payables: float | None = None
    short_term_debt: float | None = None
    total_current_liabilities: float = 0.0
    long_term_debt: float = 0.0
    total_non_current_liabilities: float = 0.0
    total_liabilities: float = 0.0
    retained_earnings: float | None = None
    total_stockholders_equity: float = 0.0
    total_equity: float = 0.0
    total_debt: float = 0.0
    net_debt: float = 0.0
    common_stock_shares_outstanding: float | None = None


class CashFlow(_FMPBase):
    symbol: str = ""
    date: str = ""
    period: str = ""
    net_income: float = 0.0
    depreciation_and_amortization: float | None = None
    stock_based_compensation: float | None = None
    operating_cash_flow: float = 0.0
    capital_expenditure: float = 0.0
    free_cash_flow: float = 0.0
    common_stock_repurchased: float | None = None
    dividends_paid: float | None = None
    net_cash_used_provided_by_financing_activities: float | None = None

    @property
    def capex(self) -> float:
        return abs(self.capital_expenditure)


# ── Company Data ──────────────────────────────────────────────────────────

class CompanyProfile(_FMPBase):
    symbol: str = ""
    price: float = 0.0
    beta: float | None = None
    mkt_cap: float = 0.0
    company_name: str = ""
    currency: str = "USD"
    cik: str | None = None
    isin: str | None = None
    exchange: str = ""
    exchange_short_name: str = ""
    industry: str = ""
    website: str | None = None
    description: str | None = None
    ceo: str | None = None
    sector: str = ""
    country: str = ""
    full_time_employees: str | None = None
    ipo_date: str | None = None
    is_etf: bool = False
    is_actively_trading: bool = True
    is_adr: bool = False


class KeyMetrics(_FMPBase):
    symbol: str = ""
    date: str = ""
    period: str = ""
    market_cap: float | None = None
    enterprise_value: float = 0.0
    pe_ratio: float | None = None
    price_to_sales_ratio: float | None = None
    pfcf_ratio: float | None = None
    pb_ratio: float | None = None
    ev_to_sales: float | None = None
    enterprise_value_over_ebitda: float | None = None
    earnings_yield: float | None = None
    free_cash_flow_yield: float | None = None
    debt_to_equity: float | None = None
    net_debt_to_ebitda: float | None = None
    current_ratio: float | None = None
    interest_coverage: float | None = None
    dividend_yield: float | None = None
    roic: float | None = None
    roe: float | None = None
    invested_capital: float | None = None
    research_and_development_to_revenue: float | None = None
    capex_to_revenue: float | None = None


class KeyMetricsTTM(_FMPBase):
    pe_ratio_ttm: float | None = None
    price_to_sales_ratio_ttm: float | None = None
    pfcf_ratio_ttm: float | None = None
    pb_ratio_ttm: float | None = None
    ev_to_sales_ttm: float | None = None
    enterprise_value_over_ebitda_ttm: float | None = None
    debt_to_equity_ttm: float | None = None
    net_debt_to_ebitda_ttm: float | None = None
    current_ratio_ttm: float | None = None
    interest_coverage_ttm: float | None = None
    dividend_yield_ttm: float | None = None
    roic_ttm: float | None = None
    roe_ttm: float | None = None
    free_cash_flow_yield_ttm: float | None = None
    market_cap_ttm: float | None = None
    enterprise_value_ttm: float | None = None


class Ratios(_FMPBase):
    symbol: str = ""
    date: str = ""
    period: str = ""
    gross_profit_margin: float | None = None
    operating_profit_margin: float | None = None
    net_profit_margin: float | None = None
    return_on_assets: float | None = None
    return_on_equity: float | None = None
    return_on_capital_employed: float | None = None
    debt_equity_ratio: float | None = None
    interest_coverage: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    asset_turnover: float | None = None
    inventory_turnover: float | None = None
    price_to_book_ratio: float | None = None
    price_to_sales_ratio: float | None = None
    price_earnings_ratio: float | None = None
    price_to_free_cash_flows_ratio: float | None = None
    enterprise_value_multiple: float | None = None
    dividend_yield: float | None = None
    free_cash_flow_per_share: float | None = None
    operating_cash_flow_per_share: float | None = None


class RatiosTTM(_FMPBase):
    gross_profit_margin_ttm: float | None = None
    operating_profit_margin_ttm: float | None = None
    net_profit_margin_ttm: float | None = None
    return_on_assets_ttm: float | None = None
    return_on_equity_ttm: float | None = None
    debt_equity_ratio_ttm: float | None = None
    interest_coverage_ttm: float | None = None
    current_ratio_ttm: float | None = None
    pe_ratio_ttm: float | None = None
    price_to_book_ratio_ttm: float | None = None
    price_to_sales_ratio_ttm: float | None = None
    free_cash_flow_yield_ttm: float | None = None


# ── Market Intelligence ───────────────────────────────────────────────────

class InsiderTransaction(_FMPBase):
    symbol: str = ""
    filing_date: str = ""
    transaction_date: str | None = None
    reporting_name: str = ""
    type_of_owner: str | None = None
    acquisition_or_disposition: str = ""
    form_type: str = "4"
    securities_transacted: float = 0.0
    price: float | None = None
    securities_owned: float | None = None
    security_name: str | None = None

    @property
    def is_open_market_purchase(self) -> bool:
        return self.acquisition_or_disposition == "A"

    @property
    def value_usd(self) -> float | None:
        if self.price and self.securities_transacted:
            return self.price * abs(self.securities_transacted)
        return None


class EarningsSurprise(_FMPBase):
    date: str = ""
    symbol: str = ""
    actual_earning_result: float | None = None
    estimated_earning: float | None = None

    @property
    def surprise_pct(self) -> float | None:
        if (
            self.estimated_earning is not None
            and self.actual_earning_result is not None
            and self.estimated_earning != 0
        ):
            return (
                self.actual_earning_result - self.estimated_earning
            ) / abs(self.estimated_earning)
        return None


class AnalystCoverage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    symbol: str = ""
    analyst_count: int = 0
    estimates: list[dict[str, Any]] = Field(default_factory=list)
    price_target_summary: dict[str, Any] = Field(default_factory=dict)
    consensus_rating: str | None = None


class ShortInterest(_FMPBase):
    symbol: str = ""
    date: str = ""
    free_float: float | None = None
    float_shares: float | None = None
    outstanding_shares: float | None = None
    source: str | None = None


class InstitutionalHolder(_FMPBase):
    holder: str = ""
    shares: float = 0.0
    date_reported: str = ""
    change: float = 0.0
    weight_percent: float = 0.0


# ── Screener ──────────────────────────────────────────────────────────────

@dataclass
class ScreenerParams:
    region: str = "US"
    cap_min: float = 50_000_000
    cap_max: float = 10_000_000_000
    sector: str | None = None
    exchange: str | None = None
    exclusion_policy: str | None = None  # registered policy name; None = settings


class ScreenerResult(_FMPBase):
    symbol: str = ""
    company_name: str = ""
    market_cap: float = 0.0
    sector: str = ""
    industry: str = ""
    beta: float | None = None
    price: float = 0.0
    volume: float | None = None
    exchange: str = ""
    exchange_short_name: str = ""
    country: str = ""
    is_etf: bool = False
    is_actively_trading: bool = True


# ── Alpha Vantage ─────────────────────────────────────────────────────────

class WeeklyPrice(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    date: str
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int
    dividend_amount: float = 0.0


class Quote(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    symbol: str
    price: float
    open: float
    high: float
    low: float
    volume: int
    previous_close: float
    change: float
    change_percent: str
    latest_trading_day: str


class QuarterlyEarning(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    fiscal_date_ending: str
    reported_date: str | None = None
    reported_eps: float | None = None
    estimated_eps: float | None = None
    surprise: float | None = None
    surprise_percentage: float | None = None


class EarningsData(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    symbol: str
    quarterly_earnings: list[QuarterlyEarning] = Field(default_factory=list)
