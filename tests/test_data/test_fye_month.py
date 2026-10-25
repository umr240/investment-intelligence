"""Follow-up F4: correct the stored fiscal-year-end month from stored annual periods.

Undived companies kept the month the old raw-month parser wrote (ROST "0201"
stored as 2, KLAC defaulting to 12 for a June year end; author DB 2026-10-25).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from data.fye_month import confirmed_month, plan_fye_month_updates
from data.models.schema import Base, Company, Financial


def _session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _annual(co: int, fy: int, start: str, end: str) -> Financial:
    return Financial(
        company_id=co,
        fiscal_year=fy,
        period="annual",
        period_start_date=date.fromisoformat(start),
        period_end_date=date.fromisoformat(end),
    )


def test_the_latest_annual_period_sets_the_nominal_month() -> None:
    s = _session()
    for i, (t, stored) in enumerate([("ROST", 2), ("KLAC", 12), ("AAPL", 9)], start=1):
        s.add(Company(id=i, ticker=t, name=t, exchange="NASDAQ", fiscal_year_end_month=stored))
    s.add_all([
        _annual(1, 2025, "2024-02-04", "2025-02-01"),  # 52/53-week: nominal January
        _annual(2, 2024, "2023-07-01", "2024-06-30"),
        _annual(2, 2025, "2024-07-01", "2025-06-30"),
        _annual(3, 2025, "2024-09-29", "2025-09-27"),  # already right
        Financial(company_id=3, fiscal_year=2026, period="Q1",
                  period_start_date=date(2025, 9, 28), period_end_date=date(2025, 12, 27)),
    ])  # fmt: skip
    s.commit()
    assert plan_fye_month_updates(s) == [("KLAC", 12, 6), ("ROST", 2, 1)]


def test_a_company_without_a_year_long_annual_period_is_left_alone() -> None:
    s = _session()
    s.add(Company(id=1, ticker="X", name="X", exchange="NYSE", fiscal_year_end_month=2))
    s.add(_annual(1, 2025, "2025-01-01", "2025-03-31"))  # a quarter mislabelled annual
    s.commit()
    assert plan_fye_month_updates(s) == []


def test_only_a_sec_stated_month_is_written() -> None:
    # Review of #29: AMZN's stored rows include a 10-Q trailing year ending
    # 2026-03-31, which implies March; SEC says December, as stored.
    assert confirmed_month(stored=12, derived=3, sec=12) is None
    assert confirmed_month(stored=2, derived=1, sec=1) == 1  # LULU-style, confirmed
    assert confirmed_month(stored=12, derived=10, sec=9) == 9  # SEC wins over stored rows
    assert confirmed_month(stored=12, derived=3, sec=None) is None  # no SEC month: left as is
