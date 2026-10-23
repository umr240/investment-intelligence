---
slug: sunk_cost
name: Sunk Cost Bias
school: kahneman
citation_tier: "★★"
always_load: true
related_models:
  - opportunity_cost
  - liking_loving_tendency
  - inversion
  - circle_of_competence
code_consequences:
  - Every position is re-evaluated each cycle as if entered fresh today (not preserved by prior research investment)
  - Verdict labels EXCLUDE / RESEARCH-ONLY exist as exit options — system isn't biased toward continued holding by framework structure
  - Mental-model retirement criteria (ADR-024 §1.6) defend against keeping models because they were authored, not because they earn their tokens
  - data_gaps[] surfaced fresh each dive — past data investments don't anchor today's coverage assessment
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Sunk Cost Bias

> Every position is re-evaluated each cycle as if entered fresh today.

## Summary

The tendency to continue a course of action because of past investment, even when forward-looking analysis says stop. Hours spent researching create reluctance to abandon. Capital deployed creates reluctance to sell. Both are sunk; only forward economics matter.

## When to apply

- Every WATCHLIST → re-evaluation cycle — what would I do if this were a fresh idea today?
- Every position holding period — would I enter this position now at this price with current data?
- Every framework / mental model — does this still earn its tokens, or is it preserved because it was authored?
- Every research investment — does the next hour spent on this name produce more value than the next hour elsewhere?

## Inversion form

The under-corrective stance: discarding genuine accumulated knowledge because of bias-awareness over-correction. Years of context on a name are real informational advantage. The discipline is separating *informational* sunk cost (legitimate) from *emotional* sunk cost (the bias to defend against).

## Antipatterns

- "I've spent 20 hours on this thesis" creating reluctance to exclude
- "My average cost is below current price" treated as relevant to forward decision
- Keeping mental models in the lattice because they were written, not because they have code consequences
- Defending a prior verdict on a name despite new data contradicting it

## Examples in this codebase

- Composite recomputed each dive — past verdicts don't anchor present scoring
- ADR-024 §1.6 mental-model retirement criteria — annual review forces honest assessment of whether each model still earns its tokens
- F4 framework treats institutional ownership as a SIGNAL, not as proof that "smart money likes this so I should too" — defends against anchoring on prior institutional consensus
- HIMS dive: F5 dropped from 8.5 to 6.0 after total_debt fix — the prior 8.5 was based on incomplete data; sunk-cost defence required re-running cleanly without preserving the higher prior score
