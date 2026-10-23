---
slug: mirror_existing_patterns
name: Mirror Existing Patterns
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - read_before_writing
  - respect_the_contract
  - code_read_more_than_written
  - chestertons_fence
code_consequences:
  - When adding F8, F9, etc., follow the F1-F7 module structure (DATA_REQUIREMENT at top, async score function, helpers below)
  - When adding a new ADR, mirror the structure of recent ADRs (frontmatter table, §0 reframe, §1 decision, §2 NOT-do, §3 anti-patterns, §4 status, §5 references)
  - When adding a mental model, follow the established schema (frontmatter + Summary + When to apply + Inversion form + Antipatterns + Examples)
  - When adding tests, follow existing test naming and fixture patterns in the same test_<module>.py file
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Mirror Existing Patterns

> If three modules do X one way, the fourth does X the same way. Inconsistency is a bug.

## Summary

Pattern consistency across a codebase is itself a feature. A reader (human or AI) navigating from one framework to another, one ADR to another, one mental-model file to another, should see the same shape. Established patterns reflect decisions; deviating from them without reason produces drift, which compounds as the codebase grows.

## When to apply

- Every new module — what are the existing modules in the same directory shaped like? Match.
- Every new ADR — recent ADRs are the template; mirror their structure
- Every new mental-model file — schema is documented in `mental_models/README.md`; follow it precisely
- Every new test — tests in the same file are the template; match assertion style, fixture style, naming

## Inversion form

What does pattern-drift cost? A codebase that reads like four authors after every Claude Code session. Future agents (and future-you) re-derive the pattern each time, often producing a fifth distinct shape, then a sixth. The structure of CLAUDE.md / ADRs / mental_models is the system *being* the pattern; deviating without reason undermines that.

## Antipatterns

- Adopting a "modern" alternative pattern when the existing pattern works
- "Improving" the pattern in a single new module while leaving the old ones in the previous shape
- Restructuring mid-PR without ADR rationale
- Naming inconsistencies (snake_case vs camelCase vs PascalCase) within the same scope

## Examples in this codebase

- F1-F7 follow the same module structure — `DATA_REQUIREMENT` at top, `async def score_fN`, helper functions named `_compute_*`, returns `FrameworkResult`
- ADR-021 / 022 / 023 / 024 / 025 share the same frontmatter table + section structure — agent adding ADR-026 should mirror
- Mental-model files all share the same schema (12 mandatory fields per ADR-024 §1.3 + 5 mandatory body sections)
- Counter-example to watch for: any new framework that introduces a different return shape, async pattern, or helper-function convention — should be flagged
