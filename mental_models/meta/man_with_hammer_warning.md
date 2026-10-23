---
slug: man_with_hammer_warning
name: Man with a Hammer Warning (Meta)
school: munger_meta
citation_tier: "◯"
always_load: true
related_models:
  - lollapalooza_alignment_detector
  - circle_of_competence
  - opportunity_cost
  - inversion
code_consequences:
  - ADR-024 §1.6 anti-bloat protections defend against single-model dominance in the lattice itself
  - Composite scoring caps prevent any single framework from dominating the verdict — system-level man-with-hammer defence
  - Annual mental-model review (ADR-024 §1.6) catches over-applied models that have stopped earning their tokens
  - Model retirement criteria — models that fire on every dive without producing differential signal should be reviewed
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Man with a Hammer Warning (Meta)

> *"To a man with a hammer, every problem looks like a nail."* — Abraham Maslow / Munger. Self-referential to the lattice: when one model becomes the favoured tool, every situation gets framed through it whether it fits or not.

## Summary

The lattice's own success creates this risk. Once `inversion` produces good outputs, every situation gets the inversion treatment; once `peters_taylor_intangible_capital` becomes the methodology, every company gets capitalised; once `outsiders_eight_traits` becomes the lens, every CEO gets graded on it regardless of relevance. Munger's man-with-hammer warning applies recursively to the mental-model library — over-application of a favourite model is itself a failure mode.

## When to apply

- Every dive where one model seems to be doing all the analytical work
- Every cross-framework conviction that traces back to a single-domain anchor
- Mental-model PR review — does the new model add diversity, or is it another instance of an over-represented school?
- Annual lattice review — which models have fired on every dive without producing differential signal?

## Inversion form

What does the over-corrective stance look like? Suppressing the use of well-fitting models because they're "favourite" — equally wrong. The discipline is *appropriateness checking*, not *favouritism avoidance*. Some models genuinely apply universally (inversion, owner-operator stance, falsifiability); others are situational (Peters-Taylor for intangible-heavy; PSA for spinoffs). The hammer warning applies to model selection, not model quality.

## Antipatterns

- Applying Peters-Taylor to companies where R&D and SG&A are immaterial (man with capitalisation hammer)
- Applying Outsiders to founder-CEOs at companies where management isn't the limiting factor (man with capital-allocation hammer)
- Applying ICA-5 to every dive where GAAP and non-GAAP differ regardless of magnitude (correctly avoided by the 3pp threshold)
- Adding more models to handle edge cases when a single model is being misapplied — the bloat-by-misapplication failure

## Examples in this codebase

- ADR-024 §1.6 mandatory `code_consequences` field — defends against decorative models that just over-apply existing framing
- Composite caps + bounded overlay bonuses — system-level defence against single-framework dominance
- AMBA dive: F7 strong_fit (cheap) was deliberately not allowed to drive the composite — the value-trap pattern recognition required NOT applying the cheapness hammer
- Per `_gaps.md`: refinements within already-dense domains (statistical, bias) are likely to introduce man-with-hammer risk because the school is over-represented; meta-domain diversification is preferred
