---
slug: mean_reversion_secular_vs_cyclical
name: Mean Reversion — Secular vs Cyclical
school: standard
citation_tier: "★★"
always_load: true
related_models:
  - regression_to_mean
  - equilibrium_vs_steady_state
  - phase_transitions
  - moat_direction
code_consequences:
  - F2 momentum signals interpreted differently for secular trends (extrapolatable) vs cyclical (mean-reverting)
  - F7 z-scores compute against own-history — captures cyclical reversion, less reliable for secular shifts
  - Regression-to-mean reasoning split: cyclical mean is stationary, secular mean is drifting
  - Tier 2 DCF moat-direction analysis distinguishes cyclical operating-leverage from secular cost-structure improvement
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Mean Reversion — Secular vs Cyclical

> Cyclical reversion is around a stationary mean. Secular reversion is around a moving mean. Misclassifying produces forecast errors of orders of magnitude.

## Summary

Mean reversion is empirically real for most metrics, but the relevant mean differs by phenomenon type. Cyclical reversion (industries fluctuating around stable equilibrium — commodities, capacity-cycle businesses) reverts to a stable mean. Secular reversion (industries with structurally drifting means — newspapers post-internet, retail post-DTC) reverts to a *moving* mean that may be substantially below where it was.

## When to apply

- Every "this is mean-reverting" claim — what's the relevant mean, and is it stationary?
- "Buy the dip" patterns — cyclical dips revert; secular declines continue
- Multiple-compression analysis — is this a multiple compression around a stable mean (mean-reverting) or a regime shift (not)?
- "Quality compounder at fair price" — the "fair price" anchor must be calibrated to the right mean

## Inversion form

The stationarity assumption: treating all reversion as cyclical when it's actually secular. Kodak in 2001 looked like a cyclical play; it was a secular declining business. Defence: identify the structural drivers of the mean and check whether they are themselves stable.

## Antipatterns

- "Multiple is below historical average" without checking whether the historical average is still applicable
- Reverting to "trailing 10-year median" when the last 5 years marked a regime change
- Treating cyclical earnings cycles as evidence of secular decline (or vice versa)
- Buy-the-dip strategies in secular-decline sectors (catches falling knife)

## Examples in this codebase

- F7 z-scores compute against own-history — robust to cyclical reversion, less robust to secular regime shifts
- Mean-reversion reasoning in F2 momentum framework — cyclical interpretation default, secular adjustment requires explicit context
- AMBA dive: F7 strong_fit (z-score signal of cheapness) — but is the relevant historical mean still applicable? Mature-wave specialty silicon may be in secular decline relative to AI-cycle peers
- INTA dive: GAAP losses are characteristic of SaaS reinvestment phase (cyclical pre-profit), not secular decline
