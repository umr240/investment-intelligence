"""Generating a v2 narrative (ADR-045 §2.4, §2.5): transport, prompt and the one repair.

Fake clients only; no tokens. The view is the golden set's real CRWD train view.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import openai
import pytest

import deepdive.narrative as narrative
from config.llm_prices import cost_usd
from config.settings import settings
from deepdive.narrative_eval.export import TRAIN
from deepdive.narrative_eval.graders import EvalOutput, grade, summary
from deepdive.narrative_output import SCHEMA_V2, NarrativeBodyV2, NarrativeProvider, NarrativeStatus
from deepdive.narrative_render import render_body
from deepdive.scorecard_view import ScorecardView

ROOT = Path(__file__).resolve().parents[1]
MODEL = "claude-sonnet-4-6"


@pytest.fixture(scope="module")
def crwd() -> ScorecardView:
    path = ROOT / "tests/fixtures/narrative_golden/train/CRWD.json"
    return ScorecardView.from_dict(json.loads(path.read_text("utf-8"))["view"])


def _point(detail: str, ids: list[str]) -> dict[str, Any]:
    return {"headline": "Cash generation", "detail": detail, "framework_codes": ["F5"],
            "numeric_claims": [{"field_id": i} for i in ids]}  # fmt: skip


def _reply(**over: Any) -> dict[str, Any]:
    """A clean v2 answer for CRWD, as the provider returns it."""
    return {
        "one_liner": "Growth at {F5.revenue_cagr_3y}; GAAP returns still negative.",
        "verdict": "WATCHLIST WITH TRIGGERS", "verdict_reason": "Composite {composite.score}.",
        "owner_operator_answer": "NOT_YET", "moat_direction": "UNKNOWN",
        "bull": [_point("FCF margin is {F5.fcf_margin}.", ["F5.fcf_margin"])],
        "bear": [_point("ROIC is {F5.roic}.", ["F5.roic"])], "risks": [],
        "triggers": [{"field_id": "F5.roic", "condition": "turns positive"}],
        "data_caveats": ["Short interest is withheld."], **over,
    }  # fmt: skip


INVENTED = _reply(one_liner="Revenue tripled to $77.7B.")  # fails the guard


class _Anthropic:
    """Answers each request with the next queued reply and keeps the request."""

    replies: list[Any] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, **_: Any) -> None:
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        _Anthropic.calls.append(copy.deepcopy(kwargs))
        reply = _Anthropic.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text, stop = (
            (reply, "end_turn") if isinstance(reply, str) else (json.dumps(reply), "end_turn")
        )
        if reply == "TRUNCATED":
            text, stop = '{"one_liner": "cut', "max_tokens"
        usage = SimpleNamespace(
            input_tokens=10_000, output_tokens=2_000,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )  # fmt: skip
        return SimpleNamespace(id=f"msg_{len(_Anthropic.calls)}", content=[
            SimpleNamespace(type="text", text=text)], usage=usage, stop_reason=stop)  # fmt: skip


@pytest.fixture(autouse=True)
def _client(monkeypatch: pytest.MonkeyPatch) -> None:
    _Anthropic.calls, _Anthropic.replies = [], []
    monkeypatch.setattr(anthropic, "Anthropic", _Anthropic)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-dummy-test")


def _generate(view: ScorecardView, *replies: Any) -> Any:
    _Anthropic.replies = list(replies)
    return narrative.generate_eval_narrative(view, NarrativeProvider.ANTHROPIC, MODEL)


# ── Generation ─────────────────────────────────────────────────────────────


def test_a_clean_answer_is_rendered_from_the_view_it_was_checked_against(
    crwd: ScorecardView, llm_rows: list[dict[str, Any]]
) -> None:
    out = _generate(crwd, _reply())
    assert (out.schema_version, out.status, out.guard_warnings) == (
        SCHEMA_V2,
        NarrativeStatus.OK,
        [],
    )
    assert out.rendered == render_body(out.body, crwd.citable_fields())
    assert out.rendered.bull[0].detail == "FCF margin is +29.8%."
    assert out.first_attempt is None and len(_Anthropic.calls) == 1
    (row,) = llm_rows
    assert (row["attempt"], row["guard_status"]) == (1, "ok")
    assert row["prompt_version"] == narrative.PROMPT_VERSION


def test_a_failed_answer_gets_one_repair_with_its_warnings(
    crwd: ScorecardView, llm_rows: list[dict[str, Any]]
) -> None:
    out = _generate(crwd, INVENTED, _reply())
    assert out.status == NarrativeStatus.OK and out.guard_warnings == []
    assert out.first_attempt is not None and out.first_attempt.one_liner.startswith(
        "Revenue tripled"
    )
    assert any("77.7b" in w for w in out.first_attempt_warnings)
    first, repair = _Anthropic.calls
    turns = repair["messages"]
    assert turns[0] == first["messages"][0] and [t["role"] for t in turns] == [
        "user",
        "assistant",
        "user",
    ]
    assert json.loads(turns[1]["content"])["one_liner"] == "Revenue tripled to $77.7B."
    assert "77.7b" in turns[2]["content"]  # the warnings go back to the model
    assert [(r["attempt"], r["guard_status"]) for r in llm_rows] == [(1, "warnings"), (2, "ok")]
    assert (out.prompt_tokens, out.completion_tokens) == (20_000, 4_000)
    assert out.cost_usd == round(2 * cost_usd(MODEL, 10_000, 2_000), 6)  # type: ignore[operator]


def test_a_repair_names_the_ids_an_unknown_one_likely_meant(crwd: ScorecardView) -> None:
    # The smoke test's gpt-4o-mini repair wrote {F3.gaap_net_income}; the view has ICA-3's.
    unknown = _reply(bear=[_point("Net income was {F3.gaap_net_income}.", ["F5.moat"])])
    _generate(crwd, unknown, _reply())
    warnings = _Anthropic.calls[1]["messages"][2]["content"]
    assert (
        "- 'F3.gaap_net_income' is not listed. Similar: 'ICA-3.gaap_net_income' "
        "(ICA-3 gaap net income, usd). Use one only if it is the same measure; "
        "otherwise state it in words, without a number."
    ) in warnings
    assert "- 'F5.moat' is not listed; state it in words, without a number." in warnings


def test_a_hint_shows_what_each_similar_id_measures_and_at_most_three(
    crwd: ScorecardView,
) -> None:
    fields = crwd.citable_fields()
    # A level metric's nearest ID is a growth rate: the label says so, and words stay an option.
    (hint,) = narrative._id_hints(["x: placeholder '{F5.revenue}' is not a citable field"], fields)
    assert "'F5.revenue_cagr_3y' (Revenue CAGR 3y, pct)" in hint and "in words" in hint
    (hint,) = narrative._id_hints(["triggers[0]: 'X.score' is not a citable field"], fields)
    assert hint.count("score)") == 3


def test_the_prompt_hash_covers_the_request_schema_and_the_repair_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = narrative._versioned_schema()
    assert "Limit: at most 600 characters." in json.dumps(before)  # restated in the schema
    monkeypatch.setattr(narrative, "_HINT_NEAR", "- '{bad}': try {near}.")
    assert narrative._versioned_schema() != before


def test_there_is_never_a_second_repair(crwd: ScorecardView) -> None:
    out = _generate(crwd, INVENTED, INVENTED, _reply())
    assert len(_Anthropic.calls) == 2 and len(_Anthropic.replies) == 1
    assert out.status == NarrativeStatus.GUARD_FAILED and out.first_attempt is not None


def test_a_repair_that_errors_keeps_the_first_answer(crwd: ScorecardView) -> None:
    out = _generate(crwd, INVENTED, "TRUNCATED")
    assert out.status == NarrativeStatus.GUARD_FAILED and out.first_attempt is None
    assert out.body.one_liner == "Revenue tripled to $77.7B."
    # The cut-off repair was billed: its tokens count, and its note is not "formatting".
    assert (out.prompt_tokens, out.completion_tokens) == (20_000, 4_000)
    assert out.cost_usd == round(2 * cost_usd(MODEL, 10_000, 2_000), 6)  # type: ignore[operator]
    assert not [w for w in out.guard_warnings if w.startswith("formatting: repair")]
    assert any(
        "repair: anthropic: anthropic stopped early: max_tokens" in w for w in out.guard_warnings
    )


def test_a_truncated_answer_is_a_provider_error(crwd: ScorecardView) -> None:
    with pytest.raises(narrative.NarrativeUnavailableError, match="stopped early: max_tokens"):
        _generate(crwd, "TRUNCATED")


# ── Transport and prompt ───────────────────────────────────────────────────


def test_anthropic_gets_structured_output_with_this_views_ids(crwd: ScorecardView) -> None:
    _generate(crwd, _reply())
    (call,) = _Anthropic.calls
    assert "tool_choice" not in call and "tools" not in call  # current models reject a forced tool
    schema = call["output_config"]["format"]["schema"]
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"maxLength"' not in text
    assert "do not choose it" in schema["properties"]["verdict"]["description"]  # kept inlining
    point = schema["properties"]["bull"]["items"]["properties"]
    ids = point["numeric_claims"]["items"]
    assert ids["properties"]["field_id"]["enum"] == list(crwd.citable_fields())
    feasible = sorted(f.code for f in crwd.frameworks if not f.is_unfeasible)
    assert point["framework_codes"]["items"]["enum"] == feasible
    assert "at most 600 characters" in schema["properties"]["verdict_reason"]["description"]
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(
        NarrativeBodyV2.model_fields
    )


def test_openai_gets_the_same_strict_schema(
    crwd: ScorecardView, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    class _OpenAI:
        def __init__(self, **_: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs: Any) -> Any:
            seen.append(kwargs)
            msg = SimpleNamespace(content=json.dumps(_reply()))
            usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
            return SimpleNamespace(id="c1", choices=[SimpleNamespace(message=msg)], usage=usage)

    monkeypatch.setattr(openai, "OpenAI", _OpenAI)
    monkeypatch.setattr(settings, "openai_api_key", "sk-dummy-test")
    narrative.generate_eval_narrative(crwd, NarrativeProvider.OPENAI, "gpt-4o-mini")
    fmt = seen[0]["response_format"]["json_schema"]
    assert fmt["strict"] is True and fmt["schema"] == narrative._request_schema(crwd)


def test_the_prompt_gives_the_verdict_and_every_citable_field(crwd: ScorecardView) -> None:
    prompt = narrative._build_user_prompt(crwd)
    assert "Verdict (copy it exactly): WATCHLIST WITH TRIGGERS" in prompt
    assert "F6.rule_of_40 = 48.94  (Rule of 40)" in prompt
    assert all(f"\n{fid} = " in prompt for fid in crwd.citable_fields())
    unknown = copy.deepcopy(crwd)
    unknown.composite.verdict = "mystery"
    with pytest.raises(ValueError, match="no narrative verdict"):
        narrative._build_user_prompt(unknown)


def test_extra_points_are_cut_to_the_schema_limit(crwd: ScorecardView) -> None:
    point = _point("FCF margin is {F5.fcf_margin}.", ["F5.fcf_margin"])
    out = _generate(crwd, _reply(bull=[point] * 7))
    assert len(out.body.bull) == 5
    assert "formatting: bull cut from 7 to 5 items" in out.guard_warnings


# ── Grading a repaired answer (§2.7 item 4) ────────────────────────────────


def test_the_first_attempt_is_the_headline_grade(crwd: ScorecardView) -> None:
    out = _generate(crwd, INVENTED, _reply())
    sha = "0" * 64
    ev = EvalOutput(case_id="CRWD", view_sha256=sha, model=MODEL, prompt_version=3, narrative=out,
                    input_tokens=20_000, output_tokens=4_000, latency_ms=9_000)  # fmt: skip
    by = {g.grader: g for g in grade(crwd, ev)}
    assert (by["G1"].status, by["G1r"].status) == ("fail", "pass")
    assert (by["G2"].status, by["G2r"].status, by["G5"].status) == ("pass", "pass", "pass")
    assert by["G6"].value == round(2 * cost_usd(MODEL, 10_000, 2_000), 6)  # type: ignore[operator]
    s = summary({"CRWD": grade(crwd, ev)}, {"CRWD": TRAIN}, TRAIN)
    assert (s["G1"], s["G1r"], s["repairs"]) == (0.0, 1.0, 1)
