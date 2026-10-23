"""Universe refresh — bootstraps the warehouse (Phase 4b / ADR-017).

Universe enumeration is a SPECIAL CASE — it doesn't fit the per-ticker
``FilterTask`` shape because it produces tickers rather than maintaining a
column on existing ones. Cron handlers call :func:`refresh_universe`
BEFORE running any per-filter tasks; everything else then operates on the
``Company`` rows it created.

The SEC universe file (~1MB, ~10000 rows) is cached for 7 days by
``data.universe.sec_us``; calling this more often is a no-op cost-wise.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.models.schema import Company
from data.universe.sec_us import SecUsUniverseProvider

logger = logging.getLogger("task-runner")


DEFAULT_UNIVERSE_REFRESH = timedelta(days=7)


@dataclass(slots=True)
class UniverseRefreshResult:
    region: str
    fetched: int
    inserted: int
    updated: int
    duration_seconds: float


def refresh_universe(
    db: Session,
    region: str = "us",
    refresh_interval: timedelta = DEFAULT_UNIVERSE_REFRESH,
) -> UniverseRefreshResult:
    """Refresh the ``Company`` warehouse seed from the regional universe provider.

    Idempotent: re-running on a fresh cache is a no-op (the provider's
    7-day cache short-circuits the SEC fetch). New tickers land as
    ``status='screener_candidate'``; existing rows have their identity
    fields refreshed (name, exchange, cik) but ``status``, exclusion verdicts
    and warehouse columns are left alone.
    """
    import time
    started = time.monotonic()

    if region != "us":
        raise NotImplementedError(
            f"refresh_universe: region={region!r} not supported "
            "(only 'us' is wired in Phase 4b)"
        )

    provider = SecUsUniverseProvider()
    universe = provider.fetch()
    if not universe:
        logger.warning("[universe_refresh] empty universe from provider")
        return UniverseRefreshResult(
            region=region,
            fetched=0,
            inserted=0,
            updated=0,
            duration_seconds=time.monotonic() - started,
        )

    logger.info("[universe_refresh] %d tickers from %s provider", len(universe), region)

    existing = {
        c.ticker: c
        for c in db.execute(
            select(Company).where(
                Company.ticker.in_([u.ticker for u in universe])
            )
        ).scalars().all()
    }

    now = datetime.now(UTC)
    inserted = 0
    updated = 0
    new_rows: list[Company] = []
    for u in universe:
        existing_row = existing.get(u.ticker)
        if existing_row is None:
            new_rows.append(Company(
                ticker=u.ticker,
                name=u.name,
                exchange=u.exchange,
                cik=u.cik,
                status="screener_candidate",
            ))
            inserted += 1
        else:
            # Refresh identity fields if they drifted
            changed = False
            if existing_row.name != u.name and u.name:
                existing_row.name = u.name
                changed = True
            if existing_row.exchange != u.exchange and u.exchange:
                existing_row.exchange = u.exchange
                changed = True
            if not existing_row.cik and u.cik:
                existing_row.cik = u.cik
                changed = True
            if changed:
                existing_row.updated_at = now
                updated += 1

    if new_rows:
        db.add_all(new_rows)
    db.commit()

    duration = time.monotonic() - started
    logger.info(
        "[universe_refresh] inserted=%d updated=%d in %.2fs",
        inserted, updated, duration,
    )
    return UniverseRefreshResult(
        region=region,
        fetched=len(universe),
        inserted=inserted,
        updated=updated,
        duration_seconds=duration,
    )


__all__ = ["UniverseRefreshResult", "refresh_universe"]
