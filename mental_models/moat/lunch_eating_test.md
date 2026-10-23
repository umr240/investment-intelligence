---
slug: lunch_eating_test
name: The Lunch-Eating Test
school: practitioner
citation_tier: "◯"
always_load: false
related_models:
  - munger_dorsey_five_sources
  - tam_ceiling
  - challenger_inversion_test
  - opportunity_cost
code_consequences:
  - F6 surfaces growth-vs-incumbents context — not just standalone growth rate
  - Cross-framework decision matrix flags "must take share from Mag 7 head-on" as a structural fail, regardless of other strong signals
  - ADR-023 §1.4 §5 mandates the narrative LLM apply this test concretely (not abstractly)
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# The Lunch-Eating Test

> If scaling requires taking 1–2% from the Mag 7 head-on, the math fails. Look for companies *expanding the pie* or *displacing in markets giants don't defend*.

## Summary

The Mag 7 are not passive. Any thesis that requires winning meaningful share from Apple / Microsoft / Google / Meta / Amazon / Nvidia / Tesla in their core competencies is fighting against the deepest pockets, the strongest distribution, and the most aligned incentives in capitalism. The math fails not because the small company is bad but because the incumbent's defence is rational and well-funded.

## When to apply

- Every "next big thing in [Mag-7-occupied space]" thesis
- Sector analysis — which spaces are Mag 7-defended vs un-defended?
- Innovation thesis (F3) — is the innovation expanding the pie or seeking a slice the giants will defend?
- Acquisition speculation — "great strategic fit" usually means "easily replicated by the incumbent"

## Pass conditions

The lunch-eating test PASSES when:
- Company is *expanding the pie* (creating a new category the incumbents can't easily extend into)
- Company is *displacing in markets giants don't defend* (regulated industries, low-margin operational complexity giants avoid, B2B verticals with relationship capital)
- Company has structural Counter-Positioning (Helmer Power #1 — incumbent can't adopt without cannibalising)

## Inversion form

What does the Mag 7 incumbent *actually defend*? Wherever revenue per engineer-hour is highest and where ecosystem effects compound. The best-defended categories are core search, cloud infrastructure, mobile OS, ecommerce logistics, GPU compute. The least-defended: highly regulated B2B, low-margin operational verticals, geographically-bound services, relationship-driven enterprise sales.

## Antipatterns

- "We're disrupting Google search" — almost always fails
- "We're a better Slack" — Microsoft will defend Teams to zero margin
- "We're an AWS competitor" — without a structural Counter-Positioning angle, this doesn't compound
- Ignoring the question entirely on consumer DTC plays (incumbents don't need to be Mag 7 to defend; Pfizer, Lilly, Walmart are all defending against HIMS-style entrants)

## Examples in this codebase

- INTA dive read — vertical SaaS for legal/PE is in a category Mag 7 doesn't defend (relationship capital + regulated workflows + niche data) → passes
- AMBA dive read — specialty silicon competing in lanes where Nvidia / TXN / AVGO dominate → fails
- HIMS dive read — DTC telehealth competing against incumbents about to enter direct GLP-1 distribution (Lilly, Pfizer, Walmart Health) → fails (defenders aren't Mag 7 but are equally well-funded)
- ADR-023 §1.4 §5 mandates the test be applied concretely with named defenders, not as abstract platitude
