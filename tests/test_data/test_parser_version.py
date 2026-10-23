"""Logged filings carry the parser version that read them.

A parser fix must reach rows stored before it. Filings logged by an older
PARSER_VERSION drop out of the known-accession set, so the next refresh
re-reads them once and re-stamps them (CRWD's revenue, 2026-10-21).
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import data.pipeline as pipeline
from data.edgar_companyfacts import PARSER_VERSION
from data.edgar_fetcher import EdgarFinancialRow
from data.models.schema import Base, FinancialSourceLog


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def session() -> Iterator[Session]:
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(pipeline, "get_session", session)
    yield factory
    engine.dispose()


def _row(accession: str, year: int = 2026) -> EdgarFinancialRow:
    return EdgarFinancialRow(
        ticker="X", fiscal_year=year, period="annual", accession_number=accession
    )


def _log(
    factory: sessionmaker[Session], accession: str, version: int | None, year: int = 2026
) -> None:
    with factory() as s:
        s.add(
            FinancialSourceLog(
                ticker="X",
                accession_number=accession,
                form_type="10-K",
                fiscal_year=year,
                parser_version=version,
            )
        )
        s.commit()


def test_new_filings_are_stamped_with_the_current_parser(db: sessionmaker[Session]) -> None:
    pipeline._persist_source_log("X", [_row("a1")])
    with db() as s:
        assert s.query(FinancialSourceLog.parser_version).scalar() == PARSER_VERSION
    assert pipeline._load_known_accessions("X") == frozenset({"a1"})


def test_older_filings_are_stale_until_read_again(db: sessionmaker[Session]) -> None:
    _log(db, "old", None)
    _log(db, "prev", PARSER_VERSION - 1)
    _log(db, "cur", PARSER_VERSION)
    assert pipeline._stale_parse_count("X") == 2
    assert pipeline._load_known_accessions("X") == frozenset({"cur"})

    pipeline._persist_source_log("X", [_row("old"), _row("prev", 2025)])
    assert pipeline._stale_parse_count("X") == 0
    assert pipeline._load_known_accessions("X") == frozenset({"old", "prev", "cur"})
    with db() as s:
        assert s.query(FinancialSourceLog).count() == 3


def test_a_full_reread_stamps_superseded_filings_too(db: sessionmaker[Session]) -> None:
    # A superseded 10-Q emits no row once a later filing restates its period;
    # without stamping it the stale count never reaches zero and every refresh
    # re-downloads companyfacts.
    _log(db, "latest", None)
    _log(db, "superseded", None)
    pipeline._persist_source_log("X", [_row("latest")], reparsed=True)
    assert pipeline._stale_parse_count("X") == 0


def test_an_incremental_read_leaves_unread_filings_stale(db: sessionmaker[Session]) -> None:
    _log(db, "latest", None)
    _log(db, "superseded", None)
    pipeline._persist_source_log("X", [_row("latest")])
    assert pipeline._stale_parse_count("X") == 1


def test_a_reread_stamps_only_the_years_it_read(db: sessionmaker[Session]) -> None:
    # A two-year dive re-reads FY2025-26 only; stamping FY2016 current would
    # leave its old-parser values in place for good.
    _log(db, "recent", None, 2026)
    _log(db, "old", None, 2016)
    pipeline._persist_source_log("X", [_row("recent", 2026)], reparsed=True)
    assert pipeline._stale_parse_count("X") == 1
    assert pipeline._stale_parse_count("X", since_year=2025) == 0


def test_a_gap_year_inside_the_read_is_stamped(db: sessionmaker[Session]) -> None:
    # No FY2024 row comes back (a gap year); left stale, it would force a full
    # re-read on every refresh.
    _log(db, "gap", None, 2024)
    pipeline._persist_source_log("X", [_row("a", 2023), _row("b", 2025)], reparsed=True)
    assert pipeline._stale_parse_count("X") == 0
