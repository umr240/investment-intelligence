"""Composite-score + data-completeness task — Phase 4b (ADR-017) + 5i (ADR-021).

In-memory: combines the warehouse columns populated by upstream tasks
(``MetadataYFTask``, ``FundamentalsTask``, ``IPODateTask``,
``ExclusionClassifyTask``) into a single ranking score.

Score formula (per DEC-15 / ADR-017 §13, augmented per ADR-021 §4.4 / DEC-28):

    economic_roic = max(roic, pt_adjusted_roic)
                    when pt_adjusted_roic > roic + 0.03
                    else roic

    composite = 1.5 * normalize(economic_roic, scale=0.5)
              + 1.0 * normalize(fcf_margin, scale=0.4)
              + 0.5 * (1 - min(1, debt_to_equity))     # inverse: lower=better
              + 0.5 * normalize(revenue_growth, scale=0.5)

ADR-021 §4.4: when Peters-Taylor adjusted ROIC materially exceeds GAAP
ROIC (≥3pp), use the higher value. This rescues intangible-heavy
candidates (R&D-heavy SaaS / biotech / semis) without inflating mature
businesses where GAAP ≈ economic ROIC. The 3pp gate is the "materially
exceeds" threshold — below that, the GAAP figure is preferred for
conservatism (Chesterton's Fence: GAAP exists for a reason).

Each component is clipped to [-1, 1] before being weighted; missing
components contribute 0 (neutral). Score range is roughly [-1.5, 3.5].

``data_completeness`` is the fraction of the canonical warehouse columns
listed in ``WAREHOUSE_COLUMNS`` that are non-null on a given Company row.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.models.schema import Company
from screener.tasks.base import FilterResult

if TYPE_CHECKING:
    from data.rate_limit import TokenBucket


# Columns that count toward data_completeness. composite_score itself is
# excluded (it's the output, not an input). Exclusion-policy verdicts are not
# data and never count (they live in exclusion_verdicts).
WAREHOUSE_COLUMNS: tuple[str, ...] = (
    "market_cap_usd",
    "sector",
    "industry",
    "ipo_date",
    "roic",
    "fcf_margin",
    "debt_to_equity",
    "revenue_growth",
)

# Fields where the API source IS the canonical source — SEC structurally
# cannot provide them (market prices aren't in EDGAR filings). For these,
# yfinance / polygon get full Tier-1 trust weight (1.00) instead of the
# default Tier-3 discount (0.85 / 0.95). Penalizing market_cap_usd for
# being from yfinance is mis-signal: it implies a better source exists
# when none does.
_CANONICAL_API_FIELDS: frozenset[str] = frozenset({
    "market_cap_usd",   # SEC has no market prices; yfinance is canonical
    "shares_float",     # float = outstanding − insider; ultimately needs price
    "beta",             # 5yr regression — now self_computed but yfinance acceptable as fallback
})


class CompositeScoreTask:
    name = "composite_score"
    source = "in-memory"
    refresh_interval = timedelta(days=1)
    concurrency_override = None

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            # Need at least one of the inputs to compute anything meaningful
            .where(
                or_(
                    Company.roic.isnot(None),
                    Company.fcf_margin.isnot(None),
                    Company.debt_to_equity.isnot(None),
                    Company.revenue_growth.isnot(None),
                )
            )
            .where(
                or_(
                    Company.composite_score_fetched_at.is_(None),
                    Company.composite_score_fetched_at < cutoff,
                )
            )
        )
        return list(db.execute(stmt).scalars().all())

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        results: list[FilterResult] = []
        for c in companies:
            score = compute_composite(
                roic=c.roic,
                pt_adjusted_roic=c.pt_adjusted_roic,
                fcf_margin=c.fcf_margin,
                debt_to_equity=c.debt_to_equity,
                revenue_growth=c.revenue_growth,
            )
            completeness = compute_data_completeness(c)
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "composite_score": score,
                    "data_completeness": completeness,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            company.composite_score = r.values["composite_score"]
            company.data_completeness = r.values["data_completeness"]
            company.composite_score_fetched_at = now

        db.commit()


_PT_MATERIAL_GAP = 0.03   # 3 percentage points; ADR-021 §4.4 / DEC-28 threshold


def _economic_roic(
    roic: float | None,
    pt_adjusted_roic: float | None,
) -> float | None:
    """Pick the better of GAAP ROIC and Peters-Taylor ROIC when PT
    materially exceeds GAAP. ADR-021 §4.4 / DEC-28.

    Rules:
      • Both None → None
      • Only one populated → use it
      • Both populated AND pt_roic > roic + 3pp → use pt_roic
      • Otherwise → use roic (default conservative)
    """
    if pt_adjusted_roic is None:
        return roic
    if roic is None:
        return pt_adjusted_roic
    if pt_adjusted_roic > roic + _PT_MATERIAL_GAP:
        return pt_adjusted_roic
    return roic


def compute_composite(
    *,
    roic: float | None,
    fcf_margin: float | None,
    debt_to_equity: float | None,
    revenue_growth: float | None,
    pt_adjusted_roic: float | None = None,
) -> float:
    """Composite quality score from warehouse columns. Higher = better.

    ADR-021 §4.4 / DEC-28 integration: ROIC component uses Peters-Taylor
    adjusted ROIC when it materially exceeds GAAP ROIC (≥3pp). Otherwise
    GAAP ROIC is preferred for conservatism. Other components unchanged.
    """
    score = 0.0
    eff_roic = _economic_roic(roic, pt_adjusted_roic)
    if eff_roic is not None:
        score += 1.5 * max(-1.0, min(1.0, eff_roic / 0.5))
    if fcf_margin is not None:
        score += 1.0 * max(-1.0, min(1.0, fcf_margin / 0.4))
    if debt_to_equity is not None:
        # Lower D/E is better; map [0..1] D/E to [1..0] contribution.
        # D/E > 1.0 caps at zero; negative D/E (rare; equity-deficient) caps at 1.
        capped = max(0.0, min(1.0, debt_to_equity))
        score += 0.5 * (1.0 - capped)
    if revenue_growth is not None:
        score += 0.5 * max(-1.0, min(1.0, revenue_growth / 0.5))
    return score


def compute_data_completeness(company: Company) -> float:
    """Tier-weighted data completeness score, per ADR-033 §1.1 source
    hierarchy and API_FIELD_AUDIT.md §F (Phase 1 source-tag plumbing).

    Phase 1 (2026-05-16): Each warehouse column has a paired `<field>_source`
    column populated at every write site. This function reads the actual
    source per row instead of the legacy `FIELD_DEFAULT_TIER` static guess —
    so migrating a field from yfinance to SEC (Phase 2) is immediately
    visible in the completeness score.

    Weight resolution per field:
      1. If `<field>_source` column exists and is non-NULL → use its tier
         weight from `config.source_tags.tier_weight()`.
      2. If `<field>_source` is NULL → fall back to a conservative default
         (0.80, slightly below yfinance) signalling "pre-migration row,
         provenance unknown."
      3. The `industry` field reads `sector_source` (legacy unified column).

    Formula: score = Σ (weight × present?) / N
    where N = number of warehouse columns and weight ∈ [0.50, 1.00].

    Score range: [0, 1]. A fully-SEC row scores 1.00; a fully-yfinance
    row scores ≈0.85 (Tier 3b avg); a row with N/2 fields missing scores
    ≈ avg_present_weight / 2. This makes the SEC-over-yfinance trust
    upgrade *measurably visible* (per API_FIELD_AUDIT.md §H invariant 1).
    Compare to the legacy `Σ weight present / Σ weight` formula, which
    self-normalised: a fully-yfinance row scored 1.0 (same as fully SEC),
    eliminating any incentive for the Phase 2 migration to surface in
    the score.
    """
    from config.source_tags import tier_weight, YFINANCE, POLYGON

    # Map warehouse column → corresponding `_source` column name.
    # `industry` is a special case (legacy `sector_source` covers it).
    SOURCE_COL: dict[str, str | None] = {
        "market_cap_usd": "market_cap_usd_source",
        "sector": "sector_source",
        "industry": "sector_source",          # shared with sector (legacy)
        "ipo_date": "ipo_date_source",
        "roic": "roic_source",
        "fcf_margin": "fcf_margin_source",
        "debt_to_equity": "debt_to_equity_source",
        "revenue_growth": "revenue_growth_source",
    }

    n = len(WAREHOUSE_COLUMNS)
    if n == 0:
        return 0.0

    trust_sum = 0.0
    for col in WAREHOUSE_COLUMNS:
        source_col = SOURCE_COL.get(col)
        source_value: str | None = (
            getattr(company, source_col, None) if source_col else None
        )

        # Canonical-API override (2026-05-17). For fields where SEC
        # structurally cannot supply data (prices, market_cap, etc.), the
        # API IS the canonical source — full Tier-1 weight, not the
        # default Tier-3 discount. Penalizing yfinance market_cap implies
        # a better source exists when none does — mis-signal.
        if col in _CANONICAL_API_FIELDS and source_value in (YFINANCE, POLYGON):
            weight = 1.00
        else:
            # Legacy: `sector_source='sec_sic'` shorthand maps to 1.00.
            # All other tags resolved via tier_weight (which handles
            # canonical sec_*/edgartools/self_computed/etc).
            weight = tier_weight(source_value)

        if getattr(company, col, None) is not None:
            trust_sum += weight

    return trust_sum / n


__all__ = [
    "CompositeScoreTask",
    "compute_composite",
    "compute_data_completeness",
    "WAREHOUSE_COLUMNS",
]
