"""
SEC EDGAR `frames.json` bulk fetcher — universe-wide one-concept-at-a-time
fundamentals fetch (docs/architecture/SCREENER_PIPELINE.md §1 Tier 4, DECISIONS.md DEC-09).

Endpoint:
  https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json

Each call returns ONE concept across ALL filers that reported it for a given
period. ~30 calls cover the entire universe's screening fundamentals — vs
~10000 per-ticker companyfacts calls. This is the architectural unlock that
makes the screener scale to ~5000 tickers.

Period naming (calendar-aligned by SEC):
  CY2024        — full calendar year 2024 (duration concepts)
  CY2024Q1      — calendar Q1 2024 (3-month duration)
  CY2024Q1I     — calendar Q1 2024 instantaneous (point-in-time, balance sheet)

Off-fiscal-year companies (NVDA Jan, AAPL Sep) appear under whichever
calendar period their value's `end` date falls in. Each FrameEntry carries
the actual `end` date so callers can disambiguate; see
`docs/architecture/DATA_LAYER.md` for empirical NVDA findings.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from typing import Any

from data.cache.manager import CacheManager

logger = logging.getLogger(__name__)


_BASE_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json"
_DEFAULT_CACHE_TTL = 24 * 3600   # 24h — frames change only when new filings land


@dataclass
class FrameEntry:
    """One company's value for a (concept, period) pair from SEC frames."""
    cik: int
    entity_name: str
    val: float
    end: date                 # calendar end date — canonical time anchor
    accn: str                 # accession number of the filing this came from

    @property
    def end_calendar_quarter(self) -> str:
        """Return 'YYYY[Q1-Q4]' for the calendar quarter containing `end`."""
        q = (self.end.month - 1) // 3 + 1
        return f"{self.end.year}Q{q}"


# ── Public API ───────────────────────────────────────────────────────────


def fetch_frame(
    concept: str,
    period: str,
    unit: str = "USD",
    identity: str | None = None,
    use_cache: bool = True,
) -> dict[int, FrameEntry]:
    """
    Single GET to SEC's frames endpoint for one (concept, period, unit).
    Returns {cik: FrameEntry} for every filer that reported a value.

    Cached 24h via CacheManager. Empty dict on 404 / network error.
    """
    cache = CacheManager() if use_cache else None
    cache_key = f"frames:{concept}:{period}:{unit}"

    payload = cache.get(cache_key) if cache else None
    if payload is None:
        payload = _fetch_remote(concept, period, unit, identity)
        if payload is not None and cache is not None:
            cache.set(cache_key, payload, ttl=_DEFAULT_CACHE_TTL)

    if not payload:
        return {}
    return _parse_payload(payload)


def build_frames_universe(
    concepts_periods: list[tuple[str, str, str]],
    identity: str | None = None,
    use_cache: bool = True,
) -> dict[int, dict[str, FrameEntry]]:
    """
    Synchronous version. Fetches each (concept, period, unit) and merges into
    a {cik: {f"{concept}@{period}": FrameEntry}} dict.

    Use `build_frames_universe_async` from async contexts to parallelise.
    """
    out: dict[int, dict[str, FrameEntry]] = {}
    for concept, period, unit in concepts_periods:
        frame = fetch_frame(concept, period, unit, identity, use_cache=use_cache)
        key = f"{concept}@{period}"
        for cik, entry in frame.items():
            out.setdefault(cik, {})[key] = entry
    return out


async def build_frames_universe_async(
    concepts_periods: list[tuple[str, str, str]],
    identity: str | None = None,
    max_concurrency: int = 5,
    use_cache: bool = True,
) -> dict[int, dict[str, FrameEntry]]:
    """
    Parallel variant with semaphore (default 5 — SEC's fair-use is 10 req/sec).
    Returns the same shape as `build_frames_universe`.
    """
    sem = asyncio.Semaphore(max_concurrency)
    loop = asyncio.get_event_loop()

    async def _one(c: str, p: str, u: str) -> tuple[str, str, dict[int, FrameEntry]]:
        async with sem:
            frame = await loop.run_in_executor(
                None, partial(fetch_frame, c, p, u, identity, use_cache),
            )
            return c, p, frame

    results = await asyncio.gather(
        *[_one(c, p, u) for c, p, u in concepts_periods]
    )

    out: dict[int, dict[str, FrameEntry]] = {}
    for concept, period, frame in results:
        key = f"{concept}@{period}"
        for cik, entry in frame.items():
            out.setdefault(cik, {})[key] = entry
    return out


# ── Internals ────────────────────────────────────────────────────────────


def _fetch_remote(
    concept: str, period: str, unit: str, identity: str | None,
) -> dict[str, Any] | None:
    """Single HTTP GET. Returns parsed JSON or None on error/404."""
    from data.api._retry import sec_get_with_retry
    url = _BASE_URL.format(concept=concept, unit=unit, period=period)
    headers = {
        "User-Agent": identity or _resolve_identity(),
        "Accept-Encoding": "gzip",
        "Host": "data.sec.gov",
    }
    resp = sec_get_with_retry(
        url, headers=headers, timeout=30.0,
        label=f"sec_frames:{concept}/{period}",
    )
    if resp is None:
        return None
    if resp.status_code == 404:
        logger.debug("frames 404: %s/%s (no data)", concept, period)
        return None
    if resp.status_code != 200:
        logger.warning(
            "frames fetch failed %s/%s: status=%d",
            concept, period, resp.status_code,
        )
        return None
    try:
        return resp.json()
    except (ValueError, KeyError) as exc:
        logger.warning("frames JSON parse failed %s/%s: %s", concept, period, exc)
        return None


def _parse_payload(payload: dict[str, Any]) -> dict[int, FrameEntry]:
    """Convert SEC frames JSON to {cik: FrameEntry}. Skip malformed entries."""
    out: dict[int, FrameEntry] = {}
    for entry in payload.get("data", []):
        try:
            cik_raw = entry.get("cik")
            val_raw = entry.get("val")
            end_raw = entry.get("end")
            if cik_raw is None or val_raw is None or end_raw is None:
                continue
            cik = int(cik_raw)
            val = float(val_raw)
            if val != val:    # NaN
                continue
            end = _parse_iso(end_raw)
            if end is None:
                continue
            out[cik] = FrameEntry(
                cik=cik,
                entity_name=str(entry.get("entityName") or ""),
                val=val,
                end=end,
                accn=str(entry.get("accn") or ""),
            )
        except (TypeError, ValueError):
            continue
    return out


def _parse_iso(s: Any) -> date | None:
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _resolve_identity() -> str:
    from config.settings import require_edgar_identity
    return require_edgar_identity()


# ── Period helpers ───────────────────────────────────────────────────────


def latest_complete_calendar_year(today: date | None = None) -> int:
    """
    Most recent calendar year for which we EXPECT 10-K filings to be largely
    in. Rule: today must be ≥90 days into the new year; else use prev_year-1
    (the most recent year for which filings should be complete).

    Examples:
      today=2026-05-03 → CY2025 (5 months past Jan 1 → CY2025 10-Ks in)
      today=2026-02-15 → CY2024 (only 6 weeks past Jan 1)
      today=2026-01-15 → CY2024 (2 weeks past Jan 1)
    """
    today = today or date.today()
    days_into_year = (today - date(today.year, 1, 1)).days
    if days_into_year >= 90:
        return today.year - 1
    return today.year - 2
