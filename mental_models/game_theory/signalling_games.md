---
slug: signalling_games
name: Signalling Games (Spence)
school: spence
citation_tier: "★★★"
always_load: false
related_models:
  - incentive_structures
  - thorndike_outsiders_eight_traits
  - commitment_devices
  - authority_bias
code_consequences:
  - F4 stealth framework treats insider buying as a costly signal — open-market purchases (transaction code P) require capital commitment, separating signal from noise
  - F5 / F6 surface buyback timing relative to price — at lows = signal of management's view of intrinsic value; at peaks = anti-signal
  - DEF 14A parsing extracts CEO ownership % and tenure — costly signals of alignment / belief in long-run value
  - ADR-022 methodology disclosure is itself a signal — declaring source provenance separates rigorous analysis from sell-side prose
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Signalling Games (Spence)

> Costly signals are credible. Cheap signals are noise. Read management actions for what was costly, not what was said.

## Summary

Michael Spence's Nobel-winning insight: in markets with information asymmetry, signals are credible only if they are *costly* to fake. Translated: management's costly actions (insider buying with personal capital, dividend commitments, debt-funded buybacks at lows) carry information; management's cheap actions (forward guidance, presentations, "vision" decks) carry little.

## When to apply

- Every CEO evaluation — what costly signals has management sent, and what cheap signals?
- Insider transaction analysis — separate code-P (open-market purchase, costly) from code-A (award grant, free)
- Dividend / buyback analysis — buybacks at price lows are costly signals; at peaks are anti-signals
- M&A signalling — debt-funded acquisitions in down markets signal contrarian conviction; equity-funded acquisitions at peaks signal opportunism

## Inversion form

The cheap-signal trap: weighting management's stated views (interviews, earnings calls) heavier than management's costly actions. Defence: when stated views and costly actions diverge, weight the actions.

## Antipatterns

- Reading earnings-call commentary for signal (mostly cheap)
- Treating share-grant vesting as insider buying (it's not — no capital committed)
- Ignoring buyback timing relative to price band
- Treating "founder mode" rhetoric as ESS-grade signal without checking ownership %

## Examples in this codebase

- F1 / F4 insider transaction analysis filters by transaction_codes=("P",) — Lakonishok-Lee discipline; only open-market purchases count
- F5 buyback yield analysis — pairs buyback amount with price band relative to multi-year history
- HIMS dive: $918M convertible debt issuance at presumed price peak = anti-signal (cheap capital deployed at expensive price)
- Outsiders trait #5 — buybacks at lows = costly signal of management's view of intrinsic value
