"""
F4 — Stealth Accumulation.

Four academic signals combine to a 0-10 score:

  1. Short-interest decline (Desai 2002, Boehmer 2008)        3 points
     Peak SI > 8% AND current SI < 5% across recent settlements
     → bullish "shorts being covered" signal. With Polygon time-series
     short interest (ADR-019 P3), we now have ~24 bi-monthly readings
     per year — this signal is materially stronger than the old
     yfinance single-snapshot.

  2. 13F holder-count rising (Cohen-Polk-Silli 2010)          2 points
     Holder count Q4 vs Q1 +10% = institutional accumulation.
     NOTE: requires multiple dives over time to accumulate snapshots.
     v1 reports a data_gap when only one snapshot exists.

  3. EPS acceleration (Chan-Jegadeesh-Lakonishok 1996)        3 points
     Strict monotonic increase in eps_actual across last 4 quarters.

  4. EPS surprise streak (proxy for revenue beat streak)      2 points
     Consecutive quarters with eps_surprise_pct > 0. Spec calls for
     revenue surprise; yfinance only exposes EPS surprise. Documented
     proxy. Overlaps slightly with F2's PEAD signal — F4 weights it
     differently (needs longer streak; rewards "stealth" not catalyst).

Components NOT in F4 v1:
  - Options put/call ratio (Pan-Poteshman 2006). Free-tier CBOE/Market-
    Chameleon data unavailable; PROJECT_SPEC says "flag as data gap".
"""
from __future__ import annotations

from typing import Any

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
)


DATA_REQUIREMENT = DataRequirement(
    quarterly_count=4,
    needs_short_interest_history=True,
    needs_institutional_holders=True,
    needs_earnings_history=True,
)


# ── Tunables (per PROJECT_SPEC §F4) ────────────────────────────────────────

SI_PEAK_HIGH = 8.0                 # peak above 8% short → "high SI" prerequisite
SI_CURRENT_LOW = 5.0               # current below 5% → "covered" indicator
SI_LOOKBACK_DAYS = 200             # ~6 bi-monthly settlements per Polygon spec
SI_MIN_OBSERVATIONS = 4            # need at least 4 readings for trend math

HOLDER_GROWTH_THRESHOLD = 0.10     # +10% holder count Q4 vs Q1

EPS_ACCEL_PERIODS = 4              # need 4 quarters of monotonic EPS

SURPRISE_STREAK_FULL = 4
SURPRISE_STREAK_PARTIAL = 2

SI_MAX_POINTS = 3.0
HOLDER_MAX_POINTS = 2.0
EPS_ACCEL_MAX_POINTS = 3.0
SURPRISE_STREAK_MAX_POINTS = 2.0


