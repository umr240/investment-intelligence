---
slug: test_behaviour_not_implementation
name: Test Behaviour, Not Implementation
school: standard
citation_tier: "★★"
always_load: true
related_models:
  - functional_core_imperative_shell
  - boundaries_hexagonal
  - parse_dont_validate
  - test_failure_modes_not_happy_paths
code_consequences:
  - Framework tests verify (given typed input → expected typed output), not internal call sequences
  - Avoid mock-heavy unit tests that lock in implementation details
  - Pure-function frameworks enable behavioural testing — input/output assertions, no mocks needed
  - Integration tests at orchestrator level verify the user-visible contract; unit tests of internals stay focused on pure logic
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Test Behaviour, Not Implementation

> Tests against interface, not internals. Refactor freely if behaviour holds. Mock-heavy tests lock in implementation details and prevent refactoring.

## Summary

Tests should assert what the system does (given input X, output is Y or X is persisted in state Z), not how it does it (function A calls function B then C). Implementation-locking tests turn refactors into test rewrites and discourage cleanup. Behavioural tests survive refactoring as long as the contract holds.

## When to apply

- Every test — am I asserting behaviour, or am I asserting "this method called that method"?
- Every mock — does mocking at this layer reflect a real boundary, or am I locking in an internal call sequence?
- Every refactor — if my tests break before I've changed any behaviour, the tests were testing implementation
- Every "test that fails for the right reason" — does it fail because behaviour is wrong, or because I changed an internal name?

## Inversion form

What does implementation-testing cost? Refactor friction. The desire to clean up code or change internal structure is blocked by tests that lock in the current shape. Over time, this calcifies the codebase — implementation can't change without test rewrites, so cleanup never happens.

## Antipatterns

- `mock.patch` at deep internal layers
- Asserting `mock.assert_called_with(...)` for calls that aren't part of the public contract
- Tests that need to be rewritten when internals change but external behaviour doesn't
- Tests that pass only because the implementation matches a specific call sequence

## Examples in this codebase

- Framework score tests assert `(ticker, reader-with-fixtures) → expected FrameworkResult` — pure function tested behaviourally
- `respx` mocks at the HTTP boundary (the real I/O surface) — appropriate; doesn't lock in internal SQLAlchemy call sequences
- ADR-023 §1.8 personality tests assert output structure (sections present, vocabulary constrained) — behaviour, not LLM internals
- Counter-example to watch for: any test that mocks `data.reader.CompanyDataReader.annuals` as part of testing a framework — should pass a `reader` fixture instead, treating the reader as the input
