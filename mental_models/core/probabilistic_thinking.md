---
slug: probabilistic_thinking
name: Probabilistic Thinking
school: tetlock_kahneman
citation_tier: "◯"
always_load: true
related_models:
  - margin_of_safety
  - second_order_thinking
  - circle_of_competence
  - inversion
code_consequences:
  - Verdicts are research labels (WATCHLIST / EXCLUDE / RESEARCH-ONLY), not point-estimate buy/sell
  - F7 z-score thresholds (z < -1.0 = cheap) are probabilistic regions, not crisp pass/fail
  - ADR-023 §1.3 Block 2 mandates "PROBABILISTIC: state the base rate for this profile and the conditional probability"
  - DCF intrinsic-value calculation is followed by margin-of-safety discount — point estimate explicitly distrusted
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Probabilistic Thinking

> Outcomes are distributions, not point estimates. Always state base rate, conditional probability, and downside.

## Summary

A "good business" is one whose distribution of 10-year outcomes has a heavy right tail and a survivable left tail. A point estimate of fair value hides the distribution. Probabilistic framing forces explicit treatment of base rates and tail risk.

## When to apply

- Any DCF / intrinsic value output — pair with the distributional context, not just the point
- Sector base rates — DTC, biotech, semis have known reversion patterns
- Conditional updating — when new 10-K data arrives, adjust prior beliefs explicitly
- Verdict labelling — verdicts are claims about the probability distribution, not the realised future

## Inversion form

Point-estimate certainty: a precise intrinsic value or target price that hides what the analyst doesn't know. Defence: every numerical output declares its uncertainty range; verdicts are constrained to the probabilistic vocabulary (WATCHLIST WITH TRIGGERS, not BUY).

## Antipatterns

- Target prices as outputs (false precision)
- Single-scenario DCF models without sensitivity analysis
- Treating a 60% probability as "right" or a 40% probability as "wrong" — both are about the distribution, not the realisation
- Ignoring base rates because the specific case "feels different"

## Examples in this codebase

- F7 z-score bands (z < -1.0 → 5 pts, z > 1.0 → 0 pts) — graded probabilistic regions, not binary
- `frameworks/composite.py` clamps scores and renormalises — produces a graded output, not a binary verdict
- ADR-023 §1.3 Block 2 — narrative LLM mandated to state base rates and conditional probabilities
- DCF margin-of-safety discount (≥20%) — explicit acknowledgement that the point estimate is uncertain
