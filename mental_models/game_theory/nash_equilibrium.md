---
slug: nash_equilibrium
name: Nash Equilibrium
school: nash
citation_tier: "★★★"
always_load: false
related_models:
  - evolutionary_stable_strategies
  - prisoners_dilemma_industries
  - munger_dorsey_five_sources
  - lunch_eating_test
code_consequences:
  - F6 platform analysis distinguishes oligopolistic Nash equilibria (Visa/Mastercard duopoly stable) from competitive equilibria (race-to-zero margin)
  - Sector base rates capture industry equilibrium structure — airlines pre-consolidation vs post
  - Cross-framework decision matrix flags businesses operating in race-to-bottom Nash equilibria as structurally lower-quality regardless of current metrics
  - Helmer Counter-Positioning Power = strategy outside the existing Nash equilibrium; competitors can't profitably switch
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Nash Equilibrium

> A configuration of strategies where no player can improve by unilaterally changing. Industry profitability is largely a function of equilibrium structure.

## Summary

Game theory's foundational solution concept: strategies are in Nash equilibrium when no participant can improve outcome by changing strategy alone, given other players' strategies. In economic terms, industry profitability is largely determined by the Nash equilibrium structure: cooperative-feeling oligopolies (consumer staples, payment networks) sustain margins; race-to-bottom equilibria (commodity airlines, undifferentiated retail) compress margins to capital cost.

## When to apply

- Industry-level analysis — what's the equilibrium structure, and does this company benefit from it?
- Cross-sector base-rate construction — different equilibria produce different return distributions
- Competitor analysis — would an equilibrium-changing move by a competitor harm this business?
- Counter-Positioning analysis — is this company operating outside the existing equilibrium?

## Inversion form

The "good company in bad industry" trap: a high-quality operator in a race-to-bottom Nash equilibrium produces mediocre returns regardless of operational excellence. Munger: "I'd rather have a great industry with a fair company than a fair industry with a great company." Defence: industry equilibrium analysis precedes company analysis.

## Antipatterns

- Evaluating company quality without industry equilibrium context
- Treating temporary supply imbalances as permanent (industry equilibria reform)
- Ignoring that disruption shifts equilibrium structure (DTC didn't just enter retail; it shifted the equilibrium)
- "Best operator in the space" claims when the space's equilibrium is unfavourable

## Examples in this codebase

- F6 academic anchors capture equilibrium quality (concentration vs commoditisation)
- AMBA dive: specialty silicon competitive structure = sub-$2B players competing in markets Mag 7 dominates → unfavourable Nash equilibrium
- INTA dive: vertical SaaS in legal/PE has fragmented competitive structure with high switching costs → favourable equilibrium
- HIMS dive: DTC consumer health → race-to-bottom equilibrium once incumbents enter direct distribution
