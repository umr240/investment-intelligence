---
slug: rule_of_three
name: Rule of Three
school: standard_xp
citation_tier: "★★"
always_load: true
related_models:
  - yagni
  - dry_caveat
  - chestertons_fence
  - boring_technology
code_consequences:
  - Don't pre-build abstractions for hypothetical second use cases — wait for the third concrete instance
  - Mental-model schema (ADR-024 §1.6) requires ≥2 `related_models` cross-references — three concrete examples in the lattice teach the pattern, two don't
  - Test coverage prioritises the three-failure-mode patterns that produce most observed failures (failure_pareto)
  - Refactoring discipline: don't extract a helper until you've copy-pasted the same logic three times
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Rule of Three

> Duplicate twice. Refactor on the third occurrence. Counters DRY-cult premature abstraction; three concrete examples teach the right shape, two don't.

## Summary

When you see code that looks similar in two places, the temptation is to abstract it immediately (DRY). Often this produces wrong abstractions — the two cases that *currently* look similar are encoding different concepts that will diverge. Wait for a third instance: now you have evidence about what's genuinely shared vs incidentally similar, and the abstraction you build will fit all three.

## When to apply

- Every "let me extract this into a helper" reflex — is there a third instance, or am I premature?
- Every refactor that proposes a base class — wait until three subclasses exist to see what's truly shared
- Every "we need a generic X for this" — defer until X is concretely needed in three places
- Every test pattern — three test cases reveal the parametrisation; two are guesswork

## Inversion form

What does premature abstraction cost? Locked-in wrong abstractions that block the third use case from fitting. Two functions that "look similar" often encode different concepts (e.g., `validate_user_email` and `validate_company_email` look the same but the validation rules diverge). Merging them produces a confused abstraction that handles neither well.

## Antipatterns

- Extracting helpers after seeing one duplicate
- "Generic" base classes built before three concrete subclasses exist
- Abstractions that handle two cases by introducing if-branches inside (sign that the abstraction is wrong)
- DRY cult: "duplication is bad" without considering what's actually being duplicated

## Examples in this codebase

- Framework score functions: F1-F7 each have similar shape but distinct logic; resisted the urge to extract a `BaseFramework` until three+ produced shared infrastructure
- Overlay functions: `run_ica`, `run_psa`, `run_bew` — similar return shape; common interface emerged from concrete implementations, not pre-designed
- Mental-model file template: emerged from extracting the first ~10 models, not pre-designed
- Counter-example to watch for: `_INCOME_CONCEPTS` / `_BALANCE_CONCEPTS` / `_CASHFLOW_CONCEPTS` — three structurally identical concept-alias lists; if a fourth emerges (e.g., `_IFRS_CONCEPTS` per ADR-025), the abstraction may be earned
