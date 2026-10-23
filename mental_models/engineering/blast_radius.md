---
slug: blast_radius
name: Blast Radius
school: sre_security
citation_tier: "★★"
always_load: true
related_models:
  - margin_of_safety
  - failure_mode_analysis
  - opportunity_cost
  - redundancy
code_consequences:
  - Composite score is capped at 10.0; overlay bonuses bounded — blast radius of any single signal is bounded
  - Position sizing ≤ 5-10% per name (per CLAUDE.md / PROJECT_SPEC) — single-position blast radius capped
  - F7 contestedness flagged so the framework can't dominate composite — its blast radius is structurally bounded
  - data_gaps[] surface unknowns so analyst doesn't act on a thesis whose blast radius they haven't measured
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Blast Radius

> If this fails, what does it take down with it? Cap the radius before you cap the probability.

## Summary

SRE / security principle: minimise the consequences of failure rather than relying solely on minimising the probability of failure. Applied to investment analysis: every signal, every position, every framework should have bounded influence such that being wrong about it doesn't cascade.

## When to apply

- Every framework weight — what's the maximum harm if this framework is structurally wrong?
- Every position size — what's the portfolio impact if this name goes to zero?
- Every system change — what depends on this, and what fails downstream if it breaks?
- Every overlay — what's the cap on its composite influence (currently 1.0 / 10.0)?

## Inversion form

The over-corrective stance: capping every signal so tightly that nothing meaningfully drives a verdict. The discipline is *graduated* blast radius — high-confidence signals get more weight, but no signal gets unbounded weight. Defence: the cap exists; the relative weights within the cap are calibrated.

## Antipatterns

- Single-framework signals that can drive a 10/10 composite alone
- Position sizes that depend on a single thesis being right
- Overlays that aren't bounded (could push composite to 10 from a 4 base)
- Framework weights set such that one strong signal dominates
- Concentrated capital in untested theses

## Examples in this codebase

- TOTAL_OVERLAY_BONUS_CAP=1.0 — bounded overlay influence
- Composite clamps to [0, 10] — bounded composite range
- Framework weights renormalised on feasibility — unfeasible frameworks don't cascade-fail the composite
- ADR-021 §0 rejected unbounded SBC add-back chain — its blast radius would have been the entire composite for any high-SBC company
