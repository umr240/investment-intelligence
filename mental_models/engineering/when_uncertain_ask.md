---
slug: when_uncertain_ask
name: When Uncertain, Ask
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - circle_of_competence
  - read_before_writing
  - respect_the_contract
  - one_concern_per_change
code_consequences:
  - When user request has plausible alternative interpretations, ask via AskUserQuestion (per Claude Code skill)
  - Architectural decisions (new ADR, schema change, methodology choice) — confirm scope before implementing
  - When project conventions are unclear: read CLAUDE.md + relevant ADRs before guessing
  - When a contract appears to conflict with the user's stated request: flag the conflict, don't silently choose one side
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# When Uncertain, Ask

> If two interpretations of a request are plausible, ask. Don't pick the one Claude Code can solve fastest. The cost of asking is one round trip; the cost of guessing wrong is the entire reverse-engineering cycle.

## Summary

AI agents have a structural bias toward action — silence is awkward; producing output feels productive. But when the user's request admits multiple plausible readings, picking one without checking is gambling on the user's intent. The discipline is recognising "this could mean X or Y" *before* generating output and surfacing the choice rather than implicitly deciding.

## When to apply

- Every request with two plausible interpretations
- Every architectural-scope decision (new directory? new top-level module? new ADR?)
- Every "do you want full or minimal version?" before generating either
- Every conflict between user's stated request and a documented contract — surface the conflict; don't silently resolve

## Inversion form

What does guess-and-ship cost? Reverse-engineering work — the user reviews the output, identifies the wrong interpretation, asks for the other, agent produces the other, user re-reviews. Two cycles instead of one. Plus the user's trust degrades each time the agent's "default reading" turns out to be wrong. Asking up-front is cheaper across both axes.

## Antipatterns

- Picking the interpretation the agent can solve fastest
- Generating both versions and asking the user to choose (wastes the user's review time)
- Silent contract bending when the user's request appears to require it
- "I'll go ahead and assume X" without flagging the assumption

## Examples in this codebase

- This very session used AskUserQuestion at multiple decision points (scope of GAAP/non-GAAP integration; ADR-022 minimum viable shape; Stage 0c placement) — appropriate use of the discipline
- Counter-example to watch for: an agent that adds an `engineering/software/` sub-directory without checking whether the user wanted flat or nested structure
- ADR-023 §"Open questions" deliberately defers ambiguous design decisions to implementation time — preserves the option to ask
