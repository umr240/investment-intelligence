---
slug: margin_of_safety
name: Margin of Safety
school: graham_buffett
citation_tier: "◯"
always_load: true
related_models:
  - inversion
  - first_principles
  - second_order_thinking
  - probabilistic_thinking
code_consequences:
  - Composite score is capped at 10.0; overlay bonuses bounded at TOTAL_OVERLAY_BONUS_CAP=1.0 — no single signal can dominate
  - Tier 2 screening filter requires margin_of_safety ≥ 20% (Tier 2 DCF intrinsic-value gate)
  - Multiple frameworks must agree before high-conviction labelling (redundancy as safety margin)
  - data_gaps[] preferred over inferred values — uncertainty is acknowledged, not paved over
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Margin of Safety

> *"Buy at a price that survives being wrong about the future."* — Graham, via Buffett

## Summary

Build buffer into every estimate so being wrong about an input doesn't mean being wrong about the conclusion. Applies to valuation (price < intrinsic value by X%), to system design (composite caps, bounded bonuses), and to data discipline (multiple sources, gap acknowledgement).

## When to apply

- Valuation work — discount intrinsic-value estimates by a survivability buffer
- Composite design — no single signal should be load-bearing
- Test design — happy paths assume best case; tests must exercise the worst case
- Methodology — multiple data sources must corroborate any verdict-shaping value

## Inversion form

The "precise enough" trap: a model that produces a tight point estimate ($X.XX intrinsic value) is more dangerous than one that produces a range. Precision without margin of safety creates false confidence. Defence: every numerical output declares its uncertainty, and no verdict rides on point-estimate equality.

## Antipatterns

- Single-framework signals labelled "high conviction"
- Overlay bonuses uncapped (would let one overlay dominate composite)
- Inferred values filling missing data ("approximately X based on sector average")
- Backtests that ignore survivorship bias (delisted companies absent from training universe)

## Examples in this codebase

- `deepdive/orchestrator.py:_compute_overlay_composite_bonus` — TOTAL_OVERLAY_BONUS_CAP=1.0 prevents overlay capture
- `frameworks/composite.py:compute_composite_score` — clamps to [0, 10]; renormalises rather than zero-fills missing frameworks
- Tier 2 screener `min_margin_of_safety=0.20` — DCF gate
- ADR-021 — Peters-Taylor applies a *capitalisation accounting change*, not an earnings adjustment, to avoid the SBC-add-back trap that has no margin of safety
