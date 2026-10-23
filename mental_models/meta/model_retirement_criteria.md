---
slug: model_retirement_criteria
name: Model Retirement Criteria (Meta)
school: adr_024
citation_tier: "★★"
always_load: false
related_models:
  - man_with_hammer_warning
  - sunk_cost
  - opportunity_cost
  - circle_of_competence
code_consequences:
  - ADR-024 §1.6 mandates annual review of every model file (`last_reviewed` >12 months → flagged for retire-or-update)
  - Models with empty `code_consequences` are rejected at write time (schema enforcement)
  - Models that haven't changed any framework / overlay / test / output decision in 12 months are retire candidates
  - '`_gaps.md` "Retired models" section logs retirements with rationale — preserves audit trail'
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Model Retirement Criteria (Meta)

> A model that hasn't earned its tokens in 12 months should be retired or substantially updated. The lattice is a graph; dead nodes degrade the whole structure.

## Summary

Mental-model libraries can grow without bound, becoming repositories of philosophical aphorisms with no operational teeth. The discipline is the inverse: every model must justify its continued presence by changing some framework / overlay / test / output decision. Models that don't are decorative; they consume token budget in the composer's prompt without contributing to verdicts.

## When to apply

- Annual review (ADR-024 §1.6) — every model with `last_reviewed` >12 months gets evaluated
- Every PR that adds a new model — what specifically does this change? If `code_consequences` is empty, defer
- Composer-output review — which models in the lattice never appear in the narrative LLM's reasoning chains? Candidates for retirement
- Cross-domain audit — is one school over-represented in the lattice without producing differential signal?

## Retirement criteria

A model qualifies for retirement review when ANY of:

1. **Empty operational consequences**: `code_consequences` field references nothing in the actual codebase, or only references things that don't exist anymore
2. **Subsumed**: another model in the lattice covers the same territory more rigorously
3. **Stale citation tier**: a `★★★` claim is no longer supported by current empirical literature
4. **Superseded by ADR**: a project decision (new ADR) makes the model's claim obsolete or contradicted
5. **Decorative quote**: model text is interesting but doesn't constrain any decision the system makes

## Inversion form

What does retirement-discipline-failure cost? Lattice bloat without removal. Every addition gets celebrated; nothing ever gets retired. The library degrades into noise; the composer's prompt fills with low-signal content; the narrative LLM's reasoning quality drops because channel capacity is saturated. Munger's man-with-hammer applies recursively — but so does Knight's law of large libraries: bigger isn't better when no quality bar is enforced.

## Antipatterns

- Keeping a model because "it's in there now and removing it feels destructive"
- Retirement-by-deletion without logging in `_gaps.md` (loses audit trail; future agent re-derives the same model)
- Retiring multiple models in one batch (mixed concerns; can't trace which retirement caused which downstream effect)
- Treating retirement as failure of the original author rather than as natural lattice evolution

## Examples in this codebase

- ADR-024 §1.6 sets the structural enforcement — annual review marker, `code_consequences` mandatory, ≥2 `related_models` mandatory
- `_gaps.md` has dedicated "Retired models" section — currently empty (annual review begins 2027-05) but the structure is in place
- `sunk_cost` model itself is the cross-link defence — applies recursively to mental-model retention
- Counter-example to watch for: any model file where `code_consequences` is generic ("informs reasoning") rather than specific ("F1 P3 signal applies this; ICA-5 trigger keys off this") — early signal of decorative drift
