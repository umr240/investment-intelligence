"""The verdict store: one row per (company, policy), written before or after a flush."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from data.models.schema import Base, Company, ExclusionVerdict
from screener.policies import verdicts


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _company(ticker: str) -> Company:
    return Company(ticker=ticker, exchange="NYSE", name=ticker, status="screener_candidate")


def _tickers(session: Session, where: ColumnElement[bool]) -> set[str]:
    return {str(t) for t in session.execute(select(Company.ticker).where(where)).scalars()}


def test_set_status_works_before_the_company_is_flushed(session: Session) -> None:
    c = _company("NEW")
    verdicts.set_status(c, "p", "fail", reason="r", source="s")
    session.add(c)
    session.flush()
    row = session.execute(
        select(
            ExclusionVerdict.company_id,
            ExclusionVerdict.policy,
            ExclusionVerdict.status,
            ExclusionVerdict.reason,
        )
    ).one()
    assert tuple(row) == (c.id, "p", "fail", "r")


def test_set_status_updates_in_place(session: Session) -> None:
    c = _company("X")
    session.add(c)
    verdicts.set_status(c, "p", "fail")
    session.flush()
    verdicts.set_status(c, "p", "pass")
    session.flush()
    assert session.query(ExclusionVerdict).count() == 1
    assert verdicts.status_of(c, "p") == "pass"


def test_policies_keep_separate_verdicts(session: Session) -> None:
    c = _company("X")
    verdicts.set_status(c, "a", "fail")
    verdicts.set_status(c, "b", "pass")
    session.add(c)
    session.flush()
    assert (verdicts.status_of(c, "a"), verdicts.status_of(c, "b")) == ("fail", "pass")
    assert verdicts.status_of(c, "c") is None


def test_predicates_treat_a_missing_verdict_as_unclassified(session: Session) -> None:
    for ticker, status in (("PASS", "pass"), ("FAIL", "fail"), ("NONE", None)):
        c = _company(ticker)
        if status:
            verdicts.set_status(c, "p", status)
        session.add(c)
    session.flush()
    assert _tickers(session, verdicts.has_status("p", "pass")) == {"PASS"}
    assert _tickers(session, verdicts.lacks_status("p", "fail")) == {"PASS", "NONE"}
    assert _tickers(session, verdicts.lacks_status("other", "fail")) == {"PASS", "FAIL", "NONE"}


def test_one_verdict_per_company_and_policy(session: Session) -> None:
    c = _company("X")
    session.add(c)
    session.flush()
    session.add_all(
        [
            ExclusionVerdict(company_id=c.id, policy="p", status="pass"),
            ExclusionVerdict(company_id=c.id, policy="p", status="fail"),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_a_company_deletes_its_verdicts(session: Session) -> None:
    c = _company("X")
    verdicts.set_status(c, "p", "fail")
    session.add(c)
    session.flush()
    session.delete(c)
    session.flush()
    assert session.query(ExclusionVerdict).count() == 0


def test_reason_is_read_back_with_the_verdict(session: Session) -> None:
    c = _company("X")
    verdicts.set_status(c, "p", "fail", reason="conventional_banking")
    session.add(c)
    session.flush()
    assert verdicts.reason_of(c, "p") == "conventional_banking"
    assert verdicts.reason_of(c, "other") is None


def test_board_rows_carry_the_exclusion_reason(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    import screener.persistence as persistence

    class _Policy:
        name = "p"

        def status_of(self, company: Company) -> str | None:
            return verdicts.status_of(company, "p")

        def not_excluded(self) -> ColumnElement[bool]:
            return verdicts.lacks_status("p", "ineligible")

    c = _company("BANK")
    verdicts.set_status(c, "p", "ineligible", reason="conventional_banking")
    session.add(c)
    session.flush()

    @contextmanager
    def _session() -> Generator[Session, None, None]:
        yield session

    monkeypatch.setattr(persistence, "get_session", _session)
    monkeypatch.setattr(persistence, "get_policy", lambda: _Policy())
    [row] = persistence.list_screener_candidates()
    # A policy with its own vocabulary: "excluded" comes from its predicate, not the word.
    assert (row["exclusion_status"], row["exclusion_reason"], row["excluded"]) == (
        "ineligible",
        "conventional_banking",
        True,
    )


def test_moat_screener_eligibility_sql_runs_for_a_verdict_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Raw sqlite3 cannot bind the IN-list placeholder SQLAlchemy leaves unless
    # the statement is compiled with render_postcompile.
    import importlib.util
    import sqlite3

    import screener.policies as policies

    class _Policy:
        def eligible(self) -> ColumnElement[bool]:
            return verdicts.has_status("p", "pass")

    monkeypatch.setattr(policies, "get_policy", lambda name=None: _Policy())
    spec = importlib.util.spec_from_file_location(
        "moat_value_screener", Path(__file__).parents[2] / "scripts" / "moat_value_screener.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    db = tmp_path / "w.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        for ticker, status in (("IN", "pass"), ("OUT", "fail")):
            c = _company(ticker)
            verdicts.set_status(c, "p", status)
            s.add(c)
        s.commit()
        ids = {str(c.ticker): int(c.id) for c in s.query(Company)}
    engine.dispose()

    sql, params = module._eligible_ids_sql()
    con = sqlite3.connect(db)
    try:
        got = {row[0] for row in con.execute(sql, params)}
    finally:
        con.close()
    assert got == {ids["IN"]}
