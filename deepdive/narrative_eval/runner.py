"""Live eval runs (ADR-047 §2.3): one narrative per golden-set case.

Spends tokens. Only `invest narrative eval run` calls `run_case`, after the owner
confirms a priced estimate (§2.7 item 2). The model is called through
`deepdive/narrative.py`, the allow-listed call site, and the call is recorded in
`llm_calls` with `purpose="eval"` (§2.7 item 3).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from config.llm_prices import cost_usd, require_price
from deepdive.mental_model_composer import select_models_for_dive
from deepdive.narrative_eval.export import TEST, TRAIN
from deepdive.narrative_eval.graders import EvalOutput
from deepdive.narrative_output import NarrativeProvider
from deepdive.scorecard_view import ScorecardView

EST_OUTPUT_TOKENS = 3_800  # ADR-047 §2.4: measured output per narrative
CHARS_PER_TOKEN = 4  # rough; the figure is shown as an estimate
REPAIR_NOTE_TOKENS = 500  # the guard's warnings in a repair turn; a guess, shown as one
MAX_CONSECUTIVE_FAILURES = 3  # a billing or auth error fails every case; stop, rerun resumes


# The model families each provider serves; a mismatch would fail every case after confirming.
_PROVIDER_MODELS = {
    NarrativeProvider.ANTHROPIC: re.compile(r"^claude-"),
    NarrativeProvider.OPENAI: re.compile(r"^(gpt-|o\d)"),
}


def refusal(provider: NarrativeProvider, model: str) -> str | None:
    """Why a run cannot start, checked before any estimate or spend; None if it can."""
    from sqlalchemy import inspect
    from sqlalchemy.exc import NoSuchTableError

    from config.settings import settings
    from data.db import get_session

    if not _PROVIDER_MODELS[provider].match(model):
        return f"{model} is not a {provider.value} model"
    anthropic = provider == NarrativeProvider.ANTHROPIC
    key = settings.anthropic_api_key if anthropic else settings.openai_api_key
    if not key:
        return f"no {provider.value.upper()}_API_KEY is set"
    # Without the column every llm_calls write fails: the spend would leave no record (§2.7 item 3).
    with get_session() as session:
        try:
            columns = {c["name"] for c in inspect(session.get_bind()).get_columns("llm_calls")}
        except NoSuchTableError:
            return "the database has no llm_calls table: check DATABASE_URL"
    if "purpose" not in columns:
        return "llm_calls has no purpose column: run `alembic upgrade head` (migration 0009) first"
    return None


def select_cases(golden: Path, split: str) -> list[dict[str, Any]]:
    """The cases of one split, or both ("all"), in case-id order."""
    splits = (TRAIN, TEST) if split == "all" else (split,)
    cases = [json.loads(p.read_text("utf-8")) for s in splits for p in (golden / s).glob("*.json")]
    return sorted(cases, key=lambda c: str(c["case_id"]))


def estimate_cost(cases: list[dict[str, Any]], model: str, *, repairs: bool = False) -> float:
    """Estimated USD for one narrative per case; with `repairs`, if every case used its one
    repair, whose input adds the failed answer (ADR-045 §2.5). Raises UnpricedModelError."""
    from deepdive.narrative import _build_system_prompt, _build_user_prompt

    require_price(model)
    system = len(_build_system_prompt())
    total = 0.0
    for case in cases:
        chars = system + len(_build_user_prompt(ScorecardView.from_dict(case["view"])))
        total += cost_usd(model, chars // CHARS_PER_TOKEN, EST_OUTPUT_TOKENS) or 0.0
        if repairs:
            repair_in = chars // CHARS_PER_TOKEN + EST_OUTPUT_TOKENS + REPAIR_NOTE_TOKENS
            total += cost_usd(model, repair_in, EST_OUTPUT_TOKENS) or 0.0
    return total


def output_path(golden: Path, model: str, prompt_version: int, case_id: str) -> Path:
    name = re.sub(r"[^A-Za-z0-9.-]", "_", case_id)
    return golden / "outputs" / model / f"v{prompt_version}" / f"{name}.json"


def deferred_models(view: ScorecardView) -> list[str]:
    """Slugs the composer drops for budget on this view: ADR-055's lattice-RAG evidence."""
    from deepdive.narrative import _get_lattice, _lattice_profile_from_view

    composition = select_models_for_dive(_get_lattice(), _lattice_profile_from_view(view))
    return [m.slug for m in composition.deferred]


def last_call_id() -> int:
    """The newest `llm_calls` row id, 0 for none: the rows after it belong to the next case."""
    from sqlalchemy import func, select

    from data.db import get_session
    from data.models.schema import LlmCall

    with get_session() as session:
        return int(session.execute(select(func.max(LlmCall.id))).scalar() or 0)


def _usage(after_id: int, ticker: str) -> tuple[int, int, int, int, int] | None:
    """(input, output, cache read, cache write, latency ms) summed over the case's narrative
    calls: a repair is a second call (ADR-045 §2.7 item 4). None if none was recorded."""
    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import LlmCall

    with get_session() as session:
        rows: list[Any] = list(session.execute(
            select(LlmCall).where(  # not a UI or --narrate call another process made meanwhile
                LlmCall.__table__.c.id > after_id, LlmCall.__table__.c.call_site == "narrative",
                LlmCall.__table__.c.purpose == "eval", LlmCall.__table__.c.ticker == ticker,
            )
        ).scalars())  # fmt: skip
        if not rows:
            return None
        return (
            sum(int(r.input_tokens) for r in rows),
            sum(int(r.output_tokens) for r in rows),
            sum(int(r.cache_read_tokens) for r in rows),
            sum(int(r.cache_write_tokens) for r in rows),
            sum(int(r.latency_ms) for r in rows),
        )


def run_case(case: dict[str, Any], provider: NarrativeProvider, model: str) -> EvalOutput:
    """Generate and package one case's narrative. Spends tokens."""
    from deepdive.narrative import PROMPT_VERSION, generate_eval_narrative

    view = ScorecardView.from_dict(case["view"])
    deferred = deferred_models(view)
    before = last_call_id()
    start = time.perf_counter()
    narrative = generate_eval_narrative(view, provider, model)
    elapsed = int((time.perf_counter() - start) * 1000)
    usage = _usage(before, view.ticker)
    # Without the rows (their write failed), the narrative's own counts; cache tokens unknown.
    inp, out, cache_read, cache_write, latency = usage or (
        narrative.prompt_tokens, narrative.completion_tokens, 0, 0, elapsed,
    )  # fmt: skip
    return EvalOutput(
        case_id=case["case_id"],
        view_sha256=case["view_sha256"],
        model=model,  # as requested, so a resumed run finds it; the served id is in narrative
        prompt_version=PROMPT_VERSION,
        narrative=narrative,
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        latency_ms=latency,
        lattice_deferred=deferred,
    )


def write_output(golden: Path, out: EvalOutput) -> Path:
    path = output_path(golden, out.model, out.prompt_version, out.case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out.model_dump_json(indent=2) + "\n", "utf-8")
    return path