async def score_f4(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F4 — Stealth Accumulation score."""
    signals: dict[str, Any] = {}
    data_gaps: list[str] = []

    # ── 1. Short-interest decline ────────────────────────────────────────
    si_pts, si_signals, si_gap = _compute_short_interest(reader, ticker)
    signals["short_interest"] = si_signals
    if si_gap:
        data_gaps.append(si_gap)

    # ── 2. 13F holder count delta ────────────────────────────────────────
    holder_pts, holder_signals, holder_gap = _compute_holder_count_delta(reader, ticker)
    signals["holders"] = holder_signals
    if holder_gap:
        data_gaps.append(holder_gap)

    # ── 3. EPS acceleration ──────────────────────────────────────────────
    eps_pts, eps_signals, eps_gap = _compute_eps_acceleration(reader, ticker)
    signals["eps_acceleration"] = eps_signals
    if eps_gap:
        data_gaps.append(eps_gap)

    # ── 4. EPS surprise streak (proxy for revenue beat streak) ───────────
    surprise_pts, surprise_signals, surprise_gap = _compute_surprise_streak(reader, ticker)
    signals["surprise_streak"] = surprise_signals
    if surprise_gap:
        data_gaps.append(surprise_gap)

    # Options data — explicit deferral per spec
    data_gaps.append(
        f"{ticker}: F4 options put/call ratio — no free-tier source "
        "(skipped per PROJECT_SPEC §F4 Pan-Poteshman 2006)"
    )

    score = round(si_pts + holder_pts + eps_pts + surprise_pts, 2)
    score = min(max(score, 0.0), 10.0)
    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    return FrameworkResult(
        framework="F4",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
    )


# ── 1. Short-interest decline (Desai-Boehmer) ─────────────────────────────


def _compute_short_interest(
    reader: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Peak > 8% AND current < 5% across recent settlements = strong signal.

    Filters to Polygon-sourced rows (ADR-019 P3 time series), since yfinance
    only records "today's snapshot" → its short_pct_float values are all
    identical and don't form a real time series. Falls back to yfinance
    snapshot when no Polygon rows exist.
    """
    rows = reader.short_interest_history(within_days=SI_LOOKBACK_DAYS, last_n=24)
    # Prefer Polygon time-series rows
    polygon_rows = [r for r in rows if (r.source or "") == "polygon"]
    series = polygon_rows or rows
    series = [r for r in series if r.short_pct_float is not None]

    if len(series) < SI_MIN_OBSERVATIONS:
        return 0.0, {
            "n_observations": len(series),
            "current_pct_float": series[0].short_pct_float if series else None,
            "peak_pct_float": None,
            "decline_signal": False,
            "points": 0.0,
        }, f"{ticker}: F4 short-interest — only {len(series)} observations (need ≥{SI_MIN_OBSERVATIONS})"

    series_sorted = sorted(series, key=lambda r: r.settlement_date)
    current = series_sorted[-1].short_pct_float
    peak = max(r.short_pct_float for r in series_sorted)

    decline_signal = peak > SI_PEAK_HIGH and current < SI_CURRENT_LOW

    if decline_signal:
        pts = SI_MAX_POINTS
        band = "covered_decline"
    elif peak > SI_PEAK_HIGH and current < peak * 0.6:
        # Partial: still elevated short, but trending down 40%+
        pts = 1.5
        band = "partial_cover"
    elif current < 2.0:
        # Always-low short — not a stealth signal but not adversarial
        pts = 0.5
        band = "consistently_low"
    elif current > peak * 0.9:
        # Short interest at-or-near peak → adversarial
        pts = 0.0
        band = "elevated"
    else:
        pts = 1.0
        band = "neutral"

    return pts, {
        "n_observations": len(series_sorted),
        "current_pct_float": round(current, 3),
        "peak_pct_float": round(peak, 3),
        "current_settlement_date": series_sorted[-1].settlement_date,
        "peak_settlement_date": max(series_sorted, key=lambda r: r.short_pct_float).settlement_date,
        "decline_signal": decline_signal,
        "band": band,
        "source_priority": "polygon" if polygon_rows else "yfinance_snapshot",
        "points": pts,
    }, None


# ── 2. 13F holder count delta ─────────────────────────────────────────────


def _compute_holder_count_delta(
    reader: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """+10% holder count over 4Q is bullish accumulation. Requires multi-dive
    history; v1 reports gap when only one snapshot exists.
    """
    history = reader.institutional_holder_count_history()
    if len(history) < 2:
        return 0.0, {
            "snapshot_dates": [d for d, _ in history],
            "snapshot_counts": [n for _, n in history],
            "delta_pct": None,
            "points": 0.0,
        }, (f"{ticker}: F4 13F holder-count delta — only {len(history)} snapshot(s) "
            "(needs multiple dives over time to accumulate)")

    # Newest first → take first vs last for delta
    latest_date, latest_n = history[0]
    oldest_date, oldest_n = history[-1]
    if oldest_n == 0:
        return 0.0, {
            "latest_count": latest_n, "oldest_count": oldest_n,
            "delta_pct": None, "points": 0.0,
        }, f"{ticker}: F4 holder count delta — oldest snapshot empty"

    delta_pct = (latest_n - oldest_n) / oldest_n
    if delta_pct >= HOLDER_GROWTH_THRESHOLD:
        pts = HOLDER_MAX_POINTS
    elif delta_pct >= 0.0:
        pts = 1.0
    else:
        pts = 0.0

    return pts, {
        "snapshot_dates": [d for d, _ in history],
        "snapshot_counts": [n for _, n in history],
        "latest_date": latest_date,
        "latest_count": latest_n,
        "oldest_date": oldest_date,
        "oldest_count": oldest_n,
        "delta_pct": round(delta_pct, 4),
        "threshold": HOLDER_GROWTH_THRESHOLD,
        "points": pts,
    }, None


# ── 3. EPS acceleration ───────────────────────────────────────────────────


def _compute_eps_acceleration(
    reader: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Monotonic EPS increase across the last 4 reported quarters."""
    rows = reader.earnings_history(last_n=8)
    reported = [r for r in rows if r.eps_actual is not None]
    if len(reported) < EPS_ACCEL_PERIODS:
        return 0.0, {
            "reported_count": len(reported),
            "needed": EPS_ACCEL_PERIODS,
            "monotonic": False,
            "points": 0.0,
        }, f"{ticker}: F4 EPS accel — only {len(reported)} reported quarters"

    # earnings_history is most-recent-first; reverse for chronological order
    chrono = list(reversed(reported[:EPS_ACCEL_PERIODS]))
    eps_values = [r.eps_actual for r in chrono]

    monotonic = all(eps_values[i] > eps_values[i - 1] for i in range(1, len(eps_values)))
    weakly_increasing = all(eps_values[i] >= eps_values[i - 1] for i in range(1, len(eps_values)))

    if monotonic:
        pts = EPS_ACCEL_MAX_POINTS
        band = "strict_monotonic"
    elif weakly_increasing:
        pts = 2.0
        band = "weakly_increasing"
    elif eps_values[-1] > eps_values[0]:
        pts = 1.0
        band = "net_increase_with_dips"
    else:
        pts = 0.0
        band = "no_acceleration"

    return pts, {
        "reported_count": len(reported),
        "eps_sequence_chrono": eps_values,
        "monotonic": monotonic,
        "band": band,
        "points": pts,
    }, None


# ── 4. EPS surprise streak (proxy for revenue beat streak) ────────────────


def _compute_surprise_streak(
    reader: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    rows = reader.earnings_history(last_n=8)
    reported = [r for r in rows if r.eps_surprise_pct is not None]
    if not reported:
        return 0.0, {"streak": 0, "points": 0.0}, "F4 surprise streak: no reported rows"

    streak = 0
    for r in reported:
        if r.eps_surprise_pct > 0:
            streak += 1
        else:
            break

    if streak >= SURPRISE_STREAK_FULL:
        pts = SURPRISE_STREAK_MAX_POINTS
    elif streak >= SURPRISE_STREAK_PARTIAL:
        pts = 1.0
    else:
        pts = 0.0

    return pts, {
        "streak": streak,
        "reported_count": len(reported),
        "points": pts,
    }, None
