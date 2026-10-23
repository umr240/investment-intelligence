"""
All quantitative thresholds, weights, and mode definitions.
Single source of truth — sourced from PROJECT_SPEC.md.
"""
from __future__ import annotations

from typing import Final

# ── Framework modes ───────────────────────────────────────────────────────
VALID_MODES: Final = {"A", "B", "C", "D"}

# ── Universe filters ──────────────────────────────────────────────────────
MIN_MARKET_CAP_DEFAULT: Final = 50_000_000          # $50M
MAX_MARKET_CAP_DEFAULT: Final = 10_000_000_000      # $10B
LIQUIDITY_FLOOR: Final = 300_000_000               # $300M — F2 requirement

# ── Screener concurrency + retention (see docs/architecture/SCREENER_PIPELINE.md §2, §4) ──
# Per-stage semaphore caps. yfinance is rate-limit-tolerant; SEC enforces 10 req/sec.
MAX_YF_CONCURRENCY: Final = 1    # Yahoo's anti-abuse layer bans us at higher concurrency.
                                  # Universe-wide screens take longer but actually succeed.
MAX_SEC_CONCURRENCY: Final = 5
RETENTION_DAYS_DEFAULT: Final = 30                 # screener_candidate TTL

# ── Warehouse task runner (Phase 4a, ADR-017 §4) ─────────────────────────
TASK_CHUNK_SIZE: Final = 50                  # tickers per fetch_chunk call
TASK_DEFAULT_CONCURRENCY: Final = 5          # parallel chunks; tasks may override
TASK_MAX_RETRIES: Final = 3                  # per-chunk attempts before failure
TASK_FAILURE_BACKOFF_BASE: Final = 2.0       # seconds; doubles each retry
TASK_FAILURE_BACKOFF_CAP: Final = 30.0       # cap on a single sleep
MAX_TASK_RETRIES_PER_CIK: Final = 5          # skip ticker after this many sequential failures

# ── Stage failure gates (Phase 5c-5, ADR-017 §14 step 5) ─────────────────
# A stage that retains less than this fraction of its input survivors
# raises a ValueError so the cron handler logs an alert. Prevents the
# legacy "Stage A produces 0 survivors silently" failure mode.
STAGE_MIN_SURVIVOR_RATIO: Final[float] = 0.10        # 10% — at least 1 in 10 must clear
# Below this absolute count, a stage fails regardless of ratio (catches the
# small-universe case where 1/10 still rounds to 0%).
STAGE_MIN_ABSOLUTE_SURVIVORS: Final[int] = 1

# ── F1 — Pre-Discovery Alpha ──────────────────────────────────────────────
F1_INSIDER_CLUSTER_MIN: Final = 3      # open-market buys in 90 days
F1_MAX_ANALYST_COUNT: Final = 5        # ≤5 = neglect premium
F1_GP_A_PERCENTILE_MIN: Final = 60     # top 40% of sector

# ── F2 — Momentum ─────────────────────────────────────────────────────────
F2_52WK_HIGH_PROXIMITY: Final = 0.10   # within 10% of 52wk high
F2_EV_REV_Z_CHEAP: Final = -1.0        # historically cheap z-score
F2_PB_Z_CHEAP: Final = -1.0

# ── F3 — Innovation Compounder ────────────────────────────────────────────
F3_GM_EXPANSION_MIN: Final = 0.02      # ≥200bps annual gross margin expansion
F3_RD_INTENSITY_MIN: Final = 0.15      # 15% R&D/Revenue (sweet spot floor)
F3_RD_INTENSITY_MAX: Final = 0.35      # 35% R&D/Revenue (sweet spot ceiling)

# ── F4 — Stealth Accumulation ─────────────────────────────────────────────
F4_SI_HIGH: Final = 0.08               # short interest "high" threshold
F4_SI_LOW: Final = 0.05                # short interest "low" (declining signal)
F4_HOLDER_COUNT_GROWTH: Final = 0.10   # +10% institutional holder count

# ── F5 — Growth Quality ───────────────────────────────────────────────────
F5_REVENUE_CAGR_MIN: Final = 0.10      # >10% 3yr CAGR
F5_FCF_MARGIN_MIN: Final = 0.20        # >20% FCF margin
F5_ROIC_MIN: Final = 0.15              # >15% ROIC
F5_DEBT_EBITDA_MAX: Final = 2.0        # <2.0x Debt/EBITDA
F5_BUYBACK_YIELD_MIN: Final = 0.02     # 2% buyback yield floor
F5_BUYBACK_YIELD_MAX: Final = 0.05     # 5% buyback yield ceiling
F5_CEO_TENURE_MIN: Final = 5.0         # years
F5_FOUNDER_CEO_EQUITY_MIN: Final = 0.05  # >5% equity stake

# ── ICA Overlay (Peters & Taylor 2017) ───────────────────────────────────
ICA_ROIC_FAIL_THRESHOLD: Final = 0.15
ICA_RD_INTENSITY_TRIGGER: Final = 0.10
ICA_RD_DEPRECIATION_RATE: Final = 0.15    # 15%/yr knowledge capital decay
ICA_SGA_FRACTION: Final = 0.25            # 25% of SG&A → organisational capital
ICA_OC_DEPRECIATION_RATE: Final = 0.20    # 20%/yr org capital decay
ICA_OCF_TO_LOSS_RATIO: Final = 2.0        # ICA-3 trigger: OCF/|net loss| > 2x
ICA_PB_TRIGGER: Final = 4.0              # ICA-4 trigger: P/B > 4x

