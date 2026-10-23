---
slug: base_rate_fallacy
name: Base Rate Fallacy
school: kahneman_tversky
citation_tier: "★★★"
always_load: true
related_models:
  - probabilistic_thinking
  - regression_to_mean
  - sample_size_law_of_small_numbers
  - bayesian_updating
code_consequences:
  - ADR-023 §1.3 Block 2 mandates "PROBABILISTIC: state the base rate for this profile and the conditional probability"
  - F4 stealth framework rewards low analyst coverage explicitly — base rate of neglect-premium outperformance (Hong-Lim-Stein)
  - HIMS dive read explicitly cited DTC consumer-scaling base rate (Stitch Fix / Casper / Allbirds reverted) before sector-specific analysis
  - Cross-framework decision matrix flags single-framework strong_fit verdicts unless base-rate context supports
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Base Rate Fallacy

> The specific case feels different. The base rate doesn't care.

## Summary

Tendency to ignore prior probability (the base rate for the reference class) in favour of case-specific evidence. Most companies don't 10x. Most DTC scalers don't compound. Most "next NVIDIA" candidates aren't. Specific-case analysis without base-rate anchoring produces over-confident verdicts.

## When to apply

- Every multibagger thesis — what's the base rate for this profile?
- Sector-pattern recognition — DTC, biotech, semis have observed reversion patterns
- Recent-IPO analysis — base rate for SPAC-merger names underperforming index is real
- Cross-framework verdicts — anchor framework strong_fit against the base rate of false positives

## Inversion form

The over-anchoring failure: treating a specific case as bound by base rate when it's genuinely different. NVIDIA in 2015 was inside the "specialty silicon" base rate but was empirically not bound by it. Defence: cite the base rate, then identify *specifically what evidence* lifts this case above (or below) the rate.

## Antipatterns

- Skipping base-rate citation entirely ("this stock is a 10x candidate")
- Citing a flattering reference class ("the next FAANG" — who chose that reference class?)
- Refusing to deviate from base rate when specific evidence is genuinely strong
- Conflating base rate (population frequency) with sample mean (this dataset's experience)

## Examples in this codebase

- HIMS dive read: cited DTC-scaler base rate (Stitch Fix/Casper/Allbirds reverted) before specific analysis
- INTA dive read: cited vertical-SaaS base rate (Veeva/Tyler/RealPage compounded) — favourable for the specific case
- AMBA dive read: specialty-silicon sub-$2B base rate is bimodal (acquired or fades) — explicit reference class
- ADR-023 §1.3 Block 2 mandates probabilistic reasoning with base-rate citation
