"""The decision log must be usable as an audit trail.

It previously was not: eleven labels named two different decisions each, `D17`
named three, and two decisions were recorded twice. References like "per D19"
could not be resolved. These assertions keep the repaired state repaired.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_LOG = _ROOT / "architecture-decisions"          # resolved below
_LOG_CANDIDATES = [
    _ROOT / ".claude" / "architecture" / "DECISIONS.md",
    _ROOT / "docs" / "architecture" / "DECISIONS.md",
]

_HEADING = re.compile(r"^## (DEC-\d+) — (.+)$", re.M)
_REFERENCE = re.compile(r"\bDEC-\d+\b")


def _log_path() -> Path:
    for p in _LOG_CANDIDATES:
        if p.exists():
            return p
    pytest.skip("decision log not found")


def _defined_ids() -> set[str]:
    return {m.group(1) for m in _HEADING.finditer(_log_path().read_text(encoding="utf-8"))}


def test_every_decision_id_is_unique() -> None:
    ids = [m.group(1) for m in _HEADING.finditer(_log_path().read_text(encoding="utf-8"))]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"decision ids reused — the log cannot resolve a reference: {dupes}"


def test_ids_are_contiguous_and_ordered() -> None:
    nums = [int(i.split("-")[1]) for i in sorted(_defined_ids())]
    assert nums == list(range(1, len(nums) + 1)), f"gaps or disorder in decision ids: {nums}"


def test_entries_are_in_chronological_order() -> None:
    text = _log_path().read_text(encoding="utf-8")
    pairs = re.findall(r"^## (DEC-\d+) —.*?\n+\*\*Date\*\*: (\S+)", text, re.M | re.S)
    dates = [d for _, d in pairs]
    assert dates == sorted(dates), "decision entries are not in date order"


def test_every_referenced_decision_exists() -> None:
    """A DEC-nn cited anywhere in the repo must be defined in the log."""
    defined = _defined_ids()
    out = subprocess.run(
        ["git", "grep", "-ohE", r"\bDEC-[0-9]+\b"], cwd=_ROOT,
        capture_output=True, text=True,
    )
    referenced = {r for r in out.stdout.split() if r}
    dangling = sorted(referenced - defined)
    assert not dangling, f"references to decisions that do not exist: {dangling}"


def test_no_mixed_old_and_new_identifier_ranges() -> None:
    """Catches a botched rewrite like `D1–DEC-16`."""
    out = subprocess.run(
        # Excludes this file: the docstring's example matches under a UTF-8
        # regex engine (GNU git on Linux), though not under Apple Git.
        ["git", "grep", "-nE", r"\bD[0-9]+ *[–-] *DEC-|DEC-[0-9]+ *[–-] *\bD[0-9]+\b",
         "--", ".", f":(exclude){Path(__file__).relative_to(_ROOT).as_posix()}"],
        cwd=_ROOT, capture_output=True, text=True,
    )
    assert not out.stdout.strip(), f"mixed identifier ranges:\n{out.stdout}"
