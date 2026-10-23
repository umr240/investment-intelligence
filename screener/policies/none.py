"""The default policy: nothing is excluded for non-financial reasons."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import true

from screener.policies.base import INCLUDED, PolicyVerdict

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

    from data.models.schema import Company
    from data.reader import CompanyDataReader


class NonePolicy:
    name = "none"

    def classify(self, sector: str | None, industry: str | None) -> PolicyVerdict:
        return INCLUDED

    def gate(self, reader: CompanyDataReader) -> PolicyVerdict:
        return PolicyVerdict(excluded=False, reason="no exclusion policy active")

    def not_excluded(self) -> ColumnElement[bool]:
        return true()

    def eligible(self) -> ColumnElement[bool]:
        return true()

    def status_of(self, company: Company) -> str | None:
        return None

    def record_exclusion(self, company: Company, reason: str) -> None:
        return None

    def record_tier3_pass(self, company: Company) -> None:
        return None

    def classification_task(self) -> Any | None:
        return None
