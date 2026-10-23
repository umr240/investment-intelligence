"""Canonical source tags + tier weights — ADR-033 §1.1 source hierarchy.

Every API/SEC-sourced column on `Company` is paired with a `<field>_source`
column that records WHERE the value originated. The tag is one of the
constants below; `tier_weight()` maps it to the trust multiplier used by
`screener/tasks/composite.py:compute_data_completeness`.

Phase 1 of the SEC-first migration codified in API_FIELD_AUDIT.md §F.1.

The canonical hierarchy (ADR-033 §1.1):

    Tier 1A — SEC raw endpoints                              weight 1.00
    Tier 1B — edgartools typed surfaces                      weight 1.00
    Tier 2  — Self-computed from SEC primitives              weight 1.00
    Tier 3a — Polygon (paid, decent quality)                 weight 0.95
    Tier 3b — yfinance (free, scraped Yahoo)                 weight 0.85
    Tier 3c — FMP free tier                                  weight 0.80
    Tier 4  — LLM extraction (external_signals only)         weight 0.50
    Manual  — User-supplied                                  weight 0.50

Per ADR-031 §4.1: LLM-derived canonical fields do NOT currently flow into
`WAREHOUSE_COLUMNS` — `external_signals` is isolated from the deterministic
data path. The `LLM` tier exists here for future-proofing only.
"""
from __future__ import annotations

from typing import Final


# ── Tier 1A: SEC raw endpoints ────────────────────────────────────────────
SEC_XBRL: Final = "sec_xbrl"                 # companyfacts.json / companyconcept
SEC_DEI: Final = "sec_dei"                   # DEI namespace (EntityPublicFloat, ReportingCurrencyISOCode)
SEC_SUBMISSIONS: Final = "sec_submissions"   # submissions.json (filer metadata, filing list)
SEC_DEF14A: Final = "sec_def14a"             # DEF 14A proxy parsing (CEO comp, equity %, tenure)
SEC_SC13D: Final = "sec_sc13d"               # SC 13D/A Item 5 Row 13 beneficial ownership
SEC_FORM4: Final = "sec_form4"               # Form 3/4/5 Section 16 insider filings
SEC_FRAMES: Final = "sec_frames"             # XBRL frames endpoint (cross-sectional)
SEC_TEXT: Final = "sec_text"                 # 10-K/10-Q HTML regex / BeautifulSoup
SEC_6K_MIC: Final = "sec_6k_mic"             # Canadian FPI 6-K Management Information Circular

# ── Tier 1B: edgartools typed surfaces ────────────────────────────────────
EDGARTOOLS: Final = "edgartools"             # Company.* attributes (sic, is_foreign, get_ttm, etc.)

# ── Tier 2: Self-computed from SEC primitives ─────────────────────────────
SELF_COMPUTED: Final = "self_computed"       # ROIC, ratios, regressions

# ── Tier 3: External APIs ─────────────────────────────────────────────────
POLYGON: Final = "polygon"                   # Polygon.io (paid)
YFINANCE: Final = "yfinance"                 # yfinance.info / .history()
FMP: Final = "fmp"                           # Financial Modeling Prep (free tier)

# ── Tier 4: LLM + manual ──────────────────────────────────────────────────
LLM: Final = "llm"                           # external_signals only (ADR-031 §4.1)
MANUAL: Final = "manual"                     # user-supplied

# Pre-Phase-1 legacy tag for sector/industry classification from SEC SIC.
# Two spellings exist in historical writes: `sec_sic` (data/pipeline.py and a
# since-archived backfill) and `sec-sic` (ipo_date.py). Both
# mean the same thing — SEC SIC-derived industry classification (Tier 1B).
# Kept as constants here so tier_weight() resolves both without a NULL
# fallback; new code should prefer EDGARTOOLS or SEC_SUBMISSIONS for clarity.
SEC_SIC: Final = "sec_sic"
SEC_SIC_DASH: Final = "sec-sic"           # legacy spelling
POLYGON_SIC: Final = "polygon-sic"        # sector-source from Polygon SIC mapping


