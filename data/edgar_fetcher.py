"""
SEC EDGAR fetcher — synchronous edgartools wrapper.

All functions are synchronous; call via asyncio.get_event_loop().run_in_executor()
from the async pipeline to avoid blocking the event loop.

Data hierarchy (zero LLM, zero paid APIs):
  SEC companyfacts.json  → 20yr+ fundamentals in ONE HTTP call (primary path,
                             see data/edgar_companyfacts.py)
  EDGAR 10-K / 10-Q      → per-filing XBRL fallback if companyfacts unavailable
  EDGAR Form 4           → insider transactions (50 most recent)
  EDGAR DEF 14A          → CEO ownership / founder status (HTML table parsing)
  EDGAR 10-K text        → customer concentration regex, founder regex
  EDGAR XBRL             → customer concentration (ConcentrationRiskPercentage1)
  yfinance               → price, ownership %, analyst coverage (separate module)

Performance gates:
  - Tier 0: data.models.schema.FinancialSourceLog records every parsed
    accession number. The companyfacts parser skips facts whose accn is in
    this set, so a warm-cache refresh emits ZERO new EdgarFinancialRows.
  - Tier 1: companyfacts JSON is cached 24h via data.cache.manager.CacheManager
    (key = edgar:companyfacts:{cik}). Two refreshes within 24h = 1 EDGAR call.

The data layer is fully deterministic. No Anthropic / OpenAI calls are made
anywhere in the screener / data-fetch path. AI usage is restricted to
deepdive/narrative.py (Phase 6).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from data.edgar_text_parser import (
    CustomerSignals,
    ProxyOwnership,
    parse_ceo_tenure,
    parse_customer_concentration,
    parse_is_founder_ceo,
    parse_proxy_ownership,
    parse_relationship_years,
)
from config.constants import DEFAULT_HISTORY_YEARS

logger = logging.getLogger(__name__)

# EDGAR identity — required by EDGAR fair-use policy (10 req/sec limit)
# Set once at module import; override via EDGAR_IDENTITY env var if needed.
_IDENTITY_SET = False


def _ensure_identity() -> None:
    global _IDENTITY_SET
    if _IDENTITY_SET:
        return
    from edgar import set_identity

    from config.settings import require_edgar_identity
    set_identity(require_edgar_identity())
    _IDENTITY_SET = True


# ── Data containers ───────────────────────────────────────────────────────


@dataclass
class EdgarFinancialRow:
    """One fiscal period of financial data parsed from 10-K / 10-Q XBRL."""
    ticker: str
    fiscal_year: int
    period: str                  # 'annual' | 'Q1' | 'Q2' | 'Q3' | 'Q4'
    source: str = "edgar"
    accession_number: str = ""
    # Canonical calendar time anchors (Phase 3a §12.1).
    # period_end_date is the AUTHORITATIVE anchor for cross-company ranking.
    period_end_date: date | None = None
    period_start_date: date | None = None
    filed_date: date | None = None

    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    gross_margin: float | None = None
    operating_income: float | None = None
    operating_expenses: float | None = None
    net_income: float | None = None
    ebitda: float | None = None
    rd_expense: float | None = None
    # Phase 5S-2: distinguishes "no R&D" from "R&D bundled into Other OpEx".
    # disclosed_exact = ResearchAndDevelopmentExpense tag present
    # bundled_in_opex = no R&D tag, but tax footnote claims R&D credit (HIMS pattern)
    # None            = no evidence either way (genuine data gap)
    rd_disclosure_state: str | None = None
    sga_expense: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    capex: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    long_term_debt: float | None = None
    cash_and_equivalents: float | None = None
    # Phase 5S-5: sum of AFS-current + AFS-noncurrent + plain ST investments.
    # Excess-capital parked in marketable securities; excluded from invested
    # capital and netted against debt in net_debt / Debt/EBITDA.
    short_term_investments: float | None = None
    accounts_receivable: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    inventory: float | None = None
    shares_outstanding: float | None = None
    eps_diluted: float | None = None
    eps_basic: float | None = None
    dividends_paid: float | None = None
    share_repurchases: float | None = None
    interest_expense: float | None = None
    income_tax_expense: float | None = None
    depreciation_amortization: float | None = None
    # Phase 5k / DEC-31 / 5k-5: float-related fields. funds_held_for_clients
    # is a balance-sheet item separate from cash_and_equivalents (most
    # filers keep them distinct; a few include in cash → handled in IC).
    # investment_income_interest is the float-interest revenue line; when
    # present and the ticker is a non-insurer, the ROIC numerator
    # subtracts it (Buffett-on-insurance-float treatment).
    funds_held_for_clients: float | None = None
    investment_income_interest: float | None = None
    # Phase 5R-1: data-quality signals. SBC critical for SaaS analysis
    # (dilution + cash-flow ex-SBC view); goodwill flags serial acquirers.
    share_based_compensation: float | None = None
    goodwill: float | None = None


@dataclass
class EdgarInsiderRow:
    """One Form 4 transaction parsed from EDGAR."""
    ticker: str
    filing_date: date
    transaction_date: date | None
    insider_name: str
    insider_title: str
    transaction_type: str        # 'P' purchase | 'S' sale | 'A' award
    shares: float
    price_per_share: float | None
    value_usd: float | None
    is_open_market: bool
    accession_number: str = ""


@dataclass
class EdgarFetchResult:
    ticker: str
    financials: list[EdgarFinancialRow] = field(default_factory=list)
    insider_transactions: list[EdgarInsiderRow] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    latest_10k_accession: str = ""


# ── Public entry points ───────────────────────────────────────────────────


def fetch_edgar_fundamentals(
    ticker: str,
    annual_years: int = DEFAULT_HISTORY_YEARS,
    quarterly_count: int = 10,
    skip_accessions: frozenset[str] | None = None,
    keep_only_years: frozenset[int] | None = None,
    fiscal_year_end_month: int = 12,
    *,
    bypass_cache: bool = False,
) -> EdgarFetchResult:
    """
    Fetch fundamentals for `ticker` via SEC's companyfacts.json bulk endpoint.

    Single HTTP call returns the company's full GAAP fact history; we trim to
    the last `annual_years` fiscal years before persisting (default 10 covers
    F7's max requirement — see frameworks/f7_smart_beta.py — and every other
    framework needs ≤5 years).

    Caller passes `skip_accessions` (Tier-0 cache) so we materialize only NEW
    rows. Falls back to per-filing XBRL parsing if companyfacts is unavailable
    (e.g. tiny / foreign filers without complete tagging).

    Override with `annual_years=20` for F7 deep-dive z-scores when you want
    extra long history.
    """
    from data.edgar_companyfacts import fetch_companyfacts, parse_companyfacts
    from data.cache.manager import CacheManager

    _ensure_identity()
    skip_accessions = skip_accessions or frozenset()
    result = EdgarFetchResult(ticker=ticker)

    # ── Resolve CIK once via edgartools (small, fast call after first-import) ──
    try:
        from edgar import Company
        company = Company(ticker)
        cik = int(getattr(company, "cik", 0) or 0)
    except Exception as exc:
        result.gaps.append(f"EDGAR: could not resolve company '{ticker}': {exc}")
        return result

    if cik == 0:
        result.gaps.append(f"EDGAR: CIK lookup failed for {ticker}")
        return result

    # ── Phase A+G: companyfacts bulk fetch (1 HTTP call, 24h cache) ──────────
    # bypass_cache=True (set by pipeline when force_refresh) skips the cache
    # lookup so a fresh dive always sees the latest SEC XBRL. The cache
    # TTL of 24h would otherwise hide a 10-Q filed within the last day —
    # which is exactly the scenario for an earnings-day dive.
    cache = CacheManager()
    cache_key = f"edgar:companyfacts:{cik}"
    payload = None if bypass_cache else cache.get(cache_key)
    if payload is None:
        from config.settings import require_edgar_identity
        payload = fetch_companyfacts(cik, require_edgar_identity())
        if payload:
            cache.set(cache_key, payload, ttl=86_400)

    if payload:
        rows = parse_companyfacts(
            ticker, payload, skip_accessions=skip_accessions,
            annual_years_limit=annual_years,
            keep_only_years=keep_only_years,
            fiscal_year_end_month=fiscal_year_end_month,
        )
        if rows:
            result.financials.extend(rows)
            # latest_10k_accession = the highest fiscal_year `annual` accession
            for row in rows:
                if row.period == "annual" and row.accession_number:
                    result.latest_10k_accession = row.accession_number
                    break
            return result

        # No new rows but companyfacts succeeded → fully warm cache.
        return result

    # ── Fallback: per-filing XBRL parse (covers companies with poor tagging) ──
    result.gaps.append(
        f"EDGAR companyfacts unavailable for CIK {cik}; falling back to per-filing XBRL"
    )

    try:
        annual_filings = company.get_filings(form="10-K").head(annual_years)
        for filing in annual_filings:
            accn = str(getattr(filing, "accession_number", "") or "")
            if accn and accn in skip_accessions:
                continue
            row = _parse_10k(ticker, filing)
            if row:
                result.financials.append(row)
                if not result.latest_10k_accession:
                    result.latest_10k_accession = row.accession_number
    except Exception as exc:
        result.gaps.append(f"EDGAR 10-K fallback: {exc}")

    try:
        quarterly_filings = company.get_filings(form="10-Q").head(quarterly_count)
        for filing in quarterly_filings:
            accn = str(getattr(filing, "accession_number", "") or "")
            if accn and accn in skip_accessions:
                continue
            row = _parse_10q(ticker, filing)
            if row:
                result.financials.append(row)
    except Exception as exc:
        result.gaps.append(f"EDGAR 10-Q fallback: {exc}")

    if not result.financials:
        result.gaps.append(f"EDGAR: no financial data parsed for {ticker}")

    return result


def fetch_edgar_insiders(ticker: str, limit: int = 50) -> list[EdgarInsiderRow]:
    """
    Fetch the most recent Form 4 insider transactions from EDGAR.

    50 covers F1's 90-day cluster window with margin (most companies file 5-15
    Form 4s/month; 50 ≈ 3-10 months of activity). Caller may raise the limit
    for richer history at the cost of more EDGAR roundtrips.
    Called synchronously; run in a thread pool from async pipeline.
    """
    _ensure_identity()
    rows: list[EdgarInsiderRow] = []

    try:
        from edgar import Company
        company = Company(ticker)
        form4_filings = company.get_filings(form="4").head(limit)

        for filing in form4_filings:
            try:
                form4 = filing.obj()
                parsed = _parse_form4(ticker, form4, filing)
                rows.extend(parsed)
            except Exception as exc:
                logger.debug("Form 4 parse error (%s): %s", ticker, exc)
    except Exception as exc:
        logger.warning("EDGAR Form 4 fetch failed (%s): %s", ticker, exc)

    return rows


# ── Internal parsers ──────────────────────────────────────────────────────


def _parse_10k(ticker: str, filing: Any) -> EdgarFinancialRow | None:
    """Parse one 10-K filing into an EdgarFinancialRow."""
    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            return None
        financials = xbrl.financials
        income = _df_to_dict(getattr(financials, "income_statement", None))
        balance = _df_to_dict(getattr(financials, "balance_sheet", None))
        cashflow = _df_to_dict(getattr(financials, "cash_flow_statement", None))

        year = _extract_fiscal_year(filing)
        revenue = _get(income, ["Revenues", "Revenue", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                  "RevenueFromContractWithCustomerIncludingAssessedTax"])
        cost_of_revenue = _get(income, ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostsAndExpenses"])
        gross_profit = _get(income, ["GrossProfit"])
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue
        operating_income = _get(income, ["OperatingIncomeLoss", "OperatingIncome"])
        operating_expenses = _get(income, ["OperatingExpenses", "CostsAndExpenses"])
        net_income = _get(income, ["NetIncomeLoss", "NetIncome"])
        rd_expense = _get(income, ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenses"])
        sga_expense = _get(income, ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"])
        interest_expense = _get(income, ["InterestExpense", "InterestAndDebtExpense", "InterestExpenseDebt"])
        income_tax_expense = _get(income, ["IncomeTaxExpenseBenefit", "IncomeTaxesPaid"])
        ebitda = _compute_ebitda(income, cashflow, operating_income)

        total_assets = _get(balance, ["Assets", "TotalAssets"])
        total_equity = _get(balance, ["StockholdersEquity", "TotalStockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
        long_term_debt = _get(balance, ["LongTermDebt", "LongTermDebtNoncurrent"])
        short_term_debt = _get(balance, ["ShortTermBorrowings", "LongTermDebtCurrent", "CurrentPortionOfLongTermDebt"]) or 0.0
        total_debt = (long_term_debt or 0.0) + (short_term_debt or 0.0) or None
        cash = _get(balance, ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"])
        current_assets = _get(balance, ["AssetsCurrent"])
        current_liabilities = _get(balance, ["LiabilitiesCurrent"])
        accounts_receivable = _get(balance, ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"])
        inventory = _get(balance, ["InventoryNet", "Inventory"])
        shares_outstanding = _get(balance, ["CommonStockSharesOutstanding"])

        operating_cf = _get(cashflow, ["NetCashProvidedByUsedInOperatingActivities", "NetCashFromOperatingActivities"])
        capex = _get(cashflow, ["PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures"])
        capex_abs = abs(capex) if capex is not None else None
        free_cash_flow = (operating_cf - capex_abs) if (operating_cf is not None and capex_abs is not None) else None
        dividends_paid = _get(cashflow, ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"])
        dividends_abs = abs(dividends_paid) if dividends_paid is not None else None
        share_repurchases = _get(cashflow, ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"])
        repurchases_abs = abs(share_repurchases) if share_repurchases is not None else None
        depreciation_amortization = _get(cashflow, ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"])

        eps_diluted = _get(income, ["EarningsPerShareDiluted", "IncomeLossFromContinuingOperationsPerDilutedShare"])
        eps_basic = _get(income, ["EarningsPerShareBasic"])
        gross_margin = (gross_profit / revenue) if (gross_profit is not None and revenue) else None

        accession = getattr(filing, "accession_number", "") or ""

        # Calendar time anchors (best-effort from filing metadata)
        period_end = _filing_date_attr(filing, "period_of_report") or _filing_date_attr(filing, "period_end")
        filed_date_val = _filing_date_attr(filing, "filing_date") or _filing_date_attr(filing, "date")

        return EdgarFinancialRow(
            ticker=ticker,
            fiscal_year=year,
            period="annual",
            accession_number=str(accession),
            period_end_date=period_end,
            filed_date=filed_date_val,
            revenue=revenue,
            cost_of_revenue=cost_of_revenue,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
            operating_income=operating_income,
            operating_expenses=operating_expenses,
            net_income=net_income,
            ebitda=ebitda,
            rd_expense=rd_expense,
            sga_expense=sga_expense,
            interest_expense=interest_expense,
            income_tax_expense=income_tax_expense,
            depreciation_amortization=depreciation_amortization,
            operating_cash_flow=operating_cf,
            free_cash_flow=free_cash_flow,
            capex=capex_abs,
            total_assets=total_assets,
            total_equity=total_equity,
            total_debt=total_debt,
            long_term_debt=long_term_debt,
            cash_and_equivalents=cash,
            accounts_receivable=accounts_receivable,
            current_assets=current_assets,
            current_liabilities=current_liabilities,
            inventory=inventory,
            shares_outstanding=shares_outstanding,
            eps_diluted=eps_diluted,
            eps_basic=eps_basic,
            dividends_paid=dividends_abs,
            share_repurchases=repurchases_abs,
        )
    except Exception as exc:
        logger.debug("10-K parse error (%s): %s", ticker, exc)
        return None


def _parse_10q(ticker: str, filing: Any) -> EdgarFinancialRow | None:
    """Parse one 10-Q filing into an EdgarFinancialRow (quarterly period)."""
    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            return None
        financials = xbrl.financials
        income = _df_to_dict(getattr(financials, "income_statement", None))
        balance = _df_to_dict(getattr(financials, "balance_sheet", None))
        cashflow = _df_to_dict(getattr(financials, "cash_flow_statement", None))

        year = _extract_fiscal_year(filing)
        quarter = _extract_quarter(filing)
        revenue = _get(income, ["Revenues", "Revenue", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                  "RevenueFromContractWithCustomerIncludingAssessedTax"])
        cost_of_revenue = _get(income, ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"])
        gross_profit = _get(income, ["GrossProfit"])
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue
        operating_income = _get(income, ["OperatingIncomeLoss"])
        operating_expenses = _get(income, ["OperatingExpenses"])
        net_income = _get(income, ["NetIncomeLoss"])
        rd_expense = _get(income, ["ResearchAndDevelopmentExpense"])
        operating_cf = _get(cashflow, ["NetCashProvidedByUsedInOperatingActivities"])
        capex = _get(cashflow, ["PaymentsToAcquirePropertyPlantAndEquipment"])
        capex_abs = abs(capex) if capex is not None else None
        free_cash_flow = (operating_cf - capex_abs) if (operating_cf is not None and capex_abs is not None) else None
        total_assets = _get(balance, ["Assets"])
        total_equity = _get(balance, ["StockholdersEquity", "TotalStockholdersEquity"])
        cash = _get(balance, ["CashAndCashEquivalentsAtCarryingValue"])
        accounts_receivable = _get(balance, ["AccountsReceivableNetCurrent"])
        current_assets = _get(balance, ["AssetsCurrent"])
        current_liabilities = _get(balance, ["LiabilitiesCurrent"])
        eps_diluted = _get(income, ["EarningsPerShareDiluted"])
        eps_basic = _get(income, ["EarningsPerShareBasic"])
        gross_margin = (gross_profit / revenue) if (gross_profit is not None and revenue) else None

        accession = getattr(filing, "accession_number", "") or ""

        period_end = _filing_date_attr(filing, "period_of_report") or _filing_date_attr(filing, "period_end")
        filed_date_val = _filing_date_attr(filing, "filing_date") or _filing_date_attr(filing, "date")

        return EdgarFinancialRow(
            ticker=ticker,
            fiscal_year=year,
            period=quarter,
            accession_number=str(accession),
            period_end_date=period_end,
            filed_date=filed_date_val,
            revenue=revenue,
            cost_of_revenue=cost_of_revenue,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
            operating_income=operating_income,
            operating_expenses=operating_expenses,
            net_income=net_income,
            rd_expense=rd_expense,
            operating_cash_flow=operating_cf,
            free_cash_flow=free_cash_flow,
            capex=capex_abs,
            total_assets=total_assets,
            total_equity=total_equity,
            cash_and_equivalents=cash,
            accounts_receivable=accounts_receivable,
            current_assets=current_assets,
            current_liabilities=current_liabilities,
            eps_diluted=eps_diluted,
            eps_basic=eps_basic,
        )
    except Exception as exc:
        logger.debug("10-Q parse error (%s): %s", ticker, exc)
        return None


def _parse_form4(ticker: str, form4: Any, filing: Any) -> list[EdgarInsiderRow]:
    """Parse one Form 4 filing into EdgarInsiderRow rows via Form4.to_dataframe().

    ADR-018 D5: the previous implementation read attributes that no longer
    exist on edgartools' Form4 (it tried `form4.transactions` and
    `form4.non_derivative_transactions`, both None on current edgartools).
    The replacement uses `Form4.to_dataframe()` which returns a structured
    DataFrame with columns:
      Transaction Type | Code | Description | Shares | Price | Value | Date |
      Form | Issuer | Ticker | Insider | Position | Remaining Shares

    `Code` carries the SEC Form-4 transaction code (P/S/A/M/F/G/D/X/J)
    that F1's "cluster buy" signal needs.

    Issuer filter (added 2026-05-15): a single Form-4 filing can carry
    transactions across MULTIPLE issuers when the filer is a 10%+ owner
    of more than one company (e.g. SHOP holds 10%+ of Klaviyo via
    Shopify Strategic Holdings 3 LLC, so SHOP's CIK accumulates Form-4s
    where Issuer='Klaviyo, Inc.' / Ticker='KVYO'). Persisting those
    against SHOP's ticker corrupts F1's open-market-buyer signal. We
    now drop any row whose `Ticker` column doesn't match the ticker
    we're fetching for. When the row's Ticker is empty/missing we fall
    back to matching `Issuer` against the filer's expected issuer name
    (best-effort; empty Ticker is rare).
    """
    rows: list[EdgarInsiderRow] = []
    try:
        filing_date_raw = getattr(filing, "filing_date", None) or getattr(filing, "date", None)
        filing_date_val: date
        if isinstance(filing_date_raw, str):
            from datetime import datetime as _dt
            filing_date_val = _dt.strptime(filing_date_raw[:10], "%Y-%m-%d").date()
        elif isinstance(filing_date_raw, date):
            filing_date_val = filing_date_raw
        else:
            return rows

        accession = str(getattr(filing, "accession_number", "") or "")
        # Top-level insider name from Form4 obj (more reliable than per-row)
        top_name = str(getattr(form4, "insider_name", "") or "")

        # Primary path: structured DataFrame
        try:
            df = form4.to_dataframe()
        except Exception as exc:
            logger.debug("Form4.to_dataframe() failed (%s): %s", ticker, exc)
            return rows

        if df is None or not hasattr(df, "iterrows") or len(df) == 0:
            return rows

        ticker_upper = ticker.upper().strip()
        for _, r in df.iterrows():
            try:
                # Issuer filter — drop transactions whose Issuer/Ticker
                # doesn't match the company we're fetching for. This
                # excludes Form-4s where the filer is a 10%+ owner of
                # a different company (SHOP-as-insider-of-KVYO pattern).
                row_ticker = str(r.get("Ticker") or "").strip().upper()
                if row_ticker and row_ticker != ticker_upper:
                    continue

                code = str(r.get("Code") or "").strip().upper()
                shares = _to_float(r.get("Shares"))
                price = _to_float(r.get("Price"))
                value = _to_float(r.get("Value"))
                if value is None and shares is not None and price:
                    value = shares * price
                txn_date = _to_date(r.get("Date"))
                insider_name = str(r.get("Insider") or top_name or "").strip()
                position = str(r.get("Position") or "").strip()

                # P (purchase) and S (sale) are open-market transactions in
                # the academic insider-buy literature. M (option exercise),
                # F (tax withholding), A (award), G (gift), D (disposition)
                # are non-open-market.
                is_open_market = code in ("P", "S")

                rows.append(EdgarInsiderRow(
                    ticker=ticker,
                    filing_date=filing_date_val,
                    transaction_date=txn_date,
                    insider_name=insider_name,
                    insider_title=position,
                    transaction_type=code,
                    shares=shares or 0.0,
                    price_per_share=price,
                    value_usd=value,
                    is_open_market=is_open_market,
                    accession_number=accession,
                ))
            except Exception as exc:
                logger.debug("Form 4 row parse error: %s", exc)
    except Exception as exc:
        logger.debug("Form 4 outer parse error (%s): %s", ticker, exc)
    return rows


def _to_float(v: Any) -> float | None:
    """Convert a Form 4 numeric cell (NaN / None / pandas value) to float."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:    # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _to_date(v: Any) -> date | None:
    """Convert a Form 4 date cell (Timestamp / datetime / str / date) → date.

    NOTE: order matters — datetime is-a date in Python (datetime inherits
    from date), so we MUST check datetime first. Otherwise we pass through
    a datetime object that downstream code stringifies with the time
    component and writes wrong values into the DB Date column.
    """
    if v is None:
        return None
    from datetime import datetime as _dt
    if hasattr(v, "to_pydatetime"):    # pandas Timestamp — most common
        try:
            return v.to_pydatetime().date()
        except Exception:
            return None
    if isinstance(v, _dt):              # plain datetime
        return v.date()
    if isinstance(v, date):             # plain date (must come AFTER datetime)
        return v
    if isinstance(v, str):
        try:
            return _dt.strptime(v[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None
    return None


# ── XBRL helpers ──────────────────────────────────────────────────────────


def _df_to_dict(df: Any) -> dict[str, float]:
    """Convert an edgartools XBRL DataFrame/Series to a flat {concept: value} dict."""
    if df is None:
        return {}
    try:
        import pandas as pd
        if isinstance(df, pd.DataFrame):
            # edgartools returns index=concept, columns=periods; take most recent column
            col = df.columns[0] if len(df.columns) else None
            if col is not None:
                return {str(k): float(v) for k, v in df[col].items() if v is not None and str(v) != "nan"}
        elif isinstance(df, pd.Series):
            return {str(k): float(v) for k, v in df.items() if v is not None and str(v) != "nan"}
        elif isinstance(df, dict):
            return {str(k): float(v) for k, v in df.items() if v is not None}
    except Exception as exc:
        logger.debug("_df_to_dict error: %s", exc)
    return {}


def _get(data: dict[str, float], keys: list[str]) -> float | None:
    """Return first matching key from XBRL concept dict, or None."""
    for key in keys:
        val = data.get(key)
        if val is not None:
            return val
    return None


def _compute_ebitda(
    income: dict[str, float],
    cashflow: dict[str, float],
    operating_income: float | None,
) -> float | None:
    ebitda = _get(income, ["EarningsBeforeInterestTaxesDepreciationAndAmortization", "EBITDA"])
    if ebitda is not None:
        return ebitda
    da = _get(cashflow, ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"])
    if operating_income is not None and da is not None:
        return operating_income + da
    return None


def _extract_fiscal_year(filing: Any) -> int:
    for attr in ("period_of_report", "period", "fiscal_year"):
        val = getattr(filing, attr, None)
        if val:
            s = str(val)[:4]
            if s.isdigit():
                return int(s)
    return 0


# ── F6 signal extraction (deterministic — XBRL → text regex → HTML) ───────


def fetch_sec_industry_classification(ticker: str) -> dict[str, Any] | None:
    """Return SEC SIC-based industry classification for a ticker.

    Returns a dict with keys:
      - sic_code     (int)    e.g. 8011
      - sic_description (str) e.g. "Services-Offices & Clinics of Doctors of Medicine"
      - is_foreign   (bool)   filing as foreign private issuer right now
      - filer_category (str)  e.g. "Large accelerated filer"
      - is_smaller_reporting_company (bool)
      - is_financial_institution (bool)
      - is_fund (bool)

    SIC classification is the SEC-canonical industry assignment, set by the
    issuer at registration. yfinance.info.industry uses a different
    proprietary taxonomy and can diverge materially (e.g. HIMS yfinance
    "Software - Application" vs SEC SIC 8011 "Offices & Clinics of Doctors
    of Medicine" — the SIC is correct; HIMS is a telehealth company).

    Returns None on lookup failure. Caller decides whether SEC should
    override yfinance (recommended for industry per user 2026-05-15) or
    just supplement.
    """
    _ensure_identity()
    try:
        from edgar import Company
        co = Company(ticker)
        d = co.data
        return {
            "sic_code": getattr(d, "sic", None),
            "sic_description": getattr(d, "sic_description", None),
            "is_foreign": bool(getattr(co, "is_foreign", False)),
            "filer_category": str(getattr(co, "filer_category", "")) or None,
            "is_smaller_reporting_company": bool(
                getattr(co, "is_smaller_reporting_company", False)
            ),
            "is_financial_institution": bool(
                co.is_financial_institution()
                if callable(getattr(co, "is_financial_institution", None))
                else False
            ),
            "is_fund": bool(
                co.is_fund()
                if callable(getattr(co, "is_fund", None))
                else False
            ),
            "business_category": str(getattr(co, "business_category", "")) or None,
        }
    except Exception as exc:
        logger.debug("SEC industry lookup failed (%s): %s", ticker, exc)
        return None


def fetch_sec_exchange(ticker: str) -> str | None:
    """Return SEC-canonical exchange listing for a ticker.

    Uses `edgartools.Company.get_exchanges()` which reads
    `submissions.json:exchanges` (Tier 1B). When a filer is cross-listed,
    returns the primary (first) exchange — typically the registered US
    primary listing.

    Examples:
      NVDA → "Nasdaq"
      SHOP → "NYSE" (despite TSX co-listing — SEC tracks US primary)
      ASML → "Nasdaq" (ADR on US exchange)

    Returns None on lookup failure. Caller falls back to yfinance per
    ADR-033 §1.3 SEC-first invariant.
    """
    _ensure_identity()
    try:
        from edgar import Company
        co = Company(ticker)
        exchanges = co.get_exchanges()
        if not exchanges:
            return None
        return exchanges[0] if isinstance(exchanges, list) else str(exchanges)
    except Exception as exc:
        logger.debug("SEC exchange lookup failed (%s): %s", ticker, exc)
        return None


def fetch_latest_ceo_sc13d(ticker: str, ceo_name: str) -> Any | None:
    """Fetch the most-recent SC 13D / 13D/A filing on `ticker`'s CIK where
    the Reporting Person matches `ceo_name` (last-name token).

    Returns the matching edgartools Filing object or None when:
      - No SC 13D/A filings exist on the issuer's CIK (CEO is below
        5% threshold), or
      - All existing 13D/A filings are by other parties (VC firms,
        founder trusts) — the LULU/INTA/ADBE pattern.

    This is the PRIMARY source for CEO equity when applicable. Per
    ADR-031 §1.2 + §4.3, the verbatim quote from Row 13 of the cover
    page is the SEC-Rule-13d-3 beneficial ownership %; F5's Fahlenbrach
    5% threshold consumes exactly this number.

    Strict-RP-match is mandatory: returning a non-CEO 13D's %
    would silently corrupt the F5 founder_aligned signal (HIMS
    investigation 2026-05-15 §3).
    """
    if not ceo_name:
        return None
    _ensure_identity()
    try:
        from edgar import Company
        company = Company(ticker)
        # Pull both forms; SC 13D/A (amendments) supersede the original
        sca = list(company.get_filings(form="SC 13D/A").head(8))
        sc = list(company.get_filings(form="SC 13D").head(8))
        # Sort all by filing_date descending — amendments naturally newer
        candidates = sorted(
            sca + sc,
            key=lambda f: str(getattr(f, "filing_date", "0")),
            reverse=True,
        )
    except Exception as exc:
        logger.debug("SC 13D probe failed (%s): %s", ticker, exc)
        return None

    if not candidates:
        return None

    from data.edgar_text_parser import parse_sc13d_ownership
    for filing in candidates:
        try:
            html = filing.html()
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="ignore")
            if not html:
                continue
            ownership = parse_sc13d_ownership(html, ceo_name_hint=ceo_name)
            if ownership.matches_ceo and ownership.percent_of_class is not None:
                # Cache the ownership snapshot on the filing object so the
                # caller doesn't have to re-fetch + re-parse
                filing._parsed_ownership = ownership  # type: ignore[attr-defined]
                return filing
        except Exception as exc:
            logger.debug("SC 13D parse failed (%s, %s): %s",
                         ticker, getattr(filing, "accession_no", "?"), exc)
            continue
    return None


def fetch_latest_10k_filing(ticker: str) -> Any | None:
    """
    Fetch the latest 10-K filing object once, to be shared across F6 helpers
    (customer concentration + founder regex). Returns None if unavailable.
    """
    _ensure_identity()
    try:
        from edgar import Company
        company = Company(ticker)
        filings = company.get_filings(form="10-K").head(1)
        for filing in filings:
            return filing
    except Exception as exc:
        logger.warning("fetch_latest_10k_filing failed (%s): %s", ticker, exc)
    return None


def fetch_latest_10q_filing(ticker: str) -> Any | None:
    """ADR-026 / Phase 5Q: Most-recent 10-Q filing object.

    Quarterly equivalent of fetch_latest_10k_filing(). Used by the
    retention regex (5Q-4) and Cloud-ARR regex (5Q-5) to read the
    freshest MD&A narrative, since these SaaS-specific disclosures
    refresh quarterly. Returns None when no 10-Q exists (rare —
    typically only for very recent IPOs that haven't filed a 10-Q yet).
    """
    _ensure_identity()
    try:
        from edgar import Company
        company = Company(ticker)
        filings = company.get_filings(form="10-Q").head(1)
        for filing in filings:
            return filing
    except Exception as exc:
        logger.warning("fetch_latest_10q_filing failed (%s): %s", ticker, exc)
    return None


def fetch_edgar_patent_disclosure(
    ticker: str,
    filing: Any | None = None,
    tenk: Any | None = None,
):
    """5k-6 (partial): extract patent count from 10-K narrative.

    Fallback path while waiting on USPTO API key (5k-6b). Reuses the
    customer-concentration TenK section reader. Returns
    ``PatentSignals(state='not_disclosed')`` on absence — most non-tech /
    non-biotech companies don't quantify portfolio size in 10-K, which is
    a 0pt outcome (no penalty), not a parser failure.
    """
    from data.edgar_text_parser import PatentSignals, parse_patent_count
    if tenk is None:
        if filing is None:
            filing = fetch_latest_10k_filing(ticker)
        if filing is None:
            return PatentSignals(state="not_disclosed")
        try:
            tenk = filing.obj() if hasattr(filing, "obj") else filing
        except Exception:
            tenk = filing
    try:
        sections = _read_tenk_sections(tenk)
        if sections:
            combined = "\n\n".join(sections.values())
            return parse_patent_count(combined)
    except Exception as exc:
        logger.warning(
            "fetch_edgar_patent_disclosure failed (%s): %s", ticker, exc,
        )
    return PatentSignals(state="not_disclosed")


def fetch_edgar_arr_metrics(ticker: str):
    """ADR-026 / 5Q-5: extract Cloud ARR + Total ARR from latest 10-K/10-Q.

    Same freshness-wins logic as `fetch_edgar_retention_metrics()`:
    pulls latest 10-K and latest 10-Q, parses both, returns the
    freshest disclosure (10-Q in normal cases, since SaaS companies
    update ARR quarterly). Returns ARRSignals(state='not_disclosed')
    when neither filing has an ARR mention with a parseable value.
    """
    from data.edgar_text_parser import ARRSignals, parse_arr_metrics

    def _parse(f: Any):
        if f is None:
            return ARRSignals(state="not_disclosed"), None
        try:
            obj = f.obj() if hasattr(f, "obj") else f
        except Exception:
            obj = f
        form_type = getattr(f, "form", None) or ""
        if "10-Q" in str(form_type):
            sections = _read_tenq_sections(obj)
        else:
            sections = _read_tenk_sections(obj)
        if not sections:
            return ARRSignals(state="not_disclosed"), None
        combined = "\n\n".join(sections.values())
        result = parse_arr_metrics(combined)
        filed_date = getattr(f, "filing_date", None) or getattr(f, "filed", None)
        return result, filed_date

    try:
        tenk = fetch_latest_10k_filing(ticker)
    except Exception as exc:
        logger.warning("ARR: 10-K fetch failed for %s: %s", ticker, exc)
        tenk = None
    try:
        tenq = fetch_latest_10q_filing(ticker)
    except Exception as exc:
        logger.warning("ARR: 10-Q fetch failed for %s: %s", ticker, exc)
        tenq = None

    annual_result, annual_date = _parse(tenk) if tenk else (ARRSignals(state="not_disclosed"), None)
    quarterly_result, quarterly_date = _parse(tenq) if tenq else (ARRSignals(state="not_disclosed"), None)

    annual_has = annual_result.state == "disclosed_exact"
    quarterly_has = quarterly_result.state == "disclosed_exact"
    if quarterly_has and annual_has:
        if quarterly_date and annual_date and quarterly_date > annual_date:
            return quarterly_result
        return quarterly_result    # prefer 10-Q by default
    if quarterly_has:
        return quarterly_result
    if annual_has:
        return annual_result
    if quarterly_result.state == "parser_uncertain":
        return quarterly_result
    return annual_result


def fetch_edgar_retention_metrics(
    ticker: str,
    filing: Any | None = None,
    tenk: Any | None = None,
):
    """5k-7 / ADR-026 5Q-4: extract NRR / GRR from latest filing's MD&A.

    Reads BOTH the latest 10-K and latest 10-Q, parses each, and returns
    the freshest disclosure (by filing date). For SaaS-heavy holdings
    NRR/GRR refresh quarterly — relying on the 10-K alone leaves data
    stale by 6-11 months. ADR-026 reframes the parser fleet to
    "freshest disclosure wins".

    Returns ``RetentionSignals(state='not_disclosed')`` when neither
    filing has a parseable disclosure.
    """
    from data.edgar_text_parser import RetentionSignals, parse_retention_metrics

    def _parse_filing(f: Any) -> tuple[RetentionSignals, Any]:
        """Return (parsed result, filing-date or None) for one filing."""
        if f is None:
            return RetentionSignals(state="not_disclosed"), None
        try:
            obj = f.obj() if hasattr(f, "obj") else f
        except Exception:
            obj = f
        # Choose the section reader by form type
        form_type = getattr(f, "form", None) or ""
        if "10-Q" in str(form_type):
            sections = _read_tenq_sections(obj)
        else:
            sections = _read_tenk_sections(obj)
        if not sections:
            return RetentionSignals(state="not_disclosed"), None
        combined = "\n\n".join(sections.values())
        result = parse_retention_metrics(combined)
        filed_date = getattr(f, "filing_date", None) or getattr(f, "filed", None)
        return result, filed_date

    # Allow callers to pass an already-fetched 10-K via the legacy
    # `filing`/`tenk` keyword args (existing customer-concentration
    # callsite). When supplied we still cross-check the latest 10-Q.
    annual_filing = filing
    if annual_filing is None and tenk is None:
        try:
            annual_filing = fetch_latest_10k_filing(ticker)
        except Exception as exc:
            logger.warning("retention: 10-K fetch failed for %s: %s", ticker, exc)
            annual_filing = None
    try:
        quarterly_filing = fetch_latest_10q_filing(ticker)
    except Exception as exc:
        logger.warning("retention: 10-Q fetch failed for %s: %s", ticker, exc)
        quarterly_filing = None

    try:
        annual_result, annual_date = _parse_filing(annual_filing) if annual_filing else (
            RetentionSignals(state="not_disclosed"), None
        )
        quarterly_result, quarterly_date = _parse_filing(quarterly_filing) if quarterly_filing else (
            RetentionSignals(state="not_disclosed"), None
        )
    except Exception as exc:
        logger.warning("fetch_edgar_retention_metrics failed (%s): %s", ticker, exc)
        return RetentionSignals(state="not_disclosed")

    # Choose the freshest filing that has an actual disclosure.
    annual_has_value = annual_result.state == "disclosed_exact"
    quarterly_has_value = quarterly_result.state == "disclosed_exact"

    if quarterly_has_value and annual_has_value:
        # Both disclosed — pick by filing date.
        if quarterly_date and annual_date and quarterly_date > annual_date:
            return quarterly_result
        if quarterly_date and not annual_date:
            return quarterly_result
        # Default tie-breaker: prefer 10-Q (always more recent than annual
        # in normal calendar terms — annual filed once/yr vs quarterly 3x).
        return quarterly_result
    if quarterly_has_value:
        return quarterly_result
    if annual_has_value:
        return annual_result
    # Neither had a clean disclosure — return whichever had a phrase match
    # (parser_uncertain takes precedence over not_disclosed for signal).
    if quarterly_result.state == "parser_uncertain":
        return quarterly_result
    return annual_result


def fetch_edgar_customer_concentration(
    ticker: str,
    filing: Any | None = None,
    tenk: Any | None = None,
) -> CustomerSignals:
    """
    ADR-018 D4 — resolve revenue + receivables customer concentration.

    Priority chain (deterministic, zero LLM):
      1. XBRL concept ConcentrationRiskPercentage1 — when filer tags it
      2. Regex on TenK[Item 1, 1A, 7, 8] section text (validated v6
         pattern set; 7/7 in ADR-018 §6.2 corpus). Uses the new edgartools
         section accessors with legacy fallback (`tk["part_ii_item_8"]`
         then `tk["Item 8"]`) since accessor names drift across filings.
      3. Return CustomerSignals(state='not_disclosed') on absence

    Caller may pass `tenk` (a TenK object) to share the latest 10-K fetch
    with other branches in the dive (e.g. founder regex). When `filing`
    is supplied we still derive a TenK from it for backward compat.
    """
    if tenk is None:
        if filing is None:
            filing = fetch_latest_10k_filing(ticker)
        if filing is None:
            return CustomerSignals(state="not_disclosed")
        # filing may BE a TenK or a Filing — try to obtain TenK
        try:
            tenk = filing.obj() if hasattr(filing, "obj") else filing
        except Exception:
            tenk = filing

    try:
        # ── Strategy 1: XBRL structured concept ─────────────────────────
        # _xbrl_concentration_lookup uses Filing.xbrl(), so pass a filing
        # if we have one (TenK doesn't expose .xbrl directly).
        if filing is not None:
            xbrl_signal = _xbrl_concentration_lookup(filing)
            if xbrl_signal is not None:
                return CustomerSignals(
                    concentration_pct=xbrl_signal,
                    relationship_years=_extract_relationship_from_filing(filing),
                    extraction_method="xbrl",
                    state="disclosed_exact",
                )

        # ── Strategy 2: Targeted-section regex ───────────────────────────
        sections = _read_tenk_sections(tenk)
        if sections:
            combined = "\n\n".join(sections.values())
            return parse_customer_concentration(combined)
    except Exception as exc:
        logger.warning("fetch_edgar_customer_concentration failed (%s): %s", ticker, exc)

    return CustomerSignals(state="not_disclosed")


def _read_tenq_sections(tenq: Any) -> dict[str, str]:
    """ADR-026: 10-Q section reader, parallel to _read_tenk_sections().

    10-Q structure:
      Part I:
        Item 1 — Financial Statements (condensed)
        Item 2 — Management's Discussion and Analysis (MD&A — the prize)
        Item 3 — Quantitative and Qualitative Disclosures about Market Risk
        Item 4 — Controls and Procedures
      Part II:
        Item 1, 1A — Legal Proceedings, Risk Factors
        Item 2-6 — Various

    For Phase 5Q retention + ARR extraction we primarily need Part I
    Item 2 (MD&A). Other sections are loaded for completeness so future
    regex passes (guidance changes, risk factor deltas) can use the
    same fetch.
    """
    if tenq is None:
        return {}
    sections: dict[str, str] = {}
    keymap = [
        # Part I — financials + MD&A
        ("Item 1",     "part_i_item_1"),
        ("Item 2",     "part_i_item_2"),
        ("Item 3",     "part_i_item_3"),
        ("Item 4",     "part_i_item_4"),
        # Part II — legal / risk-factor updates
        ("Item 1A",    "part_ii_item_1a"),
    ]
    for legacy_key, new_key in keymap:
        text = None
        for key in (new_key, legacy_key):
            try:
                v = tenq[key]
                if isinstance(v, str) and v:
                    text = v
                    break
            except Exception:
                continue
        if text:
            sections[legacy_key] = text
    return sections


def _read_tenk_sections(tenk: Any) -> dict[str, str]:
    """ADR-018 D4 — read Item 1 + 1A + 7 + 8 with new/legacy key fallback.

    edgartools uses two key conventions across filings:
      - new:    tk["part_ii_item_8"]
      - legacy: tk["Item 8"]
    Try new first; fall back to legacy when new returns None / KeyError.
    """
    if tenk is None:
        return {}
    sections: dict[str, str] = {}
    keymap = [
        ("Item 1",  "part_i_item_1"),
        ("Item 1A", "part_i_item_1a"),
        ("Item 7",  "part_ii_item_7"),
        ("Item 8",  "part_ii_item_8"),
    ]
    for legacy_key, new_key in keymap:
        text = None
        for key in (new_key, legacy_key):
            try:
                v = tenk[key]
                if isinstance(v, str) and v:
                    text = v
                    break
            except Exception:
                continue
        if text:
            sections[legacy_key] = text
    return sections


def fetch_edgar_proxy_ownership(
    ticker: str,
    latest_10k: Any | None = None,
    ceo_name_hint: str | None = None,
    company: Any | None = None,
) -> ProxyOwnership:
    """
    Resolve F6 CEO equity + founder status signals via edgartools' STRUCTURED
    DEF 14A access (ADR-018 D2).

    Replaces the legacy BeautifulSoup HTML-table regex parser with
    edgartools' `Company.proxy_season(0).proxy.beneficial_ownership` — a
    typed DataFrame with columns `holder_name | holder_type | shares |
    percent_of_class`. Cross-references `proxy.peo_name` (Principal
    Executive Officer = CEO, often last-name-only) against
    `beneficial_ownership.holder_name` to identify the CEO row, then
    reads `percent_of_class`.

    Three-state output (`result.state`):
      - 'disclosed_exact': single-class issuer; PEO matched a row in
        beneficial_ownership; percent_of_class read.
      - 'parser_uncertain': multi-class issuer (deferred to v2 per
        ADR-018 §6.3) OR PEO didn't match any holder within fuzzy
        threshold OR proxy season unavailable.
      - 'not_disclosed': proxy fetched but contains no beneficial
        ownership table (extremely rare; procedural anomaly).
      - 'none': proxy season fetch failed entirely (network / 404).

    `company` may be a shared `edgar.Company(ticker)` instance — see
    ADR-018 trace open Q #1 (avoiding redundant submissions.json fetches
    across Branches B/D/E).
    """
    result = ProxyOwnership()
    if ceo_name_hint:
        result.ceo_name = ceo_name_hint
        result.extraction_method = "yfinance"

    _ensure_identity()
    try:
        if company is None:
            from edgar import Company as _EdgarCompany
            company = _EdgarCompany(ticker)
    except Exception as exc:
        logger.warning("proxy_ownership: Company(%s) failed: %s", ticker, exc)
        result.state = "none"
        return result

    # ── Structured DEF 14A via edgartools.proxy_season ───────────────────
    proxy = None
    try:
        ps = company.proxy_season(index=0)
        proxy = getattr(ps, "proxy", None) if ps is not None else None
    except Exception as exc:
        logger.debug("proxy_season(0) failed for %s: %s", ticker, exc)

    if proxy is not None:
        # PEO name (often last-name-only with non-breaking spaces — clean it)
        peo_raw = getattr(proxy, "peo_name", None) or ""
        peo_clean = _normalize_peo_name(peo_raw)
        if peo_clean and not result.ceo_name:
            result.ceo_name = peo_clean

        # PEO total compensation (DEF 14A Summary Compensation Table "Total" row).
        # Phase 2.2 migration (audit §B.2) — Tier 1A SEC source replaces
        # yfinance.info "totalPay" which is scraped and stale.
        peo_total = getattr(proxy, "peo_total_comp", None)
        if peo_total is not None:
            try:
                result.ceo_total_pay = float(peo_total)
            except (TypeError, ValueError):
                pass

        # beneficial_ownership DataFrame access
        bo = None
        try:
            bo = proxy.beneficial_ownership
        except Exception as exc:
            logger.debug("beneficial_ownership unavailable for %s: %s", ticker, exc)

        if bo is not None and len(bo) > 0:
            # Detect edgartools' "<1%" sentinel: when many director_officer
            # rows carry the *same* small value of percent_of_class, that
            # value is a placeholder for "less than 1%" (real values vary
            # by holder; the sentinel does not). Used to flag CEO rows
            # whose true equity is "<1%" as parser_uncertain rather than
            # mis-reporting the sentinel as the actual percentage.
            sub_one_sentinel = _detect_sub_one_sentinel(bo)

            ceo_row, multi_class, fuzzy_matched = _find_ceo_row(
                bo, peo_clean or result.ceo_name
            )
            result.multi_class_detected = multi_class
            if ceo_row is not None:
                pct = _read_pct_of_class(ceo_row)
                if pct is not None:
                    is_sentinel = (
                        sub_one_sentinel is not None
                        and abs(pct - sub_one_sentinel) < 0.01
                    )
                    result.ceo_equity_pct = pct
                    result.extraction_method = "structured_xbrl"
                    if is_sentinel:
                        # CEO ownership is <1% per disclosure; the value
                        # itself is a placeholder. Record but flag.
                        result.state = "parser_uncertain"
                    elif multi_class:
                        result.state = "parser_uncertain"
                    else:
                        result.state = "disclosed_exact"
                # If CEO row found but no pct, keep state="none" so caller knows
                if not result.ceo_name:
                    result.ceo_name = str(ceo_row.get("holder_name") or "") or None
            else:
                # PEO exists but no holder row matched. Flag uncertain.
                if peo_clean:
                    result.state = "parser_uncertain"
                else:
                    result.state = "not_disclosed"
        else:
            # ADR-018-fix: edgartools' structured XBRL parser sometimes
            # returns an empty DataFrame even when the DEF 14A contains a
            # well-formed beneficial-ownership table (e.g. PAYC). Fall
            # back to the legacy BeautifulSoup HTML-table parser before
            # giving up.
            try:
                html = _safe_html(proxy.filing) if hasattr(proxy, "filing") else ""
                if html:
                    html_signal = parse_proxy_ownership(
                        html, ceo_name_hint=peo_clean or result.ceo_name,
                    )
                    if html_signal.ceo_equity_pct is not None:
                        result.ceo_equity_pct = html_signal.ceo_equity_pct
                        result.extraction_method = "html_table_fallback"
                        result.state = "disclosed_exact"
                        if html_signal.ceo_name and not result.ceo_name:
                            result.ceo_name = html_signal.ceo_name
                    else:
                        # Genuinely no ownership table found
                        result.state = "not_disclosed"
                else:
                    result.state = "not_disclosed"
            except Exception as exc:
                logger.debug("HTML-fallback proxy parse failed (%s): %s", ticker, exc)
                result.state = "not_disclosed"

        # Founder + tenure regex on proxy text — proximity-scoped to CEO name
        # (otherwise board-member bios with their own external founder roles
        # produce false positives, as seen on AAPL's proxy).
        try:
            proxy_text = _safe_text(proxy.filing) if hasattr(proxy, "filing") else ""
            if proxy_text:
                if result.is_founder_ceo is None:
                    result.is_founder_ceo = parse_is_founder_ceo(
                        proxy_text, ceo_name=result.ceo_name,
                    )
                if result.ceo_tenure_years is None:
                    result.ceo_tenure_years = parse_ceo_tenure(proxy_text)
        except Exception as exc:
            logger.debug("proxy text regex failed for %s: %s", ticker, exc)

    # Founder fallback: regex on the latest 10-K business section, also
    # proximity-scoped to the CEO's name.
    if result.is_founder_ceo is None and latest_10k is not None:
        try:
            text = _safe_text(latest_10k)
            if text:
                result.is_founder_ceo = parse_is_founder_ceo(
                    text, ceo_name=result.ceo_name,
                )
        except Exception as exc:
            logger.debug("10-K founder parse failed (%s): %s", ticker, exc)

    # ── Canadian FPI MIC TERTIARY fallback for ceo_equity_pct ───────────────
    #
    # When DEF 14A produces nothing (typical for Canadian Foreign Private
    # Issuers like SHOP, BB, CSU pre-domestic-filer conversion), check the
    # most recent 6-K for a Management Information Circular attachment.
    # The MIC is the Canadian equivalent of a US DEF 14A's beneficial
    # ownership table — same data, different jurisdiction.
    #
    # See ADR-025 (IFRS / FPI universe support) + ADR-031 §1.2 D-category
    # for the rationale. The MIC parser was built 2026-05-15 during the
    # SHOP investigation and shipped as parse_mic_ownership(); this is
    # the pipeline integration that ADR-031 §8 marked deferred.
    if result.ceo_equity_pct is None and result.ceo_name:
        try:
            from data.edgar_text_parser import parse_mic_ownership
            from edgar import Company as _EdgarCo
            co = _EdgarCo(ticker)
            # Probe last 30 6-K filings for circular attachments. MICs file
            # annually around AGM (typically April/May for SHOP, BB, etc.)
            # so we need depth to span at least one year of 6-Ks.
            six_ks = list(co.get_filings(form="6-K").head(30))
            mic_extracted = False
            for f in six_ks:
                if mic_extracted:
                    break
                # Collect ALL matching attachments (a single filing may have
                # both a SEC cover form named *circular*.htm AND the actual
                # MIC text as EX-99.1 *mic*.htm). Try them in size-desc
                # order — the actual MIC is materially larger than the
                # cover form.
                matching = []
                for a in f.attachments:
                    doc = (getattr(a, "document", "") or "").lower()
                    if "circular" in doc or "mic" in doc:
                        if doc.endswith(".htm") or doc.endswith(".html"):
                            matching.append(a)
                if not matching:
                    continue
                # Read all matching attachments, sort by length descending,
                # try the largest first
                payload: list[tuple[int, str, Any]] = []
                for a in matching:
                    try:
                        raw = a.content
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="ignore")
                        if raw:
                            payload.append((len(raw), raw, a))
                    except Exception:
                        continue
                payload.sort(reverse=True)
                for size, raw, a in payload:
                    if size < 50_000:
                        continue   # cover form — skip
                    mic = parse_mic_ownership(raw, ceo_name_hint=result.ceo_name)
                    if (
                        mic.ceo_equity_pct is not None
                        and mic.state == "disclosed_exact"
                        and mic.ceo_equity_pct > 0
                    ):
                        logger.info(
                            "MIC fallback for %s: extracted %.2f%% from "
                            "6-K %s (%s, attachment %s)",
                            ticker, mic.ceo_equity_pct,
                            getattr(f, "accession_no", "?"),
                            getattr(f, "filing_date", "?"),
                            getattr(a, "document", "?"),
                        )
                        result.ceo_equity_pct = mic.ceo_equity_pct
                        result.extraction_method = "canadian_mic_6k"
                        result.state = "disclosed_exact"
                        result.multi_class_detected = mic.multi_class_detected
                        mic_extracted = True
                        break
        except Exception as exc:
            logger.debug("MIC fallback failed for %s: %s", ticker, exc)

    # ── SC 13D / 13D/A PRIMARY OVERRIDE for ceo_equity_pct ──────────────────
    #
    # When the CEO is a 5%+ beneficial owner of their company, they must
    # file SC 13D under SEC Rule 13d-3. The 13D's Item 5 / cover-page
    # Row 13 is the AUTHORITATIVE figure — it states beneficial ownership
    # under a uniform, regulator-defined methodology (treating derivatives
    # as if exercised). DEF 14A's "% of Class" column uses varying
    # conventions (strict-class vs as-if-converted, blank vs `*` for
    # under-1%, voting-power vs economic) — see HIMS investigation
    # 2026-05-15 where DEF 14A produced 87.73% (voting) when the
    # economic number was 11.1% per Dudum's SC 13D/A.
    #
    # We override only when:
    #   a) ceo_name is known (we need to match the reporting person)
    #   b) An SC 13D/A exists where the reporting person matches the
    #      CEO's last name (strict match — prevents Hill Investors /
    #      Shopify-as-10%-owner mistakes)
    #
    # When override fires, result.extraction_method becomes
    # "sec_sc13d_cover" and result.state stays/becomes "disclosed_exact".
    # When no matching SC 13D exists (the common case below 5%), the
    # DEF 14A result is kept untouched.
    if result.ceo_name:
        try:
            sc13d_filing = fetch_latest_ceo_sc13d(ticker, result.ceo_name)
        except Exception as exc:
            logger.debug("SC 13D probe failed for %s: %s", ticker, exc)
            sc13d_filing = None
        if sc13d_filing is not None:
            ownership = getattr(sc13d_filing, "_parsed_ownership", None)
            if (
                ownership is not None
                and ownership.matches_ceo
                and ownership.percent_of_class is not None
                and ownership.percent_of_class > 0
            ):
                logger.info(
                    "SC 13D override for %s: DEF 14A produced %s; SC 13D "
                    "(%s, %s) produces %.2f%% — using SC 13D as primary",
                    ticker, result.ceo_equity_pct,
                    getattr(sc13d_filing, "accession_no", "?"),
                    getattr(sc13d_filing, "filing_date", "?"),
                    ownership.percent_of_class,
                )
                result.ceo_equity_pct = ownership.percent_of_class
                result.extraction_method = "sec_sc13d_cover"
                result.state = "disclosed_exact"
                # Multi-class indicator stays set if DEF 14A flagged it —
                # this is informational; the 13D number already accounts
                # for the as-if-converted basis.

    return result


def _normalize_peo_name(raw: str) -> str | None:
    """Clean edgartools' peo_name string.

    edgartools returns values like 'Mr.\\xa0Hall' — non-breaking space + last
    name only. Normalise whitespace and strip honorifics so the result can
    fuzzy-match against the beneficial_ownership.holder_name column.
    """
    if not raw:
        return None
    import re
    # Replace non-breaking spaces and similar with regular space
    s = raw.replace(" ", " ").replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Strip leading honorific
    s = re.sub(r"^(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.)\s+", "", s, flags=re.I)
    return s or None


def _find_ceo_row(bo: Any, ceo_name: str | None) -> tuple[Any, bool, bool]:
    """Find the CEO row in a beneficial_ownership DataFrame.

    Returns (row | None, multi_class_detected: bool, fuzzy_matched: bool).
    `multi_class_detected` is True when the table has more than one
    distinct value of percent_of_class column unit (e.g. Class A vs Class
    B). For v1 this triggers parser_uncertain per ADR-018 §6.3.
    """
    multi_class = False
    fuzzy_matched = False
    try:
        # Detect multi-class: edgartools may add a 'class' or 'security_class'
        # column when multiple share classes are reported. If absent, assume
        # single-class (the common case).
        class_cols = [c for c in bo.columns if str(c).lower() in
                      ("class", "security_class", "share_class", "title_of_class")]
        if class_cols:
            distinct = bo[class_cols[0]].dropna().unique()
            if len(distinct) > 1:
                multi_class = True
    except Exception:
        pass

    if not ceo_name:
        return None, multi_class, fuzzy_matched

    # Try exact match first, then last-name fuzzy match
    last_name = ceo_name.split()[-1].lower() if ceo_name else ""
    full_lower = ceo_name.lower()
    try:
        for _, row in bo.iterrows():
            holder = str(row.get("holder_name") or "").lower()
            if not holder:
                continue
            if full_lower in holder or holder in full_lower:
                return row, multi_class, False
        # Fuzzy: match by last name
        for _, row in bo.iterrows():
            holder = str(row.get("holder_name") or "").lower()
            if last_name and last_name in holder:
                return row, multi_class, True
    except Exception:
        pass
    return None, multi_class, False


def _read_pct_of_class(row: Any) -> float | None:
    """Read the percent_of_class value from a beneficial_ownership row.

    edgartools normalises percentages to the 0-100 scale (i.e. 7.64 means
    7.64%, not 0.0764). NEVER apply a 0-1→0-100 multiplier here — that
    bug previously turned AAPL's "<1%" sentinel value 0.50 into 50%.
    """
    for key in ("percent_of_class", "percent", "pct_of_class", "%"):
        try:
            v = row.get(key) if hasattr(row, "get") else row[key]
        except Exception:
            continue
        if v is None:
            continue
        try:
            f = float(v)
            if 0 < f <= 100:
                return f
        except (TypeError, ValueError):
            continue
    return None


def _detect_sub_one_sentinel(bo: Any) -> float | None:
    """Detect edgartools' "<1%" sentinel value in the beneficial_ownership table.

    Returns the sentinel value when at least 5 director_officer rows
    share the same percent_of_class value AND that value is <= 1.0.
    Otherwise returns None (no sentinel; values are real).
    """
    try:
        from collections import Counter
        # Filter to director_officer rows only — 5%-holders are real values
        df = bo
        if hasattr(df, "iterrows"):
            counts: Counter[float] = Counter()
            for _, row in df.iterrows():
                holder_type = str(row.get("holder_type") or "").lower()
                if "director" not in holder_type and "officer" not in holder_type:
                    continue
                pct = _read_pct_of_class(row)
                if pct is None or pct > 1.0:
                    continue
                counts[round(pct, 2)] += 1
            if not counts:
                return None
            most_common, count = counts.most_common(1)[0]
            if count >= 5:
                return most_common
    except Exception:
        return None
    return None


# ── Filing text/HTML access helpers ───────────────────────────────────────


def _safe_text(filing: Any) -> str:
    """Extract plain text from an EDGAR filing; tolerant of edgartools API drift."""
    for attr in ("text", "filing_text"):
        try:
            val = getattr(filing, attr, None)
            if callable(val):
                val = val()
            if isinstance(val, str) and val.strip():
                return val
        except Exception:
            continue
    try:
        doc = getattr(filing, "document", None)
        if doc is not None:
            txt = getattr(doc, "text", None)
            if callable(txt):
                txt = txt()
            if isinstance(txt, str):
                return txt
    except Exception:
        pass
    return ""


def _safe_html(filing: Any) -> str:
    """Extract raw HTML from an EDGAR filing."""
    for attr in ("html", "filing_html"):
        try:
            val = getattr(filing, attr, None)
            if callable(val):
                val = val()
            if isinstance(val, str) and val.strip():
                return val
        except Exception:
            continue
    try:
        doc = getattr(filing, "document", None)
        if doc is not None:
            html = getattr(doc, "html", None)
            if callable(html):
                html = html()
            if isinstance(html, str):
                return html
    except Exception:
        pass
    return ""


def _xbrl_concentration_lookup(filing: Any) -> float | None:
    """Look up `ConcentrationRiskPercentage1` (or aliases) from filing XBRL facts."""
    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            return None
        facts = getattr(xbrl, "facts", None)
        if facts is None:
            return None
        for concept in ("ConcentrationRiskPercentage1", "ConcentrationRiskPercentage"):
            series = getattr(facts, concept, None)
            if series is None:
                continue
            try:
                import pandas as pd
                val: float | None = None
                if isinstance(series, (pd.DataFrame, pd.Series)):
                    first = series.iloc[0] if hasattr(series, "iloc") else None
                    val = float(first) if first is not None else None
                if val is not None:
                    # XBRL stores as 0–1 ratio; convert to 0–100%
                    return val * 100.0 if val < 1.0 else val
            except Exception:
                continue
    except Exception as exc:
        logger.debug("XBRL concentration lookup error: %s", exc)
    return None


def _extract_relationship_from_filing(filing: Any) -> float | None:
    text = _safe_text(filing)
    return parse_relationship_years(text) if text else None


def _filing_date_attr(filing: Any, attr: str) -> date | None:
    """Extract a date-like attribute from a filing, normalising str/date inputs."""
    val = getattr(filing, attr, None)
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(val[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
    return None


def _extract_quarter(filing: Any) -> str:
    """Best-effort quarter extraction from filing metadata."""
    for attr in ("period_of_report", "period"):
        val = getattr(filing, attr, None)
        if val:
            s = str(val)
            if len(s) >= 7:
                month = int(s[5:7]) if s[5:7].isdigit() else 0
                if month in (1, 2, 3):
                    return "Q1"
                elif month in (4, 5, 6):
                    return "Q2"
                elif month in (7, 8, 9):
                    return "Q3"
                elif month in (10, 11, 12):
                    return "Q4"
    return "Q?"
