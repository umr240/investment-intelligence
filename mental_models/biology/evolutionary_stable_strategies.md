---
slug: evolutionary_stable_strategies
name: Evolutionary Stable Strategies (ESS)
school: maynard_smith
citation_tier: "★★★"
always_load: false
related_models:
  - selection_pressure
  - nash_equilibrium
  - munger_dorsey_five_sources
  - helmer_seven_powers
code_consequences:
  - F6 platform framework treats network-effects-with-multi-homing-resistance as ESS-grade moats (Visa) vs displaceable network effects (any with low multi-homing cost)
  - Helmer Counter-Positioning Power maps to ESS — incumbent CAN'T adopt the strategy without cannibalising, so the strategy is stable against invasion
  - Moat-direction analysis distinguishes ESS-stable equilibria from currently-favoured-but-invadable positions
  - Cross-framework decision matrix recognises that ESS-grade moats deserve different treatment from currently-strong moats that face strategic invasion risk
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Evolutionary Stable Strategies (ESS)

> A strategy is evolutionarily stable if no rare alternative can invade it. Most "great strategies" are merely currently-dominant; ESS strategies survive challenger arrivals.

## Summary

Maynard Smith's game-theoretic / evolutionary concept: a strategy is ESS if a population playing it cannot be invaded by a small fraction of players using any alternative strategy. In business: strategies that survive the entry of well-funded challengers are ESS-grade; strategies that depend on incumbent advantages that challengers can replicate are not.

## When to apply

- Every moat narrative — would this moat survive a $1B-funded challenger? (Challenger Inversion Test is ESS in disguise.)
- Network-effects analysis — multi-homing turns network effects from ESS-stable to invadable
- Counter-Positioning analysis — Helmer's Power #1 is an explicit ESS construction
- Long-horizon thesis durability — ESS-grade moats compound for decades; non-ESS moats erode within a cycle

## Inversion form

The "currently dominant ≠ ESS" failure: assuming the current incumbent's position is stable when it's actually merely dominant in the absence of strategic challenge. Defence: explicitly test invasion — what would a challenger do, and does it work?

## Antipatterns

- "Network effects" claimed as moat without checking multi-homing economics
- Brand-only moats treated as ESS (most aren't — challenger marketing budgets can dent brand)
- Counter-Positioning claimed without identifying what specifically the incumbent can't adopt
- Treating market share as ESS evidence (share is observable; stability under challenge is what matters)

## Examples in this codebase

- INTA dive read: vertical SaaS switching costs survive the $1B-challenger test → ESS-grade moat
- HIMS dive read: DTC brand without switching costs is invadable by incumbent direct distribution → not ESS
- AMBA dive read: specialty silicon at sub-$2B has no ESS — Mag 7 incumbents have the resources to displace whenever they choose
- Helmer Counter-Positioning Power = explicit ESS construction; F6 academic anchor weighting reflects this
