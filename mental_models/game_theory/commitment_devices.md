---
slug: commitment_devices
name: Commitment Devices (Schelling)
school: schelling
citation_tier: "★★★"
always_load: false
related_models:
  - signalling_games
  - repeated_games
  - thorndike_outsiders_eight_traits
  - incentive_structures
code_consequences:
  - F5 surfaces long-duration debt as constraint on future capital allocation — debt is a commitment device that limits dividend / buyback / M&A flexibility
  - F6 founder-CEO ownership % — illiquid concentrated stake is a commitment device tying CEO to long-run outcome
  - ADR-022 source-provenance discipline is a commitment device — declaring sources publicly raises cost of methodology drift
  - ADR-024 schema enforcement is a commitment device — mandatory inversion_form raises cost of half-loaded models
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Commitment Devices (Schelling)

> A commitment that constrains your own future options is often more credible than a promise that doesn't.

## Summary

Thomas Schelling's bargaining-theory insight: voluntarily restricting one's own future options can produce better strategic outcomes by making one's commitment credible. In business: long-duration debt commits future cash flows. Founder ownership commits the founder to long-run outcomes. Public ADR commitments raise the cost of methodology drift.

## When to apply

- Capital-structure analysis — what commitments has management voluntarily accepted, and what does that signal?
- Dividend policy — initiating a dividend is a commitment device (cuts are reputation-damaging); buybacks are not
- Architectural decisions — ADRs and schema enforcement are commitment devices for the codebase
- CEO equity grants — multi-year vesting + claw-back provisions = commitment devices

## Inversion form

The bad-commitment failure: committing to a path that turns out to be wrong, and being unable to exit gracefully. Long-duration debt issued at peak rates = bad commitment. Defence: commitment devices should be evaluated against the *base rate* of being wrong; over-commitment is worse than under-commitment when the future is uncertain.

## Antipatterns

- Issuing long-duration debt at peak rates / multiples ("locking in cheap capital" or "locking in the high")
- Multi-year executive comp tied to a single metric (commits to that metric, gameable)
- Mental-model schema with no inversion_form requirement (no commitment to lattice quality)
- Public predictions without margin of safety (over-commits to point estimates)

## Examples in this codebase

- HIMS dive: $918M convertible debt issued at presumed peak = commitment device locking in expensive capital cost into a fragile period
- ADR-024 §1.6 mandatory schema fields = commitment device against half-loaded mental models
- ADR-022 source-provenance declaration = commitment device against silent methodology drift
- Outsiders trait #6 (strategic episodic leverage) — leverage as deliberate commitment device, not chronic crutch
