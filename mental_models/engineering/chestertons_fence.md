---
slug: chestertons_fence
name: Chesterton's Fence
school: chesterton
citation_tier: "★★★"
always_load: true
related_models:
  - failure_mode_analysis
  - read_before_writing
  - respect_the_contract
  - circle_of_competence
code_consequences:
  - When refactoring framework / overlay / parser code, understand WHY the existing pattern exists before replacing it (e.g., the seemingly-redundant span filter in companyfacts parser exists to prevent quarterly-YTD leakage)
  - ADRs in `docs/architecture/adrs/` document WHY each architectural decision was made — chesterton-fence-resistant by design
  - Mental-model retirement criteria (ADR-024 §1.6) require explicit annual review — defends against quietly removing a model whose role isn't currently visible
  - Anti-pattern lists in every ADR explicitly document what was rejected and why
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Chesterton's Fence

> *"Don't ever take a fence down until you know the reason why it was put up."* — G.K. Chesterton. Critical for AI agents refactoring code: the agent doesn't have the context the original author had.

## Summary

Code conventions, defensive checks, redundant-looking branches, and "weird" patterns often exist because past failures shaped them. Removing them naively reintroduces the bugs that produced them. The discipline is: investigate before refactoring; understand the reason before assuming it's unnecessary.

## When to apply

- Every refactor — what does this code currently do that I'm about to remove?
- Every "this seems redundant" branch — when was it added, and what bug was it preventing?
- Every "let me clean this up" instinct — does the cleanup re-create a class of failures the original was preventing?
- Every architectural pattern that "should be simpler" — is it covering a complexity the simpler version misses?

## Inversion form

What does naive removal cost? Bugs that surface weeks later in subsystems you didn't know depended on the removed code. The agent that removed the span filter "to clean up" the parser silently re-introduced quarterly-YTD leakage that nobody noticed for two refresh cycles, eventually corrupting framework scores. Loud failure on first regression would be a gift; silent regression is the rule.

## Antipatterns

- "This looks unused, let me remove it" without `git blame` + commit-message reading
- Removing a defensive check because tests still pass (tests don't cover the failure mode the check exists for)
- Replacing a "verbose" pattern with a clever one without understanding why the verbose pattern was chosen
- Cleaning up "redundant" branches in error handling

## Examples in this codebase

- `data/edgar_companyfacts.py` — span filter (350-380 days for annual periods) prevents YTD-vs-period leakage; looks redundant, isn't
- The accession-level `FinancialSourceLog` cache prevents redundant SEC fetches; removing it would seem like simplification but would reintroduce rate-limit pressure
- ADR-021 §0 — explicitly documents the rejected "Phase 2 Non-GAAP ROIC" path; future agent considering "let's just add SBC add-backs" must read the rejection first
- Multiple framework disqualification checks (CGS top-decile, M-Score) — each was added in response to a specific class of false-positive; removing one re-opens that class
