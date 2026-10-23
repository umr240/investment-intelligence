# ADR-040 — Local Web UI: FastAPI Control-Plane + Frontend Over the Existing CLI Engine

| Field | Detail |
|---|---|
| **Status** | **Accepted** — stack decided (React + Vite + TypeScript, 2026-08-09). Not yet built. |
| **Phase** | Presentation layer / new component (additive) |
| **Supersedes** | Nothing. The Typer CLI (`cli/main.py`) remains the canonical, fully-featured entrypoint; it is not deprecated. |
| **Extends** | ADR-032 (project-local skills — `invest skill run`), ADR-039 (`FundamentalsSource` port — the precedent that proves a hexagonal boundary pays for itself), ADR-031 (data-gap register, $100/mo LLM ceiling), ADR-022 (per-field provenance disclosure), ADR-017 (warehouse `FilterTasks`) |
| **Resolves** | The system is currently terminal-only. The user wants a clickable local web UI exposing the screener engine, the deep-dive engine, and the three project-local skills as buttons — without re-deriving any scoring logic in a second codebase. |
| **Provenance** | User directive 2026-08-09: "before doing that I would need a frontend app... it has to have the screener engine like we implemented, it has to have the deep dive engine like we implemented, convert those /deep-dive /screener skills... into actionable buttons... first an implementation plan, likely an ADR." Triggered while revisiting the stale VHI.TO dive (2026-06-06, EXCLUDE 3.21/10) ahead of scheduling a re-dive post-earnings. |

---

## 0. The non-negotiable shape

This ADR is only acceptable if its proposal:

1. **Adds a seam, does not rewrite the engine.** Screener and deep-dive logic already live behind clean function boundaries — `screener/pipeline.py`, `deepdive/orchestrator.py` (`run_tier1`/`run_tier2` return a plain outcome object; `cli/main.py` does all Rich-table rendering on top of it, it does not compute anything). The web layer calls those same functions. Zero business logic is duplicated in `api/` or `frontend/` (`chestertons_fence`, `single_source_of_truth`).
2. **Preserves lazy-load-everything (CLAUDE.md §Core Design Principle).** Every button = one explicit user action = exactly the CLI-equivalent call, nothing more. Read-only views (an already-persisted scorecard, an already-registered job list) may load on page-open — they're free SQLite reads, same as `invest score-card` reading a prior run. Anything that fetches EDGAR/yfinance, spends LLM tokens, or writes a new `DeepDiveRun` requires an explicit click with the action named plainly (no auto-refresh polling that silently re-triggers a fetch).
3. **Preserves the two-permitted-Anthropic-call-sites rule (CLAUDE.md, ADR-031 §4.1, ADR-032 §1.5).** The API process never calls Anthropic/OpenAI directly. It invokes `deepdive/narrative.py` and `deepdive/external_signals.py` exactly as the CLI does today — same two call sites, one new caller (the API router) each, not a third site.
4. **Stays local-only — no new auth surface.** This is a single-user local research tool. The API binds to `127.0.0.1` only, CORS locked to the frontend's local origin, no login system in v1. Remote/LAN access is explicitly out of scope and would need its own ADR with real auth.
5. **Does not silently double-fire the scheduler.** `invest scheduler start` (existing, `BlockingScheduler`) and any new in-process scheduler this ADR adds are two ways to run jobs from the same `.ii_jobs.json` file. Running both against the same job file is a real footgun (duplicate deep-dives, duplicate LLM spend) and this ADR must name the mitigation, not hand-wave it (§3.4).
6. **`dangerous: true` skills keep their confirmation gate, verbatim.** `external-signals` (ADR-032 §2.4) requires the same explicit-confirmation discipline in the UI that it requires in a Claude Code session — a real "I understand this costs tokens and calls Anthropic" confirmation, not a single click indistinguishable from a safe action.

If any of these is violated, scrap the proposal.

---

## 1. Context

### 1.1 What exists today

