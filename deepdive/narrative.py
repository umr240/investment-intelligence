"""
AI Narrative Layer — the ONLY module permitted to call OpenAI/Anthropic SDKs.

CLAUDE.md hard rule (project-root):
  > LLMs are a presentation layer only — constrained to reference actual
  > metrics from backend calculations.

Inputs:  ScorecardView (deterministic, computed by Python)
Outputs: NarrativeOutput (typed Pydantic envelope)

Provider routing:
  • OpenAI is the PRIMARY provider for the MVP (settings.openai_narrative_model,
    default gpt-4o-mini — cheap, JSON-schema response_format support).
  • Anthropic is the FALLBACK when:
      - OpenAI returns 401/403/429 / quota / rate-limit / connection error
      - settings.narrative_provider is "anthropic" (preference flip)
  • settings.narrative_provider can pin a single provider:
      "openai_only" / "anthropic_only" — fallback disabled.

The narrative is ALWAYS validated by `narrative_guard.validate()` before
being returned. A guard failure does NOT mask the output — it sets
`status=guard_failed` and emits warnings, so the CLI surfaces the issue
to the human reader. Hallucinations leak through louder than they hide.

Schema v2 (ADR-045): the model cites field IDs and writes numbers only as
`{field_id}` placeholders, which `narrative_render` fills from the view. Both
providers get the same per-request JSON schema as structured output; a guard
failure earns one repair call on the same provider (§2.5).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import get_close_matches
from typing import Any, cast

from pydantic import BaseModel

from config.settings import settings
from config.verdicts import narrative_verdict
from deepdive.citable_fields import CitableField
from deepdive.llm_calls import annotate_last, attempt_context, last_call_cost, recorded_call
from deepdive.mental_model_composer import (
    Archetype,
    CompositionResult,
    LatticeProfile,
    MentalModel,
    OverlayName,
    load_lattice,
    select_models_for_dive,
)
from deepdive.narrative_output import (
    SCHEMA_V2,
    NarrativeBodyV2,
    NarrativeOutput,
    NarrativeProvider,
    NarrativeStatus,
    narrative_json_schema_v2,
)
from deepdive.narrative_render import render_body
from deepdive.scorecard_view import ScorecardView

logger = logging.getLogger(__name__)

# Bump on any change to the system prompt or the narrative schema (ADR-048 §2.2);
# tests/test_llm_calls.py fails on a changed prompt hash without a bump.
PROMPT_VERSION = 4


# ── Public API ───────────────────────────────────────────────────────────


class NarrativeUnavailableError(RuntimeError):
    """Raised when both providers fail (or are unconfigured)."""


class NarrativeOnStaleDiveError(NarrativeUnavailableError):
    """The latest dive's inputs were superseded (DEC-46); re-run the dive first."""


def generate_narrative(
    view: ScorecardView,
    *,
    provider_pref: str | None = None,
) -> NarrativeOutput:
    """Generate a full narrative for a scorecard view.

    `provider_pref` overrides settings.narrative_provider for a single call:
      "openai" | "anthropic" | "openai_only" | "anthropic_only"
    """
    from data.dive_staleness import latest_dive_stale_reason, latest_run_id

    stale = latest_dive_stale_reason(view.ticker)
    if stale:
        raise NarrativeOnStaleDiveError(f"{view.ticker}: latest dive is stale ({stale})")

    pref = (provider_pref or settings.narrative_provider or "openai").lower()
    order = _provider_order(pref)
    if not order:
        raise NarrativeUnavailableError(
            "No narrative providers available. Set OPENAI_API_KEY or "
            "ANTHROPIC_API_KEY in .env, or NARRATIVE_PROVIDER=...",
        )

    return _generate(view, order, run_id=latest_run_id(view.ticker))


def generate_eval_narrative(
    view: ScorecardView, provider: NarrativeProvider, model: str
) -> NarrativeOutput:
    """One narrative for an eval case (ADR-047): this provider and model, no fallback.

    A golden-set view is a frozen public copy, not the ticker's live dive, so no
    staleness check applies; the `llm_calls` row is marked `purpose="eval"`.
    """
    return _generate(view, [provider], run_id=None, model=model, purpose="eval")


