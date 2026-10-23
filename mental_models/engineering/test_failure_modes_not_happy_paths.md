---
slug: test_failure_modes_not_happy_paths
name: Test the Failure Modes, Not Just Happy Paths
school: standard
citation_tier: "★★"
always_load: true
related_models:
  - failure_mode_analysis
  - failure_pareto
  - inversion
  - fail_fast
code_consequences:
  - CLAUDE.md §"Tests exercise failure modes first" — already encoded; promotes to its own model file
  - Framework tests should outnumber happy-path tests with failure-mode coverage (missing data, stale data, wrong data)
  - ADR-023 §1.8 mandates anti-hallucination tests (LLM behaviour under data-gap input)
  - Each disqualification check (CGS top-decile, M-Score) should have a positive test (case where it correctly disqualifies) AND a negative test (case where it correctly does NOT disqualify)
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Test the Failure Modes, Not Just Happy Paths

> Most of the value is in the failure-path tests. Happy-path tests are table stakes; failure-path tests are what catches regressions and produces honest verdicts.

## Summary

Happy-path tests confirm the system works when everything is right. Failure-path tests confirm the system fails *correctly* (loud failure, graceful degradation, accurate `data_gaps`) when inputs are missing, stale, or wrong. The latter is where most of the analytical value lives — analytical correctness in the rare-data case is what separates rigorous systems from fluent-but-wrong ones.

## When to apply

- Every framework test — what failure modes have I covered?
- Every parser test — missing fields, malformed XML, partial filings, NaN values, wrong fiscal year
- Every overlay test — what happens when the trigger fires on incomplete data?
- Every test review — count failure-mode tests vs happy-path tests; aim for failure-mode-heavy

## Inversion form

What does happy-path-only testing cost? The first time a real-world data anomaly arrives in production, behaviour is undefined. Frameworks silently produce wrong scores; parsers silently lose data; the system fails *quietly* exactly when it should fail loudly. Test coverage that's all happy-path is theatre.

## Antipatterns

- Test suites that only verify "given good input, output X"
- Mocking at the wrong layer to avoid the failure cases
- "Edge cases" listed in comments rather than encoded in tests
- 100% line coverage that's all happy-path (line coverage ≠ failure-mode coverage)

## Examples in this codebase

- ADR-023 §1.8 mandates three test categories for narrative.py (contract, anti-hallucination, personality) — explicitly failure-mode-heavy
- Framework tests should cover: company with <2 annual periods (InsufficientHistoryError), company with sga_expense=None (PT degraded mode), company with negative equity (DCF fail)
- Parser tests in `tests/test_data/` should cover: malformed XBRL, missing concepts, multi-accession-merge edge cases
- Counter-example to watch for: any test that only checks "function returns successfully" without asserting the failure modes are also handled correctly
