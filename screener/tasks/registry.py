"""FilterTask registry — single source of truth for what tasks exist (Phase 4c).

The CLI (`invest task list/run/status`) and the cron handlers in
``scheduler/jobs.py`` both look up tasks here. Adding a new task means:

  1. Implement the FilterTask in ``screener/tasks/<name>.py``
  2. Register it via ``@register_task`` (or add to TASK_REGISTRY below)
  3. Decide which cron group it belongs to (yf / sec / in-memory)

The registry is order-preserving so a deterministic cron group lists
the tasks in the right declared order.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from screener.tasks.bew_overlay import BEWOverlayTask
from screener.tasks.composite import CompositeScoreTask
from screener.tasks.exclusion import ExclusionClassifyTask
from screener.tasks.framework_score import FrameworkScoreTask
from screener.tasks.fundamentals import FundamentalsTask
from screener.tasks.intrinsic_value import IntrinsicValueTask
from screener.tasks.ipo_date import IPODateTask
from screener.tasks.metadata_polygon import MetadataPolygonTask
from screener.tasks.metadata_yf import MetadataYFTask
from screener.tasks.polygon import (
    PolygonCurrentPriceTask,
    PolygonMACDTask,
    PolygonRSITask,
    PolygonShortInterestTask,
    PolygonSMATask,
    PolygonWeeklyPriceTask,
)

if TYPE_CHECKING:
    from screener.tasks.base import FilterTask


# Class registry — name → class. Concrete instances are constructed by
# callers (each task instance is cheap; some carry per-call caches).
# Annotated as `type` rather than `type[FilterTask]` because mypy doesn't
# recognise structural Protocol subtyping in dict-literal positions; the
# class-level attributes still satisfy the Protocol at runtime.
TASK_REGISTRY: dict[str, type] = {
    "metadata_yf":            MetadataYFTask,
    # Polygon metadata fallback — runs only on rows where yfinance failed
    # (market_cap_usd IS NULL). Per ADR-019 source-priority: yf > polygon.
    "metadata_polygon":       MetadataPolygonTask,
    "exclusion_classify":     ExclusionClassifyTask,
    "ipo_date":               IPODateTask,
    "fundamentals":           FundamentalsTask,
    "composite_score":        CompositeScoreTask,
    "framework_score":        FrameworkScoreTask,
    "bew_overlay":            BEWOverlayTask,
    "intrinsic_value":        IntrinsicValueTask,    # ADR-027 Phase D
    # Polygon plugin (ADR-019). Opt-in via POLYGON_API_KEY; tasks
    # short-circuit when key unset. Run on watchlist tickers only —
    # 5 calls/min free tier won't survive universe-scale use.
    "polygon_current_price":  PolygonCurrentPriceTask,
    "polygon_weekly_price":   PolygonWeeklyPriceTask,
    "polygon_short_interest": PolygonShortInterestTask,
    "polygon_rsi":            PolygonRSITask,
    "polygon_sma":            PolygonSMATask,
    "polygon_macd":           PolygonMACDTask,
}


# Cron groups — by upstream rate-limit source, mirroring DEC-14's three slots
# but with task-list shape (ADR-017 §6). Universe refresh is a special-case
# bootstrap fn, not a FilterTask — cron handlers call it before the chunked
# tasks in the yf group.
CRON_GROUPS: dict[str, tuple[str, ...]] = {
    # MetadataYF runs first; MetadataPolygon backfills any tickers yfinance
    # couldn't resolve (NULL market_cap after yf attempt).
    "warehouse-yf-tasks":      ("metadata_yf", "metadata_polygon"),
    "warehouse-sec-tasks":     ("ipo_date", "fundamentals"),
    "warehouse-rollup-tasks":  (
        "exclusion_classify",
        "composite_score",
        "framework_score",
        "bew_overlay",
        "intrinsic_value",
    ),
    # Polygon plugin runs on its own cadence — separated so the 5/min
    # quota doesn't block the universe-scale warehouse refreshes.
    # Recommended cron: nightly @ 2am for watchlist tickers only.
    "polygon-watchlist-tasks": (
        "polygon_current_price",
        "polygon_weekly_price",
        "polygon_short_interest",
        "polygon_rsi",
        "polygon_sma",
        "polygon_macd",
    ),
}


def get_task(name: str) -> FilterTask:
    """Instantiate a registered task by name. Raises KeyError on unknown name."""
    try:
        cls = TASK_REGISTRY[name]
    except KeyError as e:
        raise KeyError(
            f"Unknown task {name!r}. "
            f"Registered tasks: {sorted(TASK_REGISTRY)}"
        ) from e
    instance: FilterTask = cls()
    return instance


def task_names() -> list[str]:
    """Names of all registered tasks, in declaration order."""
    return list(TASK_REGISTRY)


__all__ = [
    "CRON_GROUPS",
    "TASK_REGISTRY",
    "get_task",
    "task_names",
]
