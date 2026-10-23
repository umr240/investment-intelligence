---
slug: intersubjective_verification
name: Intersubjective Verification
school: popper
citation_tier: "★★"
always_load: true
related_models:
  - redundancy
  - first_principles
  - confirmation_bias
  - lollapalooza
code_consequences:
  - Multiple frameworks aligning required for high-conviction labelling — analytical equivalent of peer review
  - ADR-022 source-provenance discipline ensures other observers could re-derive the same numbers from the same SEC filings — intersubjectively verifiable
  - F1-F7 deterministic compute — given same inputs, any observer produces same outputs (intersubjective by construction)
  - Methodology disclosure (Stage 0c) makes every dive auditable against its own claims
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Intersubjective Verification

> A claim is more credible when independent observers reach the same conclusion via independent paths. Frameworks aligning ≈ peer review.

## Summary

Karl Popper's insight that scientific knowledge is intersubjective — not "objective" in some absolute sense, but agreed upon by independent observers using independent methods. Translated to investment analysis: a verdict that emerges from multiple independent frameworks via independent reasoning paths is more credible than one anchored on a single framework's strong signal.

## When to apply

- Every high-conviction verdict — does the conclusion survive when computed via different framework paths?
- Cross-source data verification — does EDGAR + yfinance + 10-K text triangulate?
- Methodology disclosure — is the analysis reproducible by another observer?
- LLM narrative output — anti-hallucination lint enforces intersubjective verification at the output layer

## Inversion form

The "single brilliant insight" trap: a thesis that depends on one observer's unique reading of the data is structurally fragile. Defence: theses that survive only when no one else looks at them are usually not thesis material.

## Antipatterns

- Single-framework verdicts treated as conclusive
- Single-source numerical claims
- Reasoning chains that depend on the analyst's idiosyncratic priors
- Methodology buried in footnotes rather than declared

## Examples in this codebase

- Multi-framework agreement requirement for high-conviction labelling
- ADR-022 source-provenance — every metric traceable to its source; reproducible by any auditor
- F1-F7 deterministic compute — given same SEC data, any deployment produces same scores
- Stage 0c methodology panel — declares the reasoning publicly so it can be checked
