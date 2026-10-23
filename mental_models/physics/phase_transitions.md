---
slug: phase_transitions
name: Phase Transitions
school: statistical_mechanics
citation_tier: "★★"
always_load: false
related_models:
  - critical_mass
  - equilibrium_vs_steady_state
  - feedback_loops
  - second_order_thinking
code_consequences:
  - F2 / F3 / F7 stage-conditional weighting recognises that phase transitions invalidate prior-regime z-scores
  - DCF DOL_Trend signal (TTM vs annual baseline) explicitly captures inflection points = phase transitions
  - Cross-framework decision matrix flags when a company is between regimes (data ambiguous because the underlying system is changing)
  - Tier 2 "Buy the Change" philosophy targets phase transitions before market recognition
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Phase Transitions

> Discontinuous regime changes — water freezes, ferromagnets demagnetise, NVIDIA pre/post-AI-cycle. Continuous models fail at phase boundaries.

## Summary

Statistical mechanics: most state changes are smooth, but at certain critical points systems undergo discontinuous transitions where small parameter changes produce qualitatively different behaviour. Translated to business: most company-quality changes are gradual, but some are phase transitions — moats that suddenly emerge or collapse, business models that flip from loss-making to profit-generating, sectors that shift regime entirely.

## When to apply

- Inflection-point analysis — is this company at a phase transition, or just having a good year?
- Sector-regime classification — is this sector in transition (e.g. retail pre/post-DTC, semis pre/post-AI)?
- Operating-leverage breakthrough — a company crossing from below-threshold to above-threshold scale
- Market-multiple regime shifts — multiple compression / expansion can be phase-transition-like

## Inversion form

The "transition as trend" trap: extrapolating a phase transition into a continuous trend. NVIDIA's AI-cycle phase transition wasn't a continuous trend; it was a regime change. Forecasting forward from peak as if it's a steady-state usually overshoots.

## Antipatterns

- DCF perpetual-growth modelling at post-phase-transition rates (treats discontinuity as continuous)
- Pre-transition company evaluated using post-transition framework (e.g. F7 z-scores from prior regime)
- Treating multiple expansion / compression as random rather than recognising it as multi-year regime shift
- Ignoring that different companies in the same sector may be on different sides of the transition

## Examples in this codebase

- DCF DOL_Trend signal — TTM vs annual baseline captures inflection (phase transition acceleration)
- Tier 2 "Buy the Change" philosophy — explicitly targets pre-recognition phase transitions
- F7 minimum 5-year history — at minimum spans one regime; phase transitions during the window are observable as z-score discontinuities
- INTA dive ROIC -3.36% → 5.31%: could be early phase transition (loss-making to profitable, R&D-heavy SaaS template) or could be transient — direction beats width-of-evidence here
