---
slug: motivated_reasoning_fire
name: Motivated Reasoning (FIRE-Goal Specific)
school: munger
citation_tier: "◯"
always_load: true
related_models:
  - confirmation_bias
  - liking_loving_tendency
  - margin_of_safety
  - probabilistic_thinking
code_consequences:
  - Composite score is capped at 10.0; overlay bonuses bounded — no single signal can produce the verdict the analyst wants
  - Multi-framework agreement requirement means motivated reasoning has to corrupt multiple independent checks to drive a verdict
  - Verdict labels constrained to WATCHLIST / EXCLUDE / RESEARCH-ONLY — no ability to label "BUY" out of urgency
  - data_gaps[] echoed verbatim — motivated smoothing is structurally impossible at the output layer
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Motivated Reasoning (FIRE-Goal Specific)

> The FIRE goal creates motivated reasoning. Inversion + multi-framework agreement + cap on single-signal influence are explicit defences.

## Summary

A bias category specific to this project's owner-operator context: the long-term financial-independence goal creates structural pressure to find investable names. Pressure to find creates pressure to lower the bar. Lowered bars produce false positives, which (if acted on) compound losses against the very goal motivating the search. The bias is endogenous to the project's purpose and requires explicit defences.

## When to apply

- Every dive where the bear case is being suppressed
- Every "I need this to work" framing
- Every "we haven't found a buy in months, we're due"
- Every framework score that just barely passes a threshold

## Inversion form

What does over-corrective discipline look like? Refusing to deploy capital indefinitely. The goal isn't to never invest; it's to invest only when the framework lattice converges. The defence is structural (multi-framework agreement, capped composite, constrained vocabulary), not psychological self-discipline.

## Antipatterns

- "I haven't found a name in 6 months, time to stretch" → lowering the bar
- Quietly relaxing thresholds after a dive's first read
- Excluding the inversion check on a name that "feels right" because the search has been long
- Rationalising overlay bonuses to push a borderline composite over the threshold

## Examples in this codebase

- TOTAL_OVERLAY_BONUS_CAP=1.0 — overlay bonuses can't push a 5.5 framework composite to high-conviction by themselves
- Multi-framework agreement requirement (≥3 frameworks aligning) for high-conviction labelling
- Composite renormalisation on framework feasibility — a recent IPO with F7 unfeasible doesn't get a free pass; weights redistribute symmetrically
- Verdict vocabulary structurally cannot say BUY — the urgency the FIRE goal creates can't be expressed in the output, so it can't anchor the analysis
