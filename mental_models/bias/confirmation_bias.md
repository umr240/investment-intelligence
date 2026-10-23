---
slug: confirmation_bias
name: Confirmation Bias
school: kahneman_munger
citation_tier: "★★"
always_load: true
related_models:
  - inversion
  - liking_loving_tendency
  - motivated_reasoning_fire
  - anchoring_bias
code_consequences:
  - ADR-023 §1.3 Block 2 mandates inversion BEFORE synthesis (not after) — structural defence against post-hoc rationalisation
  - F1-F7 each have a disqualification check, not just a passing condition — symmetric scoring
  - Multi-framework agreement required for high-conviction labelling — single-framework agreement is suspect when authoring the thesis
  - data_gaps[] echoed verbatim in narrative output — no smoothing toward a thesis
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Confirmation Bias

> When a thesis feels right, run the inversion *first*, not after.

## Summary

The tendency to seek and weight evidence supporting an existing belief while discounting contradictory evidence. Especially dangerous in research workflows where the analyst's belief forms early (often during initial reading) and subsequent data-gathering becomes selective.

## When to apply

- Every dive — run the inversion before synthesis
- Every "this looks great" reaction — what would have to be true for it to be wrong?
- Cross-checking multi-framework agreement — three frameworks aligning is conviction; one framework strong with the others ignored is bias
- When defending a previously-formed thesis against new data — has the data actually changed, or am I rationalising?

## Inversion form

The over-corrective stance: rejecting any thesis that "feels right" purely because it feels right. Confirmation bias has a counterpart in *reverse confirmation bias* (rejecting good ideas because they came too easily). Defence: the inversion test must be substantive, not a token "I considered the bear case."

## Antipatterns

- Conducting inversion *after* writing the thesis (post-hoc rationalisation)
- Treating "I considered the bear case" as sufficient without naming concrete failure modes
- Scoring frameworks asymmetrically (passing thresholds liberal, disqualifying thresholds strict — or vice versa)
- Reading 10-K narrative selectively for confirming evidence

## Examples in this codebase

- ADR-023 §1.3 Block 2 — inversion is the FIRST mandatory reasoning step
- F1 / F2 / F3 / F4 / F5 / F6 / F7 each have explicit disqualification checks
- Composite scoring requires multi-framework agreement (Lollapalooza) for high-conviction labels
- ADR-022 Stage 0c methodology panel surfaces what is NOT done — defence against quietly inserting confirming methodology choices
