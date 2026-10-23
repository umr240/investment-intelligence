---
slug: epistemic_humility_unknown_unknowns
name: Epistemic Humility (Unknown Unknowns)
school: rumsfeld_standard
citation_tier: "★★"
always_load: true
related_models:
  - circle_of_competence
  - margin_of_safety
  - probabilistic_thinking
  - confidence_calibration
code_consequences:
  - data_gaps[] is a first-class system output — explicit acknowledgement of "we don't know what we don't know"
  - Composite cap (10.0) + bounded overlay bonuses recognise that the model itself can't be fully right — top-end limited
  - InsufficientHistoryError raised rather than fabricated z-scores — honest about the unknowable
  - ADR-023 §1.3 Block 3 "Data Discipline" — every numerical claim must trace to scorecard; nothing inferred outside known
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Epistemic Humility (Unknown Unknowns)

> Three categories: known knowns, known unknowns, unknown unknowns. The third category is what kills theses, and the discipline is leaving room for it.

## Summary

The framework popularised by Donald Rumsfeld but standard in epistemology and military planning: knowledge stratifies into known facts, known gaps, and unknown gaps (things you don't know that you don't know). The third category is structurally invisible to the analyst until it materialises. Margin-of-safety and bounded-confidence are the structural responses.

## When to apply

- Every confident-feeling thesis — what could I be missing that I don't know I'm missing?
- Sectors outside circle of competence — unknown unknowns dominate; default to RESEARCH-ONLY or EXCLUDE
- New regulatory environments, new technologies — recently-emerged unknowns haven't been mapped yet
- "Black swan" risks — unknown unknowns made visible only after the fact

## Inversion form

The over-corrective stance: paralysis from "what if I'm missing something" without concrete failure modes to defend against. The discipline is *bounded* humility — acknowledge unknown unknowns with margin-of-safety rather than refusing all action.

## Antipatterns

- "I've done my research" treated as eliminating unknown unknowns
- Tight DCF confidence intervals that don't leave room for surprises
- Unbounded composite scores that imply complete knowledge
- Theses without margin of safety against the unknown

## Examples in this codebase

- data_gaps[] as first-class output — explicit "known unknowns" surface
- Composite caps + bounded overlay bonuses — leaves room for "unknown unknowns" to bring outcomes below the modeled best case
- Tier 1 Recession Stress Test — defends against the known-unknown of cyclical stress, leaves margin for the unknown-unknown of cycles unlike historical ones
- Methodology disclosure (ADR-022) — declares what we DO know, structurally implies what we don't
