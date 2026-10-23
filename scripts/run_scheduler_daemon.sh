#!/usr/bin/env bash
# APScheduler daemon — macOS / Linux counterpart of run_scheduler_daemon.bat.
#
# Crons registered via `invest scheduler add-deepdive` only fire while this is
# alive. Run it from launchd (KeepAlive) or a systemd user unit rather than a
# login shell, so it survives the terminal closing.
#
# Output: appended to $HOME/investment_intelligence_daemon.log
#
# Unlike the .bat, this propagates the exit status — launchd and systemd both
# decide whether to restart from it.

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

LOG="$HOME/investment_intelligence_daemon.log"

{
  echo
  echo "=== Daemon started at $(date '+%Y-%m-%d %H:%M:%S') ==="
} >> "$LOG"

uv run invest scheduler start >> "$LOG" 2>&1
status=$?

echo "=== Daemon exited at $(date '+%Y-%m-%d %H:%M:%S') (exit=$status) ===" >> "$LOG"
exit "$status"
