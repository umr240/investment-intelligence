---
slug: failing_test_before_fix
name: Failing Test Before Fix
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - test_failure_modes_not_happy_paths
  - verify_with_tests
  - fail_fast
  - one_concern_per_change
code_consequences:
  - Bug fix commits include a test that reproduces the bug (and now passes)
  - Test pins the bug — future regressions are caught at CI rather than at the next user-visible dive
  - For data-layer bugs (HIMS total_debt-style): a test that asserts the specific concept gets parsed correctly
  - For framework bugs: a test that asserts the framework produces the expected score given a fixture matching the bug condition
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Failing Test Before Fix

> When fixing a bug, write the failing test first. Then make it pass. The test pins the bug; without it, the bug regresses and nobody notices.

## Summary

The discipline of bug-driven test development: every bug discovered should produce a test that fails *before* the fix and passes *after*. The test stays in the suite forever, preventing future regressions. Without this discipline, the same bug recurs months later because nothing pinned the corrected behaviour. Especially valuable in analytical systems where bugs produce subtly wrong outputs that are hard to notice.

## When to apply

- Every bug fix — write the failing test first
- Every "this should work but doesn't" investigation — encode the expected behaviour as a test, then make it pass
- Every methodology fix — encode the expected behaviour at the framework / overlay level
- Every parser fix — write a test using a fixture that exercises the bug, fix the parser, verify the test now passes

## Inversion form

What does fix-first cost? Bugs that regress because no test pins the behaviour. Six months later, a refactor in an unrelated module quietly re-introduces the same bug; nobody notices because there's no failing test. The bug surfaces again as a wrong verdict on a real ticker. The test would have caught it in CI; without it, the user catches it.

## Antipatterns

- Fixing a bug without adding a test
- "I don't need a test, the fix is obvious"
- Adding a test that passes whether the bug is fixed or not (test doesn't pin the corrected behaviour)
- Bundling bug-fix tests with feature tests in unrelated modules

## Examples in this codebase

- The HIMS total_debt fix should be (and going forward must be) accompanied by a test: feed parser a fixture with `ConvertibleDebtNoncurrent`, assert `total_debt` correctly aggregates it
- ADR-023 §1.8 mandates anti-hallucination tests — encodes failure modes as tests so regressions are caught
- F1-F7 disqualification checks should each have a positive (correctly disqualifies) AND negative (correctly does NOT disqualify) test — catches both directions of regression
- Counter-example to watch for: any bug-fix PR without a test — should be flagged and a test required before merge
