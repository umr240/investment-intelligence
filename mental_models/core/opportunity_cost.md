---
slug: opportunity_cost
name: Opportunity Cost
school: economics
citation_tier: "◯"
always_load: true
related_models:
  - owner_operator_stance
  - margin_of_safety
  - circle_of_competence
  - probabilistic_thinking
code_consequences:
  - Composite score normalised to 0-10 across companies — every position competes against every other
  - Verdict vocabulary "EXCLUDE WITH REASON" exists to force articulation of why this isn't best-available
  - Universe screening (Tier 0-6 ladder) ranks; doesn't accept "good enough" in isolation
  - F7 contestedness flagged because cheapness is meaningless without comparison to alternatives
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Opportunity Cost

> Every position is a vote against every other position. The bar is "best available," not "good enough."

## Summary

Capital, time, and attention are bounded resources. Allocating to one position means not allocating to another. The relevant comparison is never "is this attractive in absolute terms?" but "is this the best use of capital among the options I have?"

## When to apply

- Every WATCHLIST decision — what is this displacing?
- Every framework score — relative to what universe / sector / peer?
- Every research investment — would the same hour spent elsewhere produce more decision value?
- Position sizing — concentration only justifies if no comparable alternative exists

## Inversion form

The "good enough" trap: a company that scores well in isolation but worse than alternatives that aren't being considered. Defence: framework outputs include relative ranking within universe, not just absolute score.

## Antipatterns

- "This passed all my filters, therefore I should buy" — ignores what else passed
- Sentiment toward a researched name ("I've spent 20 hours on this") creating sunk-cost reluctance to compare
- Sector-specific evaluations that skip cross-sector comparison
- Treating "WATCHLIST" as an obligation to act rather than a permission to monitor

## Examples in this codebase

- Composite score is universe-comparable (0-10 scale across all tickers)
- `screener/` Tier 0-6 ladder ranks; doesn't approve in isolation
- `cli/main.py` verdict vocabulary requires "EXCLUDE WITH REASON" — articulates why this loses to alternatives
- F7 (Smart Beta) contestedness is itself an opportunity-cost statement — cheap doesn't mean best-available