- `investment-intelligence/` is CLI-only. `cli/main.py` (Typer) is the sole entrypoint. There is **no** HTTP server, no FastAPI app, anywhere in this project.
- This is deliberate and stated in the parent `CLAUDE.md`: *"Self-contained R&D project inside `next-nvidia-detector/`. Does NOT share code with the main FastAPI backend or Next.js frontend."* The Boardroom's `microservices/unified-backend` (FastAPI, port 8000) is a **different codebase** for a different product; nothing here should import from or couple to it.
- The CLI is already split cleanly into service functions vs. rendering:
  - `deepdive/orchestrator.py::run_tier1` / `run_tier2` → returns an outcome dataclass (scores, verdicts, overlay triggers, data gaps). `cli/main.py::_render_dive_outcome` turns that into Rich tables. **The service layer has zero Rich/Typer coupling already** — this is the load-bearing fact that makes this ADR cheap.
  - `screener/pipeline.py` → Tier 0–6 staged screening, DB-persisted, read back via `invest screen-show`/`screen-ls`.
  - `scheduler/jobs.py` → job registry persisted to a flat file `.ii_jobs.json` (not the SQLite DB), `register_deepdive_job`/`register_checkpoint_job`/`register_portfolio_reassessment_job`/`register_job`, `start_daemon()` runs an APScheduler `BlockingScheduler` — **foreground, blocking, must be started manually and left running**.
  - Skills (`.claude/skills/*.md`) already have a CLI surface independent of a Claude Code session: `invest skill run <name> [ticker] [--confirm]`, `invest skill list`, `invest skill status`. Only `external-signals` is `dangerous: true`.
- DB is SQLite in **WAL mode** (`data/db.py`, `PRAGMA journal_mode=WAL`) — already configured for concurrent readers + a writer, which matters because a web API process and the CLI (and, if adopted, an in-process scheduler) may all touch the same file.

### 1.2 The triggering example

`invest score-card VHI.TO` (VitalHub Corp, TSXV, Tier-3 yfinance source per ADR-039) shows a dive last run **2026-06-06**: composite 3.21/10, verdict **EXCLUDE**, F1 fail (3.0), F2 fail (1.0), F5 partial (4.5), F3/F4/F6/F7 unfeasible (insufficient history at Tier-3 depth). A new earnings report has since been released — that dive is stale and the underlying financials have moved. Re-running it is a one-line CLI call today (`invest dive VHI.TO --tier 2 --force --auto-overlays`); the user's ask is that going forward this kind of action — and the screener/skills workflows — should be clickable, not terminal-only.

### 1.3 Why a port/adapter shape, not a rewrite

Same justification as ADR-039 (`rule_of_three`): there are now three "callers" of the underlying engine — the CLI, the (proposed) HTTP API, and (already) the Claude Code `Skill` tool. Three real callers earns the abstraction. The abstraction here is smaller than ADR-039's `FundamentalsSource` port because it *already exists* — the orchestrator/pipeline functions are the seam. This ADR just adds a second caller (FastAPI routers) and a second renderer (React components instead of Rich tables) on top of a boundary that was accidentally-already hexagonal.

---

## 2. Decision

Add two new, additive components. **Zero edits to `frameworks/`, `screener/`, `deepdive/`, `overlays/`, `data/` business logic.** Small, named edits to `scheduler/jobs.py` only (§3.4).

### 2.1 `api/` — thin FastAPI pass-through (NEW, single module — not a package of routers)

