---
slug: survivorship_bias
name: Survivorship Bias
school: standard
citation_tier: "★★★"
always_load: true
related_models:
  - base_rate_fallacy
  - confirmation_bias
  - probabilistic_thinking
  - circle_of_competence
code_consequences:
  - Screener universe must include delisted companies for honest base rates — current listing skews positive
  - F7 z-scores computed per-company against own history, not survivor-only sector aggregate
  - Backtests of framework signals must use point-in-time universe (companies that delisted are absent today but were in the universe at the time)
  - HIMS-style "DTC scaler" analysis explicitly cites failed peers (Stitch Fix, Casper, Allbirds) — counterfactual to today's listed-survivor view
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Survivorship Bias

> Looking at the survivors tells you what didn't kill them. Not what kills.

## Summary

When the analytical universe is composed only of survivors, every base rate, every "what works" pattern, every backtest is biased toward outcomes that didn't fail. The companies that died are absent — and they were the ones whose patterns *would* have warned us.

## When to apply

- Every screener output — current list excludes companies that delisted; their patterns are missing
- Every "great companies have these traits" pattern study — the failed companies that had the same traits aren't in the dataset
- Every backtest — point-in-time universe vs current universe is a critical distinction
- Cross-sector pattern recognition — semiconductor "winners" exclude the dozens of failed semiconductor companies of the same era

## Inversion form

The over-corrective failure: refusing to learn from survivors at all. Survivors do tell you something — just not what survives. Defence: pair survivor-pattern analysis with explicit failed-peer analysis, citing concrete names and patterns.

## Antipatterns

- "Great founders all do X" — drawn from a survivor sample
- "This sector has these characteristics" — from currently-listed companies only
- Backtests on the current S&P 500 (look-ahead via index reconstitution)
- "Buy the dip" pattern recognition without including the companies whose dip didn't recover

## Examples in this codebase

- HIMS dive: cited *failed* DTC peers (Stitch Fix, Casper, Allbirds) explicitly as base rate — counterfactual to "DTC works" survivor view
- F4 academic anchors (Hong-Lim-Stein neglect premium) controlled for delisted neglect names in original studies
- F7 z-scores compute against own-company history, not sector survivor aggregate
- Tier 1 ROIC volatility filter rewards multi-year durability — implicitly weights against transient-winner survivor noise