def _generate(
    view: ScorecardView,
    order: list[NarrativeProvider],
    *,
    run_id: int | None,
    model: str | None = None,
    purpose: str | None = None,
) -> NarrativeOutput:
    from deepdive.narrative_guard import validate as guard_validate

    fields = view.citable_fields()  # one view for the prompt, the guard and the render
    last_err: Exception | None = None
    fallback_reason = ""
    attempt = 0
    for idx, provider in enumerate(order):
        attempt += 1
        try:
            with attempt_context(
                ticker=view.ticker, run_id=run_id, attempt=attempt, purpose=purpose
            ):
                first = _call_provider(provider, view, model)
                first_warnings = guard_validate(first.body, view)
                annotate_last("warnings" if first_warnings else "ok", len(first_warnings))
        except _ProviderError as e:
            last_err = e
            # Provider errors can echo part of the API key; this text is logged
            # and persisted, so key-like tokens are scrubbed (Security §1).
            fallback_reason = f"{provider.value}: {_redact(str(e))}"
            logger.warning("Narrative provider %s failed: %s", provider.value, _redact(str(e)))
            continue

        reply, warnings, cost = first, first_warnings, last_call_cost()
        repair_notes: list[str] = []  # a failed repair: not a grounding fault, not formatting
        failed_repair_tokens = (0, 0)
        if first_warnings:  # §2.5: one repair, same provider, same request; never a second
            attempt += 1
            try:
                with attempt_context(
                    ticker=view.ticker, run_id=run_id, attempt=attempt, purpose=purpose
                ):
                    repair = (first.body, first_warnings)
                    reply = _call_provider(provider, view, model, repair=repair)
                    warnings = guard_validate(reply.body, view)
                    annotate_last("warnings" if warnings else "ok", len(warnings))
                repair_cost = last_call_cost()
                cost = None if cost is None or repair_cost is None else round(cost + repair_cost, 6)
            except _ProviderError as e:
                reply, warnings = first, first_warnings
                cost = None if cost is None else cost + (last_call_cost() or 0.0)
                failed_repair_tokens = e.usage
                repair_notes = [f"repair: {provider.value}: {_redact(str(e))}"]
        repaired = reply is not first
        extra_pt, extra_ct = (
            (reply.prompt_tokens, reply.completion_tokens) if repaired else failed_repair_tokens
        )

        # Status reflects grounding faults only. A trim is cosmetic — surfacing
        # it is right, but letting it raise GUARD_FAILED would report
        # "numeric/citation validation failed" for an over-long headline and
        # blunt a signal that should mean a suspect number.
        status = NarrativeStatus.GUARD_FAILED if warnings else NarrativeStatus.OK

        return NarrativeOutput(
            ticker=view.ticker,
            generated_at=datetime.now(timezone.utc),
            provider=provider,
            model=reply.model,
            prompt_tokens=first.prompt_tokens + extra_pt,
            completion_tokens=first.completion_tokens + extra_ct,
            cost_usd=cost,
            fallback_used=(idx > 0),
            fallback_reason=fallback_reason if idx > 0 else "",
            status=status,
            guard_warnings=[*warnings, *(f"formatting: {n}" for n in reply.fit_notes),
                            *repair_notes],  # fmt: skip
            schema_version=SCHEMA_V2,
            body=reply.body,
            rendered=render_body(reply.body, fields),
            first_attempt=first.body if repaired else None,
            first_attempt_warnings=first_warnings if repaired else [],
        )

    raise NarrativeUnavailableError(
        f"All narrative providers failed. Last error: {_redact(str(last_err))}",
    )


# ── Provider routing ─────────────────────────────────────────────────────


# Key-shaped tokens a provider may echo back: sk-…, key_…, or anything masked with ***.
_KEYISH = re.compile(r"\b(?:sk|key|rk|pk)[-_][\w*-]{4,}|[\w-]*\*{3,}[\w-]*", re.IGNORECASE)


def _redact(text: str) -> str:
    """Scrub key-like tokens from provider error text before it is logged or stored."""
    return _KEYISH.sub("[redacted]", text)


class _ProviderError(RuntimeError):
    """Marker for a provider-side failure that should trigger fallback.

    `usage` is (prompt, completion) tokens of a reply that came back but was unusable,
    e.g. cut off at max_tokens: billed, so counted.
    """

    def __init__(self, message: str, usage: tuple[int, int] = (0, 0)) -> None:
        super().__init__(message)
        self.usage = usage


def _provider_order(pref: str) -> list[NarrativeProvider]:
    """Resolve provider preference into an ordered fallback list.

    Filters out providers without a configured key. "openai_only" /
    "anthropic_only" disable fallback even if both keys are set.
    """
    has_openai = bool(settings.openai_api_key)
    has_anthropic = bool(settings.anthropic_api_key)

    if pref == "openai_only":
        return [NarrativeProvider.OPENAI] if has_openai else []
    if pref == "anthropic_only":
        return [NarrativeProvider.ANTHROPIC] if has_anthropic else []

    if pref == "anthropic":
        primary, fallback = NarrativeProvider.ANTHROPIC, NarrativeProvider.OPENAI
    else:  # default + "openai"
        primary, fallback = NarrativeProvider.OPENAI, NarrativeProvider.ANTHROPIC

    out: list[NarrativeProvider] = []
    if primary == NarrativeProvider.OPENAI and has_openai:
        out.append(NarrativeProvider.OPENAI)
    elif primary == NarrativeProvider.ANTHROPIC and has_anthropic:
        out.append(NarrativeProvider.ANTHROPIC)

    if fallback == NarrativeProvider.OPENAI and has_openai:
        out.append(NarrativeProvider.OPENAI)
    elif fallback == NarrativeProvider.ANTHROPIC and has_anthropic:
        out.append(NarrativeProvider.ANTHROPIC)

    # Dedupe while preserving order (when primary == fallback).
    seen: set[NarrativeProvider] = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _recorded(provider: str, model: str, system_prompt: str) -> Any:
    """The `llm_calls` record for one narrative request (ADR-048)."""
    return recorded_call(
        call_site="narrative",
        provider=provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        system_prompt=system_prompt,
        schema=_versioned_schema(),
    )


