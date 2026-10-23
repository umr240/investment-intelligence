# ADR-017 — Screener as warehouse query, not pipeline run

| Field          | Detail                                                          |
|----------------|-----------------------------------------------------------------|
| **Status**     | Accepted                                                        |
| **Date**       | 2026-05-05 (proposed) / 2026-05-06 (accepted)                   |
| **Supersedes** | ADR-016 in part (FMP at Tier 2 stays — but as `MetadataFMPTask`) |
| **Amends**     | DEC-14 (three staged crons — slots survive but contents change), the v2 screener plan's funnel model (archived) |
| **Preserves**  | DEC-09 (SEC frames), DEC-10 (no auto-dive), DEC-11 (status lifecycle), DEC-12 (period_end_date), DEC-13 (one exclusion rule set at Tier 3), DEC-15 (soft Tier 4 → now per-task scoring) |
| **Provenance** | Architecture pattern researched and proposed by Umar (2026-05-04 chat), validated against Finviz / TradingView / Fiscal.ai / StockAnalysis.com production screeners. |

---

## 1. The mental model was wrong

ADR-016 and the v2 screener plan both assumed the screener is a **linear
pipeline** that runs end-to-end on a schedule. Tier 0 → Tier 1 → ... → Tier
6, each tier narrowing the input to the next. This is intuitive but it's
not how any production screener works.

After the user pushed back ("you would need to research that") and looking
at how Finviz, TradingView, Fiscal.ai, and StockAnalysis.com actually
architect their systems, the pattern is universal:

| Platform | Architecture |
|----------|--------------|
| **Finviz** | URL parameter filters (`?f=cap_midunder,exch_nyse,fa_div_o5,idx_sp500`) translate to SQL against a continuously-updated warehouse |
| **TradingView** | SQL-like syntax with full support for AND/OR logic; 500+ fundamental and technical fields with auto refresh as fast as 10 seconds |
| **Fiscal.ai** | filter companies based on ~335 financial metrics; sources from S&P Global, Nasdaq Data Link |
| **StockAnalysis.com** | Warehouse sourced from S&P Capital IQ + Fiscal.ai |

**One-line summary**: continuous ingestion fills the warehouse; the screener
is a query.

The linear pipeline model breaks down because:

- Adding a new filter (IPO date, beta, dividend yield, anything) requires
  ramming it into a tier and re-running the whole pipeline
- A failure in one fetch (FMP down, SEC 429s) blocks tickers from advancing
  past the failed tier
- Idempotency requires tracking "where did we get to" instead of "what data
  do we have"
- Each filter can't have its own update cadence (price = daily, fundamentals
  = quarterly, IPO date = once)
- Re-fetching universe data on every screen run is wasteful

The IPO-date question that started this thread is the canary: in a tier
model it's a numbering debate (Tier 2.5? new Tier 1.5?). In a warehouse
model it's a `Company.ipo_date` column populated by `IPODateTask`. Same for
any future filter the user wants — beta, dividend yield, ESG ratings,
short interest, anything.

The right model: **`Company` is a wide table; each filter is a column;
each column has an independent task that keeps it fresh; the screener is
`SELECT WHERE … ORDER BY composite_score`.**

---

## 2. Architecture: warehouse + task queue

