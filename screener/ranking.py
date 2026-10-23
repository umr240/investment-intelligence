"""
Universe-wide ranking helpers (docs/architecture/SCREENER_PIPELINE.md §1 Tiers 5–6).

Decile ranking is keyed on `Financial.period_end_date`'s calendar quarter
(see DECISIONS.md DEC-12) — cross-company comparisons need calendar alignment,
not fiscal alignment.

`decile_rank(values, target)` returns 1–10 where 10 = top decile.
Used as input to:
  G4 (asset growth — top decile = WORST, hard fail)
  G7 (momentum   — bottom decile = WORST, soft fail)
"""
from __future__ import annotations

from datetime import date, timedelta


def decile_rank(values: list[float], target: float) -> int:
    """
    Return 1-10. 10 = target is in the top 10% of values; 1 = bottom 10%.

    `values` is the universe of comparable values (peers).  `target` is the
    individual ticker's value. Returns 5 (median) if `values` is empty.
    """
    if not values:
        return 5
    below = sum(1 for v in values if v < target)
    pct = below / len(values)
    return min(10, max(1, int(pct * 10) + 1))


def compute_asset_growth_deciles(
    asset_growth_yoy: dict[str, float | None],
) -> dict[str, int]:
    """
    Universe-wide asset growth decile rank per ticker.
    Skips tickers with None asset_growth_yoy.
    """
    valid_values = [v for v in asset_growth_yoy.values() if v is not None]
    return {
        ticker: decile_rank(valid_values, growth)
        for ticker, growth in asset_growth_yoy.items()
        if growth is not None
    }


def compute_momentum_deciles(
    twelve_month_returns: dict[str, float | None],
) -> dict[str, int]:
    """Universe-wide 12-month return decile rank."""
    valid_values = [v for v in twelve_month_returns.values() if v is not None]
    return {
        ticker: decile_rank(valid_values, ret)
        for ticker, ret in twelve_month_returns.items()
        if ret is not None
    }


def compute_twelve_month_return(
    ticker: str,
    as_of: date | None = None,
) -> float | None:
    """
    Pull the ticker's price history from the DB and compute the 12-month
    total return ending on `as_of` (default today). Returns None if
    insufficient history.
    """
    from data.reader import CompanyDataReader
    reader = CompanyDataReader(ticker)
    as_of = as_of or date.today()
    rows = reader.price_history(within_days=400)    # buffer for weekend gaps
    if len(rows) < 2:
        return None
    # rows are most-recent-first
    latest = rows[0]
    target = as_of - timedelta(days=365)
    earliest = next((r for r in rows if r.date <= target), None)
    if earliest is None or not earliest.close or not latest.close:
        return None
    return (latest.close / earliest.close) - 1.0


def compute_asset_growth_yoy(ticker: str) -> float | None:
    """YoY asset growth from the most recent 2 annual Financial rows."""
    from data.reader import CompanyDataReader
    reader = CompanyDataReader(ticker)
    annuals = reader.annuals(last_n=2)
    if len(annuals) < 2:
        return None
    cur = annuals[0].total_assets
    prior = annuals[1].total_assets
    if not cur or not prior:
        return None
    return (cur - prior) / prior
