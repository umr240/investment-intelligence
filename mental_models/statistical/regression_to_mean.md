---
slug: regression_to_mean
name: Regression to the Mean
school: galton_kahneman
citation_tier: "★★★"
always_load: true
related_models:
  - recency_bias
  - probabilistic_thinking
  - base_rate_fallacy
  - second_order_thinking
code_consequences:
  - F2 momentum signals must be paired with multi-year context — short streaks revert
  - Tier 1 ROIC volatility filter (<10%) rewards stability, not peak — peak years often regress
  - F7 z-scores compute against own multi-year history — captures own-history reversion
  - Composite stage-weights down-weight F2 for mature companies where reversion dominates short-window momentum
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Regression to the Mean

> Extreme outcomes are followed by less extreme ones. The streak ends.

## Summary

Galton's foundational statistical insight, reinforced by Kahneman as the antidote to recency bias. Extreme observations contain a transient component that doesn't repeat. Apparent skill in a streak often dissolves under regression. Apparent crisis in a slump often reverts.

## When to apply

- Every momentum signal — what's the long-run mean, and how far is the current observation from it?
- Every "great year" — was it skill or transient luck?
- Every "horrible year" — is the business broken or is the data point an outlier?
- Cross-checking F2 (momentum) and F7 (cheapness) — both rely on reversion logic but from opposite directions

## Inversion form

The over-reversion failure: assuming everything mean-reverts, including genuine secular changes. Some businesses don't revert (Kodak, Sears, Blackberry) — they're on permanent trajectories. Defence: distinguish *cyclical* reversion (operates around stable mean) from *secular* drift (mean itself is moving).

## Antipatterns

- Treating one good year as a new normal
- Treating one bad year as terminal
- Pairing F2 (momentum) with F7 (cheapness) as if they're independent — both anchor on reversion logic
- Ignoring that the mean itself can drift (recency-bias-corrected over-correction)

## Examples in this codebase

- F2 momentum framework — pairs current momentum with longer-window context
- Tier 1 ROIC volatility (<10%) — durability requirement defends against single-peak misread
- F7 z-score banding — captures own-history reversion structurally
- HIMS dive: 2025's profit jump (NI flipped positive after years of losses) framed against the multi-year trajectory rather than treated as new normal
