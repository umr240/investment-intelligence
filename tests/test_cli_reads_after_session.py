"""CLI commands on a database that has rows in it.

Found by the Phase 8 fresh-install walkthrough: `export list` and
`watchlist list` read rows after `get_session()` had committed and expired
them (DetachedInstanceError), and `screen-cleanup` compared the DateTime
`last_screened` with a date (TypeError). Unit tests built objects in memory,
so none of the three ever crossed a commit.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

import data.db
import screener.cleanup
from cli.main import app
from data.models.schema import Base, Company, DeepDiveRun, ScreenerRun, WatchlistEntry


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine)  # expire_on_commit, as in data/db.py

    @contextmanager
    def get_session() -> Iterator[Session]:
        session = make()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    monkeypatch.setattr(data.db, "get_session", get_session)
    monkeypatch.setattr(screener.cleanup, "get_session", get_session)
    yield make
    engine.dispose()


def test_lists_stored_dives_and_runs(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        company = Company(ticker="NVDA", exchange="Nasdaq", name="NVIDIA")
        s.add(company)
        s.flush()
        s.add(
            DeepDiveRun(
                company_id=company.id,
                ticker="NVDA",
                mode="C",
                tier=1,
                composite_score=7.4,
                verdict="initiate",
                run_date=datetime(2026, 10, 22),
            )
        )
        s.add(ScreenerRun(mode="B", region="us", universe_count=7, passed_gates=5))
        s.commit()

    result = CliRunner().invoke(app, ["export", "list"], env={"COLUMNS": "120"})

    assert result.exit_code == 0, result.output
    assert "NVDA" in result.output
    assert "priority_watchlist" in result.output
    assert "initiate" not in result.output


def test_watchlist_list_shows_entries(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        company = Company(ticker="COST", exchange="Nasdaq", name="Costco", status="watchlist")
        s.add(company)
        s.flush()
        s.add(WatchlistEntry(company_id=company.id, role="core", notes="moat"))
        s.commit()

    result = CliRunner().invoke(app, ["watchlist", "list"], env={"COLUMNS": "120"})

    assert result.exit_code == 0, result.output
    assert "COST" in result.output and "moat" in result.output


def test_cleanup_archives_a_stale_candidate_read_back_from_the_db(
    factory: sessionmaker[Session],
) -> None:
    with factory() as s:
        for ticker, screened in (("OLD", datetime(2026, 1, 1)), ("NEW", datetime(2026, 10, 20))):
            s.add(
                Company(
                    ticker=ticker,
                    exchange="NYSE",
                    name=ticker,
                    status="screener_candidate",
                    last_screened=screened,
                    retention_days=30,
                )
            )
        s.commit()

    report = screener.cleanup.archive_stale_candidates(dry_run=True, today=date(2026, 10, 22))

    assert report.candidates_evaluated == 2
    assert report.archived_tickers == ["OLD"]
    result = CliRunner().invoke(app, ["screen-cleanup", "--dry-run"], env={"COLUMNS": "120"})
    assert result.exit_code == 0, result.output
