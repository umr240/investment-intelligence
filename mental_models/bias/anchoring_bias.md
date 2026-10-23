---
slug: anchoring_bias
name: Anchoring Bias
school: kahneman
citation_tier: "★★"
always_load: true
related_models:
  - first_principles
  - confirmation_bias
  - sunk_cost
  - probabilistic_thinking
code_consequences:
  - DCF intrinsic-value calculation rebuilt from primitives each refresh — doesn't anchor on prior calculation
  - Composite scores recomputed each dive with current data — past verdicts don't anchor present scoring
  - ADR-022 source-provenance discipline prevents anchoring on a single platform's number
  - Analyst price targets treated as one input, not as anchor — F4 explicitly rewards low analyst coverage (no anchor)
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Anchoring Bias

> A private buyer's prior bid is a useful reference point, not a price floor. The business has changed since.

## Summary

The tendency to weight a salient initial value — first observed price, prior valuation, analyst target — disproportionately in subsequent estimates. The anchor is rarely accurate enough to deserve its cognitive weight, and the business / market has usually changed since the anchor was set.

## When to apply

- Every valuation reference to "what someone paid for it" — useful only if business and market are unchanged
- Analyst price targets — directional input, not anchoring valuation
- Prior dive verdict for the same ticker — re-evaluate from current data, don't anchor on prior label
- Sector-wide P/E "norms" — these change across cycles; current norm isn't necessarily right

## Inversion form

The over-corrective stance: rejecting all reference points because anchoring is a risk. Reference points are useful as sanity checks. The discipline is calibration: weight the reference by its informational content (recent + similar context = high weight; old + different context = low weight).

## Antipatterns

- Defining "fair value" relative to prior trading range (a.k.a. technical analysis as valuation)
- Trusting an analyst target because it's a number on the page
- Refusing to update a thesis because the original price entry "should hold"
- Anchoring on an acquirer's offer price as floor when the business / sector has shifted

## Examples in this codebase

- DCF rebuilt each refresh from current `Financial` row primitives — no carry-forward of prior intrinsic-value estimate
- Tier 2 screener `min_margin_of_safety=0.20` is *first-principles*, not anchored on historical norms
- ADR-021 §0 rejected anchoring on "Bloomberg / FactSet management non-GAAP" — chose Peters-Taylor first-principles instead
- F7 z-scores compute against the company's *own* multi-year history, not external sector anchors
