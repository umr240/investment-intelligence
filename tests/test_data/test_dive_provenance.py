"""DEC-46: dives record their inputs; dives on superseded data are flagged, not deleted.

The 52/53-week parser fix (parser v3, 2026-10-24) re-read every dived ticker's
filings, and no stored dive recorded which data it had read.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import data.dive_staleness as staleness
from data.models.schema import Base, Company, DeepDiveRun, FinancialSourceLog


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

    monkeypatch.setattr(staleness, "get_session", session)
    yield factory
    engine.dispose()


def _seed(
    factory: sessionmaker[Session], log_versions: list[int | None], dive_versions: list[int | None]
) -> None:
    with factory() as s:
        co = Company(ticker="LULU", name="lululemon", exchange="NASDAQ")
        s.add(co)
        s.flush()
        for i, v in enumerate(log_versions):
            s.add(
                FinancialSourceLog(
                    ticker="LULU",
                    accession_number=f"a-{i}",
                    form_type="10-K",
                    fiscal_year=2020 + i,
                    period="annual",
                    parser_version=v,
                )
            )
        for v in dive_versions:
            s.add(
                DeepDiveRun(
                    company_id=co.id,
                    ticker="LULU",
                    mode="default",
                    parser_version=v,
                    bull_narrative="[]",
                )
            )
        s.commit()


def _runs(factory: sessionmaker[Session]) -> list[DeepDiveRun]:
    with factory() as s:
        return list(s.execute(select(DeepDiveRun).order_by(DeepDiveRun.id)).scalars())


def test_dives_read_by_an_older_parser_are_flagged_not_deleted(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[None, 3, 3], dive_versions=[None, 2, 3])
    assert staleness.flag_superseded_dives("LULU") == 2
    runs = _runs(db)
    assert len(runs) == 3
    assert runs[0].stale_reason == "fundamentals re-read by parser v3 (dive read unversioned)"
    assert runs[1].stale_reason == "fundamentals re-read by parser v3 (dive read v2)"
    assert runs[2].stale_reason is None
    assert isinstance(runs[0].stale_at, datetime)
    assert runs[0].bull_narrative == "[]"


def test_flagging_is_idempotent(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[3], dive_versions=[None])
    assert staleness.flag_superseded_dives("LULU") == 1
    first = _runs(db)[0].stale_at
    assert staleness.flag_superseded_dives("LULU") == 0
    assert _runs(db)[0].stale_at == first


def test_nothing_is_flagged_while_no_filing_is_versioned(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[None, None], dive_versions=[None])
    assert staleness.flag_superseded_dives("LULU") == 0


def test_provenance_lookups(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[None, 3], dive_versions=[])
    with db() as s:
        s.add(
            FinancialSourceLog(
                ticker="LULU",
                accession_number="q-1",
                form_type="10-Q",
                fiscal_year=2030,
                period="Q1",
                parser_version=3,
            )
        )
        s.commit()
        assert staleness.fundamentals_parser_version(s, "LULU") == 3
        assert staleness.latest_10k_accession(s, "LULU") == "a-1"
        assert staleness.fundamentals_parser_version(s, "NONE") is None


def test_latest_dive_stale_reason(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[3], dive_versions=[None, 3])
    staleness.flag_superseded_dives("LULU")
    assert staleness.latest_dive_stale_reason("lulu") is None  # the newest dive read v3
    with db() as s:
        s.add(DeepDiveRun(company_id=1, ticker="LULU", mode="default", stale_reason="x"))
        s.commit()
    assert staleness.latest_dive_stale_reason("LULU") == "x"


def test_narrative_is_not_generated_on_a_stale_dive(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepdive.narrative as narrative

    monkeypatch.setattr(staleness, "latest_dive_stale_reason", lambda _t: "fundamentals re-read")

    def _no_call(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider was called on a stale dive")

    monkeypatch.setattr(narrative, "_call_provider", _no_call)

    class _View:
        ticker = "LULU"

    with pytest.raises(narrative.NarrativeOnStaleDiveError, match="latest dive is stale"):
        narrative.generate_narrative(_View(), provider_pref="openai")  # type: ignore[arg-type]


def test_export_withholds_the_narrative_of_a_stale_dive() -> None:
    from deepdive.serializer import export_deepdive_markdown

    run = DeepDiveRun(
        ticker="LULU",
        mode="default",
        tier=2,
        run_date=datetime(2026, 5, 17),
        composite_score=5.0,
        verdict="watchlist",
        stale_reason="fundamentals re-read",
        bull_narrative='[{"point": "x"}]',
        bear_narrative='[{"point": "y"}]',
        risk_factors='{"risks": []}',
    )
    md = export_deepdive_markdown(run)
    assert "**Stale:** fundamentals re-read" in md
    assert "Withheld" in md
    assert "## Bull Case" not in md and "## Bear Case" not in md
