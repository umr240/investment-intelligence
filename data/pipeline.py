"""
Data refresh pipeline — fully deterministic, zero LLM calls.

Performance architecture:
  Phase 0 (sync, fast)     ensure Company row exists; load Tier-0 source-log
  Phase 1 (asyncio.gather) EDGAR fundamentals + EDGAR Form 4 + yfinance full
                           snapshot — independent table writes, run in parallel
  Phase 2 (sync, fast)     bulk persist Phase 1 results
  Phase 3 (sync)           F6 — needs latest annual Financial row to exist
  Phase 4 (sync)           derived metrics (buyback yield needs both EDGAR
                           share_repurchases and yfinance market_cap)

Data sources (all deterministic, zero LLM):
  - SEC companyfacts.json    → 20yr+ fundamentals in 1 HTTP call (Phase A)
  - EDGAR Form 4 (50)        → insider transactions
  - EDGAR DEF 14A HTML       → CEO equity % (BeautifulSoup table parsing)
  - EDGAR 10-K text          → founder regex, customer concentration regex
  - yfinance .info / etc.    → company profile, ownership %, holders, prices,
                                 analyst consensus

NO LLM calls anywhere in this module. NO ANTHROPIC_API_KEY required for the
data or screener paths. AI usage is restricted to deepdive/narrative.py
(Phase 6). FMP and Alpha Vantage are NOT used.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Any

from data.db import get_session
from data.models.schema import (
    AnalystCoverageRecord,
    Company,
    EarningsHistory,
    Financial,
    FinancialSourceLog,
    InsiderTransactionRecord,
    InstitutionalHolderRecord,
    PriceHistory,
    ShortInterestRecord,
)
from config.constants import DEFAULT_HISTORY_YEARS

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────


async def refresh_ticker(
    ticker: str,
    force_refresh: bool = False,
    years: int = DEFAULT_HISTORY_YEARS,
    requirement: Any | None = None,
) -> list[str]:
    """
    Fetch data for ticker and persist to DB. Framework-aware lazy load.

    Pass `requirement: DataRequirement` from frameworks.base to fetch only the
    minimum superset needed by the selected frameworks. If `requirement` is
    omitted, falls back to a kitchen-sink fetch bounded by `years`.

    Three-tier lazy load on the EDGAR fundamentals path:
      1. Year-coverage gate (DB read, 0 network) — compute missing fiscal years
         from the requirement's annual_years window. If nothing's missing,
         fall through to step 2.
      2. Submissions.json probe (~50-200KB GET) — confirm no new 10-K has been
         filed since last refresh. If no new filing, SKIP companyfacts
         entirely (0 EDGAR calls).
      3. Companyfacts fetch (~5MB) — only when (1) finds gaps OR (2) finds
         new filings. Parser materializes ONLY the missing fiscal years.

    Per-task gating from the requirement:
      annual_years > 0           → EDGAR companyfacts fetch (gated above)
      needs_insider_transactions → Form 4 fetch (skipped otherwise)
      needs_proxy_ownership      → DEF 14A HTML fetch (skipped otherwise)
      needs_customer_concentration → 10-K text + XBRL (skipped otherwise)
      price_history_years > 0    → yfinance .history() (skipped otherwise)

    yfinance .info / ownership / analyst always runs (single small call,
    populates company profile + valuation snapshots).
    """
    from frameworks.base import DataRequirement, kitchen_sink_requirement

    ticker = ticker.upper()
    if requirement is None:
        requirement = kitchen_sink_requirement(years)
    elif not isinstance(requirement, DataRequirement):
        raise TypeError(
            f"requirement must be a DataRequirement, got {type(requirement).__name__}"
        )

    logger.info(
        "refresh_ticker: %s (force=%s, annual_years=%d, qcount=%d, price=%dyr)",
        ticker, force_refresh, requirement.annual_years,
        requirement.quarterly_count, requirement.price_history_years,
    )
    gaps: list[str] = []
    loop = asyncio.get_event_loop()

    # ── Phase 0: ensure Company row exists ────────────────────────────────
    _ensure_company_row(ticker)

    # ── Phase 0.5: resolve the fundamentals source (ADR-039) ──────────────
    # The pipeline depends on the FundamentalsSource PORT, not on a concrete
    # fetcher (Dependency Inversion). The SEC adapter owns CIK resolution, the
    # Tier-0 accession cache, the year-coverage gate, and fiscal-year-end
    # handling — all SEC-specific. Non-SEC adapters (yfinance Tier-3 today;
    # SEDAR+ Tier-1B once Phase C lands) ignore that machinery and source via
    # their own wire format. resolve_source routes by exchange suffix.
    from data.sources import resolve_source
    from data.sources.jurisdiction import REGIME_SEC_XBRL, jurisdiction_for
    source = resolve_source(ticker, None)

    # ADR-041: Form 4, 10-K text and DEF 14A are SEC ARTIFACTS. A Swedish or
    # Canadian issuer has none by construction, so firing these at a non-SEC
    # ticker spends six network round trips to log six "Company not found"
    # warnings — noise that reads like a bug and buries real gaps. Gate them
    # on the jurisdiction's filing regime, not just on DataRequirement.
    sec_filer = jurisdiction_for(ticker).regime == REGIME_SEC_XBRL

    # ── Phase 1: parallel fetch (each task gated by requirement) ──────────
    from data.edgar_fetcher import (
        fetch_edgar_insiders,
        fetch_latest_10k_filing,
    )
    from data.api.yfinance_client import fetch_yfinance_snapshot

    # Fundamentals via the resolved source. The adapter returns an awaitable
    # that joins the same asyncio.gather as the other Phase-1 tasks, preserving
    # the original parallelism. The SEC adapter applies the year-coverage gate
    # internally; non-SEC adapters fetch unconditionally (no accession cache).
    fundamentals_task: Any = source.fetch(ticker, requirement, force_refresh=force_refresh)

    # Form 4 insiders (gated by requirement AND by SEC jurisdiction)
    if requirement.needs_insider_transactions and sec_filer:
        insiders_task: Any = loop.run_in_executor(
            None, partial(fetch_edgar_insiders, ticker, 50)
        )
    else:
        async def _empty_insiders() -> list:
            return []
        insiders_task = _empty_insiders()

    # yfinance snapshot — always runs (single small call), but the heavy
    # `.history()` download is gated by price_history_years.
    yf_years = requirement.price_history_years
    yfinance_task = loop.run_in_executor(
        None, lambda: fetch_yfinance_snapshot(ticker, yf_years)
    )

    # Latest 10-K filing object — needed only if F6/customer/founder
    needs_10k = sec_filer and (
        requirement.needs_customer_concentration
        or requirement.needs_proxy_ownership
        or requirement.needs_founder_status
    )
    if needs_10k:
        latest_10k_task: Any = loop.run_in_executor(
            None, partial(fetch_latest_10k_filing, ticker)
        )
    else:
        async def _empty_10k() -> Any:
            return None
        latest_10k_task = _empty_10k()

    # ADR-018 Branch F: FMP /stable/profile (CEO name, IPO date, CIK).
    # Always runs — one HTTP call, free-tier-cheap. If FMP_API_KEY is unset
    # or the call fails (HTTP 402 small-cap escalation), we get an
    # FMPProfile with `error` set and the dive falls back to yf+edgartools.
    fmp_profile_task = loop.run_in_executor(
        None, lambda: _fetch_fmp_profile_safe(ticker)
    )

    # ADR-019 Branch G+H: Polygon weekly prices (P1) + short-interest history (P3).
    # Opt-in via POLYGON_API_KEY. Free tier 5/min — TokenBucket-throttled
    # internally so concurrent Polygon calls won't blow the rate limit.
    # If POLYGON_API_KEY is unset OR Polygon fails, the dive falls back to
    # yfinance price history. Polygon NEVER replaces SEC fundamentals or
    # edgartools governance signals.
    polygon_task = loop.run_in_executor(
        None, lambda: _fetch_polygon_safe(ticker, requirement.price_history_years)
    )

    edgar_result, insider_rows, yf_snapshot, latest_10k, fmp_profile, polygon_data = await asyncio.gather(
        fundamentals_task,
        insiders_task,
        yfinance_task,
        latest_10k_task,
        fmp_profile_task,
        polygon_task,
    )

    gaps.extend(edgar_result.gaps)
    gaps.extend(yf_snapshot.gaps)

    # ── Phase 2: bulk persist Phase 1 results ─────────────────────────────
    if edgar_result.financials:
        _persist_financials(ticker, edgar_result.financials)
        upgraded = _persist_source_log(
            ticker, edgar_result.financials, reparsed=edgar_result.reparsed
        )
        if upgraded:  # a same-parser --force re-read upgrades nothing and flags nothing
            gaps.extend(_flag_dives_after_reparse(ticker))
        # ADR-039: persist non-SEC provenance (data_source_tier, reporting
        # currency, FX) so the dive methodology panel + data_completeness
        # reflect Tier-3 sourcing. SEC rows keep the 'sec_edgar' default.
        if source.name != "sec_edgar":
            _persist_source_provenance(ticker, edgar_result)
    # Cold-fetch "no fundamentals — check spelling" warning is emitted by the
    # SEC adapter itself (so it never fires on a warm-cache skip) and arrives
    # via edgar_result.gaps, already folded into `gaps` above.

    if requirement.needs_insider_transactions:
        if insider_rows:
            _persist_insiders_bulk(ticker, insider_rows, source="edgar")
        elif sec_filer:
            gaps.append(f"{ticker}: no Form 4 insider transactions found on EDGAR")
        else:
            # Distinguish "we looked and found none" from "this disclosure
            # regime does not exist here" — they mean different things to F1
            # and to the reader (ADR-031 gap register).
            jur = jurisdiction_for(ticker)
            gaps.append(
                f"{ticker}: insider transactions unavailable — {jur.venue} issuers "
                f"file no SEC Form 4 (jurisdiction {jur.country}, regime {jur.regime})"
            )

    yf_gaps = _persist_yfinance_snapshot(ticker, yf_snapshot)
    gaps.extend(yf_gaps)

    # ADR-019: persist Polygon rows AFTER yfinance — Polygon UPSERTs with
    # source='polygon' overwrite the yfinance row when same (company_id,
    # date). Failure of Polygon does NOT block — yfinance rows already
    # landed and F2 reads from price_history regardless of source.
    if polygon_data is not None:
        polygon_gaps = _persist_polygon_data(ticker, polygon_data)
        gaps.extend(polygon_gaps)

    # ── Phase 3: F6 deterministic signals (gated, needs latest annual to exist) ──
    # SEC-only: these parse 10-K text and DEF 14A HTML, which non-SEC filers
    # do not produce. ESEF Phase-1 block-tags the notes, so the equivalent
    # signals are not extractable there either — they stay explicit gaps.
    if sec_filer and (
        requirement.needs_customer_concentration
        or requirement.needs_proxy_ownership
        or requirement.needs_founder_status
    ):
        try:
            f6_gaps = await _fetch_f6_signals(ticker, latest_10k, requirement)
            gaps.extend(f6_gaps)
        except Exception as exc:
            gaps.append(f"{ticker}: F6 signal fetch failed — {exc}")

    # ── Phase 3.5: ADR-018 reconciliation across sources ──────────────────
    # Fold FMP + yfinance + edgartools sources into the 3-state columns.
    # Runs after Phase 2 (yf snapshot wrote yf-side ceo_name, ipo_date) and
    # Phase 3 (F6 wrote edgartools peo_name, ceo_equity_pct, founder).
    try:
        _apply_adr018_reconciliation(ticker, yf_snapshot, fmp_profile)
    except Exception as exc:
        logger.debug("ADR-018 reconciliation failed (%s): %s", ticker, exc)

    # ── Phase 4: derived metrics needing data from multiple sources ───────
    try:
        _compute_buyback_yields(ticker)
    except Exception as exc:
        logger.debug("buyback_yield compute (%s): %s", ticker, exc)

    try:
        _record_share_split_basis(ticker)
    except Exception as exc:
        logger.debug("share split basis (%s): %s", ticker, exc)

    logger.info("refresh_ticker: %s complete. %d gaps.", ticker, len(gaps))
    return gaps


async def get_data_gaps(ticker: str) -> list[str]:
    """
    Inspect the DB and report which data fields are missing or stale for a ticker.
    No API calls — reads DB only.
    """
    ticker = ticker.upper()
    gaps: list[str] = []

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return [f"{ticker}: not in database — run 'invest data refresh {ticker}' first"]

        fin_count = session.query(Financial).filter_by(company_id=company.id).count()
        if fin_count == 0:
            gaps.append(f"{ticker}: no financial rows — EDGAR fetch needed")
        else:
            annual_count = (
                session.query(Financial)
                .filter_by(company_id=company.id, period="annual")
                .count()
            )
            if annual_count < 3:
                gaps.append(
                    f"{ticker}: only {annual_count} annual periods (need ≥3 for trend analysis)"
                )

            # Staleness guard (2026-05-17). Flags tickers whose latest annual
            # is more than 16 months old — strong signal we missed a filing.
            # Continuously-filing US issuers file 10-Ks within ~90 days of FY-end
            # (60 for large accelerated, 75 accelerated, 90 non-accelerated),
            # so latest annual should be at most ~15 months stale during the lag.
            # 16-month threshold = 15 months + 1-month buffer. Beyond that →
            # likely parser miss (ILMN/LULU fiscal-calendar-transition pattern).
            from datetime import date as _date
            latest_annual = (
                session.query(Financial)
                .filter_by(company_id=company.id, period="annual")
                .filter(Financial.period_end_date.isnot(None))
                .order_by(Financial.period_end_date.desc())
                .first()
            )
            if latest_annual and latest_annual.period_end_date:
                months_stale = (
                    (_date.today().year - latest_annual.period_end_date.year) * 12
                    + (_date.today().month - latest_annual.period_end_date.month)
                )
                if months_stale > 16:
                    gaps.append(
                        f"{ticker}: latest annual is {months_stale} months stale "
                        f"(FY{latest_annual.fiscal_year} ending {latest_annual.period_end_date}). "
                        f"Continuous filers should be ≤15 months. Likely a parser miss — "
                        f"check whether `fiscal_year_end_month={company.fiscal_year_end_month}` "
                        f"matches recent filings; ILMN/LULU-style fiscal-calendar transition "
                        f"may need investigation. Run `invest data refresh {ticker} --force`."
                    )

                # Off-by-one fiscal_year label guard: when the stored fiscal_year
                # differs from period_end_date.year by more than 1, the parser
                # is likely mislabeling (transition case where stored
                # fiscal_year_end_month doesn't match actual filings).
                year_lag = abs(latest_annual.fiscal_year - latest_annual.period_end_date.year)
                if year_lag > 1:
                    gaps.append(
                        f"{ticker}: fiscal_year label drift — FY{latest_annual.fiscal_year} "
                        f"on period ending {latest_annual.period_end_date} "
                        f"(|lag|={year_lag} years > 1). Stored fiscal_year_end_month="
                        f"{company.fiscal_year_end_month} may be stale; consider updating."
                    )

        if session.query(InsiderTransactionRecord).filter_by(company_id=company.id).count() == 0:
            gaps.append(f"{ticker}: no insider transactions (Form 4 not fetched)")

        if session.query(EarningsHistory).filter_by(company_id=company.id).count() == 0:
            gaps.append(
                f"{ticker}: no earnings surprise history "
                "(yfinance earnings_history not fetched)"
            )

        price_count = session.query(PriceHistory).filter_by(company_id=company.id).count()
        if price_count == 0:
            gaps.append(f"{ticker}: no price history (yfinance not fetched)")
        elif price_count < 52:
            gaps.append(
                f"{ticker}: only {price_count} price rows (need ≥52 weeks for momentum)"
            )

        if company.sector is None:
            gaps.append(f"{ticker}: sector unknown — yfinance profile not fetched")
        if company.ceo_equity_pct is None:
            gaps.append(f"{ticker}: ceo_equity_pct not extracted (DEF 14A HTML table parse)")
        if company.is_founder_ceo is None:
            gaps.append(f"{ticker}: is_founder_ceo unknown (no founder regex match)")

    return gaps


async def refresh_watchlist_signals() -> dict[str, list[str]]:
    """
    Mid-quarter refresh (yfinance snapshot only — short interest + institutional %)
    for active watchlist tickers. Snapshots accumulate over time → F4 trend signals.
    Called by the monthly scheduler job.
    """
    from data.models.schema import WatchlistEntry

    with get_session() as session:
        tickers: list[str] = [
            row[0]
            for row in (
                session.query(Company.ticker)
                .join(WatchlistEntry, WatchlistEntry.company_id == Company.id)
                .filter(WatchlistEntry.is_active.is_(True))
                .all()
            )
        ]

    sem = asyncio.Semaphore(10)

    async def _refresh_one(ticker: str) -> tuple[str, list[str]]:
        async with sem:
            from data.api.yfinance_client import fetch_yfinance_snapshot
            loop = asyncio.get_event_loop()
            snapshot = await loop.run_in_executor(
                None, lambda: fetch_yfinance_snapshot(ticker, 0)
            )
            gaps = _persist_yfinance_snapshot(ticker, snapshot)
            return ticker, snapshot.gaps + gaps

    pairs = await asyncio.gather(*[_refresh_one(t) for t in tickers])
    return dict(pairs)


# ── Phase 0 helpers ───────────────────────────────────────────────────────


def _ensure_company_row(ticker: str) -> None:
    """Create the Company row up-front so Phase 1 tasks can write concurrently."""
    with get_session() as session:
        existing = session.query(Company).filter_by(ticker=ticker).first()
        if not existing:
            session.add(Company(
                ticker=ticker,
                exchange="",
                name=ticker,
                listing_type="standard",
            ))


def _resolve_filer_metadata(ticker: str) -> dict[str, Any] | None:
    """
    Resolve a ticker → CIK and fetch filer metadata (fiscal year end, name,
    exchanges) from SEC submissions.json. One small HTTP call (~50-200KB)
    + edgartools CIK lookup. Returns the metadata dict (see
    edgar_companyfacts.fetch_filer_metadata) or None on failure.

    Persists the CIK on the Company row so subsequent calls don't have to
    re-resolve it through edgartools.
    """
    # First, try the cached CIK on the Company row (fast path).
    cik: int | None = None
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if company and company.cik:
            try:
                cik = int(company.cik)
            except (TypeError, ValueError):
                cik = None

    if cik is None:
        try:
            from edgar import Company as _EdgarCompany
            from edgar.core import set_identity

            from config.settings import require_edgar_identity
            identity = require_edgar_identity()
            set_identity(identity)
            cik = int(getattr(_EdgarCompany(ticker), "cik", 0) or 0)
        except Exception as exc:
            logger.debug("CIK resolve failed for %s: %s", ticker, exc)
            return None
        if cik <= 0:
            return None
    else:
        from config.settings import require_edgar_identity
        identity = require_edgar_identity()

    try:
        from data.edgar_companyfacts import fetch_filer_metadata
        meta = fetch_filer_metadata(cik, identity)
    except Exception as exc:
        logger.debug("filer metadata fetch failed for %s (CIK %d): %s", ticker, cik, exc)
        return None

    if meta is None:
        # Couldn't fetch submissions.json but we have the CIK — return that
        # alone so the caller can still persist it.
        return {"cik": cik, "fiscal_year_end_month": None, "name": None,
                "tickers": [], "exchanges": [], "fiscal_year_end": None,
                "sic": None, "sic_description": None}
    return meta


def _persist_filer_metadata(ticker: str, meta: dict[str, Any]) -> None:
    """Write CIK + fiscal_year_end_month onto the Company row."""
    cik = meta.get("cik")
    fyem = meta.get("fiscal_year_end_month")
    name = meta.get("name")
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return
        if cik is not None:
            # Store as zero-padded 10-digit string per the schema comment
            company.cik = str(int(cik)).zfill(10)
        if fyem is not None:
            company.fiscal_year_end_month = int(fyem)
        if name and (not company.name or company.name == ticker):
            company.name = name


def _persist_source_provenance(ticker: str, result: Any) -> None:
    """ADR-039: tag a non-SEC ticker's Company + Financial rows with their
    data source. Writes ``Company.data_source_tier`` + ``currency`` and stamps
    ``Financial.fx_rate_to_usd`` on every row for this ticker, so downstream
    completeness scoring and the methodology panel reflect Tier-3 sourcing.
    """
    tier = getattr(result, "source_tier", None)
    currency = getattr(result, "reporting_currency", None)
    fx = getattr(result, "fx_rate_to_usd", None)
    metadata = getattr(result, "metadata", None) or {}
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return
        if tier:
            company.data_source_tier = tier
        if currency:
            company.currency = currency
            # ADR-041: currency provenance follows the source that reported it.
            # An ESEF filing's iso4217 unit is filing-grade, not a yfinance guess.
            company.currency_source = "esef" if tier == "esef" else "yfinance"
        # ADR-041: cache the resolved LEI so the next ESEF refresh skips the
        # GLEIF identity hop entirely (lazy-load: pay for identity once).
        lei = metadata.get("lei")
        if lei and not getattr(company, "lei", None):
            company.lei = lei
        if fx is not None:
            for fin in session.query(Financial).filter_by(company_id=company.id).all():
                fin.fx_rate_to_usd = fx


def _load_known_accessions(ticker: str) -> frozenset[str]:
    """
    Tier-0 cache: accessions already parsed for this ticker by the CURRENT
    parser. Phase A's companyfacts parser skips these; older ones are re-read.
    """
    from data.edgar_companyfacts import PARSER_VERSION

    with get_session() as session:
        rows = (
            session.query(FinancialSourceLog.accession_number)
            .filter_by(ticker=ticker, parser_version=PARSER_VERSION)
            .all()
        )
        return frozenset(row[0] for row in rows if row[0])


def _stale_parse_count(ticker: str, since_year: int | None = None) -> int:
    """Logged accessions read by an older parser (or before versioning).

    `since_year` limits the count to the window a refresh would read, so years
    outside it do not force a re-read they could not repair.
    """
    from data.edgar_companyfacts import PARSER_VERSION

    with get_session() as session:
        q = (
            session.query(FinancialSourceLog)
            .filter(FinancialSourceLog.ticker == ticker)
            .filter(
                (FinancialSourceLog.parser_version.is_(None))
                | (FinancialSourceLog.parser_version < PARSER_VERSION)
            )
        )
        if since_year is not None:
            q = q.filter(FinancialSourceLog.fiscal_year >= since_year)
        return q.count()


@dataclass
class CoverageDecision:
    fetch_fundamentals: bool
    keep_only_years: frozenset[int] | None
    reason: str
    reparse: bool = False  # read every filing again, ignoring the Tier-0 cache
    cold: bool = False  # the ticker has no stored annuals yet


def _existing_annual_years(ticker: str) -> set[int]:
    """Return the set of fiscal years for which we have an `annual` Financial row."""
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return set()
        rows = (
            session.query(Financial.fiscal_year)
            .filter_by(company_id=company.id, period="annual")
            .all()
        )
        return {y for (y,) in rows if y}


def _existing_quarter_count(ticker: str) -> int:
    """Return how many quarterly (Q1–Q4) Financial rows the ticker has."""
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return 0
        return (
            session.query(Financial)
            .filter(Financial.company_id == company.id, Financial.period != "annual")
            .count()
        )


def _decide_companyfacts_fetch(
    ticker: str,
    years: int,
    force_refresh: bool,
    known_accessions: frozenset[str],
    quarters: int = 0,
) -> CoverageDecision:
    """
    Year- and quarter-coverage gate. Four outcomes:

    a) FETCH ALL needed (cold cache or partial gap):
       fetch_fundamentals=True, keep_only_years={missing FYs}.
       Parser materializes ONLY those missing years — never re-parses years
       we already have, even if companyfacts returns full history.

    b) FULL COVERAGE BUT POSSIBLY NEW FILINGS:
       Probe SEC submissions.json (~50-200KB, fast). If the latest 10-K
       accession is in our FinancialSourceLog → SKIP companyfacts entirely.
       Otherwise → fetch (a new fiscal year was filed; parser will catch it
       via skip_accessions).

    c) FORCE REFRESH:
       Always fetch. Pass keep_only_years=None so the full requested window
       gets re-parsed. skip_accessions is empty in force mode (caller's job).

    d) PARSER UPGRADE (filings in the requested window logged by an older
       PARSER_VERSION): reparse=True. Every filing is read again, as in force
       mode; reading only the stale ones would rebuild rows from superseded
       filings alone. Checked before (e) for the same reason.

    e) QUARTERLY GAP (fewer than `quarters` Q rows): fetch_fundamentals=True,
       keep_only_years=None. A year filter would drop the recent quarters.
    """
    if force_refresh:
        return CoverageDecision(
            fetch_fundamentals=True, keep_only_years=None,
            reason="force_refresh", reparse=True,
            cold=not _existing_annual_years(ticker),
        )

    existing = _existing_annual_years(ticker)
    if not existing:
        # Cold cache for this ticker → fetch everything in the requested window.
        return CoverageDecision(
            fetch_fundamentals=True, keep_only_years=None,
            reason="cold cache (no Financial rows for ticker)", cold=True,
        )

    # Anchor `needed` on max(latest_have, current_calendar_year). Without
    # this, once the DB has any annuals the gate would only ask for years
    # ≤ latest_have, so newly-filed 10-Ks (FY > latest_have) would never
    # enter `missing` and never be fetched — even when SEC has them.
    # 2026-05-17 ILMN bug: had FY2023 latest; SEC had FY2024/FY2025 filed;
    # gate computed needed={2014..2023} and missing={2018,2020} only.
    # Fix: forward window must extend to current calendar year.
    from datetime import date as _date
    current_year = _date.today().year
    forward_anchor = max(max(existing), current_year)
    window_start = forward_anchor - years + 1

    # Before the quarterly check: any partial read would rebuild rows from
    # stale filings alone, so a parser upgrade always re-reads in full.
    stale = _stale_parse_count(ticker, since_year=window_start)
    if stale:
        return CoverageDecision(
            fetch_fundamentals=True,
            keep_only_years=None,
            reason=f"parser upgraded: {stale} filings were read by an older parser",
            reparse=True,
        )

    have_q = _existing_quarter_count(ticker) if quarters else 0
    if have_q < quarters:
        return CoverageDecision(
            fetch_fundamentals=True, keep_only_years=None,
            reason=f"quarterly gap: have {have_q}Q, need {quarters}Q",
        )

    needed: frozenset[int] = frozenset(range(window_start, forward_anchor + 1))
    missing: frozenset[int] = frozenset(needed - existing)

    if missing:
        return CoverageDecision(
            fetch_fundamentals=True, keep_only_years=missing,
            reason=f"gap: missing FYs {sorted(missing)}",
        )

    # Full year coverage in DB. Probe submissions.json for new filings.
    probe = _probe_new_filings(ticker, known_accessions)
    if probe is None:
        # Probe failed (network or no CIK) — fetch to be safe.
        return CoverageDecision(
            fetch_fundamentals=True, keep_only_years=None,
            reason="submissions probe inconclusive — defensive fetch",
        )
    if probe:
        return CoverageDecision(
            fetch_fundamentals=True, keep_only_years=None,
            reason=f"new filing detected (accn={probe})",
        )
    return CoverageDecision(
        fetch_fundamentals=False, keep_only_years=None,
        reason="full coverage + no new 10-K filed",
    )


def _probe_new_filings(ticker: str, known_accessions: frozenset[str]) -> str | None | bool:
    """
    Hit SEC submissions.json (~50-200KB) and check if the most recent annual
    filing's accession is already in our FinancialSourceLog.

    Returns:
      - accession_number (str)  → a NEW filing exists not in our log
      - False                    → latest filing accession is already in our log
      - None                     → probe failed (CIK lookup or HTTP error)
    """
    try:
        from edgar import Company as _EdgarCompany
        from edgar.core import set_identity

        from config.settings import require_edgar_identity
        identity = require_edgar_identity()
        set_identity(identity)
        cik = int(getattr(_EdgarCompany(ticker), "cik", 0) or 0)
        if cik == 0:
            return None
    except Exception as exc:
        logger.debug("submissions probe: CIK lookup failed (%s): %s", ticker, exc)
        return None

    try:
        from data.edgar_companyfacts import fetch_latest_filings
        recent = fetch_latest_filings(cik, identity, limit=3)
    except Exception as exc:
        logger.debug("submissions probe error (%s): %s", ticker, exc)
        return None

    if not recent:
        return None

    for entry in recent:
        accn = entry.get("accession_number") or ""
        if accn and accn not in known_accessions:
            return accn
    return False


# ── Persistence (bulk patterns, single SELECT for dedup) ──────────────────


def _persist_financials(ticker: str, rows: list[Any]) -> None:
    from data.edgar_fetcher import EdgarFinancialRow
    if not rows:
        return
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return

        # Build existing-key set with one query
        existing_keys: set[tuple[int, str]] = {
            (year, period)
            for year, period in session.query(
                Financial.fiscal_year, Financial.period
            ).filter_by(company_id=company.id).all()
        }

        new_rows: list[Financial] = []
        for row in rows:
            if not isinstance(row, EdgarFinancialRow) or not row.fiscal_year:
                continue
            key = (row.fiscal_year, row.period)
            if key in existing_keys:
                # Update in place — restatement may have changed values
                fin = (
                    session.query(Financial)
                    .filter_by(company_id=company.id, fiscal_year=row.fiscal_year, period=row.period)
                    .first()
                )
                if fin:
                    _apply_financial_row(fin, row)
            else:
                fin = Financial(
                    company_id=company.id,
                    fiscal_year=row.fiscal_year,
                    period=row.period,
                )
                _apply_financial_row(fin, row)
                new_rows.append(fin)
                existing_keys.add(key)

        if new_rows:
            session.add_all(new_rows)


def _apply_financial_row(obj: Financial, row: Any) -> None:
    """
    Copy raw fields + compute every derived ratio. Frameworks should never
    re-derive these — read them straight from the Financial row.
    """
    obj.source = row.source
    obj.period_end_date = getattr(row, "period_end_date", None)
    obj.period_start_date = getattr(row, "period_start_date", None)
    obj.filed_date = getattr(row, "filed_date", None)
    # Separated time concepts (TradingView/Finviz pattern):
    # - event_date: when the market reacts (mirrors SEC reportDate; for
    #   companyfacts entries we don't have a separate reportDate, so use
    #   filed_date as the catalyst proxy. Earnings rows set this directly
    #   to the press-release date.)
    # - fiscal_year_label_basis: 'end' = our convention (FY = year period
    #   ends in). Documents which convention produced the fiscal_year column.
    # - source_timezone: SEC filings are timestamped US/Eastern.
    obj.event_date = getattr(row, "filed_date", None) or getattr(row, "period_end_date", None)
    obj.event_time = None    # 10-K/Q have no intraday timestamp; earnings rows set this
    obj.fiscal_year_label_basis = "end"
    obj.source_timezone = "US/Eastern"
    obj.revenue = row.revenue
    obj.cost_of_revenue = row.cost_of_revenue
    obj.gross_profit = row.gross_profit
    obj.gross_margin = row.gross_margin
    obj.operating_income = row.operating_income
    obj.operating_expenses = row.operating_expenses
    obj.net_income = row.net_income
    obj.ebitda = row.ebitda
    obj.rd_expense = row.rd_expense
    obj.rd_disclosure_state = getattr(row, "rd_disclosure_state", None)
    obj.sga_expense = row.sga_expense
    obj.interest_expense = getattr(row, "interest_expense", None)
    obj.income_tax_expense = getattr(row, "income_tax_expense", None)
    obj.depreciation_amortization = getattr(row, "depreciation_amortization", None)
    obj.funds_held_for_clients = getattr(row, "funds_held_for_clients", None)
    obj.investment_income_interest = getattr(row, "investment_income_interest", None)
    # Phase 5R-1: data-quality signals — absolute SBC + goodwill, plus
    # derived intensity / concentration percentages for convenience.
    obj.share_based_compensation = getattr(row, "share_based_compensation", None)
    obj.goodwill = getattr(row, "goodwill", None)
    obj.operating_cash_flow = row.operating_cash_flow
    obj.free_cash_flow = row.free_cash_flow
    obj.capex = row.capex
    obj.total_assets = row.total_assets
    obj.total_equity = row.total_equity
    obj.total_debt = row.total_debt
    obj.long_term_debt = row.long_term_debt
    obj.cash_and_equivalents = row.cash_and_equivalents
    obj.short_term_investments = getattr(row, "short_term_investments", None)
    obj.accounts_receivable = row.accounts_receivable
    obj.current_assets = row.current_assets
    obj.current_liabilities = row.current_liabilities
    obj.inventory = getattr(row, "inventory", None)
    obj.shares_outstanding = row.shares_outstanding
    obj.eps_diluted = row.eps_diluted
    obj.eps_basic = getattr(row, "eps_basic", None)
    obj.dividends_paid = getattr(row, "dividends_paid", None)
    obj.share_repurchases = getattr(row, "share_repurchases", None)

    rev = row.revenue
    ni = row.net_income
    ta = row.total_assets
    te = row.total_equity
    td = row.total_debt
    oi = row.operating_income
    ocf = row.operating_cash_flow
    fcf = row.free_cash_flow
    gp = row.gross_profit
    ebitda = row.ebitda
    rd = row.rd_expense
    ie = getattr(row, "interest_expense", None)
    tax = getattr(row, "income_tax_expense", None)
    cs = row.cash_and_equivalents
    sti = getattr(row, "short_term_investments", None)
    ca = row.current_assets
    cl = row.current_liabilities

    # ── ROIC (Phase 5k / DEC-31, refined 5S-5) ──────────────────────────────
    # Textbook GAAP ROIC = NOPAT / IC where:
    #   NOPAT = EBIT × (1 − effective_tax_rate)
    #   IC    = Total Equity + Total Debt − Cash − Short-Term Investments
    #
    # Phase 5S-5 (excess-capital exclusion): IC now subtracts marketable
    # securities (AFS debt securities + ShortTermInvestments) as well as
    # cash. McKinsey/Stewart/Mauboussin all treat these as excess capital —
    # they earn the risk-free rate, not operating returns, so they don't
    # deserve a cost-of-capital charge. Pre-5S-5 HIMS's $700M AFS portfolio
    # inflated IC by ~50% and dragged ROIC down spuriously; NVDA's $32B
    # portfolio dragged its ROIC by ~10pp.
    #
    # Total Debt already includes ASC 842 operating-lease liabilities (rolled
    # up by edgar_companyfacts.py:643-655). Goodwill stays in IC via
    # Total Equity per Stewart/McKinsey/Mauboussin standard — stripping it
    # would flatter serial acquirers (the exact pattern F5 is meant to
    # reward on disciplined capital allocation, not double-count).
    #
    # 5k-5 float disclosure: investment_income_interest and
    # funds_held_for_clients are persisted on this Financial row so the
    # dive renderer + warehouse rollup can surface them transparently and
    # apply industry-aware adjustments. The per-period ROIC stored here
    # is intentionally INDUSTRY-BLIND (operating-income-as-reported) —
    # insurers (where investment income IS the business) keep float
    # in numerator, non-insurers (PAYC, ADP) subtract it at the rollup
    # layer where industry classification is available. See
    # `_render_roic_summary` and `_rollup_warehouse_columns`.
    invested_capital = (te or 0.0) + (td or 0.0) - (cs or 0.0) - (sti or 0.0)
    etr = _effective_tax_rate(ni, tax)
    nopat = (oi * (1 - etr)) if oi is not None else None
    obj.roic = (
        (nopat / invested_capital)
        if (nopat is not None and invested_capital and invested_capital > 0)
        else None
    )
    obj.pretax_roic = (
        (oi / invested_capital)
        if (oi is not None and invested_capital and invested_capital > 0)
        else None
    )
    obj.roe = (ni / te) if (ni and te) else None
    obj.roa = (ni / ta) if (ni and ta) else None
    obj.gp_a = (gp / ta) if (gp is not None and ta) else None
    obj.net_margin = (ni / rev) if (ni is not None and rev) else None
    obj.operating_margin = (oi / rev) if (oi is not None and rev) else None
    obj.fcf_margin = (fcf / rev) if (fcf is not None and rev) else None
    obj.rd_intensity = (rd / rev) if (rd is not None and rev) else None
    obj.asset_turnover = (rev / ta) if (rev is not None and ta) else None
    obj.debt_to_equity = (td / te) if (td is not None and te) else None
    # Phase 5S-5: net_debt + Debt/EBITDA on net basis.
    # net_debt = total_debt − cash − short_term_investments. When net_debt
    # ≤ 0 (net-cash position), Debt/EBITDA is clamped to 0.0 by convention:
    # the ratio is undefined / inverted for the cash-rich case, and
    # rendering a negative ratio as "leverage" is misleading. The pre-5S-5
    # behaviour (gross total_debt / EBITDA) reported HIMS as 7x leveraged
    # when economically net-cash, and NVDA as 0.09x when actually net-cash
    # by $30B+.
    if td is not None:
        net_debt_val = td - (cs or 0.0) - (sti or 0.0)
    else:
        net_debt_val = None
    obj.net_debt = net_debt_val
    if ebitda is not None and ebitda > 0 and net_debt_val is not None:
        obj.debt_to_ebitda = max(net_debt_val / ebitda, 0.0)
    else:
        obj.debt_to_ebitda = None
    obj.current_ratio = (ca / cl) if (ca is not None and cl) else None
    obj.interest_coverage = (oi / ie) if (oi is not None and ie) else None
    obj.accruals_ratio = (
        ((ni - ocf) / ta) if (ni is not None and ocf is not None and ta) else None
    )
    # Phase 5R-1: derived data-quality ratios. SBC intensity and goodwill
    # concentration. Both are simple ratios over the same period; computed
    # here to avoid re-deriving every time F5 / DEC-34 read them.
    sbc = getattr(row, "share_based_compensation", None)
    gw = getattr(row, "goodwill", None)
    obj.sbc_pct_of_revenue = (
        (sbc / rev) if (sbc is not None and rev and rev > 0) else None
    )
    obj.goodwill_pct_of_assets = (
        (gw / ta) if (gw is not None and ta and ta > 0) else None
    )


_STATUTORY_TAX_RATE = 0.21    # US federal C-corp statutory rate
_ETR_CLAMP_LO = 0.0           # negative ETR = NOL benefit; not normal-state
_ETR_CLAMP_HI = 0.40          # > 40% usually means data error or one-time items


def _effective_tax_rate(net_income: float | None, tax: float | None) -> float:
    """Derive ETR from income_tax_expense / pretax_income.

    pretax_income = net_income + income_tax_expense (when tax positive).
    Falls back to statutory 21% when:
      - either input is None
      - pretax_income ≤ 0 (loss-making period — NOL benefit not normal-state)
      - resulting ETR is outside [0, 40%] (likely data error)

    Used by the per-period ROIC computation in `_apply_financial_row`. A
    company-wide single ETR is intentionally NOT computed here — each fiscal
    period's ROIC uses that period's own ETR, so a one-time tax adjustment
    affects only that year's ROIC, not the trailing series.
    """
    if net_income is None or tax is None:
        return _STATUTORY_TAX_RATE
    pretax = net_income + tax
    if pretax <= 0:
        return _STATUTORY_TAX_RATE
    etr = tax / pretax
    if etr < _ETR_CLAMP_LO or etr > _ETR_CLAMP_HI:
        return _STATUTORY_TAX_RATE
    return etr


def _flag_dives_after_reparse(ticker: str) -> list[str]:
    """DEC-46: flag dives that read data older than the parser now in use; returns the gap."""
    from data.dive_staleness import flag_dives_after_reparse
    from data.edgar_companyfacts import PARSER_VERSION

    flagged = flag_dives_after_reparse(ticker, PARSER_VERSION)
    if not flagged:
        return []
    return [f"{ticker}: {flagged} earlier deep dive(s) flagged stale (filings re-read); re-run"]


def _persist_source_log(ticker: str, rows: list[Any], *, reparsed: bool = False) -> int:
    """Tier-0 cache gate: record accession numbers we've already parsed.

    After a full re-read, every logged filing from the earliest fiscal year the
    read produced onwards is stamped current, including superseded ones and gap
    years that emit no row; otherwise the stale count would never reach zero.
    Earlier years stay stale until a refresh covers them. Returns how many
    logged filings were raised to the current parser (new filings not counted).
    """
    from data.edgar_fetcher import EdgarFinancialRow
    if not rows:
        return 0
    from data.edgar_companyfacts import PARSER_VERSION

    parsed = [r for r in rows if isinstance(r, EdgarFinancialRow) and r.accession_number]
    if not parsed:
        return 0
    upgraded = 0
    with get_session() as session:
        logged: dict[str, FinancialSourceLog] = {
            str(log.accession_number): log
            for log in session.query(FinancialSourceLog).filter(
                FinancialSourceLog.accession_number.in_({r.accession_number for r in parsed})
            )
        }
        new_logs: list[FinancialSourceLog] = []
        for row in parsed:
            log = logged.get(row.accession_number)
            if log is not None:
                if log.parser_version is None or log.parser_version < PARSER_VERSION:
                    upgraded += 1
                # Re-read after a parser upgrade. Column-style models type this as Column[int].
                log.parser_version = PARSER_VERSION  # type: ignore[assignment]
                continue
            log = FinancialSourceLog(
                ticker=ticker,
                accession_number=row.accession_number,
                form_type="10-K" if row.period == "annual" else "10-Q",
                fiscal_year=row.fiscal_year,
                period=row.period,
                parsing_status="success",
                parser_version=PARSER_VERSION,
            )
            logged[row.accession_number] = log
            new_logs.append(log)
        if new_logs:
            session.add_all(new_logs)
        if reparsed:
            upgraded += (
                session.query(FinancialSourceLog)
                .filter(
                    FinancialSourceLog.ticker == ticker,
                    # From the earliest year read: gap years inside the read have
                    # nothing left to repair and must not stay stale forever.
                    FinancialSourceLog.fiscal_year >= min(r.fiscal_year for r in parsed),
                    FinancialSourceLog.parser_version.is_(None)
                    | (FinancialSourceLog.parser_version < PARSER_VERSION),
                )
                .update({"parser_version": PARSER_VERSION}, synchronize_session=False)
            )
    return upgraded


def _persist_insiders_bulk(ticker: str, rows: list[Any], source: str = "edgar") -> None:
    """
    Bulk-insert insider rows with in-memory dedup.
    Works for both EdgarInsiderRow and YFInsiderTransaction.
    """
    if not rows:
        return
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return

        # Build existing-key set with one query
        existing_keys: set[tuple[Any, str, str, float]] = {
            (filing_date, name or "", txn_type or "", shares or 0.0)
            for filing_date, name, txn_type, shares in session.query(
                InsiderTransactionRecord.filing_date,
                InsiderTransactionRecord.insider_name,
                InsiderTransactionRecord.transaction_type,
                InsiderTransactionRecord.shares,
            ).filter_by(company_id=company.id).all()
        }

        new_rows: list[InsiderTransactionRecord] = []
        for row in rows:
            filing_date = (
                getattr(row, "filing_date", None) or getattr(row, "transaction_date", None)
            )
            if filing_date is None:
                continue
            txn_date = getattr(row, "transaction_date", None)
            insider_name = getattr(row, "insider_name", None) or ""
            insider_title = getattr(row, "insider_title", None) or ""
            txn_type = getattr(row, "transaction_type", None) or ""
            shares = getattr(row, "shares", None) or 0.0
            price = getattr(row, "price_per_share", None)
            value = getattr(row, "value_usd", None)
            is_open = getattr(
                row, "is_open_market",
                txn_type in ("P", "S", "Purchase", "Sale"),
            )

            key = (filing_date, insider_name, txn_type, shares)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            new_rows.append(InsiderTransactionRecord(
                company_id=company.id,
                filing_date=filing_date,
                transaction_date=txn_date,
                insider_name=insider_name,
                insider_title=insider_title,
                transaction_type=txn_type,
                shares=shares,
                price_per_share=price,
                value_usd=value,
                is_open_market=is_open,
                form_type="4" if source == "edgar" else "yf",
                source=source,
            ))

        if new_rows:
            session.add_all(new_rows)


# ── yfinance persistence ──────────────────────────────────────────────────


def _latest_fx_rate_to_usd(session: Any, company_id: int) -> float | None:
    """Most recent non-null ``Financial.fx_rate_to_usd`` for a company.

    ADR-039 added the column and the ESEF/yfinance adapters populate it. ADR-043
    is the first consumer: it converts a natively-reported market cap to USD so
    USD thresholds compare like with like. Returns None when no rate exists,
    which the caller must treat as "refuse", not "assume 1.0" — assuming 1.0 is
    precisely the bug (it is what treating SEK as USD amounts to).
    """
    row = (
        session.query(Financial.fx_rate_to_usd)
        .filter(Financial.company_id == company_id,
                Financial.fx_rate_to_usd.isnot(None))
        .order_by(Financial.fiscal_year.desc())
        .first()
    )
    return float(row[0]) if row and row[0] else None


def _persist_yfinance_snapshot(ticker: str, snapshot: Any) -> list[str]:
    """
    Persist all parts of YFSnapshot in bulk:
      - Company profile + valuation snapshot fields
      - Short interest / institutional aggregate (today's snapshot)
      - Top-20 institutional holders (individual rows)
      - Analyst coverage row for today
      - Price history (bulk insert with in-memory dedup)
      - Supplementary insider transactions (bulk dedup vs. EDGAR Form 4)
    """
    gaps: list[str] = []
    info = snapshot.info
    today = date.today()

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return [f"{ticker}: not in DB — run 'invest data refresh {ticker}' first"]

        # Company profile
        company.name = info.name or company.name
        # Industry + SEC classification: SEC SIC is canonical (verifiable,
        # GAAP-uniform taxonomy). yfinance proprietary classifications
        # misclassify some tickers (HIMS yfinance "Software" vs SEC SIC
        # "Offices & Clinics of Doctors of Medicine"). Per Tier 1.1/2.4
        # substitution (2026-05-15): SEC is primary, yfinance fallback.
        from data.edgar_fetcher import fetch_sec_industry_classification
        sec_class = fetch_sec_industry_classification(ticker)
        if sec_class and sec_class.get("sic_description"):
            company.industry = sec_class["sic_description"]
            company.sector_source = "sec_sic"
            # Tier 2.4 — persist the full SEC classification record so
            # frames-based peer ranking can filter by SIC + filer type
            sic = sec_class.get("sic_code")
            if sic is not None:
                try:
                    company.sic_code = int(sic)
                except (TypeError, ValueError):
                    pass
            company.filer_category = sec_class.get("filer_category")
            company.is_smaller_reporting_company = sec_class.get("is_smaller_reporting_company")
            company.is_financial_institution = sec_class.get("is_financial_institution")
            company.is_fund = sec_class.get("is_fund")
        else:
            company.industry = info.industry or company.industry
            if info.industry:
                company.sector_source = "yfinance"
        # Sector: keep yfinance for now (SIC 2-digit → sector mapping would
        # be cleaner but is out of scope for Tier-1 substitution; tracked
        # as Tier 2+ work)
        # Per-field source tagging (Phase 1, 2026-05-16) — every yfinance
        # write below records `_source='yfinance'` so compute_data_completeness
        # can weight it at Tier 3b (0.85) instead of guessing via defaults.
        from config.source_tags import EDGARTOOLS as _SRC_ET, YFINANCE as _SRC_YF
        company.sector = info.sector or company.sector
        # Exchange: SEC primary (Tier 1B via Company.get_exchanges()),
        # yfinance fallback. Phase 2.1 migration (audit §C.3).
        from data.edgar_fetcher import fetch_sec_exchange
        sec_exch = fetch_sec_exchange(ticker)
        if sec_exch:
            company.exchange = sec_exch
            company.exchange_source = _SRC_ET
        elif info.exchange:
            company.exchange = info.exchange
            company.exchange_source = _SRC_YF
        # ADR-041: never let the yfinance snapshot downgrade a currency that a
        # filing-grade source already established. The reporting currency read
        # off an ESEF filing's iso4217 unit is authoritative; yfinance's
        # `currency` is the QUOTE currency and can legitimately differ from the
        # reporting currency (Nordic Semiconductor: quoted NOK, reports USD).
        # SEC-first hierarchy, ADR-033 §"trust hierarchy".
        if info.currency and company.currency_source != "esef":
            company.currency = info.currency
            company.currency_source = _SRC_YF
        if info.market_cap is not None:
            # ADR-043 §2.1 — yfinance reports market cap in the filer's TRADING
            # currency. Store it natively, and only populate market_cap_usd
            # after an actual conversion. A non-USD cap written straight into
            # market_cap_usd is the original bug: SEK 14.56bn read as $14.56bn,
            # a 9.5x overstatement that cleared the $300m liquidity floor.
            native_cur = (company.currency or info.currency or "USD").upper()
            company.market_cap_native = info.market_cap
            company.market_cap_currency = native_cur
            if native_cur == "USD":
                company.market_cap_usd = info.market_cap
                company.market_cap_usd_source = _SRC_YF
            else:
                fx = _latest_fx_rate_to_usd(session, company.id)
                if fx:
                    company.market_cap_usd = info.market_cap * fx
                    company.market_cap_usd_source = f"{_SRC_YF}+fx"
                else:
                    # Fail CLOSED. A NULL cap makes the gates refuse; a wrong
                    # one makes them pass. ADR-043 §2.1.
                    company.market_cap_usd = None
                    company.market_cap_usd_source = None
                    gaps.append(
                        f"{company.ticker}: market cap {info.market_cap:,.0f} "
                        f"{native_cur} could not be converted to USD (no "
                        f"fx_rate_to_usd persisted) — USD thresholds will refuse"
                    )
        if info.float_shares is not None:
            company.shares_float = info.float_shares
            company.shares_float_source = _SRC_YF
        if info.ceo_name:
            company.ceo_name = info.ceo_name
        if info.ceo_total_pay is not None:
            company.ceo_total_pay = info.ceo_total_pay
            company.ceo_total_pay_source = _SRC_YF
        # IPO date: yfinance firstTradeDateEpochUtc is our authoritative
        # source. Persist on write so feasibility checks don't have to infer
        # from price history.
        if info.first_trade_date is not None and not company.ipo_date:
            company.ipo_date = info.first_trade_date
            company.ipo_date_source = _SRC_YF
        # Valuation ratios + beta: DISABLED yfinance fetch per ADR-033 §1.2
        # compute-don't-pull invariant + §4 #1 no-API-ratios prohibition.
        # These fields are populated by:
        #   - valuation/sec_derived_ratios.py:compute_sec_ratios() — P/E, P/B, EV/EBITDA
        #     (market_cap / TTM_net_income_from_SEC, etc.)
        #   - valuation/sec_derived_beta.py:compute_beta_for_ticker() — beta
        #     from PriceHistory regression vs SPY
        # yfinance values are known-contaminated (HIMS P/E 57.14x using
        # forward-EPS to hide GAAP loss; HIMS EV/EBITDA 134.16x adds SBC back;
        # INTA P/B 5.00x vs SEC 3.08x; FIG / INTA negative-ratio gibberish).
        # See ADR-033 §3.2 empirical evidence table.
        #
        # company.pe_trailing  ← populated by compute_sec_ratios + persist_sec_ratios
        # company.pb_ratio     ← populated by compute_sec_ratios + persist_sec_ratios
        # company.ev_ebitda    ← populated by compute_sec_ratios + persist_sec_ratios
        # company.beta         ← populated by compute_beta_for_ticker + persist_beta
        if info.insider_pct is not None:
            company.insider_pct_latest = info.insider_pct
            company.insider_pct_latest_source = _SRC_YF
        if info.institution_pct is not None:
            company.institution_pct_latest = info.institution_pct
            company.institution_pct_latest_source = _SRC_YF
        if info.short_pct_float is not None:
            company.short_pct_float_latest = info.short_pct_float
            company.short_pct_float_latest_source = _SRC_YF

        # Short interest snapshot (one row per day per ticker)
        if info.short_pct_float is not None:
            existing_si = (
                session.query(ShortInterestRecord)
                .filter_by(company_id=company.id, settlement_date=today)
                .first()
            )
            if not existing_si:
                session.add(ShortInterestRecord(
                    company_id=company.id,
                    settlement_date=today,
                    short_pct_float=info.short_pct_float,
                    float_shares=int(info.float_shares) if info.float_shares else None,
                    source="yfinance",
                ))

        # Institutional aggregate snapshot (sentinel holder _aggregate)
        if info.institution_pct is not None:
            existing_inst = (
                session.query(InstitutionalHolderRecord)
                .filter_by(
                    company_id=company.id,
                    report_date=today,
                    holder_name="_aggregate",
                )
                .first()
            )
            if not existing_inst:
                session.add(InstitutionalHolderRecord(
                    company_id=company.id,
                    report_date=today,
                    holder_name="_aggregate",
                    pct_of_shares_out=info.institution_pct,
                    source="yfinance",
                ))

        # Individual institutional holders — bulk pattern
        if snapshot.institutional_holders:
            existing_holder_keys: set[tuple[date, str]] = {
                (rd, name)
                for rd, name in session.query(
                    InstitutionalHolderRecord.report_date,
                    InstitutionalHolderRecord.holder_name,
                ).filter_by(company_id=company.id).all()
            }
            new_holder_rows: list[InstitutionalHolderRecord] = []
            for holder in snapshot.institutional_holders:
                if not holder.holder_name:
                    continue
                holder_date = holder.date_reported or today
                key = (holder_date, holder.holder_name)
                if key in existing_holder_keys:
                    # Update in place
                    existing = (
                        session.query(InstitutionalHolderRecord)
                        .filter_by(
                            company_id=company.id,
                            report_date=holder_date,
                            holder_name=holder.holder_name,
                        )
                        .first()
                    )
                    if existing:
                        existing.shares_held = holder.shares
                        existing.value_usd = holder.value_usd
                        existing.pct_of_shares_out = holder.pct_out
                else:
                    existing_holder_keys.add(key)
                    new_holder_rows.append(InstitutionalHolderRecord(
                        company_id=company.id,
                        report_date=holder_date,
                        holder_name=holder.holder_name,
                        shares_held=holder.shares,
                        value_usd=holder.value_usd,
                        pct_of_shares_out=holder.pct_out,
                        source="yfinance",
                    ))
            if new_holder_rows:
                session.add_all(new_holder_rows)

        # Analyst coverage (one row per day)
        if info.analyst_count is not None or info.target_price_mean is not None:
            existing_an = (
                session.query(AnalystCoverageRecord)
                .filter_by(company_id=company.id, as_of_date=today)
                .first()
            )
            target = existing_an or AnalystCoverageRecord(
                company_id=company.id,
                as_of_date=today,
                source="yfinance",
            )
            target.analyst_count = info.analyst_count
            target.consensus_rating = info.recommendation
            target.price_target_mean = info.target_price_mean
            target.price_target_high = info.target_price_high
            target.price_target_low = info.target_price_low
            if existing_an is None:
                session.add(target)

    # Price history — bulk pattern, separate session to flush large batch cleanly
    if snapshot.price_history:
        gaps.extend(_persist_price_history_bulk(ticker, snapshot.price_history))

    # Supplementary yfinance insider trades — dedup vs Form 4 via the bulk helper
    if snapshot.insider_transactions:
        _persist_insiders_bulk(ticker, _yf_insiders_to_rows(snapshot.insider_transactions),
                               source="yfinance")

    # ADR-018 D6: earnings history (EPS estimate / actual / surprise + AMC/BMO)
    earnings = getattr(snapshot, "earnings_history", None)
    if earnings:
        _persist_earnings_history_bulk(ticker, earnings)

    return gaps


def _persist_earnings_history_bulk(ticker: str, rows: list[Any]) -> None:
    """ADR-018 D6 — write yfinance.earnings_dates rows into earnings_history.

    Dedup key: (company_id, fiscal_quarter) where fiscal_quarter is derived
    from event_date + Company.fiscal_year_end_month using the same
    end-year convention as the financials parser. Keeps event_date,
    event_time (BMO/AMC), eps_actual / estimate / surprise.
    """
    if not rows:
        return
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return
        fyem = int(company.fiscal_year_end_month or 12)

        existing_keys: set[str] = {
            row[0]
            for row in session.query(EarningsHistory.fiscal_quarter)
            .filter_by(company_id=company.id).all()
        }

        new_rows: list[EarningsHistory] = []
        for r in rows:
            event_date_val = getattr(r, "event_date", None)
            if event_date_val is None:
                continue
            label = _fiscal_quarter_label(event_date_val, fyem)
            if label in existing_keys:
                # Update in place if values differ (e.g. estimate firmed up)
                existing = (
                    session.query(EarningsHistory)
                    .filter_by(company_id=company.id, fiscal_quarter=label)
                    .first()
                )
                if existing:
                    existing.report_date = event_date_val
                    existing.eps_actual = r.eps_actual
                    existing.eps_estimate = r.eps_estimate
                    existing.eps_surprise_pct = r.eps_surprise_pct
                continue
            existing_keys.add(label)
            new_rows.append(EarningsHistory(
                company_id=company.id,
                fiscal_quarter=label,
                report_date=event_date_val,
                eps_actual=r.eps_actual,
                eps_estimate=r.eps_estimate,
                eps_surprise_pct=r.eps_surprise_pct,
                source="yfinance",
            ))
        if new_rows:
            session.add_all(new_rows)


def _fiscal_quarter_label(event_date: "date", fye_month: int) -> str:
    """Return e.g. '2026Q2' label for an earnings event date.

    For now this uses the CALENDAR quarter of the event itself
    (Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec). That gives a
    unique key per (company, calendar quarter) which is all the unique-
    constraint needs.

    NOTE: this is the *event's* quarter, not necessarily the *fiscal
    quarter being reported* — those are usually 1-2 months apart for
    non-Dec-FY companies. The richer mapping (event → reported period →
    fiscal quarter using fye_month) is deferred to v2; consumers that
    need the reported-period anchor should join EarningsHistory.report_date
    against Financial.period_end_date in SQL.
    """
    cal_q = ((event_date.month - 1) // 3) + 1
    return f"{event_date.year}Q{cal_q}"


def _yf_insiders_to_rows(yf_rows: list[Any]) -> list[Any]:
    """Adapter so YFInsiderTransaction rows go through _persist_insiders_bulk."""
    class _Adapter:
        __slots__ = (
            "filing_date", "transaction_date", "insider_name", "insider_title",
            "transaction_type", "shares", "price_per_share", "value_usd",
            "is_open_market",
        )
        def __init__(self, src: Any) -> None:
            txn_type = (src.transaction_type or "").strip()
            self.filing_date = src.transaction_date
            self.transaction_date = src.transaction_date
            self.insider_name = src.insider_name or ""
            self.insider_title = src.insider_title or ""
            self.transaction_type = txn_type
            self.shares = src.shares
            self.price_per_share = None
            self.value_usd = src.value_usd
            self.is_open_market = (
                "purchase" in txn_type.lower() or "sale" in txn_type.lower()
            )

    return [_Adapter(r) for r in yf_rows if r.transaction_date and r.shares]


def _persist_price_history_bulk(ticker: str, rows: list[Any]) -> list[str]:
    """
    Bulk insert price history. Uses one SELECT to build existing-date set,
    then session.add_all() with the new rows.
    """
    if not rows:
        return []
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return [f"{ticker}: not in DB"]

        existing_dates: set[date] = {
            d for (d,) in session.query(PriceHistory.date)
            .filter_by(company_id=company.id).all()
        }
        new_rows = [
            PriceHistory(
                company_id=company.id,
                date=row.date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                adj_close=row.adj_close,
                source="yfinance",
            )
            for row in rows
            if row.date not in existing_dates
        ]
        if new_rows:
            session.add_all(new_rows)
    return []


# ── F6 deterministic signals (Phase 3) ────────────────────────────────────


async def _fetch_f6_signals(
    ticker: str,
    latest_10k: Any | None,
    requirement: Any,
) -> list[str]:
    """
    Fetch F6-class signals deterministically, gated by the requirement.
    Only runs the parts the selected frameworks actually need:
      - customer_concentration  → needs_customer_concentration
      - DEF 14A proxy ownership → needs_proxy_ownership OR needs_founder_status

    Reuses the latest 10-K filing object fetched in Phase 1 to avoid redundant
    EDGAR roundtrips.
    """
    from data.edgar_fetcher import (
        fetch_edgar_arr_metrics,
        fetch_edgar_customer_concentration,
        fetch_edgar_patent_disclosure,
        fetch_edgar_proxy_ownership,
        fetch_edgar_retention_metrics,
    )
    loop = asyncio.get_event_loop()
    gaps: list[str] = []

    # Pull current CEO name from Company (yfinance wrote it in Phase 2)
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        ceo_name_hint = company.ceo_name if company else None

    tasks: list[Any] = []
    do_customer = requirement.needs_customer_concentration
    do_proxy = requirement.needs_proxy_ownership or requirement.needs_founder_status
    do_retention = requirement.needs_retention_metrics
    do_patents = requirement.needs_patent_disclosure
    do_arr = requirement.needs_arr_metrics

    # ADR-018 D4: `latest_10k` is a Filing object (per fetch_latest_10k_filing).
    # We pass it as `filing` so XBRL fast-path can call .xbrl(); the function
    # internally derives a TenK via filing.obj() for the section regex path.
    if do_customer:
        tasks.append(loop.run_in_executor(
            None, lambda: fetch_edgar_customer_concentration(
                ticker, filing=latest_10k,
            )
        ))
    if do_proxy:
        tasks.append(loop.run_in_executor(
            None, lambda: fetch_edgar_proxy_ownership(
                ticker, latest_10k=latest_10k, ceo_name_hint=ceo_name_hint,
            )
        ))
    if do_retention:
        tasks.append(loop.run_in_executor(
            None, lambda: fetch_edgar_retention_metrics(
                ticker, filing=latest_10k,
            )
        ))
    if do_patents:
        tasks.append(loop.run_in_executor(
            None, lambda: fetch_edgar_patent_disclosure(
                ticker, filing=latest_10k,
            )
        ))
    if do_arr:
        tasks.append(loop.run_in_executor(
            None, lambda: fetch_edgar_arr_metrics(ticker)
        ))
    if not tasks:
        return gaps

    results = await asyncio.gather(*tasks)
    idx = 0
    customer = None
    if do_customer:
        customer = results[idx]
        idx += 1
    proxy = None
    if do_proxy:
        proxy = results[idx]
        idx += 1
    retention = None
    if do_retention:
        retention = results[idx]
        idx += 1
    patents = None
    if do_patents:
        patents = results[idx]
        idx += 1
    arr_signals = None
    if do_arr:
        arr_signals = results[idx]
        idx += 1

    # ADR-018 — emit gaps only for true unknowns. `not_disclosed` is a
    # POSITIVE signal (e.g. INTA: no >10% customer = diversified moat),
    # not a parser failure. Don't append it to gaps[].
    if do_customer and customer is not None and customer.state == "parser_uncertain":
        gaps.append(f"{ticker}: customer_concentration parser_uncertain — manual review")
    if do_proxy and proxy is not None and proxy.state == "parser_uncertain":
        if proxy.multi_class_detected:
            gaps.append(f"{ticker}: ceo_equity_pct parser_uncertain — multi-class issuer (deferred to v2)")
        else:
            gaps.append(f"{ticker}: ceo_equity_pct parser_uncertain — see logs")

    confidence_map = {
        "xbrl": 1.0, "structured_xbrl": 1.0, "html_table": 1.0,
        "regex": 0.6, "negative_phrase": 0.6, "yfinance": 0.8, "none": 0.0,
    }
    from datetime import datetime as _dt
    now = _dt.utcnow()

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return gaps

        # ── Proxy / D2 / D3 / D1 fragments ───────────────────────────────
        if proxy is not None:
            if proxy.ceo_name:
                company.ceo_name = proxy.ceo_name
            if proxy.ceo_equity_pct is not None:
                company.ceo_equity_pct = proxy.ceo_equity_pct
            # ALWAYS overwrite is_founder_ceo with the latest parse (even if
            # None) so parser improvements propagate. The Phase 3.5
            # reconciliation will OR-merge this with the yf signal.
            company.is_founder_ceo = proxy.is_founder_ceo
            if proxy.ceo_tenure_years is not None:
                company.ceo_tenure_years = proxy.ceo_tenure_years
            # ceo_total_pay: Phase 2.2 migration (audit §B.2). DEF 14A SCT
            # via edgartools.proxy.peo_total_comp is Tier 1A SEC primary;
            # yfinance write earlier in this refresh acted as fallback when
            # proxy was unavailable. Overwrite here when proxy gave us a
            # value (real GAAP source beats Yahoo scrape).
            if proxy.ceo_total_pay is not None:
                from config.source_tags import SEC_DEF14A as _SRC_DEF14A
                company.ceo_total_pay = proxy.ceo_total_pay
                company.ceo_total_pay_source = _SRC_DEF14A

        # ── Customer / D4 ────────────────────────────────────────────────
        if customer is not None:
            most_recent = (
                session.query(Financial)
                .filter_by(company_id=company.id, period="annual")
                .order_by(Financial.fiscal_year.desc())
                .first()
            )
            if most_recent:
                # Revenue concentration
                if customer.concentration_pct is not None:
                    most_recent.customer_concentration_pct = customer.concentration_pct
                # Receivables concentration (separate column per ADR-018 §2.3)
                if customer.receivables_concentration_pct is not None:
                    most_recent.receivables_concentration_pct = (
                        customer.receivables_concentration_pct
                    )
                if customer.relationship_years is not None:
                    most_recent.customer_relationship_years = customer.relationship_years
                most_recent.extraction_confidence = confidence_map.get(
                    customer.extraction_method, 0.0
                )
                # 3-state column writes
                # Revenue side: disclosed_exact when concentration_pct present;
                # not_disclosed when state='not_disclosed'; uncertain otherwise.
                if customer.concentration_pct is not None:
                    most_recent.customer_concentration_state = customer.state
                else:
                    most_recent.customer_concentration_state = (
                        "not_disclosed" if customer.state == "not_disclosed"
                        else "parser_uncertain" if customer.state == "parser_uncertain"
                        else "not_disclosed"
                    )
                most_recent.customer_concentration_fetched_at = now
                # Receivables side
                if customer.receivables_concentration_pct is not None:
                    most_recent.receivables_concentration_state = "disclosed_exact"
                else:
                    most_recent.receivables_concentration_state = "not_disclosed"
                most_recent.receivables_concentration_fetched_at = now

        # ── Retention metrics / 5k-7 ──────────────────────────────────────
        if retention is not None:
            most_recent_ret = (
                session.query(Financial)
                .filter_by(company_id=company.id, period="annual")
                .order_by(Financial.fiscal_year.desc())
                .first()
            )
            if most_recent_ret:
                if retention.nrr_pct is not None:
                    most_recent_ret.nrr_pct = retention.nrr_pct
                if retention.grr_pct is not None:
                    most_recent_ret.grr_pct = retention.grr_pct
                most_recent_ret.retention_state = retention.state
                most_recent_ret.retention_fetched_at = now

        # ── Patent disclosure / 5k-6 partial ──────────────────────────────
        if patents is not None:
            most_recent_pat = (
                session.query(Financial)
                .filter_by(company_id=company.id, period="annual")
                .order_by(Financial.fiscal_year.desc())
                .first()
            )
            if most_recent_pat:
                if patents.patent_count is not None:
                    most_recent_pat.patent_count_disclosed = float(patents.patent_count)
                most_recent_pat.patent_disclosure_state = patents.state
                most_recent_pat.patent_disclosure_fetched_at = now

        # ── ARR metrics / ADR-026 5Q-5 ─────────────────────────────────────
        # ARR sits on the latest ANNUAL row (the per-period concept is the
        # company's most-recent fiscal-year-equivalent forward-looking
        # commitment). When a fresher 10-Q disclosure exists, we overwrite
        # the same field — the value reflects the freshest filing.
        if arr_signals is not None:
            most_recent_arr = (
                session.query(Financial)
                .filter_by(company_id=company.id, period="annual")
                .order_by(Financial.fiscal_year.desc())
                .first()
            )
            if most_recent_arr:
                if arr_signals.cloud_arr_usd is not None:
                    most_recent_arr.cloud_arr_usd = arr_signals.cloud_arr_usd
                if arr_signals.cloud_arr_growth_yoy_pct is not None:
                    most_recent_arr.cloud_arr_growth_yoy_pct = arr_signals.cloud_arr_growth_yoy_pct
                if arr_signals.total_arr_usd is not None:
                    most_recent_arr.total_arr_usd = arr_signals.total_arr_usd
                if arr_signals.total_arr_growth_yoy_pct is not None:
                    most_recent_arr.total_arr_growth_yoy_pct = arr_signals.total_arr_growth_yoy_pct
                most_recent_arr.arr_state = arr_signals.state
                most_recent_arr.arr_fetched_at = now

    return gaps


def _fetch_polygon_safe(ticker: str, price_history_years: int) -> "Any | None":
    """ADR-019 P1+P3 — Polygon weekly aggs + short-interest history.

    Returns a `_PolygonBranchResult` carrying weekly bars + short-interest
    rows + per-task error strings. Never raises — Polygon failure is opt-
    in absorbed by the dive (F2 falls back to yfinance rows; F4 falls back
    to yfinance snapshot).

    Skipped entirely when POLYGON_API_KEY is unset (returns None — caller
    treats as no-op).
    """
    from datetime import date as _date, timedelta as _td
    from data.api.polygon_client import PolygonClient
    from data.db import get_session
    from data.models.schema import TaskRun
    from datetime import datetime as _dt

    client = PolygonClient()
    if not client.has_key:
        return None    # gracefully no-op; matches "POLYGON_API_KEY unset = behaviour identical to today"

    started = _dt.utcnow()
    result = _PolygonBranchResult()

    # Weekly aggs window: ~13 months default (covers F2 12-1 momentum)
    years = max(price_history_years, 1) or 1
    end = _date.today()
    start = end - _td(days=int(years * 370))

    # P1 — weekly aggs
    p1_run = TaskRun(task_name="polygon_weekly_aggs", ticker=ticker.upper(),
                     started_at=started, status="running")
    try:
        weekly = client.fetch_weekly_aggs(ticker, start=start, end=end)
        result.weekly_bars = weekly.rows
        result.weekly_error = weekly.error
        p1_run.status = "success" if weekly.ok else "failed"
        p1_run.error = weekly.error
        p1_run.rows_written = len(weekly.rows)
    except Exception as exc:    # noqa: BLE001
        result.weekly_error = f"{type(exc).__name__}: {exc}"
        p1_run.status = "failed"
        p1_run.error = result.weekly_error
    p1_run.completed_at = _dt.utcnow()

    # P3 — short-interest history
    p3_run = TaskRun(task_name="polygon_short_interest", ticker=ticker.upper(),
                     started_at=_dt.utcnow(), status="running")
    try:
        si = client.fetch_short_interest_history(ticker)
        result.short_interest_rows = si.rows
        result.short_interest_error = si.error
        p3_run.status = "success" if si.ok else "failed"
        p3_run.error = si.error
        p3_run.rows_written = len(si.rows)
    except Exception as exc:    # noqa: BLE001
        result.short_interest_error = f"{type(exc).__name__}: {exc}"
        p3_run.status = "failed"
        p3_run.error = result.short_interest_error
    p3_run.completed_at = _dt.utcnow()

    # Persist task_runs immediately so visibility doesn't depend on
    # downstream persist succeeding.
    try:
        with get_session() as session:
            session.add_all([p1_run, p3_run])
    except Exception as exc:
        logger.debug("task_runs persistence (%s): %s", ticker, exc)

    return result


@dataclass
class _PolygonBranchResult:
    """Internal carrier for Phase 1 Polygon branch outputs."""
    weekly_bars: list = None    # type: ignore[assignment]
    weekly_error: str | None = None
    short_interest_rows: list = None    # type: ignore[assignment]
    short_interest_error: str | None = None

    def __post_init__(self) -> None:
        if self.weekly_bars is None:
            self.weekly_bars = []
        if self.short_interest_rows is None:
            self.short_interest_rows = []


def _persist_polygon_data(ticker: str, branch: "_PolygonBranchResult") -> list[str]:
    """Write Polygon rows into price_history (P1) + short_interest (P3).

    Polygon > yfinance precedence: when a (company_id, date) row already
    exists from yfinance, we OVERWRITE it with Polygon's values and set
    `source='polygon'`. yfinance writers must NOT clobber polygon rows —
    that's enforced by checking source on the existing row before update.

    Per-table errors do NOT cascade — P1 failure leaves yfinance rows
    intact; P3 failure leaves yfinance short-interest snapshot intact.
    """
    gaps: list[str] = []
    if not branch:
        return gaps

    # ── P1: price_history UPSERT with polygon > yfinance precedence ──────
    if branch.weekly_bars:
        try:
            written, replaced = _upsert_polygon_price_bars(ticker, branch.weekly_bars)
            logger.info(
                "polygon weekly aggs (%s): %d new + %d replaced (yfinance→polygon)",
                ticker, written, replaced,
            )
        except Exception as exc:    # noqa: BLE001
            gaps.append(f"{ticker}: polygon weekly aggs persist failed — {exc}")
    elif branch.weekly_error:
        gaps.append(f"{ticker}: polygon weekly aggs unavailable — {branch.weekly_error}")

    # ── P3: short_interest UPSERT (Polygon = primary source for time series) ──
    if branch.short_interest_rows:
        try:
            written = _upsert_polygon_short_interest(ticker, branch.short_interest_rows)
            logger.info(
                "polygon short-interest (%s): %d settlements written/refreshed",
                ticker, written,
            )
        except Exception as exc:    # noqa: BLE001
            gaps.append(f"{ticker}: polygon short-interest persist failed — {exc}")
    elif branch.short_interest_error:
        gaps.append(f"{ticker}: polygon short-interest unavailable — {branch.short_interest_error}")

    return gaps


def _upsert_polygon_price_bars(ticker: str, bars: list) -> tuple[int, int]:
    """UPSERT weekly bars. Returns (newly_inserted, yfinance_rows_replaced)."""
    if not bars:
        return 0, 0
    written = 0
    replaced = 0
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return 0, 0

        # Prefetch existing rows in the date range — single SELECT for dedup
        bar_dates = {b.date for b in bars if b.date is not None}
        if not bar_dates:
            return 0, 0
        existing = {
            r.date: r
            for r in session.query(PriceHistory)
            .filter(PriceHistory.company_id == company.id)
            .filter(PriceHistory.date.in_(bar_dates))
            .all()
        }
        new_rows: list[PriceHistory] = []
        for b in bars:
            if b.date is None:
                continue
            existing_row = existing.get(b.date)
            if existing_row is None:
                new_rows.append(PriceHistory(
                    company_id=company.id,
                    date=b.date,
                    open=b.open, high=b.high, low=b.low,
                    close=b.close, adj_close=b.close,    # Polygon adjusted=true
                    volume=b.volume,
                    source="polygon",
                ))
                written += 1
            else:
                # Polygon > yfinance precedence: overwrite values + mark source.
                # If the existing row is ALREADY 'polygon', this is a refresh
                # (e.g. corrected close). Either way, Polygon wins.
                was_yf = existing_row.source != "polygon"
                existing_row.open = b.open
                existing_row.high = b.high
                existing_row.low = b.low
                existing_row.close = b.close
                existing_row.adj_close = b.close
                existing_row.volume = b.volume
                existing_row.source = "polygon"
                if was_yf:
                    replaced += 1
        if new_rows:
            session.add_all(new_rows)
    return written, replaced


def _upsert_polygon_short_interest(ticker: str, rows: list) -> int:
    """UPSERT bi-weekly short-interest settlements. Returns rows written."""
    if not rows:
        return 0
    n_written = 0
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return 0

        settlement_dates = {r.settlement_date for r in rows if r.settlement_date}
        existing = {
            r.settlement_date: r
            for r in session.query(ShortInterestRecord)
            .filter(ShortInterestRecord.company_id == company.id)
            .filter(ShortInterestRecord.settlement_date.in_(settlement_dates))
            .all()
        }
        # Pull float_shares from Company so we can compute pct-of-float.
        float_shares = company.shares_float or 0
        new_rows: list[ShortInterestRecord] = []
        for r in rows:
            if r.settlement_date is None:
                continue
            pct_float = None
            if float_shares and r.short_interest:
                pct_float = (r.short_interest / float_shares) * 100.0
            target = existing.get(r.settlement_date)
            if target is None:
                target = ShortInterestRecord(
                    company_id=company.id,
                    settlement_date=r.settlement_date,
                    short_interest=r.short_interest,
                    short_pct_float=pct_float,
                    days_to_cover=r.days_to_cover,
                    float_shares=int(float_shares) if float_shares else None,
                    source="polygon",
                )
                new_rows.append(target)
                n_written += 1
            else:
                # Polygon > yfinance precedence
                target.short_interest = r.short_interest
                target.days_to_cover = r.days_to_cover
                if pct_float is not None:
                    target.short_pct_float = pct_float
                if float_shares:
                    target.float_shares = int(float_shares)
                target.source = "polygon"
                n_written += 1
        if new_rows:
            session.add_all(new_rows)
    return n_written


def _fetch_fmp_profile_safe(ticker: str) -> Any:
    """Branch F — FMP /stable/profile. Never raises; returns FMPProfile with .error set."""
    from data.api.fmp_client import FMPClient, FMPProfile
    from config.settings import settings as _settings
    if not _settings.fmp_api_key:
        return FMPProfile(ticker=ticker.upper(), error="FMP_API_KEY not set")
    try:
        return FMPClient(api_key=_settings.fmp_api_key).fetch_profile(ticker)
    except Exception as exc:
        return FMPProfile(ticker=ticker.upper(), error=f"client: {type(exc).__name__}: {exc}")


def _apply_adr018_reconciliation(
    ticker: str, yf_snapshot: Any, fmp_profile: Any,
) -> None:
    """ADR-018 Phase 3.5 — fold per-source signals into 3-state columns.

    Source-priority chain (locked at write-time per ADR-018 §A.4):
      D1 ceo_name:    FMP /profile.ceo  >  yf officers tokeniser  >  edgartools peo_name
      D7 ipo_date:    yf firstTradeDateMs  >  FMP /profile.ipoDate
                      (Polygon tiebreaker deferred per §6.4 / open Q #4)
      D3 founder:     OR across yf title-contains-'founder' AND existing flags

    Reads what's already on the Company row (yf snapshot wrote yf-side
    values in Phase 2; F6 wrote edgartools-side values in Phase 3).
    Writes only the _state columns + final reconciled values where they
    improve on what's already there.
    """
    from datetime import UTC, datetime
    yf_info = yf_snapshot.info if yf_snapshot is not None else None
    yf_officers = []
    if yf_info is not None:
        # Re-extract yf founder signal (we don't store the raw officers list)
        # We need the original raw .info dict — yfinance doesn't expose it
        # post-snapshot. Fall back to: if the persisted ceo_name came from
        # yfinance and yf_info captured a 'co-founder' marker we'd need
        # access to officers. For now we accept that yf-side founder gets
        # the value from the parser when the title was matched; the OR
        # union with edgartools/regex still works.
        pass

    fmp_ceo = (fmp_profile.ceo if fmp_profile and not fmp_profile.error else None)
    fmp_ipo = (fmp_profile.ipo_date if fmp_profile and not fmp_profile.error else None)

    now = datetime.now(UTC)

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return

        # ── D1: CEO name reconciliation ──────────────────────────────────
        # Priority: FMP > yf > edgartools peo_name (already on row from Phase 3)
        existing_name = company.ceo_name
        chosen: str | None = fmp_ceo or existing_name or None
        if chosen:
            company.ceo_name = chosen
            company.ceo_name_state = "disclosed_exact"
        else:
            company.ceo_name_state = "not_disclosed"
        company.ceo_name_fetched_at = now

        # ── D2: CEO equity (already written by Phase 3 if available) ────
        # Phase 3 wrote ceo_equity_pct from edgartools.proxy.beneficial_ownership
        # plus extraction_method. We only set the _state column here.
        if company.ceo_equity_pct is not None:
            # Phase 3 may have written extraction_method='structured_xbrl'
            # but state is set there too via the ProxyOwnership.state field.
            # Read it back from the DB? No — we can infer: if the value is
            # 0.5 exactly (sentinel) → parser_uncertain; else → disclosed_exact.
            if abs(company.ceo_equity_pct - 0.5) < 0.01:
                company.ceo_equity_pct_state = "parser_uncertain"
            else:
                company.ceo_equity_pct_state = "disclosed_exact"
        else:
            company.ceo_equity_pct_state = "not_disclosed"
        company.ceo_equity_pct_fetched_at = now

        # ── D3: founder status union ────────────────────────────────────
        # is_founder_ceo on Company comes from edgartools/regex (Phase 3).
        # Add yf-side: if we can find the CEO in officers and the title
        # contains 'founder', the OR-union flips to True.
        from data.api.yfinance_client import is_ceo_a_founder
        try:
            import yfinance as _yf
            officers = _yf.Ticker(ticker).info.get("companyOfficers") or []
            yf_founder = is_ceo_a_founder(officers)
        except Exception:
            yf_founder = None
        existing_founder = company.is_founder_ceo
        # OR-union: any True wins; absence-of-evidence stays None
        merged: bool | None
        if existing_founder is True or yf_founder is True:
            merged = True
        elif existing_founder is False and yf_founder is False:
            merged = False
        else:
            merged = existing_founder if existing_founder is not None else yf_founder
        company.is_founder_ceo = merged
        if merged is not None:
            company.is_founder_ceo_state = "disclosed_exact"
        else:
            company.is_founder_ceo_state = "not_disclosed"
        company.is_founder_ceo_fetched_at = now

        # ── D7: IPO date reconciliation ──────────────────────────────────
        # yf primary (firstTradeDateMs already wrote ipo_date in Phase 2);
        # FMP cross-validate. State = parser_uncertain when they disagree
        # by >1 day, disclosed_exact when they agree, not_disclosed when
        # both empty.
        existing_ipo = company.ipo_date
        if existing_ipo is not None and fmp_ipo is not None:
            diff_days = abs((existing_ipo - fmp_ipo).days)
            if diff_days <= 1:
                company.ipo_date_state = "disclosed_exact"
            else:
                company.ipo_date_state = "parser_uncertain"
                logger.info(
                    "ADR-018 D7: %s ipo_date disagreement yf=%s fmp=%s (Δ%dd)",
                    ticker, existing_ipo, fmp_ipo, diff_days,
                )
        elif existing_ipo is not None:
            company.ipo_date_state = "disclosed_exact"
        elif fmp_ipo is not None:
            company.ipo_date = fmp_ipo
            company.ipo_date_state = "disclosed_exact"
        else:
            company.ipo_date_state = "not_disclosed"
        company.ipo_date_fetched_at = now


def _compute_buyback_yields(ticker: str) -> None:
    """Buyback yield = share_repurchases / market_cap on most-recent annual."""
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company or not company.market_cap_usd:
            return
        most_recent = (
            session.query(Financial)
            .filter_by(company_id=company.id, period="annual")
            .order_by(Financial.fiscal_year.desc())
            .first()
        )
        if most_recent and most_recent.share_repurchases:
            most_recent.buyback_yield = most_recent.share_repurchases / company.market_cap_usd


def _record_share_split_basis(ticker: str) -> None:
    """Stamp each annual row with its split factor and a point-in-time reference.

    Neither column replaces `shares_outstanding` — EDGAR stays authoritative
    (SECURITY §4). They exist so `data/share_basis.py` can tell which split
    basis the as-filed count is already on; see that module for why.
    """
    import bisect

    from data.api.yfinance_client import fetch_stock_splits
    from data.share_basis import remaining_split_factor

    splits = fetch_stock_splits(ticker)
    points = _fetch_point_in_time_shares(ticker)
    if not splits and not points:
        return
    dates = [d for d, _ in points]

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return
        rows = (
            session.query(Financial)
            .filter_by(company_id=company.id, period="annual")
            .all()
        )
        for row in rows:
            period_end = row.period_end_date
            if period_end is None:
                continue
            pit = None
            if points:
                idx = bisect.bisect_right(dates, period_end) - 1
                if idx >= 0:
                    pit = points[idx][1]
                    row.shares_outstanding_pit = pit
            row.share_split_factor = remaining_split_factor(
                row.shares_outstanding,
                pit,
                [(d, r) for d, r in splits if d > period_end],
            )
        session.commit()


def _fetch_point_in_time_shares(ticker: str) -> list[tuple[date, float]]:
    """yfinance share-count series, oldest first. Best-effort; [] on failure."""
    try:
        import warnings

        warnings.filterwarnings("ignore")
        import yfinance as yf

        series = yf.Ticker(ticker).get_shares_full(start="2005-01-01")
    except Exception as exc:  # noqa: BLE001 — scraper; never fail the refresh
        logger.debug("point-in-time shares unavailable (%s): %s", ticker, exc)
        return []
    if series is None or not len(series):
        return []
    out: list[tuple[date, float]] = []
    for ts, val in series.items():
        try:
            out.append((ts.date(), float(val)))
        except (AttributeError, TypeError, ValueError):
            continue
    return sorted(out)