INNOVATION_SECTORS: Final[frozenset[str]] = frozenset({
    # Reverted to the original 5 per docs/methodology/DIAGNOSTIC_OVERLAYS.md.
    # ADR-021's earlier expansion to {software, technology} was unjustified silent
    # drift — "software" is a superset of SaaS (legacy on-prem, gaming, dev tools)
    # and "technology" is too broad (hardware, telecom, internet). ICA-2 must
    # stay precision-targeted at intangible-heavy R&D-driven sectors.
    "saas", "biotech", "semiconductors", "deep_tech", "pharma",
})

# ── BEW Overlay (Bessembinder 2018) ──────────────────────────────────────
BEW_MARKET_CAP_MAX: Final = 2_000_000_000   # <$2B at acquisition
BEW_IDIO_VOL_MIN: Final = 0.30              # >30% annualised idiosyncratic vol
BEW_RETURN_12M_TRIGGER: Final = 0.50        # >50% 12m return
BEW_TAM_REVENUE_RATIO_MIN: Final = 20.0     # TAM / revenue > 20x
BEW_F3_SCORE_MIN: Final = 7.0
BEW_F6_SCORE_MIN: Final = 7.0

BESSEMBINDER_GROWTH_SECTORS: Final[frozenset[str]] = frozenset({
    "technology", "healthcare", "consumer_discretionary", "industrials",
})

# ── Disqualification checks ───────────────────────────────────────────────
DISQ_EQUITY_ISSUE_MAX: Final = 0.05     # equity issued > 5% of market cap
DISQ_DEBT_ISSUE_MAX: Final = 0.20       # net debt issued > 20% of prior debt
DISQ_ASSET_GROWTH_DECILE: Final = 9     # top 2 deciles = disqualify

# ── Screener qualifier thresholds (by mode) ───────────────────────────────
DEEP_DIVE_THRESHOLDS: Final[dict[str, int]] = {
    "A": 20,    # out of 30
    "B": 33,    # out of 50
    "C": 47,    # out of 70
}
WATCH_THRESHOLDS: Final[dict[str, int]] = {
    "A": 16,
    "B": 27,
    "C": 38,
}

# ── Verdict thresholds (composite 0–10 scale) ─────────────────────────────
VERDICT_PRIORITY_WATCHLIST: Final = 7.0   # labels: ADR-054
VERDICT_WATCHLIST: Final = 5.0
VERDICT_MONITOR: Final = 3.0

# Minimum fraction of the mode's framework weight that must be PRESENT (not
# renormalised away as None) for the composite verdict to reach "watchlist"
# or "priority_watchlist". Below this floor the verdict is capped at "monitor" —
# protects against the TAOP-style false positive (a $12M shell that scored
# composite 8.5 because only 1 thin momentum framework ran on default
# baseline values and got 100% post-renorm weight).
MIN_FRAMEWORK_WEIGHT_COVERAGE: Final = 0.5

# ── Mode weights ──────────────────────────────────────────────────────────
WEIGHTS_B: Final[dict[str, dict[str, float]]] = {
    "pre_profitability": {"f1": 0.30, "f2": 0.10, "f3": 0.30, "f4": 0.15, "f5": 0.15},
    "mid_cap":           {"f1": 0.20, "f2": 0.20, "f3": 0.20, "f4": 0.15, "f5": 0.25},
    "established":       {"f1": 0.15, "f2": 0.20, "f3": 0.10, "f4": 0.15, "f5": 0.40},
}

WEIGHTS_C: Final[dict[str, dict[str, float]]] = {
    "pre_profitability": {
        "f1": 0.25, "f2": 0.10, "f3": 0.25, "f4": 0.10,
        "f5": 0.05, "f6": 0.15, "f7": 0.10,
    },
    "mid_cap": {
        "f1": 0.15, "f2": 0.15, "f3": 0.15, "f4": 0.10,
        "f5": 0.20, "f6": 0.10, "f7": 0.15,
    },
    "established": {
        "f1": 0.10, "f2": 0.20, "f3": 0.05, "f4": 0.10,
        "f5": 0.30, "f6": 0.05, "f7": 0.20,
    },
}

# ── F7 disclaimer (always appended) ──────────────────────────────────────
F7_DISCLAIMER: Final = (
    "F7 rests on contested academic ground. Arnott (Research Affiliates) argues "
    "valuation z-scores predict factor returns; Asness (AQR) argues the effect is "
    "exaggerated and inapplicable. AQR manages $100B+ on the opposite view. "
    "Score weighted ≤ 0.10. Use with explicit knowledge of this dispute."
)

# ── History depth (ADR-030-A2) ────────────────────────────────────────────
# Must EXCEED the strictest framework floor (F7's MIN_HISTORY_YEARS=10), not
# equal it: filing-date drift otherwise leaves most companies one row short.
# At a depth of 10, only 19.1% of companies reached 10 annual rows against
# 55.6% reaching 9.
DEFAULT_HISTORY_YEARS = 12
