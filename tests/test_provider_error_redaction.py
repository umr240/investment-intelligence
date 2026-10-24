"""A provider's 401 must not carry a key fragment out of the LLM layer.

OpenAI's 401 echoes a masked key (`sk-proj-ab***…wxyz`). The per-provider
warning in narrative.py was scrubbed, but the "all providers failed" error was
not — the CLI printed it and the API returned it as a 503 body — and chat
scrubbed neither its log line nor its final error (Security §1).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import deepdive.conversation as conversation
import deepdive.narrative as narrative
from config.settings import settings

_FRAGMENT = "sk-proj-ab" + "*" * 20 + "wxyz"


def _reject(*_: object, **__: object) -> None:
    raise narrative._ProviderError(
        f"openai transport: AuthenticationError: Incorrect API key provided: {_FRAGMENT}."
    )


@pytest.fixture(autouse=True)
def _openai_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "sk-dummy-test")
    # The DEC-46 stale-dive gate runs before any provider; keep it off the real DB.
    monkeypatch.setattr("data.dive_staleness.latest_dive_stale_reason", lambda _t: None)


def _leaks(text: str) -> bool:
    return "wxyz" in text or "sk-proj" in text


def test_narrative_final_error_is_redacted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(narrative, "_call_provider", _reject)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(narrative.NarrativeUnavailableError) as exc,
    ):
        narrative.generate_narrative(SimpleNamespace(ticker="X"), provider_pref="openai_only")  # type: ignore[arg-type]
    assert "[redacted]" in str(exc.value)
    assert not _leaks(str(exc.value))
    assert not _leaks(caplog.text)


def test_chat_log_and_final_error_are_redacted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(conversation, "_call_openai_chat", _reject)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(narrative.NarrativeUnavailableError) as exc,
    ):
        conversation.generate_chat_response(None, [], "q", provider_pref="openai_only")  # type: ignore[arg-type]
    assert "[redacted]" in str(exc.value)
    assert not _leaks(str(exc.value))
    assert not _leaks(caplog.text)
