"""Deep-dive provenance and staleness (DEC-46, amended by DEC-47).

A dive records the oldest parser version among its ticker's logged filings,
the latest 10-K in that log, and a digest of the fundamentals it read. A later
refresh that changes those fundamentals (a parser fix, a new 10-K, a
restatement) flags the dive stale; it is never deleted. A dive is withheld
while it is flagged or has no recorded digest: inputs that cannot be checked
count as changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from data.db import get_session
from data.models.schema import Company, DeepDiveRun, Financial, FinancialSourceLog

# What _apply_financial_row writes from the parser, raw values and the ratios
# derived from them (data/pipeline.py), so a formula fix counts too. Later
# refresh phases add split, FX and price-derived columns, and filing dates move
# when a later filing repeats a figure: none of those is in the digest, so
# prices moving never makes a dive stale. Inputs outside Financial (insiders,
# prices, analyst coverage) are not covered.
DIGEST_FIELDS: tuple[str, ...] = (
    "fiscal_year", "period", "period_start_date", "period_end_date",
    "revenue", "cost_of_revenue", "gross_profit", "operating_income", "operating_expenses",
    "net_income", "ebitda", "rd_expense", "rd_disclosure_state", "sga_expense",
    "interest_expense", "income_tax_expense", "depreciation_amortization",
    "funds_held_for_clients", "investment_income_interest", "share_based_compensation",
    "goodwill", "operating_cash_flow", "free_cash_flow", "capex", "total_assets",
    "total_equity", "total_debt", "long_term_debt", "cash_and_equivalents",
    "short_term_investments", "accounts_receivable", "current_assets", "current_liabilities",
    "inventory", "shares_outstanding", "eps_diluted", "eps_basic", "dividends_paid",
    "share_repurchases",
    "gross_margin", "roic", "pretax_roic", "roe", "roa", "gp_a", "net_margin",
    "operating_margin", "fcf_margin", "rd_intensity", "asset_turnover", "debt_to_equity",
    "net_debt", "debt_to_ebitda", "current_ratio", "interest_coverage", "accruals_ratio",
    "sbc_pct_of_revenue", "goodwill_pct_of_assets",
)  # fmt: skip

UNRECORDED_REASON = "inputs not recorded (dive predates DEC-47)"


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


def fundamentals_digest(session: Session, ticker: str) -> str | None:
    """SHA-256 of the ticker's parser-written Financial values; None if it has no rows."""
    cols = [getattr(Financial, f) for f in DIGEST_FIELDS]
    rows = session.execute(
        select(*cols)
        .join(Company, Company.id == Financial.company_id)
        .where(Company.ticker == ticker)
    ).all()
    if not rows:
        return None
    # Sorted here, not in SQL: SQLite and Postgres collate "Q1" and "annual" differently.
    ordered = sorted((list(r) for r in rows), key=lambda r: (r[0], str(r[1])))
    body = json.dumps(ordered, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def flag_dives_with_changed_inputs(ticker: str) -> int:
    """Flag the ticker's dives whose recorded digest differs from its fundamentals now."""
    with get_session() as session:
        current = fundamentals_digest(session, ticker)
        company_id = session.execute(select(Company.id).where(Company.ticker == ticker)).scalar()
        if current is None or company_id is None:
            return 0
        runs = (
            session.execute(
                select(DeepDiveRun).where(
                    DeepDiveRun.company_id == company_id,
                    DeepDiveRun.stale_reason.is_(None),
                    DeepDiveRun.inputs_sha256.is_not(None),
                    DeepDiveRun.inputs_sha256 != current,
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now()
        for run in runs:
            run.stale_reason = f"fundamentals changed since this dive (refresh of {now:%Y-%m-%d})"
            run.stale_at = now
        return len(runs)


def dive_withheld_reason(run: Any) -> str | None:
    """Why a dive's narrative and chat are withheld; None if they may be used."""
    if run.stale_reason:
        return str(run.stale_reason)
    if run.inputs_sha256 is None:
        return UNRECORDED_REASON
    return None


def run_withheld_reason(run_id: int) -> str | None:
    """dive_withheld_reason for a dive by id; a missing dive is withheld too."""
    with get_session() as session:
        run = session.get(DeepDiveRun, run_id)
        return "dive not found" if run is None else dive_withheld_reason(run)


def latest_dive_stale_reason(ticker: str, mode: str | None = None) -> str | None:
    """Withheld reason of the ticker's most recent dive (of `mode`, if given); None if usable."""
    with get_session() as session:
        q: Select[Any] = (
            select(DeepDiveRun)
            .join(Company, Company.id == DeepDiveRun.company_id)
            .where(Company.ticker == ticker.upper())
        )
        if mode is not None:
            q = q.where(DeepDiveRun.mode == mode)
        run = session.execute(q.order_by(DeepDiveRun.id.desc()).limit(1)).scalars().first()
        return None if run is None else dive_withheld_reason(run)
