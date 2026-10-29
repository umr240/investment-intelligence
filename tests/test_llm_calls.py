"""ADR-048: every LLM call attempt is recorded, priced from a dated table, and versioned.

All offline: fake clients, an in-memory database, no tokens.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx
import openai
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import deepdive.conversation as conversation
import deepdive.external_signals as external_signals
import deepdive.llm_calls as llm_calls
import deepdive.narrative as narrative
from config.llm_prices import PRICES, PRICES_AS_OF, UnpricedModelError, cost_usd, price_for
from config.settings import settings
from deepdive.narrative_output import NarrativeProvider
from tests.test_narrative_eval.test_export import _view

# The real writers, saved before the autouse `llm_rows` fixture replaces them.
_WRITE, _UPDATE = llm_calls._write, llm_calls._update

URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm"
ACC = "0000000001-26-000001"

# (call site, prompt) -> {PROMPT_VERSION: sha256 of system prompt + schema}. A prompt
# change without a version bump fails here: bump the module's PROMPT_VERSION and add a row.
RECORDED = {
    ("narrative", "narrative"): {
        1: "249f31cfb12ff9f6bf49a8bb2c5cd47fd6c691d7e0b41bdbaedd2ae1e26c9f5b",
        2: "82453c483981084f95f1ff951cb1a03d11539aca0eecf2a4817d806f216f22fe",  # ADR-045 schema v2
        3: "e05770e18b62d867c1c98ba7d422cd30e9ca216f9d6724e68e7c6bb4958a1f53",  # S5 fixes
    },
    ("chat", "chat"): {1: "cf660ece09c18355cebe42b2576c5a56e63c5d3d6c8dce53d37ea9ae04783ee9"},
    ("external_signals", "8-K"): {
        1: "de2629661b26aa2f989278dbe111ff5d996d11c1ebc02d82f96035aada47f2ef",
    },
    ("external_signals", "DEF 14A"): {
        1: "fb1f97e10d29fdf5aa7e618e86e5080c071f4ec1bca6ce11d3d202a019f78200",
    },
}

_POINT = {"headline": "h", "detail": "d", "framework_codes": [], "numeric_claims": []}
_NARRATIVE = {  # schema v2, for `_view()` (its one citable field is composite.score)
    "one_liner": "Composite {composite.score}.", "verdict": "WATCHLIST WITH TRIGGERS",
    "verdict_reason": "r", "owner_operator_answer": "NOT_YET", "moat_direction": "UNKNOWN",
    "bull": [_POINT], "bear": [_POINT], "risks": [],
    "triggers": [{"field_id": "composite.score", "condition": "rises"}], "data_caveats": [],
}  # fmt: skip


class _FakeAnthropic:
    tool_input: dict[str, Any] = {}

    def __init__(self, **_: Any) -> None:
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        if "output_config" in kwargs:  # structured output (the narrative, ADR-045)
            block = SimpleNamespace(type="text", text=json.dumps(_FakeAnthropic.tool_input))
        else:
            name = kwargs["tool_choice"]["name"]
            block = SimpleNamespace(type="tool_use", name=name, input=_FakeAnthropic.tool_input)
        usage = SimpleNamespace(
            input_tokens=1_000, output_tokens=200,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )  # fmt: skip
        return SimpleNamespace(id="msg_1", content=[block], usage=usage, stop_reason="end_turn")


class _DownOpenAI:
    def __init__(self, **_: Any) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_: Any) -> Any:
        request = cast(Any, httpx.Request("POST", "https://api.openai.com"))  # SDK types httpx2
        raise openai.APIConnectionError(request=request)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(openai, "OpenAI", _DownOpenAI)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-dummy-test")
    monkeypatch.setattr(settings, "openai_api_key", "sk-dummy-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-test")


# ── Prices ────────────────────────────────────────────────────────────────


def test_every_configured_model_has_a_dated_price() -> None:
    extraction = os.getenv("ANTHROPIC_EXTRACTION_MODEL", "claude-sonnet-4-6")
    configured = {settings.openai_narrative_model, settings.anthropic_narrative_model, extraction}
    assert {m for m in configured if price_for(m) is None} == set()
    assert PRICES_AS_OF <= date.today()


def test_cost_counts_cached_tokens_at_their_own_rate() -> None:
    p = PRICES["claude-sonnet-4-6"]
    expected = (1_000 * p.input + 200 * p.output + 500 * p.cache_read) / 1e6
    assert cost_usd("claude-sonnet-4-6", 1_000, 200, cache_read_tokens=500) == round(expected, 6)
    assert price_for("gpt-4o-mini-2024-07-18") == PRICES["gpt-4o-mini"]


def test_an_unpriced_model_has_no_cost_rather_than_a_guess() -> None:
    assert cost_usd("mystery-model", 1_000, 200) is None
    assert price_for("gpt-4o-audio-preview") is None  # a variant, not a snapshot
    assert price_for("claude-haiku-4-5-20251001") == PRICES["claude-haiku-4-5"]


def test_token_usage_reads_both_providers() -> None:
    oa = SimpleNamespace(usage=SimpleNamespace(
        prompt_tokens=1_000, completion_tokens=50,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
    ))  # fmt: skip
    an = SimpleNamespace(usage=SimpleNamespace(
        input_tokens=600, output_tokens=50,
        cache_creation_input_tokens=100, cache_read_input_tokens=400,
    ))  # fmt: skip
    assert llm_calls.token_usage(oa) == (600, 50, 0, 400)
    assert llm_calls.token_usage(an) == (600, 50, 100, 400)
    assert llm_calls.token_usage(None) == (0, 0, 0, 0)


# ── One row per attempt ───────────────────────────────────────────────────


def _narrate(monkeypatch: pytest.MonkeyPatch) -> Any:
    import data.dive_staleness as staleness

    monkeypatch.setattr(staleness, "latest_dive_stale_reason", lambda _t: None)
    monkeypatch.setattr(staleness, "latest_run_id", lambda _t: 7)
    monkeypatch.setattr(narrative, "_build_user_prompt", lambda _v: "user")
    monkeypatch.setattr("deepdive.narrative_guard.validate", lambda _b, _v: [])
    _FakeAnthropic.tool_input = _NARRATIVE
    return narrative.generate_narrative(_view("LULU"), provider_pref="openai")


def test_a_failed_attempt_and_its_fallback_are_both_recorded(
    monkeypatch: pytest.MonkeyPatch, llm_rows: list[dict[str, Any]]
) -> None:
    out = _narrate(monkeypatch)
    failed, ok = llm_rows
    assert (failed["attempt"], failed["provider"], failed["status"]) == (1, "openai", "error")
    assert (failed["error_class"], failed["cost_usd"]) == ("APIConnectionError", 0.0)
    assert (ok["attempt"], ok["provider"], ok["status"], ok["request_id"]) == (
        2, "anthropic", "ok", "msg_1",
    )  # fmt: skip
    assert {r["call_site"] for r in llm_rows} == {"narrative"}
    assert {(r["ticker"], r["run_id"]) for r in llm_rows} == {("LULU", 7)}
    assert (ok["guard_status"], ok["warning_count"]) == ("ok", 0)
    assert ok["cost_usd"] == cost_usd(settings.anthropic_narrative_model, 1_000, 200)
    assert out.cost_usd == ok["cost_usd"]


def test_an_eval_call_is_marked_and_real_use_is_not(
    monkeypatch: pytest.MonkeyPatch, llm_rows: list[dict[str, Any]]
) -> None:
    _narrate(monkeypatch)
    assert {r["purpose"] for r in llm_rows} == {None}
    llm_rows.clear()
    model = "claude-haiku-4-5"
    narrative.generate_eval_narrative(_view("LULU"), NarrativeProvider.ANTHROPIC, model)
    (row,) = llm_rows  # one provider, no fallback
    assert (row["purpose"], row["model"], row["run_id"], row["provider"]) == (
        "eval", "claude-haiku-4-5", None, "anthropic",
    )  # fmt: skip


def test_a_call_whose_row_was_not_written_is_still_the_last_call(
    monkeypatch: pytest.MonkeyPatch, llm_rows: list[dict[str, Any]]
) -> None:
    # Verifier on #37: a failed write left the previous row's id and cost behind, so the
    # guard verdict went to the wrong row and a chat turn was charged $0.
    def write_once(row: dict[str, Any]) -> int | None:
        if row["status"] == "ok":
            return None  # "database is locked"
        llm_rows.append(row)
        return len(llm_rows)

    monkeypatch.setattr(llm_calls, "_write", write_once)
    out = _narrate(monkeypatch)
    (failed,) = llm_rows
    assert "guard_status" not in failed  # not annotated with the later call's verdict
    assert out.cost_usd == cost_usd(settings.anthropic_narrative_model, 1_000, 200)


def test_recording_never_fails_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: Any, **_k: Any) -> float:
        raise ValueError("bad usage object")

    monkeypatch.setattr(llm_calls, "cost_usd", broken)
    with llm_calls.recorded_call(
        call_site="chat", provider="anthropic", model="m", prompt_version=1,
        system_prompt="s", schema={},
    ) as call:  # fmt: skip
        call.response = SimpleNamespace(usage=None)
    assert llm_calls.last_call_cost() is None


def test_prompt_text_is_never_recorded(
    monkeypatch: pytest.MonkeyPatch, llm_rows: list[dict[str, Any]]
) -> None:
    _narrate(monkeypatch)
    system = narrative._build_system_prompt()
    for row in llm_rows:
        assert not any(isinstance(v, str) and system[:40] in v for v in row.values())


def test_a_changed_prompt_needs_a_new_version(
    monkeypatch: pytest.MonkeyPatch, llm_rows: list[dict[str, Any]]
) -> None:
    _narrate(monkeypatch)
    monkeypatch.setattr(conversation, "_build_user_message", lambda *_: "user")
    _FakeAnthropic.tool_input = {"reply": "r", "numeric_claims": []}
    conversation._call_anthropic_chat(None, [], "q")  # type: ignore[arg-type]
    _FakeAnthropic.tool_input = {"signals": []}
    external_signals.extract_signals_via_llm("TST", "text", URL, ACC, "label")
    external_signals.extract_ceo_equity_via_llm(
        "TST", "<p>x</p>", URL, ACC, "label", "CEO", filing_date=date(2026, 4, 28)
    )
    got = [r for r in llm_rows if r["status"] == "ok"]
    seen = [(r["call_site"], r["prompt_version"], r["prompt_sha256"]) for r in got]
    for (site, prompt), (call_site, version, sha) in zip(RECORDED, seen, strict=True):
        assert site == call_site
        assert version in RECORDED[(site, prompt)], f"{site} {prompt}: add a row for v{version}"
        assert RECORDED[(site, prompt)][version] == sha, (
            f"{site} {prompt}: prompt or schema changed; bump PROMPT_VERSION and add its hash"
        )


def test_chat_never_calls_an_unpriced_model(
    monkeypatch: pytest.MonkeyPatch, llm_rows: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr("data.dive_staleness.run_withheld_reason", lambda _r: None)
    monkeypatch.setattr(settings, "anthropic_narrative_model", "mystery-model")
    with pytest.raises(narrative.NarrativeUnavailableError, match="priced model"):
        conversation.generate_chat_response(
            None,  # type: ignore[arg-type]
            [],
            "q",
            run_id=1,
            provider_pref="anthropic_only",
        )
    assert llm_rows == []
    with pytest.raises(UnpricedModelError):
        monkeypatch.setenv("ANTHROPIC_EXTRACTION_MODEL", "mystery-model")
        external_signals.extract_signals_via_llm("TST", "text", URL, ACC, "label")
    assert llm_rows == []


# ── Persistence and the stats command ─────────────────────────────────────


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    from data.models.schema import Base

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

    monkeypatch.setattr("data.db.get_session", session)
    yield factory
    engine.dispose()


def _row(**kw: Any) -> dict[str, Any]:
    return {
        "call_site": "narrative", "ticker": "LULU", "run_id": 7, "attempt": 1,
        "provider": "anthropic", "model": "claude-sonnet-4-6", "prompt_version": 1,
        "prompt_sha256": "0" * 64, "input_tokens": 1_000, "output_tokens": 200,
        "cache_write_tokens": 0, "cache_read_tokens": 0, "latency_ms": 2_500,
        "status": "ok", "error_class": None, "cost_usd": 0.006, "request_id": "msg_1", **kw,
    }  # fmt: skip


def test_rows_are_written_and_annotated(db: sessionmaker[Session]) -> None:
    from data.models.schema import LlmCall

    row_id = _WRITE(_row())
    assert row_id is not None
    _UPDATE(row_id, {"guard_status": "warnings", "warning_count": 2})
    with db() as s:
        rec: Any = s.execute(select(LlmCall)).scalars().one()
        assert (rec.cost_usd, rec.guard_status, rec.warning_count) == (0.006, "warnings", 2)


def test_a_failed_write_never_fails_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Any:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("data.db.get_session", broken)
    assert _WRITE(_row()) is None
    _UPDATE(1, {"guard_status": "ok"})  # logged, not raised


def test_llm_stats(db: sessionmaker[Session]) -> None:
    from typer.testing import CliRunner

    from cli.main import app

    _WRITE(_row())
    _WRITE(_row(attempt=2, status="error", error_class="APIConnectionError", cost_usd=0.0))
    _WRITE(_row(model="mystery-model", cost_usd=None))
    result = CliRunner().invoke(app, ["llm", "stats"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "claude-sonnet-4-6" in result.output and "Per ok call" in result.output
    assert result.output.count("$0.0060") == 2  # total, and per successful call
    assert "mystery-model" in result.output and "—" in result.output


def test_llm_stats_keeps_eval_spend_on_its_own_row(db: sessionmaker[Session]) -> None:
    from typer.testing import CliRunner

    from cli.main import app

    _WRITE(_row())
    _WRITE(_row(purpose="eval", cost_usd=0.5))
    result = CliRunner().invoke(app, ["llm", "stats"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if "claude-sonnet-4-6" in line]
    assert len(lines) == 2
    assert any("eval" in line and "$0.5000" in line for line in lines)
    assert any("use" in line and "$0.0060" in line for line in lines)
