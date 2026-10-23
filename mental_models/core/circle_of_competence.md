---
slug: circle_of_competence
name: Circle of Competence
school: buffett
citation_tier: "◯"
always_load: true
related_models:
  - inversion
  - margin_of_safety
  - opportunity_cost
  - epistemic_humility_unknown_unknowns
code_consequences:
  - data_gaps[] is a first-class output across every framework — "we don't know" is a valid system response
  - Frameworks declare DATA_REQUIREMENT explicitly so missing inputs surface as unfeasible, not silent zero
  - InsufficientHistoryError raised rather than fabricated z-scores (F7 on recent IPOs)
  - Methodology disclosure panel (Stage 0c, ADR-022) declares what we know AND what we don't
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Circle of Competence

> *"What counts is knowing what you don't know."* — Buffett

## Summary

State explicitly what is understood about a business and what is not. The size of the circle matters less than knowing where its boundary lies. Outside the circle, "I don't know" beats any synthesised guess.

## When to apply

- Before any high-conviction label — what would I need to know that I don't?
- During data refresh — distinguish "value missing" from "value zero"
- When evaluating a sector unfamiliar to the operator (biotech mechanism-of-action, complex banks, mining geology)
- In every framework's `data_gaps` accounting — the absence is a first-class signal

## Inversion form

The illusion of competence: smooth narrative prose that paves over gaps. The LLM in `narrative.py` is structurally vulnerable to this — its job is fluent prose. Defence: ADR-023 §1.4 §7 mandates `data_gaps` echoed verbatim in every dive output, with no paraphrasing.

## Antipatterns

- Treating `None` as `0` in derived metrics
- Smoothing over a gap with "approximately X" or "in line with sector"
- Extending into a sector without surfacing the unknown-unknowns
- "We have 2 years of data" treated as equivalent to "we have 10 years of data" in z-score-style frameworks

## Examples in this codebase

- `data/reader.py:CompanyDataReader` — returns explicit None for missing fields, never a synthesised default
- `frameworks/base.py:InsufficientHistoryError` — raised rather than fabricated when annual_years requirement unmet
- `cli/main.py:_render_dive_outcome` — `data_gaps` rendered as a first-class section
- ADR-022 §1.2 Stage 0c panel — methodology + sources declared explicitly so the reader can audit the circle
