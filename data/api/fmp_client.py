"""
Slim FMP (Financial Modeling Prep) client — screener Tier 2 metadata only.

Per ADR-016: FMP's `/v3/stock-screener` endpoint is the ONLY FMP usage in
the lab. One bulk call replaces ~10,000 yfinance metadata calls. Returns
ticker + name + market_cap + sector + industry + exchange + country +
isActivelyTrading per matching company.

Free tier limits (as of 2026-05):
  - 250 calls / day
  - We use 1 call per screener run (≤2% of daily quota at quarterly cadence)

This is a vendored slim copy of `next-nvidia-detector/microservices/shared/
data_sources/fmp.py` (910 LOC); we only need ~150 LOC for the screener
endpoint. Vendoring keeps the repository free of cross-project imports.

NOT USED FOR FUNDAMENTALS: per-ticker fundamentals stay SEC EDGAR-only
(DEC-09 SEC frames, DEC-03 SEC companyfacts). FMP is a metadata-source-of-record
ONLY for the bulk universe filter.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/stable"
# FMP retired legacy /api/v3/* endpoints on 2025-08-31. Free tier now lives at
# /stable/* with renamed paths:
#   stock-screener  → company-screener
#   quote/{ticker}  → quote?symbol={ticker}
#   profile/{ticker} → profile?symbol={ticker}
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_WAIT_429 = 60    # seconds
_RATE_LIMIT_DELAY = 0.4         # min seconds between successful calls


# ── Result type ──────────────────────────────────────────────────────────


@dataclass
class FMPScreenerEntry:
    """One row from FMP's /v3/stock-screener bulk response."""
    ticker: str
    name: str
    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    exchange_short: str | None = None
    country: str | None = None
    price: float | None = None
    beta: float | None = None
    is_actively_trading: bool = False


@dataclass
class FMPProfile:
    """Slice of /stable/profile fields ADR-018 D1 (CEO) and D7 (IPO) need.

    Per ADR-018 §A.2 probe results, this endpoint is the most reliable
    free-tier source of CEO name + IPO date for large/mid caps. Small
    caps may return HTTP 402 (silent paid escalation); the caller treats
    that as "no value", not an error.
    """
    ticker: str
    company_name: str | None = None
    ceo: str | None = None
    ipo_date: "Any | None" = None     # date object — Any to keep dataclass forward-clean
    cik: str | None = None
    sector: str | None = None
    industry: str | None = None
    full_time_employees: int | None = None
    error: str | None = None