def _versioned_schema() -> dict[str, Any]:
    """What the prompt hash covers besides the system prompt (ADR-048 §2.2): the request
    schema without a view's IDs, and the repair turn's fixed text."""
    return {
        "request": [  # with and without a scored framework; sentinels stand in for the enums
            _strict_schema(_inline_refs(narrative_json_schema_v2(["<id>"], codes, ["<g>"])))
            for codes in (["<code>"], [])
        ],
        "repair": [_REPAIR_ASK, _HINTS_HEADER, _HINT_NEAR, _HINT_NONE],
    }


@dataclass(frozen=True)
class _Reply:
    body: NarrativeBodyV2
    prompt_tokens: int
    completion_tokens: int
    model: str
    fit_notes: list[str]


Repair = tuple[NarrativeBodyV2, list[str]]  # the answer that failed the guard, and why


def _call_provider(
    provider: NarrativeProvider,
    view: ScorecardView,
    model: str | None = None,
    repair: Repair | None = None,
) -> _Reply:
    """One structured-output request; `model` overrides the configured one."""
    if provider == NarrativeProvider.OPENAI:
        return _call_openai(view, model, repair)
    return _call_anthropic(view, model, repair)


def _request_schema(view: ScorecardView) -> dict[str, Any]:
    """The v2 body schema with this view's IDs, inlined and strict for both providers."""
    feasible = sorted(f.code for f in view.frameworks if not f.is_unfeasible)
    fields = list(view.citable_fields())
    triggers = [t.trigger_id for t in view.overlay_triggers]
    # OpenAI rejects '"' in an enum value; a gap's text before one is still a part the guard
    # matches (narrative_guard._risk_grounding_warnings accepts any part of a gap).
    gaps = [re.split(r'["\n]', g, maxsplit=1)[0].strip() for g in view.fetch_data_gaps or []]
    groundings = list(dict.fromkeys([*feasible, *triggers, *fields, *filter(None, gaps)]))
    schema = narrative_json_schema_v2(fields, feasible, groundings)
    return _strict_schema(_inline_refs(schema))


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace each `$ref` with its `$defs` entry: one schema shape both providers accept."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):  # keep its description
                siblings = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**defs[ref.split("/")[-1]], **siblings})
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return cast(dict[str, Any], walk(schema))


_UNKNOWN_ID = re.compile(r"'\{?([^'{}]+)\}?' is not a citable field")
_REPAIR_ASK = (
    "The checks rejected that answer:\n{faults}\n\nReturn the whole narrative again with each "
    "fault fixed. Keep everything that passed. Every number must be a {{field_id}} placeholder "
    "from the citable fields."
)
_HINTS_HEADER = "\n\nCitable fields with a similar ID:\n"
# A similar ID can be a different measure (revenue vs revenue CAGR); the guard checks only
# that an ID exists, so the label and unit go with it and words stay an option.
_HINT_NEAR = (
    "- '{bad}' is not listed. Similar: {near}. Use one only if it is the same measure; "
    "otherwise state it in words, without a number."
)
_HINT_NONE = "- '{bad}' is not listed; state it in words, without a number."


def _id_hints(warnings: list[str], fields: dict[str, CitableField]) -> list[str]:
    """For each unknown ID a warning names, up to three citable IDs it may have meant."""
    ids, hints = list(fields), []
    for bad in dict.fromkeys(m[1] for w in warnings for m in _UNKNOWN_ID.finditer(w)):
        name = bad.rsplit(".", 1)[-1]
        near = [i for i in ids if i.rsplit(".", 1)[-1] == name][:3] or get_close_matches(
            bad, ids, n=3, cutoff=0.6
        )
        shown = ", ".join(
            f"'{i}' ({fields[i].label}, {fields[i].unit})" if fields[i].unit
            else f"'{i}' ({fields[i].label})" for i in near
        )  # fmt: skip
        hints.append(_HINT_NEAR.format(bad=bad, near=shown) if near else _HINT_NONE.format(bad=bad))
    return hints


def _repair_turns(repair: Repair | None, view: ScorecardView) -> list[dict[str, Any]]:
    """The failed answer and the guard's warnings, as the next two turns (§2.5)."""
    if repair is None:
        return []
    body, warnings = repair
    faults = "\n".join(f"- {w}" for w in warnings)
    if hints := _id_hints(warnings, view.citable_fields()):
        faults += _HINTS_HEADER + "\n".join(hints)
    return [
        {"role": "assistant", "content": body.model_dump_json()},
        {"role": "user", "content": _REPAIR_ASK.format(faults=faults)},
    ]


