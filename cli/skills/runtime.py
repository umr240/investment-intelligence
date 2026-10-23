"""ADR-032 §9 — skill-runtime: read frontmatter, dispatch handler, telemetry.

The runtime is the glue between `.claude/skills/*.md` (declarative design doc)
and `cli/skills/*.py` (Python implementation). Every skill invocation goes
through `run_skill()` so that:

  - Frontmatter is parsed and validated (mandatory fields present)
  - Dangerous-skill confirmation is enforced (raises if not authorised)
  - The Python handler is dispatched by skill name
  - Postconditions are evaluated and recorded
  - Shadow-mode delta-checks fire if `shadow_mode_until` is in the future
  - A `SkillInvocation` telemetry row is written for every run (success or
    failure)

The handler interface is intentionally narrow: `(ctx) -> SkillResult`.
Each handler receives a `SkillContext` containing the parsed frontmatter +
parsed CLI args + the timestamp, and returns a structured `SkillResult`
with postcondition outcomes, anomalies, render output, and cost.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

logger_name = __name__

# Skills directory — markdown source-of-truth for frontmatter + design
_SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"


# ── Public data types ─────────────────────────────────────────────────────


@dataclass
class PostCondition:
    """One testable assertion declared by a skill body and checked at runtime.

    `pass_` is True/False; `observed` records what was actually seen for
    audit; `expected` records the assertion that was supposed to hold.
    """
    name: str
    pass_: bool
    observed: Any = None
    expected: Any = None


@dataclass
class SkillContext:
    """Inputs handed to a skill handler at invocation time."""
    name: str                       # canonical skill name, e.g. "audit-completeness"
    version: str
    args: dict[str, Any]            # parsed CLI args
    frontmatter: dict[str, Any]     # full parsed YAML frontmatter
    invoked_at: datetime
    shadow_mode_active: bool        # whether shadow_mode_until is in the future


@dataclass
class SkillResult:
    """Output of a skill handler. The runtime persists this as telemetry."""
    success: bool
    postconditions: list[PostCondition] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    render_output: str = ""         # what to print to the user
    tool_calls_count: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost_usd: float = 0.0
    error_message: str | None = None


# ── Handler registry ──────────────────────────────────────────────────────


_HANDLERS: dict[str, Callable[[SkillContext], SkillResult]] = {}


def register(name: str) -> Callable[[Callable[[SkillContext], SkillResult]],
                                     Callable[[SkillContext], SkillResult]]:
    """Decorator: register a Python handler function for the named skill.

    The skill name MUST match the `name:` field in the markdown frontmatter
    and the filename stem in `.claude/skills/`. Mismatch → AssertionError
    at first invocation via `get_handler()`.
    """
    def _decorator(
        fn: Callable[[SkillContext], SkillResult],
    ) -> Callable[[SkillContext], SkillResult]:
        if name in _HANDLERS:
            raise ValueError(f"Skill handler already registered for {name!r}")
        _HANDLERS[name] = fn
        return fn
    return _decorator


def get_handler(name: str) -> Callable[[SkillContext], SkillResult]:
    """Lookup the Python handler for a skill by name. Raises KeyError on miss."""
    # Lazy-import handlers — every import here registers the handler via
    # the @register decorator on first attribute access.
    import cli.skills.audit_completeness  # noqa: F401
    import cli.skills.dive_complete  # noqa: F401
    import cli.skills.external_signals  # noqa: F401
    import cli.skills.intrinsic_value  # noqa: F401
    if name not in _HANDLERS:
        raise KeyError(
            f"No handler registered for skill {name!r}. "
            f"Available: {sorted(_HANDLERS.keys())}"
        )
    return _HANDLERS[name]


# ── Frontmatter parsing ───────────────────────────────────────────────────


def load_skill_frontmatter(name: str) -> dict[str, Any]:
    """Parse the YAML frontmatter from `.claude/skills/{name}.md`.

    Validates mandatory fields per ADR-032 §2.1:
      - name, version, description, do_not_invoke_when, dangerous,
        shadow_mode_until, permitted_anthropic_calls
    Missing or malformed frontmatter raises ValueError — refuse to run.
    """
    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"No skill file at {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path.name}: missing frontmatter delimiter")
    end_idx = text.find("\n---", 4)
    if end_idx < 0:
        raise ValueError(f"{path.name}: unterminated frontmatter")
    yaml_text = text[4:end_idx]

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML not installed; cannot parse skill frontmatter. "
            "Add to pyproject.toml."
        ) from exc
    fm = yaml.safe_load(yaml_text) or {}

    required = {
        "name", "description", "do_not_invoke_when", "dangerous",
        "shadow_mode_until", "permitted_anthropic_calls", "version",
    }
    missing = required - set(fm.keys())
    if missing:
        raise ValueError(
            f"{path.name}: frontmatter missing mandatory fields: "
            f"{sorted(missing)} (ADR-032 §2.1)"
        )
    if fm["name"] != name:
        raise ValueError(
            f"{path.name}: frontmatter name={fm['name']!r} mismatches "
            f"filename {name!r}"
        )
    if not isinstance(fm["do_not_invoke_when"], list) or len(fm["do_not_invoke_when"]) < 3:
        raise ValueError(
            f"{path.name}: do_not_invoke_when must have ≥3 negative "
            f"examples (ADR-032 §1.4 Vector 2 mitigation)"
        )

    return fm


# ── Main entry point ──────────────────────────────────────────────────────


def run_skill(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    confirm_dangerous: bool = False,
) -> SkillResult:
    """Run a skill end-to-end with telemetry. Returns the SkillResult.

    Workflow:
      1. Load and validate frontmatter
      2. If `dangerous: true` and confirm_dangerous=False → refuse
      3. Resolve handler from registry
      4. Build SkillContext with shadow_mode_active flag
      5. Dispatch handler; capture timing
      6. Post-flight: persist SkillInvocation row regardless of outcome
      7. Return result

    Errors during handler execution are caught and recorded; the runtime
    never lets a skill failure crash the calling process — failures are
    surfaced via SkillResult.success=False + error_message.
    """
    args = args or {}
    fm = load_skill_frontmatter(name)

    # Dangerous-skill confirmation gate (ADR-032 §2.4)
    if fm.get("dangerous") and not confirm_dangerous:
        return SkillResult(
            success=False,
            error_message=(
                f"Skill {name!r} is dangerous=true (frontmatter). "
                f"Re-invoke with --confirm to authorise. "
                f"Estimated cost: ${fm.get('cost_estimate_usd', 0):.4f}"
            ),
        )

    handler = get_handler(name)

    # Shadow-mode active flag
    shadow_until = fm.get("shadow_mode_until")
    if isinstance(shadow_until, date):
        shadow_active = date.today() < shadow_until
    elif isinstance(shadow_until, str):
        try:
            shadow_active = date.today() < date.fromisoformat(shadow_until)
        except ValueError:
            shadow_active = False
    else:
        shadow_active = False

    ctx = SkillContext(
        name=name,
        version=str(fm.get("version", "0.0.0")),
        args=args,
        frontmatter=fm,
        invoked_at=datetime.utcnow(),
        shadow_mode_active=shadow_active,
    )

    start = time.time()
    try:
        result = handler(ctx)
    except Exception as exc:  # noqa: BLE001 — runtime captures all handler failures
        import traceback
        result = SkillResult(
            success=False,
            error_message=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}",
        )
    duration = time.time() - start

    # Persist telemetry — always, success or failure
    _persist_invocation(
        name=name,
        version=ctx.version,
        args=args,
        result=result,
        duration_seconds=duration,
        shadow_mode_active=shadow_active,
    )

    return result


# ── Telemetry persistence ─────────────────────────────────────────────────


def _persist_invocation(
    *,
    name: str,
    version: str,
    args: dict[str, Any],
    result: SkillResult,
    duration_seconds: float,
    shadow_mode_active: bool,
) -> int:
    """Write one SkillInvocation row. Returns the new row id."""
    from sqlalchemy import select

    from data.db import SessionLocal
    from data.models.schema import SkillInvocation

    pc_serialised = json.dumps([
        {
            "name": p.name,
            "pass": p.pass_,
            "observed": _safe_json(p.observed),
            "expected": _safe_json(p.expected),
        }
        for p in result.postconditions
    ])
    anomalies_serialised = (
        json.dumps([_safe_json(a) for a in result.anomalies])
        if result.anomalies else None
    )

    with SessionLocal() as s:
        inv = SkillInvocation(
            skill_name=name,
            skill_version=version,
            args_json=json.dumps(args),
            success=result.success,
            duration_seconds=duration_seconds,
            tool_calls_count=result.tool_calls_count,
            tokens_prompt=result.tokens_prompt,
            tokens_completion=result.tokens_completion,
            cost_usd=result.cost_usd,
            postconditions_json=pc_serialised,
            shadow_mode_active=shadow_mode_active,
            anomalies_json=anomalies_serialised,
            error_message=result.error_message,
        )
        s.add(inv)
        s.commit()
        return inv.id


def _safe_json(value: Any) -> Any:
    """Best-effort JSON serialisation — fall back to str() for opaque types."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ── Shadow-mode introspection ─────────────────────────────────────────────


