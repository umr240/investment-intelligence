---
slug: read_before_writing
name: Read Before Writing (Claude Code Discipline)
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - chestertons_fence
  - mirror_existing_patterns
  - respect_the_contract
  - circle_of_competence
code_consequences:
  - Before editing: view the target file, the relevant test, any imports, and the immediately upstream/downstream callers
  - Before adding a new pattern: search the codebase for existing instances of the same problem and adopt the pattern in use
  - Before assuming a function signature: read the actual definition, not the inferred one from usage
  - Pattern recognition: existing code reflects accumulated decisions; new code should fit the established shape
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Read Before Writing (Claude Code Discipline)

> View the file, the SKILL.md, the test, and any imports — before editing. The CLAUDE.md project already has strong conventions; an agent that doesn't read first will violate them.

## Summary

AI-agent-specific engineering discipline. The agent's training-data defaults often conflict with project-specific conventions. Reading the target file, related code, tests, and CLAUDE.md sections relevant to the change is structurally required before generating an edit. The cost of read-before-write is usually <30 seconds; the cost of writing-without-reading is the time to revert + re-do once a convention violation surfaces.

## When to apply

- Every edit to existing code — read the file (and related context) first
- Every new module — search for similar patterns already in the codebase; adopt the existing convention
- Every "I'll just add a quick X" — verify there isn't already an X in a different naming convention
- Every test write — read the existing tests in the same module to match their style and depth

## Inversion form

What does write-first cost? Code that contradicts existing patterns — different naming style, different error-handling, different test structure, different import conventions. The codebase reads like four authors after every Claude Code session, and CLAUDE.md's purpose (concentrating conventions) erodes. The agent's training data favours generic patterns; this codebase has specific ones; the agent must defer to the specific.

## Antipatterns

- Generating code based on training-data defaults without checking the target file
- Adding imports without checking existing import patterns
- Writing tests without reading existing tests in the same area
- Making an "obvious" small change without reading the function it touches

## Examples in this codebase

- CLAUDE.md sections (TECH STACK, AI layer boundary, Operational rules) document conventions the agent must respect
- ADRs document past decisions — agent must read relevant ADR before changing a system the ADR governs
- `frameworks/f1_pre_discovery.py` style is the template for any new framework — read it before writing F8
- Counter-example to watch for: an agent that adds a new XBRL alias to `_INCOME_CONCEPTS` without reading the parser logic that consumes it (would miss the span-resolution requirement)
