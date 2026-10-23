---
slug: taxonomy_of_uncertainty
name: Taxonomy of Uncertainty (Meta)
school: knight_keynes
citation_tier: "★★★"
always_load: true
related_models:
  - epistemic_humility_unknown_unknowns
  - probabilistic_thinking
  - confidence_calibration
  - circle_of_competence
code_consequences:
  - data_gaps[] is a first-class output type — distinguishes "we don't have this datum" (Knightian risk) from "we don't know what we don't know" (Knightian uncertainty)
  - Composite caps + bounded overlay bonuses recognise the structural difference between modelable and unmodelable risk
  - F7 contestedness flag is itself uncertainty taxonomy — the framework is inside known-known modelable space; its empirical hit rate is in known-unknown space
  - ADR-022 methodology disclosure declares modelable assumptions; unmodelable risks remain implicit but bounded by the cap
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Taxonomy of Uncertainty (Meta)

> Frank Knight (1921) and Keynes (1937) distinguished *risk* (known probability distribution) from *uncertainty* (unknown distribution). Most analytical frameworks treat uncertainty as risk, which is the source of most blowups.

## Summary

Knight: **risk** is when you know the distribution (a six-sided die has known probabilities). **Uncertainty** is when you don't know the distribution (will the next CEO be Outsiders-grade — sample size 1, no probability assignable). Most quantitative finance treats Knightian uncertainty as risk by assuming a distribution, which produces tight confidence intervals around the wrong answer. The lattice must respect the distinction.

## When to apply

- Every probabilistic claim — is the distribution known (risk) or assumed (uncertainty masquerading as risk)?
- Every DCF / intrinsic-value model — terminal value is Knightian uncertainty; near-term FCF is Knightian risk
- Every cross-period framework signal — is the historical distribution stationary (risk), or has the underlying regime drifted (uncertainty)?
- Every `data_gaps[]` entry — is the gap a known-unknown (collectible value, finite cost) or an unknown-unknown (the absence is itself the signal)?

## Inversion form

What does collapsing uncertainty into risk cost? False confidence. The DCF that produces a $X.XX intrinsic value treats every input as Knightian-risk-with-tight-interval; many inputs (terminal growth, discount rate, moat persistence) are Knightian uncertainty. The number is precise; the underlying confidence is much wider than the precision suggests. Margin-of-safety discipline is the structural defence.

## Antipatterns

- Treating all DCF inputs as Knightian risk; assigning point estimates to terminal-value parameters
- Treating "we don't have data" (collectible) as equivalent to "this is fundamentally unknowable" (terminal uncertainty about future regimes)
- Producing confidence intervals on Knightian-uncertainty quantities (the interval is fake — there's no distribution to interval over)
- Conversely: refusing to produce ANY estimate because of Knightian uncertainty (paralysis — bounded confidence with margin of safety is the discipline)

## Examples in this codebase

- F7 z-scores compute Knightian risk against own-history sample — internally well-formed
- F7 contestedness flag is the meta-acknowledgement that historical distribution may not predict future (Knightian uncertainty about regime stability)
- `data_gaps[]` distinguishes "value missing" (collectible Knightian risk) from "framework not feasible" (Knightian uncertainty about whether the metric applies)
- Composite caps + margin-of-safety discount on DCF intrinsic value — explicit acknowledgement that the precise number sits inside a Knightian-uncertainty envelope
- ADR-022 Stage 0c methodology panel declares assumptions explicitly — making the risk/uncertainty boundary auditable