**Decided (2026-08-09), superseding an earlier draft of this section:** the original draft of this ADR sketched a `routers/` package (8 files) plus a `schemas.py` of hand-written Pydantic wrapper models. That was over-built. The service functions (`run_tier1`/`run_tier2`, `screener/pipeline.py`, and — confirmed by reading `cli/skills/runtime.py` — `run_skill()`, which is already a plain deterministic Python function, not an LLM-mediated path) already return clean dataclasses/dicts. FastAPI serializes those directly (`response_model=None`, or Pydantic's `from_attributes`/dataclass support) — there is nothing for a hand-written wrapper schema to do except risk drifting from what it wraps. Fewer files, fewer places for the API to silently diverge from the CLI.

The one fact that doesn't go away: a browser tab is sandboxed JS and cannot import `deepdive.orchestrator` or open the SQLite file directly. *Some* process has to sit between a button click and the Python function call — that's what `api/app.py` is, kept as small as that requirement allows:

```
api/
├── __init__.py
└── app.py         — one FastAPI() instance, ~8-10 endpoints, each one line deep:
                      call the existing function, return its result. No schemas.py,
                      no routers/ package, no DTO layer. CORS locked to the Vite
                      dev origin + built frontend origin; binds 127.0.0.1 only;
                      startup/shutdown hooks own the embedded scheduler (§3.4).
```

The entire pattern, not a sketch:

```python
# api/app.py
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.post("/dive/{ticker}")
async def dive(ticker: str, tier: int = 2, mode: str | None = None,
               frameworks: str | None = None, force: bool = False):
    from deepdive.orchestrator import run_tier1, run_tier2
    runner = run_tier1 if tier == 1 else run_tier2
    fw = frameworks.split(",") if frameworks else None
    return await runner(ticker.upper(), mode, fw, force_refresh=force)

@app.get("/dive/{ticker}/scorecard")
async def scorecard(ticker: str):
    from deepdive.scorecard import build_scorecard   # same function `score-card` reads
    return build_scorecard(ticker.upper())

@app.post("/screener/run/{stage}")
async def screener_run(stage: str):
    from screener.pipeline import run_stage
    return await run_stage(stage)

@app.get("/screener/candidates")
async def screener_candidates():
    from screener.pipeline import list_candidates
    return list_candidates()

@app.post("/skill/{name}")
async def skill_run(name: str, ticker: str | None = None, confirm: bool = False):
    from cli.skills.runtime import run_skill
    args = {"ticker": ticker} if ticker else {}
    try:
        result = run_skill(name, args=args, confirm_dangerous=confirm)
    except PermissionError:
        # run_skill's own dangerous:true guard (ADR-032 §2.4) — not re-implemented here
        raise HTTPException(428, "dangerous:true skill requires confirm=true")
    return result

@app.get("/scheduler/jobs")
async def scheduler_jobs():
    from scheduler.jobs import list_jobs
    return list_jobs()

@app.post("/scheduler/jobs/deepdive")
async def scheduler_add_deepdive(name: str, tickers: str, cron: str,
                                  frameworks: str | None = None, tier: int = 1):
    from scheduler.jobs import register_deepdive_job, reload as reload_scheduler
    register_deepdive_job(name, cron, tickers.split(","),
                           framework_names=frameworks.split(",") if frameworks else None,
                           tier=tier)
    reload_scheduler(app.state.scheduler)   # §3.4 — makes it actually fire
    return {"ok": True}

# + DELETE /scheduler/jobs/{name}, GET /watchlist, POST /watchlist/{ticker},
#   GET /overlay/{ticker}, POST /overlay/{ticker}/run — same one-line shape throughout.
```

Roughly 10 endpoints, ~120-150 lines total, one file. If it later grows unwieldy (`rule_of_three` — not before), splitting into a small `routers/` package is a mechanical refactor with no behavior change; it is not pre-built now.

### 2.2 `frontend/` — React + Vite + TypeScript SPA (NEW directory, project root)

Panels map 1:1 to CLI command groups — this is the "convert skills/screener/dive into buttons" ask:

| Panel | Wraps | Key controls |
|---|---|---|
| **Screener** | `screen-candidates`, `screen-winners`, `screen-stage`, `screen-show` | Run-stage button per tier, sortable results table with gate pass/fail badges |
| **Deep Dive** | `invest dive`, `invest score-card` | Ticker input, tier/mode/framework selectors, force/auto-overlay checkboxes, scorecard view (framework bars, unfeasible reasons, overlay triggers, **data gaps rendered as loudly as the CLI's gap panel**) |
| **Skills** | `invest skill run` | One button per skill (`dive-complete`, `audit-completeness` — single click; `external-signals` — click opens a confirmation modal naming the cost estimate and Anthropic call, per §0.6) |
| **Scheduler** | `invest scheduler add-*`, `list`, `remove-job` | Job list (name, cron, last run), add-job forms per type (deepdive/checkpoint/portfolio-reassessment) |
| **Watchlist / Portfolio** | `invest watchlist`, `invest portfolio` | Simple list + add/remove |

The frontend renders only what the API returns — no client-side scoring, no client-side verdict logic. This mirrors the parent project's own rule for LLMs ("presentation layer only, never invents numbers"); applied here, the **frontend is presentation-layer only**.

---

## 3. Architecture & schema

### 3.1 Request flow

```
Browser (React)
   → FastAPI endpoint (api/app.py — one of ~10 one-line handlers)
       → existing service function (deepdive.orchestrator.run_tier2 /
         screener.pipeline.* / scheduler.jobs.register_deepdive_job /
         cli.skills.runtime.run_skill — same function `invest skill run` calls)
           → same SQLite DB (WAL mode) the CLI reads/writes
       ← outcome dataclass / dict — FastAPI serializes it directly, no wrapper model
← JSON
```

### 3.2 No DB schema changes

Every endpoint in §2.1 is a read or a trigger over data the DB already models. No new tables, no migration. (Contrast with ADR-039, which needed `data_source_tier` + `fx_rate_to_usd` columns — this ADR needs none.)

### 3.3 Job file concurrency (`.ii_jobs.json`)

`scheduler/jobs.py`'s `_load`/`_save` do whole-file read/write with no locking. Today only the CLI touches it, so races are theoretical. Once the API's scheduler router can also write it, two processes *can* interleave a read-modify-write. Given this is a single-user local tool and job mutations are rare, infrequent, human-triggered clicks (not a hot path), the fix is deliberately minimal: wrap `_load`/`_save` in a `filelock.FileLock(".ii_jobs.json.lock")` (new dependency, ~5 lines) rather than migrating job storage into SQLite. Migrating to SQLite is YAGNI unless contention is actually observed — noted as a future escalation, not built now.

### 3.4 The scheduler must actually fire from the UI

This is the one real design decision, not just plumbing. Today, registering a job (`invest scheduler add-deepdive`) only writes `.ii_jobs.json` — it does **not** run anything until a human separately runs `invest scheduler start` in a terminal and leaves it running. A "Schedule a deep dive" button in a web UI that silently requires the user to *also* keep a terminal open defeats the point of building the UI.

**Decision:** `api/app.py`'s FastAPI startup hook creates one process-wide `apscheduler.schedulers.asyncio.AsyncIOScheduler` (the async-compatible sibling of the CLI's `BlockingScheduler` — coexists with FastAPI's event loop instead of blocking it). It loads `.ii_jobs.json` and schedules each job against the **same** `_dispatch(name)` function `scheduler/jobs.py` already defines for the CLI daemon (zero duplication of dispatch logic). A small addition to `scheduler/jobs.py` (~15 LOC): a `reload(scheduler: AsyncIOScheduler) -> None` function that re-syncs live jobs after any add/remove — called by the API router after every mutation.

**The double-fire risk this creates:** if a user runs `invest scheduler start` (CLI daemon) *and* leaves the API server running, both processes hold their own `AsyncIOScheduler`/`BlockingScheduler` reading the same job file — every job fires twice. Mitigation, scoped honestly for a single-user tool (no distributed lock): `start_daemon()` (CLI) and the API's startup hook both write a PID + timestamp to `.ii_scheduler.lock` on start and **loudly warn** (not block — a stale lock from a crashed process shouldn't deadlock a solo user) if a live PID is already holding it. This is best-effort, documented as an accepted limitation for v1, not a solved distributed-systems problem.

---

## 4. Inversion (mandatory per CLAUDE.md §"Inversion is mandatory and primary")

| Forward | Inversion | Mitigation |
|---|---|---|
| A UI makes screening/diving effortless. | Effortless clicking defeats lazy-load — does the owner start firing EDGAR/LLM calls out of idle curiosity the way people doomscroll? | Every network- or token-costing action requires an explicit click naming the action; no auto-refresh/polling re-triggers a fetch. Skill frontmatter's `cost_estimate_usd`/`token_budget_estimate` (ADR-032) is surfaced in the UI next to the button, not hidden. |
| A polished frontend makes the system look production-ready. | Does that create false confidence in a tool whose verdicts are mostly MONITOR/EXCLUDE, and whose Tier-3 (yfinance) dives are honestly shallower than Tier-1A (SEC) dives (ADR-039 §4)? | The scorecard view renders `data_gaps`, `unfeasible` frameworks-with-reasons, and the source-tier methodology panel with the same explicitness as the CLI's Rich output — verdict labels (MONITOR/EXCLUDE/WATCHLIST) are never softened into a bare progress bar. Validation test §6.5 explicitly checks this against a Tier-3 ticker. |
| An embedded scheduler makes "set and forget" possible. | A forgotten recurring job silently burns EDGAR rate limit or LLM budget for months with no one watching. | Job list UI shows `last_run`, next cron fire, and a running monthly cost estimate against ADR-031 §3's $100/mo ceiling — visible in the UI, not just enforced deep inside `narrative.py`. |
| Buttons replace the Claude-Code `Skill()` tool invocation path. | Does bypassing the LLM-mediated skill invocation lose anything skills currently get from being read + reasoned-through by an LLM each call? | `dive-complete` / `audit-completeness` are pure deterministic workflows already reachable via `invest skill run` with no LLM in the loop — nothing is lost. `external-signals` (LLM-calling, `dangerous: true`) keeps its ADR-032 §2.4 confirmation gate 1:1 in the UI — a modal that must be explicitly acknowledged, never a single ambiguous click (§0.6). |
| The API is "just a wrapper," so it's low-risk. | What's the worst case if a router handler silently reimplements scoring logic instead of calling the existing function (drift risk)? | §6.1's byte-equivalence validation test is the gate: any handler whose JSON output doesn't numerically match the CLI's output for identical DB state fails CI before merge. |

If a UI interaction can't preserve lazy-load, gap-honesty, and the `dangerous:true` confirmation gate, it does not ship — same bar CLAUDE.md sets for the mental-model lattice itself.

---

## 5. Alternatives considered

- **Alt 1 — Vanilla JS + server-rendered fragments (FastAPI + Jinja2/htmx), zero build step.** Pro: no Node/npm toolchain in a Python-only project (`pyproject.toml` has no JS anywhere today); fits the "solo local research tool" ethos. Con: the screener/scorecard/job-status views have real client state (sortable candidate tables, per-framework score bars, live scheduler status) that gets hand-rolled painfully without a component model — would end up reimplementing a worse React.
- **Alt 2 (recommended) — React + Vite + TypeScript SPA over a JSON API.** Con: adds a Node/npm toolchain the project doesn't have today. Pro: the panel/component mapping in §2.2 is natural in React; TypeScript types can still be generated (`openapi-typescript` against FastAPI's auto-generated OpenAPI spec, which it produces even for schema-less dict/dataclass returns) so frontend/backend contracts don't silently drift — extending the same "no silent assumption" discipline CLAUDE.md applies to missing financial data.
- **Alt 3 — Skip a bespoke frontend; use FastAPI's auto-generated `/docs` (Swagger UI).** Rejected: technically exposes every endpoint as a form, but doesn't render a scorecard, doesn't group buttons by workflow, and doesn't render the gap/verdict panels honestly. Fails the actual ask.
- **Alt 4 — Extend the parent project's Next.js frontend / unified-backend instead of building new.** Rejected explicitly per this project's own CLAUDE.md boundary ("does NOT share code with the main FastAPI backend or Next.js frontend"). Mixing them now pre-empts the deliberate, eventual, considered hand-off to The Boardroom and couples two codebases of very different maturity. `frontend/` and `api/` stay inside `investment-intelligence/`.
- **Alt 5 — pywebview desktop shell (single process, no HTTP server, JS calls Python methods directly via `window.pywebview.api`).** Genuinely avoids the "why do we need an API" question — no port, no CORS, no JSON contract. Considered directly against Alt 2 (§2.1) after the user asked why a client-server split is needed at all. Rejected for this ADR: it trades a browser page (`localhost:5173`, open in any tab) for a distributed native window/process the user launches separately — a different distribution model than "a frontend app" implied. The underlying fact stands either way: *some* bridge between click and Python call is unavoidable once JS can't touch the filesystem directly; Alt 2 keeps that bridge as a thin ~10-endpoint FastAPI pass-through (§2.1) rather than eliminating it via a different UI shell. Worth revisiting if the browser-tab distribution model turns out not to matter to the user.

