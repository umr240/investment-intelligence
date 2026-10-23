---
slug: munger_dorsey_five_sources
name: Five Structural Sources of Moat (Munger / Dorsey)
school: munger_dorsey
citation_tier: "◯"
always_load: false
related_models:
  - helmer_seven_powers
  - moat_direction
  - lunch_eating_test
  - challenger_inversion_test
  - tam_ceiling
code_consequences:
  - F6 Platform framework structures moat detection around these 5 sources rather than treating "moat" as monolithic
  - F1 / F3 / F5 / F6 each surface different moat-source signals (intangibles vs switching costs vs network vs cost vs efficient scale)
  - Moat classification in DCF analysis (`unified-backend/strategies/screening/dcf_analyzer.py`) keyed off these categories
  - Cross-framework decision matrix requires identifying WHICH moat source is operative, not just "has moat"
token_cost_estimate: 320
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Five Structural Sources of Moat (Munger / Dorsey)

> *"In business, I look for economic castles protected by unbreachable moats."* — Buffett, channelling Munger

## Summary

Five distinct structural sources of competitive advantage. Each has different signals, different durability characteristics, and different failure modes. "Has a moat" is too coarse — the source matters because the inversions matter.

## When to apply

- Every company evaluation — identify WHICH source is operative
- Cross-checking moat claims — narrative claims of "moat" without identifiable source = no moat
- Sector pattern recognition — different sectors are dominated by different sources (consumer = brand, enterprise = switching costs, marketplace = network, retail = cost / efficient scale)

## The five sources

1. **Intangible assets** — brand, patents, regulatory licences. Examples: Coca-Cola brand, Pfizer patents, Moody's regulatory designation.
2. **Switching costs** — financial, procedural, data, relational. Examples: ERP / CRM (Veeva, Tyler), bank checking accounts, broker IRAs.
3. **Network effects** — value scales with users. Examples: Visa / Mastercard, Airbnb, Booking.com, exchanges (CME, ICE).
4. **Cost advantages** — scale, location, unique resource access. Examples: Walmart scale, GEICO direct distribution, BHP iron ore.
5. **Efficient scale** — limited market that can't profitably support a second entrant. Examples: regional pipelines, regional airports, niche industrials.

## Inversion form

What destroys each source?
- **Intangibles** — brand decay (taste shifts, regulatory loss, scandal). Patents expire.
- **Switching costs** — workflow standardisation lowers them (cloud APIs vs on-prem ERPs).
- **Network effects** — multi-homing destroys them (Uber/Lyft, Spotify/Apple).
- **Cost advantages** — new technology resets the curve (DTC dismantling retail-scale advantages).
- **Efficient scale** — new technology expands the addressable market past niche capacity.

Every moat claim must answer: "what would destroy this, and is that already happening?"

## Antipatterns

- "Has moat" without identifying source
- Treating high gross margins as evidence of moat (could be transient pricing, mix shift, or accounting choice)
- Ignoring multi-homing risk in network-effect claims
- Conflating brand strength with brand premium pricing power

## Examples in this codebase

- F6 Platform framework — surfaces customer concentration (switching cost signal), founder-CEO premium (intangibles via culture), GP/A (cost advantage), Rule of 40 (composite signal)
- DCF moat classification — variable cost trend × rate gives Emerging / Established / Expanding / No Moat labels
- INTA dive read — vertical SaaS = switching costs (procedural + data + relational); explicitly named the source rather than abstract "moat"
- AMBA dive read — specialty silicon at sub-$2B vs Mag 7 = no source identifiable, lunch-eating test fails
