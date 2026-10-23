---
slug: commitment_consistency
name: Commitment & Consistency
school: cialdini
citation_tier: "★★"
always_load: true
related_models:
  - sunk_cost
  - confirmation_bias
  - liking_loving_tendency
  - bayesian_updating
code_consequences:
  - Every position re-evaluated each cycle as if entered fresh today (CLAUDE.md §"Bias awareness") — defends against commitment-consistency drift
  - DeepDiveRun history persisted but not weighted in current dive composite — past commitments don't anchor present analysis
  - Verdict labels include EXCLUDE explicitly — system structurally permits reversing a prior favourable label
  - ADR-024 §1.6 mental-model annual review — defends against keeping models because authored, not because earning tokens
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Commitment & Consistency

> Once committed publicly to a position, people maintain it past evidence to the contrary. The bias is structural; defences must also be structural.

## Summary

Robert Cialdini's principle: humans value consistency with prior commitments and will rationalise to maintain it even when new evidence contradicts. Public commitments amplify the bias. Translated to investment analysis: prior verdicts, prior research investments, prior public positions create pressure to maintain them — independent of whether evidence still supports them.

## When to apply

- Re-evaluating prior dive verdicts — am I defending the prior verdict or evaluating fresh?
- "I've been long this for years" framing — commitment-consistency may be doing the work, not analysis
- Public positions (writing about a name, sharing a thesis) — public commitment amplifies the bias
- CEO management decisions — has management committed to a strategy that's now wrong but they can't reverse?

## Inversion form

The over-corrective stance: reversing positions whenever evidence suggests, producing whipsawed analysis. The discipline is *evidence-proportionate* update — Bayesian updating with calibrated weight on new vs prior evidence, not commitment-consistency anchoring nor reverse-anchoring rejection.

## Antipatterns

- "I said this was a buy three months ago, so I have to defend it" — commitment-consistency
- Refusing to upgrade a prior EXCLUDE verdict when material new positive evidence arrives
- CEO doubling down on a failing strategy because publicly committed
- Mental-model lattice maintained for inertia rather than utility

## Examples in this codebase

- HIMS dive: F5 dropped from 8.5 (prior, with bug) to 6.0 (after debt fix) — system reversed without commitment-consistency defence kicking in (because the analysis is structurally fresh each dive)
- ADR-024 §1.6 mental-model annual review — defends against author-commitment-consistency at the lattice level
- Bayesian updating model — explicit framework for evidence-proportionate update, defending against both commitment-consistency and over-reaction
- DeepDiveRun history is informational (audit trail) but doesn't bias current dive scoring
