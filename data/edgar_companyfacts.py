"""
SEC EDGAR companyfacts.json bulk fetcher — single-call alternative to per-filing
XBRL parsing. One ~5-10MB HTTP request returns 20+ years of GAAP facts.

  https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json

This is the high-leverage replacement for fetch_edgar_fundamentals' per-filing
xbrl() loop. It eliminates 40+ network roundtrips and 40+ pandas XBRL parses
into a single JSON GET that we cache for 24h.

Data integrity invariants (do NOT relax):
  1. Form-type whitelist: only 10-K/10-Q/20-F/40-F and their /A amendments.
     Other forms (8-K, S-1, DEF 14A) may carry incidental tagged facts that
     don't represent fiscal-period reporting and would corrupt our schema.
  2. Period derivation is **period_end-authoritative**: fiscal_year and
     period are derived from the entry's `end` date plus the company's
     fiscal-year-end month. SEC's `fy`/`fp` fields are the *filing's*
     fiscal year, not the period's — using them caused the INTA FY2022 /
     FY2023 duplicate-label bug. End-year convention: FY = calendar year
     in which the period ends.
  3. Restatement handling: for each derived (fy, period) we keep the bucket
     whose accession has the latest `filed` date — the most-recent restated
     value.
  4. Period-span selection: 10-Qs report both YTD-cumulative AND
     just-the-period values for flow concepts. We pick the entry with the
     shortest start-end span — the just-the-period value (3 months for
     Q1/Q2/Q3, ~365 days for FY).
  5. Unit selection: explicit per-concept (USD for monetary, shares for share
     counts, USD/shares for per-share metrics). Never auto-pick.
  6. Missing concepts: return None on the row. We do NOT impute or estimate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from data.edgar_fetcher import EdgarFinancialRow

logger = logging.getLogger(__name__)


# Forms that report fiscal-period fundamentals.
# Amendments (/A) supersede prior filings via restatement handling below.
_FUNDAMENTAL_FORMS: frozenset[str] = frozenset({
    "10-K", "10-K/A",
    "10-Q", "10-Q/A",
    "20-F", "20-F/A",      # foreign private issuers — annual
    "40-F", "40-F/A",      # Canadian filers — annual
})


# Concept aliases preserved verbatim from edgar_fetcher._parse_10k.
# Order matters: first-match wins per concept.
# Bump when the concept chains or period derivation change: filings logged
# under an older version are then re-read once (data/pipeline.py coverage gate).
PARSER_VERSION = 2

_INCOME_CONCEPTS: list[tuple[str, list[str]]] = [
    ("revenue", [
        "Revenues",
        "Revenue",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ]),
    ("cost_of_revenue", [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ]),
    ("gross_profit", ["GrossProfit"]),
    ("operating_income", ["OperatingIncomeLoss", "OperatingIncome"]),
    ("operating_expenses", ["OperatingExpenses", "CostsAndExpenses"]),
    ("net_income", ["NetIncomeLoss", "NetIncome"]),
    # Phase 5k-9: fallback fields for filers that don't tag OperatingIncomeLoss
    # directly (e.g. ADP). Used to derive operating_income at row-build time:
    #   operating_income = pretax_income - nonoperating_income_expense.
    # Aggregate before geo-split — `Domestic + Foreign` variant is captured if
    # the Extraordinary aggregate isn't present.
    ("pretax_income", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ]),
    ("pretax_income_domestic", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
    ]),
    ("pretax_income_foreign", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign",
    ]),
    ("nonoperating_income_expense", [
        "NonoperatingIncomeExpense",
    ]),
    ("rd_expense", [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenses",
    ]),
    # Phase 5S-2: R&D activity signal from the tax footnote. Used to
    # detect "bundled_in_opex" disclosure pattern (HIMS-style filers
    # that conduct R&D but never tag it as a separate income-statement
    # line). When `rd_expense` is None but this signal is present, the
    # filer is doing R&D — it's just buried in "Operations & Support"
    # or "Other OpEx" and not separable from XBRL alone. Set as
    # rd_disclosure_state = "bundled_in_opex" downstream. The value
    # itself is NOT used for F3 scoring (it's the annual R&D tax credit
    # in USD, not R&D opex — different magnitude and meaning).
    ("rd_tax_credits_signal", [
        "IncomeTaxReconciliationTaxCreditsResearch",
    ]),
    ("sga_expense", [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ]),
    ("interest_expense", [
        "InterestExpense",
        "InterestAndDebtExpense",
        "InterestExpenseDebt",
    ]),
    ("income_tax_expense", ["IncomeTaxExpenseBenefit", "IncomeTaxesPaid"]),
    ("ebitda_direct", [
        "EarningsBeforeInterestTaxesDepreciationAndAmortization",
        "EBITDA",
    ]),
    ("eps_diluted", [
        "EarningsPerShareDiluted",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
    ]),
    ("eps_basic", ["EarningsPerShareBasic"]),
]

_BALANCE_CONCEPTS: list[tuple[str, list[str]]] = [
    ("total_assets", ["Assets", "TotalAssets"]),
    ("total_equity", [
        "StockholdersEquity",
        "TotalStockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ]),
    # long_term_debt: prefer aggregate concepts first (LongTermDebt /
    # LongTermDebtNoncurrent often roll up the company's whole debt stack);
    # fall back to specific instrument concepts ONLY when no aggregate is
    # present. Order matters — first non-None wins, so the aggregate slot
    # prevents double-counting when an issuer reports both the aggregate
    # AND its components. Specific-instrument fallbacks added per the
    # HIMS case (ConvertibleDebtNoncurrent — $972.58M FY2025 — was being
    # silently dropped, leaving total_debt = operating-lease only).
    ("long_term_debt", [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligationsAndOtherLongTermDebt",
        "ConvertibleDebtNoncurrent",
        "SeniorNotesNoncurrent",
        "SeniorLongTermNotes",
        "NotesPayableNoncurrent",
        "LongTermNotesPayable",
        "LongTermLineOfCredit",
        "SecuredDebtNoncurrent",
        "UnsecuredDebtNoncurrent",
        "FinanceLeaseLiabilityNoncurrent",
        "CapitalLeaseObligationsNoncurrent",
    ]),
    ("short_term_debt", [
        "ShortTermBorrowings",
        "DebtCurrent",
        "LongTermDebtCurrent",
        "CurrentPortionOfLongTermDebt",
        "ConvertibleDebtCurrent",
        "SeniorNotesCurrent",
        "NotesPayableCurrent",
        "LinesOfCredit",
        "LinesOfCreditCurrent",
        "SecuredDebtCurrent",
        "UnsecuredDebtCurrent",
        "FinanceLeaseLiabilityCurrent",
        "CapitalLeaseObligationsCurrent",
    ]),
    # ASC 842 operating-lease liabilities (post-2019). yfinance includes
    # these in `totalDebt`. We capture them as transient parser fields and
    # roll them into `total_debt` at materialisation time so F5 Debt/EBITDA
    # and ICA invested-capital reflect total interest-bearing obligations.
    # Not persisted as separate Financial columns — only the rolled-up
    # `total_debt` is.
    ("operating_lease_lt", [
        "OperatingLeaseLiabilityNoncurrent",
        "OperatingLeaseLiabilitiesNoncurrent",
    ]),
    ("operating_lease_st", [
        "OperatingLeaseLiabilityCurrent",
        "OperatingLeaseLiabilitiesCurrent",
    ]),
    ("cash_and_equivalents", [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashAndCashEquivalents",
    ]),
    # Phase 5S-5: marketable securities / short-term investments — held by
    # cash-rich filers as excess-capital parking (T-bills, commercial paper,
    # AFS debt securities). Captured as two separate components — current
    # and noncurrent — then summed at materialise time into
    # `short_term_investments`. Excluded from invested capital and netted
    # against debt for the net-debt calculation. Carefully NOT mapped from
    # `LongTermInvestments` (too broad — can include strategic equity
    # stakes) or `EquitySecuritiesFvNi*` (equity, not debt securities).
    # HIMS FY2025: $349M current + $351M noncurrent = $700M total.
    # NVDA FY2026: ~$32B across both buckets.
    ("short_term_investments_current", [
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
    ]),
    ("short_term_investments_noncurrent", [
        "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
    ]),
    # Aggregate alternative — some filers (notably NVDA FY2026+) report the
    # total AFS portfolio without splitting current vs noncurrent. When the
    # aggregate is present, prefer it over summing the split fields (avoids
    # ambiguity when one of the split fields is reported but not the other).
    ("short_term_investments_aggregate", [
        "AvailableForSaleSecuritiesDebtSecurities",
        "MarketableSecurities",
    ]),
    # Phase 5k / DEC-31 / task 5k-5: float-related concepts. Captured for
    # transparency on payroll/payments/insurance tickers and used to detect
    # whether IC denominator already excludes client funds. Two flavours of
    # source tag — `FundsHeldForClients` is most specific (PAYC-style),
    # `RestrictedCashAndCashEquivalents` is a more general fallback (ADP).
    ("funds_held_for_clients", [
        "FundsHeldForClients",
        "RestrictedCashAndCashEquivalents",
    ]),
    # Float interest income — when present and a non-insurer reports this
    # within operating revenue/income, ROIC numerator gets contaminated.
    # Subtracting at NOPAT-derivation time gives the clean operating ROIC.
    ("investment_income_interest", [
        "InvestmentIncomeInterest",
        "InterestIncomeOperating",
    ]),
    # Phase 5R-1: Share-Based Compensation. Critical SaaS data-quality
    # signal — SBC as % of revenue. Per ADR-021 we do NOT add SBC back to
    # operating income for ROIC (rejected as management non-GAAP). But the
    # absolute SBC magnitude IS a meaningful signal: dilution rate,
    # capital-allocator discipline, "real" cash flow ex-SBC.
    ("share_based_compensation", [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
        "StockBasedCompensation",
    ]),
    # Goodwill — needed to surface concentration (goodwill / total_assets)
    # for serial acquirers. Per DEC-31 goodwill stays in IC via total_equity
    # (Stewart standard); 5R-1 just surfaces the value as a flag, doesn't
    # change IC math.
    ("goodwill", [
        "Goodwill",
    ]),
    ("accounts_receivable", [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ]),
    ("current_assets", ["AssetsCurrent"]),
    ("current_liabilities", ["LiabilitiesCurrent"]),
    ("inventory", ["InventoryNet", "Inventory"]),
    # Point-in-time end-of-period share count is preferred (F1 L7 dilution
    # check is YoY-comparable). When the issuer doesn't tag the point-in-time
    # concept (some SaaS / consumer-tech filers don't — HIMS) we fall back
    # to weighted-average basic shares from the income statement, which
    # under-reports end-of-period by the in-period issuance pattern but is
    # still YoY-comparable. Diluted is the last-resort fallback.
    ("shares_outstanding", [
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ]),
]

_CASHFLOW_CONCEPTS: list[tuple[str, list[str]]] = [
    ("operating_cash_flow", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashFromOperatingActivities",
    ]),
    ("capex", [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",       # NVDA FY2021+ uses this tag
        "CapitalExpenditures",
    ]),
    ("dividends_paid", [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ]),
    ("share_repurchases", [
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ]),
    ("depreciation_amortization", [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ]),
]

# Default unit is USD (monetary). Override per-concept where required.
_NON_USD_UNITS: dict[str, str] = {
    "shares_outstanding": "shares",
    "eps_diluted": "USD/shares",
    "eps_basic": "USD/shares",
}

# Phase 5S-3: fields filed YTD-only in 10-Qs.
#
# SEC XBRL convention: cash-flow-statement concepts (and a few non-cash
# adjustments that live in the cash-flow reconciliation block) are reported
# as cumulative-from-fiscal-year-start in each 10-Q — never as discrete
# three-month values. Concretely, for NVDA FY2026:
#   Q1 10-Q:  start=2025-01-27  end=2025-04-27  ( 90d) val=$27,414M
#   Q2 10-Q:  start=2025-01-27  end=2025-07-27  (181d) val=$42,779M   (Q1+Q2)
#   Q3 10-Q:  start=2025-01-27  end=2025-10-26  (272d) val=$66,530M   (Q1+Q2+Q3)
#   10-K:     start=2025-01-27  end=2026-01-25  (363d) val=$102,718M  (FY)
#
# Income-statement concepts (revenue, net income, etc.) are filed at BOTH
# 90-day discrete AND YTD durations, so the shortest-span resolution in
# `_ingest` keeps the discrete value. Cash-flow concepts have no discrete
# alternative — they must be DIFFERENCED post-ingest:
#   Q2_discrete = Q2_YTD − Q1_YTD
#   Q3_discrete = Q3_YTD − Q2_YTD
#   Q4_discrete = FY     − Q3_YTD     (Q4 is implicit, never filed standalone)
#
# Before the 5S-3 fix the parser's span>200 filter silently dropped the
# 9-month Q3 YTD entries, zeroing every Q3 cash-flow value across every
# ticker. Q2 also stored the 6-month YTD as if it were discrete Q2.
# See _difference_ytd_quarters() for the differencing pass.
_CUMULATIVE_QUARTERLY_FIELDS: frozenset[str] = frozenset({
    "operating_cash_flow",
    "capex",
    "dividends_paid",
    "share_repurchases",
    "depreciation_amortization",
    "share_based_compensation",
})

_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


@dataclass
class _FilingFacts:
    """Internal accumulator for one (accession, derived_fy, derived_period) bucket.

    `fiscal_year` / `period` are DERIVED from the entry's period_end + the
    company's fiscal-year-end month — never from SEC's `fy`/`fp` fields,
    which are the *filing's* year (caused INTA FY2022/FY2023 dup-label bug).
    """
    accession_number: str
    fiscal_year: int
    period: str
    form: str
    filed: str
    fields: dict[str, float]
    spans: dict[str, int | None]    # field_name → start-end span days
    # Canonical calendar time anchors — captured from the entry whose value
    # was kept (i.e. shortest span), so end_date matches the value's period.
    period_end_str: str | None = None      # 'YYYY-MM-DD'
    period_start_str: str | None = None


# ── Public API ───────────────────────────────────────────────────────────


def fetch_latest_filings(
    cik: int,
    identity: str,
    forms: frozenset[str] = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F"}),
    limit: int = 5,
) -> list[dict[str, str]]:
    """
    Cheap probe to SEC submissions.json (~50-200KB) — returns the most recent
    filings (default: last 5 annual reports) so the pipeline can decide whether
    a fresh companyfacts fetch is needed.

    Returned entries have keys: accession_number, form, filing_date, report_date.
    Empty list on 404 / network error (caller treats as "unknown — fetch anyway").
    """
    from data.api._retry import sec_get_with_retry
    url = _SUBMISSIONS_URL.format(cik=cik)
    headers = {
        "User-Agent": identity,
        "Accept-Encoding": "gzip",
        "Host": "data.sec.gov",
    }
    resp = sec_get_with_retry(
        url, headers=headers, timeout=15.0, label="sec_submissions_probe",
    )
    if resp is None or resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except (ValueError, KeyError) as exc:
        logger.warning("submissions probe parse failed for CIK %d: %s", cik, exc)
        return []

    recent = (data.get("filings") or {}).get("recent") or {}
    accns = recent.get("accessionNumber") or []
    forms_list = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []

    rows: list[dict[str, str]] = []
    for i, form in enumerate(forms_list):
        if form not in forms:
            continue
        rows.append({
            "accession_number": str(accns[i]) if i < len(accns) else "",
            "form": str(form),
            "filing_date": str(filing_dates[i]) if i < len(filing_dates) else "",
            "report_date": str(report_dates[i]) if i < len(report_dates) else "",
        })
        if len(rows) >= limit:
            break
    return rows


def fetch_filer_metadata(cik: int, identity: str) -> dict[str, Any] | None:
    """
    Fetch filer-level metadata from SEC submissions.json — small (~50-200KB)
    GET that returns name, exchanges, fiscal year-end (e.g. "0630" for June 30
    year-end), former names, and recent filings.

    Returns a dict with stable, normalized keys so callers don't have to deal
    with SEC's inconsistent casing:
      - cik (int)
      - name (str | None)
      - tickers (list[str])
      - exchanges (list[str])
      - fiscal_year_end (str | None)         e.g. "0630" — raw SEC value
      - fiscal_year_end_month (int | None)   e.g. 6 — derived; 1-12 or None
      - sic (str | None)
      - sic_description (str | None)

    Returns None on 404 / network failure.
    """
    from data.api._retry import sec_get_with_retry
    url = _SUBMISSIONS_URL.format(cik=cik)
    headers = {
        "User-Agent": identity,
        "Accept-Encoding": "gzip",
        "Host": "data.sec.gov",
    }
    resp = sec_get_with_retry(
        url, headers=headers, timeout=15.0, label="sec_filer_metadata",
    )
    if resp is None or resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except (ValueError, KeyError) as exc:
        logger.warning("submissions metadata parse failed for CIK %d: %s", cik, exc)
        return None

    fy_end_raw = data.get("fiscalYearEnd") or None
    fy_end_month: int | None = None
    if isinstance(fy_end_raw, str) and len(fy_end_raw) == 4 and fy_end_raw.isdigit():
        try:
            month_val = int(fy_end_raw[:2])
            if 1 <= month_val <= 12:
                fy_end_month = month_val
        except ValueError:
            pass

    return {
        "cik": cik,
        "name": data.get("name") or None,
        "tickers": list(data.get("tickers") or []),
        "exchanges": list(data.get("exchanges") or []),
        "fiscal_year_end": fy_end_raw,
        "fiscal_year_end_month": fy_end_month,
        "sic": data.get("sic") or None,
        "sic_description": data.get("sicDescription") or None,
    }


def fetch_companyfacts(cik: int, identity: str) -> dict[str, Any] | None:
    """
    Single GET to SEC's companyfacts endpoint. Returns the parsed JSON or
    None on 404 / network error. Caller handles caching.
    """
    from data.api._retry import sec_get_with_retry
    url = _BASE_URL.format(cik=cik)
    headers = {
        "User-Agent": identity,
        "Accept-Encoding": "gzip",
        "Host": "data.sec.gov",
    }
    resp = sec_get_with_retry(
        url, headers=headers, timeout=30.0, label="sec_companyfacts",
    )
    if resp is None:
        return None
    if resp.status_code == 404:
        logger.info("companyfacts: 404 for CIK %d (no XBRL facts on file)", cik)
        return None
    if resp.status_code != 200:
        logger.warning(
            "companyfacts fetch failed for CIK %d: status=%d", cik, resp.status_code,
        )
        return None
    try:
        return resp.json()
    except ValueError as exc:
        logger.warning("companyfacts parse failed for CIK %d: %s", cik, exc)
        return None


# Below this fraction of the cover-page count, a share figure is a units error,
# not a share class. Multi-class filers tagging only one class still land far
# above 1%; a value reported in millions lands at 1e-6.
_SHARE_SCALE_FLOOR = 0.01


def dei_share_anchors(payload: dict[str, Any] | None) -> dict[int, float]:
    """Cover-page shares outstanding per fiscal year, from the dei namespace.

    `dei:EntityCommonStockSharesOutstanding` is required on the cover of every
    10-K and is SEC-validated as an absolute count, which makes it a reliable
    scale reference. The us-gaap concepts are not: McDonald's tags
    WeightedAverageNumberOfSharesOutstandingBasic as 713.4, i.e. in millions.
    """
    if not payload:
        return {}
    entries = (
        payload.get("facts", {})
        .get("dei", {})
        .get("EntityCommonStockSharesOutstanding", {})
        .get("units", {})
        .get("shares", [])
    )
    best: dict[int, tuple[str, float]] = {}
    for e in entries:
        fy, val, filed = e.get("fy"), e.get("val"), e.get("filed") or ""
        if e.get("fp") != "FY" or not isinstance(fy, int) or not val:
            continue
        if not str(e.get("form", "")).replace("-", "").upper().startswith("10K"):
            continue
        prior = best.get(fy)
        if prior is None or filed > prior[0]:
            best[fy] = (filed, float(val))
    return {fy: v for fy, (_filed, v) in best.items()}


def repair_share_scale(shares: float | None, anchor: float | None) -> float | None:
    """The anchor when `shares` is implausibly small against it, else None.

    Returns None to mean "no repair needed" so the caller can distinguish a
    corrected value from an untouched one and log accordingly.
    """
    if not shares or not anchor or shares <= 0 or anchor <= 0:
        return None
    if shares < anchor * _SHARE_SCALE_FLOOR:
        return anchor
    return None


def parse_companyfacts(
    ticker: str,
    payload: dict[str, Any] | None,
    skip_accessions: frozenset[str] = frozenset(),
    annual_years_limit: int | None = 10,
    keep_only_years: frozenset[int] | None = None,
    fiscal_year_end_month: int = 12,
) -> list[EdgarFinancialRow]:
    """
    Materialize EdgarFinancialRow per fiscal period from the companyfacts JSON.

    Period derivation is **period_end-authoritative**: every entry's
    fiscal_year and period are derived from its `end` date plus the company's
    fiscal-year-end month — NOT from SEC's `fy`/`fp` fields, which carry the
    *filing's* year (a 10-K filed in CY2025 reporting FYE June 2025 also
    carries fy=2025 on its FY2024 prior-period comparatives, which produced
    INTA's FY2022/FY2023 duplicate-label bug).

    Pass `fiscal_year_end_month` (1-12) — defaults to 12 (December year-end).
    Caller must persist Company.fiscal_year_end_month and pass it here.

    Process:
      1. Iterate facts.us-gaap.{concept}.units.{unit}.[entries]
      2. Filter to fundamental forms; drop entries whose accession is in
         skip_accessions (Tier-0 source-log gate)
      3. Derive (fiscal_year, period) from entry.end + FYEM (end-year
         convention). Skip entries whose end-date isn't a fiscal-period
         boundary (intra-period snapshots).
      4. Group by (accn, derived_fy, derived_period); for each field, prefer
         the shortest start-end span (just-the-period value, not YTD).
      5. Resolve restatements: for each (derived_fy, derived_period), keep
         the bucket whose accn has the latest `filed` date.
      6. Materialize EdgarFinancialRow per (fy, period) with derived fields
         (gross_profit fallback, total_debt = LT+ST, FCF = OCF-|CapEx|,
         EBITDA fallback = OI + D&A).
      7. Trim to the most recent `annual_years_limit` fiscal years (default
         10 — F7's max requirement; pass None to keep full history).
      8. If `keep_only_years` is provided, materialize only rows whose
         fiscal_year is in that set. Used by the pipeline's coverage gate to
         avoid re-parsing fiscal years we already have in the Financial
         table.
    """
    if not payload:
        return []
    facts = payload.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    if not us_gaap:
        return []

    by_filing: dict[tuple[str, int, str], _FilingFacts] = {}

    def _ingest(concept_name: str, field_name: str, unit_key: str) -> None:
        concept = us_gaap.get(concept_name)
        if not concept:
            return
        units = concept.get("units", {})
        entries = units.get(unit_key, [])
        for entry in entries:
            form = entry.get("form")
            if form not in _FUNDAMENTAL_FORMS:
                continue
            accn = entry.get("accn") or ""
            if not accn or accn in skip_accessions:
                continue
            entry_end = entry.get("end")
            entry_start = entry.get("start")
            if not entry_end:
                continue
            end_date = _parse_iso(entry_end)
            if end_date is None:
                continue
            start_date = _parse_iso(entry_start) if entry_start else None
            derived = _derive_fiscal_period(end_date, start_date, fiscal_year_end_month)
            if derived is None:
                # Entry's end isn't a fiscal-period boundary — skip.
                continue
            fy, period = derived
            val_raw = entry.get("val")
            if val_raw is None:
                continue
            try:
                val = float(val_raw)
            except (TypeError, ValueError):
                continue
            if val != val:    # NaN check
                continue
            span = _span_days(entry_start, entry_end)

            # For annual flow concepts, only keep entries whose span is
            # roughly a year (350-380 days). Prevents quarterly-YTD leakage
            # into annual buckets.
            if period == "annual" and span is not None and span < 350:
                continue
            # For quarterly flow concepts (where start is given), only keep
            # entries whose span is plausibly quarterly (≤200 days). This
            # filters multi-quarter YTD entries that would otherwise pollute
            # individual Q1/Q2/Q3 buckets — EXCEPT for cumulative-only
            # cash-flow fields (5S-3), where the YTD entry is the ONLY
            # entry filed. Those are kept here as raw YTD and differenced
            # later in _difference_ytd_quarters().
            if (
                period in ("Q1", "Q2", "Q3")
                and span is not None
                and span > 200
                and field_name not in _CUMULATIVE_QUARTERLY_FIELDS
            ):
                continue

            key = (accn, fy, period)
            bucket = by_filing.get(key)
            if bucket is None:
                bucket = _FilingFacts(
                    accession_number=accn,
                    fiscal_year=fy,
                    period=period,
                    form=str(form),
                    filed=str(entry.get("filed", "") or ""),
                    fields={},
                    spans={},
                )
                by_filing[key] = bucket

            existing_val = bucket.fields.get(field_name)
            existing_span = bucket.spans.get(field_name)

            # Span resolution: prefer shorter span (just-the-period, not YTD).
            # When we replace the kept value, also capture its calendar window
            # — the bucket's period_end/start strings should match the value
            # we ended up keeping for the canonical / longest concept (revenue).
            if existing_val is None:
                bucket.fields[field_name] = val
                bucket.spans[field_name] = span
                # Anchor period_end to the FIRST concept that gives us an end
                # date (typically revenue). This is the canonical calendar
                # window for the (fy, period) bucket.
                if bucket.period_end_str is None and entry_end:
                    bucket.period_end_str = entry_end
                    bucket.period_start_str = entry_start
                continue
            if span is None:
                continue
            if existing_span is None or span < existing_span:
                bucket.fields[field_name] = val
                bucket.spans[field_name] = span
                # Re-anchor calendar window to the better-spanned entry
                if entry_end:
                    bucket.period_end_str = entry_end
                    bucket.period_start_str = entry_start

    # Walk all concept groups in priority order.
    for groups in (_INCOME_CONCEPTS, _BALANCE_CONCEPTS, _CASHFLOW_CONCEPTS):
        for field_name, aliases in groups:
            unit = _NON_USD_UNITS.get(field_name, "USD")
            for alias in aliases:
                _ingest(alias, field_name, unit)

    # Restatement resolution — FIELD-LEVEL merge, not bucket-level.
    #
    # A given (fy, period) is reported by multiple filings:
    #   - the primary 10-K for that fiscal year (full income/balance/cashflow)
    #   - more recent 10-Ks via prior-period comparatives
    #   - more recent 10-Qs via prior-FY-end balance sheet (sparse — usually
    #     ONLY the balance sheet, no income/cashflow)
    #
    # Naive bucket-level "latest filed wins" causes a 10-Q's sparse bucket
    # to displace the original 10-K's complete bucket — see INTA FY2024,
    # whose income/CF data was nuked by the FY2026 Q2 10-Q's prior-FY
    # balance-sheet snapshot. Per-field provenance is the fix:
    #   - For each field: keep the value from the latest-filed bucket that
    #     reported that specific field with a non-None value.
    #   - Never let a None override an existing non-None.
    #   - Anchor period_end/start to the bucket whose `revenue` field won
    #     (so the calendar window reflects the income statement, not a
    #     prior-FY balance-sheet snapshot).
    by_period: dict[tuple[int, str], _FilingFacts] = {}
    field_filed: dict[tuple[int, str, str], str] = {}    # (fy, period, field) → filed
    period_end_filed: dict[tuple[int, str], str] = {}    # (fy, period) → filed of revenue winner

    for bucket in by_filing.values():
        period_key = (bucket.fiscal_year, bucket.period)
        existing = by_period.get(period_key)
        if existing is None:
            existing = _FilingFacts(
                accession_number=bucket.accession_number,
                fiscal_year=bucket.fiscal_year,
                period=bucket.period,
                form=bucket.form,
                filed=bucket.filed,
                fields=dict(bucket.fields),
                spans=dict(bucket.spans),
                period_end_str=bucket.period_end_str,
                period_start_str=bucket.period_start_str,
            )
            by_period[period_key] = existing
            for fname in bucket.fields:
                field_filed[(bucket.fiscal_year, bucket.period, fname)] = bucket.filed
            if "revenue" in bucket.fields:
                period_end_filed[period_key] = bucket.filed
            continue

        # Field-level merge into existing
        for fname, val in bucket.fields.items():
            if val is None:
                continue
            prev_filed = field_filed.get((bucket.fiscal_year, bucket.period, fname))
            if prev_filed is None or _filed_lt(prev_filed, bucket.filed):
                existing.fields[fname] = val
                existing.spans[fname] = bucket.spans.get(fname)
                field_filed[(bucket.fiscal_year, bucket.period, fname)] = bucket.filed

        # Anchor calendar window to the bucket whose `revenue` won.
        # (Falls back to the first bucket that supplied period_end_str.)
        if "revenue" in bucket.fields and bucket.period_end_str:
            prev = period_end_filed.get(period_key)
            if prev is None or _filed_lt(prev, bucket.filed):
                existing.period_end_str = bucket.period_end_str
                existing.period_start_str = bucket.period_start_str
                period_end_filed[period_key] = bucket.filed
        elif existing.period_end_str is None and bucket.period_end_str:
            existing.period_end_str = bucket.period_end_str
            existing.period_start_str = bucket.period_start_str

        # Bucket-level provenance always tracks the most recent filing
        # (used for Tier-0 source-log accession recording).
        if _filed_lt(existing.filed, bucket.filed):
            existing.filed = bucket.filed
            existing.accession_number = bucket.accession_number
            existing.form = bucket.form

    # Phase 5S-3: YTD → discrete differencing for cumulative-only fields.
    # Operates per-fiscal-year, in reverse-period order (Q3 first, then Q2)
    # so the differencing reads YTD values that haven't been overwritten
    # yet. Also synthesizes Q4 = FY − Q3_YTD.
    _difference_ytd_quarters(by_period)

    rows: list[EdgarFinancialRow] = []
    for bucket in by_period.values():
        rows.append(_materialize_row(ticker, bucket))

    # Repair filer-side share-count mis-scaling against the cover-page anchor.
    anchors = dei_share_anchors(payload)
    if anchors:
        for row in rows:
            anchor = anchors.get(row.fiscal_year)
            repaired = repair_share_scale(row.shares_outstanding, anchor)
            if repaired is not None:
                logger.info(
                    "%s FY%d: share count %s implausible vs cover-page %s — using anchor",
                    ticker, row.fiscal_year, row.shares_outstanding, anchor,
                )
                row.shares_outstanding = repaired

    # Sort: most-recent first (annual then quarterly within same year).
    period_rank = {"annual": 0, "Q4": 1, "Q3": 2, "Q2": 3, "Q1": 4}
    rows.sort(
        key=lambda r: (-r.fiscal_year, period_rank.get(r.period, 99))
    )

    # Optional history cap — trim to last N fiscal years.
    if annual_years_limit is not None and rows:
        latest_fy = rows[0].fiscal_year
        cutoff_fy = latest_fy - annual_years_limit + 1
        rows = [r for r in rows if r.fiscal_year >= cutoff_fy]

    # Optional year-set filter — used by the coverage gate.
    if keep_only_years is not None:
        rows = [r for r in rows if r.fiscal_year in keep_only_years]

    return rows


# ── Materialization ──────────────────────────────────────────────────────


def _materialize_row(ticker: str, b: _FilingFacts) -> EdgarFinancialRow:
    period_end = _parse_iso(b.period_end_str)
    period_start = _parse_iso(b.period_start_str)
    filed_date_val = _parse_iso(b.filed)
    f = b.fields
    revenue = f.get("revenue")
    cost_of_revenue = f.get("cost_of_revenue")
    gross_profit = f.get("gross_profit")
    if gross_profit is None and revenue is not None and cost_of_revenue is not None:
        gross_profit = revenue - cost_of_revenue
    gross_margin = (gross_profit / revenue) if (gross_profit is not None and revenue) else None

    long_term_debt = f.get("long_term_debt")
    short_term_debt = f.get("short_term_debt")
    op_lease_lt = f.get("operating_lease_lt")
    op_lease_st = f.get("operating_lease_st")
    # total_debt rolls up financial debt + operating-lease liabilities (ASC 842).
    # Returns None only when ALL four sources are absent — distinguishing
    # "genuinely debt-free with no leases" (rare) from "we just didn't fetch".
    components = (long_term_debt, short_term_debt, op_lease_lt, op_lease_st)
    if all(c is None for c in components):
        total_debt: float | None = None
    else:
        total_debt = sum(c or 0.0 for c in components)
        total_debt = total_debt if total_debt != 0.0 else None

    # Phase 5S-5: short-term investments. Resolution order:
    #   1. If aggregate (AvailableForSaleSecuritiesDebtSecurities w/o suffix)
    #      is present, use it directly — that's the filer's own roll-up.
    #   2. Otherwise sum (current + noncurrent) split fields.
    #   3. If all three are absent, leave None (genuinely no AFS portfolio).
    sti_aggregate = f.get("short_term_investments_aggregate")
    sti_current = f.get("short_term_investments_current")
    sti_noncurrent = f.get("short_term_investments_noncurrent")
    if sti_aggregate is not None:
        short_term_investments: float | None = sti_aggregate
    elif sti_current is None and sti_noncurrent is None:
        short_term_investments = None
    else:
        short_term_investments = (sti_current or 0.0) + (sti_noncurrent or 0.0)
        short_term_investments = (
            short_term_investments if short_term_investments != 0.0 else None
        )

    capex = f.get("capex")
    capex_abs = abs(capex) if capex is not None else None
    operating_cf = f.get("operating_cash_flow")
    free_cash_flow = (operating_cf - capex_abs) if (operating_cf is not None and capex_abs is not None) else None

    dividends_paid = f.get("dividends_paid")
    dividends_abs = abs(dividends_paid) if dividends_paid is not None else None
    share_repurchases = f.get("share_repurchases")
    repurchases_abs = abs(share_repurchases) if share_repurchases is not None else None

    # Phase 5k-9: derive operating_income from pretax + nonoperating when the
    # OperatingIncomeLoss tag isn't reported (ADP-style filers). XBRL sign
    # convention: pretax_income = operating_income + nonoperating_income_expense
    # (signed). So operating_income = pretax_income − nonoperating_income_expense.
    operating_income = f.get("operating_income")
    if operating_income is None:
        pti = f.get("pretax_income")
        if pti is None:
            pti_d = f.get("pretax_income_domestic")
            pti_f = f.get("pretax_income_foreign")
            if pti_d is not None or pti_f is not None:
                pti = (pti_d or 0.0) + (pti_f or 0.0)
        nonop = f.get("nonoperating_income_expense")
        if pti is not None and nonop is not None:
            operating_income = pti - nonop

    ebitda = f.get("ebitda_direct")
    if ebitda is None:
        da = f.get("depreciation_amortization")
        if operating_income is not None and da is not None:
            ebitda = operating_income + da

    # Phase 5S-2: derive R&D disclosure state.
    # `rd_tax_credits_signal` (IncomeTaxReconciliationTaxCreditsResearch) only
    # appears in 10-K FY filings (tax-footnote rollup), so quarterly rows
    # inherit the state from the parent FY at the orchestrator layer rather
    # than being set here. For now: per-row only.
    rd_expense_val = f.get("rd_expense")
    rd_credit_signal = f.get("rd_tax_credits_signal")
    if rd_expense_val is not None:
        rd_disclosure_state = "disclosed_exact"
    elif rd_credit_signal is not None and rd_credit_signal != 0:
        # R&D activity confirmed via tax footnote but no separate XBRL line —
        # the HIMS pattern. Surface as informational rather than missing.
        rd_disclosure_state = "bundled_in_opex"
    else:
        rd_disclosure_state = None

    return EdgarFinancialRow(
        ticker=ticker,
        fiscal_year=b.fiscal_year,
        period=b.period,
        source="edgar",
        accession_number=b.accession_number,
        period_end_date=period_end,
        period_start_date=period_start,
        filed_date=filed_date_val,
        revenue=revenue,
        cost_of_revenue=cost_of_revenue,
        gross_profit=gross_profit,
        gross_margin=gross_margin,
        operating_income=operating_income,
        operating_expenses=f.get("operating_expenses"),
        net_income=f.get("net_income"),
        ebitda=ebitda,
        rd_expense=f.get("rd_expense"),
        rd_disclosure_state=rd_disclosure_state,
        sga_expense=f.get("sga_expense"),
        interest_expense=f.get("interest_expense"),
        income_tax_expense=f.get("income_tax_expense"),
        depreciation_amortization=f.get("depreciation_amortization"),
        operating_cash_flow=operating_cf,
        free_cash_flow=free_cash_flow,
        capex=capex_abs,
        total_assets=f.get("total_assets"),
        total_equity=f.get("total_equity"),
        total_debt=total_debt,
        long_term_debt=long_term_debt,
        cash_and_equivalents=f.get("cash_and_equivalents"),
        short_term_investments=short_term_investments,
        funds_held_for_clients=f.get("funds_held_for_clients"),
        investment_income_interest=f.get("investment_income_interest"),
        share_based_compensation=f.get("share_based_compensation"),
        goodwill=f.get("goodwill"),
        accounts_receivable=f.get("accounts_receivable"),
        current_assets=f.get("current_assets"),
        current_liabilities=f.get("current_liabilities"),
        inventory=f.get("inventory"),
        shares_outstanding=f.get("shares_outstanding"),
        eps_diluted=f.get("eps_diluted"),
        eps_basic=f.get("eps_basic"),
        dividends_paid=dividends_abs,
        share_repurchases=repurchases_abs,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _is_ytd_span(span: int | None) -> bool:
    """Heuristic: a quarterly field's value is YTD if its calendar span is
    materially longer than a single 3-month period.

    Discrete 3M values have span ~88-92 days. YTD values are ~180d (Q2),
    ~270d (Q3), ~365d (FY). 100 days is comfortably between the two.
    """
    return span is not None and span > 100


def _difference_ytd_quarters(
    by_period: dict[tuple[int, str], _FilingFacts],
) -> None:
    """Convert YTD-cumulative cash-flow values into discrete quarterly values.

    SEC XBRL convention (per 5S-3): cash-flow-statement concepts are filed
    YTD-only — Q1 has 3M, Q2 has 6M, Q3 has 9M, FY has 12M. The parser
    stores them as-is during ingestion (`_CUMULATIVE_QUARTERLY_FIELDS`
    bypass the span>200 filter). This function converts them to discrete:

      Q3_discrete = Q3_YTD − Q2_YTD     (process FIRST, while Q2 still YTD)
      Q2_discrete = Q2_YTD − Q1_YTD
      Q1_discrete = Q1_YTD              (already discrete: 3M = 3M)

    Also synthesizes a Q4 bucket per fiscal year, since companies never
    file a discrete Q4 10-Q:

      Q4_discrete = FY − (Q1 + Q2 + Q3)_discrete

    SPAN GATING (critical, see HIMS AllocatedShareBasedCompensationExpense):
    Some filers report cumulative concepts at BOTH YTD AND discrete-3M
    durations. The shortest-span resolution in `_ingest` already keeps
    the 3M-discrete value when both are available. This function ONLY
    differences fields whose stored value is YTD (span > 100d). Without
    this gate the pass would double-difference already-discrete values
    and produce Q3 SBC = ~$4M instead of the true ~$40M (the difference
    between 3M-discrete and 6M-discrete).

    The Q4 bucket inherits its accession_number / filed from the matching
    10-K so downstream consumers (Tier-0 source-log) attribute correctly.

    Mutates `by_period` in place. No-op when a fiscal year is missing a
    quarter (e.g. recent IPO, mid-year switch).
    """
    # Collect fiscal years that have any quarterly rows
    fiscal_years = sorted({fy for (fy, _p) in by_period.keys()})

    for fy in fiscal_years:
        q1 = by_period.get((fy, "Q1"))
        q2 = by_period.get((fy, "Q2"))
        q3 = by_period.get((fy, "Q3"))
        fy_bucket = by_period.get((fy, "annual"))

        # --- Step 1: Q3 differencing (MUST run before Q2 diff) ---
        # Only difference Q3 fields that are currently in YTD form. For
        # Q3 YTD we need a 6M-YTD value to subtract. Q2's stored value may
        # itself be YTD (180d) — use directly — or discrete (90d) — in
        # which case reconstruct 6M YTD = Q1_3M + Q2_discrete.
        if q3 is not None and q2 is not None:
            for field in _CUMULATIVE_QUARTERLY_FIELDS:
                v3 = q3.fields.get(field)
                s3 = q3.spans.get(field)
                if v3 is None or not _is_ytd_span(s3):
                    continue
                v2 = q2.fields.get(field)
                if v2 is None:
                    continue
                if _is_ytd_span(q2.spans.get(field)):
                    ytd6 = v2
                else:
                    # Q2 is already discrete — reconstruct 6M YTD
                    v1 = q1.fields.get(field) if q1 else None
                    if v1 is None:
                        continue
                    ytd6 = v1 + v2
                q3.fields[field] = v3 - ytd6
                q3.spans[field] = 90

        # --- Step 2: Q2_discrete = Q2_YTD − Q1_YTD ---
        # Q1 is always discrete = 3M YTD (90d span either way).
        if q2 is not None and q1 is not None:
            for field in _CUMULATIVE_QUARTERLY_FIELDS:
                v2 = q2.fields.get(field)
                if v2 is None or not _is_ytd_span(q2.spans.get(field)):
                    continue
                v1 = q1.fields.get(field)
                if v1 is None:
                    continue
                q2.fields[field] = v2 - v1
                q2.spans[field] = 90

        # --- Step 3: synthesize Q4_discrete = FY − Q3_YTD ---
        # We need Q3 _YTD_ here, but step 1 already overwrote q3 with
        # discrete values. Reconstruct YTD = sum(Q1, Q2_discrete, Q3_discrete)
        # for each cumulative field. (Q2 is now discrete after step 2.)
        if fy_bucket is not None and q3 is not None and q2 is not None and q1 is not None:
            q4_fields: dict[str, float] = {}
            q4_spans: dict[str, int | None] = {}
            for field in _CUMULATIVE_QUARTERLY_FIELDS:
                fy_val = fy_bucket.fields.get(field)
                if fy_val is None:
                    continue
                q1_val = q1.fields.get(field)
                q2_val = q2.fields.get(field)
                q3_val = q3.fields.get(field)
                if q1_val is None or q2_val is None or q3_val is None:
                    continue
                q4_fields[field] = fy_val - (q1_val + q2_val + q3_val)
                q4_spans[field] = 90    # approx 3-month span
            if q4_fields:
                # Pull non-cumulative balance-sheet & income fields from
                # the FY bucket so Q4 isn't a sparse cash-flow-only row.
                # Income flow items (revenue, NI) for Q4 = FY − (Q1+Q2+Q3 from
                # their discrete entries), but the existing code already
                # has each quarter's discrete income values stored. We
                # compute Q4 here for income items the same way as cash flow,
                # but ONLY for fields where all three prior quarters AND FY
                # are present.
                _income_flow_fields = (
                    "revenue", "cost_of_revenue", "gross_profit",
                    "operating_income", "operating_expenses", "net_income",
                    "ebitda", "ebitda_direct", "rd_expense", "sga_expense",
                    "interest_expense", "income_tax_expense", "pretax_income",
                    "pretax_income_domestic", "pretax_income_foreign",
                    "nonoperating_income_expense",
                )
                for field in _income_flow_fields:
                    if field in q4_fields:
                        continue
                    fy_val = fy_bucket.fields.get(field)
                    q1_val = q1.fields.get(field)
                    q2_val = q2.fields.get(field)
                    q3_val = q3.fields.get(field)
                    if None in (fy_val, q1_val, q2_val, q3_val):
                        continue
                    q4_fields[field] = fy_val - (q1_val + q2_val + q3_val)
                    q4_spans[field] = 90
                # Balance-sheet (instant) fields don't difference — copy
                # FY's values (which are end-of-year = end-of-Q4 anyway).
                _balance_instant_fields = (
                    "total_assets", "total_equity", "total_debt",
                    "long_term_debt", "cash_and_equivalents",
                    "accounts_receivable", "current_assets",
                    "current_liabilities", "inventory",
                    "shares_outstanding", "goodwill",
                    "funds_held_for_clients", "investment_income_interest",
                )
                for field in _balance_instant_fields:
                    fy_val = fy_bucket.fields.get(field)
                    if fy_val is not None:
                        q4_fields[field] = fy_val
                        q4_spans[field] = fy_bucket.spans.get(field)

                # Anchor Q4 calendar window to FY's end + Q3's end + 1 day
                # (start = day after Q3 end; end = FY end).
                q4_end = fy_bucket.period_end_str
                q4_start = None
                if q3.period_end_str:
                    try:
                        q3_end_d = datetime.strptime(
                            q3.period_end_str, "%Y-%m-%d"
                        ).date()
                        q4_start = (q3_end_d + timedelta(days=1)).strftime("%Y-%m-%d")
                    except (TypeError, ValueError):
                        q4_start = None

                by_period[(fy, "Q4")] = _FilingFacts(
                    accession_number=fy_bucket.accession_number,
                    fiscal_year=fy,
                    period="Q4",
                    form=fy_bucket.form,
                    filed=fy_bucket.filed,
                    fields=q4_fields,
                    spans=q4_spans,
                    period_end_str=q4_end,
                    period_start_str=q4_start,
                )


def _span_days(start: str | None, end: str | None) -> int | None:
    """Return inclusive span in days between SEC date strings, or None."""
    if not start or not end:
        return None
    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        return (e - s).days
    except (TypeError, ValueError):
        return None


def _derive_fiscal_period(
    period_end: date,
    period_start: date | None,
    fye_month: int,
) -> tuple[int, str] | None:
    """
    Derive (fiscal_year, period) from an entry's calendar window using the
    company's fiscal-year-end month. End-year convention: FY = the calendar
    year in which the period ends.

    Returns None if `period_end` isn't a fiscal-period boundary (Q1/Q2/Q3/Q4
    end), so intra-period snapshots get filtered out.

    Examples (Intapp, FYEM=6):
      end=2022-06-30, span≈365 → (2022, 'annual')
      end=2022-09-30, span≈92  → (2023, 'Q1')      # Q1 of FY2023
      end=2023-03-31, span≈92  → (2023, 'Q3')      # Q3 of FY2023
      end=2023-06-30, span≈365 → (2023, 'annual')

    Examples (calendar-year filer, FYEM=12):
      end=2024-12-31, span≈365 → (2024, 'annual')
      end=2024-03-31, span≈90  → (2024, 'Q1')
    """
    if not (1 <= fye_month <= 12):
        fye_month = 12

    # End-year convention: FY = the calendar year in which the period ends.
    # For FYEM=6 (Jun): end Jun→FY ends in same year; Jul-Dec→FY ends NEXT year.
    # For FYEM=12 (Dec): end Jan-Dec→FY ends same year (Jan periods are 53-week
    #   year ends carrying the prior fiscal year — see footnote).
    if period_end.month <= fye_month:
        fiscal_year = period_end.year
    else:
        fiscal_year = period_end.year + 1

    # Span-FIRST detection (2026-05-17 fix). When period_start is provided AND
    # the span is annual (~365 days), accept as annual REGARDLESS of whether
    # the end-month matches the stored fye_month's quarter-end pattern.
    #
    # This catches fiscal-calendar transitions like ILMN's 2023 switch from
    # 53-week year ending early Jan (fye_month=1) to Dec-31 calendar year-end
    # (effectively fye_month=12). For end=2023-12-31 with fye_month=1, the
    # quarter-boundary check below returns None (months_from_fy_start=11),
    # dropping the row. Span-first override rescues it.
    if period_start is not None:
        span = (period_end - period_start).days
        if 340 <= span <= 380:
            return (fiscal_year, "annual")
        if span < 14:
            return None    # too short — likely an intra-period snapshot

    # Quarter-boundary check. Only end-months that are fiscal-quarter ends
    # are valid period anchors. Anything else (mid-quarter snapshot) skips.
    fy_start_month = (fye_month % 12) + 1
    months_from_fy_start = ((period_end.month - fy_start_month) % 12) + 1
    quarter_map = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
    quarter_label = quarter_map.get(months_from_fy_start)
    if quarter_label is None:
        return None

    # End-month-based default. Q4-end is the year-end balance / annual flow.
    if quarter_label == "Q4":
        return (fiscal_year, "annual")
    return (fiscal_year, quarter_label)


def _filed_lt(a: str, b: str) -> bool:
    """ISO-date string compare (lexicographic == chronological for YYYY-MM-DD)."""
    return (a or "") < (b or "")


def _parse_iso(s: str | None) -> date | None:
    """Parse 'YYYY-MM-DD' string to date; return None on bad input."""
    from datetime import datetime as _datetime
    if not s:
        return None
    try:
        return _datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
