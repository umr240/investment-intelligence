"""
Mental Model Composer — loads the lattice and selects relevant subsets per dive.

Per ADR-024 §1.5 selection rules + ADR-023 §1.3 Block 2 lattice-ordered reasoning.

This is the Phase 6.1 module that the future `deepdive/narrative.py` (Phase 6)
consumes. **Skeleton only** — per the lattice's own engineering models (YAGNI):
the full prompt-formatter, audit log, and per-model regression tests live with
`narrative.py` when it ships, not here.

Architecture: functional core, imperative shell.
- ``load_lattice()`` — imperative — reads files, parses frontmatter, fails fast
  on malformed input.
- ``select_models_for_dive()`` — pure — input typed, output typed; no I/O.
  Tests of selection logic do not need the file system.

Example::

    from deepdive.mental_model_composer import (
        load_lattice, select_models_for_dive, LatticeProfile,
    )

    lattice = load_lattice()
    profile = LatticeProfile(
        has_revenue=True,
        has_proxy_data=True,
        archetype="platform_dominator",
        overlays_fired={"ICA"},
    )
    result = select_models_for_dive(lattice, profile, token_budget=4000)
    for m in result.selected:
        print(f"{m.slug:<40} {m.citation_tier}  {m.token_cost_estimate}t")
    print(f"Total: {result.total_tokens}/{result.budget}")
"""
from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

# ── Public types ──────────────────────────────────────────────────────────

CitationTier = Literal["★★★", "★★", "★", "◯"]
Archetype = Literal["pre_discovery", "platform_dominator", "post_spinoff", "recent_ipo"]
OverlayName = Literal["ICA", "PSA", "BEW"]


class MentalModel(BaseModel):
    """A parsed mental-model file. Frontmatter fields + body markdown.

    Mandatory fields enforced per ADR-024 §1.3. Validation failures raise
    immediately at parse time (fail-fast). Models are immutable after load
    so the lattice can be cached safely across dives.
    """

    # Mandatory frontmatter (ADR-024 §1.3)
    slug: str
    name: str
    school: str
    citation_tier: CitationTier
    always_load: bool
    related_models: list[str] = Field(min_length=2)
    code_consequences: list[str] = Field(min_length=1)
    token_cost_estimate: int = Field(ge=50, le=2000)
    version: float
    added: _date
    last_reviewed: _date

    # Computed at parse time
    domain: str
    body: str
    file_path: str

    model_config = {"frozen": True}

    @field_validator("citation_tier")
    @classmethod
    def _check_tier(cls, v: str) -> str:
        if v not in ("★★★", "★★", "★", "◯"):
            raise ValueError(f"invalid citation_tier: {v!r}")
        return v


class LatticeProfile(BaseModel):
    """Inputs that drive composition. Built once per dive by the orchestrator
    from `Company` warehouse state + framework results + overlay outcomes.
    Pure data; no methods, no I/O.
    """

    has_revenue: bool = False
    has_proxy_data: bool = False
    archetype: Archetype | None = None
    overlays_fired: frozenset[OverlayName] = Field(default_factory=frozenset)


class CompositionResult(BaseModel):
    """Return type of ``select_models_for_dive``. Selected models are in
    inclusion order (always_load first, then by citation tier). Deferred
    models are those that exceeded the token budget — surfaced for
    diagnostics, not silently dropped.
    """

    selected: list[MentalModel]
    deferred: list[MentalModel] = Field(default_factory=list)
    total_tokens: int
    budget: int
    selection_log: list[str] = Field(default_factory=list)

    @property
    def total_models(self) -> int:
        return len(self.selected)

    @property
    def utilisation(self) -> float:
        return self.total_tokens / self.budget if self.budget else 0.0


# ── Loader (imperative shell) ─────────────────────────────────────────────

_FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_DEFAULT_LATTICE_ROOT = (
    Path(__file__).resolve().parent.parent / "mental_models"
)


