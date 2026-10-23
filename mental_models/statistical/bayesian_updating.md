---
slug: bayesian_updating
name: Bayesian Updating
school: bayes_jaynes
citation_tier: "★★★"
always_load: true
related_models:
  - probabilistic_thinking
  - base_rate_fallacy
  - confirmation_bias
  - sample_size_law_of_small_numbers
code_consequences:
  - Composite re-computed each dive cycle from current data — explicit posterior given new 10-K / 10-Q evidence
  - Multi-dive history persisted in DeepDiveRun — supports Bayesian update across periods (prior verdict + new evidence → posterior)
  - data_gaps[] surface unknowns explicitly — preserves honest priors when evidence is incomplete
  - F1 P3/P4/L5/L6/O8/O9 YoY signals are structurally Bayesian: each year's data updates the moat-direction posterior
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Bayesian Updating

> *Posterior ∝ Prior × Likelihood.* Beliefs update on evidence; the rate of updating is itself a discipline.

## Summary

Formal framework for revising beliefs when new evidence arrives. The posterior probability of a thesis given new data is proportional to the prior × the likelihood of the data given the thesis. Most reasoning errors are Bayesian failures: under-updating (anchoring), over-updating (recency), or wrong priors (base-rate fallacy).

## When to apply

- Every quarterly 10-Q / annual 10-K — what's the prior for this thesis, and how does new data update it?
- Re-evaluating prior dive verdicts — old verdict + new evidence ≠ defending old verdict
- Data-gap reasoning — partial evidence updates the posterior partially, not fully
- Cross-framework reconciliation — when frameworks disagree, the posterior should reflect the weight-of-evidence, not majority rule

## Inversion form

The non-update failure: treating a thesis as fixed regardless of new data (confirmation bias + sunk cost combined). The over-update failure: Treating one quarter's data as if it dominates the prior. Both are Bayesian violations from opposite directions.

## Antipatterns

- "This is still a buy" without explicit reference to what evidence would change the verdict
- Dropping the prior entirely on one strong piece of new evidence
- Treating analyst-target revision as evidence (it's a derived signal, low likelihood weight)
- Confusing Bayesian posterior (probability) with frequentist test (yes/no)

## Examples in this codebase

- DeepDiveRun history persisted — supports cross-cycle posterior tracking (Phase 6.1+ when narrative.py uses this)
- F1 YoY signals (P3/P4/L5/L6/O8/O9) are Bayesian: each year's data is a likelihood update on the quality posterior
- ICA-5 firing on the gap is itself a likelihood update — material divergence between methodologies is evidence the quality posterior is wider than either single number suggests
- Composite re-computed each dive — posterior is recomputed, not just delta-updated
