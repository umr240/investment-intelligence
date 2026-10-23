---
slug: owner_operator_stance
name: Owner-Operator Stance
school: buffett
citation_tier: "◯"
always_load: true
related_models:
  - buffett_ten_year_hold
  - circle_of_competence
  - opportunity_cost
  - margin_of_safety
code_consequences:
  - CLI verdict vocabulary is constrained to "WATCHLIST WITH TRIGGERS" / "EXCLUDE WITH REASON" / "RESEARCH-ONLY" — no "buy/sell/hold"
  - ADR-023 narrative.py prompt locks the stance via system prompt (Block 1)
  - Verdict labels avoid emotional language ("compelling", "attractive", "tailwinds")
  - F5 / F6 surface CEO trait-level data because owner-operators evaluate the operator
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Owner-Operator Stance

> *"Would I be willing to own 100% of this business for the next 10 years if the market closed tomorrow?"*

## Summary

Default stance for every analytical decision. Not a quant optimising backtests, not a sell-side analyst writing notes, not a banker pitching deals. An owner putting personal capital at risk for the next decade.

## When to apply

- Every framework design choice — does this answer the owner's question?
- Every verdict — would the owner trust this label with their own savings?
- Every output — does the prose read like operator analysis or sell-side prose?
- Every data field — does an owner need this, or is it analyst-bait?

## Inversion form

The analyst stance is the inversion: short horizon, target prices, quarterly catalyst hunting, peer-relative ranking detached from absolute business quality. If a feature would be at home in a sell-side initiation report and not in a BRK letter, it fails this model.

## Antipatterns

- "Buy / sell / hold" verdict vocabulary
- Target prices as primary outputs
- Headline metrics divorced from owner-relevant context (revenue growth without unit-economic context)
- Emotional language signalling enthusiasm ("compelling", "attractive entry", "secular growth story")
- Optimising for short-window backtest performance over 10-year economic logic

## Examples in this codebase

- `cli/main.py:_render_dive_outcome` — verdict labels constrained to non-emotional vocabulary
- `deepdive/orchestrator.py` — composite is a research output, not a buy/sell signal
- ADR-023 §1.5 — forbidden language list (sell-side prose explicitly banned)
- F5 / F6 surfacing CEO tenure, ownership %, capital-allocation history — owner-operators care about the operator
