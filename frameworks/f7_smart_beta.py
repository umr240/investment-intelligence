"""
F7 — Smart Beta Timing (Mode C).

CONTESTED ACADEMIC GROUND. PROJECT_SPEC §F7 / CLAUDE.md require us to
ALWAYS append F7_DISCLAIMER to the result and to weight F7 ≤ 0.10 in any
composite score. F7 is a CHEAPNESS signal — it does not predict moat,
quality, or growth. It only asks "is this stock cheap relative to its
own history?".

Two z-scores combine to a 0-10 score:

  1. EV/Revenue z-score                                       5 points
     z = (current_ev_revenue - mean(10yr)) / std(10yr)
     z < -1.0 → historically cheap → 5 pts
     z >  1.0 → historically expensive → 0 pts

  2. P/B z-score                                              5 points
     Same scale as EV/Revenue.

Historical EV/Revenue and P/B are reconstructed per-fiscal-year by
joining `Financial` rows (revenue, total_debt, cash, total_equity,
shares_outstanding) with `PriceHistory` (close near period_end_date).
That works back to 2015-2016 for both NVDA and AAPL given our weekly-bar
fetch depth.

InsufficientHistoryError when <5 fiscal years of valid annuals — the
literature reports z-scores against 10-20yr histories; <5 is too noisy.
F7's auto-skip on recent IPOs is the correct behaviour per CLAUDE.md
("F7 ... auto-skip if the company hasn't been listed long enough").
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from config.constants import DEFAULT_HISTORY_YEARS, F7_DISCLAIMER
from data.share_basis import shares_on_current_basis
from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
)


DATA_REQUIREMENT = DataRequirement(
    # Must be >= MIN_HISTORY_YEARS, with headroom (ADR-030-A2). The SEC adapter
    # passes this straight to the year-coverage gate, whose window is anchored on
    # the current calendar year — so a December filer mid-year spends one slot on
    # a fiscal year SEC cannot have yet. Declaring exactly 10 left CSGP asking
    # for FY2026 and never fetching FY2016.
    annual_years=DEFAULT_HISTORY_YEARS,
    min_annual_years=10,                 # == MIN_HISTORY_YEARS, asserted by test
    price_history_years=DEFAULT_HISTORY_YEARS,
)


# ── Tunables ──────────────────────────────────────────────────────────────

# ADR-030 Amendment A1 — raised 5 → 10, matching the requirement this file
# already cited ("spec wants 10"). Scoring a z-score the module itself calls
# "too noisy" and then feeding it into a weighted composite is the failure
# ADR-030 exists to prevent, one framework over.
#
# This marks F7 unfeasible for most of the current universe. That is the
# intended outcome, not a side effect: the alternative is a STRONG FIT derived
# from 6 datapoints spanning a business-model change (BONEX.ST: EV/Rev z=-0.757
# across a −54.5% → +23.6% margin transition).
MIN_HISTORY_YEARS = 10           # per PROJECT_SPEC §F7; <10 = unfeasible
PRICE_LOOKUP_TOLERANCE_DAYS = 21 # nearest weekly bar to period_end_date

EV_REV_MAX = 5.0
PB_MAX = 5.0


async def score_f7(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F7 — Smart Beta Timing. ALWAYS appends F7_DISCLAIMER."""
    annuals = reader.annuals(last_n=12)
    valid_annuals = [
        a for a in annuals
        if a.revenue and a.total_equity is not None
        and a.shares_outstanding and a.period_end_date
    ]
    if len(valid_annuals) < MIN_HISTORY_YEARS:
        raise InsufficientHistoryError(
            "F7", needed=MIN_HISTORY_YEARS,
            got=len(valid_annuals), period_kind="annual",
        )

    # ── Split-basis gate ──────────────────────────────────────────────────
    # Prices are split-adjusted throughout, so share counts must be on one basis
    # too. `_construct_valuation_history` restates each EDGAR count using the
    # stored basis reference; years whose basis cannot be established are
    # dropped, and z-scoring a window thinned that way measures the split rather
    # than the valuation (CSGP: EV/Revenue 0.101 and -0.184 for FY2015-18,
    # scored 8.0/10 strong_fit). Gate on how many years actually resolve.
    resolvable = [
        a for a in valid_annuals
        if shares_on_current_basis(
            a.shares_outstanding, getattr(a, "share_split_factor", None)
        ) is not None
    ]
    if len(resolvable) < MIN_HISTORY_YEARS:
        split_year, _ = _detect_share_split(valid_annuals)
        detail = (
            f"share count changes basis around FY{split_year} and the split "
            "reference is missing or ambiguous"
            if split_year is not None else
            "split basis unresolved for one or more years"
        )
        raise InsufficientHistoryError(
            "F7", needed=MIN_HISTORY_YEARS, got=len(resolvable),
            period_kind=f"single-basis annual ({detail})",
        )
    valid_annuals = resolvable

    # ── ADR-030 Amendment A1: regime gate ─────────────────────────────────
    # A z-score assumes the window describes ONE business. When the operating
    # margin crosses from loss to profit, EV/Revenue compresses because revenue
    # grew and P/B compresses because retained earnings accumulated — both drift
    # negative REGARDLESS of price. The resulting "cheap" reading measures
    # elapsed revenue, not valuation, and is a structurally guaranteed false
    # positive for every post-inflection filer.
    #
    # Uses the same shared test as the Greenwald ladder (valuation/regime.py) so
    # the two cannot diverge again — before this, one module refused to average
    # across BONEX.ST's regime break while this one averaged across it and
    # returned STRONG FIT, in the same run.
    from valuation.regime import INFLECTING, assess_margin_regime

    margins = [
        (a.operating_income / a.revenue)
        if (a.revenue and a.operating_income is not None) else None
        for a in reversed(valid_annuals)          # reader is newest-first
    ]
    regime, regime_reason = assess_margin_regime(margins)
    if regime == INFLECTING:
        raise InsufficientHistoryError(
            "F7", needed=MIN_HISTORY_YEARS, got=len(valid_annuals),
            period_kind=f"regime-stable annual ({regime_reason})",
        )

    prices = reader.price_history(within_days=365 * 12)
    if not prices:
        raise InsufficientHistoryError(
            "F7", needed=52, got=0, period_kind="weekly_price",
        )

    company = reader.company_or_none()

    signals: dict[str, Any] = {}
    data_gaps: list[str] = []

    history_pairs = _construct_valuation_history(valid_annuals, prices)
    ev_rev_history = [p["ev_revenue"] for p in history_pairs if p["ev_revenue"] is not None]
    pb_history = [p["pb"] for p in history_pairs if p["pb"] is not None]

    if len(ev_rev_history) < MIN_HISTORY_YEARS:
        data_gaps.append(
            f"{ticker}: F7 EV/Revenue history — only {len(ev_rev_history)} valid years; "
            "z-score requires more"
        )

    # Current valuation snapshot
    current_ev_revenue, current_ev_revenue_signals = _current_ev_revenue(
        valid_annuals[0], company, prices,
    )
    current_pb, current_pb_signals = _current_pb(
        valid_annuals[0], company, prices,
    )

    # ── 1. EV/Revenue z-score ────────────────────────────────────────────
    ev_pts, ev_signals, ev_gap = _score_z(
        current=current_ev_revenue,
        history=ev_rev_history,
        max_pts=EV_REV_MAX,
        signal_name="ev_revenue",
        ticker=ticker,
    )
    ev_signals["current"] = current_ev_revenue
    ev_signals["current_components"] = current_ev_revenue_signals
    ev_signals["history"] = [round(v, 3) for v in ev_rev_history]
    signals["ev_revenue_z"] = ev_signals
    if ev_gap:
        data_gaps.append(ev_gap)

    # ── 2. P/B z-score ───────────────────────────────────────────────────
    pb_pts, pb_signals, pb_gap = _score_z(
        current=current_pb,
        history=pb_history,
        max_pts=PB_MAX,
        signal_name="pb",
        ticker=ticker,
    )
    pb_signals["current"] = current_pb
    pb_signals["current_components"] = current_pb_signals
    pb_signals["history"] = [round(v, 3) for v in pb_history]
    signals["pb_z"] = pb_signals
    if pb_gap:
        data_gaps.append(pb_gap)

    score = round(ev_pts + pb_pts, 2)
    score = min(max(score, 0.0), 10.0)
    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    return FrameworkResult(
        framework="F7",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
        notes=F7_DISCLAIMER,
    )


