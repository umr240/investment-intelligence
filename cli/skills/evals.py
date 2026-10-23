"""ADR-035 — Skill evaluation harness.

Implements the four eval dimensions from Anthropic's "Exploring how Skills
evolve" framing (Evaluation / Versioning / Composability):

    1. TRIGGERING_ACCURACY    — does Claude invoke the right skill for
                                a given user prompt? (requires LLM eval)
    2. OUTPUT_QUALITY         — does the skill's output match the declared
                                schema / postcondition shape?
    3. SCRIPT_EXECUTION       — does the underlying CLI surface still
                                exist + does the Python impl import?
    4. FRONTMATTER_STRUCTURE  — does the frontmatter satisfy ADR-032 §2.1
                                + the version-lineage invariants
                                (ADR-034 §3)?

This module is purely an aggregator over existing validators:
  - `cli.skills.runtime:load_skill_frontmatter` → frontmatter structure
  - `cli.skills.lineage:validate_lineage`       → version lineage
  - test_signature_compatibility tests          → CLI surface stability

For each skill, `run_skill_evals()` returns a `SkillEvalReport` with one
result per dimension. The CLI surfaces this via `invest skill eval`.

Triggering accuracy is deferred — it requires running Claude with seeded
user prompts and checking which skill it invokes. ADR-035 §3 specifies
the corpus format for when this is built out.
"""
from __future__ import annotations

import importlib
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"


class EvalDimension(str, Enum):
    """Five eval dimensions — four from Anthropic's slide + composability
    (ADR-036 §3, fifth dimension reserved by ADR-035 §8)."""
    TRIGGERING_ACCURACY = "triggering_accuracy"
    OUTPUT_QUALITY = "output_quality"
    SCRIPT_EXECUTION = "script_execution"
    FRONTMATTER_STRUCTURE = "frontmatter_structure"
    COMPOSABILITY_CONSISTENCY = "composability_consistency"


class EvalStatus(str, Enum):
    PASS = "PASS"     # the check ran and succeeded
    FAIL = "FAIL"     # the check ran and the skill failed it
    SKIP = "SKIP"     # the check is not applicable / deferred
    ERROR = "ERROR"   # the check itself errored (infrastructure issue)


@dataclass
class EvalResult:
    """One dimension's outcome for one skill."""
    dimension: EvalDimension
    status: EvalStatus
    detail: str = ""

    def render_short(self) -> str:
        symbol = {
            EvalStatus.PASS: "✓",
            EvalStatus.FAIL: "✗",
            EvalStatus.SKIP: "○",
            EvalStatus.ERROR: "!",
        }[self.status]
        return f"  [{symbol}] {self.dimension.value:24s} {self.status.value:5s}  {self.detail}"


@dataclass
class SkillEvalReport:
    """All four dimensions' results for one skill."""
    skill_name: str
    current_version: str
    results: list[EvalResult] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        """True iff every non-skipped dimension passes."""
        return all(
            r.status in (EvalStatus.PASS, EvalStatus.SKIP)
            for r in self.results
        )

    @property
    def has_failure(self) -> bool:
        return any(r.status == EvalStatus.FAIL for r in self.results)

    def render(self) -> str:
        lines = [f"# {self.skill_name}  (v{self.current_version})"]
        for r in self.results:
            lines.append(r.render_short())
        return "\n".join(lines)


# ── Dimension checkers ────────────────────────────────────────────────────


def _check_frontmatter_structure(skill_name: str) -> EvalResult:
    """ADR-032 §2.1 + ADR-034 §3 — frontmatter validity + lineage."""
    from cli.skills.lineage import load_skill_lineage, validate_lineage
    try:
        ln, parse_findings = load_skill_lineage(skill_name)
    except Exception as exc:
        return EvalResult(
            dimension=EvalDimension.FRONTMATTER_STRUCTURE,
            status=EvalStatus.FAIL,
            detail=f"frontmatter parse failed: {exc}",
        )

    findings = parse_findings + validate_lineage([ln])
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        return EvalResult(
            dimension=EvalDimension.FRONTMATTER_STRUCTURE,
            status=EvalStatus.FAIL,
            detail=f"{len(errors)} lineage error(s); first: {errors[0].message[:80]}",
        )
    warnings = [f for f in findings if f.severity == "warning"]
    if warnings:
        return EvalResult(
            dimension=EvalDimension.FRONTMATTER_STRUCTURE,
            status=EvalStatus.PASS,
            detail=f"OK (with {len(warnings)} warning(s) — see lineage --validate)",
        )
    return EvalResult(
        dimension=EvalDimension.FRONTMATTER_STRUCTURE,
        status=EvalStatus.PASS,
        detail=f"frontmatter + changelog clean ({len(ln.entries)} entries)",
    )


