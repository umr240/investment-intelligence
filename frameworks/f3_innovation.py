"""
F3 — Innovation Compounder.

Three academic signals combine to a 0-10 score:

  1. Gross-margin expansion trajectory                     4 points
     Average YoY change in gross_margin over the last 4-5 annual periods.
     Target ≥200bps/yr per PROJECT_SPEC §F3 (the SaaS/hardware-product
     "scaling moat" signal). Companies with widening unit economics
     consistently outperform in the academic literature.

  2. R&D-intensity sweet spot                              3 points
     rd_expense / revenue. The literature finds an inverted-U: too
     little R&D and you under-invest; too much and capital efficiency
     deteriorates. PROJECT_SPEC threshold: 15-35% of revenue.

  3. Earnings surprise streak (Jegadeesh-Livnat 2006 proxy) 3 points
     Consecutive quarters with positive eps_surprise_pct. PROJECT_SPEC
     uses revenue surprise; yfinance only exposes EPS surprise — used
     as a documented proxy. Two-plus consecutive positive = streak.

Components NOT in F3 v1 (deferred per PROJECT_SPEC):
  - Innovative Efficiency proxy (Hirshleifer-Hsu-Li 2013) requires
    patents_filed × R&D — no patent data source. Spec says "skip
    signal" if patent data unavailable. We score 0 + data_gap.
  - Estimate revision trend requires snapshots of analyst estimates
    over 90-day windows; we don't yet store estimate history.

Inputs come from `CompanyDataReader`. F3 reads:
  - reader.annuals(last_n=6)         # 5 YoY changes need 6 annuals
  - reader.earnings_history(last_n=8)

Recent IPOs with <2 annual periods raise InsufficientHistoryError; the
orchestrator surfaces it as "unfeasible" rather than failing the dive.
With 2-4 annuals we score what we can; the framework is graceful with
short history (the user explicitly tested INTA, a 2021 IPO with 6
annuals).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
)


DATA_REQUIREMENT = DataRequirement(
    annual_years=5,                    # 5yr GM trajectory; reader is allowed to return less
    quarterly_count=8,                 # surprise streak proxy (8Q yfinance default)
    needs_analyst_coverage=True,
    needs_earnings_history=True,
    needs_patent_disclosure=True,      # 5k-6 partial: 10-K text patent count
)


# ── Tunables (per PROJECT_SPEC §F3) ────────────────────────────────────────

GM_EXPANSION_TARGET_BPS = 200.0          # ≥200bps avg YoY = strong
GM_EXPANSION_PARTIAL_BPS = 100.0         # ≥100bps = partial
GM_EXPANSION_MIN_PERIODS = 2             # need ≥2 YoY changes (3 annuals)

RD_SWEET_LO = 0.15                       # 15% sweet-spot floor
RD_SWEET_HI = 0.35                       # 35% sweet-spot ceiling
RD_NEAR_LO = 0.10                        # 10-15% or 35-45% near-band
RD_NEAR_HI = 0.45

SURPRISE_STREAK_FULL = 4                 # 4+ in a row → 3 pts
SURPRISE_STREAK_STRONG = 3               # 3 in a row → 2 pts
SURPRISE_STREAK_PARTIAL = 2              # 2 in a row → 1 pt

GM_MAX_POINTS = 4.0
RD_MAX_POINTS = 3.0
SURPRISE_MAX_POINTS = 3.0

# Phase 5k-6 partial: patent disclosure scoring. Permanent state — the
# full Hirshleifer-Hsu-Li citation signal via api.uspto.gov was SHELVED
# 2026-05-10 (developer.uspto.gov requires US-side ID verification).
# Alternative sources if a contributor wants to revive it: Google Patents
# BigQuery, EPO OPS, Lens.org. Today F3 scores on absolute portfolio size from
# 10-K text — coarse but bounded. Hit rate is empirically low because
# modern 10-Ks trend qualitative ("extensive portfolio") over numeric.
PATENT_HEAVY = 1000              # ≥1000 patents → 1.0pt (defensible portfolio)
PATENT_MODERATE = 100            # ≥100 patents → 0.5pt
PATENT_MAX_POINTS = 1.0


async def score_f3(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F3 — Innovation Compounder score for `ticker`."""
    annuals = reader.annuals(last_n=6)    # newest-first
    if len(annuals) < 2:
        raise InsufficientHistoryError(
            "F3", needed=2, got=len(annuals), period_kind="annual"
        )

    signals: dict[str, Any] = {}
    data_gaps: list[str] = []

    # ── 1. Gross-margin expansion trajectory ─────────────────────────────
    gm_pts, gm_signals, gm_gap = _compute_gm_trajectory(annuals, ticker)
    signals["gm_trajectory"] = gm_signals
    if gm_gap:
        data_gaps.append(gm_gap)

    # ── 2. R&D intensity sweet spot ──────────────────────────────────────
    rd_pts, rd_signals, rd_gap = _compute_rd_intensity(annuals, ticker)
    signals["rd_intensity"] = rd_signals
    if rd_gap:
        data_gaps.append(rd_gap)

    # ── 3. Earnings surprise streak (proxy for revenue surprise) ─────────
    streak_pts, streak_signals, streak_gap = _compute_surprise_streak(reader)
    signals["surprise_streak"] = streak_signals
    if streak_gap:
        data_gaps.append(streak_gap)

    # ── 4. Patent disclosure (5k-6 partial — 10-K text fallback) ─────────
    patent_pts, patent_signals, patent_gap = _compute_patent_disclosure(annuals[0], ticker)
    signals["patent_disclosure"] = patent_signals
    if patent_gap:
        data_gaps.append(patent_gap)

    # ── Composite assembly (0-10, capped) ────────────────────────────────
    score = round(gm_pts + rd_pts + streak_pts + patent_pts, 2)
    score = min(max(score, 0.0), 10.0)

    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    return FrameworkResult(
        framework="F3",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
    )


