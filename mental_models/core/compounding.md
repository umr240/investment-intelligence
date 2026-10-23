---
slug: compounding
name: Compounding
school: buffett_munger
citation_tier: "◯"
always_load: true
related_models:
  - buffett_ten_year_hold
  - margin_of_safety
  - probabilistic_thinking
  - second_order_thinking
code_consequences:
  - Default analytical horizon is 10 years (Buffett's hold test) — short-window backtests rejected
  - F5 Quality framework weights ROIC durability + reinvestment runway because compounding requires both
  - Tier 1 "Architect" requires ROIC volatility < 10% — moat consistency over time, not single-year strength
  - Composite score doesn't reward one great year disproportionately; multi-year averages matter
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Compounding

> *"My wealth has come from a combination of living in America, some lucky genes, and compound interest."* — Buffett

## Summary

Small edges sustained over decades dwarf large edges over months. The relevant question is not "what's the rate this year?" but "what's the rate × duration × reinvestment-runway product?" Reflect this in horizon, not just rate.

## When to apply

- Every quality assessment — does this business have *runway* to compound, not just current profitability?
- ROIC analysis — durability matters more than peak level
- Reinvestment rate — high ROIC × high reinvestment runway × long duration = the multibagger formula
- Cost analysis — small structural cost advantages compound; large but eroding ones don't

## Inversion form

What destroys compounding? **Volatility drag** (geometric mean << arithmetic mean when returns vary), **leverage-induced ruin** (one wipeout destroys decades of compounding), **drift in the rate** (slow degradation of ROIC across cycles), **opportunity-cost of dead capital** (compounding requires reinvestment runway, not idle balance sheet). Each is a distinct failure mode worth scoring against.

## Antipatterns

- Single-year peak ROIC celebrated without trajectory
- High dividend payout ratio in a high-ROIC business — kills reinvestment runway
- Backtests measuring CAGR without checking max drawdown — compounding is fragile to large losses
- "10x in 10 years" projections without unit economic durability check

## Examples in this codebase

- F5 ROIC band scoring (`frameworks/f5_growth_quality.py:_compute_roic`) — strong vs acceptable vs weak vs negative
- Tier 1 ROIC volatility filter (<10%) — durability requirement
- ICA-5 firing on PT-ROIC trajectory across periods — compounding requires the derivative to be positive or stable
- F6 "Rule of 40" — combines growth rate AND profitability margin, the two factors compounding requires
