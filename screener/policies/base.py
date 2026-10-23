"""The exclusion-policy contract.

A policy decides which companies are left out of the screen. It never changes
how a company scores. See `screener/policies/README.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

    from data.models.schema import Company
    from data.reader import CompanyDataReader


@dataclass(frozen=True)
class PolicyVerdict:
    """`excluded` drives the decision; `reason` is shown to the user either way."""

    excluded: bool
    reason: str | None = None


INCLUDED = PolicyVerdict(excluded=False)


class ExclusionPolicy(Protocol):
    name: str

    def classify(self, sector: str | None, industry: str | None) -> PolicyVerdict:
        """Tier 3: sector / industry rule, before any fundamentals are fetched."""
        ...

    def gate(self, reader: CompanyDataReader) -> PolicyVerdict:
        """G1: rule over persisted fundamentals; an exclusion is a hard gate failure."""
        ...

    def not_excluded(self) -> ColumnElement[bool]:
        """SQL predicate for task selectors: skip companies already excluded."""
        ...

    def eligible(self) -> ColumnElement[bool]:
        """SQL predicate for the warehouse query: only companies confirmed eligible."""
        ...

    def status_of(self, company: Company) -> str | None:
        """The stored status shown in the UI and CLI; None when the policy keeps none."""
        ...

    def record_exclusion(self, company: Company, reason: str) -> None:
        """Persist a Tier 3 exclusion on the company row."""
        ...

    def record_tier3_pass(self, company: Company) -> None:
        """Called when an existing company passes Tier 3 again."""
        ...

    def classification_task(self) -> Any | None:
        """A warehouse task that classifies unclassified companies, or None."""
        ...
