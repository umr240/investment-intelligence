"""SedarPlusSource — Tier-1B Canadian iXBRL adapter (ADR-039 Phase C — SCAFFOLD).

SEDAR+ (sedarplus.ca) has NO public REST API as of 2026. A real implementation
must: locate the issuer's filing index → find the latest iXBRL annual filing →
parse iXBRL into EdgarFinancialRow. Estimated 4-6 weeks, fragile to site
changes (ADR-038 §"per-jurisdiction parsers"). Per the Phased scope chosen in
ADR-039, this ships as a registered-but-UNAVAILABLE scaffold: it is visible to
the resolver (so the seam is real and tested) but ``available = False`` means
``resolve_source`` skips it and Canadian tickers fall through to the yfinance
Tier-3 bridge until Phase C lands.

When Phase C is built: implement ``fetch``, flip ``available = True``, and
Canadian tickers automatically prefer this Tier-1B source over yfinance — with
ZERO edits to refresh_ticker, frameworks, or the CLI (Open/Closed).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from data.sources.base import (
    _CANADIAN_SUFFIXES,
    TAG_SEDAR,
    TIER_SEDAR_IXBRL,
    FundamentalsResult,
    _suffix,
    register,
)

if TYPE_CHECKING:
    from data.models.schema import Company

logger = logging.getLogger(__name__)


class SedarPlusSource:
    name = TAG_SEDAR
    tier = TIER_SEDAR_IXBRL
    available = False  # Phase C not yet built — resolver skips, falls to yfinance

    def supports(self, ticker: str, company: Company | None) -> bool:
        return _suffix(ticker) in _CANADIAN_SUFFIXES

    async def fetch(
        self, ticker: str, requirement: Any, *, force_refresh: bool = False
    ) -> FundamentalsResult:
        # Defensive: resolve_source skips unavailable sources, so this should
        # never be reached in normal flow. If a caller invokes it directly, it
        # fails SOFT with an explicit gap — never a silent zero (fail_fast +
        # CLAUDE.md "missing data → data_gaps entry, never a hallucinated value").
        return FundamentalsResult(
            ticker=ticker,
            source_tier=TAG_SEDAR,
            reporting_currency="CAD",
            gaps=[
                f"{ticker}: SEDAR+ Tier-1B iXBRL parser not yet implemented "
                f"(ADR-039 Phase C). Canadian fundamentals currently sourced "
                f"via yfinance Tier-3."
            ],
        )


register(SedarPlusSource())
