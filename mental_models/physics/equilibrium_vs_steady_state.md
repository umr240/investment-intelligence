---
slug: equilibrium_vs_steady_state
name: Equilibrium vs Steady State
school: standard
citation_tier: "★★"
always_load: false
related_models:
  - regression_to_mean
  - feedback_loops
  - stocks_vs_flows
  - nash_equilibrium
code_consequences:
  - Regression-to-mean signal interpretation depends on whether the system is in stable equilibrium (mean is stationary) or steady state (mean is drifting at a stable rate)
  - F2 momentum signals get different weight in equilibrium vs steady-state regimes
  - DCF terminal-value modelling distinguishes "perpetual growth at g" (steady state) from "stable margin and ROIC" (equilibrium)
  - Cross-sector base rates differ partly because some sectors are equilibrium (commodity chemicals) and others steady-state (software platforms)
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Equilibrium vs Steady State

> Equilibrium = no net change. Steady state = constant rate of change with stable structure. They look similar in cross-section but produce different forecasts.

## Summary

Physics distinction often conflated in business analysis: equilibrium is when forces balance and the system is at rest. Steady state is when the system is changing at a constant rate but its underlying structure (relative composition, ratios) is stable. A company at equilibrium has flat fundamentals; a company in steady state is growing at a constant rate.

## When to apply

- DCF modelling — distinguish perpetual-growth steady state (g > 0) from no-growth equilibrium (g = 0)
- Regression-to-mean reasoning — what's "the mean" reverting to? An equilibrium level or a steady-state trajectory?
- Sector regime classification — commodity chemicals (equilibrium), software (steady-state growth), biotech (transient between regimes)
- F2 momentum signals — momentum in steady state is different from momentum during transition between regimes

## Inversion form

The "transient as permanent" trap: misclassifying a transient phase between equilibria as a steady state. NVIDIA pre-AI-cycle and post-AI-cycle are different regimes; treating mid-2010s as steady state misses the phase transition coming.

## Antipatterns

- DCF perpetual-growth at high rates (treats high growth as steady state when it's almost always transient)
- Regression-to-mean reasoning that ignores whether the mean itself is moving
- "Mature business" classification when the business is actually pre-equilibrium (early in steady-state phase)
- Treating high growth + high stability as a paradox (they coexist in steady-state regimes)

## Examples in this codebase

- DCF analyzer in `unified-backend/strategies/screening/dcf_analyzer.py` distinguishes growth-phase from terminal-value
- F7 z-scores assume own-company history captures the relevant regime — fails when the regime has shifted
- AMBA / INTA / HIMS each represent different regimes: AMBA equilibrium-stuck, INTA early steady-state, HIMS transition (could go either way)
- Tier 1 vs Tier 2 distinction implicitly captures regime — Tier 1 quality looks for equilibrium-stable moats; Tier 2 looks for steady-state-positive operating leverage
