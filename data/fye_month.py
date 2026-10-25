"""Fiscal-year-end month from a company's own stored annual periods.

Rows parsed before the nominal-month fix (#24) keep the month the old
raw-month parser stored ("0202" as 2). The month still labels earnings rows
and the scorecard header, so it is corrected from the end date of each
company's latest year-long annual row: real filing dates, no network.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.edgar_companyfacts import _nominal_period_end
from data.models.schema import Company, Financial


def plan_fye_month_updates(session: Session) -> list[tuple[str, int | None, int]]:
    """(ticker, stored month, month implied by its latest annual period) where they differ."""
    latest: dict[int, date] = {}
    rows: Sequence[Any] = session.execute(
        select(Financial.company_id, Financial.period_start_date, Financial.period_end_date).where(
            Financial.period == "annual",
            Financial.period_start_date.is_not(None),
            Financial.period_end_date.is_not(None),
        )
    ).all()
    for company_id, start, end in rows:
        s, e = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
        if 340 <= (e - s).days <= 380 and (company_id not in latest or e > latest[company_id]):
            latest[company_id] = e
    out: list[tuple[str, int | None, int]] = []
    for co in session.execute(select(Company).where(Company.id.in_(latest))).scalars():
        month = _nominal_period_end(latest[int(co.id)]).month
        stored = int(co.fiscal_year_end_month) if co.fiscal_year_end_month is not None else None
        if stored != month:
            out.append((str(co.ticker), stored, month))
    return sorted(out)
