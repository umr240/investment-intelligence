---
slug: recent_ipo_caution
name: Recent-IPO Caution
school: practitioner
citation_tier: "★★"
always_load: false
related_models:
  - sample_size_law_of_small_numbers
  - selection_pressure
  - hormesis
  - circle_of_competence
code_consequences:
  - F2 momentum + F7 z-score frameworks auto-skip on recent IPOs (insufficient_history graceful degradation)
  - Tier 1 ROIC volatility filter requires multi-cycle data — recent IPOs can't satisfy
  - Hormesis lens: recent IPOs haven't been recession-stress-tested (cycle exposure incomplete)
  - Composite renormalises to surviving frameworks rather than penalising — recent IPOs aren't structurally excluded, just appropriately constrained
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Recent-IPO Caution

> Companies <5 years public haven't been selection-tested through cycles. Their data sample is too small for z-score frameworks, their management hasn't been hormetically stressed, and base rates skew positive (failures haven't materialised yet).

## Summary

A profile-level caution that captures multiple lattice models: thin-sample (sample-size-law-of-small-numbers), hormesis-untested (no recession stress in observable history), selection-pressure-incomplete (today's listed sample is heavy with not-yet-failed names), and circle-of-competence-narrow (insufficient observable history for confident inference).

## When to apply

- Every dive where months_since_listing < 60 — frameworks behave conservatively
- F2 / F7 should auto-skip with `insufficient_history` rather than fabricate scores
- Tier 1 quality gates (ROIC volatility, recession stress test) inapplicable
- Composite stage-weights should renormalise rather than zero-fill the missing frameworks

## Inversion form

What does the over-corrective stance look like? Refusing to engage with recent IPOs entirely, missing the genuinely-strong setups (NVIDIA in 2015 was 16 years public BUT had just entered a phase transition; vertical SaaS at IPO often shows the platform-dominator archetype emerging). Defence: don't reject; constrain the toolkit appropriately and acknowledge the unmodelled risk in the verdict.

## Antipatterns

- Computing z-scores on <5 years of data and treating them as informative (small-numbers violation)
- Treating recent-IPO base rates (skewed positive because failures haven't materialised) as the relevant reference class
- Over-claiming durability when the company hasn't been recession-tested
- Ignoring SPAC / direct-listing distinctions — different mispricing dynamics from traditional IPOs

## Examples in this codebase

- `frameworks/f2_momentum.py` and `frameworks/f7_smart_beta.py` raise `InsufficientHistoryError` when annual_years < threshold
- HIMS dive: 51 months post-SPAC; F7 unfeasible; PSA-3 fires off F7 unfeasibility (later self-disqualifies because SPAC ≠ spinoff)
- AMBA dive: long history (~10+ years); recent-IPO caution doesn't apply; full framework toolkit available
- INTA dive: ~6 years post-IPO; near the boundary; F1-F6 run cleanly; F7 z-scores have ~6 years of own-history (borderline thin sample)