def load_lattice(root: Path | None = None) -> dict[str, MentalModel]:
    """Walk ``mental_models/`` and return slug → MentalModel map.

    Skips admin files (``_*.md``, ``README.md``). Raises on malformed
    frontmatter, missing mandatory fields, or duplicate slugs — fail-fast
    discipline per CLAUDE.md §"No silent failures".

    Args:
        root: Lattice root directory. Defaults to ``mental_models/`` at the
              repository root.

    Returns:
        ``{slug: MentalModel}`` keyed by unique slug.

    Raises:
        FileNotFoundError: lattice directory does not exist.
        ValueError: malformed frontmatter, schema-validation failure, or
                    duplicate slug.
    """
    root = root or _DEFAULT_LATTICE_ROOT
    if not root.exists():
        raise FileNotFoundError(f"Lattice directory not found: {root}")

    lattice: dict[str, MentalModel] = {}

    for md_path in sorted(root.glob("*/*.md")):
        if md_path.name.startswith("_") or md_path.name == "README.md":
            continue
        domain = md_path.parent.name
        text = md_path.read_text(encoding="utf-8")
        match = _FRONTMATTER_PATTERN.match(text)
        if not match:
            raise ValueError(
                f"No frontmatter found in {md_path.relative_to(root)}"
            )
        frontmatter_text, body = match.group(1), match.group(2)

        try:
            fm: dict[str, Any] = yaml.safe_load(frontmatter_text) or {}
        except yaml.YAMLError as exc:
            raise ValueError(
                f"Malformed YAML frontmatter in {md_path.relative_to(root)}: {exc}"
            ) from exc

        # YAML interprets unquoted "X: Y" inside a list item as a dict
        # `{X: Y}` — hostile-to-prose default. Recovery is unambiguous when
        # the schema says list[str]: collapse `{k: v}` back to "k: v".
        # Applied at the boundary (parse_dont_validate). True schema errors
        # (non-string-non-dict items, missing fields) still surface below.
        for field_name in ("code_consequences", "related_models"):
            items = fm.get(field_name)
            if isinstance(items, list):
                fm[field_name] = [
                    _collapse_dict_to_string(item) for item in items
                ]

        try:
            model = MentalModel(
                **fm,
                domain=domain,
                body=body.strip(),
                file_path=str(md_path.relative_to(root)),
            )
        except Exception as exc:
            raise ValueError(
                f"Schema validation failed for {md_path.relative_to(root)}: {exc}"
            ) from exc

        if model.slug in lattice:
            existing = lattice[model.slug].file_path
            raise ValueError(
                f"Duplicate slug {model.slug!r}: "
                f"in {existing} AND {model.file_path}"
            )
        lattice[model.slug] = model

    return lattice


def _collapse_dict_to_string(item: Any) -> Any:
    """Helper: when YAML mis-parses a colon-containing prose bullet as a
    dict, collapse it back to the original string. Pass-through for items
    that are already strings or other types (those will fail Pydantic
    validation if they shouldn't be in a list[str]).

    Single-key dict ``{X: Y}`` → ``"X: Y"``. Multi-key dicts (which would
    indicate a genuine schema violation) pass through unchanged so the
    type error is surfaced loudly by Pydantic.
    """
    if isinstance(item, dict) and len(item) == 1:
        key, val = next(iter(item.items()))
        return f"{key}: {val}"
    return item


# ── Selector (functional core) ────────────────────────────────────────────

# Citation-tier ranking for budget-prioritisation when budget is tight.
# ★★★ peer-reviewed beats ★★ practical beats ★ heuristic beats ◯ qualitative.
_TIER_RANK: dict[str, int] = {"★★★": 0, "★★": 1, "★": 2, "◯": 3}

# Reason codes used in selection_log + return values. Stable strings so
# downstream consumers can depend on them.
_REASON_ALWAYS = "always_load"
_REASON_MOAT = "moat:has_revenue"
_REASON_MGMT = "management:has_proxy_data"
_REASON_LIFECYCLE_FMT = "lifecycle:{archetype}"
_REASON_VAL_ICA = "valuation:ICA_fired"
_REASON_VAL_PSA = "valuation:PSA_fired"
_REASON_VAL_BEW = "valuation:BEW_fired"
_REASON_BUDGET = "budget_exceeded"


