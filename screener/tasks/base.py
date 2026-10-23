"""FilterTask protocol + shared dataclasses (ADR-017 §3).

A ``FilterTask`` maintains one (or a small group of) warehouse columns on
``Company``. Every task has the same shape — the runner does not branch on
task identity. Adding a new filter is a one-class addition; cron handlers
just include the class in their task list.

Design constraints, lifted from ADR-017:

  • No DAG engine. Cron handlers list tasks in human-chosen order.
  • No state machine. The ``*_fetched_at`` columns ARE the state.
  • Idempotent. Re-running a task with no pending tickers is a no-op.
  • Per-chunk failures don't block other chunks; per-task failures don't
    block other tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.orm import Session

    from data.models.schema import Company
    from data.rate_limit import TokenBucket


class RateLimitError(Exception):
    """Raised by :meth:`FilterTask.fetch_chunk` when the upstream returned 429
    (or equivalent). The runner catches this and applies exponential backoff
    before retrying the chunk. Other exception types are treated as
    transient errors with the same retry policy but logged differently.
    """

    def __init__(self, source: str, *, retry_after: float | None = None) -> None:
        super().__init__(f"Rate limited by {source}" + (
            f" (retry-after={retry_after}s)" if retry_after is not None else ""
        ))
        self.source = source
        self.retry_after = retry_after


@dataclass(slots=True)
class FilterResult:
    """A single ticker's fetched values for one task.

    ``values`` maps warehouse column names (e.g. ``"roic"``,
    ``"market_cap_usd"``) to their fetched values. The runner forwards
    these dicts to :meth:`FilterTask.persist`, which is responsible for
    UPSERTing them and bumping the matching ``*_fetched_at`` columns.
    """

    cik: str
    values: dict[str, Any] = field(default_factory=dict)
    # Optional per-result diagnostic notes (e.g. "fell back to TTM",
    # "extracted via regex"). Never written to a warehouse column —
    # surfaces only in logs / task failure entries.
    notes: list[str] = field(default_factory=list)


class TaskRunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"            # some chunks failed, but task completed
    FAILED = "failed"              # task itself errored before finishing
    SKIPPED = "skipped"            # nothing pending


@dataclass(slots=True)
class TaskResult:
    """Summary returned by :func:`screener.tasks.runner.run_task`."""

    task: str
    status: TaskRunStatus
    processed: int = 0
    failed: int = 0
    failed_ciks: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str | None = None        # populated when status == FAILED


class FilterTask(Protocol):
    """The complete filter-task interface.

    Concrete tasks need only:
      1. set the four class-level attributes
      2. implement ``select_pending``, ``fetch_chunk``, and ``persist``
    """

    name: str                                 # unique — used in logs + task_failures + checkpoint
    source: str                               # 'sec' | 'fmp' | 'yf' | 'in-memory'
    refresh_interval: timedelta               # how often this column should be re-fetched
    concurrency_override: int | None          # None = use runner default

    def select_pending(self, db: Session) -> list[Company]:
        """Tickers needing this task: column missing OR stale OR last failed.

        SHOULD be indexable; runner has no other awareness of which rows
        are pending. Tasks should also exclude tickers whose
        ``task_failures.retry_count`` exceeds ``MAX_TASK_RETRIES``.
        """
        ...

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        """Fetch upstream data for a chunk of tickers.

        Implementations MUST:
          • call ``await bucket.acquire()`` before each upstream request
          • raise :class:`RateLimitError` on 429 (runner backs off + retries)
          • be idempotent — same input ≡ same output (no upstream side-effects)
          • NEVER call any module that writes to the database
        """
        ...

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        """UPSERT results into the warehouse and bump ``*_fetched_at`` columns.

        Implementations should commit in a single transaction so partial
        writes don't leave the warehouse inconsistent. If ``results`` is
        empty this is a no-op.
        """
        ...
