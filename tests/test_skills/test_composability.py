"""ADR-036 §3 — composability validation CI gate.

Tests that every skill's `composes:` block (when declared) satisfies:

  §3.1  every `composes.skills[].name` resolves to a known skill
  §3.2  no self-loops (skill composes itself)
  §3.3  no composition cycles within the skill-to-skill subgraph

These are the same invariants enforced by
`cli.skills.composability:validate_composition()`. This test file is the
CI-level harness — the parser is exercised by the runtime; this test
fails the build on any error finding.

A skill with no `composes:` block is NOT a violation — composability is
OPTIONAL today per ADR-036 §2 ("only declare what's real").
"""
from __future__ import annotations

from cli.skills.composability import (
    CompositionFinding,
    load_all_compositions,
)


def _errors_only(findings: list[CompositionFinding]) -> list[CompositionFinding]:
    return [f for f in findings if f.severity == "error"]


def test_all_skill_compositions_resolve() -> None:
    """§3.1 — every referenced skill must exist; §3.2 no self-loops;
    §3.3 no cycles."""
    compositions, findings = load_all_compositions()
    assert compositions, "no compositions loaded — discovery is broken"

    errors = _errors_only(findings)
    if errors:
        lines = [f.render_line() for f in errors]
        msg = (
            "Composition validation errors (ADR-036 §3). Fix the skill "
            "files OR amend ADR-036 if the rule needs to change:\n"
            + "\n".join(lines)
        )
        raise AssertionError(msg)


def test_composition_constraints_are_well_formed() -> None:
    """Every constraint string declared in any composes: block must
    parse as a PEP-440-style range. Errors here surface as severity
    'error' findings from the parser."""
    _, findings = load_all_compositions()
    bad = [f for f in findings if "constraint" in f.message and f.severity == "error"]
    assert not bad, (
        "Malformed version constraints in composes:\n  "
        + "\n  ".join(f.render_line() for f in bad)
    )


def test_dive_complete_uses_audit_completeness() -> None:
    """Sanity: the real-world composition we backfilled holds.

    `dive-complete` uses `audit-completeness` as workflow step 1. If
    this edge ever disappears, the backfill regressed."""
    compositions, _ = load_all_compositions()
    dive = next((c for c in compositions if c.skill_name == "dive-complete"), None)
    assert dive is not None, "dive-complete missing from inventory"
    used = [s.name for s in dive.skills if s.relation == "uses"]
    assert "audit-completeness" in used, (
        f"dive-complete should `use` audit-completeness; declared uses: {used}"
    )