def select_models_for_dive(
    lattice: dict[str, MentalModel],
    profile: LatticeProfile,
    *,
    token_budget: int = 8000,
) -> CompositionResult:
    """Pure function: select relevant subset of lattice for a dive.

    Selection rules (ADR-024 §1.5):

    1. **Always-load**: every model with ``always_load=true`` regardless of
       profile (core/, bias/, plus most agent-discipline engineering).
    2. **Domain-conditional**:

       - ``moat/`` if ``profile.has_revenue``
       - ``management/`` if ``profile.has_proxy_data``
       - ``lifecycle/<archetype>`` matching ``profile.archetype``
       - ``valuation/`` matching the specific overlay that fired

    3. **Token-budget enforcement**: rank by (always_load first, then
       citation tier, then slug); cut at budget; defer the rest.

    Pure function — no I/O. Test by passing a hand-built lattice dict.

    Args:
        lattice: ``{slug: MentalModel}`` from ``load_lattice``.
        profile: company state driving conditional inclusion.
        token_budget: cap on total ``token_cost_estimate`` of selected
                      models. Default 8000 (raised from 6000 on 2026-05-16
                      after LULU run #103 surfaced thorndike_outsiders
                      being budget-starved at 6000t — Group 0 always_load
                      core+bias consumed 5530t, leaving 470t headroom and
                      Thorndike at 380t couldn't fit alongside other
                      conditional fires). 8000t still well within Sonnet
                      4.6's 200K context window (typical full prompt
                      ~12-13K tokens).

    Returns:
        ``CompositionResult`` with selected, deferred, log.
    """
    # Stage 1+2: build the candidate set with reasons.
    candidates: dict[str, tuple[MentalModel, str]] = {}

    for model in lattice.values():
        if model.always_load:
            candidates[model.slug] = (model, _REASON_ALWAYS)

    for model in lattice.values():
        if model.slug in candidates:
            continue
        reason = _domain_conditional_reason(model, profile)
        if reason is not None:
            candidates[model.slug] = (model, reason)

    # Stage 3: rank for budget enforcement.
    # Priority groups (ADR-024 §1.5 + the lattice's own opportunity_cost lens):
    #
    #   Group 0  core/ + bias/ always_load (foundational stance + guardrails;
    #            non-negotiable — these are what the lattice IS)
    #   Group 1  conditional fires (moat / management / lifecycle / valuation
    #            when their condition actually triggered — highest dive-specific
    #            signal-per-token)
    #   Group 2  other always_load (engineering, statistical, info-theory,
    #            etc. — universal-but-not-foundational; cut first under budget)
    #
    # Within each group, rank by citation tier then slug for determinism.
    def _priority_group(pair: tuple[MentalModel, str]) -> int:
        model, reason = pair
        if reason == _REASON_ALWAYS and model.domain in ("core", "bias"):
            return 0
        if reason != _REASON_ALWAYS:
            return 1
        return 2

    ranked = sorted(
        candidates.values(),
        key=lambda pair: (
            _priority_group(pair),
            _TIER_RANK.get(pair[0].citation_tier, 99),
            pair[0].slug,
        ),
    )

    selected: list[MentalModel] = []
    deferred: list[MentalModel] = []
    log: list[str] = []
    total = 0

    for model, reason in ranked:
        if total + model.token_cost_estimate <= token_budget:
            selected.append(model)
            total += model.token_cost_estimate
            log.append(
                f"INCLUDED  {model.slug:<44} "
                f"{model.citation_tier:<4} "
                f"{model.token_cost_estimate:>4}t  reason={reason}"
            )
        else:
            deferred.append(model)
            log.append(
                f"DEFERRED  {model.slug:<44} "
                f"{model.citation_tier:<4} "
                f"{model.token_cost_estimate:>4}t  reason={_REASON_BUDGET}"
            )

    return CompositionResult(
        selected=selected,
        deferred=deferred,
        total_tokens=total,
        budget=token_budget,
        selection_log=log,
    )


def _domain_conditional_reason(
    model: MentalModel, profile: LatticeProfile,
) -> str | None:
    """Return the inclusion reason for a non-always-load model, or None
    if no condition fires. Pure helper.
    """
    domain = model.domain
    slug = model.slug

    if domain == "moat" and profile.has_revenue:
        return _REASON_MOAT

    if domain == "management" and profile.has_proxy_data:
        return _REASON_MGMT

    if domain == "lifecycle" and profile.archetype is not None:
        # archetype slug is a substring of the model slug
        # (e.g. archetype='platform_dominator' matches
        # slug='platform_dominator_archetype')
        if profile.archetype in slug:
            return _REASON_LIFECYCLE_FMT.format(archetype=profile.archetype)
        return None

    if domain == "valuation" and profile.overlays_fired:
        # ICA → Peters-Taylor + Eisfeldt-Papanikolaou
        if "ICA" in profile.overlays_fired and (
            "peters_taylor" in slug or "eisfeldt" in slug
        ):
            return _REASON_VAL_ICA
        # BEW → Bessembinder
        if "BEW" in profile.overlays_fired and "bessembinder" in slug:
            return _REASON_VAL_BEW
        # PSA → post_spinoff_archetype lives in lifecycle/, but if a
        # future PSA-specific valuation model is added it would match here.
        # No valuation/ models specifically map to PSA today.
        return None

    return None


