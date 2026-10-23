"""
UniverseProvider Protocol + UniverseTicker dataclass.

A provider is region-scoped and returns ALL tickers in its region; the screener
applies cap / sector / exchange filters in-memory afterwards. Providers are
expected to cache their universe at the source level (e.g. SEC's
`company_tickers_exchange.json` is small enough to refresh weekly).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class UniverseTicker:
    """One row in a region's investable universe.

    `cik` is set for SEC-filer providers; None elsewhere. `market_cap`,
    `sector`, `industry` may be None at this stage — Tier 2 enriches via
    yfinance metadata. The provider's job is to enumerate, not enrich.
    """
    ticker: str
    name: str
    exchange: str
    cik: str | None = None
    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None
    source: str = "unknown"           # 'sec_us' | future: 'lse' | 'tsx' | etc.


class UniverseProvider(Protocol):
    """Region-pluggable universe enumeration."""

    region_code: str
    """e.g. 'us', 'lse', 'tsx'."""

    def fetch(self) -> list[UniverseTicker]:
        """
        Return the full investable universe for this region.

        Should be cheap to call repeatedly (provider implements its own cache).
        Filtering by cap / sector / exchange happens AFTER this returns.
        """
        ...


PROVIDERS: dict[str, UniverseProvider] = {}


def register_provider(region_code: str, provider: UniverseProvider) -> None:
    """Register a provider under a region code. Overwrites silently."""
    PROVIDERS[region_code] = provider


def get_provider(region_code: str) -> UniverseProvider:
    """Look up a provider by region code. Raises NotImplementedError if missing."""
    p = PROVIDERS.get(region_code)
    if p is None:
        raise NotImplementedError(
            f"Region '{region_code}' has no UniverseProvider registered. "
            f"Known regions: {sorted(PROVIDERS.keys())}"
        )
    return p