def _parse_reply(
    raw: Any, provider: str, tokens: tuple[int, int]
) -> tuple[NarrativeBodyV2, list[str]]:
    raw, fit_notes = _fit_to_declared_lengths(raw, NarrativeBodyV2)
    if isinstance(raw, dict):  # a view with no scored framework is not asked for codes
        for point in [*raw.get("bull", []), *raw.get("bear", [])]:
            if isinstance(point, dict):
                point.setdefault("framework_codes", [])
    try:
        return NarrativeBodyV2.model_validate(raw), fit_notes
    except Exception as e:
        raise _ProviderError(f"{provider} JSON did not match NarrativeBodyV2: {e}", tokens) from e


# ── OpenAI (primary) ─────────────────────────────────────────────────────


def _call_openai(
    view: ScorecardView, model_override: str | None = None, repair: Repair | None = None
) -> _Reply:
    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            OpenAI,
            RateLimitError,
        )
        from openai.types.chat import ChatCompletionMessageParam
    except ImportError as e:
        raise _ProviderError(f"openai SDK not installed: {e}") from e

    client = OpenAI(api_key=settings.openai_api_key)
    model = model_override or settings.openai_narrative_model
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(view)

    messages = cast(
        "list[ChatCompletionMessageParam]",
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt},
         *_repair_turns(repair, view)],
    )  # fmt: skip
    with _recorded("openai", model, system_prompt) as call:
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.2,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "NarrativeBody",
                        "schema": _request_schema(view),
                        "strict": True,
                    },
                },
                messages=messages,
            )
        except (RateLimitError, AuthenticationError, APIConnectionError) as e:
            raise _ProviderError(f"openai transport: {type(e).__name__}: {e}") from e
        except APIStatusError as e:
            raise _ProviderError(f"openai status {e.status_code}: {e}") from e

        call.response = resp
        usage = getattr(resp, "usage", None)
        tokens = (int(getattr(usage, "prompt_tokens", 0) or 0),
                  int(getattr(usage, "completion_tokens", 0) or 0))  # fmt: skip
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise _ProviderError("openai returned empty content", tokens)

        try:
            raw = json.loads(content)
        except json.JSONDecodeError as e:
            raise _ProviderError(f"openai returned invalid JSON: {e}", tokens) from e

        body, fit_notes = _parse_reply(raw, "openai", tokens)
        return _Reply(body, *tokens, model, fit_notes)


# ── Anthropic (fallback) ─────────────────────────────────────────────────


def _call_anthropic(
    view: ScorecardView, model_override: str | None = None, repair: Repair | None = None
) -> _Reply:
    try:
        import anthropic
        from anthropic import APIConnectionError, APIStatusError, RateLimitError
        from anthropic.types import MessageParam, OutputConfigParam
    except ImportError as e:
        raise _ProviderError(f"anthropic SDK not installed: {e}") from e

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = model_override or settings.anthropic_narrative_model
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(view)

    output_config: OutputConfigParam = {
        "format": {"type": "json_schema", "schema": _request_schema(view)}
    }
    messages = cast(
        "list[MessageParam]",
        [{"role": "user", "content": user_prompt}, *_repair_turns(repair, view)],
    )
    with _recorded("anthropic", model, system_prompt) as call:
        try:
            # Structured output, not a forced tool call: current models reject a forced
            # tool_choice with a 400 (ADR-045 §1, §2.7 item 1). The v1 baseline averaged
            # 3,130 output tokens; 8,192 leaves room for the v2 fields and a repair.
            resp = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system_prompt,
                output_config=output_config,
                messages=messages,
            )
        except (RateLimitError, APIConnectionError) as e:
            raise _ProviderError(f"anthropic transport: {type(e).__name__}: {e}") from e
        except APIStatusError as e:
            raise _ProviderError(f"anthropic status {e.status_code}: {e}") from e

        call.response = resp
        usage = getattr(resp, "usage", None)
        tokens = (int(getattr(usage, "input_tokens", 0) or 0),
                  int(getattr(usage, "output_tokens", 0) or 0))  # fmt: skip
        if resp.stop_reason in ("max_tokens", "refusal"):
            raise _ProviderError(f"anthropic stopped early: {resp.stop_reason}", tokens)
        text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise _ProviderError(f"anthropic returned invalid JSON: {e}", tokens) from e

        body, fit_notes = _parse_reply(raw, "anthropic", tokens)
        return _Reply(body, *tokens, model, fit_notes)