def shadow_mode_status(name: str) -> dict[str, Any]:
    """Return shadow-mode progress for a skill.

    Used by the CLI display and by the skill bodies when they need to
    surface graduation progress to the user.
    """
    from sqlalchemy import func, select

    from data.db import SessionLocal
    from data.models.schema import SkillInvocation

    with SessionLocal() as s:
        total = s.execute(
            select(func.count(SkillInvocation.id))
            .where(SkillInvocation.skill_name == name)
        ).scalar() or 0
        clean = s.execute(
            select(func.count(SkillInvocation.id))
            .where(SkillInvocation.skill_name == name)
            .where(SkillInvocation.success.is_(True))
            .where(SkillInvocation.anomalies_json.is_(None))
        ).scalar() or 0

    fm = load_skill_frontmatter(name)
    su = fm.get("shadow_mode_until")
    if isinstance(su, str):
        try:
            su = date.fromisoformat(su)
        except ValueError:
            su = None
    days_remaining = (su - date.today()).days if isinstance(su, date) else None

    return {
        "skill_name": name,
        "version": fm.get("version"),
        "total_invocations": total,
        "clean_invocations": clean,
        "needed_to_graduate": 10,
        "shadow_mode_until": su.isoformat() if isinstance(su, date) else None,
        "days_remaining": days_remaining,
        "currently_in_shadow": (
            isinstance(su, date) and date.today() < su and clean < 10
        ),
    }
