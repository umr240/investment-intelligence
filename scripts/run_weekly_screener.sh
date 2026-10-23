#!/usr/bin/env bash
# Weekly $100M-$2B screener + auto-dive pipeline — macOS / Linux
# counterpart of run_weekly_screener.bat.
#
# Schedule weekly (the Windows task runs Sundays at 20:00 local). Dives the
# top-30 candidates with --auto-overlays, then assembles a ranked report.
#
# Expected runtime: ~90 min (30 dives x ~3 min each). No LLM cost.
# Output:
#   - $HOME/weekly_screener.log (stdout/stderr)
#   - narrative_dumps/weekly_screener_report_YYYYMMDD_HHMMSS.md (ranked report)
#   - narrative_dumps/weekly_screener_dives_YYYYMMDD_HHMMSS.log (per-dive tails)

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

LOG="$HOME/weekly_screener.log"

{
  echo
  echo "=== Weekly screener started at $(date '+%Y-%m-%d %H:%M:%S') ==="
} >> "$LOG"

uv run python scripts/weekly_screener_pipeline.py >> "$LOG" 2>&1
status=$?

echo "=== Weekly screener finished at $(date '+%Y-%m-%d %H:%M:%S') (exit=$status) ===" >> "$LOG"
exit "$status"
