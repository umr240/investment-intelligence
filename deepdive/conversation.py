"""
Phase 5L: persistent conversational dive.

The narrative layer (deepdive/narrative.py) generates a one-shot bull/bear/
risks structured output. This module is its multi-turn cousin: the user
asks free-form questions; each LLM reply is a `ChatTurnOutput` validated
the same way (every numeric_claim must point to a `field_path` in the
ScorecardView JSON the dive grounded in).

Provider routing mirrors narrative.py — OpenAI primary by default, Anthropic
fallback. Both clamp to the configured `*_narrative_model` (Sonnet 4.6 by
default for Anthropic; Haiku 4.5 was empirically unreliable for tool-use
schema fills, see settings.py).

An allow-listed LLM call site (tests/test_llm_call_sites.py, ADR-031-A1).
Rules (CLAUDE.md "AI layer boundary"):
  • LLMs are presentation only — every number must be grounded
  • Conversation grounds in a *frozen* ScorecardView from the linked
    DeepDiveRun. Re-dive creates a new run + a fresh conversation.
  • Append-only persistence — every turn (user + assistant) writes a row
    to deep_dive_conversations. Audit trail of what was actually said.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from deepdive.narrative import (
    NarrativeProvider,
    _provider_order,
    _ProviderError,
    _redact,
)
from deepdive.narrative_guard import _walk_path
from deepdive.narrative_output import NumericClaim
from deepdive.scorecard_view import ScorecardView

logger = logging.getLogger(__name__)


# ── Output schema ────────────────────────────────────────────────────────


class ChatTurnOutput(BaseModel):
    """One assistant turn — natural-language reply + numeric_claims.

    The reply is rendered to the user. The numeric_claims list is
    validated server-side: each entry's `field_path` must resolve into
    the ScorecardView JSON the conversation is grounded in. Mismatches
    surface as guard_warnings on the persisted turn — visible to the
    user in the same way one-shot narrative validator warnings are.
    """
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(
        ..., max_length=4000,
        description=(
            "The natural-language answer to the user's question. Must reference "
            "only numbers that have a corresponding entry in numeric_claims. "
            "Cite framework codes (F1..F7) or overlay trigger IDs in prose "
            "where relevant — the validator checks they exist in the view."
        ),
    )
    numeric_claims: list[NumericClaim] = Field(
        default_factory=list,
        description=(
            "Every numeric value in `reply` must appear here with a `field_path` "
            "into ScorecardView.to_dict(). Strings preserve units ('19.9%', "
            "'$1.4B'). The validator walks each path; mismatches → guard warning."
        ),
    )


# ── Conversation history ─────────────────────────────────────────────────


@dataclass
class ChatTurn:
    """In-memory representation of one persisted turn."""
    role: str                                    # 'user' | 'assistant'
    content: str
    numeric_claims: list[NumericClaim] | None = None
    guard_warnings: list[str] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


# Sliding window for what we replay back to the model. Older turns stay
# in the DB for audit but don't enter the prompt — keeps token cost
# bounded as the conversation grows.
HISTORY_WINDOW_TURNS = 8

# Token pricing for cost estimation (USD per million tokens).
# Conservative — Anthropic Sonnet 4.6 actual is $3/$15. OpenAI gpt-4o-mini
# is much cheaper but tool-use reliability was lower in our 5j testing.
_PRICING_USD_PER_M = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
}


def estimate_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int,
) -> float:
    """Return turn cost in USD. Falls back to Sonnet pricing for unknown models."""
    in_rate, out_rate = _PRICING_USD_PER_M.get(model, (3.0, 15.0))
    return round(
        prompt_tokens / 1_000_000 * in_rate
        + completion_tokens / 1_000_000 * out_rate,
        4,
    )


# ── Validation ───────────────────────────────────────────────────────────


def validate_chat_turn(
    output: ChatTurnOutput, view: ScorecardView,
) -> list[str]:
    """Validate that every numeric_claim resolves into the ScorecardView.

    Returns a list of guard-warning strings. Empty list means clean.
    Mismatches do NOT block the response — they're surfaced so the user
    knows which numbers to scrutinise. Same philosophy as narrative_guard.
    """
    warnings: list[str] = []
    view_dict = view.to_llm_context()
    if isinstance(view_dict, str):
        try:
            view_dict = json.loads(view_dict)
        except (json.JSONDecodeError, TypeError):
            warnings.append("internal: ScorecardView.to_llm_context did not return parseable JSON")
            return warnings

    for i, claim in enumerate(output.numeric_claims):
        path = claim.field_path
        target = _walk_path(view_dict, path)
        if target is None:
            warnings.append(
                f"numeric_claim[{i}] field_path '{path}' does not resolve "
                f"in ScorecardView (claim value: '{claim.value}')"
            )
    return warnings


# ── Prompt assembly ──────────────────────────────────────────────────────


_SYSTEM_PROMPT = """You are the conversational dive layer of a deterministic equity-research lab.
The user has run a full dive on a single ticker; every quantitative signal (7 academic frameworks
F1..F7, 3 diagnostic overlays, stage-weighted composite, ROIC views, retention metrics) has
already been computed by Python and persisted. You see the FROZEN ScorecardView JSON for this
dive, plus the prior turns of this conversation, plus the user's new message.

