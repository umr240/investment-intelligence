---
slug: tracer_bullets
name: Tracer Bullets
school: pragmatic_programmer
citation_tier: "★★"
always_load: true
related_models:
  - yagni
  - boring_technology
  - rule_of_three
  - when_uncertain_ask
code_consequences:
  - Build the thinnest end-to-end slice that produces a real verdict on one real ticker BEFORE generalising the framework set
  - A working fetch→parse→one-framework→output path beats a complete data layer with no consumer — the slice proves the architecture, the layers don't
  - New ADRs should be validatable by a single concrete dive, not by inspection of the design alone (pairs with verify_with_tests)
  - n=1 vertical slice (subgraph retrieval → stakes-routed reframe → decision log → confidence update) is the canonical tracer-bullet shape — ship it end-to-end, then widen
token_cost_estimate: 180
version: 1.0
added: 2026-06-07
last_reviewed: 2026-06-07
---

# Tracer Bullets

> Hunt & Thomas: fire a thin round that goes the whole distance and shows you where you're hitting, before you build the full ammunition. Build one slice end-to-end first; flesh it out once the path is proven.

## Summary

A tracer bullet is a thin, *working*, end-to-end slice through every layer of the system — UI to data to output — that does one real thing on real input. It is not a prototype (which is throwaway); the tracer code stays and gets fleshed out. The point is feedback: a slice that runs proves the architecture connects, surfaces the integration problems early, and gives something to verify against. The opposite — building each layer "complete" before connecting any — defers all integration risk to the end, exactly when it's most expensive.

This is the direct structural antidote to the documented `planfall` / scaffolding-trap failure mode: building meta-frameworks before shipping. The tracer bullet *forces* a shippable result before generalisation is permitted. Distinct from `yagni` on a different axis: YAGNI governs *scope* ("don't build what you don't need yet"); tracer bullets governs *sequencing* ("of what you do need, build it thin-but-whole first"). They agree in practice but answer different questions.

## When to apply

- Every new project or major feature — what's the thinnest slice that produces a real output on real input?
- Every "I'll build the data layer fully, then the frameworks, then the output" plan — invert it; build one path through all three first
- Every architecture you're tempted to validate by inspection — can a single concrete run validate it instead?
- Every moment the instinct is "let me build the general version first" — that's the `planfall` tell; fire a tracer

## When NOT to apply

- When the end-to-end path is genuinely trivial and the risk is entirely in one layer (then de-risk that layer directly)
- When a tracer would require building throwaway scaffolding to fake the other layers — that's a prototype, label it as one and don't keep it
- Don't confuse "thin" with "sloppy" — the tracer is production code, just narrow

## Inversion form

What does layer-by-layer-complete cost? Integration risk concentrated at the end. You build a beautiful data layer and a complete framework set that have never run against each other; on first connection the contracts don't match, the assumptions baked into each layer collide, and you're debugging the whole system at once instead of one thin path. Worse for an INFP-scaffolding-trap operator: the general framework gets built, feels like progress, and ships *nothing* — the meta-work becomes the work. The tracer bullet's discipline is that "done" requires a real verdict on a real input, not a complete-looking subsystem.

## Antipatterns

- Building the full data/warehouse layer before any consumer exists to validate its shape
- "Framework-complete, output-pending" states that have never produced an actual verdict
- Designing the general abstraction before one concrete instance runs end-to-end (also a Rule-of-Three violation)
- Treating a slide-deck architecture or an ADR as validation in place of a running slice

## Examples in this codebase

- LifeOS n=1 vertical slice — the canonical tracer: one subgraph retrieval → one stakes-routed reframe → one decision log → one confidence update, end-to-end, before widening the ontology tooling
- The Boardroom: a single known-stable dive (INTA / AMBA) that runs fetch→parse→framework→narrative is the tracer that proves the pipeline; new frameworks widen a proven path rather than extending an unproven design
- Counter-example to watch for: ADR-024 §1.7's deferral list (composer, Obsidian sync, RAG) is YAGNI-correct precisely because it refuses to build tooling layers before the core slice ships — tracer-bullet thinking and YAGNI agreeing
