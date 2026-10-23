"""Data-layer invariants — integration tests against the live dev SQLite DB.

These tests do NOT use the in-memory fixture from conftest.py. They run
against `investment_intelligence.db` and validate that the data the F1
score (and future frameworks) depends on remains internally consistent
after each `invest dive`.

Each test skips when its prerequisite tickers haven't been loaded —
useful for CI environments where the dev DB isn't seeded.

Bundled with the F1 implementation PR per the plan:
  (a) period_end_date matches FY-end-month for non-Dec filers
  (b) quarterly chronology is monotonic (Q1 < Q2 < Q3 < Q4)
  (c) Form 4 transaction codes are well-formed
  (d) ADR-018 _state columns only carry the 4 enum values
"""
from __future__ import annotations

import calendar
from datetime import date

import pytest
from sqlalchemy import select

from data.db import get_session
from data.models.schema import (
    Company,
    Financial,
    InsiderTransactionRecord,
)

# Every test here reads the real database and skips when it is empty, so a run
# that does not load data proves nothing about these invariants. The marker
# makes that visible: `pytest -m requires_data` asserts they actually ran.
pytestmark = pytest.mark.requires_data


# Each (ticker, expected fiscal-year-end month) pair MUST match what
# `Company.fiscal_year_end_month` is populated to via SEC submissions.json.
KNOWN_FYE_MONTHS = {
    "INTA": 6,    # June fiscal year-end
    "AAPL": 9,    # September fiscal year-end
    "NVDA": 1,    # January fiscal year-end
    "MSFT": 6,    # June fiscal year-end
}


def _company(ticker: str) -> Company | None:
    with get_session() as s:
        co = s.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if co is not None:
            s.expunge(co)
        return co


def _financials(company_id: int) -> list[Financial]:
    with get_session() as s:
        rows = s.execute(
            select(Financial)
            .where(Financial.company_id == company_id)
            .order_by(Financial.fiscal_year, Financial.period)
        ).scalars().all()
        for r in rows:
            s.expunge(r)
        return list(rows)


# ── (a) period_end correctness ─────────────────────────────────────────────

@pytest.mark.parametrize("ticker", list(KNOWN_FYE_MONTHS.keys()))
def test_annual_period_end_matches_fye_month(ticker: str) -> None:
    """Annual rows' period_end_date.month must match Company.fiscal_year_end_month.

    Day-within-month varies by filer convention (e.g. NVDA uses 52-53-week
    fiscal year ending the LAST FRIDAY of January — could be Jan 25, Jan 28,
    Feb 1...). Some filers' month can even slip into the next calendar
    month (Jan 31 → Feb 1 in some 53-week years). We assert only the month
    is the FYE month OR the immediately-following month (handles 52-53wk).
    """
    co = _company(ticker)
    if not co:
        pytest.skip(f"{ticker} not loaded")
    fyem = co.fiscal_year_end_month or 12
    expected_fyem = KNOWN_FYE_MONTHS[ticker]
    assert fyem == expected_fyem, (
        f"{ticker} Company.fiscal_year_end_month = {fyem}, expected {expected_fyem}"
    )

    annuals = [r for r in _financials(co.id) if r.period == "annual"]
    if not annuals:
        pytest.skip(f"{ticker} has no annual rows")

    # For 52-53-week filers (NVDA, AAPL etc.) the fiscal year-end can fall
    # in either the FYE month OR ±1 month (52-week year ending early).
    allowed_months = {fyem, (fyem % 12) + 1, ((fyem - 2) % 12) + 1}

    bad = []
    for r in annuals:
        end = r.period_end_date
        if end is None:
            bad.append(f"FY{r.fiscal_year} has period_end_date=None")
            continue
        if end.month not in allowed_months:
            bad.append(
                f"FY{r.fiscal_year} period_end={end} month={end.month} "
                f"(expected one of {sorted(allowed_months)})"
            )
    assert not bad, f"{ticker} annual period_end violations: {bad}"


# ── (b) quarterly chronology ───────────────────────────────────────────────

