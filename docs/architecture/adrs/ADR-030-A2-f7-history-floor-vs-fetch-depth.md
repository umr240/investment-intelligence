# ADR-030 Amendment A2 — F7's history floor is unreachable at the default fetch depth

**Status**: ACCEPTED (2026-08-23) — Option A: raise fetch depth, keep the floor
**Amends**: ADR-030-A1 (F7 regime gate), §"MIN_HISTORY_YEARS rises from 5 to 10"
**Date**: 2026-08-23
**Decision-maker**: Umar

---

## 1. The open question A1 deferred

A1 §171 raised `MIN_HISTORY_YEARS` from 5 to 10 and explicitly left one question
unresolved:

> "Raising the floor to 10yr matches the spec. | Does F7 then ever run? | Rarely,
> on this universe. If F7 is almost never feasible, that is an argument about
> whether F7 belongs in the composite at all — surfaced, not resolved here."

This amendment answers it. The answer is not about F7's merit.

## 2. Measured cause — a fetch-depth artifact, not company age

Annual-row coverage across the 6,518 companies holding any annual data:

| Floor | Companies eligible | Share |
|---|---|---|
| ≥ 5yr | 5,264 | 80.8% |
| ≥ 9yr | 3,625 | 55.6% |
| **≥ 10yr** | **1,245** | **19.1%** |
| ≥ 11yr | 23 | 0.4% |
| ≥ 12yr | 7 | 0.1% |

A 66% cliff between 9 and 10, and effectively nothing beyond 10. Company ages are
not distributed this way. The cause is that `data/pipeline.py:56` defaults to
`years=10` while `MIN_HISTORY_YEARS=10`: fetch depth **equals** the strictest
framework floor, so ordinary filing-date timing leaves most companies one row
short. `cli/main.py:2377` claims "default 10 covers all frameworks"; it does not
cover F7.

Worked example — CSGP (CoStar Group), listed **1998-07-01**, 27 years available at
EDGAR. Stored annual years: 2017-2025 (9). F7 unfeasible. Nothing about this
company is short of history; the fetch window is.

## 3. Decision

1. Raise the default annual fetch depth from **10 to 12** years
   (`data/pipeline.py`, `cli/main.py` `--years`). Two years of headroom above the
   strictest floor absorbs filing-date drift.
2. Keep `MIN_HISTORY_YEARS = 10`. A1's statistical reasoning stands: a z-score
   over 5 observations has a standard error wide enough that the resulting
   verdict is close to noise, and A1's regime gate mitigates a *different*
   failure (business-model change mid-window), not small-n.
3. Correct the `--years` help text.
4. Backfill by **re-parsing existing cached payloads**, not refetching:
   `.ii_cache.db` already holds full `companyfacts` JSON (10 GB across 5,841
   companies) covering all years. Widening `keep_only_years` costs zero SEC
   calls.

## 4. Rejected alternative — lower the floor to 5

Restores 80.8% coverage immediately and needs no backfill. Rejected because it
buys coverage by weakening the statistic rather than by fixing the pipeline that
caused the shortfall, and it re-opens precisely the failure A1 documented
(BONEX.ST scoring STRONG FIT off 6 datapoints spanning a −54.5% → +23.6% margin
transition). The floor was never the reason F7 does not run.

If coverage is later judged to outweigh rigour, the honest form is a
**confidence tier** — run F7 at 5-9 years, label it low-n, and cap its composite
weight further — not a silent floor change. That remains a separate decision.

## 5. Consequences

- F7 becomes feasible for a large share of the ~3,625 companies currently at
  9 years, once re-parsed. Exact count is measurable only after backfill.
- Storage grows by roughly two annual rows per company (~13k rows), negligible
  against the existing 198,882.
- Composite scores change for any company where F7 moves from unfeasible to
  scored, because mode-C weights stop being renormalised. This is a visible,
  intended change and should be re-verified on a known ticker before the
  backfill is run at universe scale.
- No new API calls. No new secrets. No LLM involvement.

## 6. Anti-patterns this amendment forbids

- Setting fetch depth equal to any framework's floor. Depth must exceed the
  strictest floor.
- Reporting a history shortfall as "recent IPO" without checking the listing
  date (fixed separately; CSGP, listed 1998, was reported as a recent IPO).
- Declaring `DATA_REQUIREMENT.annual_years` below an enforced
  `MIN_HISTORY_YEARS`. Now covered by
  `tests/test_frameworks/test_history_contract.py`.

---

*ADR-030-A2 | accepted 2026-08-23 | evidence measured against the live DB, not estimated.*

Implemented as `config.constants.DEFAULT_HISTORY_YEARS = 12`, referenced by
`data/pipeline.py`, `data/edgar_fetcher.py`, `frameworks/base.py`, `cli/main.py`
and the orchestrator's auto-extend — which previously extended to exactly 10,
reproducing the same off-by-one it was meant to repair.
