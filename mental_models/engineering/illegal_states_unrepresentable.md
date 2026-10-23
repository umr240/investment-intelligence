---
slug: illegal_states_unrepresentable
name: Make Illegal States Unrepresentable
school: minsky_ocaml
citation_tier: "★★★"
always_load: true
related_models:
  - parse_dont_validate
  - fail_fast
  - boundaries_hexagonal
  - first_principles
  - idempotency
code_consequences:
  - Pydantic v2 + mypy strict — already enforced; types prevent invalid Financial rows from being constructed
  - Period field constrained to literal `{annual, Q1, Q2, Q3, Q4}` — no free-form strings
  - DataRequirement is a frozen dataclass — can't be mutated mid-pipeline into an inconsistent state
  - FrameworkResult.verdict constrained to literal `{strong_fit, partial, fail}` — no free-form labels
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Make Illegal States Unrepresentable

> Yaron Minsky / OCaml community: use the type system to prevent invalid states from being constructed. The compiler is the cheapest unit test.

## Summary

When a state combination is logically invalid (e.g., a `Financial` row with `revenue` populated but `period_end_date` None; a `verdict` of "buy" instead of one of three constrained labels), encode the invariant in the type system rather than checking it at runtime. Runtime checks are forgettable; type constraints are enforced everywhere by construction.

## When to apply

- Every dataclass / Pydantic model — what's the smallest set of valid states, and does the type signature reflect it?
- Every enum-like field — use `Literal["a","b","c"]` not `str`
- Every "this can be one of three things" — use a tagged union, not a flag dict
- Every "this requires that" pairing — encode as a discriminated type rather than runtime assertion

## Inversion form

What does runtime validation cost? Errors caught hours later, often by the user, often as silently-wrong verdicts rather than crashes. A `verdict: str = "by"` typo passes through every layer until a downstream consumer pattern-matches it and silently does the wrong thing. A `verdict: Literal["strong_fit","partial","fail"]` typo is a type error caught at write time.

## Antipatterns

- Free-form strings where a literal union would do
- "It's just a dict" for structured data
- Runtime `assert` statements that disappear under `-O`
- "I'll validate it at the API boundary" then internal code passing dicts around for thousands of lines

## Examples in this codebase

- `frameworks/base.py:FrameworkResult` — Pydantic / dataclass with constrained verdict
- `data/models/schema.py` — SQLAlchemy types prevent invalid column combinations at insert time
- `frameworks/base.py:DataRequirement` — frozen dataclass; mutation produces a new instance
- The `period` column constraint `{annual, Q1, Q2, Q3, Q4}` — illegal periods can't be inserted