```
┌─────────────────────────────────────────────────────────────────────┐
│                       COMPANY WAREHOUSE                              │
│                       (existing Company table, widened)              │
│                                                                      │
│  cik | ticker | exchange | market_cap | sector | industry | ipo_date│
│  fcf | roic   | debt_eq  | ...        | composite_score | status     │
│  *_fetched_at columns track per-column freshness                     │
└──────────────┬───────────────────────────────────┬──────────────────┘
               │                                   │
               │ (write)                           │ (read)
               │                                   │
   ┌───────────▼────────────┐         ┌───────────▼────────────────┐
   │  TASK REGISTRY         │         │  SCREENER QUERY ENGINE     │
   │  (each filter = task)  │         │  (just a SQL builder)      │
   │                        │         │                            │
   │  - UniverseRefreshTask │         │  invest screen \           │
   │  - MetadataFMPTask     │         │    --cap-min 500M \        │
   │  - ExclusionClassify   │         │    --ipo-after 2016 \      │
   │  - FramesRevenueTask   │         │    --policy NAME           │
   │  - FundamentalsTask    │         │                            │
   │  - MomentumTask        │         │  → SELECT * FROM companies │
   │  - CompositeScoreTask  │         │    WHERE all filters pass  │
   │  - IPODateTask         │         │    ORDER BY composite_score│
   │  - <add new = 1 class> │         │    LIMIT N                 │
   └────────────┬───────────┘         └────────────────────────────┘
                │
                │ each task is INDEPENDENT
                │ runs on its own cadence
                │ retries its own failures
                │ updates its own column(s)
                │
   ┌────────────▼─────────────────────────────────────────────────┐
   │  TASK RUNNER  (~50 lines)                                    │
   │                                                              │
   │  1. task.select_pending(db) → list of tickers needing work   │
   │  2. chunk into batches of 50                                 │
   │  3. asyncio.gather chunks at concurrency=5                   │
   │  4. shared TokenBucket per source (SEC_BUCKET, FMP_BUCKET)   │
   │  5. per-chunk retry with backoff                             │
   │  6. failed chunks logged, NOT blocking other chunks          │
   │  7. task.persist(db, results) — idempotent UPSERT            │
   └──────────────────────────────────────────────────────────────┘
```

---

## 3. The task abstraction

Every filter — every existing tier, every future filter, every "and one
more thing" — is a class implementing this protocol:

```python
from typing import Protocol
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

class FilterTask(Protocol):
    name: str                # unique identifier, used in logs + checkpoint
    source: str              # 'sec' | 'fmp' | 'yf' | 'in-memory'
    refresh_interval: timedelta  # how often this column should be re-fetched
    concurrency_override: int | None = None  # per-task cap; None = global default

    def select_pending(self, db: Session) -> list[Company]:
        """Tickers needing this task: missing the column OR stale OR failed."""

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        """Fetch data for chunk. Must be idempotent."""

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        """UPSERT into warehouse + update *_fetched_at column."""
```

**That's the entire framework.** No DAG engine. No orchestrator. No state
machine. The `Company` table's `*_fetched_at` columns ARE the state.

### 3.1 Concrete example: `IPODateTask`

```python
class IPODateTask:
    name = "ipo_date"
    source = "sec"
    refresh_interval = timedelta(days=180)  # IPO dates barely change

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(timezone.utc) - self.refresh_interval
        return (
            db.query(Company)
            .filter(
                Company.status.in_(["screener_candidate", "watchlist"]),
                or_(
                    Company.ipo_date.is_(None),
                    Company.ipo_date_fetched_at.is_(None),
                    Company.ipo_date_fetched_at < cutoff,
                ),
            )
            .all()
        )

    async def fetch_chunk(self, companies, client, bucket):
        results = []
        for c in companies:
            await bucket.acquire()
            r = await client.get(
                f"https://data.sec.gov/submissions/CIK{c.cik.zfill(10)}.json",
                headers=SEC_HEADERS,
            )
            if r.status_code == 200:
                data = r.json()
                first_10k = _earliest_10k_date(data)
                results.append(FilterResult(
                    cik=c.cik,
                    values={"ipo_date": first_10k}
                ))
            elif r.status_code == 429:
                raise RateLimitError(c.cik)  # caller retries the chunk
        return results

    def persist(self, db, results):
        now = datetime.now(timezone.utc)
        for r in results:
            db.execute(
                update(Company)
                .where(Company.cik == r.cik)
                .values(
                    ipo_date=r.values["ipo_date"],
                    ipo_date_fetched_at=now,
                )
            )
        db.commit()
```

The IPO question is now resolved completely:
- It's a column in the warehouse
- It's filled by an independent task on a 180-day cadence
- It can fail for one ticker without blocking the other 199
- It's queryable: `SELECT * FROM companies WHERE ipo_date >= '2016-01-01'`
- It re-runs only on tickers where the column is NULL or stale

Adding any new filter follows the same template: define a column, define a
task, register it. **No tier renumbering. No pipeline rework.**

---

## 4. The universal task runner

