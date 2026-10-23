# ADR-020 — Warden pattern for adaptive batched mid-run source fallback

| Field | Detail |
|---|---|
| **Status** | **Accepted (option b)** — per-chunk persist landed; warden remains parked as opt-in manual tooling |
| **Date** | 2026-05-08 (proposed and accepted same day) |
| **Extends** | ADR-017 (warehouse + per-filter task pattern) |
| **Tension with** | ADR-017 §4 — "no DAG engine, no orchestrator state, no task dependencies" |
| **Provenance** | User asked: "if Yahoo bans mid run, you should be fetching with alternatives, no? are we running the universe in batches or not? like a warden process?" — surfaced the gap that current `MetadataYFTask` runs all pending tickers single-shot with persist only at the end. User correctly flagged that the proposed warden contradicts ADR-017. |

---

## 1. The problem in one paragraph

`MetadataYFTask.select_pending` returns ALL pending tickers (potentially ~5,000 tickers at universe scale). The runner chunks at `TASK_CHUNK_SIZE=50` and runs `concurrency_override=1` chunks effectively sequentially. `task.persist` is called ONCE after all chunks complete. If the process crashes, gets OOM-killed, or is Ctrl+C'd mid-run, **everything in the not-yet-persisted FilterResult buffer is lost**. Additionally, when Yahoo's anti-abuse layer trips at ticker #1000 of #5000, the remaining 4,000 yfinance calls return empty and `MetadataPolygonTask` doesn't pick up the slack until the next cron tick — wasting hours of potential progress.

The user's instinct: "we need a warden". A supervisor that batches the work, commits between batches, monitors failure rate, switches to Polygon on detected ban, and cools off when the ban window is large.

---

## 2. What the proposed warden does (the parked draft)

`metadata_warden.py` (parked, not wired; archived):

