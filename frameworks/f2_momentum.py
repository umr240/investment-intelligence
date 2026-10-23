"""
F2 — Momentum + Mean Reversion.

Three academic components combine to a 0-10 score:

  1. 12-1 momentum (Jegadeesh-Titman 1993)             4 points
     The textbook winners-vs-losers signal. We compute the price
     return from ~52 weeks ago to ~4 weeks ago — skip the most
     recent month per J-T's "skip-1" convention which removes the
     short-term reversal effect.

  2. 52-week-high proximity (George-Hwang 2004)        3 points
     Price near its 52-week high is a remarkably persistent forward
     predictor. Within 10% = bullish per PROJECT_SPEC.

  3. PEAD — Post-Earnings Announcement Drift (Bernard-Thomas 1989)  3 points
     Two consecutive positive EPS surprises predict near-term
     positive drift. Two consecutive negative = mean reversion
     candidate.

Inputs come from `CompanyDataReader`. F2 reads:
  - reader.price_history(within_days=~420)
  - reader.earnings_history(last_n=8)

Recent IPOs (<52 weeks of price history) raise InsufficientHistoryError;
the orchestrator surfaces that as "unfeasible" rather than failing the
dive. Companies with <2 reported earnings rows lose the PEAD points but
the framework still scores.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
)


DATA_REQUIREMENT = DataRequirement(
    quarterly_count=4,
    price_history_years=2,
    needs_earnings_history=True,
)


# ── Tunables ──────────────────────────────────────────────────────────────

MOM_WINDOW_DAYS_FAR = 365      # 12-month anchor
MOM_WINDOW_DAYS_NEAR = 28      # skip-1-month anchor (J-T)
MOM_TOLERANCE_DAYS = 21        # ±21 days flex for nearest weekly bar lookup

NEAR_HIGH_BAND_TIGHT = 0.05    # within 5% of 52w high → 3 pts
NEAR_HIGH_BAND_MID = 0.10      # within 10% → 2 pts (PROJECT_SPEC threshold)
NEAR_HIGH_BAND_LOOSE = 0.20    # within 20% → 1 pt

MOMENTUM_MAX_POINTS = 4.0
NEAR_HIGH_MAX_POINTS = 3.0
PEAD_MAX_POINTS = 3.0


async def score_f2(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F2 — Momentum score for `ticker`."""
    prices = reader.price_history(within_days=420)
    if not prices:
        raise InsufficientHistoryError("F2", needed=52, got=0, period_kind="weekly_price")

    # Sort newest-last for window math
    prices_asc = sorted(prices, key=lambda p: p.date)
    if len(prices_asc) < 30:
        raise InsufficientHistoryError(
            "F2", needed=52, got=len(prices_asc), period_kind="weekly_price",
        )

    signals: dict[str, Any] = {}
    data_gaps: list[str] = []

    # ── 1. 12-1 momentum ─────────────────────────────────────────────────
    momentum_pts, mom_signals, mom_gap = _compute_momentum(prices_asc, ticker)
    signals["momentum"] = mom_signals
    if mom_gap:
        data_gaps.append(mom_gap)

    # ── 2. 52-week-high proximity ────────────────────────────────────────
    near_high_pts, near_high_signals = _compute_52w_high(prices_asc)
    signals["near_52w_high"] = near_high_signals

    # ── 3. PEAD ──────────────────────────────────────────────────────────
    pead_pts, pead_signals, pead_gap = _compute_pead(reader)
    signals["pead"] = pead_signals
    if pead_gap:
        data_gaps.append(pead_gap)

    score = round(momentum_pts + near_high_pts + pead_pts, 2)
    score = min(max(score, 0.0), 10.0)

    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    return FrameworkResult(
        framework="F2",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
    )


# ── 1. Jegadeesh-Titman 12-1 momentum ──────────────────────────────────────


