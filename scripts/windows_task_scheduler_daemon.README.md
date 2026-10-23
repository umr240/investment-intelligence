# Windows Task Scheduler daemon — installation guide

The investment-intelligence project uses APScheduler in-process. Registered
crons registered via `invest scheduler add-deepdive` only fire while the
daemon is alive. This XML imports as a Windows scheduled
task that auto-starts on user logon and re-launches on crash.

## Quick install

```powershell
# From the project root, after replacing the two placeholders in the XML.
schtasks /Create /XML scripts\windows_task_scheduler_daemon.xml /TN "InvestmentIntelligenceScheduler"
```

That registers the task but doesn't start it immediately. To start it now
without rebooting:

```powershell
schtasks /Run /TN "InvestmentIntelligenceScheduler"
```

## Verify it's running

```powershell
# Task status
schtasks /Query /TN "InvestmentIntelligenceScheduler" /FO LIST /V

# Daemon process — should show python.exe under your user
tasklist /FI "imagename eq python.exe" /V

# Live log tail
type %USERPROFILE%\investment_intelligence_daemon.log
```

## After logon, what fires when

Once installed and on next logon (or after running `schtasks /Run`), the
daemon process keeps polling registered crons:

```bash
uv run invest scheduler list
```

shows what's queued. Today (May 12 2026) you'd see:

| Name | Cron | Next fire |
|---|---|---|
| `hims-q1-fy26` | `0 8 12 5 *` | Already past — won't refire until May 12 2027 |
| `annual-health-check` | `0 8 15 3 *` | Mar 15 2027 at 08:00 system local |
| `annual-portfolio-reassessment` | `0 8 1 3 *` | Mar 1 2027 at 08:00 system local |

## Uninstall

```powershell
schtasks /Delete /TN "InvestmentIntelligenceScheduler" /F
```

## Customisation

The XML ships with two placeholders you must replace before importing:

- **`YOUR_WINDOWS_USERNAME`** — in `<Author>` and both `<UserId>` elements.
  `echo %USERNAME%` gives the value. Importing through the Task Scheduler GUI
  re-binds the user automatically, so you can skip this that way.
- **`YOUR_PROJECT_ROOT`** — in the `<Arguments>` of `<Exec>`. The absolute path
  of your checkout. It points at `scripts\run_scheduler_daemon.bat`, which
  resolves the project root from its own location, so this is the only path you
  need to set.

`uv` is assumed to be on the system PATH (the default after the Astral
installer). If it isn't, use the full path, typically
`%USERPROFILE%\.local\bin\uv.exe`.

If `schtasks /Create /XML` fails — it is fussy about encoding and permissions —
register `scripts\run_scheduler_daemon.bat` through the Task Scheduler GUI
instead. The `.bat` needs no editing.

Triggers configured:

- **LogonTrigger enabled**: starts when your user logs in. Recommended
  because the user's environment (PATH, env vars from .env loading) is
  ready by then.
- **BootTrigger disabled**: would start before user session loads, but
  `.env` resolution and PATH may not be ready. Enable manually if you
  want the daemon up before login.

Recovery behaviour:

- **3 restart attempts**, 1 minute apart, if the daemon crashes.
- **Hidden window** (`<Hidden>true</Hidden>`) — no flickering console.
- **Stdout + stderr** logged to
  `%USERPROFILE%\investment_intelligence_daemon.log` (rotate manually
  if it gets large).

## Caveat — missed fires don't catch up

If the laptop is off when a cron should have fired, the daemon doesn't
retroactively run it on next startup. APScheduler waits for the NEXT
matching cron time. For annual jobs that's a one-year miss. For one-off
jobs (the HIMS pattern) the run is lost.

Mitigation: for time-sensitive one-off dives (earnings nights), run the
dive manually after the fact rather than depending on the cron:

```bash
uv run invest dive HIMS --full-refresh --auto-overlays
```

## Why not a Windows service?

A Windows service (with `sc create` etc.) would survive logout and be
more bulletproof. But it runs as `SYSTEM` (or a service account) which
makes `.env` resolution, user-scoped Python virtualenvs, and OAuth flows
brittle. Task Scheduler running as the logged-in user is the right
compromise for a single-user analytical workstation. If/when this project
ever moves to a server deployment, swap to `systemd` (Linux) or a proper
Windows service with explicit env var injection.
