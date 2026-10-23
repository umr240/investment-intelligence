---
slug: unintended_consequences
name: Law of Unintended Consequences
school: merton
citation_tier: "★★"
always_load: true
related_models:
  - inversion
  - feedback_loops
  - second_order_thinking
  - failure_mode_analysis
code_consequences:
  - Every framework / overlay change requires inversion analysis (what new false positives or false negatives does this introduce?)
  - ICA-5 trigger added with explicit acknowledgement of its co-existence with ICA-1..4 — multiple triggers firing must self-disqualify cleanly
  - Bias models are guardrails against unintended consequences of motivated reasoning + thesis attachment
  - data_gaps[] surfaces unknowns rather than papering over them — silent consequences are the dangerous kind
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Law of Unintended Consequences

> Every intervention has consequences the designer didn't intend. Map them before shipping.

## Summary

Robert Merton's principle, restated for system design: any change to a complex system produces effects beyond the intended one. In analytical systems, a new framework signal produces false positives the designer didn't anticipate; a new disqualification check excludes companies the designer wanted to include; a new methodology choice cascades through every downstream consumer.

## When to apply

- Every new framework / overlay / signal — what unintended firings does this produce?
- Every disqualification check — what false-negative inclusions does this create?
- Every methodology change — what downstream metrics now mean something different?
- Every test addition — what does this test fail to catch even as it catches its target?

## Inversion form

The over-corrective stance: refusing to make changes because all changes have unintended consequences. The discipline is *bounded* unintended consequences — graduated rollout, observability, reversibility. Defence: changes are auditable and reversible at the architectural layer.

## Antipatterns

- Adding a signal without enumerating which other signals it correlates with (introduces redundant rather than independent evidence)
- Tightening a threshold without tracking which historical positives now exclude
- Adding a bias defence without noticing it creates a new bias (e.g. over-correcting confirmation can produce reverse-confirmation bias)
- Methodology changes shipped without ADR — invisible to downstream consumers

## Examples in this codebase

- ADR-024 §3 anti-pattern list — explicit enumeration of unintended consequences the schema discipline prevents
- ICA-5 added with documentation that it co-exists with ICA-1..4 — anticipated unintended consequence (over-firing) handled by self-disqualification when adjustment is small
- Every ADR documents what it does NOT do (§"What this ADR does NOT do") — explicitly bounds the change's scope
- Bias guardrails layered such that addressing one bias doesn't create another
