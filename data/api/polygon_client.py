"""
Polygon.io client — slim, ADR-019-scoped wrapper.

Purpose: opt-in additive data source for price history (P1) and short-interest
history (P3). Polygon is NEVER the source of truth for fundamentals or
governance — those stay SEC + edgartools per ADR-018.

Free-tier constraints (per ADR-019 §3):
  - 5 requests/minute via TokenBucket(rate=5/60, burst=5)
  - End-of-day data only (no real-time snapshot — paid tier)
  - HTTP 403 on `/v2/snapshot/...` and other paid endpoints

Failure semantics (per ADR-019 §4.2):
  - POLYGON_API_KEY unset → all methods return empty payloads (no exception)
  - HTTP 429 → wait + retry up to 3 attempts
  - HTTP 403 → short-circuit (no retry; caller treats as paid-tier escalation)
  - HTTP 5xx / network error → retry up to 3 attempts with exp backoff
  - All other failures → return empty list with an error string in `last_error`

This client is sync (mirrors fmp_client.py); it runs inside
asyncio.run_in_executor() worker threads from pipeline.py.

CLAUDE.md determinism guarantee preserved: zero LLM, deterministic JSON parse.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from data.rate_limit import POLYGON_BUCKET

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.polygon.io"
_DEFAULT_TIMEOUT = 15.0
_MAX_RETRIES = 3


# ── Result dataclasses ────────────────────────────────────────────────────


@dataclass
class PolygonBar:
    """One OHLCV bar from /v2/aggs. Date is normalised to Monday-of-week
    for weekly bars so it aligns with yfinance's convention (which uses the
    week-start Monday). Daily bars use the bar's own calendar date.
    """
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    vwap: float | None = None
    volume: int | None = None
    transactions: int | None = None


@dataclass
class PolygonShortInterest:
    """One settlement row from /stocks/v1/short-interest."""
    settlement_date: date
    short_interest: int | None = None
    avg_daily_volume: int | None = None
    days_to_cover: float | None = None


@dataclass
class PolygonIndicatorPoint:
    """Single indicator value (RSI / SMA) at a timestamp."""
    timestamp_ms: int
    value: float


@dataclass
class PolygonMACDPoint:
    """Single MACD record — line + signal + histogram at a timestamp."""
    timestamp_ms: int
    macd_line: float
    signal: float
    histogram: float


@dataclass
class PolygonTickerDetails:
    """Slice of /v3/reference/tickers/{ticker} that we use."""
    ticker: str
    name: str | None = None
    market_cap: float | None = None
    list_date: date | None = None
    primary_exchange: str | None = None
    sic_description: str | None = None
    weighted_shares_outstanding: float | None = None


@dataclass
class PolygonResponse:
    """Wrapper carrying the data + any error context for caller introspection."""
    rows: list = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ── Client ────────────────────────────────────────────────────────────────


class PolygonClient:
    """Sync client. Use from asyncio.run_in_executor() worker threads.

    All methods return a PolygonResponse — they NEVER raise. Caller checks
    `.ok` (or `.error`) to decide how to proceed. This matches the dive
    pipeline's "per-branch failure isolation" guarantee.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        if api_key is None:
            from config.settings import settings
            api_key = settings.polygon_api_key or ""
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._request_count: int = 0

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    def request_count(self) -> int:
        return self._request_count

    # ── Public methods ───────────────────────────────────────────────────

    def fetch_weekly_aggs(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        adjusted: bool = True,
    ) -> PolygonResponse:
        """ADR-019 P1: weekly OHLCV bars over [start, end].

        Pages through `next_url` if more data than fits in one page.
        Date normalised to Monday-of-week so it collides with yfinance's
        week-start dates (UPSERT semantics in persistence layer then
        applies polygon > yfinance precedence).
        """
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")

        path = (
            f"/v2/aggs/ticker/{ticker.upper()}"
            f"/range/1/week/{start.isoformat()}/{end.isoformat()}"
        )
        params: dict[str, Any] = {
            "adjusted": "true" if adjusted else "false",
            "sort": "asc",
            "limit": 100,
        }
        rows = self._paginate_aggs(path, params, granularity="weekly")
        return rows

    def fetch_prev_aggs(
        self,
        ticker: str,
        *,
        adjusted: bool = True,
    ) -> PolygonResponse:
        """ADR-019: yesterday's OHLCV bar — current-price proxy.

        Returns a PolygonResponse whose ``rows`` is at most one
        :class:`PolygonBar`. Daily-granularity bar (no Monday normalisation).
        """
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")
        path = f"/v2/aggs/ticker/{ticker.upper()}/prev"
        params: dict[str, Any] = {"adjusted": "true" if adjusted else "false"}
        data, err = self._get(path, params)
        if err:
            return PolygonResponse(error=err)
        rows: list[PolygonBar] = []
        for raw in data.get("results", []) or []:
            bar = _parse_aggs_row(raw, granularity="daily")
            if bar is not None:
                rows.append(bar)
        return PolygonResponse(rows=rows)

    def fetch_daily_aggs(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
        adjusted: bool = True,
    ) -> PolygonResponse:
        """Daily OHLCV bars over [start, end]."""
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")
        path = (
            f"/v2/aggs/ticker/{ticker.upper()}"
            f"/range/1/day/{start.isoformat()}/{end.isoformat()}"
        )
        params: dict[str, Any] = {
            "adjusted": "true" if adjusted else "false",
            "sort": "asc",
            "limit": 5000,
        }
        return self._paginate_aggs(path, params, granularity="daily")

    def fetch_rsi(
        self,
        ticker: str,
        *,
        window: int = 14,
        timespan: str = "day",
        limit: int = 1,
    ) -> PolygonResponse:
        """RSI series from /v1/indicators/rsi (most-recent-first)."""
        return self._fetch_simple_indicator(
            ticker, "rsi", window=window, timespan=timespan, limit=limit,
        )

    def fetch_sma(
        self,
        ticker: str,
        *,
        window: int = 50,
        timespan: str = "day",
        limit: int = 1,
    ) -> PolygonResponse:
        """SMA series from /v1/indicators/sma. Call separately for 50 and 200."""
        return self._fetch_simple_indicator(
            ticker, "sma", window=window, timespan=timespan, limit=limit,
        )

    def fetch_macd(
        self,
        ticker: str,
        *,
        timespan: str = "day",
        limit: int = 1,
    ) -> PolygonResponse:
        """MACD series — default 12/26/9 windows."""
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")
        path = f"/v1/indicators/macd/{ticker.upper()}"
        params: dict[str, Any] = {
            "timespan": timespan,
            "adjusted": "true",
            "short_window": 12,
            "long_window": 26,
            "signal_window": 9,
            "series_type": "close",
            "order": "desc",
            "limit": limit,
        }
        data, err = self._get(path, params)
        if err:
            return PolygonResponse(error=err)
        rows: list[PolygonMACDPoint] = []
        values = ((data.get("results") or {}).get("values")) or []
        for v in values:
            ts = v.get("timestamp")
            line = _fl(v.get("value"))
            sig = _fl(v.get("signal"))
            hist = _fl(v.get("histogram"))
            if ts is None or line is None or sig is None or hist is None:
                continue
            rows.append(PolygonMACDPoint(
                timestamp_ms=int(ts),
                macd_line=line,
                signal=sig,
                histogram=hist,
            ))
        return PolygonResponse(rows=rows)

    def fetch_ticker_details(self, ticker: str) -> PolygonResponse:
        """/v3/reference/tickers/{ticker} — list_date, market_cap, exchange.

        Returned as a PolygonResponse whose ``rows`` is at most one
        :class:`PolygonTickerDetails`.
        """
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")
        path = f"/v3/reference/tickers/{ticker.upper()}"
        data, err = self._get(path, {})
        if err:
            return PolygonResponse(error=err)
        results = data.get("results") or {}
        if not results:
            return PolygonResponse(rows=[])
        details = PolygonTickerDetails(
            ticker=ticker.upper(),
            name=results.get("name"),
            market_cap=_fl(results.get("market_cap")),
            list_date=_parse_iso_date(results.get("list_date")),
            primary_exchange=results.get("primary_exchange"),
            sic_description=results.get("sic_description"),
            weighted_shares_outstanding=_fl(
                results.get("weighted_shares_outstanding")
            ),
        )
        return PolygonResponse(rows=[details])

    def _fetch_simple_indicator(
        self,
        ticker: str,
        kind: str,
        *,
        window: int,
        timespan: str,
        limit: int,
    ) -> PolygonResponse:
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")
        path = f"/v1/indicators/{kind}/{ticker.upper()}"
        params: dict[str, Any] = {
            "timespan": timespan,
            "adjusted": "true",
            "window": window,
            "series_type": "close",
            "order": "desc",
            "limit": limit,
        }
        data, err = self._get(path, params)
        if err:
            return PolygonResponse(error=err)
        rows: list[PolygonIndicatorPoint] = []
        values = ((data.get("results") or {}).get("values")) or []
        for v in values:
            ts = v.get("timestamp")
            val = _fl(v.get("value"))
            if ts is None or val is None:
                continue
            rows.append(PolygonIndicatorPoint(timestamp_ms=int(ts), value=val))
        return PolygonResponse(rows=rows)

    def fetch_short_interest_history(
        self,
        ticker: str,
        *,
        since: date | None = None,
        max_pages: int = 3,
    ) -> PolygonResponse:
        """ADR-019 P3: time-series short interest from FINRA biweekly settlements.

        Filters to settlement_date >= `since` (default: 12 months ago) so
        we only fetch the recent window F4 actually needs. Without this
        filter, Polygon returns oldest-first from 2017 — wasteful.
        """
        if not self._api_key:
            return PolygonResponse(error="POLYGON_API_KEY not set")

        if since is None:
            since = date.today() - timedelta(days=370)
        params: dict[str, Any] = {
            "ticker": ticker.upper(),
            "settlement_date.gte": since.isoformat(),
            "limit": 50,
        }
        return self._paginate_short_interest(
            "/stocks/v1/short-interest", params, max_pages=max_pages,
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _paginate_aggs(
        self,
        path: str,
        params: dict[str, Any],
        *,
        granularity: str,
    ) -> PolygonResponse:
        rows: list[PolygonBar] = []
        next_url: str | None = None
        page = 0
        max_pages = 10

        while True:
            data, err = self._get(path, params, full_url=next_url)
            if err:
                # Empty rows + error string. F2 falls back to yfinance data.
                return PolygonResponse(rows=rows, error=err)

            for raw in data.get("results", []) or []:
                bar = _parse_aggs_row(raw, granularity=granularity)
                if bar is not None:
                    rows.append(bar)

            next_url = data.get("next_url")
            page += 1
            if not next_url or page >= max_pages:
                break
            # next_url already includes path + query, but excludes apiKey
            path = ""  # signal full_url branch
            params = {}

        return PolygonResponse(rows=rows)

    def _paginate_short_interest(
        self,
        path: str,
        params: dict[str, Any],
        *,
        max_pages: int,
    ) -> PolygonResponse:
        rows: list[PolygonShortInterest] = []
        next_url: str | None = None
        page = 0

        while True:
            data, err = self._get(path, params, full_url=next_url)
            if err:
                return PolygonResponse(rows=rows, error=err)

            for raw in data.get("results", []) or []:
                row = _parse_short_interest_row(raw)
                if row is not None:
                    rows.append(row)

            next_url = data.get("next_url")
            page += 1
            if not next_url or page >= max_pages:
                break
            path = ""
            params = {}

        return PolygonResponse(rows=rows)

    def _get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        full_url: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Execute one GET. Returns (data, error_or_None). Never raises."""
        if full_url:
            url = full_url
            query = {"apiKey": self._api_key}
        else:
            url = f"{_BASE_URL}{path}"
            query = {**params, "apiKey": self._api_key}

        last_err = ""
        for attempt in range(self._max_retries):
            # Bucket-throttle BEFORE each call (including retries) — process-
            # wide singleton so concurrent Polygon tasks share the budget.
            POLYGON_BUCKET.acquire_sync()
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(url, params=query)
            except httpx.HTTPError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt < self._max_retries - 1:
                    time.sleep(2.0 ** attempt)
                continue

            if resp.status_code == 429:
                # Rate limited — respect retry-after if present, else wait 60s.
                retry_after = int(resp.headers.get("retry-after", "60"))
                logger.warning("Polygon 429; waiting %ds (attempt %d/%d)",
                               retry_after, attempt + 1, self._max_retries)
                if attempt < self._max_retries - 1:
                    time.sleep(min(retry_after, 90))
                continue

            if resp.status_code == 403:
                # Paid-tier escalation. No point retrying.
                return {}, "HTTP 403 (paid-tier endpoint or invalid key)"

            if resp.status_code in (401,):
                return {}, f"HTTP {resp.status_code} (auth — check POLYGON_API_KEY)"

            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if attempt < self._max_retries - 1:
                    time.sleep(2.0 ** attempt)
                continue

            try:
                self._request_count += 1
                return resp.json(), None
            except ValueError as exc:
                last_err = f"JSON decode failed: {exc}"
                if attempt < self._max_retries - 1:
                    time.sleep(2.0 ** attempt)

        return {}, last_err or f"failed after {self._max_retries} attempts"


# ── Row parsers ────────────────────────────────────────────────────────────


def _parse_aggs_row(raw: dict[str, Any], *, granularity: str) -> PolygonBar | None:
    t_ms = raw.get("t")
    if t_ms is None:
        return None
    try:
        # tz-aware UTC; .date() strips tz but the wallclock value is correct
        bar_start = datetime.fromtimestamp(int(t_ms) / 1000, tz=UTC).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None

    if granularity == "weekly":
        # Normalise to Monday-of-week (yfinance convention).
        # date.weekday() returns Mon=0..Sun=6
        days_back = bar_start.weekday()
        bar_date = bar_start - timedelta(days=days_back)
    else:
        bar_date = bar_start

    return PolygonBar(
        date=bar_date,
        open=_fl(raw.get("o")),
        high=_fl(raw.get("h")),
        low=_fl(raw.get("l")),
        close=_fl(raw.get("c")),
        vwap=_fl(raw.get("vw")),
        volume=_int(raw.get("v")),
        transactions=_int(raw.get("n")),
    )


def _parse_short_interest_row(raw: dict[str, Any]) -> PolygonShortInterest | None:
    settlement = raw.get("settlement_date")
    if not isinstance(settlement, str):
        return None
    try:
        sdate = datetime.strptime(settlement[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return PolygonShortInterest(
        settlement_date=sdate,
        short_interest=_int(raw.get("short_interest")),
        avg_daily_volume=_int(raw.get("avg_daily_volume")),
        days_to_cover=_fl(raw.get("days_to_cover")),
    )


def _fl(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:    # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
