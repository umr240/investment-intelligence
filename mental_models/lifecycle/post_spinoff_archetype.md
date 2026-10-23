---
slug: post_spinoff_archetype
name: Post-Spinoff Archetype (PSA Overlay)
school: cusatis_desai_jain
citation_tier: "★★★"
always_load: false
related_models:
  - efficient_market_filtration
  - selection_pressure
  - phase_transitions
  - signalling_games
code_consequences:
  - Operational in `overlays/psa.py:run_psa` and `overlays/detector.py:_scan_psa` (PSA-1 through PSA-4)
  - Triggers on listing_type ∈ {spinoff, demerger, carve_out} AND months_since_listing < 36 (PSA-1)
  - Adjusted-Piotroski computation accounts for industry-median comparatives (when warehoused)
  - Desai-Jain focus test classifies same-SIC vs cross-SIC spinoffs (different alpha distributions)
token_cost_estimate: 240
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Post-Spinoff Archetype (PSA Overlay)

> Cusatis, Miles & Woolridge (1993) + Desai & Jain (1999): spinoffs systematically outperform peers in the 12-36 month post-listing window. The empirical edge is largest for cross-industry spinoffs and for companies subjected to forced selling pressure (institutions sell because the spin doesn't fit their mandate).

## Summary

Post-spinoff equities exhibit ~30-month abnormal positive returns vs sector peers, driven by structural mispricing: parent-company shareholders receive shares involuntarily; index funds sell because the new entity isn't in their index; small-cap / sector-fit issues create forced selling unrelated to fundamentals. The mispricing decays as the new entity establishes its own coverage and trading regime.

## When to apply

- Every recent IPO / listing where listing_type is spinoff, demerger, or carve_out (NOT SPACs, NOT direct listings)
- Within 36 months of listing — empirical alpha decay window
- Cross-checking F1 / F4 anomaly signals — PSA-4 fires when Piotroski ≤4 BUT OCF positive AND GP/A strong (the spinoff-specific anomaly profile)
- Desai-Jain focus distinction — cross-industry spinoffs (different SIC from parent) outperform same-industry; document the focus type

## Inversion form

What does the *anti*-archetype look like? Recent listings via SPAC merger (HIMS-style) or direct listing — these face different mispricing dynamics, often the *opposite* (peak hype at listing rather than forced selling). PSA's mispricing is structural to the spinoff mechanism; applying it to non-spinoff recent IPOs produces false positives. PSA-3 trigger correctly self-disqualifies in this case ("not_a_spinoff_candidate").

## Antipatterns

- Applying PSA to SPAC mergers (different mispricing regime, opposite direction)
- Applying PSA to companies >36 months post-listing (alpha window has decayed)
- Ignoring the focus test (cross-industry vs same-industry have different empirical distributions)
- Treating PSA as evidence of company quality rather than evidence of structural mispricing decay

## Examples in this codebase

- `overlays/psa.py:run_psa` — adjusted-Piotroski + Desai-Jain focus + structural-mispricing checks
- `overlays/detector.py:_scan_psa` — PSA-1 (recent spinoff), PSA-3 (F7 unfeasible due to insufficient history — proxy for recent listing), PSA-4 (Piotroski-anomaly profile)
- HIMS dive: PSA-3 fires (F7 unfeasible) but `verdict: "not_a_spinoff_candidate"` — system correctly self-disqualifies because HIMS was a SPAC merger 51 months ago, not a spinoff <36 months
- The PSA self-disqualification on HIMS is the academic anchor working as designed — PSA fires its trigger then refuses to apply when listing_type doesn't match the empirical universe
