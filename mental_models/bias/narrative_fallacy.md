---
slug: narrative_fallacy
name: Narrative Fallacy
school: taleb
citation_tier: "★★"
always_load: true
related_models:
  - confirmation_bias
  - first_principles
  - probabilistic_thinking
  - circle_of_competence
code_consequences:
  - LLM narrative output is constrained by ADR-023 — anti-hallucination lint, mandatory data_gaps echo, forbidden sell-side prose all defend against narrative fallacy at the output layer
  - Frameworks compute deterministically from primitives — narrative is the synthesis layer, not the data layer
  - Methodology disclosure (ADR-022) declares the analysis path, defending against post-hoc narrative reconstruction
  - F4 framework rewards costly signals over narrative-rich signals — defence against management-narrative-driven verdicts
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Narrative Fallacy

> Coherent stories feel more true than incoherent ones. Markets reward storytellers; analysts must defend against the same incentive.

## Summary

Nassim Taleb's term for the human tendency to construct retrospective explanations that make randomness feel inevitable, and to over-weight evidence that fits a narrative we've already constructed. 10-K narratives are written to be coherent; they may be coherent without being accurate. Analyst write-ups face the same pressure: a fluent story is more compelling than honest uncertainty.

## When to apply

- Reading 10-K narrative sections (MD&A, risk factors) — fluent prose can pave over real risks
- Writing dive narratives — does the prose feel "too clean"? Often that means real complexity has been smoothed
- Listening to earnings calls — management narratives are constructed for coherence, not accuracy
- Cross-checking analyst reports — coherent thesis isn't necessarily true thesis

## Inversion form

The over-corrective stance: refusing all narrative entirely. Some narrative is necessary to communicate analysis. Defence: the discipline is *constrained* narrative — narrative grounded in cited numbers, anchored against base rates, paired with explicit inversion.

## Antipatterns

- Fluent dive prose without `data_gaps[]` echoed verbatim
- Management's MD&A narrative accepted as factual context
- Analyst-call commentary treated as input rather than as marketing
- Single-narrative analysis without competing narratives explicitly considered

## Examples in this codebase

- ADR-023 §1.6 anti-hallucination lint — every numerical claim must round-trip to scorecard JSON
- ADR-023 §1.4 §7 data_gaps echoed verbatim — narrative cannot smooth over what's unknown
- ADR-023 §1.3 Block 4 — voice constraints (no hedging adverbs, no sell-side prose) — defends against fluent storytelling
- Methodology disclosure (Stage 0c) — declares the analysis path explicitly, defending against post-hoc narrative reconstruction
