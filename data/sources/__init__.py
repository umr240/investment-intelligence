"""data/sources/ — pluggable fundamentals-source layer (ADR-039).

The ``FundamentalsSource`` port is the hexagonal boundary between the data
pipeline and the external systems that supply per-period fundamentals
(SEC EDGAR, SEDAR+, yfinance). ``refresh_ticker`` depends on this abstraction
via ``resolve_source()``; it never imports a concrete fetcher.

Adding a new jurisdiction = one new adapter module + one ``register()`` call.
Zero edits to refresh_ticker / frameworks / overlays / CLI (Open/Closed).

Importing this package registers all built-in adapters as a side effect, so
``resolve_source`` can find them.
"""
from __future__ import annotations

# Side-effect imports: each module calls register() at import time.
from data.sources import esef, sec_edgar, sedar_plus, yfinance_fund  # noqa: E402,F401
from data.sources.base import (
    FIDELITY_FILING_GRADE,
    FIDELITY_NORMALISED,
    FundamentalsResult,
    FundamentalsSource,
    fidelity_of,
    get_source,
    register,
    resolve_source,
)
from data.sources.jurisdiction import (
    Jurisdiction,
    all_jurisdictions,
    jurisdiction_for,
)

__all__ = [
    "FundamentalsResult",
    "FundamentalsSource",
    "resolve_source",
    "get_source",
    "register",
    "fidelity_of",
    "FIDELITY_FILING_GRADE",
    "FIDELITY_NORMALISED",
    "Jurisdiction",
    "jurisdiction_for",
    "all_jurisdictions",
]
