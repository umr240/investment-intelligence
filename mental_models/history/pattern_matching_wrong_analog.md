---
slug: pattern_matching_wrong_analog
name: Pattern Matching to the Wrong Analog
school: standard
citation_tier: "★★"
always_load: true
related_models:
  - base_rate_fallacy
  - confirmation_bias
  - selection_pressure
  - circle_of_competence
code_consequences:
  - HIMS analysis explicitly cited multiple analogs (Stitch Fix, Casper, Allbirds — failed DTC; vs successful DTC like Warby Parker) — calibrated against analog selection
  - Cross-framework decision matrix flags single-analog reasoning ("the next NVIDIA") as anti-pattern
  - F4 / F7 frameworks operate against own-history base rates rather than borrowed-analog base rates
  - ADR-023 §1.3 Block 2 mandates probabilistic reasoning with explicit reference class — anti-analog discipline
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Pattern Matching to the Wrong Analog

> "This is the next X." Most "next X" companies aren't. The discipline is choosing the right analog, not just any flattering one.

## Summary

Cognitive trap of selecting historical analogs based on superficial similarity rather than structural match. "The next Amazon" rhetoric defines the reference class to flatter the specific case, ignoring the much larger reference class of "ambitious-CEO ecommerce ventures that didn't compound."

## When to apply

- Every "next X" thesis — what would have to be true for the analog to hold? Is that observable?
- Sector-pattern recognition — sectors evolve; today's analog isn't yesterday's
- "This time is different" claims — sometimes correct, often confirmation-bias
- Reference-class construction — the most relevant historical comparison is rarely the most flattering one

## Inversion form

The over-corrective stance: refusing to draw any historical analogies. History does inform — the discipline is structural matching (capital structure, business model, sector regime, competitive landscape) rather than narrative matching ("disruptive consumer brand").

## Antipatterns

- "The next Amazon / Apple / Tesla" without checking the much larger reference class of "ambitious-CEO ventures that failed"
- Pattern-matching on outcome (10x in 10 years) rather than starting conditions
- Ignoring that the analog operated in a different sector regime
- Single-analog reasoning when multiple analogs (some successes, some failures) exist

## Examples in this codebase

- HIMS dive: explicitly named multiple DTC analogs (Stitch Fix, Casper, Allbirds — failed; Warby Parker — partial success) rather than citing one flattering case
- INTA dive: vertical-SaaS reference class (Veeva, Tyler, RealPage) was structurally appropriate (same business model, same sector regime)
- AMBA dive: specialty-silicon analogs include both acquired success cases and faded ones — bimodal distribution acknowledged
- Base-rate citation in narrative output (ADR-023 §1.3 Block 2) is the structural defence against single-flattering-analog reasoning