def _check_script_execution(skill_name: str) -> EvalResult:
    """Two sub-checks:
      (a) The skill's `implementation:` Python module imports cleanly.
      (b) Every `invest <subcommand>` referenced in the skill body still
          resolves to a valid CLI surface.

    The second check is the same logic as
    `tests/test_skills/test_signature_compatibility.py` — duplicated here
    so a single `invest skill eval <name>` invocation surfaces it without
    running pytest. The pytest test still runs in CI.
    """
    from cli.skills.runtime import load_skill_frontmatter
    try:
        fm = load_skill_frontmatter(skill_name)
    except Exception as exc:
        return EvalResult(
            dimension=EvalDimension.SCRIPT_EXECUTION,
            status=EvalStatus.ERROR,
            detail=f"frontmatter not loadable: {exc}",
        )

    impl_path = fm.get("implementation")
    if impl_path:
        # implementation: cli/skills/audit_completeness.py → module dotted name
        if isinstance(impl_path, str) and impl_path.endswith(".py"):
            module_dotted = impl_path.replace("/", ".").replace("\\", ".")[:-3]
            try:
                importlib.import_module(module_dotted)
            except Exception as exc:
                return EvalResult(
                    dimension=EvalDimension.SCRIPT_EXECUTION,
                    status=EvalStatus.FAIL,
                    detail=f"impl import failed ({module_dotted}): {exc}",
                )

    # Body CLI-surface check
    body_path = _SKILLS_DIR / f"{skill_name}.md"
    body = body_path.read_text(encoding="utf-8")
    import re
    subcommands = set(re.findall(r"invest\s+([a-z][a-z\-]*)", body))
    # Filter out subcommand-app names that aren't real top-level subcommands
    # (the runner takes `invest skill run`, not `invest skill`).
    failures: list[str] = []
    for sub in sorted(subcommands):
        try:
            r = subprocess.run(
                ["uv", "run", "invest", sub, "--help"],
                capture_output=True, timeout=30,
            )
            if r.returncode != 0:
                failures.append(sub)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            failures.append(sub)

    if failures:
        return EvalResult(
            dimension=EvalDimension.SCRIPT_EXECUTION,
            status=EvalStatus.FAIL,
            detail=f"unresolved CLI subcommands referenced in body: {failures}",
        )
    return EvalResult(
        dimension=EvalDimension.SCRIPT_EXECUTION,
        status=EvalStatus.PASS,
        detail=f"impl imports + {len(subcommands)} CLI ref(s) resolved",
    )


def _check_output_quality(skill_name: str) -> EvalResult:
    """The skill must declare testable postconditions in its frontmatter.

    Per ADR-032 §2.1, `postconditions:` is mandatory. Per ADR-035 §2.2,
    an `output_schema:` is OPTIONAL — when present, the runtime can
    validate skill output against it. Today no skill declares a schema;
    this check verifies postcondition declaration as the minimum bar.

    Future: when output_schema becomes mandatory, this check tightens
    to validate the most recent `skill_invocations.render_output` row
    against the schema.
    """
    from cli.skills.runtime import load_skill_frontmatter
    try:
        fm = load_skill_frontmatter(skill_name)
    except Exception as exc:
        return EvalResult(
            dimension=EvalDimension.OUTPUT_QUALITY,
            status=EvalStatus.ERROR,
            detail=f"frontmatter not loadable: {exc}",
        )

    postconditions = fm.get("postconditions") or []
    if not isinstance(postconditions, list) or len(postconditions) == 0:
        return EvalResult(
            dimension=EvalDimension.OUTPUT_QUALITY,
            status=EvalStatus.FAIL,
            detail="postconditions: array is missing or empty (ADR-032 §2.1)",
        )

    has_schema = bool(fm.get("output_schema"))
    if has_schema:
        return EvalResult(
            dimension=EvalDimension.OUTPUT_QUALITY,
            status=EvalStatus.PASS,
            detail=f"{len(postconditions)} postcondition(s) + output_schema declared",
        )
    # No schema yet — this is a SKIP (not a fail) because ADR-035 makes
    # output_schema optional today. Surface the gap so maintainers see it.
    return EvalResult(
        dimension=EvalDimension.OUTPUT_QUALITY,
        status=EvalStatus.SKIP,
        detail=(
            f"{len(postconditions)} postcondition(s) declared; "
            f"output_schema absent (ADR-035 §2.2 — optional today)"
        ),
    )


