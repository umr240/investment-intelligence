---
slug: buffett_ten_year_hold
name: Buffett's 10-Year-Hold Test
school: buffett
citation_tier: "◯"
always_load: true
related_models:
  - owner_operator_stance
  - compounding
  - circle_of_competence
  - margin_of_safety
code_consequences:
  - Default analytical horizon is 10 years across all frameworks
  - F2 momentum framework explicitly DOWN-weighted in stage-aware composite (short-term momentum is not a 10-year signal)
  - ROIC volatility (Tier 1 ≤10%) measures durability across multi-year cycles
  - Verdict labels avoid words tied to short-window catalysts ("ahead of earnings", "set up for the print")
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Buffett's 10-Year-Hold Test

> *"If you're not willing to own a stock for 10 years, don't even think about owning it for 10 minutes."* — Buffett

## Summary

The discipline of evaluating every potential position as if you'd hold it for a decade with no ability to exit. Strips out short-window catalysts, sentiment, and price-action thinking. What remains is the business itself — its moat, its capital allocator, its compounding runway.

## When to apply

- Every WATCHLIST decision — would I hold this through a 50% drawdown if business fundamentals stayed intact?
- Every research output — did I rely on short-window catalysts that won't matter in year 7?
- Every valuation — does the math survive being wrong about the next 24 months?
- Every framework weight — does this signal predict 10-year economic outcomes, or 6-month price moves?

## Inversion form

The trader's stance: optimising for the next earnings print, the next event-driven catalyst, the next sector rotation. The 10-year-hold test is the structural defence against this. If you wouldn't hold through closure, you shouldn't have entered.

## Antipatterns

- Frameworks weighted by short-window backtest performance over 10-year economic logic
- Sizing decisions tied to "near-term catalysts"
- Excluding companies because the 6-month chart looks bad (recency bias)
- Including companies because the 6-month chart looks good (also recency bias)

## Examples in this codebase

- Composite stage weights down-weight F2 (momentum) for established / stage-3 companies — short-term momentum is not the 10-year signal for a mature business
- Tier 1 quality gates emphasise multi-year ROIC durability, not single-year peak
- ADR-023 §1.5 forbids language tied to short-window events ("headed into earnings", "set up for the print")
- F7 contestedness flagged because z-score cheapness operates on multi-year price-multiple history, not 12-month signals
