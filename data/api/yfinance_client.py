"""
yfinance typed wrapper — comprehensive equity data, zero API key.

Fetches everything yfinance exposes in a single synchronous call:
  - Company profile (sector, industry, market cap, exchange, currency)
  - Management (CEO name, total compensation)
  - Ownership (insider %, institutional %, short %)
  - Individual institutional holders (top 20 by position)
  - Recent insider transactions (Form 4 equivalent from yfinance)
  - Historical price data (weekly, up to 20 years)
  - Analyst consensus (count, recommendation, price targets)
  - Trailing valuation ratios (P/E, P/B, EV/EBITDA — cross-check only)

All functions are synchronous — call via asyncio.run_in_executor() from
the async pipeline. yfinance is a web scraper; treat it as best-effort.
Gaps are reported via the `gaps` list, never raise on missing fields.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


# ── Data containers ───────────────────────────────────────────────────────


@dataclass
class YFCompanyInfo:
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    currency: str | None = None
    country: str | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    float_shares: float | None = None
    # Management
    ceo_name: str | None = None
    ceo_total_pay: float | None = None         # annual compensation (USD)
    # Ownership percentages (converted to 0-100 scale from yfinance 0.0-1.0)
    insider_pct: float | None = None           # ALL insiders combined (not CEO-only)
    institution_pct: float | None = None       # all institutional holders combined
    short_pct_float: float | None = None       # % of float sold short
    # Analyst consensus
    analyst_count: int | None = None
    recommendation: str | None = None         # 'buy' | 'hold' | 'sell' | 'strong buy'
    target_price_mean: float | None = None
    target_price_high: float | None = None
    target_price_low: float | None = None
    # Current price snapshot
    current_price: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    beta: float | None = None
    # Trailing valuation ratios (supplementary cross-check against EDGAR)
    pe_trailing: float | None = None
    pb_ratio: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None        # annual yield as decimal (e.g. 0.015 = 1.5%)
    # IPO / first-trade date — yfinance firstTradeDateEpochUtc → date.
    # Persisted to Company.ipo_date so the dive feasibility check can
    # accurately flag recent IPOs without inferring from price history.
    first_trade_date: date | None = None


@dataclass
class YFInstitutionalHolder:
    holder_name: str
    shares: int | None = None
    value_usd: float | None = None
    pct_out: float | None = None               # % of shares outstanding (0-100 scale)
    date_reported: date | None = None


@dataclass
class YFInsiderTransaction:
    insider_name: str | None = None
    insider_title: str | None = None
    transaction_type: str | None = None        # 'Purchase' | 'Sale' | 'Sale (Automatic)'
    shares: float | None = None
    value_usd: float | None = None
    transaction_date: date | None = None


@dataclass
class YFPriceRow:
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    adj_close: float | None = None             # same as close when auto_adjust=True
    volume: int | None = None


@dataclass
class YFEarningsRow:
    """One historical earnings report from yfinance.Ticker.earnings_dates.

    `event_date` is when the market reacts (the report timestamp's date).
    `event_time` is "BMO" (before market open), "AMC" (after market close),
    or "intraday" — derived from the time-of-day. ADR-018 D6 + the prior
    TradingView/Finviz time-separation directive both rely on this split.
    """
    event_date: date
    event_time: str | None = None              # 'BMO' | 'AMC' | 'intraday' | None
    eps_estimate: float | None = None
    eps_actual: float | None = None
    eps_surprise_pct: float | None = None


@dataclass
class YFSnapshot:
    """All yfinance data for one ticker, fetched in a single function call."""
    info: YFCompanyInfo
    institutional_holders: list[YFInstitutionalHolder] = field(default_factory=list)
    insider_transactions: list[YFInsiderTransaction] = field(default_factory=list)
    price_history: list[YFPriceRow] = field(default_factory=list)
    earnings_history: list[YFEarningsRow] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


@dataclass
class YFMetadataLite:
    """Minimal yfinance metadata for the screener's Tier 2 universe filter.

    Skips holders / insiders / price history — all heavy. ~200ms per ticker
    vs ~1s for the full snapshot. The screener uses this to filter ~3000
    tickers down to ~1500 by market cap + sector before any fundamentals
    work happens.
    """
    ticker: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    currency: str | None = None
    country: str | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    float_shares: float | None = None
    analyst_count: int | None = None
    first_trade_date: date | None = None       # yfinance firstTradeDateEpochUtc → date
    error: str | None = None    # set when yfinance returns no data (delisted, suspended, etc.)


# ── Public entry point ────────────────────────────────────────────────────


def fetch_yfinance_metadata_only(
    ticker: str,
    retries: int = 3,
    backoff_base: float = 1.5,
) -> YFMetadataLite:
    """
    Lite variant — fetches only `.info` for screener Tier 2.

    Yahoo's anti-abuse layer hands out "Invalid Crumb" 401s when a single
    process hits its API too fast. We mitigate with:
      1. Per-call retry with exponential backoff (3 attempts default)
      2. Crumb refresh between attempts (yfinance picks up a fresh one
         when we instantiate a new Ticker)
      3. Caller is expected to also limit concurrency (semaphore=1 for live
         universe-wide screens; 5 for short tests)

    Returns YFMetadataLite with `error` set on persistent failure rather than
    raising — pipeline drops error rows at the cap/sector filter step.
    """
    import time
    import yfinance as yf
    out = YFMetadataLite(ticker=ticker.upper())

    raw: dict | None = None
    last_err: str = ""
    for attempt in range(retries):
        try:
            raw = yf.Ticker(ticker).info
            if raw and isinstance(raw, dict) and (raw.get("symbol") or raw.get("longName") or raw.get("shortName")):
                break    # got real data
            # Empty response — treat as transient and retry
            last_err = "empty .info response"
        except Exception as exc:    # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < retries - 1:
            time.sleep(backoff_base ** attempt)    # 1.0s, 1.5s, 2.25s

    if not raw or not isinstance(raw, dict):
        out.error = f"yfinance failed after {retries} attempts: {last_err}"
        return out

    out.name = raw.get("longName") or raw.get("shortName")
    out.sector = raw.get("sector")
    out.industry = raw.get("industry")
    out.exchange = raw.get("exchange") or raw.get("exchangeShortName")
    out.currency = raw.get("currency")
    out.country = raw.get("country")
    out.market_cap = _f(raw.get("marketCap"))
    out.shares_outstanding = _f(raw.get("sharesOutstanding"))
    out.float_shares = _f(raw.get("floatShares"))
    out.analyst_count = _i(raw.get("numberOfAnalystOpinions"))

    # First trade date — used as IPO date proxy
    out.first_trade_date = _parse_first_trade_date(raw)

    return out


def fetch_yfinance_snapshot(ticker: str, price_history_years: int = 20) -> YFSnapshot:
    """
    Fetch all available yfinance data for `ticker`.

    Called synchronously. In the async pipeline, wrap with:
        await loop.run_in_executor(None, lambda: fetch_yfinance_snapshot(ticker))

    `price_history_years`: how many years of weekly price history to fetch (max 20).
    """
    import yfinance as yf

    yticker = yf.Ticker(ticker)
    gaps: list[str] = []

    info = _parse_info(ticker, yticker.info, gaps)
    institutions = _parse_institutional_holders(ticker, yticker, gaps)
    insiders = _parse_insider_transactions(ticker, yticker, gaps)
    prices = _parse_price_history(ticker, yticker, min(price_history_years, 20), gaps)
    earnings = _parse_earnings_history(ticker, yticker, gaps)

    return YFSnapshot(
        info=info,
        institutional_holders=institutions,
        insider_transactions=insiders,
        price_history=prices,
        earnings_history=earnings,
        gaps=gaps,
    )


# ── Info parsing ──────────────────────────────────────────────────────────


def _parse_info(ticker: str, raw: dict, gaps: list[str]) -> YFCompanyInfo:
    info = YFCompanyInfo(ticker=ticker)

    info.name = raw.get("longName") or raw.get("shortName")
    info.sector = raw.get("sector")
    info.industry = raw.get("industry")
    info.exchange = raw.get("exchange") or raw.get("exchangeShortName")
    info.currency = raw.get("currency")
    info.country = raw.get("country")
    info.market_cap = _f(raw.get("marketCap"))
    info.shares_outstanding = _f(raw.get("sharesOutstanding"))
    info.float_shares = _f(raw.get("floatShares"))

    # CEO — yfinance companyOfficers is a list ordered roughly by seniority.
    # Title formats vary: "Co-Founder, CEO & Director", "Chairman & CEO",
    # "Chief Executive Officer", "President & CEO". The previous matcher
    # required substring 'chief executive' or full-string == 'ceo' — both
    # missed the comma- or ampersand-separated forms that AAPL, NVDA, INTA
    # actually use (probed in ADR-018 §2.1). We tokenise on `, & /` plus
    # whitespace and look for any token equal to 'ceo' OR substring
    # 'chief executive officer' / 'chief executive'.
    info.ceo_name, info.ceo_total_pay = _match_ceo_officer(raw.get("companyOfficers", []))

    if not info.ceo_name:
        gaps.append(f"{ticker}: yfinance CEO name not found in companyOfficers")

    # Ownership (yfinance uses 0.0–1.0 fractions → convert to 0–100 %)
    insider_frac = raw.get("heldPercentInsiders")
    inst_frac = raw.get("heldPercentInstitutions")
    short_frac = raw.get("shortPercentOfFloat")

    info.insider_pct = _pct(insider_frac)
    info.institution_pct = _pct(inst_frac)
    info.short_pct_float = _pct(short_frac)

    if info.short_pct_float is None:
        gaps.append(f"{ticker}: yfinance shortPercentOfFloat unavailable")
    if info.institution_pct is None:
        gaps.append(f"{ticker}: yfinance heldPercentInstitutions unavailable")

    # Analyst
    info.analyst_count = _i(raw.get("numberOfAnalystOpinions"))
    info.recommendation = raw.get("recommendationKey") or raw.get("recommendation")
    info.target_price_mean = _f(raw.get("targetMeanPrice"))
    info.target_price_high = _f(raw.get("targetHighPrice"))
    info.target_price_low = _f(raw.get("targetLowPrice"))

    # Price
    info.current_price = _f(raw.get("currentPrice") or raw.get("regularMarketPrice"))
    info.fifty_two_week_high = _f(raw.get("fiftyTwoWeekHigh"))
    info.fifty_two_week_low = _f(raw.get("fiftyTwoWeekLow"))
    info.beta = _f(raw.get("beta"))

    # Trailing ratios (use with caution — point-in-time, not historical)
    info.pe_trailing = _f(raw.get("trailingPE"))
    info.pb_ratio = _f(raw.get("priceToBook"))
    info.ev_ebitda = _f(raw.get("enterpriseToEbitda"))
    info.dividend_yield = _f(raw.get("dividendYield"))

    # First-trade / IPO date — yfinance exposes this under several keys
    # depending on version; check them all and fall back to the ISO string.
    info.first_trade_date = _parse_first_trade_date(raw)

    return info


def _parse_earnings_history(
    ticker: str, yticker: object, gaps: list[str]
) -> list["YFEarningsRow"]:
    """Pull historical EPS estimate / actual / surprise from yfinance.

    yfinance.Ticker.earnings_dates is a DataFrame indexed by report
    timestamp with columns 'EPS Estimate', 'Reported EPS', 'Surprise(%)'.
    The timestamp's hour-of-day distinguishes BMO vs AMC reports:
      - hour < 9   → BMO (typically 06:00-09:00 ET)
      - hour > 15  → AMC (typically 16:00-17:00 ET)
      - else       → 'intraday' (rare; some companies report at midday)

    Returns most-recent-first, capped at 20 rows. Failure → empty list +
    gap string (caller's existing pattern).
    """
    try:
        df = yticker.earnings_dates  # type: ignore[attr-defined]
    except Exception as exc:
        gaps.append(f"{ticker}: yfinance earnings_dates unavailable ({type(exc).__name__})")
        return []

    if df is None or not hasattr(df, "iterrows") or len(df) == 0:
        gaps.append(f"{ticker}: yfinance earnings_dates empty")
        return []

    rows: list[YFEarningsRow] = []
    try:
        for ts, row in df.iterrows():
            try:
                event_date_val = _ts_to_date(ts)
                if event_date_val is None:
                    continue
                hour = _ts_to_hour(ts)
                event_time = _classify_session(hour)
                eps_est = _f(row.get("EPS Estimate"))
                eps_act = _f(row.get("Reported EPS"))
                surprise = _f(row.get("Surprise(%)"))
                rows.append(YFEarningsRow(
                    event_date=event_date_val,
                    event_time=event_time,
                    eps_estimate=eps_est,
                    eps_actual=eps_act,
                    eps_surprise_pct=surprise,
                ))
            except Exception as exc:
                logger.debug("earnings row parse error (%s): %s", ticker, exc)
    except Exception as exc:
        gaps.append(f"{ticker}: yfinance earnings_dates iter error ({type(exc).__name__})")

    return rows[:20]


def _ts_to_date(ts: object) -> date | None:
    """yfinance index entries are pandas Timestamps; extract calendar date."""
    if ts is None:
        return None
    if hasattr(ts, "to_pydatetime"):
        try:
            return ts.to_pydatetime().date()
        except Exception:
            return None
    if isinstance(ts, date):
        return ts
    return None


def _ts_to_hour(ts: object) -> int | None:
    """Local-exchange hour-of-day from timestamp, used for AMC/BMO classification."""
    if ts is None:
        return None
    if hasattr(ts, "hour"):
        try:
            return int(ts.hour)
        except (TypeError, ValueError):
            return None
    return None


def _classify_session(hour: int | None) -> str | None:
    if hour is None:
        return None
    if hour < 9:
        return "BMO"
    if hour >= 16:
        return "AMC"
    return "intraday"


def _match_ceo_officer(officers: list) -> tuple[str | None, float | None]:
    """Find the CEO row in yfinance's companyOfficers list.

    Tokenises titles on `, & /` plus whitespace and tests for:
      - any token equal to 'ceo' (case-insensitive)
      - substring 'chief executive officer' (3-word phrase)
      - substring 'chief executive' (legacy / abbreviated)
    Returns (name, total_pay) of the first matching officer.

    Examples that now match:
      - "Co-Founder, CEO & Director"  (NVDA)
      - "Chairman & CEO"              (INTA)
      - "President & CEO"             (common)
      - "Chief Executive Officer"     (full-form)
    """
    for officer in officers or []:
        title = (officer.get("title") or "").strip()
        if not title:
            continue
        if _title_indicates_ceo(title):
            return _read_officer(officer)
    return None, None


def _title_indicates_ceo(title: str) -> bool:
    """True iff the title text indicates a CEO role."""
    import re
    title_lc = title.lower()
    if "chief executive officer" in title_lc or "chief executive" in title_lc:
        return True
    tokens = {t.strip(".,") for t in re.split(r"[\s,&/]+", title_lc) if t}
    return "ceo" in tokens


def is_ceo_a_founder(officers: list) -> bool | None:
    """ADR-018 D3 — does yfinance's CEO officer row have founder language?

    Returns True iff the same officer row that matched as CEO ALSO has
    'founder' or 'co-founder' in its title (case-insensitive).
    Returns None when no CEO row was matched (don't claim 'False' from
    absence of evidence).

    Examples:
      "Co-Founder, CEO & Director"  (NVDA)  → True
      "Chairman & CEO"              (INTA)  → False  (yf doesn't mark Hall as founder
                                                       even though SEC sources do — caller
                                                       OR-merges with regex source)
    """
    import re
    for officer in officers or []:
        title = (officer.get("title") or "").strip()
        if not title or not _title_indicates_ceo(title):
            continue
        title_lc = title.lower()
        if re.search(r"(?:^|\W)(?:co-?\s*founders?|founders?)(?:\W|$)", title_lc):
            return True
        return False
    return None


def _read_officer(officer: dict) -> tuple[str | None, float | None]:
    name = officer.get("name") or None
    pay = officer.get("totalPay")
    if isinstance(pay, dict):                   # yfinance sometimes wraps as {"raw": ...}
        pay = pay.get("raw")
    return name, _f(pay)


def _parse_first_trade_date(raw: dict) -> "date | None":
    """yfinance exposes the IPO/first-trade date inconsistently:
      - firstTradeDateMilliseconds (recent versions) — int, ms since epoch
      - firstTradeDateEpochUtc                       — int, seconds since epoch
      - firstTradeDate                                — int, seconds since epoch
      - ipoExpectedDate                               — ISO string 'YYYY-MM-DD'
    Probe in priority order; return the first parseable value.
    """
    from datetime import UTC, datetime
    ms = raw.get("firstTradeDateMilliseconds")
    if ms is not None:
        try:
            return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).date()
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    epoch = raw.get("firstTradeDateEpochUtc") or raw.get("firstTradeDate")
    if epoch is not None:
        try:
            return datetime.fromtimestamp(int(epoch), tz=UTC).date()
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    iso = raw.get("ipoExpectedDate")
    if isinstance(iso, str) and len(iso) >= 10:
        try:
            return datetime.strptime(iso[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            pass
    return None


# ── Institutional holders ─────────────────────────────────────────────────


def _parse_institutional_holders(
    ticker: str, yticker: object, gaps: list[str]
) -> list[YFInstitutionalHolder]:
    try:
        import pandas as pd
        df = yticker.institutional_holders  # type: ignore[union-attr]
        if df is None or df.empty:
            gaps.append(f"{ticker}: yfinance institutional_holders unavailable")
            return []

        rows: list[YFInstitutionalHolder] = []
        for _, row in df.iterrows():
            holder_date = _parse_date(row.get("Date Reported") or row.get("dateReported"))
            raw_pct = _f(row.get("% Out") or row.get("pctOut"))
            # yfinance sometimes returns fractions (0.05) sometimes percents (5.0)
            pct = raw_pct * 100.0 if (raw_pct is not None and raw_pct <= 1.0) else raw_pct
            rows.append(YFInstitutionalHolder(
                holder_name=str(row.get("Holder") or row.get("holder") or ""),
                shares=_i(row.get("Shares") or row.get("shares")),
                value_usd=_f(row.get("Value") or row.get("value")),
                pct_out=pct,
                date_reported=holder_date,
            ))
        return rows
    except Exception as exc:
        gaps.append(f"{ticker}: yfinance institutional_holders error — {exc}")
        return []


# ── Insider transactions ──────────────────────────────────────────────────


def _parse_insider_transactions(
    ticker: str, yticker: object, gaps: list[str]
) -> list[YFInsiderTransaction]:
    try:
        df = yticker.insider_transactions  # type: ignore[union-attr]
        if df is None or df.empty:
            return []

        rows: list[YFInsiderTransaction] = []
        for _, row in df.iterrows():
            txn_date = _parse_date(row.get("Start Date") or row.get("startDate"))
            rows.append(YFInsiderTransaction(
                insider_name=str(row.get("Insider") or row.get("insider") or "") or None,
                insider_title=str(row.get("Position") or row.get("position") or "") or None,
                transaction_type=str(row.get("Transaction") or row.get("transaction") or "") or None,
                shares=_f(row.get("Shares") or row.get("shares")),
                value_usd=_f(row.get("Value") or row.get("value")),
                transaction_date=txn_date,
            ))
        return rows
    except Exception as exc:
        logger.debug("yfinance insider_transactions error (%s): %s", ticker, exc)
        return []


# ── Price history ─────────────────────────────────────────────────────────


def _parse_price_history(
    ticker: str, yticker: object, years: int, gaps: list[str]
) -> list[YFPriceRow]:
    """
    Fetch weekly adjusted price history for up to `years` years.
    auto_adjust=True means Close already equals adjusted close.

    `years=0` means the caller's framework set doesn't need price history
    (e.g. F1 alone). Skip the call entirely; yfinance rejects period='0y'.
    """
    if years <= 0:
        return []
    try:
        import pandas as pd
        period = f"{years}y"
        df = yticker.history(period=period, interval="1wk", auto_adjust=True)  # type: ignore[union-attr]
        if df is None or df.empty:
            gaps.append(f"{ticker}: yfinance price history unavailable")
            return []

        rows: list[YFPriceRow] = []
        for idx, row in df.iterrows():
            rows.append(YFPriceRow(
                date=pd.Timestamp(idx).date(),
                open=_f(row.get("Open")),
                high=_f(row.get("High")),
                low=_f(row.get("Low")),
                close=_f(row.get("Close")),
                adj_close=_f(row.get("Close")),  # auto_adjust=True: Close IS adj close
                volume=_i(row.get("Volume")),
            ))
        return rows
    except Exception as exc:
        gaps.append(f"{ticker}: yfinance price history error — {exc}")
        return []


# ── Type coercion helpers ─────────────────────────────────────────────────


def _f(val: object) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # NaN check — pandas often returns NaN for missing future-quarter values
    if f != f:
        return None
    return f


def _i(val: object) -> int | None:
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return int(f)


def _pct(frac: object) -> float | None:
    """Convert yfinance 0.0–1.0 fraction to 0–100 % scale."""
    v = _f(frac)
    return v * 100.0 if v is not None else None


def _parse_date(val: object) -> date | None:
    if val is None:
        return None
    try:
        import pandas as pd
        return pd.Timestamp(val).date()  # type: ignore[arg-type]
    except Exception:
        return None


# ── Stock splits (ADR-030-A2 follow-up) ───────────────────────────────────
#
# EDGAR share counts are as-filed, and our restatement rule keeps the
# latest-filed value per fiscal year — so years covered by a post-split
# filing carry restated counts while earlier years do not. CSGP's FY2019 and
# FY2020 read 363M/381M against an actual ~37M/39M because the 2021-06-28
# 10:1 split restated exactly those comparatives. Pairing a mixed-basis
# series with split-adjusted prices misstates historical market cap by the
# split ratio.


def fetch_stock_splits(ticker: str) -> list[tuple[date, float]]:
    """Split events as (effective_date, ratio), oldest first. Empty on failure."""
    try:
        import yfinance as yf
        series = yf.Ticker(ticker).splits
    except Exception as exc:  # noqa: BLE001 — scraper; never fail the pipeline
        logger.warning("yfinance splits unavailable for %s: %s", ticker, exc)
        return []
    out: list[tuple[date, float]] = []
    for ts, ratio in getattr(series, "items", lambda: [])():
        try:
            d, r = ts.date(), float(ratio)
        except (AttributeError, TypeError, ValueError):
            continue
        if r > 0:
            out.append((d, r))
    return sorted(out)


def cumulative_split_factor(as_of: date, splits: list[tuple[date, float]]) -> float:
    """Product of split ratios effective AFTER `as_of`.

    Multiplying an as-filed count by this restates it onto today's basis, which
    is the basis split-adjusted prices are quoted on.
    """
    factor = 1.0
    for split_date, ratio in splits:
        if split_date > as_of:
            factor *= ratio
    return factor
