@echo off
REM APScheduler daemon for investment-intelligence project.
REM
REM Triggered by Windows Task Scheduler task "InvestmentIntelligenceScheduler"
REM at user logon. Keeps APScheduler alive in the background so crons
REM registered via `invest scheduler add-deepdive` actually fire at their
REM scheduled times.
REM
REM This replaces the brittle /XML import path. Direct .bat invocation
REM works under restricted permissions where schtasks /Create /XML fails.
REM
REM Output: appended to %USERPROFILE%\investment_intelligence_daemon.log

REM Resolve the project root from this script's own location, so the file
REM works from any checkout.
cd /d "%~dp0.."

echo. >> "%USERPROFILE%\investment_intelligence_daemon.log"
echo === Daemon started at %DATE% %TIME% === >> "%USERPROFILE%\investment_intelligence_daemon.log"

uv run invest scheduler start >> "%USERPROFILE%\investment_intelligence_daemon.log" 2>&1

echo === Daemon exited at %DATE% %TIME% (exit=%ERRORLEVEL%) === >> "%USERPROFILE%\investment_intelligence_daemon.log"
