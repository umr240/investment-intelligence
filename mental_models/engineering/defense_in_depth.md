---
slug: defense_in_depth
name: Defence in Depth
school: security_reliability
citation_tier: "★★"
always_load: true
related_models:
  - redundancy
  - failure_mode_analysis
  - margin_of_safety
  - blast_radius
code_consequences:
  - Multiple frameworks must agree before high-conviction labelling — defence layer 1 (single framework) backed by layers 2+ (other frameworks) and layer 3 (overlays)
  - ADR-022 methodology disclosure + ADR-023 narrative anti-hallucination lint — paired defences against bad output
  - data_gaps[] + InsufficientHistoryError + bounded overlay bonus = three layers preventing fabricated verdict
  - Bias models in `bias/` are guardrails on top of framework signals — defence layered on top of analysis
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Defence in Depth

> Don't rely on any single defence. Layer them so a single failure doesn't produce a wrong outcome.

## Summary

Security principle: protect against failure with multiple independent layers, each of which must individually fail before a bad outcome occurs. Applied to investment analysis: every verdict passes through framework signals → cross-framework agreement → overlay corroboration → bias guardrails → output anti-hallucination lint.

## When to apply

- Every architectural decision — what's the defensive layer if this layer fails?
- Every output safeguard — single check is brittle; layered checks are robust
- Every bias defence — confirmation bias defence is one layer; redundancy + multi-source + capped composite are additional layers
- Every methodology disclosure — Stage 0c panel + ICA-5 self-audit + ADR-022 anti-pattern list = layered

## Inversion form

The over-corrective stance: layering so many checks that the system can't ship verdicts (analysis paralysis). The discipline is *graduated* layering — fast cheap layers run first; expensive deep layers run only when fast layers don't terminate.

## Antipatterns

- Single-layer defences ("the lint catches it" without redundant checks)
- Layers that aren't independent (all checks rely on the same input data)
- Defence layers without a clear failure-mode each defends against
- Treating defence-in-depth as "more checks = better" rather than "independent checks at each level"

## Examples in this codebase

- Verdict path: framework score → cross-framework agreement → overlay bonus → bias guardrails → output lint (5 layers)
- ADR-022 (methodology disclosure) + ADR-023 (narrative contract) + ADR-024 (mental-model schema) — three architectural layers governing the same analytical output
- F1 disqualifications (CGS top-decile asset growth) + F4 inversions (smart-money absence) + F5 ROIC floor — multiple disqualifying paths, any one of which prevents high-conviction
- Anti-hallucination: prompt-level constraint + numerical round-trip lint + data_gaps echo discipline = three layers
