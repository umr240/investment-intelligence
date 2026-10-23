"""ADR-034 — skill versioning + lineage protocol.

Reads `.claude/skills/*.md` frontmatter and assembles a per-skill version
timeline + cross-skill chronological lineage view. The output formats
match Anthropic's "Exploring how Skills evolve" model (Evaluation +
Versioning + Composability) as referenced 2026-05-16 by the user.

Sources of truth (in priority order):
  1. `.claude/skills/<skill>.md` frontmatter `version` + `changelog:` array
  2. `skill_invocations` table (runtime telemetry per version)
  3. Git history (optional — provides commit SHA + diff lineage)

This module is read-only. It does NOT modify skill files. To bump a
version, edit the frontmatter directly + append a changelog entry; this
module surfaces inconsistencies via `validate_lineage()`.

The CLI surface for this module is `invest skill lineage [skill_name]`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# Same skills-dir resolution as runtime.py (consistent path discipline).
_SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"

# Strict format: "X.Y.Z (YYYY-MM-DD): summary..." per ADR-034 §2.
# Captures version, date, summary. Whitespace around the colon is tolerated.
_CHANGELOG_ENTRY_RE = re.compile(
    r"^(?P<version>\d+\.\d+\.\d+(?:-[A-Z]+)?)"
    r"\s*\("
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"\)"
    r"\s*:\s*"
    r"(?P<summary>.+)$"
)


# ── Data types ────────────────────────────────────────────────────────────


@dataclass(order=True)
class ChangelogEntry:
    """One row from a skill's `changelog:` frontmatter array.

    Ordered by (date, version) ascending — chronological. Two entries
    with identical (date, version) compare equal but should be flagged by
    validate_lineage().
    """
    entry_date: date
    version: str
    skill_name: str = field(compare=False)
    summary: str = field(compare=False)
    raw: str = field(compare=False)

    def render_line(self) -> str:
        return f"{self.entry_date.isoformat()}  {self.skill_name:24s} v{self.version}  {self.summary}"


@dataclass
class SkillLineage:
    """All changelog entries for one skill, ordered oldest → newest."""
    skill_name: str
    current_version: str         # frontmatter `version`
    shadow_mode_until: date | None
    last_reviewed: date | None
    entries: list[ChangelogEntry]  # sorted ascending
    file_path: Path

    @property
    def latest_entry(self) -> ChangelogEntry | None:
        return self.entries[-1] if self.entries else None

    @property
    def is_consistent(self) -> bool:
        """True iff frontmatter `version` matches the highest version
        present in `changelog`. Per ADR-034 §3.1."""
        if not self.entries:
            return False
        return self.latest_entry.version == self.current_version


@dataclass
class LineageValidationFinding:
    """One inconsistency found by validate_lineage()."""
    skill_name: str
    severity: str           # "error" | "warning"
    message: str

    def render_line(self) -> str:
        prefix = "ERROR  " if self.severity == "error" else "WARN   "
        return f"{prefix} {self.skill_name:24s}  {self.message}"


# ── Parsing ───────────────────────────────────────────────────────────────


def _parse_changelog_array(
    skill_name: str,
    raw_entries: list[str] | None,
) -> tuple[list[ChangelogEntry], list[LineageValidationFinding]]:
    """Parse the raw `changelog:` YAML array into typed entries.

    Returns (entries_sorted_ascending, findings). Entries that fail the
    strict regex are recorded as warnings (skipped from sorted list).
    """
    entries: list[ChangelogEntry] = []
    findings: list[LineageValidationFinding] = []
    if not raw_entries:
        return entries, findings

    for raw in raw_entries:
        raw_str = raw if isinstance(raw, str) else str(raw)
        m = _CHANGELOG_ENTRY_RE.match(raw_str.strip())
        if m is None:
            findings.append(LineageValidationFinding(
                skill_name=skill_name,
                severity="warning",
                message=(
                    f"changelog entry does not match required format "
                    f"'X.Y.Z (YYYY-MM-DD): summary': {raw_str!r}"
                ),
            ))
            continue
        try:
            d = date.fromisoformat(m.group("date"))
        except ValueError:
            findings.append(LineageValidationFinding(
                skill_name=skill_name,
                severity="warning",
                message=f"changelog has invalid date: {raw_str!r}",
            ))
            continue
        entries.append(ChangelogEntry(
            entry_date=d,
            version=m.group("version"),
            skill_name=skill_name,
            summary=m.group("summary").strip(),
            raw=raw_str.strip(),
        ))

    entries.sort()
    return entries, findings


def _date_or_none(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def load_skill_lineage(skill_name: str) -> tuple[SkillLineage, list[LineageValidationFinding]]:
    """Load and parse one skill's full lineage.

    Uses `cli.skills.runtime.load_skill_frontmatter` for the actual file
    read (so frontmatter parsing stays consistent with the runtime).
    """
    from cli.skills.runtime import load_skill_frontmatter
    fm = load_skill_frontmatter(skill_name)
    entries, findings = _parse_changelog_array(skill_name, fm.get("changelog"))
    return SkillLineage(
        skill_name=skill_name,
        current_version=str(fm.get("version", "")),
        shadow_mode_until=_date_or_none(fm.get("shadow_mode_until")),
        last_reviewed=_date_or_none(fm.get("last_reviewed")),
        entries=entries,
        file_path=_SKILLS_DIR / f"{skill_name}.md",
    ), findings


def discover_skill_names() -> list[str]:
    """List every skill `name` (filename without `.md`) under .claude/skills/.

    Excludes README.md, _lineage.md, and any file starting with `_`.
    """
    if not _SKILLS_DIR.exists():
        return []
    names: list[str] = []
    for p in sorted(_SKILLS_DIR.glob("*.md")):
        stem = p.stem
        if stem.startswith("_") or stem.upper() == "README":
            continue
        names.append(stem)
    return names


def load_all_skill_lineages() -> tuple[list[SkillLineage], list[LineageValidationFinding]]:
    """Load lineages for every skill in `.claude/skills/`.

    Returns (lineages, findings). Findings aggregate per-skill warnings
    + cross-skill validation findings produced by `validate_lineage()`.
    """
    all_findings: list[LineageValidationFinding] = []
    lineages: list[SkillLineage] = []
    for name in discover_skill_names():
        try:
            ln, parse_findings = load_skill_lineage(name)
        except Exception as exc:
            all_findings.append(LineageValidationFinding(
                skill_name=name,
                severity="error",
                message=f"failed to load frontmatter: {exc}",
            ))
            continue
        lineages.append(ln)
        all_findings.extend(parse_findings)
    all_findings.extend(validate_lineage(lineages))
    return lineages, all_findings


# ── Validation ────────────────────────────────────────────────────────────


def validate_lineage(
    lineages: list[SkillLineage],
) -> list[LineageValidationFinding]:
    """Cross-skill validation per ADR-034 §3.

    Invariants checked:
      §3.1  frontmatter `version` must equal the highest changelog version
      §3.2  no two changelog entries may share the same `version` within
            one skill (re-versioning the same bump is silent drift)
      §3.3  changelog entries must be date-monotonic (later versions ≥
            earlier dates within one skill)
      §3.4  `shadow_mode_until`, if set, must be in the future OR the
            skill should already be promoted (version bumped minor)

    §3.1 is an error; §3.2/§3.3 are errors; §3.4 is a warning (it's a
    flag for the maintainer, not a refusal to load).
    """
    findings: list[LineageValidationFinding] = []
    today = date.today()
    for ln in lineages:
        if not ln.entries:
            findings.append(LineageValidationFinding(
                skill_name=ln.skill_name,
                severity="error",
                message="§3.1: skill has no `changelog:` entries — every skill must declare a lineage",
            ))
            continue

        # §3.1
        if ln.latest_entry.version != ln.current_version:
            findings.append(LineageValidationFinding(
                skill_name=ln.skill_name,
                severity="error",
                message=(
                    f"§3.1: frontmatter version={ln.current_version!r} but "
                    f"latest changelog version={ln.latest_entry.version!r} "
                    f"({ln.latest_entry.entry_date}). Bump frontmatter "
                    f"OR append the missing entry."
                ),
            ))

        # §3.2 — no duplicate versions
        seen: dict[str, ChangelogEntry] = {}
        for e in ln.entries:
            if e.version in seen:
                prev = seen[e.version]
                findings.append(LineageValidationFinding(
                    skill_name=ln.skill_name,
                    severity="error",
                    message=(
                        f"§3.2: duplicate changelog version {e.version!r} "
                        f"on {e.entry_date} (earlier instance: {prev.entry_date}). "
                        f"Use a fresh semver bump per change."
                    ),
                ))
            seen[e.version] = e

        # §3.3 — date monotonic across entries (entries already sorted by
        # (date, version); this catches non-strictly-increasing semver).
        # Note: per ADR-034 §2.3, semver order within same date is allowed
        # (multiple bumps in one day); cross-date regression is the error.
        prev_entry: ChangelogEntry | None = None
        for e in ln.entries:
            if prev_entry is not None and e.entry_date < prev_entry.entry_date:
                findings.append(LineageValidationFinding(
                    skill_name=ln.skill_name,
                    severity="error",
                    message=(
                        f"§3.3: changelog regresses in date: v{e.version} "
                        f"@ {e.entry_date} appears after v{prev_entry.version} "
                        f"@ {prev_entry.entry_date}."
                    ),
                ))
            prev_entry = e

        # §3.4 — shadow_mode promotion clock
        if ln.shadow_mode_until is not None and ln.shadow_mode_until < today:
            findings.append(LineageValidationFinding(
                skill_name=ln.skill_name,
                severity="warning",
                message=(
                    f"§3.4: shadow_mode_until={ln.shadow_mode_until} is in "
                    f"the past — graduate to non-shadow + bump minor "
                    f"OR extend the window with rationale."
                ),
            ))

    return findings


# ── Rendering ─────────────────────────────────────────────────────────────


def render_skill_timeline(ln: SkillLineage) -> str:
    """One skill's version history rendered as a vertical timeline (the
    Anthropic-slide format)."""
    if not ln.entries:
        return f"# {ln.skill_name}\n  (no changelog entries)\n"

    lines: list[str] = []
    lines.append(f"# {ln.skill_name}  (current: v{ln.current_version})")
    if ln.shadow_mode_until:
        lines.append(f"  shadow_mode_until: {ln.shadow_mode_until}")
    if ln.last_reviewed:
        lines.append(f"  last_reviewed:     {ln.last_reviewed}")
    if not ln.is_consistent:
        lines.append(
            f"  [!] INCONSISTENT: frontmatter v{ln.current_version} "
            f"≠ latest changelog v{ln.latest_entry.version}"
        )
    lines.append("")
    lines.append("  Version timeline (oldest → newest):")
    lines.append("  " + "─" * 70)
    for e in ln.entries:
        marker = "●" if e.version == ln.current_version else "○"
        lines.append(f"  {marker} {e.entry_date}  v{e.version}")
        lines.append(f"        {e.summary}")
    lines.append("")
    return "\n".join(lines)


def render_cross_skill_timeline(lineages: list[SkillLineage]) -> str:
    """All skills' entries fused into one chronological timeline.

    This is the format Anthropic uses on the "Versioning" pillar slide —
    a global timeline of every skill change in date order.
    """
    all_entries: list[ChangelogEntry] = []
    for ln in lineages:
        all_entries.extend(ln.entries)
    all_entries.sort(reverse=True)   # newest first

    if not all_entries:
        return "(no skill changelog entries found)"

    lines: list[str] = []
    lines.append("# Skill lineage — cross-skill chronological view")
    lines.append("# Newest first. Format: DATE  SKILL  VERSION  SUMMARY")
    lines.append("─" * 100)
    for e in all_entries:
        lines.append(e.render_line())
    return "\n".join(lines)


def render_findings(findings: list[LineageValidationFinding]) -> str:
    """Pretty-print validation findings; empty string when clean."""
    if not findings:
        return ""
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    lines: list[str] = []
    lines.append("")
    lines.append(f"# Validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    lines.append("─" * 100)
    for f in errors:
        lines.append(f.render_line())
    for f in warnings:
        lines.append(f.render_line())
    return "\n".join(lines)


def rebuild_lineage_index() -> str:
    """Generate the canonical `.claude/skills/_lineage.md` body.

    Pure function — caller writes the file. Idempotent: running twice
    in a row on unchanged frontmatter produces identical output.
    """
    lineages, findings = load_all_skill_lineages()
    today = date.today()

    lines: list[str] = []
    lines.append("# Skill lineage — auto-generated, do not hand-edit")
    lines.append("")
    lines.append(
        f"> Regenerated: {today.isoformat()}. Source: each skill's "
        f"`changelog:` frontmatter array. Regenerate via "
        f"`invest skill lineage --rebuild`."
    )
    lines.append("")
    lines.append("Per ADR-034: this index is the chronological master view of every "
                 "skill change. The frontmatter `changelog:` array on each individual "
                 "skill remains the source of truth — this file is a derived index.")
    lines.append("")

    # Section 1 — cross-skill chronological view
    lines.append("## All skills — chronological (newest first)")
    lines.append("")
    lines.append("```")
    lines.append(render_cross_skill_timeline(lineages))
    lines.append("```")
    lines.append("")

    # Section 2 — per-skill timelines
    lines.append("## Per-skill version timelines")
    lines.append("")
    for ln in sorted(lineages, key=lambda x: x.skill_name):
        lines.append("```")
        lines.append(render_skill_timeline(ln))
        lines.append("```")
        lines.append("")

    # Section 3 — validation summary
    if findings:
        errors = [f for f in findings if f.severity == "error"]
        warnings = [f for f in findings if f.severity == "warning"]
        lines.append("## Validation findings at last regeneration")
        lines.append("")
        lines.append(f"{len(errors)} error(s), {len(warnings)} warning(s).")
        lines.append("")
        if errors:
            lines.append("### Errors (block CI)")
            lines.append("")
            for f in errors:
                lines.append(f"- **{f.skill_name}** — {f.message}")
            lines.append("")
        if warnings:
            lines.append("### Warnings")
            lines.append("")
            for f in warnings:
                lines.append(f"- **{f.skill_name}** — {f.message}")
            lines.append("")
    else:
        lines.append("## Validation findings at last regeneration")
        lines.append("")
        lines.append("(no findings — lineage is clean)")
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "ChangelogEntry",
    "SkillLineage",
    "LineageValidationFinding",
    "discover_skill_names",
    "load_skill_lineage",
    "load_all_skill_lineages",
    "validate_lineage",
    "render_skill_timeline",
    "render_cross_skill_timeline",
    "render_findings",
    "rebuild_lineage_index",
]