1. Loops up to `max_batches` times. Each iteration:
   - Reads up to `batch_size` (default 200) pending tickers via `MetadataYFTask.select_pending`.
   - **Monkey-patches** `task.select_pending` to return only that slice for the current `run_task` call.
   - Runs the task → `run_task` calls persist → batch commits.
   - Optionally runs `MetadataPolygonTask` per batch as backfill (Polygon's own `select_pending` already filters `cap IS NULL`, so it picks up yfinance failures from the batch we just ran).
2. Tracks per-batch yfinance failure rate. If ≥ `MIN_BATCH_SAMPLE` attempts AND failure rate > `BAN_THRESHOLD` (50%), counts as a "high-failure batch".
3. After `CONSECUTIVE_BAN_BATCHES` (3) high-failure batches in a row, sleeps `cool_down_secs` (1 hour by default). Counter resets on a clean batch.

Result: a 5K-ticker fill that survives Yahoo bans, commits per batch (≤200 tickers lost on crash), and adaptively yields when banning is detected.

---

## 3. Where this contradicts ADR-017

ADR-017 §4 was explicit:

> **Total new abstractions**: 1 (the `FilterTask` Protocol).
> **Total new infrastructure**: 0.
>
> | Thing we considered | Did we build it? |
> |---|---|
> | DAG engine (Airflow, Dagster, Prefect) | NO — tasks are independent or run in cron-defined order |
> | Custom scheduler | NO — using the existing cron + `scheduler.jobs` |
> | Task dependencies / topological sort | NO — humans order tasks in the cron handler |
> | Custom retry framework | NO — try/except + asyncio.sleep |
> | State machine for tickers | NO — `*_fetched_at` columns ARE the state |

The warden violates several of these:

| Violation | What the warden does |
|---|---|
| **"No orchestrator state"** | `consecutive_bans` counter; `cool_down` timer; `high_failure_batches` total. State that lives across task invocations within one process. ADR-017 said `*_fetched_at` columns are the state. |
| **"Tasks are independent"** | Warden runs `MetadataPolygonTask` immediately after each `MetadataYFTask` batch as deliberate fallback. This is an implicit DAG: yf → pg, with the edge condition "yf left rows with cap=NULL". ADR-017 said tasks shouldn't know about each other. |
| **"`select_pending()` IS the queue"** | Warden monkey-patches `select_pending` per batch to return a slice. The protocol assumed each task computes its own pending set from the DB; bypassing it via runtime substitution is a code smell that the protocol doesn't sanction. |
| **"No custom retry framework"** | The warden's "3 strikes → 1hr cool-down" IS a custom retry framework, layered ON TOP of the runner's per-chunk retry. Two retry layers with different semantics. |

ADR-017 explicitly chose simplicity. The warden re-introduces the orchestrator complexity ADR-017 rejected.

---

## 4. Two questions worth answering before deciding

### 4.1 Is the underlying problem real?

**Yes.** Three concrete failure modes:

  - **Process crash mid-run** loses up to ~80 minutes of yfinance work because persist runs once at the end. Any fill on ~5K tickers is exposed.
  - **Yahoo bans mid-run** turn the remainder of the run into wasted calls (2-3 hours of the run produces nothing). Requires manual intervention or waiting for next cron.
  - **Polygon backfill timing** — currently fires only when `MetadataPolygonTask` runs in its own cron slot. There's no mid-run yf→pg handoff; gaps stay until the next nightly polygon job.

### 4.2 Is the warden the right fix?

**Maybe not.** It solves all three but at the cost of orchestrator complexity ADR-017 deliberately avoided. There are simpler alternatives that close some/most of the gap without the architectural debt.

---

## 5. Alternatives that don't violate ADR-017

### Alt A — Per-chunk persist in the runner (smallest deviation)

Modify `screener/tasks/runner.py:run_task` to call `task.persist(db, chunk_results)` after EACH chunk completes (instead of accumulating all chunks and persisting once at the end). 

**Pros**:
- Closes the process-crash window. Loses at most one chunk (50 tickers) instead of the full task.
- Inside the existing FilterTask protocol — no monkey-patching.
- Doesn't add cross-task awareness. yf still runs to completion or failure; pg still runs in its own cron slot.
- Tiny code change (~10 lines in the runner).

**Cons**:
- Doesn't handle Yahoo ban (the 4,000 wasted calls case). Mid-run pivot to Polygon still requires the warden or some other mechanism.
- Requires `task.persist` to be safe to call N times per `run_task` invocation. All current tasks already are (they UPSERT keyed by cik), but it's a contract change worth declaring.

**Verdict**: ✅ Strictly inside ADR-017. Recommended as the bare-minimum fix.

### Alt B — Cron-iteration relies on existing mechanisms

Run yfinance and Polygon as separate cron jobs (already do). Accept that yf failures get backfilled by Polygon on the *next cron tick*, not mid-run. Use shorter cron intervals (e.g. yfinance every 4 hours instead of nightly) to make the gap shorter.

**Pros**:
- Zero architectural change.
- Pure ADR-017 conformance.
- The 4,000-wasted-calls case still happens but is bounded by cron interval, not by 24h refresh_interval.

**Cons**:
- Process-crash still loses up to a full task's work (bounded by chunk size if Alt A is also done).
- yfinance ban detection still doesn't happen — task just keeps trying every cron tick until refresh_interval expires. Yahoo's anti-abuse layer might actively hold the ban longer if we keep trying.
- No adaptive cool-down. We could end up in a yfinance retry loop that keeps the ban active.

**Verdict**: ⚠️ Reasonable for low-stakes fills (small ticker sets, infrequent refreshes). Insufficient for the universe-fill scenario the user proposed.

### Alt C — A "control loop" inside `run_task` (deepest deviation)

Push the warden's adaptive logic INTO the task runner, so any task's `run_task` invocation does per-chunk persist AND per-chunk failure-rate sampling AND chunk-level circuit-breaker. The warden becomes a *property* of the runner, applicable to any task — not a sidecar script.

**Pros**:
- Same benefits as the warden, with no monkey-patching. The runner uses the existing `select_pending` once, then iterates chunks with per-chunk persist + circuit-break.
- Re-usable across all tasks (FundamentalsTask would benefit too — same crash-mid-run risk).

**Cons**:
- Definitively re-introduces orchestrator state. ADR-017 §9 explicitly catalogued this as "things we did NOT build".
- Cross-task fallback (yf→pg) STILL needs a separate mechanism.
- Big code change in core runner; affects every task that goes through it.

**Verdict**: ❌ Architectural drift. Don't do this without an explicit override of ADR-017.

### Alt D — Do nothing

Universe-fill scenario is rare. We accept the trade-offs.

**Verdict**: ⚠️ Acceptable if universe-fill is genuinely a "once a quarter" operation and we treat it as a long-running background job that humans monitor. Not acceptable if we want a one-command robust fill.

---

## 6. Which problem are we actually solving?

There are TWO conflated problems here. Calling them out separately changes the recommendation:

**Problem P1 — Process-crash mid-run**: bounded by how long persist accumulates results. Affects ALL tasks (FundamentalsTask too, not just metadata).

**Problem P2 — Yahoo ban mid-run**: specific to yfinance. Other sources (Polygon, SEC) don't have this failure mode at our scale.

| Problem | Alt A (per-chunk persist) | Alt B (cron iteration) | Warden | Alt C (control loop) |
|---|---|---|---|---|
| P1 | ✅ Solves | ⚠️ Partial | ✅ Solves | ✅ Solves |
| P2 | ❌ Not solved | ⚠️ Eventually solves at cron cadence | ✅ Solves with cool-down | ✅ Solves |
| ADR-017 conformance | ✅ Inside | ✅ Inside | ❌ Violates | ❌ Violates |

---

## 7. Recommendation

1. **Land Alt A (per-chunk persist)** as a minor runner change. It closes P1 universally for all tasks at low architectural cost and stays inside ADR-017. ~10 LOC.
2. **For P2**, accept Alt B (cron iteration) as the default. yfinance bans get handled by Polygon's next cron tick. This is bounded and predictable.
3. **Park the warden** (`metadata_warden.py`, archived) for the case where the user is doing a one-time interactive universe fill and wants the adaptive behavior. The warden is *opt-in* manual orchestration, not core architecture.
4. **Do not promote the warden's logic into the runner (Alt C)** unless we're prepared to formally amend ADR-017.

This recommendation answers the user's two original questions:
- "Are we running in batches?" → After Alt A: yes, every chunk commits as it lands.
- "If Yahoo bans, are we falling back to alternatives?" → Yes, but at cron cadence, not mid-run. Mid-run handoff requires the warden, which is opt-in only.

---

## 8. Open questions

1. **Does the universe-fill scenario justify the warden?** If you fill the universe once a quarter and rely on cron afterwards, Alt B is enough. If you want robust on-demand fills, the warden becomes worth the architectural debt.
2. **Should `task.persist(db, chunk_results)` be the contract instead of `task.persist(db, all_results)`?** Right now it's the latter. Alt A would change the call site but every task's persist already handles the per-row case correctly via `db.execute(select(...).where(...in keys))`. The contract change is small but real.
3. **Should we log per-chunk persist outcomes to `task_runs`?** Currently `TaskRun` rows are written by Polygon tasks only. Per-chunk visibility would help ops more than per-task summaries.
4. **Cross-process Yahoo ban awareness** — if cron and warden run simultaneously they could double-spend Yahoo's anti-abuse budget. ADR-017 §9.5 has the same concern for Polygon. A shared SQLite-backed bucket (deferred) addresses both.

---

## 9. Decision (locked 2026-05-08 — option b)

User chose **(b)**: per-chunk persist in the runner (Alt A) for P1
across all tasks; warden stays parked as opt-in manual tooling.

Options that were on the table:

- **(a)** Per-chunk persist only. Park the warden permanently.
- **(b) ← chosen** — Per-chunk persist + warden as opt-in manual tooling
  (the script was parked outside the cron job set and is archived,
  used only for interactive universe-fill scenarios).
- **(c)** Formally amend ADR-017 to allow chunk-level adaptive logic in
  the runner. Higher cost, broader benefit.
- **(d)** Reject everything. Status quo single-shot persist.

What landed:

  • `screener/tasks/runner.py:run_task` calls `task.persist(db,
    chunk_results)` immediately after each successful chunk fetch
    (instead of accumulating all chunks and persisting once at the end).
  • Persist calls are serialised across concurrent chunks via
    `asyncio.Lock` because SQLAlchemy Sessions are loop-bound.
  • Per-chunk persist failures don't crash the whole task — they're
    treated as chunk-level failures and recorded to `task_failures`.
  • `TaskResult.processed` now means "rows successfully fetched AND
    persisted" rather than "rows fetched".

What stays parked:

  • `metadata_warden.py` (archived) — manual tooling for the
    interactive universe-fill scenario. NOT wired into `fill_universe.py`,
    NOT part of the cron job set. With per-chunk persist now in place,
    the warden's batched-commit benefit is partly subsumed by the
    runner; the warden's remaining value is the adaptive ban-detection
    + cool-down (P2 only).

What still isn't built:

  • P2 (Yahoo ban → 4K wasted calls before next cron) is NOT solved by
    per-chunk persist. Mid-run yf→pg fallback would require either the
    warden or option (c). Cron-cadence fallback is the standard
    behaviour.

---

## 10. State of the parked code (what NOT to ship without ADR-020 acceptance)

- `metadata_warden.py` (archived) — the draft warden. Header explicitly says "DRAFT — NOT WIRED".
- `scripts/fill_universe.py` Phase 4 — REVERTED back to the simple `_run_named_task("metadata_yf", …)` path before the warden was wired in.
- `docs/QUICKSTART.md` — REVERTED, warden subsection removed.

---

*ADR-020 | The Boardroom Lab | 2026-05-08*

*The warden idea is right. The implementation we drafted contradicts ADR-017. The right move is to land the simple per-chunk persist fix universally, keep the warden as manual interactive tooling, and not promote either into the canonical task framework without formal ADR-017 amendment.*
