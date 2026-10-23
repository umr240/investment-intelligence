---
slug: verify_with_tests
name: Verify With Tests, Not Assertions
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - test_failure_modes_not_happy_paths
  - test_behaviour_not_implementation
  - fail_fast
  - pre_mortem_before_commit
code_consequences:
  - After every code change: run the tests; verify behaviour empirically
  - Verbal "it should work" is not verification — only test execution is
  - For changes affecting framework scores: re-run a known-stable dive (INTA, AMBA) and confirm scores match expectations or the divergence is explained
  - For parser changes: probe a real ticker before declaring success (the HIMS total_debt fix re-ran the dive to confirm $148M → $1.12B before declaring done)
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Verify With Tests, Not Assertions

> After a change, run the tests. Don't claim success based on "it should work." Especially acute for AI agents — the temptation to say "done" without verification is structural.

## Summary

Code that "should work" by inspection often doesn't. Type checkers and linters catch many issues but miss runtime behaviour. The discipline for any code change: run the tests. For data-layer changes: probe a real ticker. For framework changes: re-run a known-stable dive and confirm the output. "Done" is defined by passing tests + verifying behaviour, not by writing-then-claiming.

## When to apply

- Every code change before declaring complete — run tests
- Every data-layer change — probe a real ticker that exercises the change
- Every framework / overlay change — re-run a known-stable dive (e.g., INTA / AMBA) and verify expected output
- Every parser fix — verify the specific case that motivated the fix actually works post-fix

## Inversion form

What does assert-success cost? Broken main, lost trust, rollbacks. Especially acute for AI agents — the social pressure to ship and move on is high; the verification step is easy to skip. The agent says "done"; the user runs the dive; the dive crashes; trust degrades; future agent-output is treated with more suspicion. The 30-second test-run cost is far cheaper than the trust-erosion cost.

## Antipatterns

- "I made the change, the implementation is correct, no test needed"
- Skipping verification because "the change is small"
- Declaring done without running the failing test that motivated the fix
- Trusting type-check/lint pass as evidence of correctness

## Examples in this codebase

- The HIMS dive session: every fix (total_debt, FY2024 row, shares_outstanding) was followed by re-running the dive and confirming the change took effect — `--force` re-fetch + Python DB query, not just code review
- ADR-023 §1.8 mandates test categories before narrative.py ships — verification is part of the ADR's done definition
- Test-failure-modes-not-happy-paths model — verification must include the failure cases, not just the success cases
- Counter-example to watch for: any agent session that ends with "code changes made" without "tests run" — incomplete by definition