def _check_composability_consistency(skill_name: str) -> EvalResult:
    """ADR-036 §3 — composes: block parses + validates.

    PASS when the composes: block is empty OR every entry resolves
    (skill refs exist; constraints well-formed; no cycles or self-loops).
    FAIL on any error finding from validate_composition().

    A skill with no composes: declaration → SKIP (nothing to validate).
    """
    from cli.skills.composability import (
        load_skill_composition, validate_composition,
    )
    try:
        comp, parse_findings = load_skill_composition(skill_name)
    except Exception as exc:
        return EvalResult(
            dimension=EvalDimension.COMPOSABILITY_CONSISTENCY,
            status=EvalStatus.ERROR,
            detail=f"composition load failed: {exc}",
        )

    if comp.is_empty and not parse_findings:
        return EvalResult(
            dimension=EvalDimension.COMPOSABILITY_CONSISTENCY,
            status=EvalStatus.SKIP,
            detail="no composes: block declared (ADR-036 §2 — optional)",
        )

    # Cross-skill validation requires the FULL inventory for ref checking.
    from cli.skills.composability import load_all_compositions
    _, all_findings = load_all_compositions()
    # Filter to this skill's findings only
    findings = [
        f for f in (parse_findings + all_findings)
        if f.skill_name == skill_name
    ]
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        return EvalResult(
            dimension=EvalDimension.COMPOSABILITY_CONSISTENCY,
            status=EvalStatus.FAIL,
            detail=f"{len(errors)} composition error(s); first: {errors[0].message[:80]}",
        )
    return EvalResult(
        dimension=EvalDimension.COMPOSABILITY_CONSISTENCY,
        status=EvalStatus.PASS,
        detail=(
            f"composes resolves cleanly: "
            f"{len(comp.skills)} skill(s), {len(comp.mcps)} MCP(s), "
            f"{len(comp.libraries)} lib(s)"
        ),
    )


def _check_triggering_accuracy(skill_name: str) -> EvalResult:
    """Deferred per ADR-035 §3. Triggering accuracy requires running an
    LLM against a corpus of seeded user prompts and checking which skill
    the LLM picks. The corpus format is specified in ADR-035 §3.2; the
    runner is not yet built.

    For now this dimension always returns SKIP with a pointer to the
    deferred work — so it surfaces in the eval output (visible gap)
    without blocking CI.
    """
    corpus_path = _SKILLS_DIR / "_evals" / f"{skill_name}_triggering.yaml"
    if corpus_path.exists():
        return EvalResult(
            dimension=EvalDimension.TRIGGERING_ACCURACY,
            status=EvalStatus.SKIP,
            detail=f"corpus exists at {corpus_path.name} but runner not implemented (ADR-035 §3)",
        )
    return EvalResult(
        dimension=EvalDimension.TRIGGERING_ACCURACY,
        status=EvalStatus.SKIP,
        detail="no triggering corpus declared (ADR-035 §3 — deferred)",
    )


# ── Orchestrators ─────────────────────────────────────────────────────────


def run_skill_evals(skill_name: str) -> SkillEvalReport:
    """Run all four eval dimensions on one skill."""
    from cli.skills.runtime import load_skill_frontmatter
    try:
        fm = load_skill_frontmatter(skill_name)
        current_version = str(fm.get("version", "?"))
    except Exception:
        current_version = "?"

    report = SkillEvalReport(skill_name=skill_name, current_version=current_version)
    report.results.append(_check_frontmatter_structure(skill_name))
    report.results.append(_check_script_execution(skill_name))
    report.results.append(_check_output_quality(skill_name))
    report.results.append(_check_composability_consistency(skill_name))
    report.results.append(_check_triggering_accuracy(skill_name))
    return report


def run_all_skill_evals() -> list[SkillEvalReport]:
    """Run evals on every skill in `.claude/skills/`."""
    from cli.skills.lineage import discover_skill_names
    return [run_skill_evals(name) for name in discover_skill_names()]


def render_summary(reports: list[SkillEvalReport]) -> str:
    """Render a one-line-per-skill summary table."""
    if not reports:
        return "(no skills evaluated)"

    lines: list[str] = []
    lines.append("# Skill evals — ADR-035 four-dimension report")
    lines.append("")
    header = (
        f"{'skill':24s}  v{'er':5s}  "
        f"{'frontmatter':12s}  {'script':12s}  {'output':12s}  "
        f"{'composability':13s}  {'triggering':12s}"
    )
    lines.append(header)
    lines.append("─" * len(header))

    for rep in reports:
        cells: list[str] = []
        for dim in (
            EvalDimension.FRONTMATTER_STRUCTURE,
            EvalDimension.SCRIPT_EXECUTION,
            EvalDimension.OUTPUT_QUALITY,
            EvalDimension.COMPOSABILITY_CONSISTENCY,
            EvalDimension.TRIGGERING_ACCURACY,
        ):
            r = next((x for x in rep.results if x.dimension == dim), None)
            cells.append(r.status.value if r else "?")
        lines.append(
            f"{rep.skill_name:24s}  v{rep.current_version:5s}  "
            f"{cells[0]:12s}  {cells[1]:12s}  {cells[2]:12s}  "
            f"{cells[3]:13s}  {cells[4]:12s}"
        )
    return "\n".join(lines)


def has_any_failures(reports: list[SkillEvalReport]) -> bool:
    """True iff any report contains an EvalStatus.FAIL — the CI gate."""
    return any(rep.has_failure for rep in reports)


__all__ = [
    "EvalDimension",
    "EvalStatus",
    "EvalResult",
    "SkillEvalReport",
    "run_skill_evals",
    "run_all_skill_evals",
    "render_summary",
    "has_any_failures",
]
