"""FundamentalsTask is fresh after a read even when no ROIC comes out of it.

It gated on roic_fetched_at, which is set only when a ROIC is computable, so
banks, REITs and filers without annuals were re-read on every run.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine, true
from sqlalchemy.orm import Session, sessionmaker

import screener.tasks.fundamentals as fundamentals
from data.models.schema import Base, Company
from screener.tasks.base import FilterResult


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    monkeypatch.setattr(fundamentals, "not_excluded", lambda: true())
    monkeypatch.setattr(fundamentals, "_persist_financials", lambda _t, _r: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    for ticker in ("BANK", "FRESH"):
        db.add(
            Company(
                ticker=ticker,
                cik=f"cik-{ticker}",
                exchange="NYSE",
                name=ticker,
                status="screener_candidate",
            )
        )
    db.flush()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _pending(db: Session) -> set[str]:
    return {str(c.ticker) for c in fundamentals.FundamentalsTask().select_pending(db)}


def test_a_read_without_roic_still_counts_as_fresh(session: Session) -> None:
    assert _pending(session) == {"BANK", "FRESH"}
    result: Any = FilterResult(cik="cik-BANK", values={"ticker": "BANK", "rows": []})
    fundamentals.FundamentalsTask().persist(session, [result])

    bank = session.query(Company).filter_by(ticker="BANK").one()
    assert bank.roic_fetched_at is None  # no annuals, so no ROIC
    assert bank.fundamentals_fetched_at is not None
    assert _pending(session) == {"FRESH"}
