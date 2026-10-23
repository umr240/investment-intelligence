---
slug: efficient_market_filtration
name: Efficient Market Filtration
school: fama_asness
citation_tier: "★★★"
always_load: true
related_models:
  - signal_vs_noise
  - opportunity_cost
  - probabilistic_thinking
  - circle_of_competence
code_consequences:
  - F4 stealth framework explicitly targets information that's NOT yet priced (neglect premium, smart-money accumulation before consensus)
  - F7 framework flagged as contested because cheapness alone is heavily priced — efficient-market default
  - ADR-021 methodology choice (Peters-Taylor capitalisation, not management non-GAAP) targets methodological asymmetry the market under-applies
  - Cross-framework decision matrix recognises that single-framework signals consistent with consensus add little; signals inconsistent with consensus are higher-value
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Efficient Market Filtration

> Public information at low frequency is mostly priced. The edge lives in (a) better processing of public data, (b) information that arrives slower than capital, (c) methodological asymmetries.

## Summary

Eugene Fama's efficient-markets framing, refined by Cliff Asness and others into a graduated view: markets are *mostly* efficient on widely-available data at high frequency. Edge available to retail / individual investors lives in the residuals — better processing of slow-moving public data (Piotroski signals), information that arrives at slower rates than capital can chase (multi-year quality persistence), and methodological asymmetries (Peters-Taylor capitalisation that institutions apply unevenly).

## When to apply

- Every framework signal — is this signal already priced, and if so, what makes our application different?
- Cross-checking apparent edges — if a signal looks great, why isn't capital already exploiting it?
- F4 / F7 contestedness flagging — these frameworks operate against a heavily-filtered substrate
- Methodology choices — first-principles methodology is structural alpha because it's not what platforms aggregate

## Inversion form

The "I have edge everywhere" trap: assuming the signals we observe aren't priced because we found them. They often are; the discipline is identifying *specifically why* this signal isn't priced (e.g. Hong-Lim-Stein neglect: low-coverage names are priced as if they have analyst coverage).

## Antipatterns

- Treating low-multiple cheapness as edge (it's the most-arbitraged signal)
- Single-factor "value" or "momentum" signals — heavily priced
- Ignoring why a "great signal" isn't producing returns despite being well-known
- Confusing "low coverage" with "neglected" (some low-coverage names are correctly neglected)

## Examples in this codebase

- F7 explicitly flagged as contested — z-score cheapness alone is heavily filtered out by the market
- F4 academic anchors target information-arrival lags (insider buying, 13F deltas) — slower than capital can chase
- ADR-021 Peters-Taylor methodology — first-principles capitalisation that platforms don't uniformly apply (methodological asymmetry)
- F1 Piotroski signals — slow-moving fundamental quality signals; market under-applies because horizon is too long for most capital
