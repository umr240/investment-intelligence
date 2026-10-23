---
slug: historical_base_rates
name: Historical Base Rates
school: standard
citation_tier: "★★★"
always_load: true
related_models:
  - base_rate_fallacy
  - survivorship_bias
  - selection_pressure
  - pattern_matching_wrong_analog
code_consequences:
  - Sector base rates referenced in dive narratives — DTC scaler, vertical SaaS, specialty silicon all have observable historical patterns
  - F4 stealth framework academic anchors built on historical neglect-premium base rates (Hong-Lim-Stein)
  - ADR-023 §1.3 Block 2 mandates base-rate citation in narrative output
  - Cross-sector composite weighting acknowledges different sectors have different distributions
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Historical Base Rates

> Most companies don't 10x. Most "value" cheap stocks aren't value. Most "growth" growth doesn't compound. Reference-class statistics dominate idiosyncratic narrative.

## Summary

The empirical distribution of outcomes for the relevant reference class. Most reasoning errors in investment analysis come from ignoring base rates and over-weighting case-specific evidence. Historical base rates by sector / business model / capital structure are the anchor against which specific theses must justify deviation.

## When to apply

- Every multibagger thesis — what's the base rate for this profile, and what specifically lifts this case above it?
- Sector / sub-sector classification — different reference classes produce different base rates
- Capital-structure analysis — leveraged-rollup base rates differ from organic-compounder base rates
- Recent-IPO assessment — recent-IPO base rates are heavy with not-yet-failed names; selection pressure incomplete

## Inversion form

The over-anchoring failure: treating a specific case as bound by base rate when it's structurally different (NVIDIA in 2015 didn't fit the specialty-silicon base rate). Defence: cite the base rate, then identify what specifically deviates.

## Antipatterns

- Skipping base-rate citation entirely
- Citing a flattering reference class without justification
- Ignoring that base rates evolve (DTC base rate today vs in 2018 is different)
- Confusing base rate (population frequency) with sample (this dataset's experience)

## Examples in this codebase

- HIMS dive cited DTC-scaler base rate (Stitch Fix / Casper / Allbirds reverted) before specific analysis
- INTA dive cited vertical-SaaS base rate (Veeva, Tyler, RealPage compounded) — favourable for specific case
- AMBA dive cited specialty-silicon sub-$2B base rate as bimodal (acquired or fades)
- F4 academic anchors built on multi-year historical neglect-premium base rates
