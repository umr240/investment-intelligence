"""Composite verdict labels (ADR-054).

Rows written before the rename keep their old labels; nothing rewrites them.
The ORM column type maps them on every read; raw-SQL readers call
`canonical_verdict` themselves, and SQL filters use `stored_forms` so a WHERE
clause still matches the old spelling.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

LEGACY_VERDICTS: Final[dict[str, str]] = {
    "initiate": "priority_watchlist",
    "insufficient_breadth": "research_only",
}


def canonical_verdict(verdict: str | None) -> str | None:
    """A stored composite verdict in the current vocabulary (legacy match ignores case)."""
    return None if verdict is None else LEGACY_VERDICTS.get(verdict.lower(), verdict)


def stored_forms(verdicts: Iterable[str]) -> tuple[str, ...]:
    """Every spelling a row may hold for these verdicts, legacy ones included."""
    wanted = set(verdicts)
    return tuple(sorted(wanted | {old for old, new in LEGACY_VERDICTS.items() if new in wanted}))


# The narrative's verdict for each composite verdict (ADR-054 table; ADR-023 §1.4 labels).
NARRATIVE_VERDICTS: Final[dict[str, str]] = {
    "priority_watchlist": "WATCHLIST WITH TRIGGERS",
    "watchlist": "WATCHLIST WITH TRIGGERS",
    "monitor": "WATCHLIST WITH TRIGGERS",
    "exclude": "EXCLUDE WITH REASON",
    "research_only": "RESEARCH-ONLY",
}


def narrative_verdict(verdict: str | None) -> str | None:
    """The narrative label a composite verdict maps to; None for an unknown verdict."""
    canonical = canonical_verdict(verdict)
    return None if canonical is None else NARRATIVE_VERDICTS.get(canonical)
