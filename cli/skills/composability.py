"""ADR-036 — Skill composability: dependency graph + validator.

Implements the Composability pillar from Anthropic's "Don't Build Agents,
Build Skills Instead" framing. Each skill declares an optional `composes:`
block in its frontmatter listing the other artifacts it depends on:

    composes:
      skills:                   # other .claude/skills/* files
        - name: audit-completeness
          constraint: ">=1.0"   # PEP-440 style version range
          relation: "uses"      # uses | suggests | extends
      mcps:                     # MCP servers the skill calls
        - name: filesystem
          capability: read_only
      libraries:                # Python libs with VERSION-SENSITIVE deps
        - name: edgartools
          constraint: ">=2.0"

This module:

  - Parses the `composes:` block via `load_skill_composition()`
  - Validates skill references resolve + constraints are well-formed via
    `validate_composition()`
  - Builds a multi-skill dependency graph via `build_dependency_graph()`
  - Renders a per-skill tree view via `render_composition_tree()`

The fifth eval dimension (COMPOSABILITY_CONSISTENCY in evals.py) wraps
this module. The CLI surface is `invest skill compose [name]`.

Anthropic's slide example (Branded Decks = Brand Style + PowerPoint;
PowerPoint = MCP + pandas) maps directly to this schema: relation="uses"
for skill deps, MCPs as mcps[], pandas/etc as libraries[].
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"

# Valid relation kinds per ADR-036 §2.1.
_VALID_RELATIONS = frozenset({"uses", "suggests", "extends"})

# Loose PEP-440 / npm-style constraint validator. Accepts `>=1.0`, `>=1.0,<2.0`,
# `~=1.2`, `==1.0.3`, `>=1.0.0`. Strict satisfaction is NOT performed today —
# only format validity. Future amendment may add resolution.
_CONSTRAINT_RE = re.compile(
    r"^\s*(?:(?:==|>=|<=|!=|~=|>|<)\s*\d+(?:\.\d+){0,2}(?:-[A-Za-z0-9]+)?)"
    r"(?:\s*,\s*(?:==|>=|<=|!=|~=|>|<)\s*\d+(?:\.\d+){0,2})*\s*$"
)


# ── Data types ────────────────────────────────────────────────────────────


@dataclass
class SkillDep:
    """One skill-to-skill dependency entry."""
    name: str
    constraint: str = ""
    relation: str = "uses"      # uses | suggests | extends


@dataclass
class MCPDep:
    """One skill-to-MCP dependency entry."""
    name: str
    capability: str = ""        # informational; no enforcement today


@dataclass
class LibraryDep:
    """One skill-to-Python-library dependency entry.

    Only LIST libraries here when the version constraint matters
    (e.g., edgartools >= 2.0 because the skill calls a 2.0-only API).
    Routine deps (sqlalchemy, httpx, pydantic) are NOT listed — they
    are project-wide via pyproject.toml.
    """
    name: str
    constraint: str = ""


@dataclass
class SkillComposition:
    """Parsed `composes:` block for one skill."""
    skill_name: str
    skills: list[SkillDep] = field(default_factory=list)
    mcps: list[MCPDep] = field(default_factory=list)
    libraries: list[LibraryDep] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.skills or self.mcps or self.libraries)


@dataclass
class CompositionFinding:
    """One issue found by `validate_composition()`."""
    skill_name: str
    severity: str           # "error" | "warning"
    message: str

    def render_line(self) -> str:
        prefix = "ERROR  " if self.severity == "error" else "WARN   "
        return f"{prefix} {self.skill_name:24s}  {self.message}"


# ── Parsing ───────────────────────────────────────────────────────────────


def _parse_skill_dep(skill_name: str, item: Any) -> tuple[SkillDep | None, list[CompositionFinding]]:
    findings: list[CompositionFinding] = []
    if not isinstance(item, dict):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"composes.skills entry must be a dict, got: {item!r}",
        ))
        return None, findings

    name = item.get("name")
    if not name or not isinstance(name, str):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"composes.skills entry missing `name`: {item!r}",
        ))
        return None, findings

    relation = item.get("relation", "uses")
    if relation not in _VALID_RELATIONS:
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=(
                f"composes.skills[{name}] has invalid relation {relation!r}; "
                f"must be one of {sorted(_VALID_RELATIONS)}"
            ),
        ))
        return None, findings

    constraint = item.get("constraint", "")
    if constraint and not _CONSTRAINT_RE.match(str(constraint)):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=(
                f"composes.skills[{name}] constraint {constraint!r} is not a "
                f"valid PEP-440 range (examples: '>=1.0', '>=1.0,<2.0', '~=1.2')"
            ),
        ))
        # Continue — record the dep anyway so the graph still shows the edge

    return SkillDep(name=str(name), constraint=str(constraint), relation=relation), findings


def _parse_mcp_dep(skill_name: str, item: Any) -> tuple[MCPDep | None, list[CompositionFinding]]:
    findings: list[CompositionFinding] = []
    if not isinstance(item, dict):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"composes.mcps entry must be a dict, got: {item!r}",
        ))
        return None, findings
    name = item.get("name")
    if not name or not isinstance(name, str):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"composes.mcps entry missing `name`: {item!r}",
        ))
        return None, findings
    return MCPDep(name=str(name), capability=str(item.get("capability", ""))), findings


def _parse_library_dep(skill_name: str, item: Any) -> tuple[LibraryDep | None, list[CompositionFinding]]:
    findings: list[CompositionFinding] = []
    if not isinstance(item, dict):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"composes.libraries entry must be a dict, got: {item!r}",
        ))
        return None, findings
    name = item.get("name")
    if not name or not isinstance(name, str):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"composes.libraries entry missing `name`: {item!r}",
        ))
        return None, findings
    constraint = item.get("constraint", "")
    if constraint and not _CONSTRAINT_RE.match(str(constraint)):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=(
                f"composes.libraries[{name}] constraint {constraint!r} is "
                f"malformed (PEP-440 range expected)"
            ),
        ))
    return LibraryDep(name=str(name), constraint=str(constraint)), findings


def load_skill_composition(
    skill_name: str,
) -> tuple[SkillComposition, list[CompositionFinding]]:
    """Parse one skill's `composes:` frontmatter block.

    A missing `composes:` block is NOT an error — most skills today have
    no composition. Returns an empty SkillComposition with no findings.
    """
    from cli.skills.runtime import load_skill_frontmatter
    fm = load_skill_frontmatter(skill_name)
    raw = fm.get("composes") or {}
    composition = SkillComposition(skill_name=skill_name)
    findings: list[CompositionFinding] = []

    if not isinstance(raw, dict):
        findings.append(CompositionFinding(
            skill_name=skill_name, severity="error",
            message=f"`composes:` must be a mapping, got: {type(raw).__name__}",
        ))
        return composition, findings

    for item in raw.get("skills") or []:
        dep, sub = _parse_skill_dep(skill_name, item)
        findings.extend(sub)
        if dep is not None:
            composition.skills.append(dep)
    for item in raw.get("mcps") or []:
        dep, sub = _parse_mcp_dep(skill_name, item)
        findings.extend(sub)
        if dep is not None:
            composition.mcps.append(dep)
    for item in raw.get("libraries") or []:
        dep, sub = _parse_library_dep(skill_name, item)
        findings.extend(sub)
        if dep is not None:
            composition.libraries.append(dep)

    return composition, findings


def load_all_compositions() -> tuple[list[SkillComposition], list[CompositionFinding]]:
    """Load `composes:` for every skill in `.claude/skills/`."""
    from cli.skills.lineage import discover_skill_names
    all_findings: list[CompositionFinding] = []
    compositions: list[SkillComposition] = []
    for name in discover_skill_names():
        try:
            comp, sub = load_skill_composition(name)
        except Exception as exc:
            all_findings.append(CompositionFinding(
                skill_name=name, severity="error",
                message=f"failed to load composition: {exc}",
            ))
            continue
        compositions.append(comp)
        all_findings.extend(sub)
    all_findings.extend(validate_composition(compositions))
    return compositions, all_findings


# ── Validation ────────────────────────────────────────────────────────────


def validate_composition(
    compositions: list[SkillComposition],
) -> list[CompositionFinding]:
    """Cross-skill composition validation per ADR-036 §3.

    Invariants:
      §3.1  every `composes.skills[].name` resolves to an existing skill
            file in .claude/skills/
      §3.2  no self-loops (a skill cannot compose itself)
      §3.3  no direct cycles within the composition graph
            (audit-completeness uses dive-complete AND dive-complete uses
            audit-completeness → cycle); enforced via DFS
    """
    findings: list[CompositionFinding] = []
    known_skill_names = {c.skill_name for c in compositions}

    # §3.1 + §3.2
    for comp in compositions:
        for s in comp.skills:
            if s.name == comp.skill_name:
                findings.append(CompositionFinding(
                    skill_name=comp.skill_name, severity="error",
                    message=f"§3.2: self-loop — skill composes itself ({s.name})",
                ))
            if s.name not in known_skill_names:
                findings.append(CompositionFinding(
                    skill_name=comp.skill_name, severity="error",
                    message=(
                        f"§3.1: composes.skills references unknown skill "
                        f"{s.name!r} (not found in .claude/skills/)"
                    ),
                ))

    # §3.3 — DFS cycle detection on the skill-to-skill subgraph
    adjacency: dict[str, list[str]] = {
        c.skill_name: [s.name for s in c.skills] for c in compositions
    }
    cycles: list[list[str]] = []

    def _dfs(node: str, path: list[str], visited: set[str]) -> None:
        if node in path:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return
        for nxt in adjacency.get(node, []):
            _dfs(nxt, path + [node], visited)
        visited.add(node)

    visited_global: set[str] = set()
    for skill_name in adjacency:
        _dfs(skill_name, [], visited_global)

    for cycle in cycles:
        findings.append(CompositionFinding(
            skill_name=cycle[0], severity="error",
            message=f"§3.3: composition cycle detected: {' → '.join(cycle)}",
        ))

    return findings


# ── Rendering ─────────────────────────────────────────────────────────────


def render_composition_tree(
    comp: SkillComposition,
    current_version: str = "?",
) -> str:
    """Per-skill tree view (Anthropic-slide style)."""
    if comp.is_empty:
        return f"# {comp.skill_name}  v{current_version}\n  (no declared dependencies)\n"

    lines: list[str] = [f"# {comp.skill_name}  v{current_version}"]
    if comp.skills:
        lines.append("  Skills:")
        for s in comp.skills:
            constraint = f" ({s.constraint})" if s.constraint else ""
            # Use `<relation>` not `[relation]` — square brackets are
            # parsed as style markup by rich and disappear from output.
            lines.append(f"    ├── <{s.relation}> {s.name}{constraint}")
    if comp.mcps:
        lines.append("  MCPs:")
        for m in comp.mcps:
            cap = f" — {m.capability}" if m.capability else ""
            lines.append(f"    ├── {m.name}{cap}")
    if comp.libraries:
        lines.append("  Libraries:")
        for lib in comp.libraries:
            constraint = f" ({lib.constraint})" if lib.constraint else ""
            lines.append(f"    ├── {lib.name}{constraint}")
    return "\n".join(lines)


def render_dependency_graph(
    compositions: list[SkillComposition],
) -> str:
    """Cross-skill flat graph rendering (every edge on one line)."""
    lines: list[str] = ["# Skill composition graph (all edges)"]
    lines.append("")
    any_edge = False
    for comp in compositions:
        for s in comp.skills:
            any_edge = True
            constraint = f" ({s.constraint})" if s.constraint else ""
            lines.append(f"  {comp.skill_name} --[{s.relation}]--> {s.name}{constraint}")
        for m in comp.mcps:
            any_edge = True
            lines.append(f"  {comp.skill_name} --[mcp]--> {m.name}")
        for lib in comp.libraries:
            any_edge = True
            constraint = f" ({lib.constraint})" if lib.constraint else ""
            lines.append(f"  {comp.skill_name} --[lib]--> {lib.name}{constraint}")
    if not any_edge:
        lines.append("  (no composition edges declared across the inventory)")
    return "\n".join(lines)


def render_findings(findings: list[CompositionFinding]) -> str:
    if not findings:
        return ""
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    lines: list[str] = []
    lines.append("")
    lines.append(f"# Composition validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    lines.append("─" * 80)
    for f in errors:
        lines.append(f.render_line())
    for f in warnings:
        lines.append(f.render_line())
    return "\n".join(lines)


__all__ = [
    "SkillDep", "MCPDep", "LibraryDep", "SkillComposition",
    "CompositionFinding",
    "load_skill_composition", "load_all_compositions",
    "validate_composition",
    "render_composition_tree", "render_dependency_graph",
    "render_findings",
]
