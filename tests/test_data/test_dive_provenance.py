"""DEC-46: dives record their inputs; dives on superseded data are flagged, not deleted.

The 52/53-week parser fix (2026-10-24) re-read every dived ticker's filings,
and no stored dive recorded which data it had read.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import data.dive_staleness as staleness
from data.models.schema import Base, Company, DeepDiveRun, FinancialSourceLog


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
    monkeypatch.setattr("data.db.get_session", session)
    yield factory
    engine.dispose()


def _seed(
    factory: sessionmaker[Session],
    log_versions: list[int | None],
    dive_versions: list[int | None],
    modes: list[str] | None = None,
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
        for i, v in enumerate(dive_versions):
            mode = modes[i] if modes else "default"
            s.add(
                DeepDiveRun(
                    company_id=co.id,
                    ticker="LULU",
                    mode=mode,
                    parser_version=v,
                    bull_narrative="[]",
                )
            )
        s.commit()


def _runs(factory: sessionmaker[Session]) -> list[DeepDiveRun]:
    with factory() as s:
        return list(s.execute(select(DeepDiveRun).order_by(DeepDiveRun.id)).scalars())


def test_a_reparse_flags_every_earlier_dive_without_deleting(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[4, 4], dive_versions=[None, 3, 4])
    assert staleness.flag_dives_after_reparse("LULU", 4) == 3
    runs = _runs(db)
    assert len(runs) == 3
    assert all("re-read by parser v4" in (r.stale_reason or "") for r in runs)
    assert all("values not compared" in (r.stale_reason or "") for r in runs)
    assert all(isinstance(r.stale_at, datetime) for r in runs)
    assert runs[0].bull_narrative == "[]"
    assert staleness.flag_dives_after_reparse("LULU", 4) == 0  # already flagged: untouched


def test_backfill_flags_dives_recorded_below_the_newest_parser(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[None, 3, 3], dive_versions=[None, 2, 3])
    assert staleness.flag_dives_read_by_older_parser("LULU") == 2
    runs = _runs(db)
    assert (
        runs[0].stale_reason
        == "stored before filings were re-read by parser v3; values not compared"
    )
    assert runs[1].stale_reason is not None
    assert runs[2].stale_reason is None
    assert staleness.flag_dives_read_by_older_parser("LULU") == 0


def test_backfill_flags_nothing_while_no_filing_is_versioned(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[None, None], dive_versions=[None])
    assert staleness.flag_dives_read_by_older_parser("LULU") == 0


def test_a_dive_records_the_oldest_parser_it_read(db: sessionmaker[Session]) -> None:
    # Review of #25 (2d): recording the newest let a later re-read of old years go unflagged.
    _seed(db, log_versions=[2, 3, None], dive_versions=[])
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
        assert staleness.fundamentals_parser_version(s, "LULU") == 0
        assert staleness.latest_10k_accession(s, "LULU") == "a-2"
        assert staleness.fundamentals_parser_version(s, "NONE") is None


def test_stale_reason_follows_the_requested_mode(db: sessionmaker[Session]) -> None:
    _seed(db, log_versions=[3], dive_versions=[None, 3], modes=["A", "B"])
    with db() as s:
        first = s.execute(select(DeepDiveRun).order_by(DeepDiveRun.id)).scalars().first()
        assert first is not None
        first.stale_reason = "x"  # type: ignore[assignment]  # Column-style model
        s.commit()
    assert staleness.latest_dive_stale_reason("lulu") is None  # the newest dive (mode B)
    assert staleness.latest_dive_stale_reason("LULU", "A") == "x"
    assert staleness.latest_dive_stale_reason("LULU", "B") is None


def test_the_refresh_hook_reports_flagged_dives(db: sessionmaker[Session]) -> None:
    from data.edgar_companyfacts import PARSER_VERSION
    from data.pipeline import _flag_dives_after_reparse

    _seed(db, log_versions=[PARSER_VERSION], dive_versions=[None])
    gaps = _flag_dives_after_reparse("LULU")
    assert gaps == ["LULU: 1 earlier deep dive(s) flagged stale (filings re-read); re-run"]
    assert f"parser v{PARSER_VERSION}" in (_runs(db)[0].stale_reason or "")
    assert _flag_dives_after_reparse("LULU") == []


def test_narrative_is_not_generated_on_a_stale_dive(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepdive.narrative as narrative

    monkeypatch.setattr(staleness, "latest_dive_stale_reason", lambda _t: "filings re-read")

    def _no_call(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider was called on a stale dive")

    monkeypatch.setattr(narrative, "_call_provider", _no_call)
    with pytest.raises(narrative.NarrativeOnStaleDiveError, match="latest dive is stale"):
        narrative.generate_narrative(SimpleNamespace(ticker="LULU"), provider_pref="openai")  # type: ignore[arg-type]


def _narrative() -> Any:
    point = SimpleNamespace(model_dump=lambda: {"point": "x"})
    return SimpleNamespace(
        ticker="LULU",
        body=SimpleNamespace(bull=[point], bear=[point], one_liner="", risks=[], data_caveats=[]),
        provider=SimpleNamespace(value="openai"),
        model="m",
        prompt_tokens=1,
        completion_tokens=1,
        fallback_used=False,
        fallback_reason="",
        status=SimpleNamespace(value="ok"),
        guard_warnings=[],
        generated_at=datetime(2026, 10, 24),
    )


def test_a_dive_flagged_during_generation_does_not_store_the_narrative(
    db: sessionmaker[Session],
) -> None:
    # Review of #25 (1a): the stale check ran before the provider call, the write after it.
    import deepdive.narrative as narrative

    _seed(db, log_versions=[3], dive_versions=[None])
    with db() as s:
        run = s.execute(select(DeepDiveRun)).scalars().one()
        run.bull_narrative = None  # type: ignore[assignment]  # Column-style model
        run.stale_reason = "flagged mid-call"  # type: ignore[assignment]  # Column-style model
        s.commit()
    with pytest.raises(narrative.NarrativeOnStaleDiveError, match="not stored"):
        narrative.persist_narrative(_narrative())
    assert _runs(db)[0].bull_narrative is None


def test_the_view_is_attached_to_the_run_that_produced_it(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review of #25 (4): the view used to go to whichever dive of the ticker was newest.
    from deepdive import orchestrator

    _seed(db, log_versions=[3], dive_versions=[3, 3])
    monkeypatch.setattr(
        "deepdive.scorecard_view.load_scorecard_view",
        lambda _t, mode=None: SimpleNamespace(to_llm_context=lambda: '{"ticker": "LULU"}'),
    )
    older = int(_runs(db)[0].id)
    orchestrator._record_scorecard_view(older, "LULU", "default")
    runs = _runs(db)
    assert runs[0].scorecard_view_json == '{"ticker": "LULU"}'
    assert runs[0].scorecard_view_sha256 is not None and len(runs[0].scorecard_view_sha256) == 64
    assert runs[1].scorecard_view_json is None


def test_api_withholds_and_refuses_on_a_stale_dive(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    import deepdive.narrative as narrative
    from api.app import app

    _seed(db, log_versions=[3], dive_versions=[None])
    staleness.flag_dives_read_by_older_parser("LULU")
    monkeypatch.setattr(
        "deepdive.scorecard_view.load_scorecard_view",
        lambda _t, mode=None: SimpleNamespace(ticker="LULU"),
    )

    def _no_call(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a provider was called on a stale dive")

    monkeypatch.setattr(narrative, "_call_provider", _no_call)
    client = TestClient(app)
    got = client.get("/dive/LULU/narrative").json()
    assert got["generated"] is False and got["stale"] is True
    assert "values not compared" in got["stale_reason"]
    assert client.post("/dive/LULU/narrative").status_code == 409


def test_export_withholds_the_narrative_of_a_stale_dive() -> None:
    from deepdive.serializer import export_deepdive_markdown

    run = DeepDiveRun(
        ticker="LULU",
        mode="default",
        tier=2,
        run_date=datetime(2026, 5, 17),
        composite_score=5.0,
        verdict="watchlist",
        stale_reason="filings re-read",
        bull_narrative='[{"point": "x"}]',
        bear_narrative='[{"point": "y"}]',
        risk_factors='{"risks": []}',
    )
    md = export_deepdive_markdown(run)
    assert "**Stale:** filings re-read" in md
    assert "Withheld" in md
    assert "## Bull Case" not in md and "## Bear Case" not in md
