---
slug: challenger_inversion_test
name: $1B-Funded-Challenger Inversion Test
school: practitioner
citation_tier: "◯"
always_load: false
related_models:
  - inversion
  - munger_dorsey_five_sources
  - helmer_seven_powers
  - lunch_eating_test
code_consequences:
  - ADR-023 §1.4 §5 mandates the narrative LLM apply the test with concrete answer ("could a $1B-funded challenger displace this in 5 years?")
  - F6 Platform framework academic anchors (Patatoukas concentration, Fahlenbrach founder-CEO) treated as evidence the test would FAIL for challenger
  - Composite scoring de-rates moats that fail this test even when other framework signals are strong
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# $1B-Funded-Challenger Inversion Test

> If a $1B-funded, top-talent challenger could displace the incumbent in 5 years, the moat is theoretical, not real.

## Summary

Mandatory inversion test for every moat claim. Theoretical moats — those that *describe* an advantage but don't survive a well-resourced direct attack — are everywhere. Real moats survive a $1B challenger with five years of runway. The test forces concrete reasoning about *what specifically* the challenger can't replicate.

## When to apply

- Every moat narrative — explicitly run this test before declaring a moat
- Cross-checking F3 / F5 / F6 strong_fit verdicts — does the moat survive the test?
- M&A speculation — if the answer to "what's the moat" is "scale", a $1B challenger has scale too
- Innovation theses — the innovation that won the first round may not win the second when capitalised competition arrives

## Inversion form

The reverse failure: declaring a moat *cannot* survive when in fact it can. Network effects beyond a critical-mass threshold genuinely don't yield to capital (Visa is not displaceable by a $1B network). Cornered Resources (Pixar's people, regulated franchises) genuinely don't yield. Don't over-invert.

## Antipatterns

- Skipping the test when the company "feels" defensible
- Hand-waving "they have a moat" without naming what specifically the challenger can't replicate
- Treating brand alone as moat without checking whether challenger marketing budgets ($1B over 5 years = $200M/yr) can dent it
- Ignoring multi-homing erosion in network-effect claims

## Examples in this codebase

- INTA dive read — challenger could build the software in 18 months, but couldn't displace embedded firms with years of accumulated firm-specific configuration → passes
- AMBA dive read — challenger doesn't even need $1B; Nvidia / Qualcomm could fund any chip displacement out of weekly cash flow → fails
- HIMS dive read — challenger could replicate the DTC funnel; incumbents (Lilly, Walmart) can spin up direct distribution with existing brand and infrastructure → fails
- ADR-023 §1.4 §5 — mandatory test in every narrative output
