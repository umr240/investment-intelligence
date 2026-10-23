---
slug: authority_bias
name: Authority Bias
school: cialdini_munger
citation_tier: "★★"
always_load: true
related_models:
  - first_principles
  - inversion
  - confirmation_bias
code_consequences:
  - Analyst price targets and consensus ratings are inputs (one signal among many), not data
  - F4 framework includes analyst-coverage count (Hong-Lim-Stein neglect premium) — under-coverage is a positive signal, not a negative
  - ADR-021 §0 explicitly rejected "build management non-GAAP because Bloomberg / FactSet do" — those are authority arguments, not first-principles arguments
  - Methodology disclosure (ADR-022) declares sources so reader can audit each authority claim
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Authority Bias

> Analyst price targets are inputs, not data. Treat as one signal among many.

## Summary

The tendency to weight conclusions from credentialed / institutional sources higher than the underlying evidence warrants. Includes sell-side analyst targets, ratings agency assessments, "Bloomberg consensus", and platform-aggregated non-GAAP numbers. The credential isn't the evidence.

## When to apply

- Every borrowed number — what's the source's methodology, and does it survive first-principles audit?
- Sell-side ratings — useful as sentiment signal, not as analytical input
- Platform aggregates (FactSet, Bloomberg, S&P CapIQ) — declare the methodology each applies; don't trust the headline
- "Consensus" estimates — directional only, not authoritative

## Inversion form

The under-weighting failure: rejecting institutional sources entirely because they're institutional. Sell-side analysts often have better access and deeper sector knowledge than retail. The defence is calibration, not rejection: weight by methodology audit, not by credential alone.

## Antipatterns

- Treating analyst targets as the basis for valuation
- Trusting platform-derived ratios without checking the platform's methodology
- "FactSet says X" treated as terminating the discussion
- Ignoring institutional research entirely as overcorrection

## Examples in this codebase

- F4 Stealth framework treats high analyst coverage as *negative* (vs neglect premium) — academic anchor (Hong-Lim-Stein) inverts authority bias structurally
- ADR-021 rejected the FactSet-style management non-GAAP path; first-principles Peters-Taylor capitalisation chosen instead
- ADR-022 Stage 0c declares the source for every metric — reader can audit authority claims
- `data/api/yfinance_client.py` analyst-consensus snapshot stored as raw count + recommendation, not weighted into composite
