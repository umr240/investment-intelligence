"""The LLM-provider call-site allow-list — the single source of truth for it.

Docs refer to `ALLOWED` here rather than stating a count (ADR-031-A1). Scope is
the working tree, not the tracked set, so an uncommitted module is caught too.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

ALLOWED = frozenset(
    {
        "deepdive/narrative.py",
        "deepdive/external_signals.py",
        "deepdive/conversation.py",
    }
)

_PROVIDERS = frozenset({"anthropic", "openai"})
_SKIP_DIRS = frozenset({"tests", "node_modules", "__pycache__"})


def _is_provider(name: str | None) -> bool:
    return name is not None and name.split(".")[0] in _PROVIDERS


def _source_files() -> list[Path]:
    files: list[Path] = []
    stack = [_ROOT]
    while stack:
        d = stack.pop()
        for p in d.iterdir():
            if p.is_dir():
                skip = p.name.startswith(".") or p.name in _SKIP_DIRS
                if not skip and not (p / "pyvenv.cfg").exists():
                    stack.append(p)
            elif p.suffix == ".py":
                files.append(p)
    return files


def _parse(path: Path) -> ast.AST:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # other modules' escape-sequence lint
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _provider_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, module) for every static or literal-dynamic provider import."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [(node.lineno, a.name) for a in node.names if _is_provider(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _is_provider(node.module):
                hits.append((node.lineno, str(node.module)))
        elif isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            arg = node.args[0]
            if (
                name in {"import_module", "__import__"}
                and isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and _is_provider(arg.value)
            ):
                hits.append((node.lineno, arg.value))
    return hits


def test_detector_sees_every_import_form() -> None:
    src = (
        "import anthropic\nfrom openai import OpenAI\nimport openai.types as t\n"
        "import importlib\nimportlib.import_module('anthropic')\n__import__('openai')\n"
        "from . import anthropic\nimport anthropic_tools\n"
    )
    assert [m for _, m in _provider_imports(ast.parse(src))] == [
        "anthropic",
        "openai",
        "openai.types",
        "anthropic",
        "openai",
    ]


def test_llm_providers_imported_only_at_allowed_sites() -> None:
    offenders = []
    for path in _source_files():
        rel = path.relative_to(_ROOT).as_posix()
        if rel in ALLOWED:
            continue
        hits = _provider_imports(_parse(path))
        offenders += [f"{rel}:{line} imports {mod}" for line, mod in hits]
    assert not offenders, (
        "LLM provider SDKs may be imported only by the modules in ALLOWED; a new "
        f"call site is an ADR amendment, not a code change: {offenders}"
    )


def test_allowed_sites_exist_and_still_call_a_provider() -> None:
    """A stale entry would silently widen the allow-list for whatever reuses the path."""
    for rel in sorted(ALLOWED):
        path = _ROOT / rel
        assert path.is_file(), f"{rel} is allow-listed but missing"
        assert _provider_imports(_parse(path)), (
            f"{rel} is allow-listed but no longer imports a provider — drop it from ALLOWED"
        )
