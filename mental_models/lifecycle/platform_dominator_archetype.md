---
slug: platform_dominator_archetype
name: Platform Dominator Archetype (F6 Profile)
school: lifecycle
citation_tier: "★★"
always_load: false
related_models:
  - munger_dorsey_five_sources
  - helmer_seven_powers
  - feedback_loops
  - critical_mass
code_consequences:
  - F6 framework consolidates academic anchors (Patatoukas customer-concentration, Fahlenbrach founder-CEO, Novy-Marx GP/A) + practitioner heuristics (Rule of 40, NRR, GRR)
  - Composite stage-weights up-weight F6 for established / mature companies where platform quality dominates over discovery edge
  - Cross-framework decision matrix recognises platform-dominator profile as the high-quality-compounder regime
  - F6 strong_fit + F3 strong_fit + BEW-1 trigger combine into the high-conviction extreme-winner profile
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Platform Dominator Archetype (F6 Profile)

> A profile of *durable* compounding: high gross profitability + customer-concentration sweet spot + founder-CEO ownership + Rule of 40 mechanics. Empirically captures the names where reinforcing-loop dynamics have already taken hold.

## Summary

The F6 framework synthesises three academic anchors and three practitioner heuristics that identify mature platform businesses with durable competitive position. The profile combines: founder-CEO with ≥5% equity (Fahlenbrach 2009 premium), customer concentration in 15-30% sweet spot with ≥3yr relationships (Patatoukas 2012), GP/A ≥ 0.20 (Novy-Marx 2013 top-40% proxy), Rule of 40 ≥ 35 (revenue growth + FCF margin), NRR ≥ 110% (◯ practitioner), GRR proxy ≥ 90% (◯ practitioner).

## When to apply

- Every dive where the company is established ($5B+ market cap, multi-year history)
- Cross-checking F3 (innovation) — the platform-dominator overlap with high-R&D innovation is the textbook lollapalooza
- Identifying durable compounders for the long-horizon allocation
- Cross-framework decision matrix — platform-dominator + extreme-winner profile is the high-conviction Bessembinder candidate

## Inversion form

What does the *anti*-archetype look like? No founder leadership / low ownership + diversified low-concentration customer base (or none disclosed) + GP/A below 0.20 + Rule of 40 < 25 + NRR < 100% (revenue churning faster than expanding within accounts). The reinforcing-loop dynamics aren't operating; growth requires perpetual external acquisition.

## Antipatterns

- Treating "high growth" alone as platform-dominator evidence (Rule of 40 requires profitability balance, not just growth)
- Network-effects claims without checking critical-mass status
- Single-academic-anchor strong_fit (Patatoukas alone) treated as full archetype
- Ignoring the founder-CEO premium signal when other archetype components are strong

## Examples in this codebase

- F6 framework in `frameworks/f6_platform.py`
- INTA dive: F6=5.0 partial; GP/A 0.42 ✓ (top-40%), Rule of 40 = 41.3 ✓, founder-CEO partial (CEO 7.64% but not founder), customer concentration not disclosed (Patatoukas can't fire) — partial archetype with strong academic-anchor signals
- HIMS dive: F6=6.0 partial — different mix; high R&D / marketing intensity vs low concentration
- Cross-reference: `feedback_loops` (reinforcing-loop dynamics) and `critical_mass` (network effects threshold) — platform dominator archetype assumes both have crossed their thresholds
