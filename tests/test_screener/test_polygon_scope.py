"""Polygon tasks run on the watchlist and portfolio, never the screener universe.

ADR-019: 5 calls a minute cannot cover ~10,000 screener candidates (about 34
hours per task). The tasks selected every candidate, and Stage C's shortlist
prefetch filtered a list that run_task then re-selected, so the first run
with a key would have fanned out to the whole universe.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import data.db
import screener.tasks.polygon as polygon
import screener.tasks.runner as runner
from data.api.polygon_client import PolygonClient
from data.models.schema import Base, Company, PortfolioPosition, WatchlistEntry
from screener.stages import _prefetch_polygon_for_shortlist
from screener.tasks.base import TaskResult, TaskRunStatus

TASKS = (
    polygon.PolygonCurrentPriceTask,
    polygon.PolygonWeeklyPriceTask,
    polygon.PolygonShortInterestTask,
    polygon.PolygonRSITask,
    polygon.PolygonSMATask,
    polygon.PolygonMACDTask,
)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    monkeypatch.setattr(polygon, "_polygon_client_or_none", lambda: object())
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    for ticker, status in (
        ("CAND", "screener_candidate"),
        ("WATCH", "watchlist"),
        ("HELD", "screener_candidate"),
        ("ENTRY", "dive_history"),
    ):
        db.add(Company(ticker=ticker, exchange="NYSE", name=ticker, status=status))
    db.flush()
    ids = {str(c.ticker): int(c.id) for c in db.query(Company)}
    db.add(PortfolioPosition(company_id=ids["HELD"], ticker="HELD", entry_date=date(2025, 1, 2)))
    db.add(WatchlistEntry(company_id=ids["ENTRY"], role="monitor"))
    db.flush()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize("task_cls", TASKS)
def test_default_scope_is_watchlist_and_portfolio(session: Session, task_cls: Any) -> None:
    picked = {str(c.ticker) for c in task_cls().select_pending(session)}
    assert picked == {"WATCH", "HELD", "ENTRY"}


@pytest.mark.parametrize("task_cls", TASKS)
def test_explicit_tickers_replace_the_default_scope(session: Session, task_cls: Any) -> None:
    picked = {str(c.ticker) for c in task_cls(tickers=["cand"]).select_pending(session)}
    assert picked == {"CAND"}


def test_stage_c_prefetch_is_scoped_to_its_shortlist(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[frozenset[str] | None] = []

    async def fake_run_task(task: Any, db: Session) -> Any:
        seen.append(task.tickers)
        return TaskResult(task=task.name, status=TaskRunStatus.SUCCESS)

    @contextmanager
    def get_session() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(PolygonClient, "has_key", property(lambda self: True))
    monkeypatch.setattr(runner, "run_task", fake_run_task)
    monkeypatch.setattr(data.db, "get_session", get_session)
    outcome = asyncio.run(_prefetch_polygon_for_shortlist(["CAND"]))
    assert seen == [frozenset({"CAND"}), frozenset({"CAND"})]
    assert outcome == {"prefetched": 0, "errors": 0}


def test_weekly_bars_are_not_starved_by_the_daily_price_task(session: Session) -> None:
    # Both tasks shared latest_close_at, so the daily run marked every ticker
    # fresh and the weekly task then skipped almost all of them.
    from datetime import UTC, datetime

    for c in session.query(Company):
        c.latest_close_at = datetime.now(UTC)  # type: ignore[assignment]
    session.flush()
    picked = {str(c.ticker) for c in polygon.PolygonWeeklyPriceTask().select_pending(session)}
    assert picked == {"WATCH", "HELD", "ENTRY"}


def test_weekly_task_stamps_its_own_freshness(session: Session) -> None:
    from datetime import UTC, datetime

    from screener.tasks.base import FilterResult

    watch = session.query(Company).filter_by(ticker="WATCH").one()
    result = FilterResult(
        cik="WATCH",
        values={
            "company_id": watch.id,
            "ticker": "WATCH",
            "bars": [],
            "started_at": datetime.now(UTC),
        },
    )
    polygon.PolygonWeeklyPriceTask().persist(session, [result])
    assert watch.weekly_prices_fetched_at is not None
    picked = {str(c.ticker) for c in polygon.PolygonWeeklyPriceTask().select_pending(session)}
    assert picked == {"HELD", "ENTRY"}
