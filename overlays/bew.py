"""
BEW — Bessembinder Extreme Winners.

Bessembinder (2018, JFE ★★★) and Bessembinder et al. (2019, JFE ★★★)
documented that ~4% of stocks account for nearly all net stock-market
wealth creation since 1926. Ex-ante identification of "extreme winner"
candidates uses 7 binary checks; 6+ = STRONG candidate.

  A. Small at acquisition (market_cap < $2B)
  B. High idiosyncratic volatility (>30% annualised)
  C. Positive return skewness over 3 years
  D. Sector ∈ Bessembinder growth sectors (tech / healthcare / consumer
     discretionary / industrials)
  E. Not cheap (EV/Rev > sector median — winners trade rich)
  F. Long runway (TAM / revenue > 20x)
  G. Innovation compounding (F3 ≥ 7 OR avg GM expansion ≥ 200bps/yr)

Where data isn't available:
  - Idiosyncratic vol: computable from price_history; we compute it here
    as the std of weekly returns over the last year (rough proxy)
  - Skewness: computable from price_history; we compute weekly-return
    skewness over 3 years (or as much history as we have)
  - Sector median EV/Rev: NOT warehoused — flagged as data_gap
  - TAM: NOT warehoused — flagged as data_gap

Per CLAUDE.md the overlay never auto-runs — only after explicit
confirmation of a BEW-1..3,5 trigger.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any

from config.constants import BESSEMBINDER_GROWTH_SECTORS


# Thresholds
SMALL_CAP_THRESHOLD = 2_000_000_000        # <$2B at acquisition
IDIO_VOL_THRESHOLD = 0.30                  # >30% annualised
GM_EXPANSION_TARGET_BPS = 200.0            # ≥200bps/yr GM expansion
F3_INNOVATION_THRESHOLD = 7.0
TAM_REVENUE_RATIO_MIN = 20.0


async def run_bew(
    ticker: str,
    *,
    reader: Any,
    f3_score: float | None = None,
) -> dict[str, Any]:
    """Compute Bessembinder extreme-winner candidacy for `ticker`.

    `f3_score` may be passed by the caller (when run inline after a dive);
    if None, we look up the most-recent persisted F3 score.
    """
    company = reader.company_or_none()
    annuals = reader.annuals(last_n=6)
    if not company:
        return {"ok": False, "reason": "no Company row"}

    market_cap = company.market_cap_usd
    sector = (company.sector or "").lower()
    revenue = annuals[0].revenue if annuals else None

    # Resolve F3 from DB if not provided
    if f3_score is None:
        f3_score = _lookup_latest_f_score(ticker, "f3_score")

    # ── Compute idiosyncratic volatility (proxy: stdev of weekly returns) ─
    idio_vol, idio_vol_signals = _compute_idio_vol(reader)
    skewness, skewness_signals = _compute_skewness(reader)
    avg_gm_expansion_bps = _compute_avg_gm_expansion(annuals)

    data_gaps: list[str] = []

    # ── 7 binary checks ─────────────────────────────────────────────────
    a_small = (
        market_cap is not None and market_cap < SMALL_CAP_THRESHOLD
    )
    b_high_idio_vol = (
        idio_vol is not None and idio_vol > IDIO_VOL_THRESHOLD
    )
    if idio_vol is None:
        data_gaps.append("Insufficient price history to compute idiosyncratic vol")
    c_positive_skewness = (
        skewness is not None and skewness > 0
    )
    if skewness is None:
        data_gaps.append("Insufficient price history to compute return skewness")
    d_growth_sector = sector in BESSEMBINDER_GROWTH_SECTORS

    # E. Not cheap — sector median EV/Rev not warehoused. Use absolute proxy:
    # current EV/Rev > 5x is "not cheap" by rough standard.
    e_not_cheap: bool | None = None
    current_ev_revenue = _current_ev_revenue(annuals[0] if annuals else None, company)
    if current_ev_revenue is not None:
        e_not_cheap = current_ev_revenue > 5.0
        data_gaps.append(
            "Sector median EV/Rev not warehoused — using absolute >5x proxy"
        )
    else:
        data_gaps.append("Cannot compute EV/Revenue — missing market_cap or revenue")

    # F. Long runway — TAM not warehoused.
    f_long_runway: bool | None = None
    data_gaps.append("TAM estimate not warehoused — runway check skipped")

    # G. Innovation compounding
    g_innovation = (
        (f3_score is not None and f3_score >= F3_INNOVATION_THRESHOLD)
        or (avg_gm_expansion_bps is not None and avg_gm_expansion_bps >= GM_EXPANSION_TARGET_BPS)
    )

    checks = {
        "A_small_at_acquisition": a_small,
        "B_high_idio_vol": b_high_idio_vol,
        "C_positive_skewness": c_positive_skewness,
        "D_growth_industry": d_growth_sector,
        "E_not_cheap": e_not_cheap,
        "F_long_runway": f_long_runway,
        "G_innovation_compounding": g_innovation,
    }

    n_evaluable = sum(1 for v in checks.values() if v is not None)
    score = sum(1 for v in checks.values() if v is True)

    if score >= 6:
        verdict = "EXTREME_WINNER_CANDIDATE"
        hold_period = "5–15 years minimum"
        concentration_note = (
            "Concentration is necessary — 2% position in 10x = 0.2% portfolio return. "
            "BEW candidates require sized positions to matter."
        )
    elif score >= 4:
        verdict = "moderate_winner_candidate"
        hold_period = "3–7 years"
        concentration_note = "Moderate evidence; consider as a satellite position"
    else:
        verdict = "no_winner_pattern"
        hold_period = "n/a"
        concentration_note = "Bessembinder pattern absent"

    return {
        "ok": True,
        "ticker": ticker,
        "checks": checks,
        "n_checks_evaluable": n_evaluable,
        "score": score,
        "verdict": verdict,
        "hold_period_recommendation": hold_period,
        "concentration_note": concentration_note,
        "inputs": {
            "market_cap_usd": market_cap,
            "sector": sector,
            "revenue": revenue,
            "f3_score": f3_score,
            "idio_vol": round(idio_vol, 4) if idio_vol is not None else None,
            "skewness": round(skewness, 4) if skewness is not None else None,
            "avg_gm_expansion_bps": (
                round(avg_gm_expansion_bps, 1) if avg_gm_expansion_bps is not None else None
            ),
            "current_ev_revenue": (
                round(current_ev_revenue, 3) if current_ev_revenue is not None else None
            ),
            "idio_vol_method": idio_vol_signals,
            "skewness_method": skewness_signals,
        },
        "data_gaps": data_gaps,
        "academic_anchors": [
            "Bessembinder (2018) JFE ★★★",
            "Bessembinder et al. (2019) JFE ★★★",
        ],
    }


# ── Helper computations ──────────────────────────────────────────────────


def _compute_idio_vol(reader: Any) -> tuple[float | None, dict[str, Any]]:
    """Annualised stdev of weekly returns over last 52 weeks.

    True idiosyncratic vol regresses returns against market factor; we use
    raw return-stdev as a proxy (the correlation with idio-vol is high in
    practice for the 6+ check this feeds).
    """
    prices = reader.price_history(within_days=400) if hasattr(reader, "price_history") else []
    prices_asc = sorted(prices, key=lambda p: p.date)
    closes = [p.close for p in prices_asc if p.close]
    if len(closes) < 30:
        return None, {"method": "weekly stdev × √52", "n_weeks": len(closes)}

    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if len(returns) < 20:
        return None, {"method": "weekly stdev × √52", "n_returns": len(returns)}

    weekly_vol = statistics.pstdev(returns)
    annualised = weekly_vol * math.sqrt(52)
    return annualised, {
        "method": "weekly stdev × √52 (raw, not market-adjusted)",
        "n_returns": len(returns),
        "weekly_vol": round(weekly_vol, 4),
    }


def _compute_skewness(reader: Any) -> tuple[float | None, dict[str, Any]]:
    """Sample skewness of weekly returns over last 3 years."""
    prices = reader.price_history(within_days=3 * 370) if hasattr(reader, "price_history") else []
    prices_asc = sorted(prices, key=lambda p: p.date)
    closes = [p.close for p in prices_asc if p.close]
    if len(closes) < 50:
        return None, {"method": "Pearson skewness, 3yr weekly", "n_weeks": len(closes)}

    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if len(returns) < 50:
        return None, {"method": "Pearson skewness, 3yr weekly", "n_returns": len(returns)}

    mean = statistics.mean(returns)
    sd = statistics.pstdev(returns)
    if sd == 0:
        return 0.0, {"method": "constant returns", "n_returns": len(returns)}

    n = len(returns)
    third_moment = sum((r - mean) ** 3 for r in returns) / n
    skew = third_moment / (sd ** 3)
    return skew, {
        "method": "Pearson moment-coefficient, 3yr weekly",
        "n_returns": n,
        "mean_weekly_return": round(mean, 4),
    }


def _compute_avg_gm_expansion(annuals: list[Any]) -> float | None:
    """Average YoY change in gross_margin in basis points."""
    gm = [a.gross_margin for a in annuals if a.gross_margin is not None]
    if len(gm) < 2:
        return None
    deltas_bps = [
        (gm[i] - gm[i + 1]) * 10000.0    # newest-first → newer minus older
        for i in range(len(gm) - 1)
    ]
    return sum(deltas_bps) / len(deltas_bps) if deltas_bps else None


def _current_ev_revenue(latest_annual: Any, company: Any) -> float | None:
    if not latest_annual or not company or not company.market_cap_usd:
        return None
    if not latest_annual.revenue:
        return None
    debt = latest_annual.total_debt or 0.0
    cash = latest_annual.cash_and_equivalents or 0.0
    ev = company.market_cap_usd + debt - cash
    return ev / latest_annual.revenue


def _lookup_latest_f_score(ticker: str, column: str) -> float | None:
    """Read the latest persisted FrameworkScore.{column} for `ticker`."""
    from sqlalchemy import select, desc
    from data.db import get_session
    from data.models.schema import Company, FrameworkScore

    if column not in {f"f{i}_score" for i in range(1, 8)}:
        return None
    with get_session() as s:
        co = s.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if not co:
            return None
        fs = s.execute(
            select(FrameworkScore).where(FrameworkScore.company_id == co.id)
            .order_by(desc(FrameworkScore.run_date))
        ).scalars().first()
        if not fs:
            return None
        return getattr(fs, column, None)
