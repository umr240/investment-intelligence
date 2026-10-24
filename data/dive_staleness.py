"""Deep-dive provenance and staleness (DEC-46).

A dive records the oldest parser version among its ticker's logged filings and
the latest 10-K in that log. When a later refresh re-reads those filings, the
dive's inputs are superseded: it is flagged stale, never deleted, and its
narrative is withheld until the dive is re-run. Flagging does not compare the
old and new values, and the reason says so.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from data.db import get_session
from data.models.schema import Company, DeepDiveRun, FinancialSourceLog


def fundamentals_parser_version(session: Session, ticker: str) -> int | None:
    """Oldest parser version among the ticker's logged filings (unversioned = 0); None if none."""
    v = session.execute(
        select(func.min(func.coalesce(FinancialSourceLog.parser_version, 0))).where(
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


def _flag(session: Session, ticker: str, reason: str, *extra: ColumnElement[bool]) -> int:
    company_id = session.execute(select(Company.id).where(Company.ticker == ticker)).scalar()
    if company_id is None:
        return 0
    runs = (
        session.execute(
            select(DeepDiveRun).where(
                DeepDiveRun.company_id == company_id, DeepDiveRun.stale_reason.is_(None), *extra
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now()
    for run in runs:
        run.stale_reason = reason
        run.stale_at = now
    return len(runs)


def flag_dives_after_reparse(ticker: str, parser_version: int) -> int:
    """Flag the ticker's dives that read data older than `parser_version`; returns the count.

    A forced re-read by the same parser flags nothing: DEC-46 covers a parser fix.
    """
    reason = (
        f"filings re-read by parser v{parser_version} on {datetime.now():%Y-%m-%d} "
        "after this dive; values not compared"
    )
    with get_session() as session:
        return _flag(
            session, ticker, reason, func.coalesce(DeepDiveRun.parser_version, 0) < parser_version
        )


def flag_dives_read_by_older_parser(ticker: str) -> int:
    """Backfill for dives stored before DEC-46 (no recorded version); later ones are the hook's."""
    with get_session() as session:
        current = session.execute(
            select(func.max(FinancialSourceLog.parser_version)).where(
                FinancialSourceLog.ticker == ticker
            )
        ).scalar()
        if current is None:
            return 0
        reason = f"stored before filings were re-read by parser v{current}; values not compared"
        return _flag(session, ticker, reason, DeepDiveRun.parser_version.is_(None))


def latest_dive_stale_reason(ticker: str, mode: str | None = None) -> str | None:
    """Stale reason of the ticker's most recent dive (of `mode`, if given); None if current."""
    with get_session() as session:
        q: Select[Any] = (
            select(DeepDiveRun.stale_reason)
            .join(Company, Company.id == DeepDiveRun.company_id)
            .where(Company.ticker == ticker.upper())
        )
        if mode is not None:
            q = q.where(DeepDiveRun.mode == mode)
        reason = session.execute(q.order_by(DeepDiveRun.id.desc()).limit(1)).scalar()
        return str(reason) if reason else None
