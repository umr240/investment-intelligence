---
slug: functional_core_imperative_shell
name: Functional Core, Imperative Shell
school: gary_bernhardt
citation_tier: "★★★"
always_load: true
related_models:
  - boundaries_hexagonal
  - parse_dont_validate
  - illegal_states_unrepresentable
  - test_behaviour_not_implementation
code_consequences:
  - Frameworks F1-F7 are pure functions of (ticker, CompanyDataReader) — no I/O inside the score computation
  - Overlay run_ica / run_psa / run_bew are pure given a reader — testable without DB or network
  - CLI in cli/main.py is the imperative shell — accepts user input, performs I/O, calls into the pure core
  - data/pipeline.py is also imperative shell — fetches, persists; logic lives in the parsers it calls
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Functional Core, Imperative Shell

> Gary Bernhardt: pure-function business logic at the centre, thin imperative wrapper at the edges that handles the messy real world (I/O, time, randomness).

## Summary

Refinement of hexagonal architecture: not just *separated* but *characterised differently*. The core is pure functions; the shell is imperative I/O. Tests of the core need no fixtures, no mocks, no DB. Tests of the shell are integration tests with appropriate setup. The asymmetry is the architecture's strength.

## When to apply

- Every framework — it should be a pure function of (data, parameters)
- Every overlay — same
- Every derivation / calculation — pure, given inputs
- Every "side effect" — pushed to the boundary, kept thin

## Inversion form

What does scattering side effects cost? Tests that need fixtures + DB + network for trivial logic. A pure function `compute_pt_adjusted_full(annuals)` is testable with a hardcoded list of `Financial`-like objects in 50ms. The same logic with embedded SQL takes minutes per test, requires a populated DB, and the test is fragile to schema changes.

## Antipatterns

- Business logic that fetches its own data
- Pure functions that quietly call `datetime.now()` (impure — unstable across test runs)
- "I need to test this so I'll mock SQLAlchemy" — sign that the logic shouldn't have SQL in it
- Random numbers / non-deterministic ordering inside the core

## Examples in this codebase

- `frameworks/f1_pre_discovery.py:score_f1` — pure function of `(ticker, reader)`; no I/O
- `screener/tasks/fundamentals.py:compute_pt_adjusted_full` — pure given annuals list
- `overlays/ica.py:run_ica` — pure given reader; result is a typed dict
- `cli/main.py:dive` command — imperative shell: parses args, calls async orchestrator, renders output
- Counter-example to watch for: any framework that does `datetime.now()` directly — should receive `now` as a parameter for testability
