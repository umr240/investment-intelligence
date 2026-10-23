"""Typo-catch for `mental_models:` slugs declared in skill frontmatter.

This is a documentary cross-reference check (not a hard CI gate at
error severity). Rationale established 2026-05-16: the lattice's
runtime touch-point is `deepdive/mental_model_composer.py` selecting
models per ScorecardView at narrative time, NOT skills declaring static
mental_model lists. The frontmatter field is documentary.

So this test ASSERTS no typos exist (which would mean a real bug to fix)
WITHOUT making mental_models declarations mandatory. A skill that
declares zero mental_models passes silently.

If a phantom slug appears (typo, removed lattice file, renamed model)
this test fails with a clear pointer to the offending skill + slug.
"""
from __future__ import annotations

from cli.skills.mental_model_refs import (
    discover_lattice_slugs,
    load_all_skill_mental_models,
)


def test_lattice_has_models_to_reference() -> None:
    """Sanity — discovery returns non-empty catalog. If this fires, the
    lattice path resolution is broken (not a skill-level issue)."""
    catalog = discover_lattice_slugs()
    assert len(catalog) > 0, (
        "mental_models/ catalog appears empty — discovery path is wrong "
        "or the lattice was deleted"
    )


def test_no_phantom_mental_model_slugs() -> None:
    """Every slug in any skill's `mental_models:` array must resolve to
    a real `mental_models/<domain>/<slug>.md` file."""
    refs_by_skill, findings = load_all_skill_mental_models()
    assert refs_by_skill, "no skills loaded — discovery is broken"

    if findings:
        lines = [f.render_line() for f in findings]
        msg = (
            "Phantom mental_models slug(s) in skill frontmatter. Fix the "
            "typo, author the missing lattice entry, OR remove the "
            "reference:\n  " + "\n  ".join(lines)
        )
        raise AssertionError(msg)


def test_resolved_refs_have_domain_attribution() -> None:
    """Every resolved ref should know its lattice domain (core/moat/etc).
    If a ref says resolved but has no domain, the file-path-to-domain
    mapping is broken in the validator."""
    refs_by_skill, _ = load_all_skill_mental_models()
    for skill_name, refs in refs_by_skill.items():
        for r in refs:
            if r.resolved:
                assert r.domain, (
                    f"{skill_name} → {r.slug}: resolved but no domain attribution"
                )
