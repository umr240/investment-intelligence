"""Every Anthropic call site must fit the 1.x SDK's `messages.create` signature.

anthropic 1.x dropped `temperature`/`top_p`/`top_k`; passing one raises TypeError
before the request is sent, which the call sites' API-error handlers don't catch.
No test reached `messages.create`, so the 1.x bump (PR #9) passed CI while
breaking all four calls. The fake client below rejects those arguments the same way.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

import deepdive.conversation as conversation
import deepdive.external_signals as external_signals
import deepdive.narrative as narrative
from config.settings import settings

_REMOVED_IN_1X = {"temperature", "top_p", "top_k"}

_NARRATIVE = {
    "one_liner": "Composite 7.0/10 — watchlist.",
    "bull": [{"headline": "h", "detail": "d", "framework_codes": [], "numeric_claims": []}],
    "bear": [{"headline": "b", "detail": "d", "framework_codes": [], "numeric_claims": []}],
    "risks": [],
    "data_caveats": [],
}


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
        name = kwargs["tool_choice"]["name"]
        block = SimpleNamespace(type="tool_use", name=name, input=_FakeAnthropic.tool_input)
        return SimpleNamespace(
            content=[block], usage=SimpleNamespace(input_tokens=1, output_tokens=1)
        )


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
    monkeypatch.setattr(narrative, "_build_system_prompt", lambda: "sys")
    monkeypatch.setattr(narrative, "_build_user_prompt", lambda _view: "user")
    _FakeAnthropic.tool_input = _NARRATIVE
    narrative._call_anthropic(None)  # type: ignore[arg-type]
    _assert_one_forced_tool_call("emit_narrative")


def test_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation, "_build_user_message", lambda *_: "user")
    _FakeAnthropic.tool_input = {"reply": "r", "numeric_claims": []}
    conversation._call_anthropic_chat(None, [], "q")  # type: ignore[arg-type]
    _assert_one_forced_tool_call("emit_chat_turn")


def test_external_signals() -> None:
    _FakeAnthropic.tool_input = {"signals": []}
    external_signals.extract_signals_via_llm("TST", "text", "url", "acc", "label")
    _assert_one_forced_tool_call("emit_signals")


def test_ceo_equity() -> None:
    _FakeAnthropic.tool_input = {"signals": []}
    external_signals.extract_ceo_equity_via_llm("TST", "<p>x</p>", "url", "acc", "label", "CEO")
    _assert_one_forced_tool_call("emit_signals")