def _fit_to_declared_lengths(
    payload: Any, model: type[BaseModel],
) -> tuple[Any, list[str]]:
    """Trim over-long strings and lists to the `maxLength` / `maxItems` their schema declares.

    Neither OpenAI's strict mode nor Anthropic's tool-use schema enforces
    `maxLength` — both accepted a schema declaring it and returned longer
    strings anyway. Without this, one overrun headline discards an entire paid
    generation, then the fallback provider's as well, and the user is billed
    twice for nothing.

    An overrun is a formatting fault, not a content one: the claim is intact and
    only its shape is wrong. So trim on a word boundary and report it, matching
    how guard failures are already handled — surfaced as warnings rather than
    thrown away (see generate_narrative).
    """
    notes: list[str] = []
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = defs.get(ref.split("/")[-1], {})
            return target if isinstance(target, dict) else {}
        return node

    def walk(value: Any, node: dict[str, Any], path: str) -> Any:
        node = resolve(node)
        if isinstance(value, str):
            cap = node.get("maxLength")
            if isinstance(cap, int) and len(value) > cap:
                notes.append(f"{path} trimmed from {len(value)} to {cap} chars")
                return _trim_on_word_boundary(value, cap)
            return value
        if isinstance(value, dict):
            props = node.get("properties", {})
            return {
                k: walk(v, props.get(k, {}), f"{path}.{k}" if path else k)
                for k, v in value.items()
            }
        if isinstance(value, list):
            items = node.get("items", {})
            cap = node.get("maxItems")  # not sent to the provider (ADR-045 §2.7 item 1)
            if isinstance(cap, int) and len(value) > cap:
                notes.append(f"{path} cut from {len(value)} to {cap} items")
                value = value[:cap]
            return [walk(v, items, f"{path}.{i}") for i, v in enumerate(value)]
        return value

    return walk(payload, schema, ""), notes


def _trim_on_word_boundary(text: str, cap: int) -> str:
    """Cut to at most `cap` chars, preferring the last word break, with an ellipsis."""
    if len(text) <= cap:
        return text
    clipped = text[: cap - 1].rstrip()
    space = clipped.rfind(" ")
    # Only honour the word break if it keeps most of the budget; otherwise a
    # long unbroken token would collapse the string to nothing.
    if space > cap * 0.6:
        clipped = clipped[:space].rstrip()
    return clipped.rstrip(".,;:—- ") + "…"


# ── Prompt construction ──────────────────────────────────────────────────


_SYSTEM_PROMPT = """You are the narrative layer of a deterministic equity-research lab.
A Python pipeline has already computed every quantitative signal (7 academic frameworks F1..F7,
3 diagnostic overlays, a stage-weighted composite). Your role is presentation only.

HARD RULES (violating these is the worst possible failure):
1. NEVER type a number. The user message lists the CITABLE FIELDS: an ID, its value and its
   label. To state a value, write its ID in braces, e.g. "ROIC is {F5.roic}"; code replaces
   the placeholder with the value. A number that is not a citable field must not appear at
   all: describe the pattern in words instead. A typed digit is checked and flagged.
2. Use IDs exactly as listed. List the IDs each bull or bear point relies on in its
   `numeric_claims`.
3. Cite framework codes (F1..F7) in `framework_codes` for every bull/bear point, and only
   frameworks that were scored (the user message names the unfeasible ones). When none was
   scored, the schema has no `framework_codes`: each point lists at least one field it relies
   on in `numeric_claims`.
4. Risks must be grounded in something concrete: one value from the `grounded_in` list in the
   schema (a scored framework code, an overlay trigger_id such as "BEW-2", a citable field ID,
   or a data gap, copied exactly). `grounded_in` is mandatory.
5. `verdict` is given in the user message: copy it exactly. `verdict_reason` explains why the
   scorecard produced it. You explain the verdict; you do not choose or soften it.
6. `triggers`: at least one. Each names one citable field ID and the change in it that would
   alter the verdict, e.g. field "F5.roic", condition "turns positive across two annual
   filings". A trigger condition is the ONLY place you may state a threshold of your own.
7. `owner_operator_answer`: would an owner hold 100% of this business for ten years on what
   the scorecard shows? YES, NO, or NOT_YET when the evidence is not there yet.
   `moat_direction`: WIDENING, FLAT, NARROWING, or UNKNOWN when the scorecard cannot tell.
8. Do not name external data sources (Bloomberg, FactSet, Fiscal.ai, etc.) and do not claim our
   numbers agree or disagree with any external benchmark — you have no access to those sources.
9. Tone: terse, analytical, peer-reviewed. No marketing language. No emojis. No buy/sell
   recommendations.
10. Length: the schema states each field's limit in its description; stay inside it, as
    text over the limit is cut. Prefer fewer high-quality points over many vague ones.
11. data_caveats must paraphrase the actual `fetch_data_gaps` and per-framework `data_gaps` in
    the view. Do not invent caveats; do not omit material ones.
12. The user message includes a "Lattice" section: the mental models composed for this profile.
    BEFORE drafting, reason through them in this order (ADR-023 §1.3 Block 2):
      (a) INVERSION — what makes most stocks losers; how many of those traits this one shares
      (b) CIRCLE OF COMPETENCE — what is understood vs. unknown; "unknown" is a first-class output
      (c) MOAT DIRECTION — name the specific Power if present; widening / flat / narrowing
      (d) CAPITAL ALLOCATOR — Outsiders 8 traits, scored against scorecard signals
      (e) LUNCH-EATING TEST — would a $1B-funded challenger displace this in 5 years?
      (f) PROBABILISTIC — base rate for this profile; conditional given divergent signals
    Each model's "Inversion form" line is the failure mode you must check against this profile.
    Lattice models are reasoning aids — their slugs never appear in `framework_codes`,
    `grounded_in` or field IDs.
13. HOLD-LOGIC FRAMING (DEC-23 — forever-default, 5-year minimum reconsideration):
    The user's hold philosophy is Buffett/Sleep/Akre/Smith/Russo convergent:
      • Default state: hold forever.
      • Reconsideration window: opens at 5 years, never before. Years 1-4 are
        early-warning monitoring only — read the warnings, do not act on noise.
      • Acceptable exit signals: structural moat breach, fraud, terminal
        disruption, capital-allocator failure (Outsiders 8 traits inverted).
      • Unacceptable exit signals: "the multiple looks rich", "stock is up 3x",
        valuation mean-reversion alone. Bessembinder's 4%-of-stocks wealth-
        creation finding makes "trim on price strength" a structurally
        wealth-destroying habit at the portfolio level.
    Frame your output accordingly:
      • Risks (the `risks` array) are THESIS-VALIDATION CHECKPOINTS to monitor
        across the 5-year hold, NOT stop-loss triggers. Phrase each as a condition
        to WATCH FOR over years 1-5 ("monitor whether ROIC erosion continues over
        further annual filings before reconsidering the thesis"), not a level to
        EXIT AT. High-severity risks describe thesis-BREAK conditions, not price
        moves. Put any threshold in a trigger, not in the risk text.
      • Bear points stay analytical — describe what's working against the
        thesis structurally. Don't recommend timing actions.
      • Bull points are the why-hold-forever case, including BEW (Bessembinder
        Extreme Winners) verdict if it fired — extreme winners require sized
        positions and extended holds to matter.

You will respond by filling the structured-output schema. No prose outside the schema.
"""


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT


