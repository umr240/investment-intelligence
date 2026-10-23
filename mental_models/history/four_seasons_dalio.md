---
slug: four_seasons_dalio
name: Four Seasons (Dalio)
school: dalio
citation_tier: "★★"
always_load: false
related_models:
  - selection_pressure
  - equilibrium_vs_steady_state
  - antifragility
  - mean_reversion_secular_vs_cyclical
code_consequences:
  - Cross-framework decision matrix recognises that framework weights should differ across macro regimes (rising-growth-rising-inflation vs falling-growth-rising-inflation etc.)
  - Tier 1 vs Tier 2 distinction implicitly captures regime-suitability — Tier 1 quality compounds across regimes, Tier 2 operating-leverage is regime-conditional
  - Recession Stress Test (Tier 1) explicitly targets regime survival
  - Phase 6+ macro-regime classifier could route framework-weight selection (currently aspirational)
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Four Seasons (Dalio)

> Four macro regimes: rising vs falling growth × rising vs falling inflation. Different businesses thrive in different seasons. Diversification by regime, not just by sector.

## Summary

Ray Dalio's framework: macro environments cycle through four primary regimes determined by the second-derivatives of growth and inflation. Different business models thrive in different regimes — high-quality compounders in moderate growth + moderate inflation; commodity producers in rising-inflation regimes; defensive cash flows in stagflation. Sector exposure that ignores regime exposure is incomplete.

## When to apply

- Macro overlay on bottom-up analysis — what regime is this business optimised for?
- Recession-resilience scoring — Tier 1's stress test maps to falling-growth regimes
- Inflation-pass-through analysis — does this business hold pricing power in rising-inflation regimes?
- Portfolio construction (out of scope today, but framework structure informs it) — diversification by regime exposure beats diversification by sector

## Inversion form

The "all-weather" overclaim: businesses that seem to compound in any regime usually haven't been tested across all regimes. Defence: anchor regime-suitability claims in observed multi-cycle history, not in narrative.

## Antipatterns

- Sector diversification treated as regime diversification (often correlated within regime)
- "Quality compounder" claimed without regime-stress-test history
- Inflation-hedge claims that haven't survived an actual inflation regime
- Ignoring that current-regime base rates aren't the multi-regime average

## Examples in this codebase

- Tier 1 Recession Stress Test — falling-growth regime survivor test
- Tier 1 ROIC volatility filter — multi-cycle durability indirectly captures multi-regime persistence
- F7 z-scores against own multi-year history — captures the regimes the company has actually traversed
- HIMS dive: 51-month listed history covers only one regime fragment (post-COVID, pre-recession-test) — regime-adjusted base rates penalise short history