# ── 1. Gross-margin expansion trajectory ──────────────────────────────────


def _compute_gm_trajectory(
    annuals: list[Any], ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Average YoY change in gross_margin across consecutive annuals.

    annuals is newest-first; we compute YoY differences from oldest pair to
    newest pair (e.g. with 6 annuals → 5 YoY changes).
    """
    # Filter to annuals with valid gross_margin
    gm_series = [(a.fiscal_year, a.gross_margin) for a in annuals if a.gross_margin is not None]
    if len(gm_series) < 2:
        return 0.0, {
            "yoy_changes_bps": [],
            "avg_yoy_bps": None,
            "n_periods": len(gm_series),
            "points": 0.0,
        }, f"{ticker}: F3 GM trajectory — only {len(gm_series)} annuals with gross_margin"

    # Compute YoY changes — newest_minus_prior, in basis points
    # gm_series is newest-first; pair (i, i+1) gives YoY from older→newer
    changes_bps: list[float] = []
    pairs: list[dict[str, Any]] = []
    for i in range(len(gm_series) - 1):
        fy_new, gm_new = gm_series[i]
        fy_old, gm_old = gm_series[i + 1]
        delta = (gm_new - gm_old) * 10000.0    # to basis points
        changes_bps.append(delta)
        pairs.append({
            "fy": fy_new, "prior_fy": fy_old,
            "gm_new": round(gm_new, 4), "gm_old": round(gm_old, 4),
            "delta_bps": round(delta, 1),
        })

    avg_bps = sum(changes_bps) / len(changes_bps)

    if avg_bps >= GM_EXPANSION_TARGET_BPS:
        pts = GM_MAX_POINTS
        band = "strong_expansion"
    elif avg_bps >= GM_EXPANSION_PARTIAL_BPS:
        pts = 3.0
        band = "partial_expansion"
    elif avg_bps >= 0.0:
        pts = 2.0
        band = "flat_to_slight"
    elif avg_bps >= -100.0:
        pts = 1.0
        band = "mild_compression"
    else:
        pts = 0.0
        band = "significant_compression"

    # Penalise insufficient history — when fewer than the recommended periods,
    # we're less confident. Halve the points for ≤1 period.
    if len(changes_bps) < GM_EXPANSION_MIN_PERIODS:
        pts = pts / 2

    return pts, {
        "yoy_changes_bps": [round(c, 1) for c in changes_bps],
        "yoy_pairs": pairs,
        "avg_yoy_bps": round(avg_bps, 1),
        "n_periods": len(changes_bps),
        "band": band,
        "points": round(pts, 2),
    }, None


# ── 2. R&D intensity sweet spot ───────────────────────────────────────────


def _compute_rd_intensity(
    annuals: list[Any], ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Use the most recent annual's rd_intensity. PROJECT_SPEC sweet spot
    is 15-35%. Mid-15-35% range gets full points; near bands partial; outside
    zero.
    """
    rd_intensities = [
        (a.fiscal_year, a.rd_intensity) for a in annuals
        if a.rd_intensity is not None
    ]
    if not rd_intensities:
        # Phase 5S-2: distinguish "bundled into Other OpEx" (HIMS pattern)
        # from "no R&D evidence at all". When the latest annual carries
        # rd_disclosure_state='bundled_in_opex', the filer DOES do R&D —
        # the tax footnote confirms it — but doesn't tag it as a separate
        # XBRL line. Surface as informational, not a hard miss. F3 still
        # scores 0 (we genuinely don't know the magnitude), but the dive
        # renderer + narrative can show the qualitative signal.
        state = getattr(annuals[0], "rd_disclosure_state", None) if annuals else None
        if state == "bundled_in_opex":
            return 0.0, {
                "latest_rd_intensity": None,
                "n_periods_with_data": 0,
                "state": "bundled_in_opex",
                "band": "bundled_in_opex",
                "points": 0.0,
                "note": (
                    "R&D activity confirmed via tax-footnote signal "
                    "(IncomeTaxReconciliationTaxCreditsResearch) but the filer "
                    "does not tag ResearchAndDevelopmentExpense in XBRL — "
                    "R&D is bundled into 'Operations & Support' or 'Other OpEx'. "
                    "Magnitude unknowable from XBRL alone; F3 R&D intensity "
                    "scored 0 without penalty."
                ),
            }, None
        return 0.0, {
            "latest_rd_intensity": None,
            "n_periods_with_data": 0,
            "state": "not_disclosed",
            "points": 0.0,
        }, f"{ticker}: F3 R&D intensity — no annual with rd_intensity"

    fy_latest, rd_latest = rd_intensities[0]

    if RD_SWEET_LO <= rd_latest <= RD_SWEET_HI:
        pts = RD_MAX_POINTS
        band = "sweet_spot"
    elif RD_NEAR_LO <= rd_latest < RD_SWEET_LO or RD_SWEET_HI < rd_latest <= RD_NEAR_HI:
        pts = 2.0
        band = "near_sweet"
    elif 0.05 <= rd_latest < RD_NEAR_LO or RD_NEAR_HI < rd_latest <= 0.55:
        pts = 1.0
        band = "edge_band"
    else:
        pts = 0.0
        band = "outside_band"

    # Optional: trend across history
    trend = None
    if len(rd_intensities) >= 3:
        recent_3 = [v for _, v in rd_intensities[:3]]
        # newest-first → recent_3[0] is latest
        if recent_3[0] > recent_3[-1] + 0.02:
            trend = "rising"
        elif recent_3[0] < recent_3[-1] - 0.02:
            trend = "falling"
        else:
            trend = "stable"

    # Tier 2.5 (2026-05-15): peer-relative R&D intensity context via SEC
    # frames. The absolute sweet-spot bands above are empirically
    # validated (Chan-Lakonishok-Sougiannis 2001) so we don't change the
    # POINTS scoring — but we surface SIC-filtered peer percentile +
    # sector median as supplementary `peer` signals so the narrative LLM
    # + dive display can contextualise: "MRVL R&D-intensity 33.82% is
    # 73rd pctile vs SIC 3674 peers (sector median 4.5%)" tells a much
    # richer story than the absolute "edge_band" label alone.
    peer_signals = _rd_peer_percentile(ticker, annuals[0])

    return pts, {
        "latest_rd_intensity": round(rd_latest, 4),
        "latest_fy": fy_latest,
        "sweet_band": (RD_SWEET_LO, RD_SWEET_HI),
        "band": band,
        "state": "disclosed_exact",
        "trend_3yr": trend,
        "n_periods_with_data": len(rd_intensities),
        "points": pts,
        "peer": peer_signals,
    }, None


def _rd_peer_percentile(ticker: str, current: Any) -> dict[str, Any]:
    """Compute SIC-filtered R&D intensity percentile rank vs peers.

    Returns a signals dict with peer_count, percentile, sector_median,
    sic_code, period. Empty dict (no info) on any failure — peer info
    is supplementary, never blocks scoring.
    """
    try:
        from sqlalchemy import select
        from data.db import SessionLocal
        from data.models.schema import Company
        from data.sec_frames import (
            build_sic_lookup_from_db,
            fetch_frame,
            get_percentile_rank,
        )

        with SessionLocal() as s:
            c = s.execute(
                select(Company).where(Company.ticker == ticker)
            ).scalar_one_or_none()
            if c is None or c.sic_code is None or c.cik is None:
                return {}
            sic_str = str(c.sic_code).zfill(4)
            try:
                cik_int = int(c.cik.lstrip("0") or "0")
            except ValueError:
                return {}

        period_end = getattr(current, "period_end_date", None)
        if period_end is None:
            return {}

        # Year fallback for non-Dec-FYE filers (NVDA / LULU / MRVL pattern)
        # Revenue concept union (Revenues + RevenueFromContractWithCustomerExcludingAssessedTax)
        ds_rd = None
        ds_rev = None
        period = None
        for year_candidate in (period_end.year, period_end.year - 1):
            period_try = f"CY{year_candidate}"
            rd_try = fetch_frame("ResearchAndDevelopmentExpense", period_try)
            rev_legacy = fetch_frame("Revenues", period_try)
            rev_modern = fetch_frame(
                "RevenueFromContractWithCustomerExcludingAssessedTax", period_try
            )
            # Build merged revenue dataset (prefer legacy, fall back to modern per CIK)
            if rev_legacy or rev_modern:
                from data.sec_frames import FrameDataset
                merged = FrameDataset(concept="Revenue_union", period=period_try)
                seen = set()
                for ds in (rev_legacy, rev_modern):
                    if ds is None:
                        continue
                    for e in ds.entries:
                        if e.cik not in seen:
                            merged.entries.append(e)
                            seen.add(e.cik)
                if rd_try and cik_int in rd_try.by_cik() and cik_int in seen:
                    ds_rd = rd_try
                    ds_rev = merged
                    period = period_try
                    break
        if ds_rd is None or ds_rev is None:
            return {}

        sic_lookup = build_sic_lookup_from_db()
        rank = get_percentile_rank(
            target_cik=cik_int,
            dataset_num=ds_rd,
            dataset_den=ds_rev,
            sic_lookup=sic_lookup,
            sic_prefix=sic_str[:2],   # 2-digit SIC sector
            min_peer_count=8,
        )
        if rank is None:
            return {}
        return {
            "sic_code": c.sic_code,
            "sic_prefix": sic_str[:2],
            "peer_count": rank["peer_count"],
            "percentile": round(rank["percentile"], 1),
            "sector_median": round(rank["median"], 4),
            "period": period,
            "method": "sec_frames_sic_filtered",
        }
    except Exception as exc:
        logger.debug("R&D peer percentile failed for %s: %s", ticker, exc)
        return {}


# ── 3. Earnings surprise streak ───────────────────────────────────────────


def _compute_surprise_streak(reader: Any) -> tuple[float, dict[str, Any], str | None]:
    """Consecutive REPORTED earnings rows with eps_surprise_pct > 0.

    yfinance.earnings_history rows are most-recent-first. A future-quarter
    estimate row has surprise=None; we skip those and start the streak
    from the first REPORTED row.

    Note: PROJECT_SPEC asks for revenue-surprise streak; yfinance only
    exposes EPS surprise. Documented proxy.
    """
    rows = reader.earnings_history(last_n=8)
    reported = [r for r in rows if r.eps_surprise_pct is not None]
    if not reported:
        return 0.0, {
            "streak": 0,
            "reported_count": 0,
            "points": 0.0,
        }, "F3 surprise streak: no reported earnings rows"

    streak = 0
    streak_values: list[float] = []
    for r in reported:
        if r.eps_surprise_pct > 0:
            streak += 1
            streak_values.append(r.eps_surprise_pct)
        else:
            break

    if streak >= SURPRISE_STREAK_FULL:
        pts = SURPRISE_MAX_POINTS
    elif streak >= SURPRISE_STREAK_STRONG:
        pts = 2.0
    elif streak >= SURPRISE_STREAK_PARTIAL:
        pts = 1.0
    else:
        pts = 0.0

    return pts, {
        "streak": streak,
        "streak_values_pct": [round(v, 2) for v in streak_values],
        "reported_count": len(reported),
        "first_break": (
            reported[streak].eps_surprise_pct if streak < len(reported) else None
        ),
        "points": pts,
    }, None



# ── 4. Patent disclosure (Phase 5k-6 partial) ────────────────────────────


def _compute_patent_disclosure(
    latest_annual: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Score absolute patent count from 10-K text.

    Coarse fallback while waiting on USPTO API key (5k-6b) for the full
    Hirshleifer-Hsu-Li signal. Returns 0pt with a graceful note when not
    disclosed — most non-tech / non-biotech companies don't quantify
    portfolio size.
    """
    pc = getattr(latest_annual, "patent_count_disclosed", None)
    state = getattr(latest_annual, "patent_disclosure_state", None)
    if pc is None:
        return 0.0, {
            "value": None,
            "band": "not_disclosed",
            "points": 0.0,
            "max_points": PATENT_MAX_POINTS,
            "state": state or "not_disclosed",
            "note": (
                "10-K patent disclosure absent or below regex threshold; "
                "full Hirshleifer-Hsu-Li citation signal blocked on USPTO "
                "API key (task 5k-6b)."
            ),
        }, None
    if pc >= PATENT_HEAVY:
        pts = PATENT_MAX_POINTS
        band = "defensible_portfolio"
    elif pc >= PATENT_MODERATE:
        pts = 0.5
        band = "moderate_portfolio"
    else:
        pts = 0.0
        band = "small_portfolio"
    return pts, {
        "value": int(pc),
        "band": band,
        "points": pts,
        "max_points": PATENT_MAX_POINTS,
        "state": state or "disclosed_exact",
    }, None