def _build_user_prompt(view: ScorecardView) -> str:
    """User-message body: the entire ScorecardView JSON + framing + lattice.

    Sort_keys=True on the payload keeps the prompt cache-friendly across runs
    of the same ticker (OpenAI & Anthropic both honour ≥1024-token system-prompt
    caches; the dynamic lattice block sits after the cached system prompt).
    """
    payload = view.to_llm_context()  # already pretty-printed, sorted
    feasible = [fv.code for fv in view.frameworks if not fv.is_unfeasible]
    unfeasible = [
        f"{fv.code}({fv.unfeasible_reason or 'no entry'})"
        for fv in view.frameworks
        if fv.is_unfeasible
    ]
    overlay_ids = [t.trigger_id for t in view.overlay_triggers] or ["none"]

    lattice_block = _build_lattice_block(view)
    verdict = narrative_verdict(view.composite.verdict)
    if verdict is None:  # every composite verdict maps (config/verdicts.py); never guess one
        raise ValueError(f"{view.ticker}: no narrative verdict for {view.composite.verdict!r}")
    fields = "\n".join(
        f"{fid} = {f.value}  ({f.label})" for fid, f in view.citable_fields().items()
    )

    return (
        f"Generate a narrative for {view.ticker} (run {view.run_date}, mode {view.mode_used}).\n"
        f"Verdict (copy it exactly): {verdict}\n"
        f"Feasible frameworks: {', '.join(feasible) or 'none'}\n"
        f"Unfeasible frameworks: {', '.join(unfeasible) or 'none'}\n"
        f"Active overlay triggers: {', '.join(overlay_ids)}\n\n"
        f"CITABLE FIELDS (the only numbers you may state, each as {{ID}}):\n{fields}\n\n"
        f"{lattice_block}\n\n"
        "ScorecardView JSON (context only; cite its numbers by ID, never copy them):\n"
        f"```json\n{payload}\n```\n"
    )


# ── Lattice composition (ADR-024 wiring) ─────────────────────────────────


# Module-level lazy cache so the lattice is read from disk once per process,
# not once per dive. Tests can override by assigning ``_LATTICE_CACHE`` directly.
_LATTICE_CACHE: dict[str, MentalModel] | None = None

# How long to keep an IPO "recent" for archetype selection. 24 months matches
# the F2/F7 history threshold the deep-dive feasibility check applies (a company
# with <2yr public history is structurally different from one with 5+ years).
_RECENT_IPO_DAYS = 730

