---
slug: recency_bias
name: Recency Bias
school: kahneman
citation_tier: "★★"
always_load: true
related_models:
  - probabilistic_thinking
  - buffett_ten_year_hold
  - compounding
  - anchoring_bias
code_consequences:
  - Default analytical horizon is 10 years (Buffett's hold test) — defends against short-window over-weighting
  - F2 momentum framework explicitly DOWN-weighted in stage-aware composite for established / mature companies
  - F7 z-scores require ≥5 years of history (cross-cycle context) — single-cycle thinking is rejected structurally
  - ROIC volatility analysis (Tier 1) measures durability across cycles, not single recent year
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Recency Bias

> Six-month price action is not a signal of business quality.

## Summary

The tendency to over-weight recent observations relative to longer-horizon evidence. The most recent quarter, the most recent year, the trailing-six-month price action all loom larger in cognition than their analytical weight justifies. The owner-operator stance over a 10-year horizon is the structural defence.

## When to apply

- Every "this stock is hot" / "this stock is broken" reaction
- Every framework signal that anchors on last-twelve-months — pair with multi-year context
- Every momentum read — what does this look like over 5-10 years, not 12 months?
- Every "great year" — is it sustainable or is the market extrapolating?

## Inversion form

The over-corrective stance: ignoring recent data because it might be recency bias. Recent data is still data; the discipline is contextualising it within longer-horizon evidence, not rejecting it.

## Antipatterns

- 6-month chart shape driving framework weights
- Single-year ROIC peak treated as evidence of moat
- Recent earnings beat / miss treated as signal of business quality
- Momentum (F2) treated as equivalent to other frameworks for mature companies (it isn't)

## Examples in this codebase

- F7 minimum 5-year history requirement — cross-cycle z-scores, not single-window
- Tier 1 ROIC volatility (<10%) — multi-year durability, not peak
- Composite stage weights down-weight F2 for mature / established companies
- HIMS dive: 2025 was a great year (revenue +59%, NI flipped positive) but composite read overlaid the 5-year context (asset growth +205% in CGS top-decile band) — defended against single-year exuberance
