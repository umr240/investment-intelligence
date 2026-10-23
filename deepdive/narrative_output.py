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
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


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
    fallback_used: bool = False
    fallback_reason: str = ""
    status: NarrativeStatus = NarrativeStatus.OK
    guard_warnings: list[str] = Field(default_factory=list)
    body: NarrativeBody
