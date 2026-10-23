"""Self-computed beta from PriceHistory regression vs SPY benchmark.

ADR-033 §1.2 compute-don't-pull invariant: yfinance.info.beta is a
pre-computed value using their proprietary methodology (likely 5-year
monthly returns vs S&P 500). We compute our own beta from raw
PriceHistory using the standard CAPM regression:

    β = Cov(r_stock, r_market) / Var(r_market)

where r_t = (P_t − P_{t-1}) / P_{t-1} (simple returns).

Architectural notes:
  - PriceHistory stores weekly close prices (verified: ~52 rows/year
    per ticker; HIMS 349 rows over 6.7yr ≈ 1.0/week)
  - Benchmark: SPY (S&P 500 ETF). SPY is an SEC-registered fund so
    has a CIK, but its DAILY/WEEKLY market prices are not in SEC
    filings — Tier 3 API fetch per ADR-033 §1.1
  - Window: 5 years (matches yfinance methodology) with fallback to
    available history for recent IPOs (FIG ~2yr, INTA ~5yr)
  - Minimum: 52 weekly observations (~1 year) before computing —
    below that the beta estimate is noise

Honest undefined-ness: when stock has <52 weekly observations OR
market data is missing for the period, beta = None (no fabrication).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from data.models.schema import Company, PriceHistory

logger = logging.getLogger(__name__)

MIN_OBSERVATIONS = 52       # one year of weekly returns
DEFAULT_WINDOW_YEARS = 5    # matches yfinance convention


@dataclass
class BetaResult:
    """Self-computed beta + audit trail."""
    ticker: str
    beta: float | None
    n_observations: int
    window_start: date | None
    window_end: date | None
    stock_volatility: float | None    # annualised σ of r_stock
    market_volatility: float | None   # annualised σ of r_market
    correlation: float | None         # ρ(stock, market)
    r_squared: float | None           # ρ²
    method: str = "sec_derived_from_price_history_vs_spy"
    benchmark: str = "SPY"
    note: str = ""


# ── Statistics primitives ─────────────────────────────────────────────────


def _pct_returns(prices: list[float]) -> list[float]:
    """Simple period-over-period returns. prices[0] is oldest."""
    return [
        (prices[i] - prices[i - 1]) / prices[i - 1]
        for i in range(1, len(prices))
        if prices[i - 1] > 0
    ]


def _covariance(xs: list[float], ys: list[float]) -> float:
    """Sample covariance (n−1 divisor)."""
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)


def _variance(xs: list[float]) -> float:
    """Sample variance (n−1 divisor)."""
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


# ── SPY benchmark fetch ──────────────────────────────────────────────────


def ensure_spy_price_history(session: Session, force: bool = False) -> int:
    """Ensure SPY weekly price history is present in PriceHistory.

    Per ADR-033 §1.1, market prices are Tier 3 (API-fallback). We pull
    SPY weekly close from yfinance ONCE and persist to PriceHistory.
    SPY is an SEC-registered ETF so we use ticker 'SPY' with a synthetic
    Company row.

    Returns the number of PriceHistory rows in the DB for SPY post-fetch.
    Set `force=True` to refetch even when SPY rows already exist.
    """
    spy = session.execute(
        select(Company).where(Company.ticker == "SPY")
    ).scalar_one_or_none()
    if spy is None:
        spy = Company(
            ticker="SPY",
            name="SPDR S&P 500 ETF Trust",
            cik="0000884394",   # SPY's SEC CIK
            exchange="NYQ",
            sector="ETF",
            industry="Exchange Traded Fund",
            sector_source="manual",
        )
        session.add(spy)
        session.commit()

    if not force:
        from sqlalchemy import func
        n_existing = session.execute(
            select(func.count(PriceHistory.id)).where(
                PriceHistory.company_id == spy.id
            )
        ).scalar() or 0
        if n_existing > 0:
            return n_existing

    # Fetch via yfinance — the canonical Tier-3 fallback for price data
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(f"yfinance not installed: {exc}") from exc

    ticker_obj = yf.Ticker("SPY")
    # 10 years weekly — covers any 5yr window for tickers in our universe
    hist = ticker_obj.history(period="10y", interval="1wk", auto_adjust=False)
    if hist is None or len(hist) == 0:
        raise RuntimeError("yfinance returned no SPY history")

    rows_added = 0
    for ts, row in hist.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        # Skip if already present
        existing = session.execute(
            select(PriceHistory).where(
                PriceHistory.company_id == spy.id,
                PriceHistory.date == d,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(PriceHistory(
            company_id=spy.id,
            date=d,
            open=float(row.get("Open", 0)) or None,
            high=float(row.get("High", 0)) or None,
            low=float(row.get("Low", 0)) or None,
            close=float(row.get("Close", 0)) or None,
            adj_close=float(row.get("Adj Close", row.get("Close", 0))) or None,
            volume=int(row.get("Volume", 0) or 0) or None,
            source="yfinance",
        ))
        rows_added += 1
    session.commit()
    return rows_added


# ── Beta computation ─────────────────────────────────────────────────────


def compute_beta_for_ticker(
    session: Session,
    ticker: str,
    window_years: int = DEFAULT_WINDOW_YEARS,
) -> BetaResult:
    """Compute beta from PriceHistory regression vs SPY.

    Honest behaviour:
      - If <MIN_OBSERVATIONS weekly observations available → beta = None
      - If SPY history doesn't cover the stock's window → beta = None
      - All numeric outputs (volatility, correlation, R²) follow the
        same None-when-undefined convention
    """
    c = session.execute(
        select(Company).where(Company.ticker == ticker.upper())
    ).scalar_one_or_none()
    if c is None:
        return BetaResult(
            ticker=ticker.upper(),
            beta=None, n_observations=0,
            window_start=None, window_end=None,
            stock_volatility=None, market_volatility=None,
            correlation=None, r_squared=None,
            note=f"no Company row for {ticker}",
        )

    spy = session.execute(
        select(Company).where(Company.ticker == "SPY")
    ).scalar_one_or_none()
    if spy is None:
        return BetaResult(
            ticker=ticker.upper(),
            beta=None, n_observations=0,
            window_start=None, window_end=None,
            stock_volatility=None, market_volatility=None,
            correlation=None, r_squared=None,
            note="SPY benchmark not in DB — call ensure_spy_price_history first",
        )

    # Window: last `window_years` years up to most recent stock observation
    latest_stock = session.execute(
        select(PriceHistory)
        .where(PriceHistory.company_id == c.id)
        .order_by(desc(PriceHistory.date))
        .limit(1)
    ).scalar_one_or_none()
    if latest_stock is None:
        return BetaResult(
            ticker=ticker.upper(),
            beta=None, n_observations=0,
            window_start=None, window_end=None,
            stock_volatility=None, market_volatility=None,
            correlation=None, r_squared=None,
            note="no price history for ticker",
        )

    window_end = latest_stock.date
    window_start = window_end - timedelta(days=window_years * 365)

    # Pull aligned weekly prices for stock + SPY
    stock_rows = session.execute(
        select(PriceHistory.date, PriceHistory.adj_close)
        .where(
            PriceHistory.company_id == c.id,
            PriceHistory.date >= window_start,
            PriceHistory.date <= window_end,
        )
        .order_by(PriceHistory.date)
    ).all()
    spy_rows = session.execute(
        select(PriceHistory.date, PriceHistory.adj_close)
        .where(
            PriceHistory.company_id == spy.id,
            PriceHistory.date >= window_start,
            PriceHistory.date <= window_end,
        )
        .order_by(PriceHistory.date)
    ).all()

    # Align by date — only keep dates present in BOTH series
    spy_by_date = {d: p for d, p in spy_rows if p is not None and p > 0}
    stock_prices: list[float] = []
    market_prices: list[float] = []
    actual_dates: list[date] = []
    for d, p in stock_rows:
        if p is None or p <= 0:
            continue
        # Find nearest SPY observation within 3 days (handles weekly-alignment slack)
        for delta in (0, 1, -1, 2, -2, 3, -3):
            check_date = d + timedelta(days=delta)
            if check_date in spy_by_date:
                stock_prices.append(p)
                market_prices.append(spy_by_date[check_date])
                actual_dates.append(d)
                break

    if len(stock_prices) < MIN_OBSERVATIONS:
        return BetaResult(
            ticker=ticker.upper(),
            beta=None, n_observations=len(stock_prices),
            window_start=actual_dates[0] if actual_dates else None,
            window_end=actual_dates[-1] if actual_dates else None,
            stock_volatility=None, market_volatility=None,
            correlation=None, r_squared=None,
            note=(
                f"insufficient observations: {len(stock_prices)} < "
                f"{MIN_OBSERVATIONS} ({window_years}yr window)"
            ),
        )

    r_stock = _pct_returns(stock_prices)
    r_market = _pct_returns(market_prices)
    # _pct_returns drops the first observation; align lengths
    n = min(len(r_stock), len(r_market))
    r_stock = r_stock[:n]
    r_market = r_market[:n]

    cov = _covariance(r_stock, r_market)
    var_m = _variance(r_market)
    var_s = _variance(r_stock)
    if var_m == 0:
        beta = None
    else:
        beta = cov / var_m

    # Volatility (annualised, weekly returns → ×√52)
    ann_factor = math.sqrt(52)
    stock_vol = math.sqrt(var_s) * ann_factor if var_s > 0 else None
    market_vol = math.sqrt(var_m) * ann_factor if var_m > 0 else None
    correlation = (
        cov / math.sqrt(var_s * var_m)
        if (var_s > 0 and var_m > 0)
        else None
    )
    r_squared = correlation ** 2 if correlation is not None else None

    return BetaResult(
        ticker=ticker.upper(),
        beta=beta,
        n_observations=n,
        window_start=actual_dates[0],
        window_end=actual_dates[-1],
        stock_volatility=stock_vol,
        market_volatility=market_vol,
        correlation=correlation,
        r_squared=r_squared,
    )


def persist_beta(session: Session, result: BetaResult) -> None:
    """Persist self-computed beta to Company.beta, overwriting any
    yfinance-pulled value. Records `beta_fetched_at` timestamp.

    Per ADR-033 §1.2 compute-don't-pull: the self-computed value is
    canonical when available; None values are preserved (no fallback
    to yfinance.info.beta — honesty invariant).
    """
    from datetime import datetime
    c = session.execute(
        select(Company).where(Company.ticker == result.ticker)
    ).scalar_one()
    from config.source_tags import SELF_COMPUTED as _SRC_SC
    c.beta = result.beta
    c.beta_source = _SRC_SC if result.beta is not None else None
    if hasattr(c, "beta_fetched_at"):
        c.beta_fetched_at = datetime.utcnow()
    session.commit()
