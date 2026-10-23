---
slug: inversion
name: Inversion
school: munger
citation_tier: "◯"
always_load: true
related_models:
  - margin_of_safety
  - second_order_thinking
  - circle_of_competence
  - confirmation_bias
code_consequences:
  - Every framework has a corresponding disqualification check (e.g. F1 CGS top-decile asset-growth disqualifier)
  - Tests exercise failure modes before happy paths
  - Each new feature must survive its own inversion before shipping
  - ICA-5 fires on the gap regardless of GAAP level (inversion of "ICA only matters when GAAP looks bad")
  - Mental models without inversion_form section are rejected (ADR-024 §1.6)
token_cost_estimate: 280
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Inversion

> *"Invert, always invert."* — Carl Jacobi (via Munger)

## Summary

Munger's primary tool. For any forward question, also ask its inverse. Solving the negation is often easier and more reliable than solving the positive — and often more honest about what you actually know.

## When to apply

- Whenever a new framework, signal, overlay, or thesis is introduced — pair it with the inversion before shipping
- Before high-conviction labelling of any company (run the inversion *first*, not after)
- When a thesis "feels right" — confirmation bias defends against you, inversion defends for you
- Designing tests — inversion is what generates failure-mode test coverage

## Inversion form

The inversion of inversion: when does it fail? When the negation isn't well-defined (e.g. "what makes this NOT a great business" devolves into infinite enumeration), inversion produces motion without progress. Defence: the inversion must be *concrete and observable*, not abstract enumeration.

## Antipatterns

- Running inversion *after* synthesis instead of before (defeats the point)
- Treating inversion as a checkbox rather than a real investigation
- Inverting only positive claims (also invert negative claims — "what would make this exclude *wrong*?")
- Calling "what could go wrong" inversion when it's actually risk enumeration without structural analysis

## Examples in this codebase

- `frameworks/f1_pre_discovery.py` — Piotroski 9 signals are themselves inversions of red flags
- `frameworks/f5_growth_quality.py:_compute_roic` — band-by-band scoring inverts "what does bad capital efficiency look like?"
- Universal disqualification rules across F1-F7 (CGS top-decile, M-Score > -2.22)
- `tests/test_frameworks/` — failure-mode tests should outnumber happy-path tests
- `overlays/detector.py:ICA-5` — fires on ROIC gap in *both* directions (upward AND downward), inverting the assumption that ICA only matters when GAAP under-reports