# ── Convenience: build profile from warehouse state ──────────────────────


def profile_from_dive_outcome(
    *,
    has_revenue: bool,
    has_proxy_data: bool,
    archetype: Archetype | None,
    overlays_fired: set[OverlayName] | frozenset[OverlayName] | None,
) -> LatticeProfile:
    """Thin builder so callers can construct a LatticeProfile without
    importing the Pydantic class directly. Useful for the orchestrator's
    integration point with the future ``narrative.py``.
    """
    return LatticeProfile(
        has_revenue=has_revenue,
        has_proxy_data=has_proxy_data,
        archetype=archetype,
        overlays_fired=frozenset(overlays_fired or set()),
    )


# ── Validator (graph integrity — ADR-024 §1.6 / §1.7) ────────────────────


class DanglingReference(BaseModel):
    """A `related_models` entry that does not resolve to any model file."""

    source_slug: str
    source_file: str
    referenced_slug: str

    model_config = {"frozen": True}

    def __str__(self) -> str:
        return (
            f"{self.source_file}: '{self.source_slug}' references "
            f"'{self.referenced_slug}' but no such model exists"
        )


class AsymmetricEdge(BaseModel):
    """An A→B link where B does not also list A. Warning-level — the lattice
    is a *graph*, not a tree, but reciprocity isn't strictly required: a
    niche model often draws from a foundational one without the foundational
    model needing to point back. Surfaced for review, not failure.
    """

    source_slug: str
    target_slug: str

    model_config = {"frozen": True}

    def __str__(self) -> str:
        return f"{self.source_slug} -> {self.target_slug} (no reverse edge)"


class ValidationReport(BaseModel):
    """Result of ``validate_lattice``. ``errors`` are CI-blocking
    (dangling references — typos or removed slugs that must be fixed).
    ``warnings`` are informational (asymmetric edges).
    """

    errors: list[DanglingReference] = Field(default_factory=list)
    warnings: list[AsymmetricEdge] = Field(default_factory=list)
    total_models: int = 0
    total_edges: int = 0

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (
            f"{self.total_models} models / {self.total_edges} edges / "
            f"{len(self.errors)} errors / {len(self.warnings)} warnings"
        )


def validate_lattice(lattice: dict[str, MentalModel]) -> ValidationReport:
    """Pure function: integrity-check a loaded lattice graph.

    **Errors** (block CI):
      - Every slug in ``related_models`` resolves to an existing model.

    **Warnings** (informational):
      - Asymmetric edges: A → B exists but B → A does not. The lattice is
        a directed graph by design (e.g. a bias model "draws from" a core
        model without the core model needing to back-reference every bias),
        so reciprocity isn't enforced — it's just surfaced for review.

    No I/O. Test by passing a hand-built lattice dict.
    """
    slugs = set(lattice.keys())
    errors: list[DanglingReference] = []
    edges_out: dict[str, set[str]] = {}
    total_edges = 0

    for slug, model in lattice.items():
        edges_out[slug] = set(model.related_models)
        total_edges += len(model.related_models)
        for ref in model.related_models:
            if ref not in slugs:
                errors.append(DanglingReference(
                    source_slug=slug,
                    source_file=model.file_path,
                    referenced_slug=ref,
                ))

    warnings: list[AsymmetricEdge] = []
    for source, refs in edges_out.items():
        for target in refs:
            # Only flag asymmetry between pairs where BOTH ends exist —
            # dangling refs are reported as errors above; double-reporting
            # them as warnings would just be noise.
            if target not in edges_out:
                continue
            if source not in edges_out[target]:
                warnings.append(AsymmetricEdge(
                    source_slug=source, target_slug=target,
                ))

    # Stable ordering so test diffs are deterministic.
    errors.sort(key=lambda e: (e.source_slug, e.referenced_slug))
    warnings.sort(key=lambda w: (w.source_slug, w.target_slug))

    return ValidationReport(
        errors=errors,
        warnings=warnings,
        total_models=len(lattice),
        total_edges=total_edges,
    )


__all__ = [
    "MentalModel",
    "LatticeProfile",
    "CompositionResult",
    "Archetype",
    "OverlayName",
    "CitationTier",
    "load_lattice",
    "select_models_for_dive",
    "profile_from_dive_outcome",
    "validate_lattice",
    "ValidationReport",
    "DanglingReference",
    "AsymmetricEdge",
]
