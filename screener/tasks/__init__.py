"""Per-filter task package (ADR-017).

The screener is a SQL query over a wide ``Company`` warehouse. Each filter
dimension on that warehouse is maintained by an independent ``FilterTask``
subclass:

  • ``select_pending(db)`` — SQL query for tickers needing this column
  • ``fetch_chunk(...)``   — fetch upstream data for a chunk of tickers
  • ``persist(db, results)`` — UPSERT into the warehouse + bump *_fetched_at

The universal ``run_task`` runner in :mod:`screener.tasks.runner` chunks,
parallelises, and retries — every task gets the same orchestration for free.

Phase 4b implemented tasks:

  • :class:`MetadataYFTask`     — yfinance .info → market_cap, sector, industry
  • :class:`ExclusionClassifyTask` — the active exclusion policy's classifier
  • :class:`IPODateTask`        — SEC submissions.json → ipo_date
  • :class:`FundamentalsTask`   — companyfacts.json → Financial rows + warehouse rollup
  • :class:`CompositeScoreTask` — warehouse columns → composite_score + data_completeness

Phase 4b non-FilterTask helpers:

  • :func:`refresh_universe` — bootstraps Company rows from SEC universe (special case)

Not built as tasks: Tier 4 frames and the Tier 5 gates run inside the staged
screener (docs/architecture/SCREENER_PIPELINE.md); there is no FMP metadata task.
"""
from screener.tasks.base import (
    FilterResult,
    FilterTask,
    RateLimitError,
    TaskResult,
    TaskRunStatus,
)
from screener.tasks.composite import CompositeScoreTask
from screener.tasks.exclusion import ExclusionClassifyTask
from screener.tasks.framework_score import FrameworkScoreTask
from screener.tasks.fundamentals import FundamentalsTask
from screener.tasks.intrinsic_value import IntrinsicValueTask
from screener.tasks.ipo_date import IPODateTask
from screener.tasks.metadata_yf import MetadataYFTask
from screener.tasks.universe import UniverseRefreshResult, refresh_universe

__all__ = [
    "CompositeScoreTask",
    "FilterResult",
    "FilterTask",
    "FrameworkScoreTask",
    "FundamentalsTask",
    "ExclusionClassifyTask",
    "IntrinsicValueTask",
    "IPODateTask",
    "MetadataYFTask",
    "RateLimitError",
    "TaskResult",
    "TaskRunStatus",
    "UniverseRefreshResult",
    "refresh_universe",
]
