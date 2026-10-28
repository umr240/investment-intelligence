"""Live eval runs (ADR-047 §2.3, §2.7 items 2–4), with the provider stubbed: nothing is spent."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

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
def stubbed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []

    def fake(view: ScorecardView, provider: NarrativeProvider, model: str) -> NarrativeOutput:
        calls.append((view.ticker, provider.value, model))
        return _fake_narrative(view, provider, model)

    monkeypatch.setattr(narrative, "generate_eval_narrative", fake)
    monkeypatch.setattr(runner, "deferred_models", lambda _v: ["meta/dropped_model"])
    monkeypatch.setattr(runner, "last_call_id", lambda: None)
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
    monkeypatch.setattr(runner, "_usage", lambda row_id: (9_000, 3_000, 2_000, 0, 4_200))
    (case,) = runner.select_cases(_golden(tmp_path, (_view("AAA"), TRAIN)), TRAIN)
    out = runner.run_case(case, NarrativeProvider.OPENAI, "gpt-4o-mini")
    assert (out.input_tokens, out.cache_read_tokens, out.latency_ms) == (9_000, 2_000, 4_200)


def test_estimate_prices_every_case_and_refuses_an_unpriced_model(tmp_path: Path) -> None:
    golden = _golden(tmp_path, (_view("AAA"), TEST), (_view("BBB"), TEST))
    cases = runner.select_cases(golden, TEST)
    one = runner.estimate_cost(cases[:1], "claude-sonnet-4-6")
    assert one > 3_800 * 15 / 1e6  # at least the estimated output
    assert runner.estimate_cost(cases, "claude-sonnet-4-6") == pytest.approx(2 * one, rel=0.05)
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
    assert "1 written, 0 failed" in second.output
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
