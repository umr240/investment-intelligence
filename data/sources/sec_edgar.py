"""SecEdgarSource — Tier-1A adapter wrapping the existing EDGAR path (ADR-039).

Chesterton's Fence: this adapter WRAPS ``data.edgar_fetcher`` and the existing
``data.pipeline`` gating helpers — it does NOT reimplement them. The SEC fetch,
its accession-level Tier-0 cache, the year-coverage gate, and fiscal-year-end
resolution all run exactly as they did inline in ``refresh_ticker`` before
ADR-039. The only change is WHERE that logic lives (behind the port), not WHAT
it does. The behavioural contract is pinned by the US-dive byte-diff test
(ADR-039 §6 acceptance #1).
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Any

from data.sources.base import (
    _FOREIGN_SUFFIXES,
    TAG_SEC,
    TIER_SEC_XBRL,
    FundamentalsResult,
    _suffix,
    register,
)

if TYPE_CHECKING:
    from data.models.schema import Company

logger = logging.getLogger(__name__)


class SecEdgarSource:
    name = TAG_SEC
    tier = TIER_SEC_XBRL
    available = True

    def supports(self, ticker: str, company: Company | None) -> bool:
        # US tickers — anything that is NOT a known foreign venue suffix
        # (so US class-share dotted tickers like BRK.B stay here). A Canadian
        # filer must never resolve here even if a stray CIK was cached.
        return _suffix(ticker) not in _FOREIGN_SUFFIXES

    async def fetch(
        self, ticker: str, requirement: Any, *, force_refresh: bool = False
    ) -> FundamentalsResult:
        # Function-local imports: pipeline imports data.sources at call time, so
        # importing pipeline helpers at module scope would create an import cycle.
        from data.edgar_fetcher import EdgarFetchResult, fetch_edgar_fundamentals
        from data.pipeline import (
            CoverageDecision,
            _decide_companyfacts_fetch,
            _load_known_accessions,
            _persist_filer_metadata,
            _resolve_filer_metadata,
        )

        loop = asyncio.get_event_loop()

        # ── Tier-0 accession cache (skip already-parsed filings) ──
        known = frozenset() if force_refresh else _load_known_accessions(ticker)

        # ── Phase 0.5: resolve CIK + fiscal-year-end (persists CIK on the row) ──
        filer_meta = _resolve_filer_metadata(ticker)
        if filer_meta is not None:
            _persist_filer_metadata(ticker, filer_meta)
        fyem: int = (filer_meta or {}).get("fiscal_year_end_month") or 12

        # ── Phase 1a: year-coverage gate (DB-only, 0 network) ──
        if requirement.annual_years > 0:
            decision = _decide_companyfacts_fetch(
                ticker,
                years=requirement.annual_years,
                force_refresh=force_refresh,
                known_accessions=known,
                quarters=requirement.quarterly_count,
            )
        else:
            decision = CoverageDecision(
                fetch_fundamentals=False,
                keep_only_years=None,
                reason="requirement.annual_years=0 (framework set doesn't need fundamentals)",
            )

        if not decision.fetch_fundamentals:
            logger.info("SecEdgarSource: %s skipping companyfacts (%s)", ticker, decision.reason)
            return FundamentalsResult(ticker=ticker, source_tier=TAG_SEC, reporting_currency="USD")

        quarterly_count = max(requirement.quarterly_count, 8) if requirement.annual_years > 0 else 0
        skip_accessions: frozenset[str] = frozenset() if decision.reparse else known

        edgar_result: EdgarFetchResult = await loop.run_in_executor(
            None,
            partial(
                fetch_edgar_fundamentals,
                ticker,
                requirement.annual_years,
                quarterly_count,
                skip_accessions,
                decision.keep_only_years,
                fyem,
                bypass_cache=force_refresh,
            ),
        )

        gaps = list(edgar_result.gaps)
        # Cold-fetch-returned-nothing warning — emitted here (not in
        # refresh_ticker) so it never fires on a warm-cache skip. Order matches
        # the pre-ADR-039 inline behaviour (after the fetcher's own gaps).
        if not edgar_result.financials and decision.cold:
            gaps.append(f"{ticker}: no EDGAR fundamentals — check ticker spelling")

        return FundamentalsResult(
            ticker=ticker,
            financials=edgar_result.financials,
            gaps=gaps,
            source_tier=TAG_SEC,
            reporting_currency="USD",
            reparsed=decision.reparse,
        )


register(SecEdgarSource())
