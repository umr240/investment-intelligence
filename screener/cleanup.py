"""
Cleanup job (docs/architecture/SCREENER_PIPELINE.md §2, DECISIONS.md DEC-11).

Sweeps stale `screener_candidate` Company rows whose `last_screened` is
older than their per-row `retention_days`. For each, drops the heavy data
that backed up the screening (Financial / FinancialSourceLog / PriceHistory /
etc.) and marks the Company row as 'archived'. We KEEP the Company row
itself for audit (so we can see "we screened it once but didn't promote").

Protected statuses: NEVER touches `watchlist` or `dive_history` tickers
even if a stale `last_screened`. Promotion to those statuses overrides the
TTL.

Returns a `CleanupReport` summarising what was archived. `dry_run=True`
returns the report WITHOUT mutating the DB — used by `invest screen cleanup
--dry-run`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from data.db import get_session
from data.models.schema import (
    AnalystCoverageRecord,
    Company,
    EarningsHistory,
    Financial,
    FinancialSourceLog,
    InsiderTransactionRecord,
    InstitutionalHolderRecord,
    PriceHistory,
    ShortInterestRecord,
)

logger = logging.getLogger(__name__)


_PROTECTED_STATUSES = ("watchlist", "dive_history")


@dataclass
class CleanupReport:
    today: date
    candidates_evaluated: int = 0
    archived_tickers: list[str] = field(default_factory=list)
    skipped_protected: list[str] = field(default_factory=list)
    rows_deleted_by_table: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False


def archive_stale_candidates(
    today: date | None = None,
    dry_run: bool = False,
) -> CleanupReport:
    """
    Find screener_candidate Company rows where today - last_screened > retention_days
    and not in a protected status. Drop their dependent rows; mark Company.status='archived'.
    """
    today = today or date.today()
    report = CleanupReport(today=today, dry_run=dry_run)

    with get_session() as session:
        candidates = (
            session.query(Company)
            .filter(Company.status == "screener_candidate")
            .filter(Company.last_screened.isnot(None))
            .all()
        )
        report.candidates_evaluated = len(candidates)

        for c in candidates:
            # Per-ticker TTL check
            if c.last_screened is None:
                continue
            cutoff = today - timedelta(days=c.retention_days or 30)
            # DateTime column: rows read back as datetimes, the cutoff is a date.
            last = c.last_screened
            if (last.date() if isinstance(last, datetime) else last) > cutoff:
                continue   # not yet stale

            if c.status in _PROTECTED_STATUSES:
                report.skipped_protected.append(c.ticker)
                continue

            company_id = c.id
            ticker = c.ticker

            if not dry_run:
                # Drop dependent rows; bulk delete via SQL DELETE for speed
                report.rows_deleted_by_table.setdefault("financials", 0)
                deleted = (
                    session.query(Financial)
                    .filter_by(company_id=company_id)
                    .delete(synchronize_session=False)
                )
                report.rows_deleted_by_table["financials"] += deleted

                deleted = (
                    session.query(FinancialSourceLog)
                    .filter_by(ticker=ticker)
                    .delete(synchronize_session=False)
                )
                report.rows_deleted_by_table.setdefault("financial_source_log", 0)
                report.rows_deleted_by_table["financial_source_log"] += deleted

                for cls, name in [
                    (PriceHistory, "price_history"),
                    (InsiderTransactionRecord, "insider_transactions"),
                    (AnalystCoverageRecord, "analyst_coverage"),
                    (EarningsHistory, "earnings_history"),
                    (ShortInterestRecord, "short_interest"),
                    (InstitutionalHolderRecord, "institutional_holders"),
                ]:
                    deleted = (
                        session.query(cls)
                        .filter_by(company_id=company_id)
                        .delete(synchronize_session=False)
                    )
                    report.rows_deleted_by_table.setdefault(name, 0)
                    report.rows_deleted_by_table[name] += deleted

                # Keep the Company row but mark as archived
                c.status = "archived"

            report.archived_tickers.append(ticker)

    logger.info(
        "cleanup: evaluated=%d, archived=%d, protected=%d, dry_run=%s",
        report.candidates_evaluated,
        len(report.archived_tickers),
        len(report.skipped_protected),
        dry_run,
    )
    return report
