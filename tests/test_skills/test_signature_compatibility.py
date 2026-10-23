"""ADR-032 §10 #9 — CI signature-compatibility check for project-local skills.

Vector 3 of the regression analysis is *"CLI rename / flag-removal silently
breaks the skill 6 months later"*. This test loads every `.claude/skills/*.md`,
extracts every `invest <subcommand> [--flag …]` invocation referenced in the
body, and verifies via `invest <subcommand> --help`:

  1. The subcommand still exists (help text fetches without error)
  2. Every `--flag` mentioned in the skill is still present in the help

CI fails if any skill references a CLI surface that no longer exists. The
skill author MUST update the skill body OR justify the discrepancy before
the change can land.

This is the same discipline as ruff + mypy: a structural check that
prevents drift between two coupled artefacts (here: skill text and CLI
signature).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"


# Match `invest <subcommand>` or `invest <subcommand> args...`
# Captures (1)=subcommand, (2)=remainder of the line up to ` or newline or backtick
_INVEST_INVOCATION = re.compile(r"invest\s+([a-z][a-z\-]*)(?:\s+([^\n`]*))?")
# Match `--flag-name` (kebab or single-word)
_FLAG = re.compile(r"--[a-z][a-z\-]*")
# Typer forces colour under GITHUB_ACTIONS and styles `-` and `-tier` apart.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _skill_files() -> list[Path]:
    """Return every real skill .md file in .claude/skills/.

    Excludes README.md (project docs) and any file starting with `_`
    (auto-generated artifacts like _lineage.md per ADR-034 §6.2 —
    same exclusion rule as cli.skills.lineage.discover_skill_names()).
    """
    if not SKILLS_DIR.exists():
        return []
    return [
        p for p in sorted(SKILLS_DIR.glob("*.md"))
        if p.name.lower() != "readme.md" and not p.name.startswith("_")
    ]


def _invest_help(subcommand: str) -> str | None:
    """Fetch `invest <subcommand> --help` text. Returns None on non-zero exit.

    NOTE: Click/Typer's rich-formatted help output contains box-drawing
    unicode chars that crash Python's default Windows-cp1252 stdout decoding.
    We capture bytes and decode utf-8 with errors='replace' so the help-text
    presence check still works even when the rendering codec disagrees.
    """
    try:
        result = subprocess.run(
            ["uv", "run", "invest", subcommand, "--help"],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return _ANSI.sub("", result.stdout.decode("utf-8", errors="replace"))


def _extract_invocations(skill_text: str) -> list[tuple[str, str]]:
    """Pull (subcommand, args_remainder) from every `invest …` reference in the
    skill body. Deduplicated by (subcommand, frozenset(flags)).
    """
    seen: set[tuple[str, frozenset[str]]] = set()
    out: list[tuple[str, str]] = []
    for m in _INVEST_INVOCATION.finditer(skill_text):
        sub = m.group(1)
        args = m.group(2) or ""
        flags = frozenset(_FLAG.findall(args))
        key = (sub, flags)
        if key in seen:
            continue
        seen.add(key)
        out.append((sub, args))
    return out


@pytest.mark.parametrize("skill_path", _skill_files(), ids=lambda p: p.name)
def test_skill_invest_invocations_signature_compatible(skill_path: Path) -> None:
    """Each `invest <subcommand> …` referenced in a skill body must resolve
    against the current CLI signature: subcommand exists AND every --flag
    referenced is present in the subcommand's help output.

    Skills SHOULD reference `invest`-prefixed commands; non-`invest` shell
    invocations (e.g., raw python scripts) are not validated here.
    """
    text = skill_path.read_text(encoding="utf-8")
    invocations = _extract_invocations(text)
    if not invocations:
        pytest.skip(f"{skill_path.name} has no `invest …` invocations to validate")

    failures: list[str] = []
    for subcommand, args_remainder in invocations:
        help_text = _invest_help(subcommand)
        if help_text is None:
            failures.append(
                f"  subcommand `invest {subcommand}` no longer exists "
                f"(or --help failed)"
            )
            continue
        flags_in_skill = _FLAG.findall(args_remainder)
        for flag in flags_in_skill:
            if flag not in help_text:
                failures.append(
                    f"  `invest {subcommand}` no longer supports `{flag}` "
                    f"(referenced in skill at args: '{args_remainder.strip()}')"
                )

    if failures:
        msg = (
            f"\n{skill_path.name} references CLI surface that no longer exists:\n"
            + "\n".join(failures)
            + f"\n\nFix: update {skill_path.name} OR restore the CLI surface."
            f"\nADR-032 §10 #9 — Vector 3 regression mitigation."
        )
        pytest.fail(msg)


def test_skills_directory_exists() -> None:
    """The skills directory should exist once Phase 1 of ADR-032 is shipped."""
    assert SKILLS_DIR.exists(), (
        f"{SKILLS_DIR} does not exist. ADR-032 Phase 1 requires it."
    )


def test_skills_readme_exists() -> None:
    """The schema reference README must exist."""
    assert (SKILLS_DIR / "README.md").exists(), (
        f"{SKILLS_DIR / 'README.md'} missing. See ADR-032 §9 Phase 1 step 2."
    )


def test_starter_skills_present() -> None:
    """ADR-032 §3 starter skills must be on disk."""
    expected = {"dive-complete.md", "audit-completeness.md", "external-signals.md"}
    actual = {p.name for p in _skill_files()}
    missing = expected - actual
    assert not missing, f"ADR-032 §3 starter skills missing: {missing}"
