"""Exclusion-policy registry.

The active policy comes from `settings.exclusion_policy` (`EXCLUSION_POLICY`),
default `none`. Add-on packages register policies under the
`investment_intelligence.exclusion_policies` entry-point group; see README.md.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING

from screener.policies.base import INCLUDED, ExclusionPolicy, PolicyVerdict
from screener.policies.none import NonePolicy

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

ENTRY_POINT_GROUP = "investment_intelligence.exclusion_policies"
BUILTINS: dict[str, Callable[[], ExclusionPolicy]] = {"none": NonePolicy}


class UnknownPolicyError(ValueError):
    pass


@cache
def _add_ons() -> dict[str, EntryPoint]:
    """Installed add-on policies, scanned once and never imported here."""
    found = entry_points(group=ENTRY_POINT_GROUP)
    return {ep.name: ep for ep in found if ep.name not in BUILTINS}


def registered() -> list[str]:
    """Every policy name that can be selected."""
    return sorted({*BUILTINS, *_add_ons()})


def get_policy(name: str | None = None) -> ExclusionPolicy:
    """The named policy, or the configured one. Unknown names fail fast.

    Only the requested policy is imported, so a broken add-on cannot break `none`.
    """
    if name is None:
        from config.settings import settings

        name = settings.exclusion_policy
    if name in BUILTINS:
        return BUILTINS[name]()
    ep = _add_ons().get(name)
    if ep is None:
        raise UnknownPolicyError(
            f"unknown exclusion policy {name!r}; registered: {', '.join(registered())}"
        )
    try:
        factory: Callable[[], ExclusionPolicy] = ep.load()
    except Exception as exc:
        raise UnknownPolicyError(f"exclusion policy {name!r} failed to load: {exc}") from exc
    return factory()


def not_excluded() -> ColumnElement[bool]:
    """Task-selector predicate for the configured policy."""
    return get_policy().not_excluded()


__all__ = [
    "ENTRY_POINT_GROUP",
    "INCLUDED",
    "ExclusionPolicy",
    "PolicyVerdict",
    "UnknownPolicyError",
    "get_policy",
    "not_excluded",
    "registered",
]
