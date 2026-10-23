---
slug: one_concern_per_change
name: One Concern Per Change
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - boy_scout_rule_caveat
  - pre_mortem_before_commit
  - mirror_existing_patterns
  - failing_test_before_fix
code_consequences:
  - Each commit / edit addresses one well-defined concern; no "while I was in there" creep
  - Bug fixes are separate commits from refactors are separate commits from feature additions
  - Mental-model PRs add models without simultaneously changing framework code
  - Methodology changes (touching ADRs) are isolated from implementation changes
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# One Concern Per Change

> Each edit/commit addresses one thing. No "while I was in there" creep. Mixed-concern diffs are unreviewable, hard to roll back, and conflate bug fixes with refactors.

## Summary

Discipline of keeping each change focused on a single concern, with bundling deferred to deliberate batch operations. AI agents (and humans) often expand scope mid-task — fixing the bug at hand AND cleaning up adjacent code AND renaming a confusingly-named variable. The result: a 200-line diff where 5 lines fix the bug and 195 lines are cleanup. The bug-fix part can't be safely rolled back without rolling back unrelated cleanup.

## When to apply

- Every commit — does the diff have exactly one description, or do I need to say "and also"?
- Every PR — what's the single sentence that describes the scope?
- Every "while I was in there" instinct — file as a separate task; don't bundle
- Every refactor proposed mid-task — note it down, ship the original task first

## Inversion form

What does mixed-concern commits cost? Unreviewable diffs (reviewer can't tell what's load-bearing for the bug fix vs cosmetic), hard rollbacks (can't undo just the bug fix without also reverting cleanup), and conflated history (`git blame` on a line answers "what was this for?" with five different concerns). Especially acute for AI sessions where the agent's "improve everything" instinct expands scope.

## Antipatterns

- "While I was in there I also refactored X" mixed into a bug-fix commit
- Renames bundled with semantic changes (rename to be its own commit)
- Style fixes mixed with logic changes (auto-formatter handles style; logic gets focused commits)
- Multi-concern PRs that the reviewer can't decompose mentally

## Examples in this codebase

- The HIMS bug-fix session shipped 5 fixes as 5 separately-tracked tasks (total_debt, FY2024 row, shares_outstanding, CapEx, Stage 0c) — even though some were causally related, they were tracked and verified individually
- ADR-024 (mental models library) shipped before ADR-025 (IFRS support) — separate concerns, separate ADRs, separate commits
- Each mental-model file is its own commit-able artifact, not bundled with code changes
- Counter-example to watch for: an agent that adds new mental models AND simultaneously refactors framework code in the same session — should be separated into two passes
