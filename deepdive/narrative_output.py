"""
Typed contract for AI-generated narrative output.

The LLM (OpenAI primary, Anthropic fallback) is constrained to fill exactly
this shape via structured-output mode. Every numeric claim must cite either
a framework code (F1..F7) or one of the whitelisted scorecard fields, so
`narrative_guard.validate()` can verify nothing was hallucinated.

CLAUDE.md guarantee: this is the ONLY layer where AI text reaches the user.
The data-fetch / framework / overlay / screener paths remain LLM-free.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NarrativeProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class NarrativeStatus(str, Enum):
    OK = "ok"
    GUARD_FAILED = "guard_failed"
    PROVIDER_ERROR = "provider_error"


class NumericClaim(BaseModel):
    """A single quantitative reference inside a narrative bullet.

    `value` is the number as the LLM wrote it (string preserves units like
    "12.4%" / "$1.2B" / "0.85"). `field_path` MUST point to a key inside
    ScorecardView.to_dict() — the validator walks this path to confirm the
    number originated in our data layer, not the model's training set.
    """
    model_config = ConfigDict(extra="forbid")

    value: str = Field(
        ...,
        description="The number as written in the narrative (e.g. '18.3%', '$2.1B', '6/9').",
    )
    field_path: str = Field(
        ...,
        description=(
            "Dotted path into ScorecardView.to_dict() that this number came "
            "from, e.g. 'frameworks.0.score' or 'composite.score' or "
            "'company.market_cap_usd'. Validator uses this to verify."
        ),
    )


class BullPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., max_length=140)
    detail: str = Field(..., max_length=800)
    framework_codes: list[str] = Field(
        default_factory=list,
        description="F1..F7 codes that ground this bull point (must exist in view).",
    )
    numeric_claims: list[NumericClaim] = Field(default_factory=list)


class BearPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., max_length=140)
    detail: str = Field(..., max_length=800)
    framework_codes: list[str] = Field(default_factory=list)
    numeric_claims: list[NumericClaim] = Field(default_factory=list)


class RiskFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # max_length raised 300 → 500 on 2026-05-17 after LULU re-narrate with
    # the expanded lattice (post anomaly fixes) produced legitimate but
    # longer DEC-23-style monitoring conditions ("monitor whether X over N
    # annual filings, where Y would signal Z — a thesis-break condition").
    # The DEC-23 hold-philosophy framing in narrative.py §10 explicitly asks
    # for multi-clause checkpoints; 300 chars couldn't fit them. 500 still
    # well below the BullPoint/BearPoint detail cap (800).
    factor: str = Field(..., max_length=500)
    severity: str = Field(..., description="low | medium | high")
    grounded_in: str = Field(
        ...,
        description=(
            "What in the scorecard supports flagging this risk: a "
            "framework code (e.g. 'F4'), an overlay trigger ID (e.g. "
            "'BEW-3'), or a data_gap key. Required — no free-floating risks."
        ),
    )


class NarrativeBody(BaseModel):
    """The actual narrative content the LLM produces. Schema is what we
    pass to OpenAI's `response_format` / Anthropic's tool-use schema."""
    model_config = ConfigDict(extra="forbid")

    one_liner: str = Field(
        ...,
        max_length=400,
        description="One-sentence thesis grounded in the composite verdict.",
    )
    bull: list[BullPoint] = Field(..., min_length=1, max_length=5)
    bear: list[BearPoint] = Field(..., min_length=1, max_length=5)
    risks: list[RiskFactor] = Field(default_factory=list, max_length=8)
    data_caveats: list[str] = Field(
        default_factory=list,
        description=(
            "Plain-English restatement of view.fetch_data_gaps + per-framework "
            "data_gaps. Each entry MUST correspond to an entry in the view; "
            "the validator checks for spurious caveats."
        ),
    )


# ── Schema v2 (ADR-045): the model cites field IDs, code renders the numbers ──

SCHEMA_V2 = "2.0"


class NarrativeVerdict(StrEnum):
    """ADR-023 §1.4 labels: the mapped composite verdict (ADR-054, `config/verdicts.py`)."""

    WATCHLIST_WITH_TRIGGERS = "WATCHLIST WITH TRIGGERS"
    EXCLUDE_WITH_REASON = "EXCLUDE WITH REASON"
    RESEARCH_ONLY = "RESEARCH-ONLY"


class OwnerOperatorAnswer(StrEnum):
    """Would an owner hold 100% of this business for ten years? (ADR-023-A1 row 2)"""

    YES = "YES"
    NO = "NO"
    NOT_YET = "NOT_YET"


class MoatDirection(StrEnum):
    WIDENING = "WIDENING"
    FLAT = "FLAT"
    NARROWING = "NARROWING"
    UNKNOWN = "UNKNOWN"


class FieldCitation(BaseModel):
    """A value the point relies on, by citable field ID; the model never writes the number."""

    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(..., description="An ID from the citable fields list, e.g. 'F5.roic'.")


_PROSE = (
    "Write every number as a placeholder naming a citable field, e.g. '{F5.roic}'; "
    "code fills in the value. Never write a number yourself."
)


class CasePoint(BaseModel):
    """One bull or bear point."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., max_length=140, description=_PROSE)
    detail: str = Field(..., max_length=800, description=_PROSE)
    framework_codes: list[str] = Field(
        ..., description="F1..F7 codes that ground this point; only scored frameworks."
    )
    numeric_claims: list[FieldCitation] = Field(..., description="Fields this point relies on.")


