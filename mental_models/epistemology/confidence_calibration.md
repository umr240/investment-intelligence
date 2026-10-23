---
slug: confidence_calibration
name: Confidence Calibration
school: tetlock
citation_tier: "★★★"
always_load: true
related_models:
  - probabilistic_thinking
  - circle_of_competence
  - epistemic_humility_unknown_unknowns
  - bayesian_updating
code_consequences:
  - Verdicts are graduated (WATCHLIST WITH TRIGGERS / EXCLUDE WITH REASON / RESEARCH-ONLY) — not binary BUY/SELL — captures graded confidence
  - F1-F7 produce float scores 0-10, not binary pass/fail — calibrated graded outputs
  - data_gaps[] surface uncertainty — over-confident output structurally prevented when inputs incomplete
  - ADR-023 §1.3 Block 2 mandates probabilistic vocabulary in narrative — explicit calibration requirement
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Confidence Calibration

> A 90%-confident forecast should be right ~90% of the time. Most forecasters are over-confident; the discipline is matching stated confidence to actual hit rate.

## Summary

Philip Tetlock's empirical research: most forecasters are systematically over-confident. A well-calibrated forecaster's stated probabilities match observed frequencies. Translated to investment analysis: every verdict, every framework strong_fit, every "high conviction" label should be auditable against actual outcome distributions.

## When to apply

- Every "high conviction" verdict — what's the implied confidence, and is the system's track record at this confidence level matching?
- DCF intrinsic-value claims — point estimates are the maximum-confidence output; intervals are honestly-calibrated
- Single-framework strong_fit — what's the historical hit rate when this framework alone produces strong_fit?
- Cross-framework agreement — calibration improves as agreement increases (Lollapalooza)

## Inversion form

Over-correction toward eternal hedging: refusing any high-confidence output even when the evidence justifies it. Defence: track outcomes. If your "high conviction" verdicts are right 80% of the time, you're calibrated; if they're right 50%, you're over-confident.

## Antipatterns

- Stating verdicts as binary (right/wrong) when the evidence supports a probability
- Over-precise point estimates (DCF intrinsic value of $X.XX) without confidence intervals
- "I'm 99% sure" without empirical track-record support
- Treating "I don't know" as failure rather than calibrated honesty

## Examples in this codebase

- Composite is a graduated 0-10 score, not a binary verdict — naturally calibration-friendly
- ADR-023 §1.3 Block 2 mandates base-rate citation — anchors confidence to empirical reference
- Verdict vocabulary (WATCHLIST WITH TRIGGERS / EXCLUDE / RESEARCH-ONLY) prevents binary over-confidence
- DeepDiveRun history persistence (Phase 6.1+) supports outcome-vs-prediction calibration tracking