# Section-extraction regex over a model file's body markdown. Captures the
# prose under "## <heading>" until the next "## " or end-of-string.
_SECTION_RE = re.compile(
    r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _get_lattice() -> dict[str, MentalModel]:
    """Lazy-load the lattice on first use; cache for the process lifetime."""
    global _LATTICE_CACHE
    if _LATTICE_CACHE is None:
        _LATTICE_CACHE = load_lattice()
    return _LATTICE_CACHE


def _lattice_profile_from_view(view: ScorecardView) -> LatticeProfile:
    """Derive composer inputs from the deterministic scorecard view.

    Archetype priority: post_spinoff > recent_ipo > platform_dominator >
    pre_discovery. Overlay-fired and structural archetypes win over framework-
    verdict archetypes because they describe the company's *state*, not just
    how it currently scores. A spinoff that also looks like F1-strong is
    still primarily a spinoff for reasoning purposes.
    """
    company = view.company

    has_revenue = bool(company.latest_revenue and company.latest_revenue > 0)

    # `ceo_equity_pct_state` is set whenever the DEF 14A pipeline ran, even if
    # the document itself didn't disclose the figure (state == "not_disclosed").
    # That still constitutes "we have proxy data" for management/ inclusion.
    has_proxy_data = company.ceo_equity_pct_state is not None

    overlays_fired: frozenset[OverlayName] = frozenset(
        t.overlay_type  # type: ignore[misc]
        for t in view.overlay_triggers
        if t.overlay_type in ("ICA", "PSA", "BEW")
    )

    archetype: Archetype | None = _select_archetype(view, overlays_fired)

    return LatticeProfile(
        has_revenue=has_revenue,
        has_proxy_data=has_proxy_data,
        archetype=archetype,
        overlays_fired=overlays_fired,
    )


def _select_archetype(
    view: ScorecardView, overlays_fired: frozenset[OverlayName],
) -> Archetype | None:
    # PSA-fired ⇒ post_spinoff archetype IFF PSA's deeper analysis actually
    # concluded the issuer is a spinoff candidate. PSA-3 fires conditionally
    # when F7 is unfeasible ("might apply if listing_type confirms"); the
    # deeper analysis can then verdict="not_a_spinoff_candidate" for issuers
    # well past the spinoff window (LULU 158mo case 2026-05-16). Without
    # this guard, mature non-spinoff issuers got tagged post_spinoff, which
    # pulled `lifecycle/post_spinoff_archetype` into the lattice composition
    # — wrong context for the narrative LLM.
    #
    # Positive allowlist over negative denylist: only the three confirmed-
    # spinoff verdicts in overlays/psa.py qualify. `data_gaps_block_verdict`
    # is ambiguous and does NOT qualify (won't pull spinoff-specific models
    # into the lattice on incomplete data).
    if "PSA" in overlays_fired:
        psa_verdict = view.overlay_verdicts.get("PSA", "")
        if psa_verdict in (
            "strong_psa_candidate",
            "moderate_psa_candidate",
            "weak_psa_candidate",
        ):
            return "post_spinoff"
        # PSA fired but self-disqualified or ambiguous ⇒ fall through

    from data.reader import trusted_listing_date

    ipo = trusted_listing_date(view.company.ipo_date, view.company.ipo_date_state)
    if ipo is not None and (view.run_date - ipo).days < _RECENT_IPO_DAYS:
        return "recent_ipo"

    f6 = next((fv for fv in view.frameworks if fv.code == "F6"), None)
    if f6 is not None and not f6.is_unfeasible and f6.verdict == "strong_fit":
        return "platform_dominator"

    f1 = next((fv for fv in view.frameworks if fv.code == "F1"), None)
    if f1 is not None and not f1.is_unfeasible and f1.verdict == "strong_fit":
        return "pre_discovery"

    return None


def _extract_section(body: str, section_name: str) -> str:
    """Extract the prose under '## section_name' from a model body. Empty if absent."""
    target = section_name.strip().lower()
    for m in _SECTION_RE.finditer(body):
        if m.group(1).strip().lower() == target:
            return m.group(2).strip()
    return ""


def _format_lattice_block(composition: CompositionResult) -> str:
    if not composition.selected:
        return "Lattice: (no models selected — minimal-data dive)"

    lines: list[str] = [
        f"Lattice — {len(composition.selected)} models composed for this profile "
        f"({composition.total_tokens}/{composition.budget} tokens).",
        "",
        "Apply each model's 'Inversion form' to the company before drafting. "
        "These are reasoning aids; do not cite slugs in framework_codes / grounded_in.",
        "",
    ]

    by_domain: dict[str, list[MentalModel]] = {}
    for m in composition.selected:
        by_domain.setdefault(m.domain, []).append(m)

    for domain in sorted(by_domain.keys()):
        lines.append(f"### {domain}/")
        for m in by_domain[domain]:
            summary = _extract_section(m.body, "Summary") or "(no summary)"
            inversion = _extract_section(m.body, "Inversion form") or "(no inversion form)"
            lines.append(
                f"- **{m.name}** ({m.citation_tier} {m.school})"
            )
            lines.append(f"  Summary: {_one_line(summary)}")
            lines.append(f"  Inversion: {_one_line(inversion)}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _one_line(text: str) -> str:
    """Collapse whitespace so each summary/inversion fits on one prompt line."""
    return re.sub(r"\s+", " ", text).strip()


def _build_lattice_block(view: ScorecardView) -> str:
    """Compose the lattice subset for this view and format for the prompt.

    Failures here are non-fatal: a corrupt or missing lattice should not
    block narrative generation. Logged as warnings; the prompt falls back
    to a stub line and the LLM proceeds without the lattice.
    """
    try:
        lattice = _get_lattice()
    except Exception as exc:
        logger.warning("Lattice load failed; narrative will run without it: %s", exc)
        return "Lattice: (unavailable)"

    profile = _lattice_profile_from_view(view)
    composition = select_models_for_dive(lattice, profile)
    return _format_lattice_block(composition)


# ── JSON-schema strictness helper ────────────────────────────────────────


def _strict_schema(schema: dict) -> dict:
    """Recursively force `additionalProperties: false` and required-on-all-fields
    so OpenAI's `strict: true` mode accepts a Pydantic-derived schema.

    Pydantic emits `additionalProperties` only at top level by default; OpenAI
    strict mode requires it at every object level. Same for `required`.
    """
    if not isinstance(schema, dict):
        return schema

    # Resolve $defs in-place — OpenAI strict accepts $ref but every referenced
    # $def must also be strict-clean.
    if "$defs" in schema:
        schema["$defs"] = {k: _strict_schema(v) for k, v in schema["$defs"].items()}

    if schema.get("type") == "object" and "properties" in schema:
        schema["additionalProperties"] = False
        schema["required"] = list(schema["properties"].keys())
        schema["properties"] = {
            k: _strict_schema(v) for k, v in schema["properties"].items()
        }

    if schema.get("type") == "array" and "items" in schema:
        schema["items"] = _strict_schema(schema["items"])

    # anyOf / oneOf / allOf
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema and isinstance(schema[key], list):
            schema[key] = [_strict_schema(s) for s in schema[key]]

    return schema


# ── Persistence helpers ──────────────────────────────────────────────────


def shown_sections(narrative: NarrativeOutput) -> dict[str, Any]:
    """The body a reader sees, JSON-ready: for v2 the rendered copy (ADR-045 §2.2)."""
    if isinstance(narrative.body, NarrativeBodyV2):
        if narrative.rendered is None:
            raise ValueError(f"{narrative.ticker}: a v2 narrative must be rendered to be shown")
        return {"schema_version": SCHEMA_V2, **narrative.rendered.model_dump(mode="json")}
    return narrative.body.model_dump(mode="json")


def persist_narrative(narrative: NarrativeOutput) -> bool:
    """Persist narrative onto the most-recent DeepDiveRun for the ticker.

    Stores body sections as JSON strings (keeps audit trail of guard
    warnings + token usage). A v2 narrative stores its rendered copy, and the
    model's own body under `_template` so it can be re-checked, and a repaired one
    its first attempt under `_first_attempt`. Returns True on
    success, False if no DeepDiveRun exists yet for the ticker.
    """
    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun

    sections = shown_sections(narrative)
    bull_json = json.dumps(sections.pop("bull"), default=str)
    bear_json = json.dumps(sections.pop("bear"), default=str)
    if isinstance(narrative.body, NarrativeBodyV2):
        sections["_template"] = narrative.body.model_dump(mode="json")
        if narrative.first_attempt is not None:  # §2.5: what the repair replaced, and why
            sections["_first_attempt"] = {
                "template": narrative.first_attempt.model_dump(mode="json"),
                "guard_warnings": list(narrative.first_attempt_warnings),
            }
    risk_json = json.dumps(
        {
            **sections,
            "_audit": {
                "provider": narrative.provider.value,
                "model": narrative.model,
                "prompt_tokens": narrative.prompt_tokens,
                "completion_tokens": narrative.completion_tokens,
                "cost_usd": narrative.cost_usd,
                "fallback_used": narrative.fallback_used,
                "fallback_reason": narrative.fallback_reason,
                "status": narrative.status.value,
                "guard_warnings": list(narrative.guard_warnings),
                "generated_at": narrative.generated_at.isoformat(),
            },
        },
        default=str,
    )

    with get_session() as s:
        co = s.execute(
            select(Company).where(Company.ticker == narrative.ticker.upper()),
        ).scalar_one_or_none()
        if co is None:
            return False
        run = s.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.company_id == co.id)
            .order_by(desc(DeepDiveRun.id))  # the row generate_narrative's stale check read
        ).scalars().first()
        if run is None:
            return False
        from data.dive_staleness import dive_withheld_reason

        withheld = dive_withheld_reason(run)  # e.g. flagged while the provider call ran
        if withheld:
            raise NarrativeOnStaleDiveError(
                f"{narrative.ticker}: latest dive is stale ({withheld}); not stored"
            )
        run.bull_narrative = bull_json
        run.bear_narrative = bear_json
        run.risk_factors = risk_json
        s.commit()
    return True