```python
import asyncio, httpx, logging
from datetime import datetime, timezone

logger = logging.getLogger("task-runner")

# Shared per-source rate limiters (process-wide singletons)
SEC_BUCKET = TokenBucket(rate=8.0, burst=16)
FMP_BUCKET = TokenBucket(rate=4.0, burst=8)
YF_BUCKET  = TokenBucket(rate=2.0, burst=4)

BUCKETS = {"sec": SEC_BUCKET, "fmp": FMP_BUCKET, "yf": YF_BUCKET}

CHUNK_SIZE     = 50
CONCURRENCY    = 5
MAX_RETRIES    = 3


async def run_task(task: FilterTask, db: Session) -> TaskResult:
    """
    Execute a single filter task. Idempotent.
    Re-running on same DB state with no new data is a no-op.
    """
    pending = task.select_pending(db)
    if not pending:
        logger.info(f"[{task.name}] nothing pending")
        return TaskResult(task=task.name, processed=0, failed=0)

    logger.info(f"[{task.name}] {len(pending)} pending")

    chunks = [pending[i:i + CHUNK_SIZE]
              for i in range(0, len(pending), CHUNK_SIZE)]

    concurrency = task.concurrency_override or CONCURRENCY
    sem    = asyncio.Semaphore(concurrency)
    bucket = BUCKETS[task.source]
    failed_ciks: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        async def process_chunk(chunk, idx):
            async with sem:
                for attempt in range(MAX_RETRIES):
                    try:
                        results = await task.fetch_chunk(chunk, client, bucket)
                        task.persist(db, results)
                        logger.info(f"[{task.name}] chunk {idx} ✓ ({len(results)} rows)")
                        return
                    except RateLimitError:
                        await asyncio.sleep(min(2 ** attempt, 30))
                    except Exception as e:
                        logger.warning(f"[{task.name}] chunk {idx} attempt {attempt}: {e}")
                        if attempt == MAX_RETRIES - 1:
                            failed_ciks.extend(c.cik for c in chunk)
                        else:
                            await asyncio.sleep(2 ** attempt)

        await asyncio.gather(*[
            process_chunk(c, i) for i, c in enumerate(chunks)
        ])

    return TaskResult(
        task=task.name,
        processed=len(pending) - len(failed_ciks),
        failed=len(failed_ciks),
        failed_ciks=failed_ciks,
    )
```

**Lines of code: ~50.** That's the entire orchestration layer. Per-chunk
failures don't block the task. Per-task failures don't block other tasks.
Re-running a task with no pending work is a no-op.

---

## 5. The screener becomes a query

```python
# screener/query.py — replaces the entire 6-tier pipeline

from sqlalchemy import select
from data.models.schema import Company

def run_screener(
    db: Session,
    cap_min: int | None = None,
    cap_max: int | None = None,
    ipo_after: date | None = None,
    sector_in: list[str] | None = None,
    exclude_policy_failures: bool = True,
    min_roic: float | None = None,
    max_debt_equity: float | None = None,
    min_fcf_margin: float | None = None,
    min_completeness: float = 0.8,  # require 80%+ of columns populated
    top_n: int = 30,
) -> list[Company]:
    """
    The screener. Not a pipeline. A query.
    Whatever data is in the warehouse, this returns the ranked subset.
    """
    q = select(Company).where(Company.status == "screener_candidate")

    if cap_min:           q = q.where(Company.market_cap >= cap_min)
    if cap_max:           q = q.where(Company.market_cap <= cap_max)
    if ipo_after:         q = q.where(Company.ipo_date >= ipo_after)
    if sector_in:         q = q.where(Company.sector.in_(sector_in))
    if exclude_policy_failures: q = q.where(policy.eligible())
    if min_roic:          q = q.where(Company.roic >= min_roic)
    if max_debt_equity:   q = q.where(Company.debt_to_equity <= max_debt_equity)
    if min_fcf_margin:    q = q.where(Company.fcf_margin >= min_fcf_margin)

    q = q.where(Company.data_completeness >= min_completeness)
    q = q.order_by(Company.composite_score.desc()).limit(top_n)

    return db.execute(q).scalars().all()
```

**The screener is 30 lines of SQL, not 6 tiers of network code.** Filters
are composable. Adding a new filter is adding a `where()` clause.

---

## 6. Cron mapping (DEC-14 reconciliation)

DEC-14 specified three staged cron jobs grouped by rate-limit source. The
warehouse model preserves this — but each "stage" is now a **set of tasks
sharing a rate-limit bucket**, not a monolithic pipeline run.