# Year-over-year share-count ratio that only a split (or reverse split) explains.
# Organic dilution and buybacks move share counts by tens of percent a year; the
# smallest common split is 2:1. 1.8 sits between the two.
SPLIT_RATIO_THRESHOLD = 1.8


def _detect_share_split(annuals: list[Any]) -> tuple[int | None, int]:
    """(fiscal year of the first split-sized jump, longest split-free run).

    The run length is what the framework can actually use, so it is what the
    unfeasible reason should report — a 12-year window broken by one split
    offers no more than its longest clean segment.
    """
    ordered = sorted(
        (a for a in annuals if a.shares_outstanding),
        key=lambda a: a.fiscal_year,
    )
    if not ordered:
        return None, 0

    first_split: int | None = None
    longest = run = 1
    for prev, curr in zip(ordered, ordered[1:], strict=False):
        a, b = prev.shares_outstanding, curr.shares_outstanding
        if a and b and max(a, b) / min(a, b) >= SPLIT_RATIO_THRESHOLD:
            if first_split is None:
                first_split = int(curr.fiscal_year)
            run = 1
        else:
            run += 1
        longest = max(longest, run)
    return first_split, longest


# ── Valuation construction ─────────────────────────────────────────────────


def _construct_valuation_history(
    annuals: list[Any], prices: list[Any],
) -> list[dict[str, Any]]:
    """For each annual fiscal year, compute EV/Revenue and P/B as-of period_end.

    EV ≈ market_cap + total_debt - cash_and_equivalents
    market_cap ≈ price_at_period_end × shares_outstanding
    P/B = market_cap / total_equity
    """
    out: list[dict[str, Any]] = []
    for a in annuals:
        if not a.period_end_date or not a.shares_outstanding:
            continue
        price = _price_near(prices, a.period_end_date)
        if price is None or price.close is None:
            continue
        # Prices are split-adjusted throughout, so the count must be too. EDGAR
        # supplies the number; the stored basis reference only says whether the
        # as-filed value predates a split (data/share_basis.py).
        shares = shares_on_current_basis(
            a.shares_outstanding, getattr(a, "share_split_factor", None)
        )
        if shares is None:
            continue
        mc = price.close * shares
        debt = a.total_debt or 0.0
        cash = a.cash_and_equivalents or 0.0
        ev = mc + debt - cash
        ev_rev = (ev / a.revenue) if a.revenue else None
        pb = (mc / a.total_equity) if a.total_equity else None
        out.append({
            "fiscal_year": a.fiscal_year,
            "period_end_date": a.period_end_date,
            "price": price.close,
            "shares": shares,
            "market_cap": mc,
            "ev": ev,
            "revenue": a.revenue,
            "ev_revenue": ev_rev,
            "total_equity": a.total_equity,
            "pb": pb,
        })
    return out


