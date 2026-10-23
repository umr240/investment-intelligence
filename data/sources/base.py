"""FundamentalsSource port + registry + resolver (ADR-039 §2.1, §2.3).

This module is the hexagonal boundary (``mental_models/engineering/
boundaries_hexagonal.md``). It defines:

  * ``FundamentalsResult`` — the unified return type. Its ``financials`` list
    holds ``EdgarFinancialRow`` instances so the existing
    ``pipeline._persist_financials`` / ``_persist_source_log`` path consumes
    every source's output unchanged (Liskov — ``respect_the_contract``).
  * ``FundamentalsSource`` — a two-method Protocol (Interface Segregation:
    insider / proxy / 10-K-text concerns are NOT forced onto sources that
    can't provide them — they surface as ``gaps``).
  * ``register`` / ``get_source`` — the adapter registry (composition over
    inheritance — a dict of instances, not a class hierarchy).
  * ``resolve_source`` — the SINGLE place source-selection lives
    (``single_source_of_truth``).

No I/O happens in this module. Adapters do I/O; this module only routes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from data.models.schema import Company

logger = logging.getLogger(__name__)

# ── ADR-022 source tiers (written to Financial.{field}_source semantics) ──
TIER_SEC_XBRL = "sec_xbrl"        # Tier 1A — audited regulator XBRL
TIER_SEDAR_IXBRL = "sedar_ixbrl"  # Tier 1B — Canadian regulator iXBRL
TIER_ESEF_IXBRL = "esef_ixbrl"    # Tier 1B — EU/EEA regulator iXBRL (ESEF)
TIER_YFINANCE = "yfinance"        # Tier 3  — third-party scraped

# ── Company.data_source_tier tags ──
TAG_SEC = "sec_edgar"
TAG_SEDAR = "sedar_plus"
TAG_ESEF = "esef"
TAG_YFINANCE = "yfinance_only"

# Fidelity ordering — lets callers compare sources rather than hard-coding
# names. Screening (Tier-0 triage) is content with NORMALISED; a thesis-grade
# number should come from FILING_GRADE. Higher rank = higher fidelity.
FIDELITY_RANK: dict[str, int] = {
    TIER_SEC_XBRL: 3,      # filing-grade, audited, ~10yr
    TIER_ESEF_IXBRL: 3,    # filing-grade, audited, validation-scored
    TIER_SEDAR_IXBRL: 3,   # filing-grade (when Phase C lands)
    TIER_YFINANCE: 1,      # normalised third-party — adequate for triage only
}
FIDELITY_FILING_GRADE = 3
FIDELITY_NORMALISED = 1


def fidelity_of(source: FundamentalsSource | str) -> int:
    """Fidelity rank of a source (by tier). Unknown tiers rank lowest."""
    tier = source if isinstance(source, str) else source.tier
    return FIDELITY_RANK.get(tier, 0)


# ── Suffix sets (DERIVED — the jurisdiction table is the source of truth) ──
# Kept as module constants because `sec_edgar` / `sedar_plus` import them, but
# they are now views over data/sources/jurisdiction.py rather than a second
# place routing knowledge lives (single_source_of_truth).
def _derive_suffix_sets() -> tuple[frozenset[str], frozenset[str]]:
    from data.sources.jurisdiction import REGION_NORTH_AMERICA, all_jurisdictions
    canadian = frozenset(
        j.suffix for j in all_jurisdictions()
        if j.country == "CA" and j.region == REGION_NORTH_AMERICA and j.suffix
    )
    foreign = frozenset(j.suffix for j in all_jurisdictions() if j.suffix)
    return canadian, foreign


_CANADIAN_SUFFIXES, _FOREIGN_SUFFIXES = _derive_suffix_sets()


@dataclass
class FundamentalsResult:
    """Unified fetch result. Superset-compatible with ``EdgarFetchResult``.

    ``financials`` is ``list[EdgarFinancialRow]`` regardless of source, so the
    persistence layer never branches on origin. Provenance travels via
    ``source_tier`` (Company tag) and each row's ``.source`` field (ADR-022).
    """

    ticker: str
    financials: list[Any] = field(default_factory=list)  # list[EdgarFinancialRow]
    gaps: list[str] = field(default_factory=list)
    source_tier: str = TAG_SEC
    reporting_currency: str = "USD"
    fx_rate_to_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    reparsed: bool = False  # every filing was read again (force or parser upgrade)


@runtime_checkable
class FundamentalsSource(Protocol):
    """Port: one adapter per external fundamentals system.

    ``available`` lets a scaffolded adapter (e.g. SEDAR+ Phase C) be registered
    and route-visible while declaring it cannot yet serve data — the resolver
    skips unavailable sources rather than routing into a stub that returns gaps.
    """

    name: str          # registry key: 'sec_edgar' | 'sedar_plus' | 'yfinance'
    tier: str          # one of TIER_* — the ADR-022 source tier
    available: bool    # False = registered but not yet able to fetch (scaffold)

    def supports(self, ticker: str, company: Company | None) -> bool:
        """Cheap, no-I/O predicate: can this source serve this ticker?"""
        ...

    async def fetch(
        self, ticker: str, requirement: Any, *, force_refresh: bool = False
    ) -> FundamentalsResult:
        """Fetch + map to EdgarFinancialRow. Fail-soft: missing data becomes a
        ``gaps`` entry, never an exception and never a fabricated value."""
        ...


# ── Registry ──────────────────────────────────────────────────────────────
_REGISTRY: dict[str, FundamentalsSource] = {}


def register(source: FundamentalsSource) -> FundamentalsSource:
    """Register an adapter instance under its ``name``. Idempotent."""
    _REGISTRY[source.name] = source
    logger.debug("registered FundamentalsSource %r (tier=%s, available=%s)",
                 source.name, source.tier, source.available)
    return source


def get_source(name: str) -> FundamentalsSource:
    return _REGISTRY[name]


def _suffix(ticker: str) -> str:
    return ticker.rsplit(".", 1)[-1].upper() if "." in ticker else ""


def resolve_source(ticker: str, company: Company | None) -> FundamentalsSource:
    """Single source of truth for source selection + precedence (ADR-039 §2.3).

    Routing is a walk over the ticker's ``Jurisdiction.source_chain``, which is
    ordered HIGHEST FIDELITY FIRST. A candidate is taken when it is registered,
    marked ``available``, and ``supports()`` the ticker; otherwise the walk
    continues. yfinance terminates every chain, so resolution never fails.

    This replaced a hand-written if-ladder. The behavioural contract is
    unchanged for every ticker that existed before:

      * bare ticker / US class-share (``BRK.B``) → SEC EDGAR (Tier-1A)
      * ``.TO`` / ``.V`` / ``.CN`` / ``.NE``     → SEDAR+ if built, else yfinance
      * any other known foreign suffix           → its chain, ending at yfinance

    Anti-degradation guard: an UNRECOGNISED suffix resolves to the US
    jurisdiction (``jurisdiction_for``), so a stray suffix can never silently
    demote a US filer to Tier-3.

    Wrong-company guard: ``.TO`` never reaches SEC, so the ``VHI`` → Valhi
    collision stays impossible. Each adapter additionally refuses ambiguous
    identity resolution inside ``fetch`` (see ``esef._gleif_lookup``).
    """
    from data.sources.jurisdiction import jurisdiction_for

    for name in jurisdiction_for(ticker).source_chain:
        candidate = _REGISTRY.get(name)
        if candidate is None:
            continue                      # adapter not built yet (e.g. companies_house)
        if not candidate.available:
            continue                      # registered scaffold (e.g. sedar_plus)
        if not candidate.supports(ticker, company):
            continue
        return candidate

    # Every chain ends at yfinance; this is a belt-and-braces terminator.
    return _REGISTRY[TIER_YFINANCE]
