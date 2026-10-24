"""Deep-dive provenance and staleness (DEC-46).

A dive records the newest parser version that wrote its ticker's fundamentals
and the 10-K it read. When a later refresh re-reads those filings with a newer
parser, the dive's inputs are superseded: it is flagged stale, never deleted,
and its narrative is withheld until the dive is re-run.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from data.db import get_session
from data.models.schema import Company, DeepDiveRun, FinancialSourceLog


def fundamentals_parser_version(session: Session, ticker: str) -> int | None:
    """Newest parser version among the ticker's logged filings; None if none is versioned."""
    v = session.execute(
        select(func.max(FinancialSourceLog.parser_version)).where(
            FinancialSourceLog.ticker == ticker
        )
    ).scalar()
    return int(v) if v is not None else None


def latest_10k_accession(session: Session, ticker: str) -> str | None:
    """Accession of the most recent 10-K in the ticker's filing log."""
    acc = session.execute(
        select(FinancialSourceLog.accession_number)
        .where(FinancialSourceLog.ticker == ticker, FinancialSourceLog.form_type == "10-K")
        .order_by(FinancialSourceLog.fiscal_year.desc(), FinancialSourceLog.id.desc())
        .limit(1)
    ).scalar()
    return str(acc) if acc else None


def flag_superseded_dives(ticker: str) -> int:
    """Flag dives read by an older parser than the ticker's rows now carry; returns the count."""
    with get_session() as session:
        current = fundamentals_parser_version(session, ticker)
        if current is None:
            return 0
        company_id = session.execute(select(Company.id).where(Company.ticker == ticker)).scalar()
        if company_id is None:
            return 0
        runs = (
            session.execute(
                select(DeepDiveRun).where(
                    DeepDiveRun.company_id == company_id,
                    DeepDiveRun.stale_reason.is_(None),
                    func.coalesce(DeepDiveRun.parser_version, 0) < current,  # NULL = unversioned
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now()
        for run in runs:
            was = "unversioned" if run.parser_version is None else f"v{run.parser_version}"
            run.stale_reason = f"fundamentals re-read by parser v{current} (dive read {was})"
            run.stale_at = now
        return len(runs)


def latest_dive_stale_reason(ticker: str) -> str | None:
    """Stale reason of the ticker's most recent dive; None if it is current or absent."""
    with get_session() as session:
        reason = session.execute(
            select(DeepDiveRun.stale_reason)
            .join(Company, Company.id == DeepDiveRun.company_id)
            .where(Company.ticker == ticker.upper())
            .order_by(DeepDiveRun.id.desc())
            .limit(1)
        ).scalar()
        return str(reason) if reason else None