```python
# scheduler/jobs.py

@cron("0 2 15 */3 *")  # quarterly, 02:00 — FMP source group
async def screener_fmp_tasks():
    db = get_session()
    await run_task(UniverseRefreshTask(), db)
    await run_task(MetadataFMPTask(), db)        # cap, sector, industry
    await run_task(ExclusionClassifyTask(), db)   # in-memory, no I/O

@cron("0 4 15 */3 *")  # quarterly, 04:00 — SEC frames source group
async def screener_sec_frames_tasks():
    db = get_session()
    await run_task(FramesRevenueTask(), db)
    await run_task(FramesAssetsTask(), db)
    await run_task(FramesDebtTask(), db)
    await run_task(FramesFCFTask(), db)
    await run_task(QualityScoreTask(), db)        # composite, in-memory

@cron("0 6 15 */3 *")  # quarterly, 06:00 — SEC companyfacts source group
async def screener_sec_companyfacts_tasks():
    db = get_session()
    await run_task(FundamentalsTask(), db)        # full companyfacts
    await run_task(IPODateTask(), db)             # SEC submissions
    await run_task(GatesEvaluationTask(), db)     # apply 7 gates
    await run_task(CompositeScoreTask(), db)      # final ranking

@cron("0 3 * * *")  # nightly — keep watchlist fresh
async def watchlist_refresh_tasks():
    db = get_session()
    await run_task(MetadataFMPTask(), db)
    await run_task(MomentumTask(), db)            # for watchlist tickers

@cron("0 0 * * 0")  # weekly — cleanup
async def cleanup_task():
    db = get_session()
    await run_task(CleanupStaleScreenerCandidatesTask(), db)
```

**DEC-14's three slots survive.** What changes is _within_ each slot — instead
of a linear pipeline, we run a list of independent tasks. Each can fail
without blocking the others. The next quarterly run automatically picks up
whatever was missed.

---

## 7. Schema changes

Every filter dimension becomes a column on `Company`. Each gets a paired
`*_fetched_at` for freshness tracking. The schema becomes wider but
conceptually simpler.

```sql
-- Migration: warehouse_columns.py

ALTER TABLE companies ADD COLUMN market_cap NUMERIC;
ALTER TABLE companies ADD COLUMN market_cap_fetched_at TIMESTAMP;

ALTER TABLE companies ADD COLUMN sector TEXT;            -- already exists; add fetched_at
ALTER TABLE companies ADD COLUMN sector_fetched_at TIMESTAMP;

ALTER TABLE companies ADD COLUMN industry_fetched_at TIMESTAMP;

ALTER TABLE companies ADD COLUMN ipo_date DATE;
ALTER TABLE companies ADD COLUMN ipo_date_fetched_at TIMESTAMP;

-- exclusion status: stored per policy in exclusion_verdicts

ALTER TABLE companies ADD COLUMN roic NUMERIC;
ALTER TABLE companies ADD COLUMN roic_fetched_at TIMESTAMP;

ALTER TABLE companies ADD COLUMN debt_to_equity NUMERIC;
ALTER TABLE companies ADD COLUMN fcf_margin NUMERIC;
ALTER TABLE companies ADD COLUMN revenue_growth NUMERIC;
-- ... one per metric

ALTER TABLE companies ADD COLUMN composite_score NUMERIC;
ALTER TABLE companies ADD COLUMN composite_score_fetched_at TIMESTAMP;

ALTER TABLE companies ADD COLUMN data_completeness NUMERIC;
-- 0.0 to 1.0, fraction of warehouse columns populated

CREATE INDEX idx_companies_screener
  ON companies (status, composite_score DESC)
  WHERE status IN ('screener_candidate', 'watchlist');

-- Per-task failure log (for ops visibility)
CREATE TABLE task_failures (
    id INTEGER PRIMARY KEY,
    task_name TEXT NOT NULL,
    cik TEXT NOT NULL,
    failed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    UNIQUE(task_name, cik)  -- latest failure replaces older
);
```

The wide-table approach trades schema cleanliness for query simplicity.
This matches what every production warehouse does (Snowflake, BigQuery,
dbt patterns). Don't over-normalise just because the table is wide.

---

## 8. What gets deleted from the lab's Phase 3 work

Lab currently has these from Phase 3a–3e (built last 2 sessions):

