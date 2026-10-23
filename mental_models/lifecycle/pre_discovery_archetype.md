---
slug: pre_discovery_archetype
name: Pre-Discovery Archetype (F1 Profile)
school: lifecycle
citation_tier: "★★"
always_load: false
related_models:
  - signalling_games
  - efficient_market_filtration
  - selection_pressure
  - historical_base_rates
code_consequences:
  - F1 framework consolidates the academic anchors (Piotroski, Lakonishok-Lee insider cluster, Hong-Lim-Stein neglect, Cooper-Gulen-Schill asset growth, Novy-Marx GP/A)
  - PSA-4 overlay trigger fires when Piotroski ≤ 4 + OCF positive + GP/A strong — anomaly profile within pre-discovery
  - Composite stage-weights up-weight F1 / F4 for pre-discovery names (small-cap + low coverage)
  - Cross-framework decision matrix recognises pre-discovery profile as a distinct evaluation regime
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Pre-Discovery Archetype (F1 Profile)

> A profile of *under-followed* quality: small-cap + low analyst coverage + improving fundamentals + insider buying + low asset growth. Empirically captures the names where slow-moving public information hasn't been priced because nobody is looking.

## Summary

The F1 framework synthesises five academic signals that empirically identify under-followed quality compounders before broader market recognition. The profile combines: improving fundamentals quality (Piotroski ≥6/9), insider purchase clustering (≥3 unique insiders, 90 days), analyst neglect (≤3 covering analysts), low asset growth (<5% YoY = bottom decile per CGS), and high gross profitability (GP/A ≥ 0.20 per Novy-Marx). Each signal alone is suggestive; the combination is the archetype.

## When to apply

- Every dive where market cap is small ($500M-$5B) and coverage is sparse
- Cross-checking F4 stealth-accumulation signals — pre-discovery is the F4 universe
- Identifying anomalies — names with strong cash flow + GP/A but weak Piotroski (PSA-4 trigger condition)
- Universe construction — the screener's Tier 0-3 ladder filters TOWARDS this archetype before deeper analysis

## Inversion form

What does the *anti*-archetype look like? Large-cap + heavy analyst coverage + flat-to-deteriorating fundamentals + insider selling + high asset growth + mediocre GP/A. The market has fully digested these names; informational edge is minimal. F1 is structurally less useful for these — composite stage weights down-weight F1 for established / mature companies.

## Antipatterns

- Treating any single component (low coverage alone, insider buying alone) as the archetype
- Applying F1 weighting to established mid/large caps where the archetype doesn't fit
- Conflating "neglected" with "correctly ignored" — some low-coverage names are correctly neglected (failure mode for the archetype)
- Treating Piotroski 9 as a perfect score required — 6+/9 is the threshold per the academic literature

## Examples in this codebase

- F1 framework consolidation in `frameworks/f1_pre_discovery.py`
- PSA-4 trigger captures pre-discovery anomalies (Piotroski ≤ 4 + OCF positive + GP/A strong) where the archetype is partial but the residual signal merits deeper examination
- INTA dive: F1=6.0 partial — strong on multiple Piotroski signals (P3 ROA improving, P4 accruals, L5 LT debt decreasing, L6 current ratio up, O8 GM up, with P1/L7/O9 failing); doesn't fit the small-cap / low-coverage piece of the archetype but academic anchors still produce signal
- Cross-reference: `efficient_market_filtration` — pre-discovery archetype targets the slow-moving-information edge that's empirically available
