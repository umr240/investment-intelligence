"""One `llm_calls` row per LLM call attempt (ADR-048 §2.1).

The allow-listed call sites wrap each request in `recorded_call`; their
provider-fallback loops set the attempt with `attempt_context`. No SDK is
imported here, and no prompt text is stored, only its hash (§2.4). Recording
never fails a call: a write error is logged and dropped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from config.llm_prices import cost_usd

logger = logging.getLogger(__name__)

_ATTEMPT: ContextVar[dict[str, Any] | None] = ContextVar("llm_attempt", default=None)
# The latest call in this context, even when its row was not written (id None), so a
# failed write never leaves an earlier call's cost or id to be read.
_LAST: ContextVar[tuple[int | None, float | None] | None] = ContextVar("llm_last", default=None)


def prompt_sha256(system_prompt: str, schema: dict[str, Any]) -> str:
    """Hash of what defines a prompt version: the system prompt and the output schema."""
    body = system_prompt + "\n" + json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@contextmanager
def attempt_context(
    *,
    ticker: str | None = None,
    run_id: int | None = None,
    attempt: int = 1,
    purpose: str | None = None,
) -> Iterator[None]:
    """What a `recorded_call` inside belongs to: one attempt of a fallback loop.

    `purpose` is "eval" for an ADR-047 eval run, None for real use.
    """
    token = _ATTEMPT.set(
        {"ticker": ticker, "run_id": run_id, "attempt": attempt, "purpose": purpose}
    )
    try:
        yield
    finally:
        _ATTEMPT.reset(token)


@dataclass
class Call:
    """Handle a call site fills in: the provider's response, once it has one."""

    response: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def token_usage(response: Any) -> tuple[int, int, int, int]:
    """(uncached input, output, cache-write, cache-read) tokens of an OpenAI or Anthropic reply."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0, 0
    if hasattr(usage, "prompt_tokens"):  # OpenAI: prompt_tokens includes the cached ones
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        return prompt - cached, int(getattr(usage, "completion_tokens", 0) or 0), 0, cached
    return (  # Anthropic: input_tokens excludes cache reads and writes
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
        int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    )


def _error_class(exc: BaseException) -> str:
    """The provider's exception class when a call site wrapped it (`raise ... from e`)."""
    cause = exc.__cause__
    return type(cause).__name__ if cause is not None else type(exc).__name__


@contextmanager
def recorded_call(
    *,
    call_site: str,
    provider: str,
    model: str,
    prompt_version: int,
    system_prompt: str,
    schema: dict[str, Any],
) -> Iterator[Call]:
    """Time one request and record it, success or failure, as an `llm_calls` row."""
    call = Call()
    start = time.perf_counter()
    status, error = "ok", None
    try:
        yield call
    except BaseException as exc:
        status, error = "error", _error_class(exc)
        raise
    finally:
        _LAST.set((None, None))
        try:
            _record(call, call_site, provider, model, prompt_version, system_prompt, schema, start,
                    status, error)  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - observability must never fail the call
            logger.warning("llm call not recorded: %s", type(exc).__name__)


def _record(
    call: Call, call_site: str, provider: str, model: str, prompt_version: int,
    system_prompt: str, schema: dict[str, Any], start: float, status: str, error: str | None,
) -> None:  # fmt: skip
    latency_ms = int((time.perf_counter() - start) * 1000)
    inp, out, cache_write, cache_read = token_usage(call.response)
    cost = (
        cost_usd(model, inp, out, cache_read, cache_write)
        if call.response is not None
        else 0.0  # no reply: nothing billed
    )
    ctx = _ATTEMPT.get() or {}
    row = {
        "ticker": ctx.get("ticker"),
        "run_id": ctx.get("run_id"),
        "attempt": ctx.get("attempt", 1),
        "purpose": ctx.get("purpose"),
        "call_site": call_site,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256(system_prompt, schema),
        "input_tokens": inp,
        "output_tokens": out,
        "cache_write_tokens": cache_write,
        "cache_read_tokens": cache_read,
        "latency_ms": latency_ms,
        "status": status,
        "error_class": error,
        "cost_usd": cost,
        "request_id": getattr(call.response, "id", None),
    }
    _LAST.set((_write(row), cost))


def _write(row: dict[str, Any]) -> int | None:
    try:
        from data.db import get_session
        from data.models.schema import LlmCall

        with get_session() as session:
            rec = LlmCall(**row)
            session.add(rec)
            session.flush()
            return int(rec.id)
    except Exception as exc:  # noqa: BLE001 - observability must never fail the call
        logger.warning("llm_calls row not written: %s", type(exc).__name__)
        return None


def last_call_id() -> int | None:
    """Row id of the most recent recorded call in this context; None if it was not written."""
    last = _LAST.get()
    return last[0] if last else None


def last_call_cost() -> float | None:
    """Cost of the most recent recorded call in this context."""
    last = _LAST.get()
    return last[1] if last else None


def annotate_last(guard_status: str, warning_count: int) -> None:
    """Add the guard's verdict to the most recent recorded call in this context."""
    last = _LAST.get()
    if last is not None and last[0] is not None:
        _update(last[0], {"guard_status": guard_status, "warning_count": warning_count})


def _update(row_id: int, fields: dict[str, Any]) -> None:
    try:
        from data.db import get_session
        from data.models.schema import LlmCall

        with get_session() as session:
            rec = session.get(LlmCall, row_id)
            for name, value in fields.items():
                setattr(rec, name, value)
    except Exception as exc:  # noqa: BLE001 - observability must never fail the call
        logger.warning("llm_calls row %s not updated: %s", row_id, type(exc).__name__)
