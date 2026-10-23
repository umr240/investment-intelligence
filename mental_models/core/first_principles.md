---
slug: first_principles
name: First Principles
school: aristotle_feynman
citation_tier: "◯"
always_load: true
related_models:
  - circle_of_competence
  - inversion
  - second_order_thinking
code_consequences:
  - Frameworks compute from raw EDGAR XBRL where possible; never depend on third-party calculated fields without source verification
  - Peters-Taylor (ADR-021) reconstructs invested capital from primitives; rejects management non-GAAP add-backs
  - Methodology disclosure (ADR-022) declares the source of every metric so derivations are auditable
  - F7 disclaimer required because the framework is contested at the empirical level, not just the methodology level
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# First Principles

> Derive from primitives — accounting + unit economics + customer behaviour — not from sector narratives, analyst consensus, or platform-derived aggregates.

## Summary

When a calculation is needed, build it from raw inputs whose provenance you control. Borrowed numbers carry the borrowing platform's methodology assumptions, which silently propagate into your conclusions.

## When to apply

- Every metric used in framework scoring — derive from `Financial` row primitives where possible
- Cross-platform validation — TradingView/Yahoo numbers differ because they apply different methodology layers
- Non-GAAP adjustments — capitalise R&D + 25% SG&A from primitives (Peters-Taylor); never use management's "non-GAAP" headline number
- Cost-of-capital, ROIC, FCF — all derivable from XBRL primitives; don't trust pre-computed values

## Inversion form

The "consensus number" trap: deferring to FactSet / Bloomberg / sell-side aggregates because they "must be right." They reflect *their* methodology choices, not necessarily yours. Defence: every borrowed number must declare its source AND its methodology.

## Antipatterns

- Pulling a "non-GAAP EPS" from a third-party feed and treating it as comparable to a GAAP EPS from another source
- Using analyst consensus as a data point rather than an input signal
- Computing ROIC by accepting platform-derived NOPAT without verifying the add-back list
- Trusting "operating cash flow" without confirming whether SBC is reflected the way you think

## Examples in this codebase

- `data/edgar_companyfacts.py` — every Financial row materialised from raw XBRL facts; no platform aggregates
- `screener/tasks/fundamentals.py:compute_pt_adjusted_full` — capitalisation built from primitives (R&D, SG&A series)
- `cli/main.py:_render_roic_summary` — declares formula explicitly: GAAP ROIC = NetIncome / (Equity + Debt)
- ADR-021 §4.1 — rejects management non-GAAP because it isn't first-principles
