@echo off
REM Weekly $100M-$2B screener + auto-dive pipeline.
REM
REM Triggered by Windows Task Scheduler task "Weekly Midcap Screener"
REM every Sunday at 20:00 local. Runs the Python pipeline which dives the
REM top-30 candidates with --auto-overlays (BEW + ICA + PSA + SIM
REM auto-evaluate on trigger), then assembles a ranked report.
REM
REM Expected runtime: ~90 min (30 dives × ~3 min each). No LLM cost.
REM Output:
REM   - %USERPROFILE%\weekly_screener.log (Task Scheduler stdout/stderr)
REM   - narrative_dumps/weekly_screener_report_YYYYMMDD_HHMMSS.md (ranked report)
REM   - narrative_dumps/weekly_screener_dives_YYYYMMDD_HHMMSS.log (per-dive log tails)

REM Resolve the project root from this script's own location, so the file
REM works from any checkout.
cd /d "%~dp0.."

echo. >> "%USERPROFILE%\weekly_screener.log"
echo === Weekly screener started at %DATE% %TIME% === >> "%USERPROFILE%\weekly_screener.log"

uv run python scripts/weekly_screener_pipeline.py >> "%USERPROFILE%\weekly_screener.log" 2>&1

echo === Weekly screener finished at %DATE% %TIME% (exit=%ERRORLEVEL%) === >> "%USERPROFILE%\weekly_screener.log"
