---
slug: falsifiability
name: Falsifiability
school: popper
citation_tier: "★★★"
always_load: true
related_models:
  - inversion
  - failure_mode_analysis
  - confidence_calibration
  - circle_of_competence
code_consequences:
  - Every framework declares a disqualification check — explicit falsifiable claim
  - ADR-023 §1.4 §6 "Triggers to watch" mandates the narrative LLM identify what would falsify the verdict
  - Bias-defence layer enforces falsifiable thesis structure (must specify what would change the verdict)
  - Tier 1 / Tier 2 hard gates produce binary fail outcomes when conditions aren't met — falsifiable structure
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Falsifiability

> A thesis that can't be wrong isn't a thesis. Every claim must specify what observation would invalidate it.

## Summary

Karl Popper's foundational principle for distinguishing scientific from non-scientific claims: a meaningful claim must be falsifiable — its proponent must specify what evidence would prove it wrong. Theses immune to disconfirmation are not analytically useful; they're emotional commitments.

## When to apply

- Every WATCHLIST verdict — what observable future event would change this to EXCLUDE?
- Every EXCLUDE verdict — what observable future event would change this to WATCHLIST?
- Every framework signal — what disqualification check exists, and is it observable?
- Every analytical claim — "this would falsify it" must be specifiable

## Inversion form

The over-corrective stance: requiring such tight falsification criteria that no thesis can be entered. Defence: falsification criteria should be *observable in 1-3 years*, not requiring multi-decade outcomes.

## Antipatterns

- Theses without exit triggers
- "It's a great long-term hold" without specifying what would no longer be true if it weren't
- Framework strong_fit verdicts without disqualification conditions
- Bayesian-update-resistant theses (no evidence would change the verdict)

## Examples in this codebase

- F1-F7 each declare disqualification checks (CGS top-decile, M-Score > -2.22, ROIC < 0)
- ADR-023 §1.4 §6 mandates "Triggers to watch" section in every dive narrative
- Tier 1 / Tier 2 hard gates produce explicit binary fail outcomes
- INTA dive watchlist triggers (F4 reversal, dilution slowing, customer concentration disclosure, PT ROIC trajectory) — observable, time-bounded, falsifiable
