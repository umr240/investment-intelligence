---
slug: composition_over_inheritance
name: Composition over Inheritance
school: gof_design_patterns
citation_tier: "★★"
always_load: false
related_models:
  - yagni
  - boundaries_hexagonal
  - parse_dont_validate
  - illegal_states_unrepresentable
code_consequences:
  - Frameworks F1-F7 are functions, not subclasses of an abstract `Framework` class — composed via the orchestrator
  - DataRequirement is composed via merge_requirements(), not subclassed per framework
  - Overlay run_ica / run_psa / run_bew are independent functions called by the orchestrator — no shared inheritance hierarchy
  - CompanyDataReader composes data access — frameworks consume it; no inheritance
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Composition over Inheritance

> Gang of Four: prefer composing behaviour from independent pieces over inheritance hierarchies. Inheritance creates rigid couplings; composition preserves flexibility.

## Summary

Inheritance feels natural in object-heavy languages but produces tight coupling: changing a parent class affects every subclass; subclasses inherit behaviour they don't want. Composition (passing dependencies, calling other functions, combining typed objects) preserves the ability to refactor without ripple effects. In Python this is usually natural; the exception is when refactoring imports a Java/C# instinct.

## When to apply

- Every "I'll create a base class" reflex — would a function or protocol work?
- Every multi-level inheritance hierarchy — is the parent-child relationship genuine, or arbitrary?
- Every "abstract method that all subclasses must implement" — is this actually a function-passed-in?
- Every mixin — does it represent a genuine cross-cutting concern, or is it inheritance-by-the-back-door?

## Inversion form

What does inheritance overuse cost? Tight coupling that resists refactoring; behaviour scattered across the inheritance chain making "where does this method come from?" a navigation problem. The opposite over-correction (no inheritance ever) is also bad — frameworks like SQLAlchemy ORM and Pydantic genuinely use inheritance for declarative purposes.

## Antipatterns

- Abstract base class with one subclass (YAGNI signal)
- Multi-level inheritance hierarchies in business logic (3+ levels deep)
- Mixins that depend on attributes injected by other mixins
- "Override this method" patterns that could have been "pass this function"

## Examples in this codebase

- F1-F7 frameworks: separate functions, no shared hierarchy. Each declares DATA_REQUIREMENT as a module-level constant; orchestrator composes them.
- Overlay functions: `run_ica`, `run_psa`, `run_bew` — independent; orchestrator chooses which to call
- `DataRequirement` composition via `merge_requirements()` rather than subclass-per-framework
- SQLAlchemy ORM models: appropriate use of inheritance via `Base` class — declarative pattern; not business logic
- Pydantic models: similar — appropriate inheritance for the validation framework's purpose
