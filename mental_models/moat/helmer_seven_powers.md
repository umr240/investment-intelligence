---
slug: helmer_seven_powers
name: Helmer's 7 Powers
school: helmer
citation_tier: "★★"
always_load: false
related_models:
  - munger_dorsey_five_sources
  - moat_direction
  - lunch_eating_test
  - challenger_inversion_test
code_consequences:
  - ADR-023 §1.4 mandates the narrative LLM cite the specific Helmer Power present (or "no Power identified")
  - F6 Platform framework academic anchors map to subset of 7 Powers (Patatoukas concentration → Switching Costs / Cornered Resource; Fahlenbrach founder → Process Power / Cornered Resource)
  - Moat-direction analysis (widening / flat / narrowing) applied per-Power rather than at aggregate "moat" level
token_cost_estimate: 350
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Helmer's 7 Powers

> Hamilton Helmer's *7 Powers* — overlay for completeness on the Munger-Dorsey five.

## Summary

Seven persistent sources of differential return: Counter-Positioning · Scale Economies · Network Economies · Switching Costs · Branding · Cornered Resource · Process Power. Helmer's framing emphasises strategic *defensibility* — what makes the advantage hard to replicate even when observed by competitors with capital.

## The 7 Powers

1. **Counter-Positioning** — incumbent can't adopt the new model without cannibalising existing business. Examples: Vanguard index funds vs active managers; DTC brands vs retail incumbents.
2. **Scale Economies** — declining unit cost as scale grows, with the largest player permanently lower-cost. Examples: Costco, Amazon AWS infrastructure.
3. **Network Economies** — value to each user grows with total users. Examples: Visa, Booking, exchanges.
4. **Switching Costs** — financial, procedural, data, relational. Examples: Veeva, ServiceNow, banking.
5. **Branding** — durable willingness to pay premium for affective / mnemonic reasons. Examples: Tiffany, Hermès, Coca-Cola in cola.
6. **Cornered Resource** — preferential access to a coveted asset. Examples: Pixar's people, mining companies' geology, regulated franchises.
7. **Process Power** — embedded organisational capability that competitors can observe but not replicate. Examples: Toyota production system, TSMC process node leadership.

## When to apply

- Every moat narrative — name the specific Power(s) operative
- Cross-checking moat width vs depth — multiple Powers stacking is rare and valuable
- Inversion at Power level — different Powers fail differently (scale economies erode with technology resets; switching costs erode with workflow standardisation)

## Inversion form

What does *no Power* look like? Differentiation that depends on the founder's continued attention. Cost advantages that any well-funded competitor could replicate in 18 months. Network effects with multi-homing. Switching costs that workflow standardisation is dissolving. Brand without premium pricing power.

## Antipatterns

- Naming "moat" without naming the specific Power
- Confusing market share with Power (large share without Power = vulnerable)
- Treating "secular tailwind" as a Power (it isn't — it's a market condition)
- Process Power claims without organisational evidence (most "operational excellence" is replicable management practice, not Power)

## Examples in this codebase

- INTA narrative read — vertical SaaS legal/PE = Switching Costs + Cornered Resource (years of accumulated firm-specific configuration and matter history)
- HIMS narrative read — DTC consumer = Branding only, no Switching Costs (subscription cancellable in two clicks), no Network Effects, vulnerable to incumbent direct distribution
- AMBA narrative read — no Power identified at sub-$2B specialty silicon scale vs Mag 7 incumbents
- ADR-023 §1.4 §3 mandates Power citation in every narrative output
