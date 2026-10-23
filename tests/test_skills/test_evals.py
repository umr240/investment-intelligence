"""ADR-035 §4 — CI gate for the deterministic eval dimensions.

Per ADR-035, two dimensions are deterministic + mandatory in CI:

  - FRONTMATTER_STRUCTURE  (ADR-032 §2.1 + ADR-034 §3 lineage)
  - SCRIPT_EXECUTION       (impl imports + CLI surfaces resolve)

Two dimensions are deferred / permissive today:

  - OUTPUT_QUALITY         (output_schema optional today — SKIP allowed)
  - TRIGGERING_ACCURACY    (LLM eval not built — SKIP allowed)

This test fails CI iff any skill produces a FAIL on a mandatory dimension.
SKIP is acceptable; PASS is the target.
"""
from __future__ import annotations

from cli.skills.evals import (
    EvalDimension, EvalStatus,
    run_all_skill_evals,
)

_MANDATORY_DIMENSIONS = {
    EvalDimension.FRONTMATTER_STRUCTURE,
    EvalDimension.SCRIPT_EXECUTION,
    EvalDimension.COMPOSABILITY_CONSISTENCY,    # ADR-036 §3 — composition validity
}


def test_all_skills_pass_mandatory_evals() -> None:
    """Every skill must PASS the two deterministic dimensions."""
    reports = run_all_skill_evals()
    assert reports, "no skills evaluated — discovery is broken"

    failures: list[str] = []
    for rep in reports:
        for r in rep.results:
            if r.dimension in _MANDATORY_DIMENSIONS and r.status == EvalStatus.FAIL:
                failures.append(
                    f"{rep.skill_name} v{rep.current_version}: "
                    f"{r.dimension.value} FAIL — {r.detail}"
                )

    if failures:
        msg = (
            "Mandatory skill-eval dimensions failed (ADR-035 §4):\n  "
            + "\n  ".join(failures)
        )
        raise AssertionError(msg)


def test_no_skill_eval_errors() -> None:
    """ERROR status (infrastructure issue, not skill issue) should never
    occur in a healthy environment. If it does, the eval harness itself
    is broken — louder failure than a SKIP."""
    reports = run_all_skill_evals()
    errors: list[str] = []
    for rep in reports:
        for r in rep.results:
            if r.status == EvalStatus.ERROR:
                errors.append(
                    f"{rep.skill_name}: {r.dimension.value} ERROR — {r.detail}"
                )
    assert not errors, "Eval-harness ERROR (not skill error):\n  " + "\n  ".join(errors)
