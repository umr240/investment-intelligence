---
slug: lollapalooza_alignment_detector
name: Lollapalooza Alignment Detector (Meta)
school: munger_meta
citation_tier: "◯"
always_load: true
related_models:
  - lollapalooza
  - inversion
  - confidence_calibration
  - intersubjective_verification
code_consequences:
  - When ≥3 lattice models from different domains converge on the same verdict, conviction is materially higher than single-model alignment
  - ADR-023 §1.3 Block 2 mandates lattice-ordered reasoning — composer must surface alignment vs disagreement
  - Cross-framework decision matrix flags multi-framework agreement as Lollapalooza signal vs single-framework strong_fit
  - Future composer (Phase 6.1+) should explicitly score model-domain diversity in alignment, not just count
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Lollapalooza Alignment Detector (Meta)

> Meta-model: when multiple lattice models from *different domains* converge on the same conclusion, that's the empirical Lollapalooza signal — distinct from arithmetic count of agreeing models.

## Summary

The `core/lollapalooza` model captures the principle (multiple aligning forces produce non-linear outcomes). This meta-model captures the *detection* — how do we recognise lollapalooza alignment in lattice output as opposed to single-domain redundancy? Three valuation models agreeing is *one* signal in three voices; one valuation + one moat + one biology + one game-theory model agreeing is *four* independent voices.

## When to apply

- Every high-conviction verdict — count agreeing lattice models, weighted by domain diversity
- Every "everything points the same direction" feeling — verify the directions are independent, not correlated
- Cross-framework reconciliation — F1 + F4 alignment is one kind of signal; F1 + F4 + Outsiders + Peters-Taylor + Helmer is another
- Future composer design — domain-diversity weighting in selection rules

## Inversion form

What does naive count-based alignment cost? False conviction from correlated signals. Three Munger-lattice models agreeing on "this looks like a moat" is genuine alignment; three valuation multiples agreeing on "this is cheap" is one signal. The detector must recognise diversity, not count.

## Antipatterns

- Counting `bias/recency_bias` + `bias/anchoring_bias` + `bias/confirmation_bias` as 3-domain alignment (all bias domain — one voice)
- Treating same-school models as independent (Helmer + Munger-Dorsey moat are correlated — both moat-domain)
- Ignoring the inverse signal: when many lattice models DISAGREE, that's its own information about thesis fragility
- Adding agreeing models without checking they're not already in the prompt context (token-budget waste, no signal gain)

## Examples in this codebase

- INTA dive: F3 strong_fit + F6 partial-with-academic-anchors + ICA-5 upward + Peters-Taylor positive + GP/A 0.42 — multi-domain alignment (innovation + platform + valuation methodology + biology direction-beats-width) → genuine Lollapalooza
- HIMS dive: F2 fail + F4 fail + asset-growth +205% (CGS top-decile) + ICA-5 downward — multi-domain *negative* alignment → genuine inverse-Lollapalooza
- AMBA dive: F7 strong_fit (single-domain valuation) ALONE — count-based could mistake for conviction; this meta-model would correctly flag as single-domain noise
