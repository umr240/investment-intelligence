"""
CompanyDataReader — single, consistent accessor for everything stored about a
company. Frameworks consume this; nothing in frameworks/ should ever query SQL
or import the schema directly.

Design contract:
  - Every accessor returns either a typed list (most-recent first) or a single
    typed object — never raw rows or dicts.
  - Every accessor is read-only — never mutates DB state.
  - Empty result → empty list (or None for single-object accessors).
  - The reader does NOT trigger any network fetch. If a field is empty, the
    framework declares the gap and the orchestrator may issue a follow-up
    refresh_ticker() to fill it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from data.db import get_session
from data.models.schema import (
    AnalystCoverageRecord,
    Company,
    EarningsHistory,
    Financial,
    InsiderTransactionRecord,
    InstitutionalHolderRecord,
    PriceHistory,
    ShortInterestRecord,
)

# ADR-018 three-state semantics, enforced at the READ boundary. Only
# 'disclosed_exact' carries a real listing date; the parser_uncertain rows hold
# the earliest filing date in the fetched submissions window instead (KO -> 2018
# against a 1919 listing). Measured: every non-disclosed_exact row either has no
# date or a wrong one, so gating here discards nothing valid.
_TRUSTED_LISTING_STATE = "disclosed_exact"


def trusted_listing_date(ipo_date: date | None, state: str | None) -> date | None:
    """The listing date, or None when its provenance does not support using it."""
    if ipo_date is None or state != _TRUSTED_LISTING_STATE:
        return None
    return ipo_date


if TYPE_CHECKING:
    pass


# ── Preformatted label helpers (TradingView/Finviz pattern) ───────────────
#
# Frameworks and UI components NEVER re-derive these from raw dates. They
# always go through these helpers so the labelling stays consistent across:
#   - dive output tables
#   - screener result rows
#   - JSON exports
#   - the AI narrative layer
#
# Three orthogonal time concepts get three orthogonal label functions:
#   - fiscal_label(fiscal_year, period)              → "Q3 FY2025"
#   - period_label(period_end_date)                   → "Period ended Mar 31, 2025"
#   - event_label(event_date, event_time)             → "May 7, 2026 — AMC"
#   - filed_label(filed_date)                          → "Filed Aug 12, 2025"
#
# Never merge them. Traders care first about event_label (catalyst);
# investors care about period_label and fiscal_label (accounting). Filed
# date is auditing/legal, never a primary label.

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fiscal_label(fiscal_year: int | None, period: str | None) -> str:
    """
    Build a fiscal-period label like "Q3 FY2025" or "FY2025".

    Returns "" on missing inputs — never None — so f-strings stay safe.
    """
    if not fiscal_year:
        return ""
    if not period or period == "annual":
        return f"FY{fiscal_year}"
    p = period.upper()
    if p in ("Q1", "Q2", "Q3", "Q4"):
        return f"{p} FY{fiscal_year}"
    return f"FY{fiscal_year}"


def period_label(period_end: "date | None") -> str:
    """
    Build a period-end label like "Period ended Mar 31, 2025".
    Returns "" on None.
    """
    if period_end is None:
        return ""
    return f"Period ended {_MONTHS[period_end.month - 1]} {period_end.day}, {period_end.year}"


def event_label(event_date: "date | None", event_time: str | None = None) -> str:
    """
    Build a market-event label like "May 7, 2026 — AMC" / "May 7, 2026 — BMO".
    `event_time`: "AMC" (after market close), "BMO" (before market open),
    "intraday", or None. Returns "" if event_date is None.
    """
    if event_date is None:
        return ""
    base = f"{_MONTHS[event_date.month - 1]} {event_date.day}, {event_date.year}"
    if not event_time:
        return base
    return f"{base} — {event_time}"


def filed_label(filed_date: "date | None") -> str:
    """Filing-date label like "Filed Aug 12, 2025"."""
    if filed_date is None:
        return ""
    return f"Filed {_MONTHS[filed_date.month - 1]} {filed_date.day}, {filed_date.year}"


@dataclass
class TTMSnapshot:
    """
    Trailing-twelve-month synthetic snapshot. Built on demand by
    CompanyDataReader.ttm_at(); never written to the DB.

    Flow concepts are SUMMED across the 4 quarterlies. Stock concepts (the
    `_pit` / point-in-time fields) come from the most-recent quarterly.
    """
    ticker: str
    as_of: date
    period_end_date: date          # end of the most-recent constituent quarter
    period_start_date: date        # start of the oldest constituent quarter

    # Flow concepts (4-quarter sum)
    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    operating_expenses: float | None = None
    net_income: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    capex: float | None = None
    interest_expense: float | None = None
    income_tax_expense: float | None = None
    depreciation_amortization: float | None = None
    dividends_paid: float | None = None
    share_repurchases: float | None = None

    # Stock concepts (point-in-time from most-recent quarterly)
    total_assets: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    long_term_debt: float | None = None
    cash_and_equivalents: float | None = None
    # Phase 5S-5: marketable securities held as excess capital. Point-in-time
    # value from the most-recent constituent quarter. Used by F5 Debt/EBITDA
    # (net basis) and by ROIC (excluded from invested capital).
    short_term_investments: float | None = None
    net_debt: float | None = None
    accounts_receivable: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    inventory: float | None = None
    shares_outstanding: float | None = None

    # Derived flow used by Debt/EBITDA and similar ratios.
    # EBITDA = operating_income + D&A (same as Financial._apply_financial_row).
    ebitda: float | None = None

    # Derived ratios on TTM (computed in _build_ttm_snapshot)
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    fcf_margin: float | None = None
    rd_intensity: float | None = None
    roic: float | None = None
    pretax_roic: float | None = None
    roe: float | None = None
    roa: float | None = None
    gp_a: float | None = None
    asset_turnover: float | None = None
    debt_to_equity: float | None = None
    debt_to_ebitda: float | None = None
    current_ratio: float | None = None

    @property
    def period(self) -> str:
        return "ttm"

    @property
    def is_synthetic(self) -> bool:
        return True


def _sum_or_none(values: list[float | None]) -> float | None:
    """Sum values, treating None as 0 only if at least one non-None present.
    All None → None (don't fabricate zero)."""
    have_any = any(v is not None for v in values)
    if not have_any:
        return None
    return sum((v or 0.0) for v in values)


def _build_ttm_snapshot(ticker: str, quarters: list[Financial], as_of: date) -> TTMSnapshot:
    """Construct a TTMSnapshot from the 4 most-recent quarterly Financial rows."""
    # quarters ordered most-recent first per ttm_at()'s query
    latest = quarters[0]
    oldest = quarters[-1]

    rev = _sum_or_none([q.revenue for q in quarters])
    cogs = _sum_or_none([q.cost_of_revenue for q in quarters])
    gp = _sum_or_none([q.gross_profit for q in quarters])
    if gp is None and rev is not None and cogs is not None:
        gp = rev - cogs
    oi = _sum_or_none([q.operating_income for q in quarters])
    opex = _sum_or_none([q.operating_expenses for q in quarters])
    ni = _sum_or_none([q.net_income for q in quarters])
    rd = _sum_or_none([q.rd_expense for q in quarters])
    sga = _sum_or_none([q.sga_expense for q in quarters])
    ocf = _sum_or_none([q.operating_cash_flow for q in quarters])
    fcf = _sum_or_none([q.free_cash_flow for q in quarters])
    capex = _sum_or_none([q.capex for q in quarters])
    int_exp = _sum_or_none([q.interest_expense for q in quarters])
    tax_exp = _sum_or_none([q.income_tax_expense for q in quarters])
    da = _sum_or_none([q.depreciation_amortization for q in quarters])
    div = _sum_or_none([q.dividends_paid for q in quarters])
    bb = _sum_or_none([q.share_repurchases for q in quarters])

    # Stock concepts — most-recent quarter's snapshot
    ta = latest.total_assets
    te = latest.total_equity
    td = latest.total_debt

    snap = TTMSnapshot(
        ticker=ticker,
        as_of=as_of,
        period_end_date=latest.period_end_date or as_of,
        period_start_date=oldest.period_start_date or oldest.period_end_date or as_of,
        revenue=rev, cost_of_revenue=cogs, gross_profit=gp,
        operating_income=oi, operating_expenses=opex, net_income=ni,
        rd_expense=rd, sga_expense=sga, operating_cash_flow=ocf,
        free_cash_flow=fcf, capex=capex, interest_expense=int_exp,
        income_tax_expense=tax_exp, depreciation_amortization=da,
        dividends_paid=div, share_repurchases=bb,
        total_assets=ta, total_equity=te, total_debt=td,
        long_term_debt=latest.long_term_debt,
        cash_and_equivalents=latest.cash_and_equivalents,
        short_term_investments=latest.short_term_investments,
        net_debt=latest.net_debt,
        accounts_receivable=latest.accounts_receivable,
        current_assets=latest.current_assets,
        current_liabilities=latest.current_liabilities,
        inventory=latest.inventory,
        shares_outstanding=latest.shares_outstanding,
    )

    # Derived ratios — same formulas as Financial._apply_financial_row.
    # ROIC = NOPAT / IC where IC = Equity + Debt − Cash (Phase 5k / DEC-31).
    # See pipeline._effective_tax_rate + _apply_financial_row for rationale.
    from data.pipeline import _effective_tax_rate
    snap.gross_margin = (gp / rev) if (gp is not None and rev) else None
    snap.operating_margin = (oi / rev) if (oi is not None and rev) else None
    snap.net_margin = (ni / rev) if (ni is not None and rev) else None
    snap.fcf_margin = (fcf / rev) if (fcf is not None and rev) else None
    snap.rd_intensity = (rd / rev) if (rd is not None and rev) else None
    cs = latest.cash_and_equivalents
    sti = latest.short_term_investments
    # Phase 5S-5: IC excludes both cash AND short-term investments
    # (excess-capital exclusion per McKinsey/Stewart/Mauboussin standard).
    invested = (te or 0.0) + (td or 0.0) - (cs or 0.0) - (sti or 0.0)
    etr = _effective_tax_rate(ni, tax_exp)
    nopat = (oi * (1 - etr)) if oi is not None else None
    snap.roic = (
        (nopat / invested)
        if (nopat is not None and invested and invested > 0) else None
    )
    snap.pretax_roic = (
        (oi / invested)
        if (oi is not None and invested and invested > 0) else None
    )
    snap.roe = (ni / te) if (ni and te) else None
    snap.roa = (ni / ta) if (ni and ta) else None
    snap.gp_a = (gp / ta) if (gp is not None and ta) else None
    snap.asset_turnover = (rev / ta) if (rev is not None and ta) else None
    snap.debt_to_equity = (td / te) if (td is not None and te) else None
    # EBITDA on TTM = sum of quarterly operating_income + sum of quarterly D&A.
    # Debt/EBITDA on TTM uses NET debt (5S-5): clamp at 0 when net-cash.
    if oi is not None and da is not None:
        snap.ebitda = oi + da
    if td is not None:
        snap.net_debt = td - (cs or 0.0) - (sti or 0.0)
    if snap.ebitda is not None and snap.ebitda > 0 and snap.net_debt is not None:
        snap.debt_to_ebitda = max(snap.net_debt / snap.ebitda, 0.0)
    snap.current_ratio = (
        (latest.current_assets / latest.current_liabilities)
        if (latest.current_assets is not None and latest.current_liabilities) else None
    )
    return snap


class CompanyNotFoundError(Exception):
    """Raised when the reader is asked for a ticker not in the DB."""


class CompanyDataReader:
    """
    Read-only handle to all persistent data about one company.

    Usage:
        reader = CompanyDataReader('NVDA')
        annuals = reader.annuals(last_n=5)               # most-recent-first
        latest = reader.latest_annual()
        q4_2024 = reader.quarter(2024, 'Q4')
        insiders = reader.insider_transactions(within_days=90)
        prices = reader.price_history(within_days=365)

    Each call opens a fresh SQLAlchemy session, runs one query, closes the
    session. No connection state is held — the reader is safe to pass between
    coroutines.
    """

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker.upper()

    # ── Company profile ──────────────────────────────────────────────────

    def company(self) -> Company:
        with get_session() as session:
            row = session.query(Company).filter_by(ticker=self.ticker).first()
            if not row:
                raise CompanyNotFoundError(self.ticker)
            session.expunge(row)
            return row

    def company_or_none(self) -> Company | None:
        with get_session() as session:
            row = session.query(Company).filter_by(ticker=self.ticker).first()
            if row is not None:
                session.expunge(row)
            return row

    # ── Financials (annual + quarterly) ──────────────────────────────────

    def annuals(self, last_n: int | None = None) -> list[Financial]:
        """Annual Financial rows, most-recent first."""
        return self._financials(period_filter="annual", last_n=last_n)

    def quarterlies(self, last_n: int | None = None) -> list[Financial]:
        """Quarterly Financial rows (Q1-Q4), most-recent first."""
        return self._financials(period_filter="quarterly", last_n=last_n)

    def all_periods(self, last_n: int | None = None) -> list[Financial]:
        """All Financial rows regardless of period, most-recent first."""
        return self._financials(period_filter=None, last_n=last_n)

    def annual(self, fiscal_year: int) -> Financial | None:
        with get_session() as session:
            company = self._company(session)
            if not company:
                return None
            row = (
                session.query(Financial)
                .filter_by(company_id=company.id, fiscal_year=fiscal_year, period="annual")
                .first()
            )
            if row is not None:
                session.expunge(row)
            return row

    def quarter(self, fiscal_year: int, period: str) -> Financial | None:
        if period.upper() not in ("Q1", "Q2", "Q3", "Q4"):
            return None
        with get_session() as session:
            company = self._company(session)
            if not company:
                return None
            row = (
                session.query(Financial)
                .filter_by(
                    company_id=company.id,
                    fiscal_year=fiscal_year,
                    period=period.upper(),
                )
                .first()
            )
            if row is not None:
                session.expunge(row)
            return row

    def latest_annual(self) -> Financial | None:
        annuals = self.annuals(last_n=1)
        return annuals[0] if annuals else None

    def latest_quarter(self) -> Financial | None:
        quarterlies = self.quarterlies(last_n=1)
        return quarterlies[0] if quarterlies else None

    # ── TTM (computed on demand — never persisted, see DECISIONS.md DEC-12) ─

    def ttm_at(self, as_of: "date | None" = None) -> "TTMSnapshot | None":
        """
        Trailing-twelve-month synthetic snapshot ending on/before `as_of`.

        Sums flow concepts (revenue, gross_profit, operating_income, net_income,
        operating_cash_flow, free_cash_flow, capex, rd_expense, sga_expense,
        depreciation_amortization, dividends_paid, share_repurchases) over the
        4 most-recent quarterlies whose period_end_date ≤ as_of. Stock concepts
        (total_assets, total_equity, total_debt, etc.) are taken from the
        most-recent quarterly (point-in-time, not summed).

        Returns None if fewer than 4 qualifying quarterlies exist.
        Does NOT write to DB.
        """
        if as_of is None:
            as_of = date.today()

        with get_session() as session:
            company = self._company(session)
            if not company:
                return None
            # Pull all quarterly rows whose period_end_date is on/before as_of,
            # ordered most-recent first. Limit 4 — that's the trailing year.
            q = (
                session.query(Financial)
                .filter_by(company_id=company.id)
                .filter(Financial.period.in_(("Q1", "Q2", "Q3", "Q4")))
                .filter(Financial.period_end_date.isnot(None))
                .filter(Financial.period_end_date <= as_of)
                .order_by(Financial.period_end_date.desc())
                .limit(4)
                .all()
            )
            if len(q) < 4:
                return None
            for r in q:
                session.expunge(r)

        return _build_ttm_snapshot(self.ticker, q, as_of)

    def latest_annual_or_ttm(self, as_of: "date | None" = None) -> "Financial | TTMSnapshot | None":
        """
        Most-recent annual Financial if available; else TTM synthetic. None if neither.
        Frameworks call this when they don't care which it is — they just need
        the most-current 'full year equivalent' snapshot.
        """
        annual = self.latest_annual()
        if annual is not None:
            return annual
        return self.ttm_at(as_of)

    # ── ADR-026 three-tier API: ttm() / mrq() / latest_annual() ─────────
    # Public surface for framework code. Use `ttm()` for current-state
    # ratios, `mrq()` for balance-sheet snapshots, `latest_annual()` for
    # academic-framework anchors + trajectories.

    def ttm(self) -> "TTMSnapshot | None":
        """ADR-026 alias for ttm_at(today). Use for current-state ratios:
        ROIC, FCF margin, gross margin, operating margin, debt/EBITDA.

        Returns None when fewer than 4 quarterly rows are available
        (recent IPO, or quarterly fetch failed). Caller should fall back
        to latest_annual() in that case.
        """
        return self.ttm_at()

    def mrq(self) -> "Financial | None":
        """ADR-026: Most Recent Quarter — balance-sheet snapshot.

        Sorts by ``period_end_date`` (not the legacy fiscal_year + period
        sort used by `_financials`). This matters because the legacy
        sort returns Q1 first within a fiscal year, which for a company
        mid-way through its FY would mis-identify the latest quarter.

        Used for stock items: cash, debt, equity, IC denominator,
        working capital. Distinct from ttm() which is a 4-quarter
        aggregation.
        """
        with get_session() as session:
            company = self._company(session)
            if not company:
                return None
            row = (
                session.query(Financial)
                .filter_by(company_id=company.id)
                .filter(Financial.period.in_(("Q1", "Q2", "Q3", "Q4")))
                .filter(Financial.period_end_date.isnot(None))
                .order_by(Financial.period_end_date.desc())
                .first()
            )
            if row is not None:
                session.expunge(row)
            return row

    def annual_year_set(self) -> set[int]:
        """Set of fiscal years for which we have an annual row. Used by the coverage gate."""
        with get_session() as session:
            company = self._company(session)
            if not company:
                return set()
            rows = (
                session.query(Financial.fiscal_year)
                .filter_by(company_id=company.id, period="annual")
                .all()
            )
            return {y for (y,) in rows if y}

    # ── Preformatted labels (use in dive tables, exports, AI narrative) ──

    def fiscal_year_end_month(self) -> int:
        """Fiscal year-end month (1-12). Defaults to 12 if not yet resolved."""
        co = self.company_or_none()
        if co is None or co.fiscal_year_end_month is None:
            return 12
        return int(co.fiscal_year_end_month)

    @staticmethod
    def fiscal_label(fin: Financial | None) -> str:
        if fin is None:
            return ""
        return fiscal_label(fin.fiscal_year, fin.period)

    @staticmethod
    def period_label(fin: Financial | None) -> str:
        if fin is None:
            return ""
        return period_label(fin.period_end_date)

    @staticmethod
    def event_label(fin: Financial | None) -> str:
        if fin is None:
            return ""
        return event_label(fin.event_date, fin.event_time)

    @staticmethod
    def filed_label(fin: Financial | None) -> str:
        if fin is None:
            return ""
        return filed_label(fin.filed_date)

    # ── Insider transactions (Form 4 + yfinance supplementary) ──────────

    def insider_transactions(
        self,
        within_days: int | None = None,
        open_market_only: bool = False,
        transaction_codes: tuple[str, ...] | None = None,
    ) -> list[InsiderTransactionRecord]:
        """
        Form 4 + yfinance insider trades, most-recent filing-date first.
        within_days: only return rows where filing_date >= today - N
        open_market_only: filter to is_open_market=True
        transaction_codes: filter to specific codes (e.g. ('P',) for purchases only)
        """
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            q = session.query(InsiderTransactionRecord).filter_by(company_id=company.id)
            if within_days is not None:
                q = q.filter(InsiderTransactionRecord.filing_date >= date.today() - timedelta(days=within_days))
            if open_market_only:
                q = q.filter(InsiderTransactionRecord.is_open_market.is_(True))
            if transaction_codes:
                q = q.filter(InsiderTransactionRecord.transaction_type.in_(transaction_codes))
            rows = q.order_by(InsiderTransactionRecord.filing_date.desc()).all()
            for r in rows:
                session.expunge(r)
            return rows

    # ── Price history ───────────────────────────────────────────────────

    def price_history(
        self,
        within_days: int | None = None,
        last_n: int | None = None,
    ) -> list[PriceHistory]:
        """Price rows, most-recent date first. Either window or last-N count."""
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            q = session.query(PriceHistory).filter_by(company_id=company.id)
            if within_days is not None:
                q = q.filter(PriceHistory.date >= date.today() - timedelta(days=within_days))
            q = q.order_by(PriceHistory.date.desc())
            if last_n is not None:
                q = q.limit(last_n)
            rows = q.all()
            for r in rows:
                session.expunge(r)
            return rows

    def latest_price(self) -> PriceHistory | None:
        rows = self.price_history(last_n=1)
        return rows[0] if rows else None

    # ── Short interest history (F4) ─────────────────────────────────────

    def short_interest_history(
        self,
        within_days: int | None = None,
        last_n: int | None = None,
    ) -> list[ShortInterestRecord]:
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            q = session.query(ShortInterestRecord).filter_by(company_id=company.id)
            if within_days is not None:
                q = q.filter(ShortInterestRecord.settlement_date >= date.today() - timedelta(days=within_days))
            q = q.order_by(ShortInterestRecord.settlement_date.desc())
            if last_n is not None:
                q = q.limit(last_n)
            rows = q.all()
            for r in rows:
                session.expunge(r)
            return rows

    # ── Institutional holders (F4) ──────────────────────────────────────

    def institutional_holders(
        self,
        latest_only: bool = True,
        include_aggregate: bool = False,
    ) -> list[InstitutionalHolderRecord]:
        """
        Individual institutional holders. By default returns the most-recent
        report_date snapshot. include_aggregate=True keeps the sentinel
        '_aggregate' row (single-row pct_of_shares_out).
        """
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            q = session.query(InstitutionalHolderRecord).filter_by(company_id=company.id)
            if not include_aggregate:
                q = q.filter(InstitutionalHolderRecord.holder_name != "_aggregate")
            q = q.order_by(InstitutionalHolderRecord.report_date.desc())
            rows = q.all()
            if latest_only and rows:
                latest_date = rows[0].report_date
                rows = [r for r in rows if r.report_date == latest_date]
            for r in rows:
                session.expunge(r)
            return rows

    def institutional_holder_count_history(self) -> list[tuple[date, int]]:
        """Holder count per report_date — used for F4 trend."""
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            from sqlalchemy import func as sa_func
            rows = (
                session.query(
                    InstitutionalHolderRecord.report_date,
                    sa_func.count(InstitutionalHolderRecord.id),
                )
                .filter_by(company_id=company.id)
                .filter(InstitutionalHolderRecord.holder_name != "_aggregate")
                .group_by(InstitutionalHolderRecord.report_date)
                .order_by(InstitutionalHolderRecord.report_date.desc())
                .all()
            )
            return [(d, int(c)) for d, c in rows]

    # ── Analyst coverage (F1 neglect, F4) ───────────────────────────────

    def latest_analyst_coverage(self) -> AnalystCoverageRecord | None:
        with get_session() as session:
            company = self._company(session)
            if not company:
                return None
            row = (
                session.query(AnalystCoverageRecord)
                .filter_by(company_id=company.id)
                .order_by(AnalystCoverageRecord.as_of_date.desc())
                .first()
            )
            if row is not None:
                session.expunge(row)
            return row

    # ── Earnings history (F3 surprise streak, F4 PEAD) ──────────────────

    def earnings_history(self, last_n: int | None = None) -> list[EarningsHistory]:
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            q = (
                session.query(EarningsHistory)
                .filter_by(company_id=company.id)
                .order_by(EarningsHistory.report_date.desc())
            )
            if last_n is not None:
                q = q.limit(last_n)
            rows = q.all()
            for r in rows:
                session.expunge(r)
            return rows

    # ── Internal helpers ────────────────────────────────────────────────

    def _company(self, session: Session) -> Company | None:
        return session.query(Company).filter_by(ticker=self.ticker).first()

    def _financials(
        self, period_filter: str | None, last_n: int | None
    ) -> list[Financial]:
        with get_session() as session:
            company = self._company(session)
            if not company:
                return []
            q = session.query(Financial).filter_by(company_id=company.id)
            if period_filter == "annual":
                q = q.filter(Financial.period == "annual")
            elif period_filter == "quarterly":
                q = q.filter(Financial.period.in_(("Q1", "Q2", "Q3", "Q4")))
            # Order: most-recent fiscal_year first, then annual before Qs within a year
            q = q.order_by(
                Financial.fiscal_year.desc(),
                Financial.period.asc(),    # 'Q1' < 'Q2' < 'Q3' < 'Q4' < 'annual'
            )
            rows = q.all()
            # If both annual and quarterly are present for same FY, push annual to top
            rows.sort(key=lambda r: (-r.fiscal_year, 0 if r.period == "annual" else 1))
            if last_n is not None:
                rows = rows[:last_n]
            for r in rows:
                session.expunge(r)
            return rows
