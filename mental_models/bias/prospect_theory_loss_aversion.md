---
slug: prospect_theory_loss_aversion
name: Prospect Theory & Loss Aversion
school: kahneman_tversky
citation_tier: "★★★"
always_load: true
related_models:
  - sunk_cost
  - confirmation_bias
  - anchoring_bias
  - probabilistic_thinking
code_consequences:
  - Verdict labels avoid emotional language that triggers loss-aversion framing ("avoid losses" vs "miss opportunities")
  - Composite scoring is symmetric across positive and negative — no asymmetric weighting toward avoiding losses vs capturing gains
  - F4 framework signals incorporate "smart money" accumulation patterns that account for loss-aversion-driven retail behaviour
  - Bias guardrails enforce that "EXCLUDE" is as legitimate an output as "WATCHLIST" — no asymmetric reluctance to act
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Prospect Theory & Loss Aversion

> Losses hurt ~2x as much as equivalent gains feel good. People hold losers and sell winners — exactly opposite of optimal.

## Summary

Kahneman-Tversky's foundational behavioural-economics work: humans are not utility-maximisers but loss-averse evaluators. Losses feel about twice as bad as equivalent gains feel good, producing systematic disposition effects (sell winners, hold losers), reference-point dependence, and probability weighting that over-weights small probabilities and under-weights moderate ones.

## When to apply

- Re-evaluating prior verdicts — am I keeping a name on watchlist because I don't want to "lose" the prior research investment?
- Position-sizing decisions — am I sizing smaller because of recent loss aversion, even if the edge is unchanged?
- Verdict-emotional-tone awareness — does this dive feel like "avoiding a loss" rather than calibrated EXCLUDE?
- Cross-period thesis defence — am I holding the thesis because exiting feels like loss, not because evidence supports it?

## Inversion form

The over-corrective stance: ignoring loss aversion's signal value. The fact that something feels like a loss is informative — sometimes the loss aversion is reading real risk that the analytical model is missing. Defence: when loss aversion fires strongly, run the inversion explicitly to see if the gut is reading a structural risk.

## Antipatterns

- Holding a name "until I get back to even" (loss aversion + anchoring)
- Refusing to EXCLUDE a previously-strong-feeling thesis (loss aversion + sunk cost)
- Sizing smaller after recent losses when edge hasn't changed
- "Avoiding a loser" framing dominating "best available" framing in opportunity-cost decisions

## Examples in this codebase

- Verdict vocabulary structurally symmetric — WATCHLIST and EXCLUDE both legitimate outputs; no asymmetric preference
- ADR-023 §1.5 forbidden-language list bans loss-frame language in outputs
- Composite scoring symmetric in positive / negative directions — no asymmetric weighting
- F4 stealth signals capture institutional behaviour that often runs counter to retail loss-aversion patterns (institutional accumulation when retail capitulates)
