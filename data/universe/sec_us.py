"""
SEC US universe provider — pulls every SEC-filer ticker from
`https://www.sec.gov/files/company_tickers_exchange.json` (~1MB, ~10000 entries).

Source format (SEC):
    {
      "fields": ["cik", "name", "ticker", "exchange"],
      "data": [
        [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
        ...
      ]
    }

Cached for 7 days (SEC publishes daily but the universe rarely shifts more
than a handful of names per week — IPOs, delistings, ticker changes).
Filters out OTC pink-sheets, structured products (warrant suffixes / unit
suffixes / preferred share suffixes) at enumeration time so the screener
doesn't waste a yfinance call on them later.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from data.cache.manager import CacheManager
from data.universe.base import UniverseTicker

logger = logging.getLogger(__name__)

_SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_CACHE_KEY = "universe:sec_us:company_tickers_exchange"
_CACHE_TTL_SEC = 7 * 24 * 3600   # 7 days

# Suffixes that mark a non-common-stock ticker we don't want in the universe.
# Examples:
#   AAPL      keep (common)
#   BRK.B     keep (Berkshire B is a real share class)
#   SPXX.WS   drop (warrant)
#   UAVS.U    drop (SPAC unit)
#   ABC-PR-X  drop (preferred shares)
#   ABC.U     drop (units)
#   ABC$P     drop (some preferred notations)
_DROP_SUFFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.WS$", re.I),         # warrants
    re.compile(r"\.U$", re.I),          # SPAC units
    re.compile(r"\.UN$", re.I),         # units (alt notation)
    re.compile(r"\.WT$", re.I),         # warrants alt
    re.compile(r"-PR-?", re.I),         # preferred class suffix
    re.compile(r"\$P$", re.I),          # preferred (some notations)
    re.compile(r"\^.+$"),                # carat-suffixed special issues
)


class SecUsUniverseProvider:
    """SEC company_tickers_exchange.json provider."""

    region_code = "us"

    def __init__(self, identity: str | None = None) -> None:
        self._identity = identity
        self._cache = CacheManager()

    def fetch(self) -> list[UniverseTicker]:
        """Return the full SEC US universe, applying common-stock filters."""
        payload = self._cache.get(_CACHE_KEY)
        if payload is None:
            payload = self._fetch_remote()
            if payload is not None:
                self._cache.set(_CACHE_KEY, payload, ttl=_CACHE_TTL_SEC)

        if not payload:
            logger.warning("SEC universe fetch failed; returning empty universe")
            return []

        return self._parse(payload)

    # ── Internals ────────────────────────────────────────────────────────

    def _fetch_remote(self) -> dict[str, Any] | None:
        from data.api._retry import sec_get_with_retry
        identity = self._identity or self._resolve_identity()
        headers = {
            "User-Agent": identity,
            "Accept-Encoding": "gzip",
            "Host": "www.sec.gov",
        }
        resp = sec_get_with_retry(
            _SEC_URL, headers=headers, timeout=30.0, label="sec_universe",
        )
        if resp is None or resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            logger.warning("SEC universe parse failed: %s", exc)
            return None

    @staticmethod
    def _resolve_identity() -> str:
        from config.settings import require_edgar_identity
        return require_edgar_identity()

    @staticmethod
    def _parse(payload: dict[str, Any]) -> list[UniverseTicker]:
        fields = payload.get("fields") or []
        rows = payload.get("data") or []
        if not fields or not rows:
            return []

        # Build column index map (defensive — order has been stable but who knows).
        idx = {name: i for i, name in enumerate(fields)}
        i_cik = idx.get("cik")
        i_name = idx.get("name")
        i_ticker = idx.get("ticker")
        i_exchange = idx.get("exchange")

        if None in (i_cik, i_name, i_ticker, i_exchange):
            logger.error(
                "SEC universe: unexpected fields %s; aborting parse", fields
            )
            return []

        out: list[UniverseTicker] = []
        for row in rows:
            try:
                cik_raw = row[i_cik]
                ticker = (row[i_ticker] or "").strip()
                if not ticker:
                    continue
                if SecUsUniverseProvider._is_filtered_ticker(ticker):
                    continue
                exchange = (row[i_exchange] or "").strip()
                # Drop tickers without a real exchange (some private filers)
                if not exchange or exchange.lower() == "n/a":
                    continue

                out.append(UniverseTicker(
                    ticker=ticker.upper(),
                    name=(row[i_name] or "").strip(),
                    exchange=exchange,
                    cik=str(int(cik_raw)).zfill(10),
                    market_cap=None,        # populated by Tier 2
                    sector=None,            # populated by Tier 2
                    source="sec_us",
                ))
            except (IndexError, TypeError, ValueError):
                continue

        # Dedupe by ticker (some CIKs share a ticker, keep the first seen)
        seen: set[str] = set()
        deduped: list[UniverseTicker] = []
        for u in out:
            if u.ticker in seen:
                continue
            seen.add(u.ticker)
            deduped.append(u)
        return deduped

    @staticmethod
    def _is_filtered_ticker(ticker: str) -> bool:
        for pat in _DROP_SUFFIX_PATTERNS:
            if pat.search(ticker):
                return True
        return False
