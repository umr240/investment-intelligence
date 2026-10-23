"""Docs that name a path must name one that exists.

A structure diagram or a file reference that has quietly gone stale is worse
than none: a reader trusts it and is sent somewhere that does not exist. These
turn that drift into a test failure instead of a discovery.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Paths inside fenced diagrams and prose, e.g. `docs/methodology/PROJECT_SPEC.md`
# or a bare `f1_pre_discovery.py` leaf in the structure tree.
_PATHISH = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|toml|ini|json|yml|yaml))`")
_TREE_LEAF = re.compile(r"^[│├└─\s]*([A-Za-z0-9_.-]+\.(?:py|md|toml|ini|json))\s")


def _structure_block() -> list[str]:
    text = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    block = re.search(r"^## PROJECT STRUCTURE.*?^```\n(.*?)^```", text, re.S | re.M)
    assert block, "CLAUDE.md no longer has a fenced PROJECT STRUCTURE block"
    return block.group(1).splitlines()


def test_project_structure_names_only_real_files() -> None:
    """Every file leaf in CLAUDE.md's structure tree must exist somewhere."""
    existing = {p.name for p in _ROOT.rglob("*") if p.is_file()}
    missing = []
    for line in _structure_block():
        m = _TREE_LEAF.match(line)
        if m and m.group(1) not in existing:
            missing.append(m.group(1))
    assert not missing, f"CLAUDE.md structure tree names files that do not exist: {missing}"


def test_project_structure_lists_every_source_directory() -> None:
    """A top-level package missing from the tree is an undocumented component."""
    tracked_dirs = {
        p.name for p in _ROOT.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and p.name not in {"exports", "narrative_dumps", "node_modules", "__pycache__"}
        and any(p.rglob("*"))
    }
    block = "\n".join(_structure_block())
    undocumented = sorted(d for d in tracked_dirs if f"{d}/" not in block)
    assert not undocumented, (
        f"top-level directories absent from CLAUDE.md's structure tree: {undocumented}"
    )


@pytest.mark.parametrize("doc", ["CLAUDE.md", "README.md"])
def test_referenced_repo_paths_exist(doc: str) -> None:
    """Backticked repo-relative paths in the top-level docs must resolve."""
    text = (_ROOT / doc).read_text(encoding="utf-8")
    missing = []
    for candidate in set(_PATHISH.findall(text)):
        if "/" not in candidate:
            continue  # bare filenames are covered by the structure-tree test
        if candidate.startswith((".", "http")):
            continue
        if not (_ROOT / candidate).exists():
            missing.append(candidate)
    assert not missing, f"{doc} references paths that do not exist: {sorted(missing)}"
