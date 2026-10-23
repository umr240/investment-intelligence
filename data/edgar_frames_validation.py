"""
Empirical validator for SEC frames vs companyfacts on off-fiscal-year tickers
(docs/architecture/SCREENER_PIPELINE.md §3, DECISIONS.md DEC-09).

NVDA's fiscal year ends ~Jan 28. Open question: does NVDA's FY2024 revenue
appear under SEC frames `CY2023.json` (because the fiscal year MOSTLY happened
in calendar 2023) or `CY2024.json` (because the period ENDS in early CY2024)?

This module fetches both via frames AND via companyfacts and prints the
divergence so the screener implementor knows what to expect.

Run via:
    python -m data.edgar_frames_validation NVDA
    python -m data.edgar_frames_validation NVDA AAPL COST

Findings should be appended to docs/architecture/DATA_LAYER.md.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from data.edgar_companyfacts import fetch_companyfacts, parse_companyfacts
from data.edgar_frames import (
    FrameEntry,
    fetch_frame,
    latest_complete_calendar_year,
)

logger = logging.getLogger(__name__)


@dataclass
class _ValidationRow:
    ticker: str
    cik: int
    fiscal_year: int                          # company-reported fy
    period_end_date: str                       # canonical
    revenue_companyfacts: float | None
    revenue_frames_cy_match: tuple[str, float] | None    # (matched CY, val)


def _resolve_cik(ticker: str) -> int | None:
    """Cheap CIK lookup via edgartools (no companyfacts download yet)."""
    try:
        from edgar import Company
        from edgar.core import set_identity

        from config.settings import require_edgar_identity
        set_identity(require_edgar_identity())
        c = Company(ticker)
        return int(getattr(c, "cik", 0) or 0)
    except Exception as exc:    # noqa: BLE001
        logger.warning("CIK lookup failed for %s: %s", ticker, exc)
        return None


def _resolve_identity() -> str:
    from config.settings import require_edgar_identity
    return require_edgar_identity()


def validate_ticker(ticker: str) -> list[_ValidationRow]:
    """
    Compare frames vs companyfacts revenue for one ticker across the last 3
    fiscal years. Returns one row per FY showing where the value lives.
    """
    cik = _resolve_cik(ticker)
    if cik is None:
        print(f"[{ticker}] CIK lookup failed; skipping")
        return []

    identity = _resolve_identity()

    # 1. companyfacts — authoritative per-company view
    payload = fetch_companyfacts(cik, identity)
    if not payload:
        print(f"[{ticker}] companyfacts unavailable")
        return []
    cf_rows = parse_companyfacts(ticker, payload, annual_years_limit=3)
    cf_annuals = [r for r in cf_rows if r.period == "annual"]
    if not cf_annuals:
        print(f"[{ticker}] no annual companyfacts rows")
        return []

    # 2. For each FY, look up the revenue value in surrounding frames windows
    rows: list[_ValidationRow] = []
    for cf in cf_annuals:
        fy = cf.fiscal_year
        end = cf.period_end_date
        revenue_cf = cf.revenue
        # Look in 3 candidate frames windows:
        # CY{end.year-1}, CY{end.year}, CY{end.year+1}
        match: tuple[str, float] | None = None
        if end is not None:
            candidates = [
                f"CY{end.year - 1}",
                f"CY{end.year}",
                f"CY{end.year + 1}",
            ]
            for cy_period in candidates:
                frame = fetch_frame("Revenues", cy_period, "USD", identity)
                entry = frame.get(cik)
                if entry and revenue_cf is not None and abs(entry.val - revenue_cf) / max(abs(revenue_cf), 1) < 0.01:
                    match = (cy_period, entry.val)
                    break
                if entry and match is None:
                    # Fallback: nearest match even if values differ
                    match = (cy_period, entry.val)
        rows.append(_ValidationRow(
            ticker=ticker,
            cik=cik,
            fiscal_year=fy,
            period_end_date=str(end) if end else "?",
            revenue_companyfacts=revenue_cf,
            revenue_frames_cy_match=match,
        ))
    return rows


def print_report(rows: list[_ValidationRow]) -> None:
    if not rows:
        return
    cy_now = latest_complete_calendar_year()
    print(f"\n{'=' * 80}")
    print(f"  Empirical: SEC frames vs companyfacts (latest_complete_cy={cy_now})")
    print(f"{'=' * 80}")
    print(
        f"{'TICKER':<8} {'CIK':<10} {'FY':<6} {'PERIOD_END':<12} "
        f"{'REVENUE (CF)':>18} {'FRAMES@CY':<10} {'REVENUE (FR)':>18}"
    )
    for r in rows:
        cy_match = r.revenue_frames_cy_match[0] if r.revenue_frames_cy_match else "—"
        rev_match = (
            f"{r.revenue_frames_cy_match[1]:>18,.0f}"
            if r.revenue_frames_cy_match
            else f"{'—':>18}"
        )
        rev_cf = f"{r.revenue_companyfacts:>18,.0f}" if r.revenue_companyfacts is not None else f"{'—':>18}"
        print(
            f"{r.ticker:<8} {r.cik:<10} {r.fiscal_year:<6} {r.period_end_date:<12} "
            f"{rev_cf} {cy_match:<10} {rev_match}"
        )


def main(tickers: list[str]) -> int:
    if not tickers:
        print(__doc__)
        return 1
    all_rows: list[_ValidationRow] = []
    for t in tickers:
        all_rows.extend(validate_ticker(t.upper()))
    print_report(all_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