# Set of all valid tags — for validation guards.
ALL_TAGS: Final[frozenset[str]] = frozenset({
    SEC_XBRL, SEC_DEI, SEC_SUBMISSIONS, SEC_DEF14A, SEC_SC13D,
    SEC_FORM4, SEC_FRAMES, SEC_TEXT, SEC_6K_MIC,
    EDGARTOOLS, SEC_SIC, SEC_SIC_DASH, SELF_COMPUTED,
    POLYGON, POLYGON_SIC, YFINANCE, FMP,
    LLM, MANUAL,
})

# Tier weights — matches ADR-033 §1.1 + composite.py FIELD_DEFAULT_TIER.
_TIER_WEIGHTS: Final[dict[str, float]] = {
    # Tier 1A — verifiable GAAP source
    SEC_XBRL: 1.00,
    SEC_DEI: 1.00,
    SEC_SUBMISSIONS: 1.00,
    SEC_DEF14A: 1.00,
    SEC_SC13D: 1.00,
    SEC_FORM4: 1.00,
    SEC_FRAMES: 1.00,
    SEC_TEXT: 1.00,
    SEC_6K_MIC: 1.00,
    # Tier 1B — typed wrapper over SEC
    EDGARTOOLS: 1.00,
    SEC_SIC: 1.00,             # legacy `sector_source='sec_sic'`
    SEC_SIC_DASH: 1.00,        # legacy `sector_source='sec-sic'`
    # Tier 2 — self-computed from SEC primitives
    SELF_COMPUTED: 1.00,
    # Tier 3 — external APIs
    POLYGON: 0.95,
    POLYGON_SIC: 0.95,         # Polygon-derived SIC classification
    YFINANCE: 0.85,
    FMP: 0.80,
    # Tier 4 — LLM + manual
    LLM: 0.50,
    MANUAL: 0.50,
}


# Backward-compat: when a column's source is NULL (pre-migration data),
# treat as 'unknown' with a conservative weight slightly below yfinance.
# This avoids penalising historical rows but signals migration is needed.
_NULL_WEIGHT: Final[float] = 0.80


def tier_weight(source_tag: str | None) -> float:
    """Map a `<field>_source` value to its tier weight.

    Args:
        source_tag: One of the constants above, or None.

    Returns:
        Float in [0.50, 1.00]. NULL → 0.80 ("unknown / pre-migration").
        Unrecognised tags also fall through to 0.80 with no error — better
        to degrade gracefully than crash a screener mid-run on a typo.
    """
    if source_tag is None:
        return _NULL_WEIGHT
    return _TIER_WEIGHTS.get(source_tag, _NULL_WEIGHT)


def is_sec_origin(source_tag: str | None) -> bool:
    """True when the source is SEC-rooted (Tier 1A, 1B, or 2).

    Useful for audit queries: "what fraction of NVDA's columns are SEC-
    backed vs API-backed?"
    """
    if source_tag is None:
        return False
    return source_tag in {
        SEC_XBRL, SEC_DEI, SEC_SUBMISSIONS, SEC_DEF14A, SEC_SC13D,
        SEC_FORM4, SEC_FRAMES, SEC_TEXT, SEC_6K_MIC,
        EDGARTOOLS, SEC_SIC, SEC_SIC_DASH, SELF_COMPUTED,
    }


__all__ = [
    # Tier 1A
    "SEC_XBRL", "SEC_DEI", "SEC_SUBMISSIONS", "SEC_DEF14A", "SEC_SC13D",
    "SEC_FORM4", "SEC_FRAMES", "SEC_TEXT", "SEC_6K_MIC",
    # Tier 1B
    "EDGARTOOLS", "SEC_SIC", "SEC_SIC_DASH",
    # Tier 2
    "SELF_COMPUTED",
    # Tier 3
    "POLYGON", "POLYGON_SIC", "YFINANCE", "FMP",
    # Tier 4
    "LLM", "MANUAL",
    # Helpers
    "ALL_TAGS", "tier_weight", "is_sec_origin",
]
