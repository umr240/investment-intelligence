"""Polygon plugin FilterTasks (ADR-019 / Phase 5a).

Six tasks that wrap :class:`data.api.polygon_client.PolygonClient` and
write to the warehouse:

  * :class:`PolygonCurrentPriceTask`   — `/v2/aggs/{t}/prev` →
    ``Company.latest_close`` + ``latest_close_at``
  * :class:`PolygonWeeklyPriceTask`    — weekly OHLCV bars →
    ``PriceHistory`` rows (UPSERT, polygon-over-yfinance precedence)
  * :class:`PolygonShortInterestTask`  — settlement-date series →
    ``ShortInterestRecord`` rows (UPSERT)
  * :class:`PolygonRSITask`            — RSI(14) → ``Company.latest_rsi_14``
  * :class:`PolygonSMATask`            — SMA(50) + SMA(200) →
    ``Company.latest_sma_50`` + ``latest_sma_200``
  * :class:`PolygonMACDTask`           — MACD(12/26/9) →
    ``Company.latest_macd_{line,signal,histogram}``

Common rules:
  - ``source = 'polygon'`` for the universal runner's bucket lookup
  - ``concurrency_override = 1`` — the 5/min global bucket already
    throttles us, but keeping a single chunk in flight is safer for
    pagination ordering and 429 backoff observability
  - All tasks short-circuit when ``POLYGON_API_KEY`` is unset
    (``select_pending`` returns ``[]``); F2/F4 fall back to yfinance rows
  - Scope is the watchlist and active portfolio, never the screener universe
    (ADR-019: 5 calls/min cannot cover it), unless a task is constructed with
    an explicit ``tickers`` set, as Stage C's shortlist prefetch does
  - Tasks write a ``TaskRun`` row per ticker for ops visibility
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.api.polygon_client import (
    PolygonBar,
    PolygonClient,
    PolygonResponse,
)
from data.models.schema import (
    Company,
    PortfolioPosition,
    PriceHistory,
    ShortInterestRecord,
    TaskRun,
    WatchlistEntry,
)
from screener.tasks.base import FilterResult

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

    from data.rate_limit import TokenBucket

logger = logging.getLogger("task-runner")


# ── Shared helpers ────────────────────────────────────────────────────────


def _polygon_client_or_none() -> PolygonClient | None:
    """Return a usable client, or None when POLYGON_API_KEY is unset."""
    client = PolygonClient()
    return client if client.has_key else None


def _record_task_run(
    db: Session,
    task_name: str,
    ticker: str,
    started_at: datetime,
    *,
    status: str,
    error: str | None,
    rows_written: int,
) -> None:
    """Append a TaskRun row. Best-effort; never raises out of the task."""
    try:
        db.add(TaskRun(
            task_name=task_name,
            ticker=ticker,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            status=status,
            error=error,
            rows_written=rows_written,
        ))
        db.commit()
    except Exception as exc:    # noqa: BLE001
        logger.debug("task_runs persistence (%s/%s): %s", task_name, ticker, exc)
        try:
            db.rollback()
        except Exception:
            pass


def _in_scope(tickers: frozenset[str] | None) -> ColumnElement[bool]:
    """ADR-019 scope: the given tickers, else the watchlist and active portfolio."""
    if tickers is not None:
        return Company.ticker.in_(tickers)
    watched = select(WatchlistEntry.company_id).where(WatchlistEntry.is_active.is_(True))
    held = select(PortfolioPosition.company_id).where(PortfolioPosition.is_active.is_(True))
    return or_(
        Company.status == "watchlist", Company.id.in_(watched), Company.id.in_(held)
    )


class _PolygonScoped:
    """Base for the six tasks: optional explicit ticker scope (see _in_scope)."""

    def __init__(self, tickers: Iterable[str] | None = None) -> None:
        self.tickers = None if tickers is None else frozenset(t.upper() for t in tickers)


def _select_pending_with_key_gate(
    db: Session,
    fetched_at_attr: str,
    refresh_interval: timedelta,
    *,
    tickers: frozenset[str] | None = None,
    require_cik: bool = False,
) -> list[Company]:
    """Common select_pending body — short-circuits when no key, else returns
    candidates whose `fetched_at_attr` is null or older than `refresh_interval`.
    """
    if _polygon_client_or_none() is None:
        return []
    cutoff = datetime.now(UTC) - refresh_interval
    col = getattr(Company, fetched_at_attr)
    stmt = select(Company).where(_in_scope(tickers)).where(or_(col.is_(None), col < cutoff))
    if require_cik:
        stmt = stmt.where(Company.cik.isnot(None)).where(Company.cik != "")
    return list(db.execute(stmt).scalars().all())


# ── PolygonCurrentPriceTask ───────────────────────────────────────────────


class PolygonCurrentPriceTask(_PolygonScoped):
    """End-of-day OHLCV from /v2/aggs/{t}/prev → Company.latest_close."""

    name = "polygon_current_price"
    source = "polygon"
    refresh_interval = timedelta(hours=24)
    concurrency_override = 1

    def select_pending(self, db: Session) -> list[Company]:
        return _select_pending_with_key_gate(
            db,
            "latest_close_at",
            self.refresh_interval,
            tickers=self.tickers,
        )

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        results: list[FilterResult] = []
        for c in companies:
            started = datetime.now(UTC)
            try:
                resp: PolygonResponse = await asyncio.to_thread(
                    polygon.fetch_prev_aggs, c.ticker,
                )
            except Exception as exc:
                logger.warning("[%s] %s threw: %s", self.name, c.ticker, exc)
                continue
            if not resp.ok or not resp.rows:
                continue
            bar: PolygonBar = resp.rows[0]
            if bar.close is None:
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "latest_close": bar.close,
                    "started_at": started,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            company.latest_close = r.values["latest_close"]
            company.latest_close_at = now
            _record_task_run(
                db, self.name, r.values["ticker"], r.values["started_at"],
                status="success", error=None, rows_written=1,
            )

        db.commit()


# ── PolygonWeeklyPriceTask ────────────────────────────────────────────────


class PolygonWeeklyPriceTask(_PolygonScoped):
    """52 weekly OHLCV bars → PriceHistory rows. Polygon-over-yfinance UPSERT."""

    name = "polygon_weekly_price"
    source = "polygon"
    refresh_interval = timedelta(days=7)
    concurrency_override = 1

    def select_pending(self, db: Session) -> list[Company]:
        # Its own column: sharing latest_close_at let the daily price task
        # mark every ticker fresh, so weekly bars were almost never fetched.
        return _select_pending_with_key_gate(
            db,
            "weekly_prices_fetched_at",
            self.refresh_interval,
            tickers=self.tickers,
        )

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        results: list[FilterResult] = []
        end = date.today()
        start = end - timedelta(days=400)            # ~52 weekly bars
        for c in companies:
            started = datetime.now(UTC)
            try:
                resp: PolygonResponse = await asyncio.to_thread(
                    polygon.fetch_weekly_aggs, c.ticker,
                    start=start, end=end,
                )
            except Exception as exc:
                logger.warning("[%s] %s threw: %s", self.name, c.ticker, exc)
                continue
            if not resp.ok:
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "company_id": c.id,
                    "bars": resp.rows,
                    "started_at": started,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        for r in results:
            company_id = r.values["company_id"]
            bars: list[PolygonBar] = r.values["bars"]
            company = db.get(Company, company_id)
            if company is not None:
                company.weekly_prices_fetched_at = now  # type: ignore[assignment]
            if not bars:
                _record_task_run(
                    db, self.name, r.values["ticker"], r.values["started_at"],
                    status="success", error=None, rows_written=0,
                )
                continue

            # Build (date) → existing_row index for this ticker
            existing = {
                row.date: row
                for row in db.execute(
                    select(PriceHistory).where(
                        PriceHistory.company_id == company_id,
                        PriceHistory.date.in_([b.date for b in bars]),
                    )
                ).scalars().all()
            }

            new_count = 0
            updated_count = 0
            for bar in bars:
                existing_row = existing.get(bar.date)
                if existing_row is None:
                    db.add(PriceHistory(
                        company_id=company_id,
                        date=bar.date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=int(bar.volume) if bar.volume is not None else None,
                        adj_close=bar.close,
                        source="polygon",
                    ))
                    new_count += 1
                else:
                    # Polygon-over-yfinance precedence: always overwrite yfinance,
                    # always refresh polygon (latest fetch wins on a polygon row).
                    existing_row.open = bar.open
                    existing_row.high = bar.high
                    existing_row.low = bar.low
                    existing_row.close = bar.close
                    existing_row.volume = (
                        int(bar.volume) if bar.volume is not None else None
                    )
                    existing_row.adj_close = bar.close
                    existing_row.source = "polygon"
                    updated_count += 1

            _record_task_run(
                db, self.name, r.values["ticker"], r.values["started_at"],
                status="success", error=None,
                rows_written=new_count + updated_count,
            )

        db.commit()


# ── PolygonShortInterestTask ──────────────────────────────────────────────


class PolygonShortInterestTask(_PolygonScoped):
    """FINRA biweekly short-interest history → ShortInterestRecord rows."""

    name = "polygon_short_interest"
    source = "polygon"
    refresh_interval = timedelta(days=14)
    concurrency_override = 1

    def select_pending(self, db: Session) -> list[Company]:
        # Short interest doesn't have its own *_fetched_at on Company; reuse
        # the most-recent ShortInterestRecord.settlement_date age as the gate.
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        cutoff = date.today() - self.refresh_interval
        # Subquery: companies whose latest SI row is stale OR has no SI row
        # at all. Implemented in Python because portable LATERAL is annoying.
        all_active = list(db.execute(
            select(Company).where(_in_scope(self.tickers))
        ).scalars().all())
        pending: list[Company] = []
        for c in all_active:
            latest = db.execute(
                select(ShortInterestRecord.settlement_date)
                .where(ShortInterestRecord.company_id == c.id)
                .order_by(ShortInterestRecord.settlement_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest is None or latest < cutoff:
                pending.append(c)
        return pending

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        results: list[FilterResult] = []
        for c in companies:
            started = datetime.now(UTC)
            try:
                resp: PolygonResponse = await asyncio.to_thread(
                    polygon.fetch_short_interest_history, c.ticker,
                )
            except Exception as exc:
                logger.warning("[%s] %s threw: %s", self.name, c.ticker, exc)
                continue
            if not resp.ok:
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "company_id": c.id,
                    "rows": resp.rows,
                    "started_at": started,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        for r in results:
            company_id = r.values["company_id"]
            rows = r.values["rows"]
            if not rows:
                _record_task_run(
                    db, self.name, r.values["ticker"], r.values["started_at"],
                    status="success", error=None, rows_written=0,
                )
                continue

            existing = {
                row.settlement_date: row
                for row in db.execute(
                    select(ShortInterestRecord)
                    .where(ShortInterestRecord.company_id == company_id)
                    .where(ShortInterestRecord.settlement_date.in_(
                        [si.settlement_date for si in rows]
                    ))
                ).scalars().all()
            }

            written = 0
            for si in rows:
                existing_row = existing.get(si.settlement_date)
                if existing_row is None:
                    db.add(ShortInterestRecord(
                        company_id=company_id,
                        settlement_date=si.settlement_date,
                        short_interest=si.short_interest,
                        days_to_cover=si.days_to_cover,
                        float_shares=None,
                        source="polygon",
                    ))
                    written += 1
                else:
                    # Polygon precedence — overwrite yfinance snapshots
                    existing_row.short_interest = si.short_interest
                    existing_row.days_to_cover = si.days_to_cover
                    existing_row.source = "polygon"
                    written += 1

            _record_task_run(
                db, self.name, r.values["ticker"], r.values["started_at"],
                status="success", error=None, rows_written=written,
            )

        db.commit()


# ── PolygonRSITask ────────────────────────────────────────────────────────


class PolygonRSITask(_PolygonScoped):
    """RSI(14) → Company.latest_rsi_14."""

    name = "polygon_rsi"
    source = "polygon"
    refresh_interval = timedelta(days=1)
    concurrency_override = 1

    def select_pending(self, db: Session) -> list[Company]:
        return _select_pending_with_key_gate(
            db,
            "latest_rsi_14_fetched_at",
            self.refresh_interval,
            tickers=self.tickers,
        )

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        results: list[FilterResult] = []
        for c in companies:
            started = datetime.now(UTC)
            try:
                resp: PolygonResponse = await asyncio.to_thread(
                    polygon.fetch_rsi, c.ticker, window=14, timespan="day", limit=1,
                )
            except Exception as exc:
                logger.warning("[%s] %s threw: %s", self.name, c.ticker, exc)
                continue
            if not resp.ok or not resp.rows:
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "rsi_14": resp.rows[0].value,
                    "started_at": started,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            company.latest_rsi_14 = r.values["rsi_14"]
            company.latest_rsi_14_fetched_at = now
            _record_task_run(
                db, self.name, r.values["ticker"], r.values["started_at"],
                status="success", error=None, rows_written=1,
            )
        db.commit()


# ── PolygonSMATask ────────────────────────────────────────────────────────


class PolygonSMATask(_PolygonScoped):
    """SMA(50) + SMA(200) → Company.latest_sma_50 + latest_sma_200.

    Two upstream calls per ticker (one per window). The shared 5/min
    bucket throttles them globally; with concurrency_override=1, we
    effectively serialise: 2 calls per ticker × 12s = 24s/ticker for
    sustained universe runs (acceptable for nightly cron).
    """

    name = "polygon_sma"
    source = "polygon"
    refresh_interval = timedelta(days=1)
    concurrency_override = 1

    def select_pending(self, db: Session) -> list[Company]:
        # Either window stale qualifies — they're refreshed together.
        if _polygon_client_or_none() is None:
            return []
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(_in_scope(self.tickers))
            .where(
                or_(
                    Company.latest_sma_50_fetched_at.is_(None),
                    Company.latest_sma_50_fetched_at < cutoff,
                    Company.latest_sma_200_fetched_at.is_(None),
                    Company.latest_sma_200_fetched_at < cutoff,
                )
            )
        )
        return list(db.execute(stmt).scalars().all())

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        results: list[FilterResult] = []
        for c in companies:
            started = datetime.now(UTC)
            try:
                sma50 = await asyncio.to_thread(
                    polygon.fetch_sma, c.ticker, window=50, timespan="day", limit=1,
                )
                sma200 = await asyncio.to_thread(
                    polygon.fetch_sma, c.ticker, window=200, timespan="day", limit=1,
                )
            except Exception as exc:
                logger.warning("[%s] %s threw: %s", self.name, c.ticker, exc)
                continue
            if not sma50.ok and not sma200.ok:
                continue
            v50 = sma50.rows[0].value if (sma50.ok and sma50.rows) else None
            v200 = sma200.rows[0].value if (sma200.ok and sma200.rows) else None
            if v50 is None and v200 is None:
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "sma_50": v50,
                    "sma_200": v200,
                    "started_at": started,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            v = r.values
            if v.get("sma_50") is not None:
                company.latest_sma_50 = v["sma_50"]
                company.latest_sma_50_fetched_at = now
            if v.get("sma_200") is not None:
                company.latest_sma_200 = v["sma_200"]
                company.latest_sma_200_fetched_at = now
            _record_task_run(
                db, self.name, v["ticker"], v["started_at"],
                status="success", error=None,
                rows_written=int(v.get("sma_50") is not None)
                             + int(v.get("sma_200") is not None),
            )
        db.commit()


# ── PolygonMACDTask ───────────────────────────────────────────────────────


class PolygonMACDTask(_PolygonScoped):
    """MACD(12/26/9) → Company.latest_macd_{line,signal,histogram}."""

    name = "polygon_macd"
    source = "polygon"
    refresh_interval = timedelta(days=1)
    concurrency_override = 1

    def select_pending(self, db: Session) -> list[Company]:
        return _select_pending_with_key_gate(
            db,
            "latest_macd_fetched_at",
            self.refresh_interval,
            tickers=self.tickers,
        )

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = _polygon_client_or_none()
        if polygon is None:
            return []
        results: list[FilterResult] = []
        for c in companies:
            started = datetime.now(UTC)
            try:
                resp: PolygonResponse = await asyncio.to_thread(
                    polygon.fetch_macd, c.ticker, timespan="day", limit=1,
                )
            except Exception as exc:
                logger.warning("[%s] %s threw: %s", self.name, c.ticker, exc)
                continue
            if not resp.ok or not resp.rows:
                continue
            point = resp.rows[0]
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "macd_line": point.macd_line,
                    "signal": point.signal,
                    "histogram": point.histogram,
                    "started_at": started,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            v = r.values
            company.latest_macd_line = v["macd_line"]
            company.latest_macd_signal = v["signal"]
            company.latest_macd_histogram = v["histogram"]
            company.latest_macd_fetched_at = now
            _record_task_run(
                db, self.name, v["ticker"], v["started_at"],
                status="success", error=None, rows_written=1,
            )
        db.commit()


__all__ = [
    "PolygonCurrentPriceTask",
    "PolygonMACDTask",
    "PolygonRSITask",
    "PolygonSMATask",
    "PolygonShortInterestTask",
    "PolygonWeeklyPriceTask",
]