@pytest.mark.parametrize("ticker", list(KNOWN_FYE_MONTHS.keys()))
def test_quarterly_chronology_no_duplicates(ticker: str) -> None:
    """Within each fiscal year the Q-period_end values must be ascending and unique."""
    co = _company(ticker)
    if not co:
        pytest.skip(f"{ticker} not loaded")

    by_year: dict[int, list[tuple[str, date]]] = {}
    for r in _financials(co.id):
        if r.period not in ("Q1", "Q2", "Q3", "Q4"):
            continue
        if r.period_end_date is None:
            continue
        by_year.setdefault(r.fiscal_year, []).append((r.period, r.period_end_date))

    if not by_year:
        pytest.skip(f"{ticker} has no quarterly rows")

    bad: list[str] = []
    for fy, items in by_year.items():
        items.sort(key=lambda x: x[0])    # Q1 < Q2 < Q3 < Q4 lexically
        ends = [d for _, d in items]
        if len(set(ends)) != len(ends):
            bad.append(f"{ticker} FY{fy} has duplicate period_end_date: {items}")
        if ends != sorted(ends):
            bad.append(f"{ticker} FY{fy} quarter end_dates not ascending: {items}")
    assert not bad, "\n".join(bad)


# ── (c) Form 4 transaction-code well-formedness ────────────────────────────

VALID_FORM4_CODES = frozenset({
    "P", "S", "A", "M", "F", "G", "D", "X", "J", "C", "I", "K",
    "V", "W", "Z", "U", "L", "T", "B", "E", "H", "O", "Q", "Y", "",
})


@pytest.mark.parametrize("ticker", ["INTA", "NVDA", "AAPL"])
def test_form4_codes_are_well_formed(ticker: str) -> None:
    """Every InsiderTransactionRecord code is a single uppercase letter or empty."""
    co = _company(ticker)
    if not co:
        pytest.skip(f"{ticker} not loaded")
    with get_session() as s:
        # Pull (id, transaction_type) tuples directly to avoid detached-instance
        # attribute reloads after the session closes.
        rows = s.execute(
            select(InsiderTransactionRecord.id, InsiderTransactionRecord.transaction_type)
            .where(InsiderTransactionRecord.company_id == co.id)
            .where(InsiderTransactionRecord.source == "edgar")
        ).all()

    if not rows:
        pytest.skip(f"{ticker} has no EDGAR-sourced Form 4 rows")

    bad = [
        f"row {rid} code={code!r}"
        for rid, code in rows
        if code not in VALID_FORM4_CODES
    ]
    assert not bad, f"{ticker} invalid Form 4 codes: {bad[:5]}"

    codes = {code for _, code in rows}
    assert codes & {"A", "M", "F", "S"}, (
        f"{ticker} Form 4 rows contain none of A/M/F/S — parser likely broken. "
        f"Got codes: {sorted(c for c in codes if c is not None)}"
    )


# ── (d) ADR-018 _state columns are well-formed enums ───────────────────────

VALID_STATE_VALUES = frozenset({
    "disclosed_exact", "not_disclosed", "parser_uncertain", None,
})


def test_adr018_state_columns_are_well_formed_enums() -> None:
    """Every ADR-018 _state column carries one of the 4 sanctioned values."""
    with get_session() as s:
        companies = s.execute(select(Company)).scalars().all()
        if not companies:
            pytest.skip("no companies loaded")

        bad: list[str] = []
        for c in companies:
            state_cols = {
                "ceo_name_state": c.ceo_name_state,
                "ceo_equity_pct_state": c.ceo_equity_pct_state,
                "is_founder_ceo_state": c.is_founder_ceo_state,
                "ipo_date_state": c.ipo_date_state,
            }
            for col, val in state_cols.items():
                if val not in VALID_STATE_VALUES:
                    bad.append(f"{c.ticker}.{col} = {val!r}")

        # Also Financial side
        financials = s.execute(select(Financial)).scalars().all()
        for f in financials:
            for col_name, val in (
                ("customer_concentration_state", f.customer_concentration_state),
                ("receivables_concentration_state", f.receivables_concentration_state),
            ):
                if val not in VALID_STATE_VALUES:
                    bad.append(f"Financial[{f.id}].{col_name} = {val!r}")

    assert not bad, f"Invalid _state values: {bad[:10]}"
