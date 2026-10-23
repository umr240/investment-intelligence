"""YFinanceFundamentalsSource — Tier-3 multi-year fundamentals (ADR-039 Phase B).

The pragmatic bridge for non-SEC issuers (Canadian TSX/TSX-V first; any foreign
suffix as fallback). Pulls ``Ticker.income_stmt`` / ``.balance_sheet`` /
``.cashflow`` (annual + quarterly), maps Yahoo's standardised line-item labels
to ``EdgarFinancialRow``, and tags every row ``source='yfinance'``.

Honesty contract (ADR-038 §"What yfinance can deliver", ADR-022 Tier-3):
  * Depth is typically ~4 annual periods (vs ~10yr for SEC) — F7 z-scores will
    surface InsufficientHistoryError; that's the existing graceful path.
  * No insider / proxy / 10-K-text / per-concept R&D — those stay data_gaps.
  * Values are in the filer's reporting currency; ratios (ROIC, margins,
    growth, Piotroski) are currency-neutral, so F1/F3/F5 work unadjusted.
    ``fx_rate_to_usd`` is captured best-effort for absolute-value consumers.

Fail-soft throughout: a blank frame becomes a gap, never an exception.
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from data.sources.base import (
    TAG_YFINANCE,
    TIER_YFINANCE,
    FundamentalsResult,
    _suffix,
    register,
)

if TYPE_CHECKING:
    from data.models.schema import Company

logger = logging.getLogger(__name__)

# Exchange-suffix → expected reporting currency (cross-check for yfinance's
# occasionally-wrong financialCurrency field — ADR-038 §Risks).
_SUFFIX_CURRENCY = {
    "TO": "CAD", "V": "CAD", "CN": "CAD", "NE": "CAD",
    "L": "GBP", "ST": "SEK", "AX": "AUD", "DE": "EUR",
    "WA": "PLN", "OL": "NOK", "HE": "EUR", "ST.": "SEK",
}


def _val(df: Any, col: Any, labels: tuple[str, ...]) -> float | None:
    """First non-NaN value among candidate row labels at column ``col``."""
    if df is None or getattr(df, "empty", True):
        return None
    index = df.index
    for lab in labels:
        if lab in index:
            try:
                v = df.at[lab, col]
            except Exception:  # noqa: BLE001 — duplicate label / odd dtype
                continue
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isnan(fv):
                continue
            return fv
    return None


def _period_label(month: int, kind: str) -> str:
    if kind == "annual":
        return "annual"
    # Calendar-quarter approximation (Tier-3; we lack fiscal-year-end for
    # non-SEC filers). (year, period) uniqueness still holds.
    return f"Q{((month - 1) // 3) + 1}"


def _rows_from_frames(
    ticker: str, currency: str, kind: str, is_df: Any, bs_df: Any, cf_df: Any
) -> list[Any]:
    from data.edgar_fetcher import EdgarFinancialRow

    rows: list[Any] = []
    if is_df is None or getattr(is_df, "empty", True):
        return rows

    for col in is_df.columns:
        try:
            end_date = col.date()
        except Exception:  # noqa: BLE001
            continue
        fiscal_year = end_date.year

        revenue = _val(is_df, col, ("Total Revenue", "Operating Revenue"))
        gross_profit = _val(is_df, col, ("Gross Profit",))
        cost_of_revenue = _val(is_df, col, ("Cost Of Revenue", "Reconciled Cost Of Revenue"))
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue
        gross_margin = (
            (gross_profit / revenue) if (gross_profit is not None and revenue) else None
        )

        row = EdgarFinancialRow(
            ticker=ticker,
            fiscal_year=fiscal_year,
            period=_period_label(end_date.month, kind),
            source="yfinance",
            accession_number="",
            period_end_date=end_date,
            filed_date=None,
            revenue=revenue,
            cost_of_revenue=cost_of_revenue,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
            operating_income=_val(is_df, col, ("Operating Income", "EBIT")),
            operating_expenses=_val(is_df, col, ("Operating Expense", "Total Expenses")),
            net_income=_val(is_df, col, ("Net Income", "Net Income Common Stockholders")),
            ebitda=_val(is_df, col, ("EBITDA", "Normalized EBITDA")),
            rd_expense=_val(is_df, col, ("Research And Development",)),
            sga_expense=_val(
                is_df, col,
                ("Selling General And Administration", "Selling General And Administrative"),
            ),
            interest_expense=_val(
                is_df, col, ("Interest Expense", "Interest Expense Non Operating")
            ),
            income_tax_expense=_val(is_df, col, ("Tax Provision", "Income Tax Expense")),
            depreciation_amortization=_val(
                is_df, col, ("Reconciled Depreciation", "Depreciation And Amortization")
            ),
            eps_diluted=_val(is_df, col, ("Diluted EPS",)),
            eps_basic=_val(is_df, col, ("Basic EPS",)),
            # ── Balance sheet ──
            total_assets=_val(bs_df, col, ("Total Assets",)),
            total_equity=_val(
                bs_df, col,
                ("Stockholders Equity", "Total Equity Gross Minority Interest",
                 "Common Stock Equity"),
            ),
            total_debt=_val(bs_df, col, ("Total Debt",)),
            long_term_debt=_val(
                bs_df, col,
                ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
            ),
            cash_and_equivalents=_val(
                bs_df, col,
                ("Cash And Cash Equivalents",
                 "Cash Cash Equivalents And Short Term Investments"),
            ),
            short_term_investments=_val(
                bs_df, col, ("Other Short Term Investments", "Short Term Investments")
            ),
            accounts_receivable=_val(bs_df, col, ("Accounts Receivable", "Receivables")),
            current_assets=_val(bs_df, col, ("Current Assets",)),
            current_liabilities=_val(bs_df, col, ("Current Liabilities",)),
            inventory=_val(bs_df, col, ("Inventory",)),
            goodwill=_val(bs_df, col, ("Goodwill",)),
            shares_outstanding=_val(
                bs_df, col, ("Ordinary Shares Number", "Share Issued")
            ) or _val(is_df, col, ("Diluted Average Shares", "Basic Average Shares")),
            # ── Cash flow ──
            operating_cash_flow=_val(
                cf_df, col,
                ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
            ),
            free_cash_flow=_val(cf_df, col, ("Free Cash Flow",)),
            capex=_val(cf_df, col, ("Capital Expenditure", "Capital Expenditure Reported")),
            dividends_paid=_val(cf_df, col, ("Cash Dividends Paid", "Common Stock Dividend Paid")),
            share_repurchases=_val(cf_df, col, ("Repurchase Of Capital Stock",)),
            share_based_compensation=_val(cf_df, col, ("Stock Based Compensation",)),
        )
        # FCF fallback: OCF - |capex| if Yahoo didn't supply Free Cash Flow.
        if (
            row.free_cash_flow is None
            and row.operating_cash_flow is not None
            and row.capex is not None
        ):
            row.free_cash_flow = row.operating_cash_flow - abs(row.capex)
        rows.append(row)

    return rows


def _fetch_fx_to_usd(currency: str) -> float | None:
    if currency == "USD":
        return 1.0
    try:
        import yfinance as yf
        fx = yf.Ticker(f"{currency}USD=X")
        info = getattr(fx, "fast_info", None)
        rate = None
        if info is not None:
            rate = getattr(info, "last_price", None) or (
                info.get("lastPrice") if isinstance(info, dict) else None
            )
        if rate is None:
            hist = fx.history(period="5d")
            if not hist.empty:
                rate = float(hist["Close"].iloc[-1])
        return float(rate) if rate else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("FX fetch %sUSD failed: %s", currency, exc)
        return None


def _fetch_sync(ticker: str) -> FundamentalsResult:
    """Blocking yfinance pull — run via run_in_executor by ``fetch``."""
    import yfinance as yf

    result = FundamentalsResult(ticker=ticker, source_tier=TAG_YFINANCE)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as exc:  # noqa: BLE001
        result.gaps.append(f"{ticker}: yfinance resolution failed ({exc})")
        return result

    if not info.get("shortName") and not info.get("longName"):
        result.gaps.append(f"{ticker}: yfinance returned no company profile — check ticker suffix")
        return result

    suffix = _suffix(ticker)
    expected_cur = _SUFFIX_CURRENCY.get(suffix)
    currency = info.get("financialCurrency") or expected_cur or "USD"
    if expected_cur and info.get("financialCurrency") and info["financialCurrency"] != expected_cur:
        result.gaps.append(
            f"{ticker}: yfinance financialCurrency={info['financialCurrency']} but "
            f"exchange suffix .{suffix} implies {expected_cur} — using reported currency"
        )
    result.reporting_currency = currency
    result.metadata = {
        "name": info.get("longName") or info.get("shortName"),
        "exchange": info.get("exchange"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "currency": currency,
        "country": info.get("country"),
    }
    result.fx_rate_to_usd = _fetch_fx_to_usd(currency)

    try:
        annual = _rows_from_frames(
            ticker, currency, "annual", t.income_stmt, t.balance_sheet, t.cashflow
        )
    except Exception as exc:  # noqa: BLE001
        annual = []
        result.gaps.append(f"{ticker}: yfinance annual financials unavailable ({exc})")
    try:
        quarterly = _rows_from_frames(
            ticker, currency, "quarterly",
            t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow,
        )
    except Exception as exc:  # noqa: BLE001
        quarterly = []
        result.gaps.append(f"{ticker}: yfinance quarterly financials unavailable ({exc})")

    result.financials = annual + quarterly
    annual_with_rev = [r for r in annual if r.revenue is not None]
    if not annual_with_rev:
        result.gaps.append(f"{ticker}: no annual revenue from yfinance — Tier-3 dive infeasible")
    elif len(annual_with_rev) < 3:
        result.gaps.append(
            f"{ticker}: only {len(annual_with_rev)} annual periods from yfinance "
            f"(Tier-3 depth limited; F5/F7 may degrade)"
        )
    return result


class YFinanceFundamentalsSource:
    name = TIER_YFINANCE
    tier = TIER_YFINANCE
    available = True

    def supports(self, ticker: str, company: Company | None) -> bool:
        # Fallback bridge: supports any ticker (resolver only routes foreign
        # suffixes here; US tickers go to SEC).
        return True

    async def fetch(
        self, ticker: str, requirement: Any, *, force_refresh: bool = False
    ) -> FundamentalsResult:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: _fetch_sync(ticker))


register(YFinanceFundamentalsSource())
