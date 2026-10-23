---
slug: incentive_structures
name: Incentive Structures
school: munger
citation_tier: "◯"
always_load: true
related_models:
  - thorndike_outsiders_eight_traits
  - platform_dominator_archetype
  - inversion
  - confirmation_bias
code_consequences:
  - F5 / F6 surface CEO compensation structure when DEF 14A data is available
  - F6 founder-CEO premium (Fahlenbrach) treated as academic anchor — incentive alignment is structural alpha
  - Insider transaction tracking (multi-year buy/sell ratio) is non-optional for management evaluation
  - Buyback timing relative to price (lows vs peaks) surfaced as Outsiders trait #5 signal
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Incentive Structures

> *"Show me the incentive and I'll show you the outcome."* — Munger

## Summary

Behaviour follows incentive. Read the comp structure before the 10-K, the equity ownership before the strategy deck. Owners with skin in the game make different decisions than hired managers paid on EPS metrics. Hired managers paid on revenue grow revenue — even at the cost of unit economics.

## When to apply

- Every CEO evaluation — what is this person being paid to do?
- Capital allocation decisions — does the comp structure reward FCF or EPS or revenue?
- M&A decisions — does the deal benefit shareholders or empire-building executives?
- Buyback policy — at what price band were buybacks executed (incentive: lows; misalignment: peaks)?

## Inversion form

What does *bad* incentive alignment look like? Comp tied to revenue regardless of profitability. Annual EPS targets that incentivise SBC-funded buybacks at any price. Short-tenured CEOs maximising the option value of their grant. M&A bonuses paid on deal completion regardless of post-deal performance. Each is an observable signal in DEF 14A.

## Antipatterns

- Ignoring DEF 14A because "the 10-K has the financials"
- Treating CEO compensation as an HR detail rather than a capital-allocation signal
- Founder-CEO ownership treated as governance risk rather than alignment positive
- Buyback announcements taken at face value without checking execution price band

## Examples in this codebase

- F6 Fahlenbrach founder-CEO signal — `ceo_equity_pct >= 0.05` as an academic anchor
- F5 buyback yield + insider transaction direction — multi-year buy/sell ratio
- DEF 14A parsing in `data/edgar_text_parser.py` — non-optional for management evaluation
- HIMS dive: $918M convertible debt issuance at presumed peak failed Outsiders trait #4 (independent/contrarian) — incentive misalignment showing up as observable behaviour
