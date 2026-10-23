---
slug: redundancy
name: Redundancy (Belt-and-Braces)
school: reliability_engineering
citation_tier: "★★"
always_load: true
related_models:
  - margin_of_safety
  - defense_in_depth
  - failure_mode_analysis
  - first_principles
code_consequences:
  - Multi-framework agreement required for high-conviction labelling — single-framework signal is suggestive only
  - Multi-source corroboration required for verdict-shaping numbers — EDGAR + yfinance + 10-K text
  - Composite caps + bounded overlay bonuses — no single signal can drive a verdict
  - data_gaps[] preferred over inferred values — redundancy doesn't paper over absences
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Redundancy (Belt-and-Braces)

> Belt and braces is a feature, not over-engineering. Two independent failures must align before a wrong verdict.

## Summary

Reliability principle: critical systems require multiple independent paths to success such that any single failure cannot produce a wrong outcome. Applied to investment analysis: any verdict-shaping conclusion must rest on multiple independent corroborating signals, not on the strongest single signal.

## When to apply

- Every high-conviction verdict — three frameworks aligning is conviction; one framework strong is suggestive
- Every verdict-shaping number — corroborate via at least two sources
- Every framework signal — pair level with derivative, point estimate with margin of safety
- Every overlay — the overlay's signal must be independent of the framework's signal it supplements

## Inversion form

The redundancy-as-noise failure: stacking correlated signals and treating them as independent. Three valuation metrics (P/E + P/B + EV/EBITDA) all signalling cheap is ONE signal, not three. Defence: independence is empirical, not assumed; check what the signals actually correlate with.

## Antipatterns

- Single-framework strong_fit treated as conviction without cross-framework agreement
- "Three indicators agree" when all three are valuation multiples (one independent signal, three views)
- Single-source numbers driving verdicts (no corroboration)
- Inferred values backfilling redundancy gaps ("source A says X, source B says Y, the truth is probably between them")

## Examples in this codebase

- Composite scoring requires multi-framework agreement for high-conviction labels
- ADR-022 mandates source-of-record per metric — corroboration is auditable, not assumed
- TOTAL_OVERLAY_BONUS_CAP=1.0 — overlay redundancy bounded so no overlay group dominates
- F4 stealth framework requires short_interest + 13F + EPS_acceleration alignment — three independent signals
