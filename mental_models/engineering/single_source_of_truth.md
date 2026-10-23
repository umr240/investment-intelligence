---
slug: single_source_of_truth
name: Single Source of Truth
school: standard
citation_tier: "★★★"
always_load: true
related_models:
  - boundaries_hexagonal
  - illegal_states_unrepresentable
  - parse_dont_validate
  - failure_mode_analysis
  - idempotency
code_consequences:
  - Financial rows keyed (company_id, fiscal_year, period) with UNIQUE constraint — one canonical row per period; no duplicates allowed
  - FinancialSourceLog tracks accession-number provenance — each row knows which filing produced it
  - Mental-model lattice: one file per model in mental_models/; CLAUDE.md is the index, not a duplicate of the content (ADR-024)
  - ADR-022 source-provenance discipline — every metric has one declared source, not multiple competing values
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Single Source of Truth

> Each piece of state lives in exactly one place. Duplication = inconsistency = bugs. The bug-finding question for any system: where does this value get computed, and is there exactly one such place?

## Summary

When the same fact has multiple representations in a system, those representations will diverge over time. Bugs that arise from this divergence are particularly hard to debug because no single value is "wrong" — each is internally consistent within its source. The discipline is one canonical store; everything else is a derivation or a cache with explicit invalidation.

## When to apply

- Every persisted fact — where is its canonical home?
- Every cached value — what's the invalidation rule? Is the cache provably consistent with the source?
- Every derived metric — is it computed once and stored, or computed each time? Either is fine; both is a bug.
- Every documentation — does the doc duplicate code, or does it reference the code? (Duplicating produces drift)

## Inversion form

What does duplicating state cost? Sync logic, eventual divergence, debugging hell. Two copies of "what's the latest fiscal year for this company?" — one in `Company.last_fiscal_year`, one derived from `max(Financial.fiscal_year)` — drift the moment a parser updates one path but not the other. The bug surfaces as a coverage gap five months later.

## Antipatterns

- Same value persisted in two columns "for convenience"
- Documentation that duplicates code-level facts ("framework F1 needs 2 years of data") — drifts when DataRequirement changes
- Caches without explicit invalidation rules
- Mental-model content duplicated between CLAUDE.md and `mental_models/` files

## Examples in this codebase

- `Financial` rows keyed `(company_id, fiscal_year, period)` with UNIQUE — one row per period
- `FinancialSourceLog` tracks accession provenance — single source of "which filing produced this row"
- ADR-024 mental-model library — content lives in `mental_models/` files; CLAUDE.md indexes, doesn't duplicate
- ADR-022 methodology disclosure — every metric declares its single source; no value is derived from "average of multiple sources"
- Counter-example to watch for: `Company.market_cap_usd` and `yfinance.info['marketCap']` — both should reflect the same fact; the warehouse value is canonical, the live snapshot is a refreshable cache
