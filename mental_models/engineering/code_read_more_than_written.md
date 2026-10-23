---
slug: code_read_more_than_written
name: Code is Read More than Written
school: standard
citation_tier: "★★"
always_load: true
related_models:
  - two_hard_things
  - mirror_existing_patterns
  - chestertons_fence
  - parse_dont_validate
code_consequences:
  - Naming discipline (`two_hard_things`) — names optimise for reader, not writer
  - ADRs document WHY, not just WHAT — readers don't have to reverse-engineer rationale
  - Frameworks declare DATA_REQUIREMENT explicitly — readers see at a glance what data the framework needs
  - Mental-model files include "Examples in this codebase" — readers can navigate from concept to code
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Code is Read More than Written

> Optimise for readability, not cleverness. Especially relevant when an AI agent is the writer — clever code an agent generates is hard to audit.

## Summary

Code is written once, read many times — by future-you, by collaborators, by AI agents reading to make changes. Time spent on readability has a multiplier; time spent on cleverness compounds in negative reading time. The discipline is preferring boring, explicit, well-named code over compact-but-cryptic alternatives.

## When to apply

- Every clever one-liner — would a 3-line explicit version be clearer?
- Every implicit conversion / type coercion — explicit beats implicit
- Every comprehension nested 3+ levels — refactor to named intermediate steps
- Every meaningful variable named `x` / `tmp` / `_` — give it a name that explains what it is

## Inversion form

What does write-optimised cleverness cost? Future readers (including the AI agent making the next change) misunderstanding the code, breaking it, or working around it because it's too risky to modify. The "show off" one-liner saves 30 seconds for the writer and costs 30 minutes per future reader. Compounded across a codebase, this is an enormous tax.

## Antipatterns

- One-liner comprehensions doing 3 things (filter + transform + side effect)
- Single-letter variable names outside trivial loop counters
- "Clever" use of language features that requires reading the docs to understand
- Compact code prioritised over explicit code

## Examples in this codebase

- `frameworks/f1_pre_discovery.py` — explicit step-by-step composition rather than one big expression; readers can audit each Piotroski signal in isolation
- ADRs document "what was rejected and why" — saves future readers from re-litigating decisions
- Mental-model files have explicit `inversion_form` + `antipatterns` sections — readers can navigate from concept to defence against misuse
- Counter-example to watch for: dense Pydantic field declarations are fine because the framework standardises the pattern; clever runtime metaprogramming is not
