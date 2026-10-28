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
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from config.settings import settings
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
    NarrativeBody,
    NarrativeOutput,
    NarrativeProvider,
    NarrativeStatus,
)
from deepdive.scorecard_view import ScorecardView

logger = logging.getLogger(__name__)

# Bump on any change to the system prompt or NarrativeBody schema (ADR-048 §2.2);
# tests/test_llm_calls.py fails on a changed prompt hash without a bump.
PROMPT_VERSION = 1


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
    last_err: Exception | None = None
    fallback_reason = ""
    for idx, provider in enumerate(order):
        try:
            with attempt_context(
                ticker=view.ticker, run_id=run_id, attempt=idx + 1, purpose=purpose
            ):
                body, prompt_tok, completion_tok, model_id, fit_notes = _call_provider(
                    provider,
                    view,
                    model,
                )
        except _ProviderError as e:
            last_err = e
            # Provider errors can echo part of the API key; this text is logged
            # and persisted, so key-like tokens are scrubbed (Security §1).
            fallback_reason = f"{provider.value}: {_redact(str(e))}"
            logger.warning("Narrative provider %s failed: %s", provider.value, _redact(str(e)))
            continue

        # Validate post-generation. Guard failures populate warnings but do
        # NOT switch providers — re-rolling rarely fixes hallucinations and
        # would silently double the bill.
        from deepdive.narrative_guard import validate as guard_validate
        guard_warnings = guard_validate(body, view)
        # Status reflects grounding faults only. A trim is cosmetic — surfacing
        # it is right, but letting it raise GUARD_FAILED would report
        # "numeric/citation validation failed" for an over-long headline and
        # blunt a signal that should mean a suspect number.
        status = NarrativeStatus.GUARD_FAILED if guard_warnings else NarrativeStatus.OK
        warnings = [*guard_warnings, *(f"formatting: {n}" for n in fit_notes)]
        annotate_last("warnings" if guard_warnings else "ok", len(warnings))

        return NarrativeOutput(
            ticker=view.ticker,
            generated_at=datetime.now(timezone.utc),
            provider=provider,
            model=model_id,
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            cost_usd=last_call_cost(),
            fallback_used=(idx > 0),
            fallback_reason=fallback_reason if idx > 0 else "",
            status=status,
            guard_warnings=warnings,
            body=body,
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
    """Marker for a provider-side failure that should trigger fallback."""


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
        schema=NarrativeBody.model_json_schema(),
    )


def _call_provider(
    provider: NarrativeProvider,
    view: ScorecardView,
    model: str | None = None,
) -> tuple[NarrativeBody, int, int, str, list[str]]:
    """Dispatch to the per-provider call; `model` overrides the configured one.

    Returns (body, prompt_tok, comp_tok, model, fit_notes)."""
    if provider == NarrativeProvider.OPENAI:
        return _call_openai(view, model)
    return _call_anthropic(view, model)


# ── OpenAI (primary) ─────────────────────────────────────────────────────


def _call_openai(
    view: ScorecardView, model_override: str | None = None
) -> tuple[NarrativeBody, int, int, str, list[str]]:
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
    model = model_override or settings.openai_narrative_model
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(view)

    schema = NarrativeBody.model_json_schema()
    schema["additionalProperties"] = False  # strict mode requires this everywhere

    with _recorded("openai", model, system_prompt) as call:
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.2,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "NarrativeBody",
                        "schema": _strict_schema(schema),
                        "strict": True,
                    },
                },
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except (RateLimitError, AuthenticationError, APIConnectionError) as e:
            raise _ProviderError(f"openai transport: {type(e).__name__}: {e}") from e
        except APIStatusError as e:
            raise _ProviderError(f"openai status {e.status_code}: {e}") from e

        call.response = resp
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise _ProviderError("openai returned empty content")

        try:
            raw = json.loads(content)
        except json.JSONDecodeError as e:
            raise _ProviderError(f"openai returned invalid JSON: {e}") from e

        raw, fit_notes = _fit_to_declared_lengths(raw, NarrativeBody)
        try:
            body = NarrativeBody.model_validate(raw)
        except Exception as e:
            raise _ProviderError(f"openai JSON did not match NarrativeBody: {e}") from e

        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        return body, pt, ct, model, fit_notes


# ── Anthropic (fallback) ─────────────────────────────────────────────────


def _call_anthropic(
    view: ScorecardView, model_override: str | None = None
) -> tuple[NarrativeBody, int, int, str, list[str]]:
    try:
        import anthropic
        from anthropic import APIConnectionError, APIStatusError, RateLimitError
    except ImportError as e:
        raise _ProviderError(f"anthropic SDK not installed: {e}") from e

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = model_override or settings.anthropic_narrative_model
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(view)

    # Anthropic structured output via tool-use: define a single "emit_narrative"
    # tool whose schema IS NarrativeBody, force tool_choice → guarantees JSON.
    tool_schema = NarrativeBody.model_json_schema()
    tool_schema["additionalProperties"] = False

    with _recorded("anthropic", model, system_prompt) as call:
        try:
            # max_tokens=4096: empirically bull(5)+bear(5)+risks(8)+data_caveats can
            # exceed 2048 with Sonnet's verbose tool-call reasoning, leaving the
            # tool_input truncated mid-field. 4096 fits the worst case and is well
            # under the model's output ceiling.
            resp = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=[{
                    "name": "emit_narrative",
                    "description": "Emit the structured bull/bear/risks narrative for the scorecard.",  # noqa: E501
                    "input_schema": tool_schema,
                }],
                tool_choice={"type": "tool", "name": "emit_narrative"},
                messages=[{"role": "user", "content": user_prompt}],
            )
        except (RateLimitError, APIConnectionError) as e:
            raise _ProviderError(f"anthropic transport: {type(e).__name__}: {e}") from e
        except APIStatusError as e:
            raise _ProviderError(f"anthropic status {e.status_code}: {e}") from e

        call.response = resp
        tool_input: dict | None = None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                tool_input = block.input  # type: ignore[attr-defined]
                break
        if tool_input is None:
            raise _ProviderError("anthropic did not return a tool_use block")

        tool_input, fit_notes = _fit_to_declared_lengths(tool_input, NarrativeBody)
        try:
            body = NarrativeBody.model_validate(tool_input)
        except Exception as e:
            raise _ProviderError(f"anthropic tool_input did not match NarrativeBody: {e}") from e

        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "input_tokens", 0) or 0)
        ct = int(getattr(usage, "output_tokens", 0) or 0)
        return body, pt, ct, model, fit_notes


