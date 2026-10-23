#!/usr/bin/env bash
# Session sweep — pre/post-session housekeeping for investment-intelligence.
#
# Modes:
#   start  : fast git orientation (SessionStart hook)
#   stop   : git diff summary + ruff check (Stop hook — must stay fast)
#   full   : ruff + mypy + pytest (manual: `bash .claude/session-sweep.sh full`)
#
# Stop fires on every /clear, /resume, and /compact, so the stop mode
# intentionally skips mypy/pytest. Run `full` before committing.

set -uo pipefail

MODE="${1:-stop}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || { echo "session-sweep: cannot cd to $PROJECT_ROOT" >&2; exit 1; }

uv_run() {
  # Run a tool via uv, falling back to .venv directly. Treats first arg as the
  # tool name; remaining args are passed through.
  if command -v uv >/dev/null 2>&1; then
    uv run "$@"
  elif [ -x ".venv/Scripts/python.exe" ]; then
    .venv/Scripts/python.exe -m "$@"
  elif [ -x ".venv/bin/python" ]; then
    .venv/bin/python -m "$@"
  else
    echo "(no uv and no .venv — skipping)"
    return 127
  fi
}

print_git_summary() {
  echo "── git ──"
  echo "branch:  $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo n/a)"
  echo "head:    $(git log -1 --pretty=format:'%h %s' 2>/dev/null || echo n/a)"
  local dirty
  dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  echo "dirty:   ${dirty} changed paths"
  if [ "${dirty:-0}" -gt 0 ] && [ "${dirty:-0}" -lt 20 ]; then
    git status --short 2>/dev/null | sed 's/^/         /'
  fi
}

case "$MODE" in
  start)
    echo "[session-sweep:start] $(date '+%Y-%m-%d %H:%M:%S')"
    print_git_summary
    ;;
  stop)
    echo "[session-sweep:stop] $(date '+%Y-%m-%d %H:%M:%S')"
    print_git_summary
    echo "── ruff ──"
    if uv_run ruff check . 2>&1 | tail -20; then
      :
    fi
    ;;
  full)
    echo "[session-sweep:full] $(date '+%Y-%m-%d %H:%M:%S')"
    print_git_summary
    rc=0
    echo "── ruff ──"
    uv_run ruff check . || rc=1
    echo "── mypy ──"
    uv_run mypy . --strict || rc=1
    echo "── pytest ──"
    uv_run pytest -q || rc=1
    exit "$rc"
    ;;
  *)
    echo "usage: $0 {start|stop|full}" >&2
    exit 2
    ;;
esac

exit 0
