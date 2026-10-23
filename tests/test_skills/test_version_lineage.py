"""ADR-034 §3 — version<->changelog consistency CI gate.

Every `.claude/skills/*.md` MUST satisfy:
  §3.1  frontmatter `version` matches the most-recent changelog entry's version
  §3.2  no two changelog entries within one skill share a `version`
  §3.3  changelog entries are date-monotonic within one skill
        (later versions appear on dates ≥ earlier entries' dates)

This test fails CI if any error-severity finding is produced by
`cli.skills.lineage.validate_lineage()`. Warning-severity findings
(e.g., expired `shadow_mode_until`) do NOT fail the build — they
surface in the `_lineage.md` index for the maintainer to act on.
"""
from __future__ import annotations

from cli.skills.lineage import (
    LineageValidationFinding,
    load_all_skill_lineages,
)


def _errors_only(findings: list[LineageValidationFinding]) -> list[LineageValidationFinding]:
    return [f for f in findings if f.severity == "error"]


def test_all_skills_have_lineage() -> None:
    """§3.1 §3.2 §3.3 — every skill must pass the validator with zero errors."""
    lineages, findings = load_all_skill_lineages()
    assert lineages, ".claude/skills/ contains no skills — discovery is broken"

    errors = _errors_only(findings)
    if errors:
        lines = [f.render_line() for f in errors]
        msg = (
            "Lineage validation found errors (ADR-034 §3). Fix the listed "
            "skill files OR amend ADR-034 if the rule needs to change:\n"
            + "\n".join(lines)
        )
        raise AssertionError(msg)


def test_each_skill_has_at_least_one_entry() -> None:
    """A skill with an empty changelog is a lineage violation per §3.1.

    This is also reported by validate_lineage(), but called out
    separately here for diagnostic clarity in CI failure output.
    """
    lineages, _ = load_all_skill_lineages()
    empty = [ln.skill_name for ln in lineages if not ln.entries]
    assert not empty, (
        f"Skills with empty changelog: {empty}. Every skill must have "
        f"≥1 entry per ADR-034 §3.1."
    )


def test_frontmatter_version_matches_changelog_head() -> None:
    """§3.1 — direct assertion (validator covers it too; explicit here)."""
    lineages, _ = load_all_skill_lineages()
    mismatches: list[str] = []
    for ln in lineages:
        if not ln.entries:
            continue
        if ln.latest_entry.version != ln.current_version:
            mismatches.append(
                f"{ln.skill_name}: frontmatter={ln.current_version!r} "
                f"vs changelog head={ln.latest_entry.version!r}"
            )
    assert not mismatches, "Version mismatches:\n  " + "\n  ".join(mismatches)


def test_lineage_index_is_regeneratable() -> None:
    """Sanity check — rebuild_lineage_index() runs without errors and
    produces non-trivial output. Doesn't write to disk."""
    from cli.skills.lineage import rebuild_lineage_index
    body = rebuild_lineage_index()
    assert "Skill lineage" in body
    assert "chronological" in body.lower()
    assert len(body) > 500, "lineage index suspiciously short"
