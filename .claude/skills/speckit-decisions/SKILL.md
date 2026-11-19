---
name: "speckit-decisions"
description: "Before planning, list the accepted ADRs that govern this feature so the plan cites them; runs as the mandatory before_plan hook."
argument-hint: "Optional: the feature directory"
compatibility: "Spec Kit before_plan hook (agentic-kit ADR 005)"
metadata:
  author: "agentic-kit"
  source: ".specify/extensions.yml hooks.before_plan"
user-invocable: true
disable-model-invocation: false
---

## Outline

1. Find the feature's `spec.md` (`.specify/scripts/bash/check-prerequisites.sh --json`).
2. Read the ADR directory (`adr_dir` in `gate.toml`; prefix `adr_prefix`,
   default `ADR`). For each file, read only its status line and title, then
   open the **accepted** ones whose title or Decision touches what the spec
   changes: the modules, data, interfaces or rules it names. Skip proposed,
   deferred, superseded and rejected ADRs; list proposed ones that would
   matter as open questions, not as rules.
3. Hand the plan a short block to put at the top of `plan.md`:

   ```
   ## Governing decisions
   - ADR-NNN <title>: <the constraint this plan must keep>
   ```

   Write "None found" if no accepted ADR applies, with the titles checked.
4. If the spec contradicts an accepted ADR, stop and report it: a change to a
   decision is the owner's (CLAUDE.md, "Decisions are ADRs"), not the plan's.
5. While planning, if the plan makes a lasting design choice that no accepted
   ADR covers (an architecture, a dependency, a data model, or a rule other
   features must follow), draft it as a proposed ADR in the same PR and review
   it with `/agentic-kit:adr-review draft`. Choices that matter only to this
   feature stay in `plan.md`.

Keep it short: titles and one-line constraints, not ADR text.
