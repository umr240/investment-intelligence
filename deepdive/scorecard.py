"""
ScorecardData — pre-computed quantitative signals for the AI narrative layer.
All fields computed by pure Python. Serialised to JSON before any AI call.
The AI layer receives this JSON, never raw financial statements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ScorecardData:
    # ── Company metadata ──────────────────────────────────────────────────
    ticker: str
    name: str
    exchange: str
    sector: str
    market_cap_usd: float
    price: float
    ev: float
    listing_date: date | None
    listing_type: str                    # 'standard' | 'spinoff' | 'demerger' | 'ipo'

    # ── F1 signals ────────────────────────────────────────────────────────
    piotroski_score: int = 0             # 0–9
    piotroski_signals: dict[str, bool] = field(default_factory=dict)  # all 9 signals
    sloan_accruals_ratio: float = 0.0   # negative = high quality
    gp_a: float = 0.0                   # gross profit / total assets
    gp_a_sector_percentile: float = 0.0 # 0–100 (target: ≥60)
    insider_cluster_90d: int = 0        # unique open-market buyers last 90 days
    analyst_count: int = 0              # use lowest count across sources
    asset_growth_yoy: float = 0.0
    asset_growth_decile: int = 5         # 1=lowest, 10=highest (≥9 = disqualify)
    external_financing_flag: bool = False

    # ── F2 signals ────────────────────────────────────────────────────────
    return_6m: float | None = None
    return_12m: float | None = None
    momentum_decile: int | None = None   # vs universe
    pct_from_52wk_high: float | None = None
    near_52wk_high: bool = False         # within 10%
    ev_revenue_z_score: float | None = None
    pb_z_score: float | None = None
    pead_direction: str = "mixed"        # 'positive' | 'negative' | 'mixed'

    # ── F3 signals ────────────────────────────────────────────────────────
    gross_margins: list[float] = field(default_factory=list)  # 5 years
    avg_gm_expansion_bps: float = 0.0   # target: ≥200bps
    rd_intensity: float = 0.0           # R&D / revenue
    rd_intensity_in_range: bool = False  # 15–35% sweet spot
    revenue_surprise_streak: int = 0     # consecutive positive surprises
    estimate_revision_direction: str = "flat"  # 'up' | 'down' | 'flat'

    # ── F4 signals ────────────────────────────────────────────────────────
    si_current: float | None = None     # short interest % float
    si_peak_6m: float | None = None
    si_declining: bool = False          # high→low transition signal
    institutional_holder_count_trend: list[int] = field(default_factory=list)  # 4 quarters
    eps_sequence: list[float] = field(default_factory=list)     # 4 quarters
    eps_accelerating: bool = False
    revenue_beat_streak: int = 0

    # ── F5 signals ────────────────────────────────────────────────────────
    revenue_cagr_3yr: float | None = None
    fcf_margin: float | None = None
    gaap_roic: float | None = None
    gp_a_top40: bool = False
    debt_ebitda: float | None = None
    buyback_yield: float | None = None
    ceo_tenure_years: float | None = None
    is_founder_ceo: bool = False
    ceo_equity_pct: float | None = None

    # ── F6 signals (Mode C) ───────────────────────────────────────────────
    founder_ceo_equity_signal: bool = False
    customer_concentration_pct: float | None = None
    customer_relationship_years: float | None = None
    estimated_nrr: float | None = None
    rule_of_40: float | None = None
    estimated_grr: float | None = None

    # ── F7 signals (Mode C) ───────────────────────────────────────────────
    ev_revenue_10yr_history: list[float] | None = None
    pb_10yr_history: list[float] | None = None
    ev_revenue_z: float | None = None
    pb_z: float | None = None

    # ── Computed framework scores ─────────────────────────────────────────
    f1_score: float = 0.0
    f2_score: float = 0.0
    f3_score: float = 0.0
    f4_score: float | None = None
    f5_score: float | None = None
    f6_score: float | None = None
    f7_score: float | None = None
    composite_score: float = 0.0
    verdict: str = "exclude"            # ADR-054 labels; see frameworks/composite.py

    # ── Overlay trigger detection (passive) ───────────────────────────────
    overlay_triggers: list[Any] = field(default_factory=list)
    overlay_results: dict[str, Any] = field(default_factory=dict)  # populated only if run

    # ── Disqualification ──────────────────────────────────────────────────
    disqualified: bool = False
    disqualification_reasons: list[str] = field(default_factory=list)

    # ── Data gaps ─────────────────────────────────────────────────────────
    data_gaps: list[str] = field(default_factory=list)
    idiosyncratic_vol: float | None = None
    return_skewness_3yr: float | None = None
    tam_estimate: float | None = None   # for BEW overlay TAM/Revenue check
