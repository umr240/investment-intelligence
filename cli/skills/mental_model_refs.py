"""Typo-catch for `mental_models:` references in skill frontmatter.

Per the architectural separation established 2026-05-16: mental models
live in `mental_models/` (the lattice — ADR-024); skills MAY reference
them in their frontmatter as documentation of "what cognitive frame
guides this workflow." The reference is **documentary, not runtime
binding** — narrative LLM coupling happens in `deepdive/mental_model_composer.py`,
not here.

This module catches typos in those documentary references:

  - Discover all real model slugs (`mental_models/<domain>/<slug>.md`)
  - For each skill's `mental_models:` array, flag unresolved slugs
  - WARNING severity only — typos surface, but build doesn't fail

Surfaces via:
  - `invest skill compose <name>` — display block listing declared models
                                     with their file paths (or [UNRESOLVED])
  - `tests/test_skills/test_mental_model_refs.py` — CI smoke test that
    asserts ZERO unresolved slugs across the inventory (typo guard)

Not surfaced via:
  - The five-dimension eval table (this is documentary, not a skill
    quality metric — would force the wrong question)
  - `validate_lineage()` (different concern — lineage is about version
    history; this is about lattice cross-reference)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LATTICE_DIR = _PROJECT_ROOT / "mental_models"


@dataclass
class ModelRef:
    """One mental-model reference declared by a skill's frontmatter."""
    slug: str
    file_path: Path | None      # None when unresolved
    domain: str | None          # `core` | `moat` | ... | None when unresolved

    @property
    def resolved(self) -> bool:
        return self.file_path is not None

    def render_line(self) -> str:
        if self.resolved:
            # Show relative path from project root for readability
            try:
                rel = self.file_path.relative_to(_PROJECT_ROOT)
            except ValueError:
                rel = self.file_path
            return f"    ├── {self.slug}  ({rel.as_posix()})"
        return f"    ├── {self.slug}  [UNRESOLVED — typo or missing file]"


@dataclass
class MentalModelFinding:
    """One issue with a skill's mental_models: array."""
    skill_name: str
    severity: str           # always "warning" today
    message: str

    def render_line(self) -> str:
        return f"WARN   {self.skill_name:24s}  {self.message}"


def discover_lattice_slugs() -> dict[str, Path]:
    """Map every `<slug>` (filename without `.md`) to its absolute path.

    Walks `mental_models/<domain>/<slug>.md`. Skips top-level index files
    (README.md, _gaps.md, _index.md) — slug discovery is per-model only.
    """
    if not _LATTICE_DIR.exists():
        return {}
    slugs: dict[str, Path] = {}
    for path in _LATTICE_DIR.rglob("*.md"):
        # Skip index files at any level
        if path.name.startswith("_") or path.name.lower() == "readme.md":
            continue
        # Only files inside a domain subdirectory (depth ≥ 2 below lattice)
        if path.parent == _LATTICE_DIR:
            continue
        slugs[path.stem] = path
    return slugs


def load_skill_mental_models(skill_name: str) -> tuple[list[ModelRef], list[MentalModelFinding]]:
    """Parse one skill's `mental_models:` array and resolve each slug.

    Returns (refs, findings). Findings are WARNINGs for unresolved slugs.
    A skill with no `mental_models:` declaration returns ([], []).
    """
    from cli.skills.runtime import load_skill_frontmatter
    fm = load_skill_frontmatter(skill_name)
    raw = fm.get("mental_models")
    refs: list[ModelRef] = []
    findings: list[MentalModelFinding] = []

    if raw is None:
        return refs, findings
    if not isinstance(raw, list):
        findings.append(MentalModelFinding(
            skill_name=skill_name, severity="warning",
            message=f"`mental_models:` must be a list, got: {type(raw).__name__}",
        ))
        return refs, findings

    catalog = discover_lattice_slugs()
    for item in raw:
        slug = str(item).strip()
        if not slug:
            continue
        path = catalog.get(slug)
        if path is None:
            refs.append(ModelRef(slug=slug, file_path=None, domain=None))
            findings.append(MentalModelFinding(
                skill_name=skill_name, severity="warning",
                message=(
                    f"`mental_models: [{slug}]` does not resolve to a real "
                    f"lattice entry (looked for `mental_models/*/<slug>.md`). "
                    f"Typo, or model not yet authored."
                ),
            ))
            continue
        # Domain is the parent directory name (e.g., mental_models/core/xxx → "core")
        domain = path.parent.name
        refs.append(ModelRef(slug=slug, file_path=path, domain=domain))

    return refs, findings


def load_all_skill_mental_models() -> tuple[
    dict[str, list[ModelRef]],
    list[MentalModelFinding],
]:
    """Load mental-model refs for every skill."""
    from cli.skills.lineage import discover_skill_names
    refs_by_skill: dict[str, list[ModelRef]] = {}
    all_findings: list[MentalModelFinding] = []
    for name in discover_skill_names():
        try:
            refs, findings = load_skill_mental_models(name)
        except Exception as exc:
            all_findings.append(MentalModelFinding(
                skill_name=name, severity="warning",
                message=f"mental_models load failed: {exc}",
            ))
            continue
        refs_by_skill[name] = refs
        all_findings.extend(findings)
    return refs_by_skill, all_findings


def render_mental_models_block(refs: list[ModelRef]) -> str:
    """Render a skill's declared mental models as a tree block.

    Empty when the skill declares none — caller decides whether to omit
    the section entirely.
    """
    if not refs:
        return ""
    lines = ["  Mental models (documentary — see ADR-024 lattice):"]
    for r in refs:
        lines.append(r.render_line())
    return "\n".join(lines)


__all__ = [
    "ModelRef",
    "MentalModelFinding",
    "discover_lattice_slugs",
    "load_skill_mental_models",
    "load_all_skill_mental_models",
    "render_mental_models_block",
]