**Decided (2026-08-09):** Alt 2 — React + Vite + TypeScript frontend, over the thin FastAPI pass-through in §2.1 (not the router/schema layer originally drafted). Given the amount of real UI state (sortable screener tables, per-framework score bars, live scheduler job status), the component model earns its toolchain cost over hand-rolled htmx fragments — and the API's job is strictly translation (HTTP → existing function call), never a second implementation.

---

## 6. Validation plan

**Phase A (API layer) ships iff:**
1. **Byte-equivalence** — `POST /dive/VHI.TO?tier=2` returns scores/verdicts numerically identical to `invest score-card VHI.TO` for the same DB state (proves the endpoint calls, not reimplements, the engine).
2. **Lazy-load proof** — opening any UI page issues zero EDGAR/yfinance/LLM calls; a request-count assertion in tests confirms only explicit action endpoints touch the network.
3. **Dangerous-skill gate proof** — `POST /skill/external-signals` without `confirm=true` returns 428 and executes nothing (via `run_skill`'s own guard, not a re-implemented check in `api/app.py`).

**Phase B (frontend) ships iff:**
4. Screener panel reproduces `invest screen-show`'s gate pass/fail semantics.
5. Dive panel renders a scorecard equivalent to `invest score-card` for **three** tickers spanning both source tiers — NVDA (SEC Tier-1A), VHI.TO (yfinance Tier-3), AUUA.V (yfinance Tier-3) — proving the Tier-3 caveat isn't silently dropped in the UI.
6. Scheduler panel: registering a deepdive job via the UI with a near-future cron expression, and confirming (via job `last_run` or logs) that the embedded `AsyncIOScheduler` actually fires it — proving §3.4 isn't just a job-file writer with no execution behind it.

---

## 7. Consequences

| File / dir | LOC (est) | Purpose |
|---|---|---|
| `api/app.py` | ~150 | ~10 one-line-deep endpoints + CORS + scheduler lifecycle. No schemas, no routers package. |
| `scheduler/jobs.py` (edit) | ~20 | `reload()` hook + lock-file warning (§3.4) |
| `frontend/` (Vite React TS scaffold + 5 panels) | ~1200 | Screener / Dive / Skills / Scheduler / Watchlist-Portfolio panels |
| `tests/test_api/*` | ~150 | Byte-equivalence, lazy-load, dangerous-gate tests (§6.1–6.3) |

**Total ≈ 1500-1550 LOC, roughly 2-3 days** (API layer ~half a day — it's a translation layer, not new logic; frontend ~2 days).

**Preserved:** F1–F7 + overlay math (zero change) · two-Anthropic-call-sites rule · `dangerous: true` confirmation discipline (ADR-032 §2.4) · lazy-load-everything · CLI remains fully functional and canonical, untouched.

**Not decided here (separate future ADR if pursued):** remote/LAN access + real auth; migrating `.ii_jobs.json` into SQLite; SEDAR+ Tier-1B parser (ADR-039 Phase C, unrelated).

---

## 8. References

- ADR-032 — project-local skills, `dangerous: true` confirmation discipline (§2.4, preserved verbatim in §0.6/§2.2)
- ADR-039 — `FundamentalsSource` port; precedent that a hexagonal boundary (service functions with zero CLI/render coupling) makes a second caller cheap
- ADR-031 — data-gap register, $100/mo LLM cost ceiling (surfaced in Scheduler panel, §4)
- ADR-022 — per-field provenance / source-tier disclosure (preserved in scorecard rendering, §4)
- ADR-017 — warehouse `FilterTasks` (screener panel wraps `task_app`)
- CLAUDE.md — §"Core Design Principle — Lazy Load Everything", §"AI layer boundary — two permitted locations only", §"What the system must never do"
- `mental_models/engineering/`: `chestertons_fence`, `single_source_of_truth`, `boundaries_hexagonal`, `rule_of_three`, `yagni`, `respect_the_contract`, `mirror_existing_patterns`

---

*ADR-040 | Investment Intelligence Lab | 2026-08-09*

*The win here is the same shape as ADR-039's: the architecture already had a seam (service functions with no CLI coupling) — this ADR just adds a second caller and a second renderer on top of it, rather than growing a second implementation of the screener or the dive engine.*
