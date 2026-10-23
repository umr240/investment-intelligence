"""Guards on things that only break for someone setting up from scratch.

Each assertion here failed at least once in practice, so they are regression
tests rather than hypotheticals. Scope is the tracked set — what a clone
actually receives — so these skip in a source export with no git available.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Windows MAX_PATH is 260. A checkout needs room for the user's own directory
# prefix, so cap project-relative paths well below it.
_MAX_PATH_LEN = 100

# A drive-rooted path into a personal or project directory is checkout-specific.
_ABSOLUTE_DEV_PATH = re.compile(r"[A-Za-z]:[\/](?:Users|Projects)[\/]")

_TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".ini", ".cfg", ".txt", ".yml", ".yaml", ".json",
    ".bat", ".cmd", ".ps1", ".sh", ".xml", ".ts", ".tsx", ".js", ".jsx", ".html",
    ".css", ".mako",
}


def _tracked_paths() -> list[str]:
    """Repo-relative paths git would hand a fresh clone."""
    if shutil.which("git") is None or not (_ROOT / ".git").exists():
        pytest.skip("not a git checkout — nothing to assert about the tracked set")
    out = subprocess.run(
        ["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def test_no_path_risks_windows_max_path() -> None:
    offenders = sorted(
        ((len(p), p) for p in _tracked_paths() if len(p) > _MAX_PATH_LEN), reverse=True
    )
    assert not offenders, (
        "paths this long break the Windows checkout, and core.longpaths only "
        f"rescues git — .venv native extensions still fail to load: {offenders}"
    )


def test_no_absolute_developer_paths() -> None:
    """A checkout-specific absolute path is broken for every other user."""
    offenders = []
    for rel in _tracked_paths():
        path = _ROOT / rel
        if path.suffix.lower() not in _TEXT_SUFFIXES or path.name == Path(__file__).name:
            continue
        if not path.is_file():
            continue
        if _ABSOLUTE_DEV_PATH.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(rel)
    assert not offenders, f"absolute developer paths found in: {sorted(offenders)}"


def test_no_local_package_shadows_alembic() -> None:
    """An `alembic/__init__.py` makes the migrations dir shadow the real package."""
    assert not (_ROOT / "alembic" / "__init__.py").exists(), (
        "alembic/__init__.py shadows the installed alembic package whenever the "
        "project root is on sys.path (pytest, `python -m`)"
    )
