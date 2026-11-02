"""Live eval runs (ADR-047 §2.3, §2.7 items 2–4), with the provider stubbed: nothing is spent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import deepdive.narrative as narrative
import deepdive.narrative_eval.runner as runner
from config.llm_prices import UnpricedModelError
from deepdive.narrative_eval.export import TEST, TRAIN
from deepdive.narrative_eval.graders import replay
from deepdive.narrative_output import NarrativeOutput, NarrativeProvider
from deepdive.scorecard_view import ScorecardView
from tests.test_narrative_eval.test_export import _view
from tests.test_narrative_eval.test_graders import _body, _case


def _golden(tmp: Path, *views: tuple[ScorecardView, str]) -> Path:
    for view, split in views:
        (tmp / split).mkdir(parents=True, exist_ok=True)
        (tmp / split / f"{view.ticker}.json").write_text(json.dumps(_case(view, split)))
    return tmp


def _fake_narrative(
    view: ScorecardView, provider: NarrativeProvider, model: str
) -> NarrativeOutput:
    return NarrativeOutput(
        ticker=view.ticker, generated_at=datetime(2026, 10, 28), provider=provider,
        model=f"{model}-20261001", prompt_tokens=11_000, completion_tokens=3_700, body=_body(),
    )  # fmt: skip


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """An in-memory DB at the current schema, with keys set: what `refusal` checks."""
    from config.settings import settings
    from data.models.schema import Base

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def session() -> Iterator[Session]:
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr("data.db.get_session", session)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-dummy-test")
    monkeypatch.setattr(settings, "openai_api_key", "sk-dummy-test")
    yield
    engine.dispose()


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch, db: None) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []

    def fake(view: ScorecardView, provider: NarrativeProvider, model: str) -> NarrativeOutput:
        calls.append((view.ticker, provider.value, model))
        return _fake_narrative(view, provider, model)

    monkeypatch.setattr(narrative, "generate_eval_narrative", fake)
    monkeypatch.setattr(runner, "deferred_models", lambda _v: ["meta/dropped_model"])
    monkeypatch.setattr(runner, "last_call_id", lambda: 0)
    return calls


def test_run_case_packages_a_gradable_output(stubbed: list[Any], tmp_path: Path) -> None:
    view = _view("AAA")
    golden = _golden(tmp_path, (view, TEST))
    (case,) = runner.select_cases(golden, TEST)
    out = runner.run_case(case, NarrativeProvider.ANTHROPIC, "claude-sonnet-4-6")
    assert stubbed == [("AAA", "anthropic", "claude-sonnet-4-6")]
    # Filed under the requested model so a resumed run finds it; the served id stays inside.
    assert (out.model, out.narrative.model) == ("claude-sonnet-4-6", "claude-sonnet-4-6-20261001")
    assert (out.input_tokens, out.output_tokens) == (11_000, 3_700)  # no llm_calls row: narrative's
    assert out.lattice_deferred == ["meta/dropped_model"]
    assert out.prompt_version == narrative.PROMPT_VERSION
    runner.write_output(golden, out)
    result = replay(golden)
    assert result.drift == [] and set(result.grades[("claude-sonnet-4-6", out.prompt_version)]) == {
        "AAA"
    }


def test_run_case_takes_tokens_from_the_recorded_call(
    stubbed: list[Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "last_call_id", lambda: 7)
    monkeypatch.setattr(runner, "_usage", lambda row_id, ticker: (9_000, 3_000, 2_000, 0, 4_200))
    (case,) = runner.select_cases(_golden(tmp_path, (_view("AAA"), TRAIN)), TRAIN)
    out = runner.run_case(case, NarrativeProvider.OPENAI, "gpt-4o-mini")
    assert (out.input_tokens, out.cache_read_tokens, out.latency_ms) == (9_000, 2_000, 4_200)


def test_estimate_prices_every_case_and_refuses_an_unpriced_model(tmp_path: Path) -> None:
    golden = _golden(tmp_path, (_view("AAA"), TEST), (_view("BBB"), TEST))
    cases = runner.select_cases(golden, TEST)
    one = runner.estimate_cost(cases[:1], "claude-sonnet-4-6")
    assert one > 3_800 * 15 / 1e6  # at least the estimated output
    assert runner.estimate_cost(cases, "claude-sonnet-4-6") == pytest.approx(2 * one, rel=0.05)
    worst = runner.estimate_cost(cases[:1], "claude-sonnet-4-6", repairs=True)
    assert worst > 2 * one  # a repair's input also carries the failed answer
    with pytest.raises(UnpricedModelError):
        runner.estimate_cost(cases, "claude-sonnet-5")


def test_select_cases_by_split(tmp_path: Path) -> None:
    golden = _golden(tmp_path, (_view("AAA"), TEST), (_view("BBB"), TRAIN))
    assert [c["case_id"] for c in runner.select_cases(golden, TEST)] == ["AAA"]
    assert [c["case_id"] for c in runner.select_cases(golden, "all")] == ["AAA", "BBB"]


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli(*args: str, input: str | None = None) -> Any:
    from typer.testing import CliRunner

    from cli.main import app

    return CliRunner().invoke(app, ["narrative", "eval", "run", *args], input=input,
                              env={"COLUMNS": "200"})  # fmt: skip


def test_cli_refuses_an_unpriced_model_before_spending(stubbed: list[Any], tmp_path: Path) -> None:
    golden = _golden(tmp_path, (_view("AAA"), TEST))
    out = _cli("--provider", "anthropic", "--model", "claude-sonnet-5", "--golden", str(golden))
    assert out.exit_code == 2 and "Copy its price row" in out.output and stubbed == []


def test_cli_spends_only_after_confirmation_and_resumes(stubbed: list[Any], tmp_path: Path) -> None:
    golden = _golden(tmp_path, (_view("AAA"), TEST), (_view("BBB"), TEST), (_view("CCC"), TRAIN))
    args = ["--provider", "anthropic", "--model", "claude-sonnet-4-6", "--golden", str(golden)]
    declined = _cli(*args, input="n\n")
    assert declined.exit_code == 1 and "estimated $" in declined.output and stubbed == []
    first = _cli(*args, "--limit", "1", "--yes")
    assert first.exit_code == 0, first.output
    assert [c[0] for c in stubbed] == ["AAA"]  # test split only, by default
    second = _cli(*args, "--yes")
    assert [c[0] for c in stubbed] == ["AAA", "BBB"]  # AAA already had an output
    assert "1 written, 0 failed, 0 not run" in second.output
    assert "Nothing to run" in _cli(*args, "--yes").output


def test_cli_rejects_a_bad_provider_or_split(tmp_path: Path) -> None:
    golden = str(_golden(tmp_path, (_view("AAA"), TEST)))
    assert _cli("--provider", "gemini", "--model", "x", "--golden", golden).exit_code == 2
    bad = _cli("--provider", "openai", "--model", "x", "--split", "dev", "--golden", golden)
    assert bad.exit_code == 2


# ── The narrative entry point ──────────────────────────────────────────────


def test_eval_narrative_uses_the_given_model_once_and_skips_the_staleness_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data.dive_staleness as staleness
    from deepdive.llm_calls import _ATTEMPT

    def stale(_t: str) -> str:
        raise AssertionError("a golden case is not a live dive")

    seen: list[tuple[Any, ...]] = []

    def provider(p: NarrativeProvider, view: ScorecardView, model: str | None) -> Any:
        seen.append((p, model, (_ATTEMPT.get() or {}).get("purpose")))
        raise narrative._ProviderError("down")

    monkeypatch.setattr(staleness, "latest_dive_stale_reason", stale)
    monkeypatch.setattr(narrative, "_call_provider", provider)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.generate_eval_narrative(_view(), NarrativeProvider.OPENAI, "gpt-4o")
    assert seen == [(NarrativeProvider.OPENAI, "gpt-4o", "eval")]  # no fallback provider


def test_refusal_names_what_would_waste_the_run(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import settings
    from data.db import get_session

    anthropic, openai = NarrativeProvider.ANTHROPIC, NarrativeProvider.OPENAI
    assert runner.refusal(anthropic, "claude-sonnet-4-6") is None
    assert runner.refusal(openai, "gpt-4o-mini") is None
    assert "not a openai model" in str(runner.refusal(openai, "claude-sonnet-4-6"))
    assert "not a anthropic model" in str(runner.refusal(anthropic, "gpt-4o"))
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert "OPENAI_API_KEY" in str(runner.refusal(openai, "gpt-4o-mini"))
    with get_session() as s:  # a DB still at 0008
        s.execute(text("ALTER TABLE llm_calls DROP COLUMN purpose"))
    assert "migration 0009" in str(runner.refusal(anthropic, "claude-sonnet-4-6"))
    with get_session() as s:  # e.g. a mistyped sqlite path: an empty DB
        s.execute(text("DROP TABLE llm_calls"))
    assert "no llm_calls table" in str(runner.refusal(anthropic, "claude-sonnet-4-6"))


def test_cli_refuses_before_the_estimate(stubbed: list[Any], tmp_path: Path) -> None:
    golden = _golden(tmp_path, (_view("AAA"), TEST))
    out = _cli("--provider", "openai", "--model", "claude-sonnet-4-6", "--golden", str(golden))
    assert out.exit_code == 2 and "Not starting" in out.output
    assert "estimated" not in out.output and stubbed == []


def test_cli_reports_nothing_to_run_before_any_refusal(
    stubbed: list[Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from config.settings import settings

    golden = _golden(tmp_path, (_view("AAA"), TEST))
    args = ["--provider", "anthropic", "--model", "claude-sonnet-4-6", "--golden", str(golden)]
    assert _cli(*args, "--yes").exit_code == 0
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    out = _cli(*args, "--yes")
    assert out.exit_code == 0 and "Nothing to run" in out.output, out.output


def test_cli_stops_after_consecutive_failures(
    stubbed: list[Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def broke(view: ScorecardView, provider: NarrativeProvider, model: str) -> NarrativeOutput:
        calls.append(view.ticker)
        raise narrative.NarrativeUnavailableError("credit balance is too low")

    monkeypatch.setattr(narrative, "generate_eval_narrative", broke)
    golden = _golden(tmp_path, *((_view(t), TEST) for t in ("AAA", "BBB", "CCC", "DDD", "EEE")))
    args = ["--provider", "anthropic", "--model", "claude-sonnet-4-6", "--golden", str(golden)]
    out = _cli(*args, "--yes")
    assert calls == ["AAA", "BBB", "CCC"] and "3 failures in a row" in out.output, out.output
    assert "0 written, 3 failed, 2 not run" in out.output and out.exit_code == 1


def test_usage_counts_every_narrative_call_of_the_case(db: None) -> None:
    from data.db import get_session
    from data.models.schema import LlmCall

    def row(site: str, tokens: int, purpose: str | None = "eval", ticker: str = "AAA") -> LlmCall:
        return LlmCall(call_site=site, attempt=1, provider="anthropic", model="m",
                       prompt_version=2, prompt_sha256="x", input_tokens=tokens,
                       output_tokens=tokens // 10, cache_write_tokens=0, cache_read_tokens=1,
                       latency_ms=tokens // 100, status="ok", purpose=purpose,
                       ticker=ticker)  # fmt: skip

    with get_session() as s:
        s.add(row("narrative", 5_000))  # an earlier case
        s.commit()
    before = runner.last_call_id()
    with get_session() as s:  # this case: a first attempt and its repair (ADR-045 §2.7 item 4)
        s.add_all([row("narrative", 10_000), row("chat", 99_000), row("narrative", 12_000),
                   row("narrative", 7_000, purpose=None),  # a UI narrative meanwhile
                   row("narrative", 8_000, ticker="BBB")])  # fmt: skip
        s.commit()
    assert runner._usage(before, "AAA") == (22_000, 2_200, 2, 0, 220)
    assert runner._usage(runner.last_call_id(), "AAA") is None