class FMPClient:
    """
    Minimal FMP HTTP client. Sliding-window rate limiting + retry on 429s
    + exponential backoff. Mirrors the rate-limit semantics of the main
    project's FMPClient but with only the screener endpoint exposed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_wait_429: int = _DEFAULT_RETRY_WAIT_429,
        rate_limit_delay: float = _RATE_LIMIT_DELAY,
    ) -> None:
        if api_key is None:
            from config.settings import settings
            api_key = settings.fmp_api_key or ""
        if not api_key:
            raise ValueError(
                "FMP_API_KEY required. Set in .env or pass api_key= explicitly. "
                "Free key: https://site.financialmodelingprep.com/developer/docs"
            )
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_wait_429 = retry_wait_429
        self._rate_limit_delay = rate_limit_delay
        self._last_request_at: float = 0.0
        self._request_count: int = 0

    # ── Public API ───────────────────────────────────────────────────────

    def fetch_screener_universe(
        self,
        cap_min: float | None = None,
        cap_max: float | None = None,
        sector: str | None = None,
        industry: str | None = None,
        exchange: str | None = None,
        country: str = "US",
        is_actively_trading: bool = True,
        limit: int = 10000,
    ) -> list[FMPScreenerEntry]:
        """
        ONE bulk call to /v3/stock-screener. Returns matching companies with
        cap, sector, industry, exchange. Server-side filtered by all
        supplied params.

        Free tier: this single call counts as 1 of 250/day.
        """
        params: dict[str, Any] = {
            "isActivelyTrading": "true" if is_actively_trading else "false",
            "limit": limit,
            "apikey": self._api_key,
        }
        if cap_min is not None:
            params["marketCapMoreThan"] = int(cap_min)
        if cap_max is not None:
            params["marketCapLowerThan"] = int(cap_max)
        if sector:
            params["sector"] = sector
        if industry:
            params["industry"] = industry
        if exchange:
            params["exchange"] = exchange
        if country:
            params["country"] = country

        payload = self._get("/company-screener", params)
        if not isinstance(payload, list):
            logger.warning("FMP screener returned non-list payload: %s", type(payload))
            return []

        return [_to_entry(row) for row in payload if isinstance(row, dict)]

    def fetch_profile(self, ticker: str) -> "FMPProfile":
        """One call to /stable/profile?symbol=TICKER.

        Returns FMPProfile with `error` set on any failure (HTTP, 402 from
        FMP's silent paid-tier escalation on small caps, JSON malformed).
        Caller never sees an exception — the dive treats absence as a gap
        the next-priority source must cover.

        ~150-300 ms wall-clock, ~5 KB response, 1 of 250/day quota.
        """
        try:
            payload = self._get("/profile",
                                {"symbol": ticker.upper(), "apikey": self._api_key})
        except RuntimeError as exc:
            msg = str(exc)
            if "402" in msg:
                return FMPProfile(ticker=ticker.upper(), error="402 (paid-tier escalation)")
            return FMPProfile(ticker=ticker.upper(), error=f"http: {msg[:120]}")

        if not isinstance(payload, list) or not payload:
            return FMPProfile(ticker=ticker.upper(), error="empty list")
        row = payload[0]
        if not isinstance(row, dict):
            return FMPProfile(ticker=ticker.upper(), error="non-dict row")

        return FMPProfile(
            ticker=ticker.upper(),
            company_name=_clean_str(row.get("companyName")),
            ceo=_clean_str(row.get("ceo")),
            ipo_date=_parse_iso_date(row.get("ipoDate")),
            cik=_clean_str(row.get("cik")),
            sector=_clean_str(row.get("sector")),
            industry=_clean_str(row.get("industry")),
            full_time_employees=_parse_int(row.get("fullTimeEmployees")),
        )

    def request_count(self) -> int:
        """How many successful requests this client has made (debug / quota tracking)."""
        return self._request_count

    # ── Internals ────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        """GET with rate limiting + retry on 429 + backoff."""
        self._respect_rate_limit()

        url = f"{_BASE_URL}{path}"
        last_err: str = ""

        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                if attempt < self._max_retries - 1:
                    time.sleep(2.0 ** attempt)
                continue

            if resp.status_code == 429:
                logger.warning(
                    "FMP rate limit hit (attempt %d/%d); waiting %ds",
                    attempt + 1, self._max_retries, self._retry_wait_429,
                )
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_wait_429)
                continue

            if resp.status_code in (401, 403):
                # Auth failure — no point retrying
                raise RuntimeError(
                    f"FMP auth failed: HTTP {resp.status_code}. "
                    "Check FMP_API_KEY validity."
                )

            if resp.status_code == 402:
                # Silent paid-tier escalation (per ADR-018 §A.2). FMP free
                # tier returns 402 on some endpoints for small caps. Don't
                # retry — caller treats it as "no value" and falls through.
                raise RuntimeError(f"HTTP 402 (paid-tier escalation)")

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_err = f"HTTP {resp.status_code}: {exc}"
                if attempt < self._max_retries - 1:
                    time.sleep(2.0 ** attempt)
                continue

            try:
                self._request_count += 1
                self._last_request_at = time.monotonic()
                return resp.json()
            except ValueError as exc:
                last_err = f"JSON decode failed: {exc}"
                if attempt < self._max_retries - 1:
                    time.sleep(2.0 ** attempt)
                continue

        raise RuntimeError(f"FMP request failed after {self._max_retries} attempts: {last_err}")

    def _respect_rate_limit(self) -> None:
        """Sleep if needed to honour rate_limit_delay between calls."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)


# ── Helpers ──────────────────────────────────────────────────────────────


def _to_entry(row: dict[str, Any]) -> FMPScreenerEntry:
    """Map FMP screener row → FMPScreenerEntry."""
    return FMPScreenerEntry(
        ticker=str(row.get("symbol") or "").upper(),
        name=str(row.get("companyName") or ""),
        market_cap=_f(row.get("marketCap")),
        sector=row.get("sector") or None,
        industry=row.get("industry") or None,
        exchange=row.get("exchange") or None,
        exchange_short=row.get("exchangeShortName") or None,
        country=row.get("country") or None,
        price=_f(row.get("price")),
        beta=_f(row.get("beta")),
        is_actively_trading=bool(row.get("isActivelyTrading", False)),
    )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clean_str(v: Any) -> str | None:
    """Strip + normalise; return None for empty / None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _parse_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(str(v).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_iso_date(v: Any) -> "Any | None":
    """Parse 'YYYY-MM-DD' to datetime.date."""
    if not isinstance(v, str) or len(v) < 10:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
