"""Universal task runner (ADR-017 §4 + ADR-020 option b).

Every :class:`FilterTask` runs through this same orchestration layer:

  1. ``task.select_pending(db)`` — read pending tickers
  2. chunk into ``TASK_CHUNK_SIZE`` batches
  3. ``asyncio.gather`` chunks at ``concurrency_override or TASK_DEFAULT_CONCURRENCY``
  4. each chunk acquires from the shared per-source ``TokenBucket``
  5. ``RateLimitError`` triggers exponential backoff + retry
  6. terminal chunk failures log to ``task_failures``; the task continues
  7. **per-chunk** ``task.persist(db, chunk_results)`` — idempotent UPSERT
     (ADR-020 option b: closes the process-crash mid-run window. A crash
     loses at most one chunk's worth of work instead of the whole task.
     Persist calls are serialised across concurrent chunks via
     ``persist_lock`` because SQLAlchemy Sessions are loop-bound.)

There is no DAG, no dependency declaration, no orchestrator state. Cron
handlers list tasks in human-chosen order and call :func:`run_task` on
each one. Per-task failure does not block subsequent tasks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, cast

import httpx
from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config.constants import (
    TASK_CHUNK_SIZE,
    TASK_DEFAULT_CONCURRENCY,
    TASK_FAILURE_BACKOFF_BASE,
    TASK_FAILURE_BACKOFF_CAP,
    TASK_MAX_RETRIES,
)
from data.models.schema import TaskFailure
from data.rate_limit import bucket_for
from screener.tasks.base import (
    FilterResult,
    FilterTask,
    RateLimitError,
    TaskResult,
    TaskRunStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from data.models.schema import Company

logger = logging.getLogger("task-runner")


HTTP_TIMEOUT_SECONDS = 30.0


async def run_task(task: FilterTask, db: Session) -> TaskResult:
    """Execute a single filter task end-to-end. Idempotent.

    Returns a :class:`TaskResult` summarising processed/failed counts.
    Re-running with no pending work is a no-op (status SKIPPED).
    """
    started = time.monotonic()
    task_name = task.name

    try:
        pending = task.select_pending(db)
    except Exception as e:
        logger.exception("[%s] select_pending failed", task_name)
        return TaskResult(
            task=task_name,
            status=TaskRunStatus.FAILED,
            error=f"select_pending: {e}",
            duration_seconds=time.monotonic() - started,
        )

    if not pending:
        logger.info("[%s] nothing pending", task_name)
        return TaskResult(
            task=task_name,
            status=TaskRunStatus.SKIPPED,
            duration_seconds=time.monotonic() - started,
        )

    logger.info("[%s] %d pending", task_name, len(pending))

    chunks = [
        pending[i : i + TASK_CHUNK_SIZE]
        for i in range(0, len(pending), TASK_CHUNK_SIZE)
    ]
    concurrency = task.concurrency_override or TASK_DEFAULT_CONCURRENCY
    sem = asyncio.Semaphore(concurrency)
    bucket = bucket_for(task.source)

    failed_ciks: list[str] = []
    # ADR-020 option b: per-chunk persist replaces the prior single-shot
    # persist. We track aggregate counts here for the final TaskResult,
    # but each chunk commits to the DB before returning from process_chunk.
    total_processed = 0
    persist_failed_ciks: list[str] = []
    # SQLAlchemy Sessions are loop-bound and aren't safe for concurrent
    # writes. With TASK_DEFAULT_CONCURRENCY=5, multiple chunks could
    # finish fetching and try to persist simultaneously. Serialise.
    persist_lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:

        async def process_chunk(chunk: list[Company], idx: int) -> None:
            nonlocal total_processed
            async with sem:
                last_err: Exception | None = None
                results: list[FilterResult] | None = None
                for attempt in range(TASK_MAX_RETRIES):
                    try:
                        results = await task.fetch_chunk(chunk, client, bucket)
                    except RateLimitError as e:
                        wait = min(
                            TASK_FAILURE_BACKOFF_BASE ** attempt,
                            TASK_FAILURE_BACKOFF_CAP,
                        )
                        if e.retry_after is not None:
                            wait = max(wait, e.retry_after)
                        logger.warning(
                            "[%s] chunk %d rate-limited (attempt %d) — backing off %.1fs",
                            task_name, idx, attempt + 1, wait,
                        )
                        last_err = e
                        await asyncio.sleep(wait)
                        continue
                    except Exception as e:
                        last_err = e
                        logger.warning(
                            "[%s] chunk %d attempt %d failed: %s",
                            task_name, idx, attempt + 1, e,
                        )
                        if attempt + 1 < TASK_MAX_RETRIES:
                            await asyncio.sleep(
                                min(
                                    TASK_FAILURE_BACKOFF_BASE ** attempt,
                                    TASK_FAILURE_BACKOFF_CAP,
                                )
                            )
                        continue
                    else:
                        # Fetch succeeded — persist this chunk now (ADR-020 b).
                        # Lock-protected because Session isn't concurrency-safe
                        # and we may have N chunks finishing simultaneously.
                        async with persist_lock:
                            try:
                                task.persist(db, results)
                                _clear_resolved_failures(db, task_name, results)
                                total_processed += len(results)
                                logger.info(
                                    "[%s] chunk %d ✓ persisted %d rows",
                                    task_name, idx, len(results),
                                )
                            except Exception as persist_exc:
                                logger.exception(
                                    "[%s] chunk %d persist failed: %s",
                                    task_name, idx, persist_exc,
                                )
                                # Treat persist failure as a chunk-level failure.
                                # Record to task_failures so the next run sees
                                # these tickers as recently-failed.
                                _record_chunk_failure(
                                    db, task_name, chunk, persist_exc,
                                )
                                persist_failed_ciks.extend(
                                    _company_key(c) for c in chunk
                                )
                        return
                # all fetch retries exhausted — record per-ticker failures
                logger.error(
                    "[%s] chunk %d failed after %d attempts: %s",
                    task_name, idx, TASK_MAX_RETRIES, last_err,
                )
                _record_chunk_failure(db, task_name, chunk, last_err)
                failed_ciks.extend(_company_key(c) for c in chunk)

        await asyncio.gather(*[
            process_chunk(c, i) for i, c in enumerate(chunks)
        ])

    # Combine fetch-level failures and persist-level failures into a single
    # failed_ciks list so the caller sees one coherent failure count.
    all_failed = failed_ciks + persist_failed_ciks
    status = (
        TaskRunStatus.PARTIAL if all_failed
        else TaskRunStatus.SUCCESS
    )
    return TaskResult(
        task=task_name,
        status=status,
        processed=total_processed,
        failed=len(all_failed),
        failed_ciks=all_failed,
        duration_seconds=time.monotonic() - started,
    )


def _company_key(company: Company) -> str:
    """Best identifier for failure logging: cik when present, else ticker.

    `Company.ticker` is NOT NULL so this always returns a str; mypy needs
    an explicit cast because the SQLAlchemy descriptors look like Column
    types without the SA mypy plugin enabled.
    """
    return cast(str, company.cik or company.ticker)


def _record_chunk_failure(
    db: Session,
    task_name: str,
    chunk: list[Company],
    err: Exception | None,
) -> None:
    """UPSERT one TaskFailure row per ticker in a failed chunk.

    On conflict (same task_name + cik), increments retry_count and
    refreshes the error message + timestamp.
    """
    if not chunk:
        return
    err_repr = (repr(err)[:500]) if err is not None else "unknown"
    rows = [
        {
            "task_name": task_name,
            "cik": _company_key(c),
            "error": err_repr,
            "retry_count": 1,
        }
        for c in chunk
    ]
    # SQLAlchemy's portable INSERT…ON CONFLICT is dialect-keyed; we use the
    # SQLite dialect (lab dev) here. Postgres deployments will swap this for
    # `postgresql.insert(...)` in a future migration.
    stmt = sqlite_insert(TaskFailure).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TaskFailure.task_name, TaskFailure.cik],
        set_={
            "error": stmt.excluded.error,
            "retry_count": TaskFailure.retry_count + 1,
            "failed_at": stmt.excluded.failed_at,
        },
    )
    try:
        db.execute(stmt)
        db.commit()
    except Exception:
        logger.exception("[%s] failed to record chunk failure to task_failures", task_name)
        db.rollback()


def _clear_resolved_failures(
    db: Session,
    task_name: str,
    successes: list[FilterResult],
) -> None:
    """Reset retry_count for tickers that succeeded this run."""
    if not successes:
        return
    ciks = [r.cik for r in successes]
    try:
        db.execute(
            update(TaskFailure)
            .where(TaskFailure.task_name == task_name)
            .where(TaskFailure.cik.in_(ciks))
            .values(retry_count=0)
        )
        db.commit()
    except Exception:
        logger.exception("[%s] failed to clear resolved task_failures", task_name)
        db.rollback()


__all__ = ["run_task"]
