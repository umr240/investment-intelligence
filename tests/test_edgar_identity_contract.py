"""EDGAR_IDENTITY must never carry a baked-in default.

SEC rate-limits per User-Agent, so a shared default would put every operator of
a public clone on one budget — and publish the author's contact details. This
guards the SECURITY §1 rule at the level that actually regresses: source text.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import settings as live_settings
from config.settings import (
    MissingEdgarIdentityError,
    Settings,
    require_edgar_identity,
)

_ROOT = Path(__file__).resolve().parents[1]

# Any `EDGAR_IDENTITY` lookup that supplies a second argument is a fallback.
_ENV_FALLBACK = re.compile(
    r"""(?:environ|os)\s*\.\s*(?:get|getenv)\s*\(\s*["']EDGAR_IDENTITY["']\s*,""",
    re.VERBOSE,
)
_SETDEFAULT = re.compile(r"""setdefault\s*\(\s*["']EDGAR_IDENTITY["']\s*,""")


def _tracked_python_files() -> list[Path]:
    skip = {".venv", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules"}
    return [
        p for p in _ROOT.rglob("*.py")
        if not skip & set(p.relative_to(_ROOT).parts) and p.name != Path(__file__).name
    ]


def test_no_source_file_supplies_an_edgar_identity_fallback() -> None:
    offenders = []
    for path in _tracked_python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if _ENV_FALLBACK.search(text) or _SETDEFAULT.search(text):
            offenders.append(str(path.relative_to(_ROOT)))
    assert not offenders, (
        "EDGAR_IDENTITY fallback found — use config.settings.require_edgar_identity() "
        f"instead: {offenders}"
    )


def test_settings_declares_no_identity_default() -> None:
    """Assert the declared default, not an instance — a developer's real .env
    would otherwise mask it."""
    assert Settings.model_fields["edgar_identity"].default == ""


@pytest.mark.parametrize("value", ["", "   ", "Your Name your.email@example.com"])
def test_unset_or_placeholder_identity_raises(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(live_settings, "edgar_identity", value)
    with pytest.raises(MissingEdgarIdentityError):
        require_edgar_identity()


def test_identity_without_an_email_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_settings, "edgar_identity", "Nameless Operator")
    with pytest.raises(MissingEdgarIdentityError):
        require_edgar_identity()


def test_configured_identity_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_settings, "edgar_identity", " Jane Doe jane@example.com ")
    assert require_edgar_identity() == "Jane Doe jane@example.com"
