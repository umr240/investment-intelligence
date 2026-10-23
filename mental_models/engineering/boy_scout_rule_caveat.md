---
slug: boy_scout_rule_caveat
name: Boy Scout Rule — With Caveats
school: martin
citation_tier: "◯"
always_load: false
related_models:
  - one_concern_per_change
  - chestertons_fence
  - rule_of_three
  - yagni
code_consequences:
  - Improvements bundled into commits ONLY when they're directly related to the change in scope (one concern per change)
  - '"While I was in there" cleanup is deferred to its own commit unless it''s in the path of the actual change'
  - Refactoring changes are isolated commits — not mixed with bug fixes or feature additions
  - Mental-model annual review (ADR-024 §1.6) is a structured "leave the campsite cleaner" cycle — bounded, scheduled, not opportunistic
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Boy Scout Rule — With Caveats

> *"Always leave the campsite cleaner than you found it."* — Robert Martin, popular but vague. Without bounds, becomes scope creep dressed as virtue.

## Summary

The rule encourages incremental cleanup as part of any change. Real but easily abused: when "leaving the campsite cleaner" expands to refactoring code unrelated to the actual change, commits become hard to review, hard to roll back, and conflate concerns (bug fix + cleanup + opportunistic refactor in one diff). The constrained version: improvements only in the *immediate path* of the actual change; standalone cleanup gets its own commit.

## When to apply

- Touching a function for a feature/bug change — fix obvious typos, broken comments, dead variables in that function
- Reading a confusing block of code — add a comment explaining the WHY (Chesterton's-fence-friendly) if it'll help future readers
- Passing through a Pydantic model with a missing type hint — add it
- Encountering a clear bug while making an unrelated change — file a separate issue or commit a separate fix; don't bundle

## When NOT to apply

- Refactoring code unrelated to the current change ("while I was in there...")
- Renaming variables in code you're not modifying (creates needless diff noise)
- Style fixes outside the change scope (let the auto-formatter do it on its own)
- Architectural cleanup mixed with feature commits

## Inversion form

What does unbounded "scout rule" cost? Commits that mix concerns, become hard to review, hard to roll back. The bug fix that includes 200 lines of unrelated cleanup is much riskier to merge than a focused 5-line fix + a separate cleanup PR. The discipline isn't "don't clean up"; it's "clean up *separately*."

## Antipatterns

- "While I was in there I refactored the surrounding 100 lines"
- Bundling renames into bug-fix commits
- Style changes mixed with semantic changes (auto-formatter should handle style)
- Treating "the campsite" as the whole codebase rather than the specific function/module being touched

## Examples in this codebase

- ADR-024 §1.6 annual mental-model review — *structured* cleanup cycle, not opportunistic
- Each ADR is a focused architectural commit — doesn't bundle unrelated cleanup
- The HIMS bug-fix session: total_debt fix shipped first as its own concern; FY2024 partial-row fix happened to be incidentally resolved by the same `--force` re-parse but was tracked as a separate task
- Counter-example to watch for: AI-agent sessions where "improving the code" expands beyond the user's stated request — the agent should ship the requested change, then propose cleanup as a separate scope