| Component | Lab file | Why deleted |
|-----------|----------|-------------|
| 6-tier linear pipeline | `screener/pipeline.py:run_screener` | Replaced by `screener/query.py:run_screener` (SQL) |
| `Stage A/B/C` monolithic functions | `screener/stages.py` | Each stage is now a list of tasks |
| `_apply_exclusion_policy` / `_apply_cap_sector` | `screener/pipeline.py` | Become tasks `ExclusionClassifyTask` / `MetadataFMPTask` |
| `Tier4Result` rank-and-narrow | `screener/tier4_frames.py:rank_and_truncate` | Becomes `QualityScoreTask` writing `composite_score` column |
| ScreenerStage checkpoint table | `data/models/schema.py` | Each task's `*_fetched_at` is the checkpoint |
| Tier 5 "apply 7 gates" monolith | `screener/gates.py:apply_all_gates` | Each gate is a task that writes a `gate_N_passed` column |
| Stage handoff via `state_json` | `screener/stages.py` | No longer needed — DB columns ARE the handoff |
| `_run_screener_stage` scheduler dispatch | `scheduler/jobs.py` | Replaced by per-task-group cron handlers |

**Approximate loss**: ~800 lines from the 5 files above. **Approximate
gain**: ~600 lines across `screener/tasks/{base,runner,*_task}.py` +
`screener/query.py`. Net: simpler, more uniform, more testable.

| Component | Lab file | Why kept |
|-----------|----------|----------|
| `Company.status` lifecycle | `data/models/schema.py` | Still the right ticker classification (DEC-11) |
| `retention_days` per-ticker TTL | `data/models/schema.py` | Still the right cleanup mechanism (DEC-11) |
| `period_end_date` canonical anchor | `data/models/schema.py` | Still required for cross-company ranking (DEC-12) |
| FMP single-bulk endpoint | (new `data/api/fmp_client.py` per ADR-016) | Becomes the `MetadataFMPTask` |
| SEC frames fetcher | `data/edgar_frames.py` | Becomes one task per concept |
| SEC companyfacts parser | `data/edgar_companyfacts.py` | Used by `FundamentalsTask` |
| Exclusion rules | the active policy (`screener/policies/`) | Used by `ExclusionClassifyTask` |
| Decile rank helpers | `screener/ranking.py` | Used by `QualityScoreTask` and `MomentumTask` |
| TokenBucket idea | needs implementation | Becomes shared SEC_BUCKET / FMP_BUCKET / YF_BUCKET |
| One exclusion rule set | (DEC-13) | Unchanged |
| No auto-dive (DEC-10) | (DEC-10) | Unchanged — query does not write to watchlist |

---

## 9. Why this isn't over-engineered

The user's earlier concern: a "task framework" sounds like over-engineering
for a quarterly batch job. The check: count what we're NOT building.

| Thing we considered | Did we build it? |
|---------------------|------------------|
| DAG engine (Airflow, Dagster, Prefect) | NO — tasks are independent or run in cron-defined order |
| Custom scheduler | NO — using the existing cron + `scheduler.jobs` |
| Task queue (Celery, Redis Streams) | NO — `select_pending()` IS the queue |
| State machine for tickers | NO — `*_fetched_at` columns ARE the state |
| Distributed workers | NO — single process, asyncio.gather |
| Task dependencies / topological sort | NO — humans order tasks in the cron handler |
| Custom retry framework | NO — try/except + asyncio.sleep |
| Heartbeats / lease management | NO — single-writer SQLite, no contention |
| Dead letter queue | NO — `task_failures` table is enough |
| Real-time progress streaming | NO — cron job, no observer |

**Total new abstractions**: 1 (the `FilterTask` Protocol).
**Total new infrastructure**: 0 (uses existing DB, existing cron).
**Total LOC for the runner**: ~50.

The "task" abstraction is just a class with three methods. Adding a new
filter is writing one class. This is genuinely simpler than the linear
pipeline because the pipeline had implicit ordering, implicit state, and
implicit failure semantics — all now made explicit and uniform.

---

## 10. Mental model translation table

For when reading older project docs:

