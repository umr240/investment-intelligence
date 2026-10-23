---
slug: kelly_criterion
name: Kelly Criterion
school: kelly_thorp
citation_tier: "★★★"
always_load: false
related_models:
  - probabilistic_thinking
  - margin_of_safety
  - opportunity_cost
  - blast_radius
code_consequences:
  - Position sizing logic (when portfolio layer is built, currently aspirational) should follow Kelly — bet size scales with edge × confidence
  - Composite score serves as a Kelly-input proxy — higher composite implies higher edge implying larger position
  - Margin-of-safety discipline aligns with sub-Kelly sizing (Kelly's "full bet" is too aggressive given parameter uncertainty)
  - F4 strong_fit + cross-framework agreement = Kelly-input "high edge" signal
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Kelly Criterion

> Optimal bet size = edge / odds. Positions sized by Kelly maximise log-wealth. Most investors size sub-Kelly (correctly) because edge estimates are noisy.

## Summary

J.L. Kelly's formula for optimal position sizing under uncertainty: bet a fraction of capital proportional to the edge (probability-weighted advantage) divided by the odds. Mathematically optimal for log-wealth, but practical implementation requires sub-Kelly sizing because edge estimates are themselves uncertain.

## When to apply

- Position sizing — when this becomes part of the system (Phase 6+)
- Concentration decisions — concentrated positions justified only when edge × confidence × capacity supports it
- Cross-framework conviction — the higher the framework agreement, the higher the Kelly-implied size
- Risk management — Kelly bounds the maximum prudent concentration

## Inversion form

The "full Kelly" trap: betting full Kelly assumes perfect knowledge of edge. Real-world edge estimates have meaningful confidence intervals; betting full Kelly with noisy edge estimates produces ruin in the tail. Defence: half-Kelly or quarter-Kelly is the practical norm.

## Antipatterns

- Concentrated position sizing without edge-vs-noise discipline
- Treating "high conviction" as license to bet full size without considering parameter uncertainty
- Equal-weighting (sub-Kelly) when edge varies materially across positions
- Over-Kelly betting (a.k.a. ruin)

## Examples in this codebase

- Composite scoring is graduated 0-10 — supports proportional sizing rather than binary
- Multi-framework agreement requirement bounds Kelly-input edge estimates (single-framework signals have wider confidence intervals)
- Position-sizing layer is aspirational (out of Phase 6 scope) but the framework outputs are designed to feed Kelly-style sizing when built
- Outsiders trait #6 (strategic episodic leverage) reflects Kelly discipline at the company level — leverage when edge is high, deleverage when uncertain
