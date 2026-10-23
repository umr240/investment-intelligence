---
slug: antifragility
name: Antifragility
school: taleb
citation_tier: "★★"
always_load: true
related_models:
  - margin_of_safety
  - hormesis
  - red_queen_effect
  - selection_pressure
code_consequences:
  - Tier 1 Quality gates include ICR ≥ 4.0x (Recession Stress Test) — survives 2008-style credit crunch
  - Tier 1 ROIC volatility filter (<10%) measures durability across cycles — antifragile businesses don't degrade under stress
  - F4 stealth signals reward businesses where institutional accumulation persists through volatility (antifragile capital structure)
  - Composite caps prevent any single signal from dominating — system itself is antifragile to single-signal corruption
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Antifragility

> Antifragile = strengthens under stress. Robust = unchanged. Fragile = breaks. Most "stable" businesses are actually fragile under hidden stressors.

## Summary

Taleb's framing for systems / businesses / portfolios that *gain* from disorder rather than merely surviving it. A bank with conservative loan-to-deposit and excess capital strengthens during downturns (acquires distressed competitors, hires laid-off talent). A levered private-equity rollup is fragile under the same conditions.

## When to apply

- Recession-stress analysis — does this business strengthen, persist, or collapse under stress?
- Capital structure analysis — does the leverage profile create antifragile optionality (debt-funded acquisitions in down markets) or fragile compulsion (debt-service obligations during downturns)?
- Innovation analysis — does R&D intensity create antifragile optionality (multiple shots on goal) or fragile single-bet exposure?
- System design — does the analytical pipeline strengthen with more dive iterations, or degrade?

## Inversion form

What does fragility look like? High-fixed-cost businesses without scale, high-leverage businesses without offsetting cash flow, single-customer concentration, single-product franchises (Blackberry post-iPhone). Each is identifiable from the financials.

## Antipatterns

- Treating "low volatility" as antifragility (it's actually robustness, which is one rung below)
- Equating "diversified" with antifragile — diversification can be fragility if all diversified assets correlate under stress
- Citing "great track record" as evidence of antifragility — track record over a benign period doesn't test fragility
- Building portfolios around antifragility without tail-risk discipline

## Examples in this codebase

- Tier 1 Recession Stress Test (ICR ≥ 4.0x) — explicit antifragility test
- Tier 1 ROIC volatility filter — durability under cyclical stress
- F4 short-interest analysis — antifragile names see institutional accumulation rising as short interest peaks (squeeze potential)
- HIMS dive: $1.12B convertible debt issued at presumed peak = fragile under multiple-compression scenarios; failed antifragility lens
