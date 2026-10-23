---
slug: leverage_points
name: Leverage Points (Meadows)
school: meadows
citation_tier: "★★"
always_load: true
related_models:
  - feedback_loops
  - second_order_thinking
  - first_principles
  - opportunity_cost
code_consequences:
  - System-design priorities focus on highest-leverage interventions (e.g. fixing total_debt parser had system-wide blast radius — high leverage point)
  - Framework weighting concentrates analytical attention on the metrics that drive multi-period verdicts (ROIC, FCF margin) over those that don't (single-year revenue growth)
  - ADR-022 methodology disclosure operates at the highest leverage point (provenance) — fixing methodology fixes everything downstream
  - F5 / F6 academic anchors are higher-leverage signals than practitioner heuristics
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Leverage Points (Meadows)

> Donella Meadows: small interventions at the right point can shift system behaviour dramatically. Most well-meaning interventions act at low-leverage points and produce nothing.

## Summary

Meadows' classic essay identifies a hierarchy of intervention points in any system, ranked by their power to change system behaviour. The highest-leverage points are mindset / paradigm (rare to access), goals (achievable through prioritisation), rules (architectural decisions), information flows (transparency, methodology disclosure), structure (network topology). The lowest-leverage are parameters (numerical constants).

## When to apply

- Architectural decisions — am I changing a parameter (low leverage) or a rule (high leverage)?
- Bug-fix prioritisation — which fix changes the most downstream behaviour?
- Mental-model additions — which model changes the most code consequences?
- Investment thesis — what's the highest-leverage intervention this management team could make?

## Inversion form

The low-leverage trap: spending energy on parameter tweaks when the system needs a rule change. Defence: each intervention should declare which level it operates at, and prioritise upward in the hierarchy.

## Antipatterns

- Tweaking framework weights (parameters) when the framework structure itself (rules) is the issue
- Adjusting numerical thresholds without questioning whether the threshold metric is the right one
- Adding more metrics (information flows) when the methodology (rules) needs revision
- Optimising for a goal that isn't actually load-bearing

## Examples in this codebase

- ADR-022 methodology disclosure — operates at "information flows" level (high leverage); changes downstream interpretation of every metric
- ADR-024 mental-models library — operates at "structure" level; changes how the system reasons, not just what it computes
- HIMS total_debt fix — operated at parser-rule level; one fix corrected D/E for every levered company in the universe (Pareto-aligned high leverage)
- Composite caps — parameter-level decision; bounded blast radius but doesn't change reasoning structure
