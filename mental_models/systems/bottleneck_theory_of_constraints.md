---
slug: bottleneck_theory_of_constraints
name: Theory of Constraints (Bottlenecks)
school: goldratt
citation_tier: "★★"
always_load: true
related_models:
  - first_principles
  - leverage_points
  - second_order_thinking
  - opportunity_cost
code_consequences:
  - F3 innovation framework focuses on R&D intensity + GP/A — innovation is the bottleneck for compound growth in tech-led businesses
  - Cross-framework decision matrix identifies which framework's failure is the binding constraint vs which are non-binding
  - Test prioritisation focuses on the bottleneck that fails first — usually data quality, then framework logic, then composition
  - HIMS dive: identified marketing intensity (39% of revenue) as the binding constraint on unit-economic compounding
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Theory of Constraints (Bottlenecks)

> Every system has a binding constraint. Improving anything else is wasted effort. Find the constraint, lift it, find the new one.

## Summary

Goldratt's framework: in any production / value-creation system, there is one binding constraint that limits throughput. Improvements elsewhere don't increase output. Diagnosis is: identify the constraint, exploit it (use it fully), subordinate other resources to it, elevate (invest to expand it), repeat as the constraint shifts.

## When to apply

- Business analysis — what is this company's binding constraint? CAC? Talent? Regulatory approval? Component supply?
- Multi-framework verdict reconciliation — which framework's failure is binding (would need to flip for verdict to change)?
- Codebase improvement — which fix unblocks the most downstream analytical capability?
- Capital-allocation analysis — does management's investment correctly target the binding constraint?

## Inversion form

The wrong-bottleneck trap: misidentifying the binding constraint and investing in something that wasn't actually limiting. Companies often invest in growth when retention is the binding constraint, or in features when distribution is. Defence: empirical observation of which input, when changed, actually changes output.

## Antipatterns

- "We need to grow" without identifying what's actually constraining growth
- Optimising for revenue when unit economics are the binding constraint
- Improving a non-binding metric and reporting it as progress
- Treating multiple constraints as equally binding (only one is actually binding at any moment)

## Examples in this codebase

- F3 innovation framework treats R&D intensity as the binding constraint for compound innovation moats
- HIMS analysis: marketing intensity (39%) identified as the binding constraint — additional revenue growth doesn't compound until this loosens
- INTA analysis: customer-acquisition + relationship capital is the binding constraint — addressed by switching costs accumulating over time
- Tier 1 Quality gate ordering: FCF Spread first (gatekeeper), ICR second (survivability) — sequential constraint analysis