| Old terminology | New terminology |
|-----------------|-----------------|
| Tier 0 (universe) | `UniverseRefreshTask` |
| Tier 1 (exchange filter) | `WHERE` clause in screener query |
| Tier 2 (cap/sector/industry) | `MetadataFMPTask` |
| Tier 2.5 (IPO date) | `IPODateTask` |
| Tier 3 (exclusion policy) | `ExclusionClassifyTask` |
| Tier 4 (frames-driven filter) | `FramesRevenueTask`, `FramesAssetsTask`, ... + `QualityScoreTask` |
| Tier 5 (companyfacts + 7 gates) | `FundamentalsTask` + `Gate1Task`, …, `Gate7Task` |
| Tier 6 (rank + persist) | `CompositeScoreTask` + `run_screener` query at read time |
| "Run the screener pipeline" | "Run cron jobs that update tasks; query the warehouse" |
| Stage A | FMP-source task group cron slot |
| Stage B | SEC-frames-source task group cron slot |
| Stage C | SEC-companyfacts-source task group cron slot |

---

## 11. Implementation phases (against actual lab state)

### Phase 4a — Warehouse columns + task framework (1 day)
- Migration `f7a8b9c0d1e2_warehouse_columns.py`:
  - Add column-per-metric + `*_fetched_at` columns to `Company`
  - Add `task_failures` table
- New `data/rate_limit.py`: `TokenBucket` impl (~40 LOC)
- New `screener/tasks/base.py`: `FilterTask` Protocol + `FilterResult` dataclass
- New `screener/tasks/runner.py`: `run_task()` (~50 lines)
- New `screener/query.py`: `run_screener()` SQL builder (~50 lines)

### Phase 4b — Port existing tiers as tasks (2 days)
- `UniverseRefreshTask` (was Tier 0) — uses existing `data/universe/sec_us.py`
- `MetadataFMPTask` (was Tier 2 per ADR-016 — first time it actually gets built)
- `ExclusionClassifyTask` (was Tier 3) — delegates to the active policy
- `FramesRevenueTask`, `FramesAssetsTask`, `FramesDebtTask`, `FramesFCFTask` (was Tier 4)
- `QualityScoreTask` (was Tier 4 ranking + Tier 6 composite)
- `FundamentalsTask` (was Tier 5 companyfacts) — uses `data/edgar_companyfacts.py`
- `IPODateTask` (was floating Tier 2.5)
- `Gate1Task` … `Gate7Task` (was Tier 5 gates) — each writes a `gate_N_passed` column
- `CompositeScoreTask` (was Tier 6 rank/persist; now it just updates `composite_score` column)

### Phase 4c — Wire into cron + CLI (0.5 day)
- Replace `screener-stage-A/B/C` handlers with task-list handlers
- Update `invest screen` CLI to call `run_screener()` query directly (no async, no fetch)
- Add `invest task run --name <task>` for manual single-task execution
- Add `invest task status` to show last-fetched-at + failure counts per task
- Keep `invest screen-cleanup` (now `CleanupStaleScreenerCandidatesTask`)

### Phase 4d — Cleanup + observability (0.5 day)
- `CleanupStaleScreenerCandidatesTask` (was the cleanup cron)
- Add `data_completeness` computation to `CompositeScoreTask`
- Document the task pattern (now QUICKSTART §5 and `invest task list`)
- Append DEC-16 entry to `DECISIONS.md` referencing this ADR

### Total: ~4 days

This is **less work than what was budgeted across ADR-016 + Phase 3
together** (~10 days). The task pattern collapses scattered concerns into
one uniform shape.

---

## 12. Validation before implementation

- [ ] Confirm SQLite handles a 30+ column `companies` table with our query
      patterns (it does — SQLite supports up to 2000 columns; the
      composite-score index covers our hot path)
- [ ] Confirm `select_pending()` queries are indexable on
      `(status, *_fetched_at)` — add covering indexes per task as needed
- [ ] Confirm chunk size 50 doesn't blow SEC's per-second cap when 4 chunks
      hit at concurrency 5 (4 × 50 / time-per-chunk = stay under 8/sec via
      shared bucket)
- [ ] Confirm Pydantic v2 `FilterResult` dataclass round-trips through the
      task interface without copy overhead
- [ ] Decide: do we use `task_failures.retry_count` to back off failed
      tickers across multiple cron runs? (Recommend yes — increment on
      each failure, skip if count > 5; reset on success)

---

## 13. Open questions

