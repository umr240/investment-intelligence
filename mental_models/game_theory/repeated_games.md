---
slug: repeated_games
name: Repeated Games (Axelrod)
school: axelrod
citation_tier: "★★★"
always_load: false
related_models:
  - thorndike_outsiders_eight_traits
  - signalling_games
  - incentive_structures
  - buffett_ten_year_hold
code_consequences:
  - F5 / F6 weight CEO tenure heavily — long-tenured managers play repeated games with capital markets and reputation matters
  - Multi-year insider buy/sell ratio captures repeated-game strategy (consistent buying = reputation; one-shot selling at peaks = defection)
  - Outsiders trait #8 (long tenure) maps directly to repeated-game discipline
  - ADR-021 §0 — chose Peters-Taylor over management-non-GAAP because the latter has known repeated-game failures (each "one-time" charge becomes structural)
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Repeated Games (Axelrod)

> One-shot games favour defection. Repeated games favour cooperation. Reputation only exists in the repeated case.

## Summary

Robert Axelrod's *Evolution of Cooperation* established that in indefinitely-repeated games, cooperative strategies (tit-for-tat) dominate defection-based strategies because reputation accumulates and reciprocity becomes valuable. Translated: long-tenured CEOs interact repeatedly with capital markets, employees, customers; reputation matters and shapes their decisions. One-shot CEOs face no such constraint.

## When to apply

- CEO evaluation — does this leader play repeated games (long tenure, reputation-cultivating actions) or one-shot games (short tenure, opportunistic moves)?
- Capital-market interactions — companies that repeatedly tap markets need to maintain reputation; one-time IPO + done can defect
- Customer-relationship analysis — recurring-revenue businesses are repeated games; transaction businesses are closer to one-shot
- M&A behaviour — frequent acquirers are repeated-game players; rare acquirers may default to opportunism

## Inversion form

The one-shot trap: a CEO acting cooperatively to build reputation may defect catastrophically near retirement (one-shot at the end of repeated game). Defence: watch for pattern shifts in late-tenure CEOs — over-leverage, last-minute M&A, aggressive optionality cashing.

## Antipatterns

- Treating any long-tenured CEO as automatically reputation-disciplined (they may defect at the end)
- Ignoring repeated-game dynamics in serial acquirers (their next deal is shaped by their last deal's reputation)
- Treating a single transaction with a customer as predictive of long-term relationship economics
- Confusing "long history" with "playing repeated games" — some long histories are sequences of one-shot games

## Examples in this codebase

- Outsiders trait #8 (long tenure) + trait #7 (skin in the game) = repeated-game discipline indicators
- F5 buyback timing analysis across multi-year window — repeated-game consistency vs one-shot opportunism
- ADR-022 methodology discipline — committing to declared sources is itself a repeated-game commitment device
- HIMS dive: founder-CEO Dudum is in repeated-game mode (long tenure, ownership) BUT the $918M convertible at peak looks like one-shot opportunism — pattern divergence to flag
