"""Stored exclusion verdicts, one row per (company, policy).

Policies keep their classifications here instead of on `companies`, so the
core schema carries no policy-specific columns. A company with no row for a
policy has not been classified by it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from data.models.schema import Company, ExclusionVerdict

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement


def verdict_of(company: Company, policy: str) -> ExclusionVerdict | None:
    found: list[ExclusionVerdict] = [v for v in company.exclusion_verdicts if v.policy == policy]
    return found[0] if found else None


def status_of(company: Company, policy: str) -> str | None:
    v = verdict_of(company, policy)
    return None if v is None else str(v.status)


def reason_of(company: Company, policy: str) -> str | None:
    v = verdict_of(company, policy)
    return None if v is None or v.reason is None else str(v.reason)


def set_status(
    company: Company,
    policy: str,
    status: str,
    *,
    reason: str | None = None,
    source: str | None = None,
) -> None:
    """Insert or update the company's verdict; works before the company is flushed."""
    v = verdict_of(company, policy)
    if v is None:
        company.exclusion_verdicts.append(
            ExclusionVerdict(policy=policy, status=status, reason=reason, source=source)
        )
        return
    v.status = status  # type: ignore[assignment]
    v.reason = reason  # type: ignore[assignment]
    v.source = source  # type: ignore[assignment]
    v.classified_at = datetime.now(UTC)  # type: ignore[assignment]


def has_status(policy: str, *statuses: str) -> ColumnElement[bool]:
    """Companies whose verdict under `policy` is one of `statuses`."""
    return Company.id.in_(
        select(ExclusionVerdict.company_id).where(
            ExclusionVerdict.policy == policy, ExclusionVerdict.status.in_(statuses)
        )
    )


def lacks_status(policy: str, *statuses: str) -> ColumnElement[bool]:
    """Companies with no verdict under `policy`, or one outside `statuses`."""
    return ~has_status(policy, *statuses)
