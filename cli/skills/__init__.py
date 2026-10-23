"""ADR-032 — project-local skill runtime.

This package contains the Python implementations of skills declared in
.claude/skills/*.md. The markdown file is the design doc + contract
(frontmatter, preconditions, postconditions, audit trail); the Python
module is the executor.

Architecture:

  .claude/skills/audit-completeness.md   ← design + frontmatter (versioned)
                  ↓ name → handler lookup
  cli/skills/audit_completeness.py        ← Python implementation
                  ↓
  invest skill audit-completeness SHOP    ← user-invokable CLI

The runtime (`cli/skills/runtime.py`) reads the frontmatter for metadata
(version, dangerous, shadow_mode_until), dispatches to the Python
handler, runs the workflow, captures postconditions, writes a
SkillInvocation row.

No new Anthropic call sites are added by this package. Skills that
need LLM work invoke `deepdive/narrative.py` or
`deepdive/external_signals.py` — the existing two permitted sites.
"""
from __future__ import annotations

from cli.skills.runtime import (
    PostCondition,
    SkillContext,
    SkillResult,
    get_handler,
    register,
    run_skill,
)

__all__ = [
    "PostCondition",
    "SkillContext",
    "SkillResult",
    "get_handler",
    "register",
    "run_skill",
]
