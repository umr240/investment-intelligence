"""Every Anthropic call site must fit the 1.x SDK's `messages.create` signature.

anthropic 1.x dropped `temperature`/`top_p`/`top_k`; passing one raises TypeError
before the request is sent, which the call sites' API-error handlers don't catch.
No test reached `messages.create`, so the 1.x bump (PR #9) passed CI while
breaking all four calls. The fake client below rejects those arguments the same way.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

import deepdive.conversation as conversation
import deepdive.external_signals as external_signals
import deepdive.narrative as narrative
from config.settings import settings
from tests.test_narrative_eval.test_export import _view

_REMOVED_IN_1X = {"temperature", "top_p", "top_k"}

_POINT = {"headline": "h", "detail": "d", "framework_codes": [], "numeric_claims": []}
_NARRATIVE = {  # schema v2, for `_view()` (its one citable field is composite.score)
    "one_liner": "o", "verdict": "WATCHLIST WITH TRIGGERS", "verdict_reason": "r",
    "owner_operator_answer": "NOT_YET", "moat_direction": "UNKNOWN", "bull": [_POINT],
    "bear": [_POINT], "risks": [],
    "triggers": [{"field_id": "composite.score", "condition": "rises"}], "data_caveats": [],
}  # fmt: skip


class _FakeAnthropic:
    calls: list[dict[str, Any]] = []
    tool_input: dict[str, Any] = {}

    def __init__(self, **_: Any) -> None:
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        removed = _REMOVED_IN_1X & kwargs.keys()
        if removed:
            raise TypeError(
                f"Messages.create() got an unexpected keyword argument {sorted(removed)[0]!r}"
            )
        _FakeAnthropic.calls.append(kwargs)
        if "output_config" in kwargs:
            block = SimpleNamespace(type="text", text=json.dumps(_FakeAnthropic.tool_input))
        else:
            name = kwargs["tool_choice"]["name"]
            block = SimpleNamespace(type="tool_use", name=name, input=_FakeAnthropic.tool_input)
        return SimpleNamespace(
            content=[block], usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )  # fmt: skip


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAnthropic.calls = []
    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-dummy-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-test")


def _assert_one_forced_tool_call(tool: str) -> None:
    assert len(_FakeAnthropic.calls) == 1
    assert _FakeAnthropic.calls[0]["tool_choice"] == {"type": "tool", "name": tool}


def test_narrative(monkeypatch: pytest.MonkeyPatch) -> None:
    # Structured output, never a forced tool call: current models reject one (ADR-045 §2.4).
    monkeypatch.setattr(narrative, "_build_system_prompt", lambda: "sys")
    monkeypatch.setattr(narrative, "_build_user_prompt", lambda _view: "user")
    _FakeAnthropic.tool_input = _NARRATIVE
    narrative._call_anthropic(_view())
    (call,) = _FakeAnthropic.calls
    assert "tool_choice" not in call and "tools" not in call
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema" and "$ref" not in json.dumps(fmt["schema"])
    trigger = fmt["schema"]["properties"]["triggers"]["items"]
    assert trigger["properties"]["field_id"]["enum"] == ["composite.score", "F2.score"]


def test_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation, "_build_user_message", lambda *_: "user")
    _FakeAnthropic.tool_input = {"reply": "r", "numeric_claims": []}
    conversation._call_anthropic_chat(None, [], "q")  # type: ignore[arg-type]
    _assert_one_forced_tool_call("emit_chat_turn")


_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/x.htm"
_ACC = "0000000001-26-000001"


def test_external_signals() -> None:
    _FakeAnthropic.tool_input = {"signals": []}
    external_signals.extract_signals_via_llm("TST", "text", _URL, _ACC, "label")
    _assert_one_forced_tool_call("emit_signals")


def test_ceo_equity() -> None:
    from datetime import date

    _FakeAnthropic.tool_input = {"signals": []}
    external_signals.extract_ceo_equity_via_llm(
        "TST", "<p>x</p>", _URL, _ACC, "label", "CEO", filing_date=date(2026, 4, 28)
    )
    _assert_one_forced_tool_call("emit_signals")