def _fit_to_declared_lengths(
    payload: Any, model: type[BaseModel],
) -> tuple[Any, list[str]]:
    """Trim over-long strings to the `maxLength` their schema declares.

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
1. NEVER invent or estimate numbers. Every numeric value in your output (percentages, dollar
   amounts, scores, ratios, year counts, etc.) must come from the ScorecardView JSON the user
   provides. If a number you'd want to mention is not in the view, do not mention any number —
   describe the qualitative pattern instead.
2. Every numeric_claim you emit MUST include a `field_path` pointing to the exact location in
   the ScorecardView JSON where that number lives (e.g. "composite.score",
   "frameworks.0.score", "company.market_cap_usd"). The downstream validator checks each path.
3. Cite framework codes (F1..F7) in `framework_codes` for every bull/bear point, and only cite
   frameworks that appear in `frameworks` (i.e. exclude unfeasible ones).
4. Risks must be grounded in something concrete in the view: a framework code, an overlay
   trigger_id (e.g. "BEW-2"), or a data_gap entry. The `grounded_in` field is mandatory.
5. Do not name external data sources (Bloomberg, FactSet, Fiscal.ai, etc.) and do not claim our
   numbers agree or disagree with any external benchmark — you have no access to those sources.
6. Tone: terse, analytical, peer-reviewed. No marketing language. No emojis. No buy/sell
   recommendations beyond what the composite verdict already says.
7. Length: each headline ≤ 140 chars, each detail ≤ 600 chars. Prefer fewer high-quality points
   over many vague ones.
8. data_caveats must paraphrase the actual `fetch_data_gaps` and per-framework `data_gaps` in
   the view. Do not invent caveats; do not omit material ones.
9. The user message includes a "Lattice" section: the mental models composed for this profile.
   BEFORE drafting, reason through them in this order (ADR-023 §1.3 Block 2):
     (a) INVERSION — what makes most stocks losers; how many of those traits this one shares
     (b) CIRCLE OF COMPETENCE — what is understood vs. unknown; "unknown" is a first-class output
     (c) MOAT DIRECTION — name the specific Power if present; widening / flat / narrowing
     (d) CAPITAL ALLOCATOR — Outsiders 8 traits, scored against scorecard signals
     (e) LUNCH-EATING TEST — would a $1B-funded challenger displace this in 5 years?
     (f) PROBABILISTIC — base rate for this profile; conditional given divergent signals
   Each model's "Inversion form" line is the failure mode you must check against this profile.
   Lattice models are reasoning aids — DO NOT cite their slugs in `framework_codes` or
   `grounded_in` (those fields accept only F1..F7, overlay trigger_ids, view field paths).
10. HOLD-LOGIC FRAMING (DEC-23 — forever-default, 5-year minimum reconsideration):
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
        across the 5-year hold, NOT stop-loss triggers. Each risk should be
        phrased as a condition to WATCH FOR over years 1-5 ("monitor whether
        ROIC erosion continues over 2-3 more annual filings before
        reconsidering thesis"), not a level to EXIT AT ("sell if drawdown
        exceeds X%"). High-severity risks describe thesis-BREAK conditions,
        not price moves.
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

    return (
        f"Generate a narrative for {view.ticker} (run {view.run_date}, mode {view.mode_used}).\n"
        f"Feasible frameworks: {', '.join(feasible) or 'none'}\n"
        f"Unfeasible frameworks: {', '.join(unfeasible) or 'none'}\n"
        f"Active overlay triggers: {', '.join(overlay_ids)}\n\n"
        f"{lattice_block}\n\n"
        f"ScorecardView JSON (THE ONLY SOURCE OF NUMBERS):\n```json\n{payload}\n```\n"
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


def persist_narrative(narrative: NarrativeOutput) -> bool:
    """Persist narrative onto the most-recent DeepDiveRun for the ticker.

    Stores body sections as JSON strings (keeps audit trail of guard
    warnings + token usage). Returns True on success, False if no
    DeepDiveRun exists yet for the ticker.
    """
    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun

    body = narrative.body
    bull_json = json.dumps(
        [p.model_dump() for p in body.bull], default=str,
    )
    bear_json = json.dumps(
        [p.model_dump() for p in body.bear], default=str,
    )
    risk_json = json.dumps(
        {
            "one_liner": body.one_liner,
            "risks": [r.model_dump() for r in body.risks],
            "data_caveats": list(body.data_caveats),
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
