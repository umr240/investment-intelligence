---
slug: respect_the_contract
name: Respect the Contract
school: agent_engineering
citation_tier: "★★★"
always_load: true
related_models:
  - chestertons_fence
  - read_before_writing
  - boundaries_hexagonal
  - parse_dont_validate
code_consequences:
  - CLAUDE.md "AI layer boundary" — Anthropic SDK is permitted ONLY in deepdive/narrative.py. Hard wall. No exceptions.
  - ADR-021 §4.1 forbids management non-GAAP add-backs — hard methodology constraint
  - ADR-022 source-provenance discipline — hard constraint on cross-source mixing
  - ADR-024 §1.3 mandatory frontmatter fields — agent cannot ship a model file missing inversion_form
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Respect the Contract

> When CLAUDE.md says "no LLM calls outside `deepdive/narrative.py`," that's a hard wall, not a guideline. Contracts in this project encode lessons from past failures; bending them re-creates the failures.

## Summary

The project's CLAUDE.md, ADRs, and mental-model schema encode hard constraints. They look like guidelines but they're walls. The agent's "make this work" instinct will sometimes suggest violating a contract for a local benefit; the discipline is recognising that the contract exists for a system-level reason that's not visible from the local context. Contracts are Chesterton's-fence-protected at the architectural layer.

## When to apply

- Every change touching a module governed by an ADR — the ADR's anti-pattern list is binding
- Every "let me just add an API call here" — check CLAUDE.md AI layer boundary first
- Every "this would be cleaner if I bent the methodology rule" — cleanness ≠ correctness; ADRs document why the rule exists
- Every schema-enforced constraint (mandatory fields per ADR-024) — non-negotiable

## Inversion form

What does contract-bending cost? Subtle architectural rot — exactly the thing CLAUDE.md exists to prevent. The agent that adds an LLM call in `data/` to "improve" parsing has just violated the determinism rule that protects every framework score; the violation isn't visible until a downstream consumer notices their outputs are now non-deterministic. By then the rot has spread.

## Antipatterns

- "Just this one exception to the rule" — exceptions are how contracts erode
- Refactoring to "improve" code in ways that violate the existing contract
- Working around the contract instead of asking whether it should change (use ADR for that)
- Treating ADR §"What this ADR does NOT do" as suggestions rather than constraints

## Examples in this codebase

- CLAUDE.md AI-layer-boundary rule — sole permitted Anthropic SDK call site is `deepdive/narrative.py`. Adding LLM calls anywhere else is a contract violation regardless of how clean it feels locally.
- ADR-021 §4.1 forbids management non-GAAP add-backs — agent suggesting "let's add SBC add-back, it's standard" must read the rejection rationale first
- ADR-022 source-provenance — agent suggesting "let's fall back to yfinance for FPIs" violates this; ADR-025 is the correct path (extend SEC parser instead)
- ADR-024 mandatory `inversion_form` — agent shipping a mental-model file without it should be rejected at review
