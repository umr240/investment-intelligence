---
slug: moat_direction
name: Moat Direction (Derivative Beats Level)
school: practitioner
citation_tier: "◯"
always_load: false
related_models:
  - munger_dorsey_five_sources
  - helmer_seven_powers
  - second_order_thinking
  - compounding
code_consequences:
  - ICA-5 fires on the GAAP↔non-GAAP ROIC *gap* — captures direction implicitly via cross-period change
  - Tier 2 DCF analyzer tracks variable-cost trend (declining / stable / rising) — direction signal at unit-economic level
  - DOL_Trend (TTM vs annual baseline) explicitly captures moat-direction acceleration ("Buy the Change")
  - ADR-023 §1.4 §3 mandates the narrative LLM declare WIDENING / FLAT / NARROWING — direction is a required output
token_cost_estimate: 240
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Moat Direction (Derivative Beats Level)

> A narrow moat *widening* beats a wide moat *narrowing*. Track the derivative, not just the level.

## Summary

Static moat assessments anchor on current width and miss the direction of travel. The relevant question for an owner-operator over a 10-year horizon is not "how wide is the moat today?" but "is the moat widening or narrowing — and at what rate?" A wide moat decaying produces declining ROIC over the hold period; a narrow moat compounding produces the opposite.

## When to apply

- Every moat narrative — declare WIDENING / FLAT / NARROWING explicitly
- Cross-period analysis — compare PT-ROIC trajectory, not just current level
- Cost-structure analysis — declining variable cost rate = widening unit-economic moat
- Customer-concentration / NRR trends — direction signal at the customer-economics layer

## Inversion form

Static moat assessment: "this company has a wide moat." But: where is it heading? Kodak had a wide moat in 2001 that was already narrowing. Eastman Chemical has a narrower moat that has been quietly widening. Static labels miss both stories.

## Antipatterns

- "This is a moat business" without trajectory analysis
- Backwards-looking moat scoring (high historical ROIC) without forward-looking degradation analysis
- Declaring a moat permanent because it has lasted 20 years (longest-lasting moats decay too)
- Ignoring technology-driven moat resets (DTC eroding retail scale, cloud eroding on-prem switching costs)

## Examples in this codebase

- DCF analyzer trend classification (`unified-backend/strategies/screening/dcf_analyzer.py`) — variable_cost_trend = declining / stable / rising
- DOL_Trend = Growth_EBIT / Growth_Revenue — explicit derivative measurement (>1.0 = moat accelerating)
- INTA dive: ROIC -3.36% → 5.31% = +867bps direction signal supports widening claim
- HIMS dive: PT ROIC 4.57% << GAAP 18.63% (downward gap of -14pp) = direction signal of narrowing economic capital efficiency vs reported
- ADR-023 §1.4 §3 mandates direction declaration in narrative output
