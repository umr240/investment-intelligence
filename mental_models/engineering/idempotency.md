---
slug: idempotency
name: Idempotency
school: helland_distributed_systems
citation_tier: "★★★"
always_load: true
related_models:
  - single_source_of_truth
  - illegal_states_unrepresentable
  - fail_fast
  - two_hard_things
  - failure_mode_analysis
code_consequences:
  - "`--force` re-parse of a filing must produce the SAME Financial rows, not duplicates or drift — re-running is safe by construction, not by luck"
  - Financial rows keyed (company_id, fiscal_year, period) with UNIQUE — the constraint is what MAKES the ingest idempotent; an upsert, not an insert
  - FinancialSourceLog accession-keyed "never invalidate, just append" — re-fetching the same accession is a no-op, not a double-count
  - Scheduler retries (APScheduler) on a failed ticker must be safe to run twice — a partial run that half-wrote rows must not corrupt on retry
token_cost_estimate: 200
version: 1.0
added: 2026-06-07
last_reviewed: 2026-06-07
---

# Idempotency

> Pat Helland: running an operation twice should leave the system in the same state as running it once. In any pipeline with retries, caches, or re-runs, non-idempotent writes are silent corruption waiting for a retry.

## Summary

An operation is idempotent if applying it N times has the same effect as applying it once. This is the unspoken assumption that holds a fetch→parse→persist pipeline together: the moment a network call can be retried, a scheduler can re-run, or a user can type `--force`, every write path must be safe to execute more than once. The danger is not the crash — it's the *successful retry* that double-applies. This is the write-path sibling of `single_source_of_truth`: SSoT says "one canonical value"; idempotency says "the operation that produces it can run twice without producing two." Where `illegal_states_unrepresentable` makes a bad write *unconstructable* at the type level, idempotency makes a *repeated* write harmless at the storage level — same goal (the bad write can't happen), two different layers.

## When to apply

- Every persist path — if this runs twice (retry, `--force`, manual re-trigger), do I get one row or two?
- Every external fetch + write — is the write keyed such that a re-fetch upserts, or does it append?
- Every scheduler/queue task — partial completion + retry is the *normal* case, not the edge case; is the half-done state safe to resume over?
- Every "increment" or "append" — these are the classic non-idempotent operations; can a retry double them?

## When NOT to over-apply

- Genuinely append-only immutable logs (filings are immutable; `FinancialSourceLog` append is *correct* because the same accession appended twice is detectable and deduped on read, not because append is inherently safe)
- Forcing idempotency keys onto operations that are naturally pure reads — overhead with no failure mode to defend against

## Inversion form

What does non-idempotent writes cost? Silent double-counting that survives type checks and lint. A retry after a transient SEC timeout re-runs the parse; without the UNIQUE constraint upserting, you now have two `Financial` rows for the same period — `max(fiscal_year)` still looks right, the totals are quietly doubled, and the corruption surfaces three frameworks downstream as an impossible revenue figure. This is the HIMS-class failure (silent semantic corruption → wrong verdict) but triggered by retry rather than by alias-matching. The crash you can see is a gift; the successful-but-doubled retry is the rule.

## Antipatterns

- `INSERT` where the contract needs `UPSERT` / `INSERT ... ON CONFLICT`
- Counters or running totals mutated in place by a retryable task
- "Re-running the dive is probably fine" without a UNIQUE constraint or idempotency key proving it
- Cache-fill operations that aren't safe to interrupt and resume (partial write left in a non-resumable state)
- Treating idempotency as a database concern only — the parse step that assigns IDs must also be deterministic

## Examples in this codebase

- `Financial` UNIQUE (company_id, fiscal_year, period) — the constraint is the idempotency guarantee; `--force` re-parse upserts the same key, never duplicates
- `FinancialSourceLog` accession-keyed — re-fetching an already-logged accession is a detectable no-op
- The HIMS `--force` re-fetch (cited in `verify_with_tests`) only worked safely *because* the re-parse was idempotent over the period key — worth making that guarantee explicit rather than incidental
- Counter-example to watch for: any future scheduler task that does read-modify-write on an aggregate (e.g. a "total companies screened" counter) — a retry double-counts unless the write is keyed or idempotent