class RiskFactorV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str = Field(..., max_length=500, description=_PROSE)
    severity: Literal["low", "medium", "high"]
    grounded_in: str = Field(
        ...,
        description=(
            "A scored framework code ('F4'), an overlay trigger ID ('BEW-3'), a citable "
            "field ID, or a data gap. Required: no free-floating risks."
        ),
    )


class Trigger(BaseModel):
    """A condition on one field that would change the verdict."""

    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(..., description="The citable field the condition watches.")
    condition: str = Field(..., max_length=300, description="What change in it would matter.")


class NarrativeBodyV2(BaseModel):
    """Schema v2 body. Holds placeholders as the model wrote them; `render_body` fills them in."""

    model_config = ConfigDict(extra="forbid")

    one_liner: str = Field(..., max_length=400, description=_PROSE)
    verdict: NarrativeVerdict = Field(
        ..., description="The deterministic verdict you were given. Explain it; do not choose it."
    )
    verdict_reason: str = Field(..., max_length=600, description=_PROSE)
    owner_operator_answer: OwnerOperatorAnswer
    moat_direction: MoatDirection
    bull: list[CasePoint] = Field(..., min_length=1, max_length=5)
    bear: list[CasePoint] = Field(..., min_length=1, max_length=5)
    risks: list[RiskFactorV2] = Field(..., max_length=8)
    triggers: list[Trigger] = Field(..., max_length=8)
    data_caveats: list[str] = Field(
        ..., description="Plain-English restatement of the view's data gaps; one per gap."
    )


# Keywords Anthropic's structured outputs reject (ADR-045 §2.7 item 1); lengths are
# enforced after parsing instead. `minItems` above 1 is rejected too; none is used.
_UNSENT_KEYWORDS = frozenset({"minLength", "maxLength", "minimum", "maximum", "maxItems"})
# A stripped limit is restated in the description, where the model still reads it.
_LIMIT_TEXT = {
    "minLength": "at least {} characters", "maxLength": "at most {} characters",
    "minimum": "at least {}", "maximum": "at most {}", "maxItems": "at most {} items",
}  # fmt: skip


def narrative_json_schema_v2(field_ids: list[str], framework_codes: list[str]) -> dict[str, Any]:
    """The v2 body schema for one request: field IDs and framework codes are enums of this
    view's (§2.2), so an answer cannot name one the view lacks."""
    schema = NarrativeBodyV2.model_json_schema()

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: strip(v) for k, v in node.items() if k not in _UNSENT_KEYWORDS}
            limits = [_LIMIT_TEXT[k].format(v) for k, v in node.items() if k in _UNSENT_KEYWORDS]
            if limits:
                said = out.get("description", "")
                out["description"] = f"{said} Limit: {', '.join(limits)}.".lstrip()
            return out
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    schema = cast(dict[str, Any], strip(schema))
    for name in ("FieldCitation", "Trigger"):
        schema["$defs"][name]["properties"]["field_id"]["enum"] = list(field_ids)
    if framework_codes:  # an empty enum is invalid; the guard still rejects every code
        codes = schema["$defs"]["CasePoint"]["properties"]["framework_codes"]
        codes["items"]["enum"] = list(framework_codes)
    return schema


class NarrativeOutput(BaseModel):
    """Full narrative envelope: body + provenance + validation status.

    Persisted to deepdive_runs.bull_narrative / .bear_narrative / .risk_factors
    (as JSON-serialised strings) so future runs can render without re-billing.
    """
    model_config = ConfigDict(extra="forbid")

    ticker: str
    schema_version: str = "1.0"
    generated_at: datetime
    provider: NarrativeProvider
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None  # from config/llm_prices.py; None for an unpriced model
    fallback_used: bool = False
    fallback_reason: str = ""
    status: NarrativeStatus = NarrativeStatus.OK
    guard_warnings: list[str] = Field(default_factory=list)
    body: NarrativeBody | NarrativeBodyV2  # v2: as the model wrote it, placeholders and all
    rendered: NarrativeBodyV2 | None = None  # v2 only: the body with values filled in
    # ADR-045 §2.5: the body before the one bounded repair, and what the guard said about it.
    # Token and cost fields above count both calls.
    first_attempt: NarrativeBodyV2 | None = None
    first_attempt_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _body_matches_schema_version(self) -> NarrativeOutput:
        v2 = self.schema_version == SCHEMA_V2
        if v2 != isinstance(self.body, NarrativeBodyV2) or (
            not v2 and (self.rendered is not None or self.first_attempt is not None)
        ):
            raise ValueError(f"body does not match schema_version {self.schema_version}")
        if (
            self.rendered is not None
            and isinstance(self.body, NarrativeBodyV2)
            and _unrendered_parts(self.rendered) != _unrendered_parts(self.body)
        ):
            raise ValueError("rendered differs from body beyond its filled-in text")
        return self


def _unrendered_parts(body: NarrativeBodyV2) -> dict[str, Any]:
    """Everything rendering leaves as is: the guard's verdict on `body` covers `rendered`."""
    d = body.model_dump()
    for key in ("one_liner", "verdict_reason", "data_caveats"):
        d.pop(key)
    for point in (*d["bull"], *d["bear"]):
        point.pop("headline"), point.pop("detail")
    for risk in d["risks"]:
        risk.pop("factor")
    for trigger in d["triggers"]:
        trigger.pop("condition")
    return d
