"""DEC-46/47: dives record their inputs; dives whose inputs changed are flagged, not deleted.

The 52/53-week parser fix (2026-10-24) re-read every dived ticker's filings,
and no stored dive recorded which data it had read. DEC-47: a dive is withheld
only when its recorded fundamentals differ from today's, or were never recorded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import data.dive_staleness as staleness
from data.models.schema import (
    Base,
    Company,
    DeepDiveConversation,
    DeepDiveRun,
    Financial,
    FinancialSourceLog,
)


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


def _company(factory: sessionmaker[Session], revenues: list[float] | None = None) -> int:
    with factory() as s:
        co = Company(ticker="LULU", name="lululemon", exchange="NASDAQ")
        s.add(co)
        s.flush()
        for i, rev in enumerate(revenues or []):
            s.add(
                Financial(
                    company_id=co.id,
                    fiscal_year=2024 + i,
                    period="annual",
                    period_end_date=date(2024 + i, 1, 28),
                    revenue=rev,
                    total_assets=7e9,
                )
            )
        s.commit()
        return int(co.id)


def _digest(factory: sessionmaker[Session]) -> str | None:
    with factory() as s:
        return staleness.fundamentals_digest(s, "LULU")


def _dive(factory: sessionmaker[Session], co_id: int, digest: str | None, **kw: Any) -> int:
    with factory() as s:
        run = DeepDiveRun(
            company_id=co_id, ticker="LULU", mode=kw.pop("mode", "default"),
            inputs_sha256=digest, bull_narrative="[]", **kw,
        )  # fmt: skip
        s.add(run)
        s.commit()
        return int(run.id)


def _runs(factory: sessionmaker[Session]) -> list[DeepDiveRun]:
    with factory() as s:
        return list(s.execute(select(DeepDiveRun).order_by(DeepDiveRun.id)).scalars())


def _set_revenue(factory: sessionmaker[Session], value: float) -> None:
    with factory() as s:
        fin = s.execute(select(Financial).where(Financial.fiscal_year == 2024)).scalars().one()
        fin.revenue = value  # type: ignore[assignment]  # Column-style model
        s.commit()


def test_the_digest_follows_parser_values_not_prices_or_filing_dates(
    db: sessionmaker[Session],
) -> None:
    _company(db, [9.6e9, 10.6e9])
    before = _digest(db)
    assert before is not None and len(before) == 64
    with db() as s:
        for fin in s.execute(select(Financial)).scalars():
            fin.fx_rate_to_usd = 1.37  # type: ignore[assignment]
            fin.buyback_yield = 0.02  # type: ignore[assignment]
            fin.share_split_factor = 4.0  # type: ignore[assignment]
            fin.filed_date = date(2026, 3, 1)  # type: ignore[assignment]
        s.commit()
    assert _digest(db) == before
    _set_revenue(db, 9.7e9)
    assert _digest(db) != before


def test_a_formula_fix_changes_the_digest(db: sessionmaker[Session]) -> None:
    # Review of #28 (B3): derived ratios are read by frameworks directly.
    _company(db, [9.6e9])
    before = _digest(db)
    with db() as s:
        fin = s.execute(select(Financial)).scalars().one()
        fin.roic = 0.12  # type: ignore[assignment]  # Column-style model
        s.commit()
    assert _digest(db) != before


def test_every_writer_of_fundamentals_flags_changed_dives(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review of #28 (B1): the screener's FundamentalsTask calls _persist_financials directly.
    import data.pipeline as pipeline
    from data.edgar_fetcher import EdgarFinancialRow

    @contextmanager
    def session() -> Iterator[Session]:
        s = db()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(pipeline, "get_session", session)
    co = _company(db)
    row = EdgarFinancialRow(ticker="LULU", fiscal_year=2024, period="annual", revenue=9.6e9)
    row.period_end_date = date(2024, 1, 28)
    row.total_assets = 7e9
    assert pipeline._persist_financials("LULU", [row]) == []
    _dive(db, co, _digest(db))
    assert pipeline._persist_financials("LULU", [row]) == []  # same values again: not flagged
    row.revenue = 9.7e9
    assert pipeline._persist_financials("LULU", [row]) == [
        "LULU: 1 earlier deep dive(s) flagged stale (fundamentals changed); re-run"
    ]


def test_only_dives_whose_inputs_changed_are_flagged_and_none_deleted(
    db: sessionmaker[Session],
) -> None:
    co = _company(db, [9.6e9, 10.6e9])
    old = _digest(db)
    _dive(db, co, old)
    _dive(db, co, None)  # predates DEC-47: withheld anyway, not flagged here
    assert staleness.flag_dives_with_changed_inputs("LULU") == 0  # same inputs: released

    _set_revenue(db, 9.7e9)  # a restatement or a parser fix
    _dive(db, co, _digest(db))  # a dive on the new numbers
    assert staleness.flag_dives_with_changed_inputs("LULU") == 1
    runs = _runs(db)
    assert len(runs) == 3
    assert "fundamentals changed since this dive" in (runs[0].stale_reason or "")
    assert isinstance(runs[0].stale_at, datetime)
    assert runs[1].stale_reason is None and runs[2].stale_reason is None
    assert runs[0].bull_narrative == "[]"
    assert staleness.flag_dives_with_changed_inputs("LULU") == 0


def test_a_new_filing_changes_the_digest(db: sessionmaker[Session]) -> None:
    co = _company(db, [9.6e9])
    _dive(db, co, _digest(db))
    with db() as s:
        s.add(Financial(company_id=co, fiscal_year=2025, period="annual", revenue=10.6e9))
        s.commit()
    assert staleness.flag_dives_with_changed_inputs("LULU") == 1


def test_withheld_means_flagged_or_inputs_unknown(db: sessionmaker[Session]) -> None:
    co = _company(db, [9.6e9])
    known = _dive(db, co, _digest(db))
    unknown = _dive(db, co, None)
    flagged = _dive(db, co, _digest(db), stale_reason="fundamentals changed")
    assert staleness.run_withheld_reason(known) is None
    assert staleness.run_withheld_reason(unknown) == staleness.UNRECORDED_REASON
    assert staleness.run_withheld_reason(flagged) == "fundamentals changed"
    assert staleness.run_withheld_reason(9999) == "dive not found"


def test_stale_reason_follows_the_requested_mode(db: sessionmaker[Session]) -> None:
    co = _company(db, [9.6e9])
    _dive(db, co, _digest(db), mode="A", stale_reason="x")
    _dive(db, co, _digest(db), mode="B")
    assert staleness.latest_dive_stale_reason("lulu") is None  # the newest dive (mode B)
    assert staleness.latest_dive_stale_reason("LULU", "A") == "x"
    assert staleness.latest_dive_stale_reason("LULU", "B") is None


def test_a_dive_records_the_oldest_parser_it_read(db: sessionmaker[Session]) -> None:
    _company(db)
    with db() as s:
        for i, v in enumerate([2, 3, None]):
            s.add(
                FinancialSourceLog(
                    ticker="LULU", accession_number=f"a-{i}", form_type="10-K",
                    fiscal_year=2020 + i, period="annual", parser_version=v,
                )
            )  # fmt: skip
        s.commit()
        assert staleness.fundamentals_parser_version(s, "LULU") == 0
        assert staleness.latest_10k_accession(s, "LULU") == "a-2"
        assert staleness.fundamentals_parser_version(s, "NONE") is None


def test_the_refresh_hook_reports_flagged_dives(db: sessionmaker[Session]) -> None:
    from data.pipeline import _flag_dives_with_changed_inputs

    co = _company(db, [9.6e9])
    _dive(db, co, _digest(db))
    assert _flag_dives_with_changed_inputs("LULU") == []
    _set_revenue(db, 9.7e9)
    assert _flag_dives_with_changed_inputs("LULU") == [
        "LULU: 1 earlier deep dive(s) flagged stale (fundamentals changed); re-run"
    ]


def _no_call(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("a provider was called on a withheld dive")


def test_narrative_is_not_generated_on_a_withheld_dive(monkeypatch: pytest.MonkeyPatch) -> None:
    import deepdive.narrative as narrative

    monkeypatch.setattr(staleness, "latest_dive_stale_reason", lambda _t: "inputs not recorded")
    monkeypatch.setattr(narrative, "_call_provider", _no_call)
    with pytest.raises(narrative.NarrativeOnStaleDiveError, match="latest dive is stale"):
        narrative.generate_narrative(SimpleNamespace(ticker="LULU"), provider_pref="openai")  # type: ignore[arg-type]


def test_chat_is_refused_on_a_withheld_dive(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Follow-up F2: chat is the second LLM call site built on a dive's numbers.
    import deepdive.conversation as conversation
    from deepdive.narrative import NarrativeOnStaleDiveError

    co = _company(db, [9.6e9])
    run = _dive(db, co, None)
    monkeypatch.setattr(conversation, "_call_openai_chat", _no_call)
    monkeypatch.setattr(conversation, "_call_anthropic_chat", _no_call)
    with pytest.raises(NarrativeOnStaleDiveError, match="inputs not recorded"):
        conversation.generate_chat_response(None, [], "q", run_id=run)  # type: ignore[arg-type]


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
        generated_at=datetime(2026, 10, 25),
    )


def test_a_dive_flagged_during_generation_does_not_store_the_narrative(
    db: sessionmaker[Session],
) -> None:
    import deepdive.narrative as narrative

    co = _company(db, [9.6e9])
    _dive(db, co, _digest(db), stale_reason="flagged mid-call")
    with db() as s:
        run = s.execute(select(DeepDiveRun)).scalars().one()
        run.bull_narrative = None  # type: ignore[assignment]  # Column-style model
        s.commit()
    with pytest.raises(narrative.NarrativeOnStaleDiveError, match="not stored"):
        narrative.persist_narrative(_narrative())
    assert _runs(db)[0].bull_narrative is None


def test_the_view_is_built_from_and_attached_to_its_own_run(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Follow-up F5: the frozen view took overlays from the newest run by run_date.
    from deepdive import orchestrator

    co = _company(db, [9.6e9])
    older = _dive(db, co, _digest(db))
    _dive(db, co, _digest(db))
    seen: dict[str, Any] = {}

    def fake_load(_t: str, mode: str | None = None, run_id: int | None = None) -> Any:
        seen["run_id"] = run_id
        return SimpleNamespace(to_llm_context=lambda: '{"ticker": "LULU"}')

    monkeypatch.setattr("deepdive.scorecard_view.load_scorecard_view", fake_load)
    orchestrator._record_scorecard_view(older, "LULU", "default")
    assert seen["run_id"] == older
    runs = _runs(db)
    assert runs[0].scorecard_view_json == '{"ticker": "LULU"}'
    assert runs[0].scorecard_view_sha256 is not None and len(runs[0].scorecard_view_sha256) == 64
    assert runs[1].scorecard_view_json is None


def test_api_withholds_narrative_and_chat_on_a_dive_without_recorded_inputs(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    import deepdive.narrative as narrative
    from api.app import app

    co = _company(db, [9.6e9])
    _dive(db, co, None)
    monkeypatch.setattr(
        "deepdive.scorecard_view.load_scorecard_view",
        lambda _t, mode=None, run_id=None: SimpleNamespace(ticker="LULU"),
    )
    monkeypatch.setattr(narrative, "_call_provider", _no_call)
    client = TestClient(app)
    got = client.get("/dive/LULU/narrative").json()
    assert got == {"generated": False, "stale": True, "stale_reason": staleness.UNRECORDED_REASON}
    assert client.post("/dive/LULU/narrative").status_code == 409
    assert client.post("/dive/LULU/chat", params={"message": "why?"}).status_code == 409
    assert client.get("/dive/LULU/chat").json() == []  # review of #28 (B2): history withheld too
    with db() as s:
        assert s.execute(select(DeepDiveConversation)).first() is None  # user turn not stored


def _view(score: float) -> Any:
    from deepdive.scorecard_view import (
        CompanyHeader,
        CompositeView,
        FrameworkView,
        OverlayTriggerView,
        ScorecardView,
        StageView,
    )

    header: dict[str, Any] = {f: None for f in CompanyHeader.__dataclass_fields__}
    header.update(ticker="LULU", name="lululemon", ipo_date=date(2007, 7, 27),
                  latest_period_end=date(2026, 2, 1))  # fmt: skip
    return ScorecardView(
        ticker="LULU", run_date=date(2026, 10, 25), mode_used="default",
        company=CompanyHeader(**header),
        stage=StageView(stage="established", reasoning={"revenue": 9.6e9}),
        composite=CompositeView(score=score, verdict="monitor", mode_resolved="B",
                                weights_used={"F5": 0.5}, weights_renormalised=False),
        frameworks=[FrameworkView(code="F5", title="Growth Quality", score=7.0, max_score=10.0,
                                  verdict="partial", band="partial",
                                  key_signals=[("ROIC", "31%")], data_gaps=[])],
        overlay_triggers=[OverlayTriggerView(overlay_type="ICA", trigger_id="ICA-1",
                                             condition="c", relevant_numbers={"x": 1},
                                             framework_section="F5")],
        fetch_data_gaps=["gap"], overlay_verdicts={"ICA": "no_change"},
    )  # fmt: skip


def _frozen(view: Any) -> dict[str, str]:
    body = view.to_llm_context()
    return {
        "scorecard_view_json": body,
        "scorecard_view_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def test_a_frozen_view_rebuilds_to_the_same_json() -> None:
    from deepdive.scorecard_view import ScorecardView

    view = _view(6.5)
    body = view.to_llm_context()
    rebuilt = ScorecardView.from_dict(json.loads(body))
    assert rebuilt == view
    assert rebuilt.to_llm_context() == body
    d = json.loads(body)
    del d["frameworks"][0]["notes"], d["schema_version"]  # defaulted fields absent: still loads
    assert ScorecardView.from_dict(d).frameworks[0].notes == ""


@pytest.mark.parametrize(
    "tamper",
    [
        lambda d: d["company"].update(renamed_field=1),  # a field removed since the dive
        lambda d: d["company"].pop("ticker"),  # a field added since, with no default
    ],
)
def test_a_frozen_view_that_no_longer_fits_is_refused_not_raised(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, tamper: Any
) -> None:
    # Review of #32: schema drift must refuse the chat, not raise a 500.
    import data.db
    from deepdive.scorecard_view import load_frozen_scorecard_view

    monkeypatch.setattr("deepdive.scorecard_view.get_session", data.db.get_session)
    co = _company(db, [9.6e9])
    d = json.loads(_view(6.5).to_llm_context())
    tamper(d)
    body = json.dumps(d)
    sha = hashlib.sha256(body.encode()).hexdigest()
    run = _dive(db, co, None, scorecard_view_json=body, scorecard_view_sha256=sha)
    assert load_frozen_scorecard_view(run) is None
    edited = _dive(db, co, None, **{**_frozen(_view(6.5)), "scorecard_view_sha256": "0" * 64})
    assert load_frozen_scorecard_view(edited) is None  # body no longer matches its hash


def test_chat_grounds_in_the_view_its_dive_froze_not_todays(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # CLAUDE.md: chat is grounded in the frozen ScorecardView of one dive; it loaded today's.
    from fastapi.testclient import TestClient

    import data.db
    import deepdive.conversation as conversation
    from api.app import app

    monkeypatch.setattr("deepdive.scorecard_view.get_session", data.db.get_session)
    monkeypatch.setattr("deepdive.scorecard_view.load_scorecard_view", _no_call)
    co = _company(db, [9.6e9])
    run = _dive(db, co, _digest(db), **_frozen(_view(6.5)))
    seen: dict[str, Any] = {}

    def fake_chat(view: Any, _h: Any, _m: str, *, run_id: int, provider_pref: Any = None) -> Any:
        seen.update(score=view.composite.score, run_id=run_id)
        return SimpleNamespace(
            output=SimpleNamespace(reply="r", numeric_claims=[]), guard_warnings=[],
            provider="openai", model="m", prompt_tokens=1, completion_tokens=1, cost_usd=0.0,
        )  # fmt: skip

    monkeypatch.setattr(conversation, "generate_chat_response", fake_chat)
    client = TestClient(app)
    assert client.post("/dive/LULU/chat", params={"message": "why?"}).status_code == 200
    assert seen == {"score": 6.5, "run_id": run}

    bare = _dive(db, co, _digest(db))  # recorded inputs, but no frozen view
    assert client.post("/dive/LULU/chat", params={"message": "why?"}).status_code == 409
    with db() as s:  # refused before the user's turn is stored
        stored = select(DeepDiveConversation).where(DeepDiveConversation.deep_dive_run_id == bare)
        assert s.execute(stored).first() is None


def test_cli_chat_refuses_a_dive_without_a_frozen_view(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import data.db
    from cli.main import app

    monkeypatch.setattr("deepdive.scorecard_view.get_session", data.db.get_session)
    monkeypatch.setattr("deepdive.scorecard_view.load_scorecard_view", _no_call)
    co = _company(db, [9.6e9])
    older = _dive(db, co, _digest(db), **_frozen(_view(6.5)))
    _dive(db, co, _digest(db))  # the latest dive has no frozen view
    result = CliRunner().invoke(app, ["chat", "LULU"], input="/exit\n", env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "no readable frozen ScorecardView" in result.output

    # Verifier on #32: --run-id grounds in that run's view, not the newest one of its mode.
    result = CliRunner().invoke(
        app, ["chat", "LULU", "--run-id", str(older)], input="/exit\n", env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0, result.output
    assert "composite 6.50" in result.output


def test_export_withholds_the_narrative_of_a_withheld_dive() -> None:
    from deepdive.serializer import export_deepdive_markdown

    run = DeepDiveRun(
        ticker="LULU",
        mode="default",
        tier=2,
        run_date=datetime(2026, 5, 17),
        composite_score=5.0,
        verdict="watchlist",
        stale_reason="fundamentals changed",
        bull_narrative='[{"point": "x"}]',
        bear_narrative='[{"point": "y"}]',
        risk_factors='{"risks": []}',
    )
    md = export_deepdive_markdown(run)
    assert "**Stale:** fundamentals changed" in md
    assert "Withheld" in md
    assert "## Bull Case" not in md and "## Bear Case" not in md
