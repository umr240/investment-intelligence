"""
Universe enumeration — region-pluggable list of investable tickers.

A `UniverseProvider` returns the full universe for a region; the screener
applies cap/sector filters in-memory. Today only `SecUsUniverseProvider` is
registered. Non-US providers will plug in here later without touching the
screener.
"""
from data.universe.base import (
    PROVIDERS,
    UniverseProvider,
    UniverseTicker,
    get_provider,
    register_provider,
)
from data.universe.sec_us import SecUsUniverseProvider

# Auto-register the US provider on import.
register_provider("us", SecUsUniverseProvider())

__all__ = [
    "UniverseProvider",
    "UniverseTicker",
    "PROVIDERS",
    "get_provider",
    "register_provider",
    "SecUsUniverseProvider",
]