def _compute_momentum(
    prices_asc: list[Any], ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Return (points, signals, optional_gap)."""
    most_recent = prices_asc[-1]
    today = most_recent.date

    near = _find_price_near(prices_asc, today - timedelta(days=MOM_WINDOW_DAYS_NEAR))
    far = _find_price_near(prices_asc, today - timedelta(days=MOM_WINDOW_DAYS_FAR))

    if near is None or far is None or far.close in (None, 0):
        return 0.0, {
            "return_12_1": None,
            "near_anchor_date": getattr(near, "date", None),
            "far_anchor_date": getattr(far, "date", None),
            "points": 0.0,
        }, f"{ticker}: F2 momentum — insufficient price anchors"

    return_12_1 = (near.close - far.close) / far.close

    # Step function — academic literature reports the strongest signal in
    # the top quintile of cross-sectional momentum (~30-50%+ trailing).
    if return_12_1 > 0.40:
        pts = MOMENTUM_MAX_POINTS
    elif return_12_1 > 0.20:
        pts = 3.0
    elif return_12_1 > 0.0:
        pts = 2.0
    elif return_12_1 > -0.10:
        pts = 1.0
    else:
        pts = 0.0

    return pts, {
        "return_12_1": round(return_12_1, 4),
        "near_anchor_date": near.date,
        "near_anchor_price": near.close,
        "far_anchor_date": far.date,
        "far_anchor_price": far.close,
        "points": pts,
    }, None


def _find_price_near(prices_asc: list[Any], target: date) -> Any | None:
    """Return the price row closest to `target` within ±MOM_TOLERANCE_DAYS.

    Caller uses this to find approximations to "13 months ago" and "1 month
    ago" since we only have weekly bars.
    """
    best: Any = None
    best_gap: int | None = None
    for p in prices_asc:
        if p.close is None:
            continue
        gap = abs((p.date - target).days)
        if gap > MOM_TOLERANCE_DAYS:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = p, gap
    return best


# ── 2. George-Hwang 52-week-high proximity ─────────────────────────────────


def _compute_52w_high(prices_asc: list[Any]) -> tuple[float, dict[str, Any]]:
    most_recent = prices_asc[-1]
    today = most_recent.date
    cutoff = today - timedelta(days=370)
    last_year = [p for p in prices_asc if p.date >= cutoff and p.close is not None]
    if not last_year:
        return 0.0, {
            "high_52w": None, "current_price": most_recent.close,
            "pct_from_high": None, "points": 0.0,
        }

    high = max(p.close for p in last_year)
    if not high or most_recent.close is None:
        return 0.0, {"high_52w": high, "current_price": most_recent.close, "points": 0.0}

    pct_from_high = (high - most_recent.close) / high
    if pct_from_high <= NEAR_HIGH_BAND_TIGHT:
        pts = NEAR_HIGH_MAX_POINTS
    elif pct_from_high <= NEAR_HIGH_BAND_MID:
        pts = 2.0
    elif pct_from_high <= NEAR_HIGH_BAND_LOOSE:
        pts = 1.0
    else:
        pts = 0.0

    return pts, {
        "high_52w": high,
        "current_price": most_recent.close,
        "pct_from_high": round(pct_from_high, 4),
        "near_high_band": (
            "within_5pct" if pct_from_high <= NEAR_HIGH_BAND_TIGHT
            else "within_10pct" if pct_from_high <= NEAR_HIGH_BAND_MID
            else "within_20pct" if pct_from_high <= NEAR_HIGH_BAND_LOOSE
            else "below_20pct"
        ),
        "points": pts,
    }


# ── 3. Bernard-Thomas PEAD ─────────────────────────────────────────────────


def _compute_pead(reader: Any) -> tuple[float, dict[str, Any], str | None]:
    """Two consecutive positive EPS surprises = positive PEAD; both negative
    = mean-reversion candidate (low score). We require BOTH most-recent
    REPORTED rows (those with non-None eps_surprise_pct) — future-quarter
    estimate-only rows are skipped.
    """
    rows = reader.earnings_history(last_n=8)
    reported = [r for r in rows if r.eps_surprise_pct is not None]
    if len(reported) < 2:
        return 0.0, {
            "reported_count": len(reported),
            "last_two_surprises": [r.eps_surprise_pct for r in reported[:2]],
            "pead_signal": None,
            "points": 0.0,
        }, f"PEAD: only {len(reported)} reported earnings rows"

    last_two = reported[:2]    # earnings_history returns most-recent-first
    s1, s2 = last_two[0].eps_surprise_pct, last_two[1].eps_surprise_pct

    if s1 > 0 and s2 > 0:
        pts = PEAD_MAX_POINTS
        sig = "positive_drift"
    elif s1 > 0 and s2 <= 0:
        pts = 1.5
        sig = "mixed_recent_positive"
    elif s1 <= 0 and s2 > 0:
        pts = 1.0
        sig = "mixed_recent_negative"
    else:
        pts = 0.0
        sig = "negative_drift"

    return pts, {
        "reported_count": len(reported),
        "last_two_surprises": [s1, s2],
        "pead_signal": sig,
        "points": pts,
    }, None
