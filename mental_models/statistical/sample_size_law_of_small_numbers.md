---
slug: sample_size_law_of_small_numbers
name: Law of Small Numbers
school: kahneman_tversky
citation_tier: "★★★"
always_load: true
related_models:
  - probabilistic_thinking
  - regression_to_mean
  - base_rate_fallacy
  - circle_of_competence
code_consequences:
  - F7 requires ≥5 years of history (cross-cycle context); InsufficientHistoryError raised when sample is too small
  - Tier 1 ROIC volatility filter requires multi-year history — single-year strength insufficient
  - Recent-IPO graceful degradation marks F2/F7 unfeasible rather than fabricating thin-sample z-scores
  - DCF cost-structure regression requires R² ≥ 0.70 — guards against thin-sample false fits
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Law of Small Numbers

> Small samples produce extreme outcomes more often than intuition expects. Treat thin data with thin confidence.

## Summary

Kahneman-Tversky's term for the human tendency to draw confident conclusions from small samples. Variance is high in small samples; observed extremes are common, not informative. Five quarters of revenue isn't a trend; one good year isn't a moat; two analyst upgrades aren't a consensus shift.

## When to apply

- Every recent-IPO analysis — z-scores on <5 years of history are noise
- Every "year-over-year improving" claim with only 2 years
- Every framework with high parameter count relative to data points (DCF cost structure regressions)
- Cross-checking sector inferences from <30 companies

## Inversion form

The over-corrective stance: refusing to act on any signal because samples are always finite. The discipline is calibration: weight conclusions by sample size, declare confidence intervals, accept that "I don't know yet" is a valid output.

## Antipatterns

- Fitting an n=3 trend line and treating it as a forecast
- Comparing two quarters and calling the difference "improvement"
- Building DCF on 2 years of cost data and treating the regression as predictive
- Recent-IPO frameworks computing z-scores on <5 fiscal periods

## Examples in this codebase

- F7 minimum 5-year history requirement in `frameworks/f7_smart_beta.py` — explicit thin-sample guard
- DCF analyzer R² ≥ 0.70 filter in `dcf_analyzer.py` — guards against thin-sample regression artifacts
- `frameworks/base.py:InsufficientHistoryError` raised rather than fabricating z-scores
- HIMS F7 unfeasible due to insufficient history (only 2 years of joined Financial × PriceHistory) — correct application of thin-sample discipline
