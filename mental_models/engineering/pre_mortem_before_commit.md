---
slug: pre_mortem_before_commit
name: Pre-Mortem Before Commit
school: standard_klein
citation_tier: "★★"
always_load: true
related_models:
  - inversion
  - failure_mode_analysis
  - chestertons_fence
  - one_concern_per_change
code_consequences:
  - Before pushing/merging, ask explicitly "how does this break?" — mirrors the inversion lens at code-change scope
  - ADR-024 §1.6 schema enforcement runs as commit-time check (mandatory inversion_form, ≥2 related_models)
  - Test suite must pass before merge — pre-mortem encoded as a gate
  - One concern per change (related model) keeps the pre-mortem scope tractable
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Pre-Mortem Before Commit

> Before pushing: "how does this break?" Mirrors the inversion lens at code-change scope. Three minutes of pre-mortem catches the bugs that take three hours to debug after deploy.

## Summary

Pre-mortem is inversion applied to the about-to-ship change: what could go wrong with this commit, and is any of it observable now? Common failure classes (regressions in untouched code, performance cliffs, missing tests for the new path, broken contracts with downstream consumers, methodology drift) are catchable in a 3-minute pre-mortem that the actual debug session would take 30-180 minutes to identify.

## When to apply

- Every commit before pushing — what's the failure surface I'm introducing?
- Every refactor — what depended on what I just changed?
- Every threshold change — what historical positives will now exclude?
- Every dependency upgrade — what's the changelog entry that breaks us?

## Inversion form

What does skipping the pre-mortem cost? Bugs that surface in production / on the next dive — exactly the failure modes a pre-mortem would have caught in 3 minutes. The bug-fix-then-pre-mortem-anyway sequence is much more expensive than pre-mortem-and-prevent. Especially acute for AI agents whose code looks confident but may quietly violate project conventions.

## Antipatterns

- "Tests pass, ship it" without considering what the tests don't cover
- Refactors where the pre-mortem stops at "the code compiles"
- Single-line fixes where the broader regression-surface isn't checked
- "It works on my machine" as a substitute for failure-mode reasoning

## Examples in this codebase

- ADR-024 §1.6 schema enforcement is structural pre-mortem at the lattice layer
- Test suite + ruff + mypy strict — automated pre-mortem checks before commit
- ADR documents include "anti-patterns this ADR forbids" sections — explicit pre-mortem of common misapplications
- The HIMS total_debt fix: pre-mortem identified that adding aliases would alter D/E across the universe; verified no regression on previously-stable companies before merging
