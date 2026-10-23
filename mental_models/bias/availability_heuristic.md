---
slug: availability_heuristic
name: Availability Heuristic
school: kahneman_tversky
citation_tier: "★★★"
always_load: true
related_models:
  - recency_bias
  - confirmation_bias
  - base_rate_fallacy
  - pattern_matching_wrong_analog
code_consequences:
  - Base-rate citation in narrative output (ADR-023 §1.3 Block 2) defends against availability-driven reference-class selection
  - data_gaps[] discipline prevents available-but-unrepresentative data from filling cognitive gaps
  - F4 stealth framework rewards low-availability information (low analyst coverage) — directly inverts availability heuristic
  - HIMS dive cited multiple DTC analogs (some failed, some successful) — explicit defence against availability-skewed analog selection
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Availability Heuristic

> What comes to mind easily is judged more probable. Memorable cases dominate base rates.

## Summary

Kahneman-Tversky: humans estimate probability by ease of recall. Vivid recent cases (recent crashes, recent multi-baggers) loom larger in cognition than their statistical weight justifies. The most memorable analogy is rarely the most representative one.

## When to apply

- Every "this is like X" reasoning — is X the most representative analog or just the most recent / vivid?
- Risk assessment — recent salient risks dominate; structural background risks under-weighted
- Pattern-matching — availability biases the patterns we notice
- "Stocks that compound 10x" mental list — heavily availability-biased toward recent winners

## Inversion form

The over-correction: refusing to use any available memory because of availability bias. Recent memory does contain signal; the discipline is calibrating against base rates rather than rejecting recall entirely.

## Antipatterns

- "The next NVIDIA" without comparing to the dozens of failed semis from the same era
- Risk-availability skew: 2008-style recession vivid, slow-moving inflation regime less so
- Analog selection driven by ease of recall rather than structural similarity
- Treating sample mean (this dataset's experience) as base rate (population frequency)

## Examples in this codebase

- HIMS dive: explicitly cited failed DTC peers (Stitch Fix, Casper, Allbirds) alongside successful ones to defend against availability bias
- F4 academic anchors built on Hong-Lim-Stein neglect — rewards low-availability information sources
- Base-rate citation (ADR-023) anchors verdicts to population statistics rather than vivid recent cases
- Cross-sector base rates capture multiple availability regimes (each sector has different "vivid memorable" patterns)
