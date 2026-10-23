---
slug: dry_caveat
name: DRY (Don't Repeat Yourself) — With Caveats
school: pragmatic_programmer
citation_tier: "◯"
always_load: false
related_models:
  - rule_of_three
  - yagni
  - chestertons_fence
  - composition_over_inheritance
code_consequences:
  - Schema column names are deliberately repeated where the concept is the same (`fiscal_year` everywhere) — DRY at the *concept* level, not the syntax level
  - F1-F7 frameworks share NO inheritance hierarchy — apparent duplication left in until a third structurally-identical case earns the abstraction (Rule of Three)
  - mental_models/ accept some prose repetition across files where each file should stand alone — readers shouldn't have to navigate to understand a model
  - ADR documents repeat principles across ADRs deliberately so each ADR is self-contained
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# DRY (Don't Repeat Yourself) — With Caveats

> *"Every piece of knowledge must have a single, unambiguous, authoritative representation within a system."* — Pragmatic Programmer. **Often misapplied.** Two functions that currently look similar but encode different concepts should NOT be merged.

## Summary

DRY is widely cited and widely misapplied. The original principle is about *knowledge* (one authoritative representation of each fact), not about *syntax* (no two lines look similar). Applied to syntax, DRY produces wrong abstractions: two functions that incidentally look the same but encode different concepts get merged, the abstraction can't extend to the third concept that arrives, and refactoring becomes an archaeology project. **The honest restatement: prefer Rule of Three** — duplicate twice without abstracting, refactor on the third concrete instance.

## When to apply

- Single source of truth for *facts* (a value lives in one place; everything else is a derivation)
- Configuration constants used across the codebase
- Genuinely shared logic where all instances will evolve together

## When NOT to apply (where DRY misleads)

- Two functions that happen to look syntactically similar but encode different domain concepts
- Pre-extracting helpers based on superficial similarity without three concrete instances
- Merging tests because "they look similar" — tests document different scenarios; merging them obscures what's tested

## Inversion form

What does WET (Write Everything Twice) cost when over-applied? Real duplication of knowledge — schema definitions in multiple places that drift, configuration constants copy-pasted that diverge, business rules implemented twice. So DRY is real; the problem is misapplication. The discipline is *Rule of Three* + applying DRY at the *knowledge* layer (facts, not syntax).

## Antipatterns

- Premature abstraction after seeing two similar-looking pieces of code
- "Generic" base classes built before three concrete instances exist
- Wrong abstractions where concepts diverge but syntax was merged
- DRY-cult: treating any apparent duplication as a bug to fix immediately

## Examples in this codebase

- `_INCOME_CONCEPTS` / `_BALANCE_CONCEPTS` / `_CASHFLOW_CONCEPTS` — three structurally identical lists; haven't been DRY'd into a single generic structure because each evolves independently and the abstraction layer would obscure the readability of each
- Mental-model files repeat schema-level prose ("inversion form", "antipatterns" headings) — DRY at concept level (the schema is documented once in README.md), repeated at file level for self-containment
- Schema column names use full English (`operating_cash_flow` not `op_cf`) — repeats the analytical concept everywhere, deliberately, because `op_cf` would obscure intent
- Counter-example: shared utility functions in `data/api/_retry.py` are correctly DRY (the retry policy IS knowledge that should live in one place)