1. **Task ordering within a cron slot** — currently humans order them in
   the handler. Should we build dependency declarations? **Recommendation:
   no.** The current dependencies (universe → metadata → fundamentals) are
   stable and easy to reason about. Don't add a DAG until the dep graph
   has more than 2 levels.

2. **Per-task concurrency override** — Yes, added to the protocol.
   `MetadataFMPTask` only does 2 concurrent because FMP free tier is
   sensitive; SEC tasks can do 5; yfinance tasks do 1.

3. **Should tasks emit events for SSE / live progress** — useful for
   frontend "screener status" page. **Recommendation: defer to v2.**
   Cron-driven backfills don't need streaming; user-triggered ad-hoc runs
   might. Add when there's a frontend demanding it.

4. **What about the 30-day cache TTL on companyfacts.json (DEC-11)** — is
   that still needed? **Recommendation: yes**, but it's now a per-task
   concern. `FundamentalsTask` checks the cache before issuing the SEC
   request. The 30-day TTL discipline survives unchanged.

5. **What about ADR-016's FMP plumbing** — does it still need to be built?
   **Yes**, but as `MetadataFMPTask` rather than as inline pipeline code.
   The vendoring decision (slim copy vs main project import) is unchanged.
   Only the call-site moves from `_fetch_metadata_bulk` (universe walk) to
   `MetadataFMPTask.fetch_chunk` (chunked).

6. **What about the staged scheduler we just built (Phase 3e)** — gone.
   `screener/stages.py` and the `screener_stages` table are deleted in
   Phase 4. The 3 cron slot times survive but their handlers change shape.

---

## 14. Migration plan from current Phase 3 state

The lab finished Phase 3 on 2026-05-04 with a working (but yfinance-blocked)
6-tier pipeline. Migrating to the warehouse model:

| Step | Action | Risk |
|------|--------|------|
| 1 | Build Phase 4a (framework) without removing Phase 3 code | Zero — additive |
| 2 | Build Phase 4b (tasks) reading from same data sources Phase 3 used | Low — same data, different organisation |
| 3 | A/B test: run `screener-stage-A` (old) and `screener_fmp_tasks` (new) on the same DB; compare survivors | Catches regressions before the cutover |
| 4 | Switch `invest screen` CLI to query mode; deprecate `screen-stage` (still callable but logs deprecation) | Low — behaviour change is forward-compatible |
| 5 | Drop `screener/stages.py` + `screener_stages` table after 1 successful prod run | Low — by then the new path has shadowed for a quarter |

This is a **forward-compatible migration**, not a rewrite. The Phase 3 code
keeps working until step 5; new code shadows alongside until validated.

---

## 15. Cost / efficiency / speed comparison vs Phase 3 pipeline

For a typical screener query against an already-populated warehouse:

| Metric | Phase 3 pipeline (current) | ADR-017 warehouse + query |
|---|---|---|
| Cold cache (first run, full universe) | ~5-15 min wall-clock when working | ~5-15 min for backfill (same — same data) |
| Warm read (user types `invest screen ...`) | ~5-15 min (re-runs everything) | **<1 second** (SQL query only) |
| Adding a new filter | New tier number, new code path, re-test | Add column, write 1 task class, register |
| Failure recovery | Whole stage retried | Per-chunk; failed tickers skipped, others advance |
| Filter composability | Limited (each tier hardcoded) | Full SQL — `WHERE … AND … OR …` |
| Fresh-data guarantee | Re-fetch on every run | Per-column `*_fetched_at` decides |
| API call cost | Re-fetched every run | Re-fetched at task's refresh_interval cadence |

**The critical win**: querying a populated warehouse is **<1 sec** vs
**~15 min** for the pipeline approach. The warehouse takes the same time
to fill the FIRST time, but every subsequent screen reads from cached
state. Pipelines re-do the work every time.

For a user iterating on filter parameters ("show me $500M-$5B with ROIC>15%
… now show me $1B-$3B with FCF margin>20%"), the pipeline approach is
unusable. The warehouse approach is interactive.

---

*ADR-017 | The Boardroom Lab | 2026-05-05*

*The mental model shift: stop thinking "run a screener pipeline". Start
thinking "maintain a warehouse, query when needed". Every production-grade
screener — Finviz, TradingView, Fiscal.ai — works this way. The 6-tier
ladder we built was the right idea (eliminate cheap signals first) but at
runtime that's a query optimiser's job, not architecture.*
