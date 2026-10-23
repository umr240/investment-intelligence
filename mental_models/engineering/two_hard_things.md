---
slug: two_hard_things
name: Two Hard Things (Karlton)
school: karlton
citation_tier: "★★★"
always_load: true
related_models:
  - single_source_of_truth
  - code_read_more_than_written
  - parse_dont_validate
  - failure_mode_analysis
code_consequences:
  - Cache TTLs explicitly chosen and documented (24h fundamentals, 6h yfinance .info, 1h prices) — invalidation strategy is per-source
  - Cache key construction deterministic (accession_number for filings, ticker+date for prices) — no implicit invalidation rules
  - Naming conventions enforced: snake_case for fields/functions; framework slugs `f1`-`f7`; mental-model slugs descriptive not abbreviated
  - Schema column names match the analytical concept they store (revenue, total_debt, gross_margin) — no abbreviations like rev, td, gm
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Two Hard Things (Karlton)

> *"There are only two hard things in Computer Science: cache invalidation and naming things."* — Phil Karlton. Both bite hardest when ignored.

## Summary

The aphorism captures two underestimated discipline problems. **Cache invalidation**: getting wrong by quietly serving stale data, which produces silently-wrong outputs (especially dangerous in analytical systems where stale data → stale verdicts → real-world action). **Naming**: makes future code unreadable, which compounds across every reader (including future-you, including AI agents reading the code).

## When to apply

- Every cache decision — what's the TTL, what's the invalidation event, what's the key?
- Every variable / function / module name — does it tell the reader what this *is*, not what it does mechanically?
- Every schema column — name reflects analytical concept, not internal implementation
- Every "let me just add a cache here" — explicit invalidation rule mandatory

## Inversion form

**Cache wrong**: stale-data verdicts that look right because they pass type checks and lint. The system reports a moat-direction-widening signal based on data three months stale; the moat actually narrowed during the gap. **Naming wrong**: future-you (or an AI agent) reading code as if it's a stranger's, slowly. Every read costs cycles; every wrong inference costs a bug.

## Antipatterns

- Cache without explicit TTL or invalidation rule
- Cache keyed on something that drifts (e.g., user object identity rather than user_id)
- Variable names like `data`, `result`, `tmp`, `info` — meaning depends on context the reader has to reconstruct
- Mechanical names: `get_data()` vs analytical names: `fetch_latest_annual_filing()`

## Examples in this codebase

- `data/cache/manager.py` — explicit TTL strategy (24h fundamentals, 6h yfinance .info, 1h prices)
- `FinancialSourceLog` — accession-keyed cache with implicit "never invalidate, just append" rule (filings are immutable)
- Schema column names: `revenue`, `operating_cash_flow`, `total_debt` — analytical concepts, not abbreviations
- Framework slugs: `f1_pre_discovery`, `f5_growth_quality`, `f6_platform` — descriptive purpose, not "framework1"
- Mental-model slugs: `parse_dont_validate`, `chestertons_fence`, `boundaries_hexagonal` — concept-level, not category-level