def _price_near(prices: list[Any], target: date) -> Any | None:
    """Closest weekly bar to `target` within ±PRICE_LOOKUP_TOLERANCE_DAYS."""
    best = None
    best_gap: int | None = None
    for p in prices:
        if not p.date:
            continue
        gap = abs((p.date - target).days)
        if gap > PRICE_LOOKUP_TOLERANCE_DAYS:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = p, gap
    return best


def _current_ev_revenue(
    latest_annual: Any, company: Any, prices: list[Any],
) -> tuple[float | None, dict[str, Any]]:
    """Build current EV/Revenue from yfinance market_cap + latest annual debt/cash/revenue.

    Uses Company.market_cap_usd (today's yfinance value) over latest annual
    revenue. This pairs current price with TRAILING revenue — a conservative
    cheapness reading (using TTM revenue would be slightly fresher; the
    spec doesn't require TTM here).
    """
    if not company or not company.market_cap_usd or not latest_annual.revenue:
        return None, {}
    mc = company.market_cap_usd
    debt = latest_annual.total_debt or 0.0
    cash = latest_annual.cash_and_equivalents or 0.0
    ev = mc + debt - cash
    ev_rev = ev / latest_annual.revenue
    return ev_rev, {
        "market_cap": mc,
        "total_debt": debt,
        "cash": cash,
        "ev": ev,
        "revenue": latest_annual.revenue,
        "ev_revenue": round(ev_rev, 3),
    }


def _current_pb(
    latest_annual: Any, company: Any, prices: list[Any],
) -> tuple[float | None, dict[str, Any]]:
    """Build current P/B = market_cap / total_equity using latest annual book."""
    if not company or not company.market_cap_usd or not latest_annual.total_equity:
        return None, {}
    pb = company.market_cap_usd / latest_annual.total_equity
    return pb, {
        "market_cap": company.market_cap_usd,
        "total_equity": latest_annual.total_equity,
        "pb": round(pb, 3),
    }


# ── z-score scoring ────────────────────────────────────────────────────────


def _score_z(
    *,
    current: float | None,
    history: list[float],
    max_pts: float,
    signal_name: str,
    ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Compute z-score and convert to bands.

    z < -1.0 = historically cheap → full points
    z >  1.0 = historically expensive → zero points
    """
    if current is None:
        return 0.0, {"z": None, "points": 0.0}, \
               f"{ticker}: F7 {signal_name} — no current value"
    if len(history) < MIN_HISTORY_YEARS:
        return 0.0, {
            "z": None,
            "n_history": len(history),
            "min_required": MIN_HISTORY_YEARS,
            "points": 0.0,
        }, f"{ticker}: F7 {signal_name} — only {len(history)} historical points"

    mu = statistics.mean(history)
    sigma = statistics.pstdev(history)
    if sigma == 0:
        return 0.0, {
            "z": None,
            "mean": round(mu, 3),
            "stdev": 0.0,
            "n_history": len(history),
            "points": 0.0,
        }, f"{ticker}: F7 {signal_name} — historical stdev=0 (constant series)"

    z = (current - mu) / sigma

    if z <= -1.0:
        pts = max_pts
        band = "very_cheap"
    elif z <= -0.5:
        pts = 0.8 * max_pts
        band = "cheap"
    elif z <= 0.0:
        pts = 0.6 * max_pts
        band = "below_average"
    elif z <= 0.5:
        pts = 0.4 * max_pts
        band = "above_average"
    elif z <= 1.0:
        pts = 0.2 * max_pts
        band = "expensive"
    else:
        pts = 0.0
        band = "very_expensive"

    return pts, {
        "z": round(z, 3),
        "mean": round(mu, 3),
        "stdev": round(sigma, 3),
        "n_history": len(history),
        "band": band,
        "points": round(pts, 2),
    }, None
