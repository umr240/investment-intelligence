---
slug: yagni
name: YAGNI (You Aren't Gonna Need It)
school: kent_beck_xp
citation_tier: "★★★"
always_load: true
related_models:
  - rule_of_three
  - opportunity_cost
  - margin_of_safety
  - boring_technology
  - tracer_bullets
code_consequences:
  - CLAUDE.md §"CORE DESIGN PRINCIPLE — LAZY LOAD EVERYTHING" — YAGNI made systemic; nothing runs unless asked
  - Frameworks declare DataRequirement and only fetch the minimum superset needed
  - ADR-024 §1.7 explicit "What this Stage A does NOT build" list — YAGNI applied to mental-model tooling (composer, Obsidian sync, RAG deferred until earned)
  - Composite scoring uses simple stage weights, not a learned model — YAGNI applied to ML layers
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# YAGNI (You Aren't Gonna Need It)

> Kent Beck / XP: don't build for hypothetical future requirements. Build for what's needed now. Future requirements are rarely the ones you predicted.

## Summary

Pre-building generality for predicted futures locks in abstractions that turn out to be wrong, accumulates code that has to be maintained even when unused, and slows down current work for unrealised future benefit. Build for the present; refactor when the actual second use case arrives (Rule of Three).

## When to apply

- Every "we should build a generic X for when we need Y" — defer until Y arrives
- Every "abstract base class with one subclass" — collapse to the concrete
- Every "config option that nobody uses" — remove
- Every architectural extension — does the current work need it, or am I building for a hypothetical?

## Inversion form

What does pre-building cost? Locked-in wrong abstractions + debt that compounds. The generic framework you built three months ago for a use case that never materialised now blocks the actual extension you need today because its abstraction shape doesn't match. YAGNI's inversion is "abstract too late," but "abstract too early" is the more common failure.

## Antipatterns

- Plugin architectures with one plugin
- Configuration systems where every value is overridable but nobody overrides them
- Abstract base classes added "just in case" we need a second implementation
- Caches added before profiling shows they're needed

## Examples in this codebase

- CLAUDE.md core principle — lazy-load architecture; nothing runs without explicit user instruction
- Frameworks fetch the minimum superset declared by selected frameworks' DataRequirement, not "fetch everything just in case"
- ADR-024 §1.7 explicit deferral list (composer, Obsidian sync, embedding RAG) — YAGNI applied to lattice tooling
- F1-F7 are concrete frameworks; no abstract `Framework` base class hides the fact that each framework has different data needs
- Counter-example to watch for: ADR-021 deliberately rejected the "Phase 2 Non-GAAP ROIC pipeline" which would have been pre-built for hypothetical future need
