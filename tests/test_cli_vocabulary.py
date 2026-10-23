"""User-facing CLI text must not leak internal shorthand.

Decision numbers (`D22`) and build-phase labels (`Phase 5j`) are project
bookkeeping. A user reading `invest --help` has no way to resolve them, and the
decision log they point at has historically reused numbers — so the reference
would be ambiguous even with the log in hand. ADR references are allowed:
`docs/architecture/` ships with the repo, so those resolve.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_CLI = Path(__file__).resolve().parents[1] / "cli" / "main.py"

_DECISION_CODE = re.compile(r"\bD\d{1,2}\b")
_PHASE_CODE = re.compile(r"\bPhase\s+\d+[a-zA-Z]\b")


def _user_facing_strings() -> list[tuple[int, str]]:
    """Every string that reaches a user: help=, Typer/Panel/Table titles, docstrings."""
    tree = ast.parse(_CLI.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # help="...", title="..." keyword arguments
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in {"help", "title"} and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str):
                        found.append((kw.value.lineno, kw.value.value))
        # Docstrings of Typer commands only — Typer renders those as help text.
        # A private helper's docstring never reaches a user.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not any(_is_command_decorator(d) for d in node.decorator_list):
                continue
            doc = ast.get_docstring(node)
            if doc:
                found.append((node.lineno, doc))
    return found


def _is_command_decorator(node: ast.expr) -> bool:
    """True for `@app.command(...)` / `@<group>_app.command(...)` and bare forms."""
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr in {"command", "callback"}


@pytest.mark.parametrize("pattern,label", [
    (_DECISION_CODE, "decision-log code (e.g. D22)"),
    (_PHASE_CODE, "build-phase label (e.g. Phase 5j)"),
])
def test_cli_help_text_is_free_of_internal_shorthand(
    pattern: re.Pattern[str], label: str,
) -> None:
    offenders = [
        (line, text.strip().splitlines()[0][:70])
        for line, text in _user_facing_strings()
        if pattern.search(text)
    ]
    assert not offenders, (
        f"user-facing CLI text contains {label} — a reader cannot resolve it:\n"
        + "\n".join(f"  cli/main.py:{ln}: {t}" for ln, t in offenders)
    )
