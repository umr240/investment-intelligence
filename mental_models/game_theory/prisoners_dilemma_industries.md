---
slug: prisoners_dilemma_industries
name: Prisoners' Dilemma Industries
school: standard
citation_tier: "★★"
always_load: false
related_models:
  - nash_equilibrium
  - repeated_games
  - munger_dorsey_five_sources
  - lunch_eating_test
code_consequences:
  - Sector base-rate construction recognises prisoner's-dilemma sectors (commodity airlines, undifferentiated retail, mining) as structurally lower-quality
  - Cross-framework decision matrix flags PD-industry positions even when individual frameworks score well — industry equilibrium dominates
  - Helmer Counter-Positioning Power is the strategy that escapes the prisoner's-dilemma equilibrium
  - F6 customer concentration analysis (Patatoukas) captures whether the company is in a PD with its customers
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Prisoners' Dilemma Industries

> Industries where individual rational decisions produce collectively poor returns. "Bad" industries aren't bad managers — they're bad equilibria.

## Summary

Game theory's classic 2-player setup applied to industry structure: when each competitor's best response (price cuts, capacity additions, marketing intensity) leads to a worse collective outcome, the industry is structurally low-return regardless of management quality. Pre-consolidation airlines, commodity chemicals, undifferentiated retail are textbook examples.

## When to apply

- Sector-level analysis — is this industry in a prisoners' dilemma?
- Bottom-up + top-down reconciliation — strong company in PD industry usually still produces mediocre returns
- "Disruptor" theses — does the disruption escape the PD or just join it?
- Industry consolidation cycles — exit from PD is often via consolidation (post-merger oligopoly), not innovation

## Inversion form

The "this time is different" trap: assuming a PD-industry company has escaped the equilibrium when it hasn't. Most "best-in-class operator" claims in PD industries fail empirically; the best operator simply earns slightly less terrible returns than peers.

## Antipatterns

- Treating individual-company quality as sufficient when industry is in PD
- Confusing temporary supply imbalance (one player exiting) with permanent equilibrium shift
- "Branded commodity" — sometimes real (Coke), often not (most consumer staples in undifferentiated categories)
- Ignoring that PD often produces *low* volatility (everyone's mediocre together) — not all stable industries are good

## Examples in this codebase

- AMBA dive: specialty silicon at sub-$2B competing against Mag 7 = PD-like (price competition + capability matching with deeper-pocketed players)
- HIMS dive: DTC consumer health pre-incumbent-entry = oligopoly-feeling; post-incumbent-entry (Lilly, Walmart Health direct distribution) → PD-like
- INTA dive: vertical SaaS for legal/PE = NOT a PD industry — switching costs + Cornered Resource break the PD structure
- Sector base rates differ in part because PD vs non-PD industries produce different distributions of outcomes
