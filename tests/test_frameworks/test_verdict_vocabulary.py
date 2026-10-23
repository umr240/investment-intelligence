"""ADR-054: one verdict vocabulary, and no label that names an action.

Rows stored before the rename are mapped when read, never rewritten.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.verdicts import LEGACY_VERDICTS, canonical_verdict, stored_forms
from data.models.schema import Base, Company
from frameworks.composite import compute_composite_score
from screener.query import ScreenerQuery, run_screener

CURRENT = {"priority_watchlist", "watchlist", "monitor", "exclude", "research_only"}
ALL_SEVEN = ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(9.0, "priority_watchlist"), (6.0, "watchlist"), (4.0, "monitor"), (1.0, "exclude")],
)
def test_engine_bands_use_the_current_labels(score: float, verdict: str) -> None:
    out = compute_composite_score({c: score for c in ALL_SEVEN}, mode="C", stage="mid_cap")
    assert out.verdict == verdict


def test_no_engine_label_names_an_action() -> None:
    for score in (0.0, 2.5, 3.0, 5.0, 7.0, 10.0):
        out = compute_composite_score({c: score for c in ALL_SEVEN}, mode="C", stage="mid_cap")
        assert out.verdict in CURRENT


def test_legacy_rows_read_as_current_labels() -> None:
    assert canonical_verdict("initiate") == "priority_watchlist"
    assert canonical_verdict("insufficient_breadth") == "research_only"
    assert canonical_verdict("watchlist") == "watchlist"
    assert canonical_verdict(None) is None
    assert set(LEGACY_VERDICTS.values()) <= CURRENT


def test_stored_forms_include_the_legacy_spelling() -> None:
    assert stored_forms(["priority_watchlist"]) == ("initiate", "priority_watchlist")
    assert stored_forms(["monitor"]) == ("monitor",)


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


def test_warehouse_filter_finds_rows_stored_under_the_old_label(session: Session) -> None:
    for ticker, verdict in (("OLD", "initiate"), ("NEW", "priority_watchlist"), ("MID", "monitor")):
        session.add(
            Company(
                ticker=ticker,
                exchange="NYSE",
                name=ticker,
                status="screener_candidate",
                market_cap_usd=1e9,
                data_completeness=1.0,
                framework_verdict=verdict,
            )
        )
    session.flush()
    q = ScreenerQuery(framework_verdict_in=("priority_watchlist",), policy="none", top_n=10)
    assert {str(c.ticker) for c in run_screener(session, q)} == {"OLD", "NEW"}


def test_orm_reads_legacy_labels_in_the_current_vocabulary(session: Session) -> None:
    # Written with raw SQL, as rows from before ADR-054 were; never rewritten.
    from sqlalchemy import select, text

    session.add(Company(ticker="OLD", exchange="NYSE", name="OLD", status="screener_candidate"))
    session.flush()
    session.execute(text("UPDATE companies SET framework_verdict = 'initiate'"))
    raw = session.execute(text("SELECT framework_verdict FROM companies")).scalar_one()
    session.expire_all()
    assert raw == "initiate"
    assert session.execute(select(Company.framework_verdict)).scalar_one() == "priority_watchlist"


def test_legacy_mapping_ignores_case() -> None:
    assert canonical_verdict("INITIATE") == "priority_watchlist"
    assert canonical_verdict("Insufficient_Breadth") == "research_only"