HARD RULES (violating these is the worst possible failure):
1. NEVER invent numbers. Every numeric value in your reply (percentages, dollar amounts, scores,
   ratios, dates, year counts) must come from the ScorecardView JSON the user provides. If a
   number you'd want to mention is not in the view, do not mention any number — describe the
   qualitative pattern instead.
2. Every numeric_claim you emit MUST include a `field_path` pointing to the exact location in
   the ScorecardView JSON where that number lives (e.g. "composite.score",
   "frameworks.4.score", "company.market_cap_usd"). The validator walks each path.
3. Cite framework codes (F1..F7) and overlay trigger_ids (e.g. "ICA-5") inline in prose when
   relevant. They must already appear in the ScorecardView (don't invent F8 or BEW-9).
4. Tone: terse, analytical, peer-reviewed. No marketing language. No emojis. No buy/sell
   recommendations beyond what the composite verdict already says.
5. Conversation continuity: when the user asks a follow-up referring to "earlier" / "you said",
   answer based on what THIS conversation already established AND the underlying view. If your
   prior turn quoted a number, it's still grounded — re-cite the same field_path.
6. When asked something the view cannot support ("what's the analyst price target?"), say so
   plainly: "That's not in the dive's scorecard — re-run with broader DataRequirement or fetch
   analyst coverage."
7. Length: replies should be 1-4 short paragraphs typically. If the user explicitly asks for
   long-form (e.g. "walk me through F5 in detail"), longer is acceptable.

You will respond by filling the ChatTurnOutput schema. No prose outside the schema.
"""


def _build_user_message(
    view: ScorecardView,
    history: list[ChatTurn],
    user_message: str,
) -> str:
    """Assemble the user-message body: scorecard JSON + windowed history + question.

    Sliding window: replay only the last HISTORY_WINDOW_TURNS user/assistant pairs.
    Older turns stay persisted (audit) but don't enter the prompt — bounds cost.
    """
    payload = view.to_llm_context()
    feasible = [fv.code for fv in view.frameworks if not fv.is_unfeasible]
    overlays = [t.trigger_id for t in view.overlay_triggers] or ["none"]

    # Sliding window of last N turns (user + assistant pairs)
    if len(history) > HISTORY_WINDOW_TURNS * 2:
        windowed = history[-HISTORY_WINDOW_TURNS * 2:]
    else:
        windowed = history

    history_block = "\n\n".join(
        f"{t.role.upper()}: {t.content}"
        for t in windowed
    ) if windowed else "(no prior turns in this conversation)"

    return (
        f"Ticker: {view.ticker}   Run date: {view.run_date}   Mode: {view.mode_used}\n"
        f"Feasible frameworks: {', '.join(feasible) or 'none'}\n"
        f"Active overlay triggers: {', '.join(overlays)}\n\n"
        f"=== Prior turns in this conversation ===\n{history_block}\n\n"
        f"=== ScorecardView JSON (THE ONLY SOURCE OF NUMBERS) ===\n"
        f"```json\n{payload}\n```\n\n"
        f"=== User's new message ===\n{user_message}\n"
    )


# ── Provider calls ───────────────────────────────────────────────────────


def _call_openai_chat(
    view: ScorecardView, history: list[ChatTurn], user_message: str,
) -> tuple[ChatTurnOutput, int, int, str]:
    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            OpenAI,
            RateLimitError,
        )
    except ImportError as e:
        raise _ProviderError(f"openai SDK not installed: {e}") from e

    client = OpenAI(api_key=settings.openai_api_key)
    model = settings.openai_narrative_model
    schema = ChatTurnOutput.model_json_schema()
    schema["additionalProperties"] = False

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(view, history, user_message)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ChatTurnOutput",
                    "schema": schema,
                    "strict": True,
                },
            },
        )
    except (RateLimitError, APIConnectionError, AuthenticationError) as e:
        raise _ProviderError(f"openai transport: {type(e).__name__}: {e}") from e
    except APIStatusError as e:
        raise _ProviderError(f"openai status {e.status_code}: {e}") from e

    raw = resp.choices[0].message.content
    try:
        body = ChatTurnOutput.model_validate_json(raw)
    except Exception as e:
        raise _ProviderError(f"openai content did not match ChatTurnOutput: {e}") from e
    usage = getattr(resp, "usage", None)
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    return body, pt, ct, model


def _call_anthropic_chat(
    view: ScorecardView, history: list[ChatTurn], user_message: str,
) -> tuple[ChatTurnOutput, int, int, str]:
    try:
        import anthropic
        from anthropic import APIConnectionError, APIStatusError, RateLimitError
    except ImportError as e:
        raise _ProviderError(f"anthropic SDK not installed: {e}") from e

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = settings.anthropic_narrative_model
    schema = ChatTurnOutput.model_json_schema()
    schema["additionalProperties"] = False

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            tools=[{
                "name": "emit_chat_turn",
                "description": "Emit one structured assistant turn for the conversational dive.",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": "emit_chat_turn"},
            messages=[{
                "role": "user",
                "content": _build_user_message(view, history, user_message),
            }],
        )
    except (RateLimitError, APIConnectionError) as e:
        raise _ProviderError(f"anthropic transport: {type(e).__name__}: {e}") from e
    except APIStatusError as e:
        raise _ProviderError(f"anthropic status {e.status_code}: {e}") from e

    tool_input: dict | None = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            tool_input = block.input    # type: ignore[attr-defined]
            break
    if tool_input is None:
        raise _ProviderError("anthropic did not return a tool_use block")
    try:
        body = ChatTurnOutput.model_validate(tool_input)
    except Exception as e:
        raise _ProviderError(f"anthropic tool_input did not match ChatTurnOutput: {e}") from e

    usage = getattr(resp, "usage", None)
    pt = int(getattr(usage, "input_tokens", 0) or 0)
    ct = int(getattr(usage, "output_tokens", 0) or 0)
    return body, pt, ct, model


# ── Public entry point ───────────────────────────────────────────────────


@dataclass
class ChatTurnResult:
    """Aggregated result for one assistant turn — what the CLI persists + renders."""
    output: ChatTurnOutput
    provider: str            # 'openai' | 'anthropic'
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    guard_warnings: list[str]


def generate_chat_response(
    view: ScorecardView,
    history: list[ChatTurn],
    user_message: str,
    *,
    run_id: int,
    provider_pref: str | None = None,
) -> ChatTurnResult:
    """Drive one assistant turn end-to-end.

    Routes to OpenAI primary then Anthropic fallback (or pinned single
    provider via `provider_pref`). On both-failed, raises NarrativeUnavailableError
    so the CLI can surface a clear error and persist the failed user turn.

    Validation is non-blocking — guard warnings come back on the result;
    it's the CLI's job to render them.
    """
    from data.dive_staleness import run_withheld_reason
    from deepdive.narrative import NarrativeOnStaleDiveError

    withheld = run_withheld_reason(run_id)  # DEC-47: no chat on stale or unknown inputs
    if withheld:
        raise NarrativeOnStaleDiveError(f"dive {run_id} is stale ({withheld})")

    pref = (provider_pref or settings.narrative_provider or "openai").lower()
    order = _provider_order(pref)
    if not order:
        from deepdive.narrative import NarrativeUnavailableError
        raise NarrativeUnavailableError(
            "No narrative providers available. Set OPENAI_API_KEY or "
            "ANTHROPIC_API_KEY in .env, or NARRATIVE_PROVIDER=...",
        )

    last_err: Exception | None = None
    for provider in order:
        try:
            if provider == NarrativeProvider.OPENAI:
                body, pt, ct, model = _call_openai_chat(view, history, user_message)
            else:
                body, pt, ct, model = _call_anthropic_chat(view, history, user_message)
        except _ProviderError as exc:
            logger.warning("Chat provider %s failed: %s", provider.value, _redact(str(exc)))
            last_err = exc
            continue

        warnings = validate_chat_turn(body, view)
        cost = estimate_cost_usd(model, pt, ct)
        return ChatTurnResult(
            output=body,
            provider=provider.value,
            model=model,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=cost,
            guard_warnings=warnings,
        )

    from deepdive.narrative import NarrativeUnavailableError
    raise NarrativeUnavailableError(
        f"All chat providers failed. Last error: {_redact(str(last_err))}"
    )


# ── Persistence helpers ──────────────────────────────────────────────────


def load_conversation_history(
    deep_dive_run_id: int,
) -> list[ChatTurn]:
    """Load all turns for a dive run, oldest first. Used on REPL resume."""
    import json as _json

    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import DeepDiveConversation

    out: list[ChatTurn] = []
    with get_session() as db:
        rows = db.execute(
            select(DeepDiveConversation)
            .where(DeepDiveConversation.deep_dive_run_id == deep_dive_run_id)
            .order_by(DeepDiveConversation.turn_index)
        ).scalars().all()
        for r in rows:
            claims = None
            if r.numeric_claims_json:
                try:
                    claims = [
                        NumericClaim.model_validate(c)
                        for c in _json.loads(r.numeric_claims_json)
                    ]
                except (ValueError, TypeError):
                    claims = None
            warnings = None
            if r.guard_warnings_json:
                try:
                    warnings = _json.loads(r.guard_warnings_json)
                except (ValueError, TypeError):
                    warnings = None
            out.append(ChatTurn(
                role=r.role, content=r.content,
                numeric_claims=claims, guard_warnings=warnings,
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
                cost_usd=r.cost_usd,
            ))
    return out


def persist_turn(
    *,
    deep_dive_run_id: int,
    ticker: str,
    turn_index: int,
    role: str,
    content: str,
    numeric_claims: list[NumericClaim] | None = None,
    guard_warnings: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Append one turn to deep_dive_conversations. Idempotent on (run_id, turn_index)."""
    from data.db import get_session
    from data.models.schema import DeepDiveConversation

    with get_session() as db:
        row = DeepDiveConversation(
            deep_dive_run_id=deep_dive_run_id,
            ticker=ticker,
            turn_index=turn_index,
            role=role,
            content=content,
            numeric_claims_json=(
                json.dumps([c.model_dump() for c in numeric_claims], default=str)
                if numeric_claims else None
            ),
            guard_warnings_json=(
                json.dumps(guard_warnings) if guard_warnings else None
            ),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
        db.add(row)
        db.commit()
