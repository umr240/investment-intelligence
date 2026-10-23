---
slug: failure_mode_analysis
name: Failure Mode Analysis
school: reliability_engineering
citation_tier: "★★"
always_load: true
related_models:
  - inversion
  - blast_radius
  - defense_in_depth
  - challenger_inversion_test
  - root_cause_over_symptom
code_consequences:
  - Every framework has an explicit disqualification check, not just a passing condition
  - Tests prioritise failure-mode coverage over happy-path coverage
  - ICA-5 fires on methodology divergence — failure mode is methodology mismatch, not just bad data
  - F1 / F4 / F7 each declare InsufficientHistoryError as a graceful failure mode rather than fabricating outputs
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Failure Mode Analysis

> Enumerate every way this can fail. Then build for those failures.

## Summary

Reliability engineering's foundational discipline: before deploying a system, list every way it can fail and design defences for each. Applies recursively to investment theses (every way the business can fail) and to the codebase itself (every way the analytical pipeline can produce wrong outputs).

## When to apply

- Every framework / overlay / signal — what are the failure modes, and are they tested?
- Every business thesis — what are the company's failure modes, and which are observable?
- Every data path — what fails silently? what fails loudly? Loud failures are fine; silent failures are bugs.
- Every verdict — what would have to fail for this verdict to be wrong?

## Inversion form

The over-corrective stance: enumerating so many failure modes that nothing ships. The discipline is *prioritisation* — failure modes ranked by probability × impact (failure_pareto). Defence: 80/20 the modes; cover the high-impact ones thoroughly, accept residual risk on low-impact tail.

## Antipatterns

- Listing failure modes without designing defences (philosophy without code)
- Defending against low-impact modes while leaving high-impact modes uncovered
- "It works" tested without "it fails gracefully" tested
- Treating happy-path test coverage as sufficient

## Examples in this codebase

- `frameworks/base.py:InsufficientHistoryError` — graceful failure mode for thin-sample frameworks
- `data/reader.py:CompanyDataReader` returns explicit None for missing fields — silent-failure mode eliminated
- ADR-022 §1.3 ICA-5 self-audits methodology — methodology-mismatch failure mode caught at the trigger
- Tests in `tests/test_frameworks/` should outnumber happy-path tests with failure-mode coverage
