"""
Thin FastAPI pass-through over the existing CLI engine (ADR-040 §2.1).

Every handler below is a translation step and nothing else: HTTP in,
one call into an existing service function (deepdive.orchestrator,
screener.stages/persistence, overlays.detector, cli.skills.runtime,
scheduler.jobs), JSON out. No scoring logic, no persistence logic, and
no schema-wrapping layer lives in this file — see ADR-040 §0.1 and §2.1
for why that's a hard boundary, not just tidiness.

Local-only (ADR-040 §0.4): binds 127.0.0.1, no auth in v1. Run with:
    uv run uvicorn api.app:app --reload --host 127.0.0.1 --port 8000

── Postgres foresight (ADR-040 addendum, 2026-08-09) ───────────────────────
This module deliberately owns ZERO database connection code. It never
imports sqlalchemy.create_engine, never opens a session outside
`data.db.get_session` (via the service functions it calls), and never
branches on `"sqlite" in settings.database_url`. That branching already
lives in exactly one place — `data/db.py` — per `single_source_of_truth`.
The practical consequence: the day `DATABASE_URL` in `.env` changes from
`sqlite:///./investment_intelligence.db` to a Neon Postgres DSN, this
file needs zero edits. That's `boundaries_hexagonal` doing its job — the
API is on the outside of the same hexagon the CLI is on, not a new one.

What's deliberately NOT done here (`yagni` — no unused code paths):
  - No psycopg driver import, no Postgres-specific SQL, no connection
    pool tuning. `data/db.py`'s `create_engine(settings.database_url)`
    already dispatches on the URL scheme; this file doesn't need to.
  - `.ii_jobs.json` (scheduler job registry) stays a flat file for now,
    not a DB table — ADR-040 §7 flags migrating it into SQLAlchemy as a
    future step precisely because that move is free to do post-hoc: it
    would go through the same engine this API already depends on
    indirectly, not a new one.
  - The one thing that DOES change behaviourally under Postgres: SQLite
    WAL mode's single-writer semantics (data/db.py) don't apply — real
    MVCC means concurrent POST /dive requests stop being a "mostly fine
    for one local user" hazard and become a properly-handled case. No
    code change earns that; it falls out of the DSN swap.

GET /health surfaces which backend is actually live (sqlite vs postgres)
rather than assuming — same "don't hide provenance" instinct CLAUDE.md
applies to data-source tiers (ADR-022), applied here to the DB itself.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import MissingEdgarIdentityError, settings

app = FastAPI(title="Investment Intelligence — local control plane")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",  # Vite dev
        "http://localhost:4173", "http://127.0.0.1:4173",  # Vite preview
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingEdgarIdentityError)
async def _missing_edgar_identity(
    _request: Request, exc: MissingEdgarIdentityError
) -> JSONResponse:
    """Unconfigured EDGAR identity is a setup problem, not a server fault.

    Mirrors the CLI's handling: 503 with the same guidance, rather than a 500
    that reads as a bug.
    """
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ── Root ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "investment-intelligence api", "docs": "/docs", "health": "/health"}


# ── Health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    url = settings.database_url
    backend = "sqlite" if "sqlite" in url else ("postgresql" if "postgres" in url else "unknown")
    return {
        "ok": True,
        "db_backend": backend,
        "environment": settings.environment,
        "exclusion_policy": settings.exclusion_policy,
    }


# ── Overview ─────────────────────────────────────────────────────────────
# Added for the Overview/"Conviction Board" page (Claude Design import,
# 2026-08-09). Pure reads over existing tables — no schema changes. The
# mockup's own demo numbers (4,812 universe, TEM/SHOP/KLIC/ABCL rows) are
# NOT ported — every figure here is computed from real persisted rows.
# universe_count has no backing source today and is returned as null
# rather than invented; the frontend renders that as an explicit gap.

@app.get("/overview/stats")
async def overview_stats() -> dict[str, Any]:
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import DeepDiveRun
    from screener.persistence import list_screener_candidates

    cutoff = datetime.now() - timedelta(days=30)
    with get_session() as session:
        recent = session.execute(
            select(DeepDiveRun.composite_score, DeepDiveRun.verdict)
            .where(DeepDiveRun.run_date >= cutoff)
        ).all()

    composites = [r.composite_score for r in recent if r.composite_score is not None]
    verdict_counts: dict[str, int] = {}
    for r in recent:
        if r.verdict:
            verdict_counts[r.verdict] = verdict_counts.get(r.verdict, 0) + 1

    return {
        "screener_candidates": len(list_screener_candidates()),
        "deep_dives_30d": len(recent),
        "deep_dives_30d_by_verdict": verdict_counts,
        "avg_composite_30d": (sum(composites) / len(composites)) if composites else None,
        "universe_count": None,
    }


@app.get("/overview/recent-dives")
async def overview_recent_dives(limit: int = 10) -> list[dict[str, Any]]:
    """Most recent FrameworkScore row per company (deduplicated) — a ticker
    dived 4 times shows once, at its latest score, not 4 near-identical rows."""
    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import Company, FrameworkScore

    with get_session() as session:
        # Over-fetch to survive dedup, then trim to `limit` distinct companies.
        candidates = session.execute(
            select(FrameworkScore, Company)
            .join(Company, Company.id == FrameworkScore.company_id)
            .order_by(FrameworkScore.run_date.desc())
            .limit(limit * 10)
        ).all()
        seen: set[int] = set()
        rows = []
        for fs, c in candidates:
            if c.id in seen:
                continue
            seen.add(c.id)
            rows.append((fs, c))
            if len(rows) >= limit:
                break
        return [
            {
                "ticker": c.ticker, "name": c.name, "sector": c.sector,
                "stage": fs.company_stage, "composite": fs.composite_score,
                "verdict": fs.verdict, "run_date": str(fs.run_date),
                "f1": fs.f1_score, "f2": fs.f2_score, "f3": fs.f3_score,
                "f4": fs.f4_score, "f5": fs.f5_score, "f6": fs.f6_score, "f7": fs.f7_score,
            }
            for fs, c in rows
        ]


# ── Deep dive ────────────────────────────────────────────────────────────

@app.post("/dive/{ticker}")
async def dive(
    ticker: str,
    tier: int = 2,
    mode: str | None = None,
    frameworks: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Same params/semantics as `invest dive`. Auto-overlays always run
    (BEW mandatory, ICA/PSA trigger-gated) — mirrors `--auto-overlays`,
    since there's no interactive confirmation prompt to offer over HTTP."""
    from deepdive.orchestrator import run_tier1, run_tier2

    runner = run_tier1 if tier == 1 else run_tier2
    fw_list = [f.strip().upper() for f in frameworks.split(",")] if frameworks else None
    try:
        outcome = await runner(ticker.upper(), mode, fw_list, force_refresh=force)
    except NotImplementedError as exc:
        raise HTTPException(400, str(exc)) from exc
    return dataclasses.asdict(outcome)


@app.get("/dive/{ticker}/scorecard")
async def scorecard(ticker: str, mode: str | None = None) -> dict[str, Any]:
    """Reads the most recent persisted dive — no fetch, no network call.
    404 if `invest dive {ticker}` (or POST /dive/{ticker}) hasn't run yet."""
    from data.dive_staleness import latest_dive_stale_reason
    from deepdive.scorecard_view import load_scorecard_view

    view = load_scorecard_view(ticker.upper(), mode=mode)
    if view is None:
        raise HTTPException(404, f"No scorecard for {ticker.upper()}. POST /dive/{ticker.upper()} first.")
    return {**view.to_dict(), "stale_reason": latest_dive_stale_reason(ticker, mode)}  # DEC-46


# ── Narrative + Chat ─────────────────────────────────────────────────────
# Both wrap `deepdive/narrative.py` and `deepdive/conversation.py` — the
# two functions those modules already expose for exactly this purpose.
# No new Anthropic/OpenAI call site is added here (CLAUDE.md's two-
# permitted-call-sites rule): this file still never imports the SDKs
# itself, it calls into the same permitted modules `invest score-card
# --narrate` and `invest chat` already call. Real token spend either way
# (~$0.08/narrative on Claude Sonnet 4.6, measured 2026-10-23) — POST here is the explicit-
# action gate, same role `--narrate` / typing into the chat REPL plays
# in the CLI. Not auto-fired by GET or by page load.

def _latest_run_id(ticker: str) -> tuple[int, str]:
    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun

    with get_session() as session:
        co = session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if co is None:
            raise HTTPException(404, f"No company row for {ticker}.")
        run = session.execute(
            select(DeepDiveRun).where(DeepDiveRun.company_id == co.id)
            .order_by(desc(DeepDiveRun.id)).limit(1)
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(404, f"No dive runs for {ticker}. POST /dive/{ticker} first.")
        return run.id, run.mode


@app.get("/dive/{ticker}/narrative")
async def get_narrative(ticker: str) -> dict[str, Any]:
    """Reads whatever's already persisted on the latest DeepDiveRun —
    free, no LLM call. {"generated": false} if narrative was never run."""
    import json as _json

    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun

    ticker = ticker.upper()
    with get_session() as session:
        co = session.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if co is None:
            raise HTTPException(404, f"No company row for {ticker}.")
        run = session.execute(
            select(DeepDiveRun).where(DeepDiveRun.company_id == co.id)
            .order_by(desc(DeepDiveRun.id)).limit(1)
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(404, f"No dive runs for {ticker}. POST /dive/{ticker} first.")
        from data.dive_staleness import dive_withheld_reason

        withheld = dive_withheld_reason(run)  # DEC-46/47
        if withheld:
            return {"generated": False, "stale": True, "stale_reason": withheld}
        if not run.bull_narrative:
            return {"generated": False}
        risk_data = _json.loads(run.risk_factors)
        return {
            "generated": True,
            "run_id": run.id,
            "one_liner": risk_data.get("one_liner", ""),
            "bull": _json.loads(run.bull_narrative),
            "bear": _json.loads(run.bear_narrative),
            "risks": risk_data.get("risks", []),
            "data_caveats": risk_data.get("data_caveats", []),
            "audit": risk_data.get("_audit", {}),
        }


@app.post("/dive/{ticker}/narrative")
async def post_narrative(ticker: str, provider: str | None = None) -> dict[str, Any]:
    """Explicit-action endpoint — spends real Anthropic/OpenAI tokens.
    Generates via deepdive/narrative.py's permitted call site, persists
    onto the latest DeepDiveRun via persist_narrative (same as `invest
    score-card --narrate`), and returns the fresh body."""
    from deepdive.narrative import (
        NarrativeOnStaleDiveError,
        NarrativeUnavailableError,
        generate_narrative,
        persist_narrative,
    )
    from deepdive.scorecard_view import load_scorecard_view

    ticker = ticker.upper()
    view = load_scorecard_view(ticker)
    if view is None:
        raise HTTPException(404, f"No scorecard for {ticker}. POST /dive/{ticker} first.")

    try:
        narrative = generate_narrative(view, provider_pref=provider)
    except NarrativeOnStaleDiveError as exc:
        raise HTTPException(409, f"{exc}. Re-run the dive, then generate.") from exc
    except NarrativeUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    try:
        persist_narrative(narrative)
    except NarrativeOnStaleDiveError as exc:
        raise HTTPException(409, f"{exc}. Re-run the dive, then generate.") from exc

    body = narrative.body
    return {
        "generated": True,
        "one_liner": body.one_liner,
        "bull": [p.model_dump() for p in body.bull],
        "bear": [p.model_dump() for p in body.bear],
        "risks": [r.model_dump() for r in body.risks],
        "data_caveats": list(body.data_caveats),
        "audit": {
            "provider": narrative.provider.value, "model": narrative.model,
            "prompt_tokens": narrative.prompt_tokens, "completion_tokens": narrative.completion_tokens,
            "fallback_used": narrative.fallback_used, "status": narrative.status.value,
        },
        "guard_warnings": list(narrative.guard_warnings),
    }


@app.get("/dive/{ticker}/chat")
async def get_chat(ticker: str) -> list[dict[str, Any]]:
    """Free — reads persisted deep_dive_conversations turns, no LLM call."""
    from data.dive_staleness import run_withheld_reason
    from deepdive.conversation import load_conversation_history

    run_id, _mode = _latest_run_id(ticker.upper())
    if run_withheld_reason(run_id):  # DEC-47: stored replies are withheld like narratives
        return []
    history = load_conversation_history(run_id)
    return [{"role": t.role, "content": t.content, "cost_usd": t.cost_usd} for t in history]


@app.post("/dive/{ticker}/chat")
async def post_chat(ticker: str, message: str, provider: str | None = None) -> dict[str, Any]:
    """Explicit-action endpoint — one turn, real token spend. Mirrors
    `invest chat`'s persist-user-turn-first-then-call-then-persist-reply
    pattern exactly, so a failed LLM call still keeps the user's message."""
    from data.dive_staleness import run_withheld_reason
    from deepdive.conversation import ChatTurn, generate_chat_response, load_conversation_history, persist_turn
    from deepdive.narrative import NarrativeOnStaleDiveError, NarrativeUnavailableError
    from deepdive.scorecard_view import load_scorecard_view

    ticker = ticker.upper()
    run_id, mode = _latest_run_id(ticker)
    withheld = run_withheld_reason(run_id)  # DEC-47: refuse before storing the user's turn
    if withheld:
        raise HTTPException(409, f"{ticker}: latest dive is stale ({withheld}). Re-run the dive.")
    view = load_scorecard_view(ticker, mode=mode)
    if view is None:
        raise HTTPException(404, f"ScorecardView for {ticker} could not be loaded.")

    history = load_conversation_history(run_id)
    next_turn_index = len(history)
    persist_turn(deep_dive_run_id=run_id, ticker=ticker, turn_index=next_turn_index, role="user", content=message)

    try:
        result = generate_chat_response(
            view,
            history + [ChatTurn(role="user", content=message)],
            message,
            run_id=run_id,
            provider_pref=provider,
        )
    except NarrativeOnStaleDiveError as exc:  # flagged since the check above
        raise HTTPException(409, f"{exc}. Re-run the dive.") from exc
    except NarrativeUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc

    persist_turn(
        deep_dive_run_id=run_id, ticker=ticker, turn_index=next_turn_index + 1,
        role="assistant", content=result.output.reply,
        numeric_claims=result.output.numeric_claims, guard_warnings=result.guard_warnings,
        provider=result.provider, model=result.model,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
    )
    return {
        "reply": result.output.reply,
        "provider": result.provider, "model": result.model,
        "cost_usd": result.cost_usd, "guard_warnings": result.guard_warnings,
    }


# ── Overlays ─────────────────────────────────────────────────────────────

@app.get("/overlay/{ticker}")
async def overlay_status(ticker: str) -> list[dict[str, Any]]:
    from overlays.detector import get_detected_triggers

    triggers = await get_detected_triggers(ticker.upper())
    return [dataclasses.asdict(t) for t in triggers]


@app.post("/overlay/{ticker}/run")
async def overlay_run(ticker: str, overlay_type: str) -> dict[str, Any]:
    """overlay_type: ICA | PSA | BEW. Manual trigger — same as
    `invest overlay run TICKER --type ICA`. auto_overlay_results on the
    dive outcome already covers the auto-run path; this is for re-running
    one overlay in isolation."""
    from overlays.detector import run_overlay_by_type

    try:
        result = await run_overlay_by_type(ticker.upper(), overlay_type.upper())
    except NotImplementedError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


# ── Screener ─────────────────────────────────────────────────────────────

@app.get("/screener/runs")
async def screener_runs(limit: int = 20) -> list[dict[str, Any]]:
    from screener.persistence import list_recent_runs

    return list_recent_runs(limit=limit)


@app.get("/screener/runs/{run_id}")
async def screener_run_detail(run_id: int, tier: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    from screener.persistence import load_run_results

    return load_run_results(run_id, tier=tier, limit=limit)


@app.get("/screener/candidates")
async def screener_candidates(sector: str | None = None) -> list[dict[str, Any]]:
    from screener.persistence import list_screener_candidates

    return list_screener_candidates(sector=sector)


@app.get("/screener/board")
async def screener_board() -> list[dict[str, Any]]:
    """Screener candidates LEFT-JOINed to their latest real score, if any
    — the "scored vs queued for dive" distinction the Screener page needs.
    Candidates without a dive yet return composite/verdict/f1-f7 as null
    (frontend renders that as "queued", not a fabricated zero)."""
    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import Company, FrameworkScore
    from screener.persistence import list_screener_candidates

    candidates = list_screener_candidates()
    tickers = [c["ticker"] for c in candidates]

    with get_session() as session:
        rows = session.execute(
            select(FrameworkScore, Company.ticker)
            .join(Company, Company.id == FrameworkScore.company_id)
            .where(Company.ticker.in_(tickers))
            .order_by(FrameworkScore.run_date.desc())
        ).all()
        latest_by_ticker: dict[str, Any] = {}
        for fs, ticker in rows:
            if ticker not in latest_by_ticker:
                latest_by_ticker[ticker] = {
                    "composite": fs.composite_score, "verdict": fs.verdict,
                    "f1": fs.f1_score, "f2": fs.f2_score, "f3": fs.f3_score, "f4": fs.f4_score,
                    "f5": fs.f5_score, "f6": fs.f6_score, "f7": fs.f7_score,
                }

    empty_score = {"composite": None, "verdict": None, "f1": None, "f2": None, "f3": None, "f4": None, "f5": None, "f6": None, "f7": None}
    return [{**c, **latest_by_ticker.get(c["ticker"], empty_score)} for c in candidates]


@app.post("/screener/stage/a")
async def screener_stage_a(
    run_id: int | None = None,
    cap_min: str = "50M",
    cap_max: str = "10B",
    sector: str | None = None,
    exchange: str | None = None,
    ipo_after: str | None = None,
    ipo_before: str | None = None,
    tickers: str | None = None,
    retain_days: int = 30,
) -> dict[str, Any]:
    """Heavy — yfinance-scale universe scan. Explicit-trigger only, same
    as `invest screen-stage A`; nothing here runs on page load."""
    from data.models.api_models import ScreenerParams
    from screener.stages import StageFailureGate, create_screener_run, run_stage_a

    def _parse_cap(value: str) -> float:
        v = value.upper().strip()
        for suffix, mult in [("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)]:
            if v.endswith(suffix):
                return float(v[:-1]) * mult
        return float(v)

    ipo_after_d = datetime.strptime(ipo_after, "%Y-%m-%d").date() if ipo_after else None
    ipo_before_d = datetime.strptime(ipo_before, "%Y-%m-%d").date() if ipo_before else None
    ticker_list = [t.strip().upper() for t in tickers.split(",")] if tickers else None

    params = ScreenerParams(
        region="us", cap_min=_parse_cap(cap_min), cap_max=_parse_cap(cap_max),
        sector=sector, exchange=exchange,
    )
    rid = run_id or create_screener_run(params, "B")
    try:
        state = await run_stage_a(
            rid, params, retain_days,
            ipo_after=ipo_after_d, ipo_before=ipo_before_d, test_tickers=ticker_list,
        )
    except StageFailureGate as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "run_id": rid,
        "survivors": len(state.tier3_survivors),
        "gate_funnel": state.gate_funnel,
        "exclusions": state.exclusions,
    }


@app.post("/screener/stage/b")
async def screener_stage_b(run_id: int | None = None) -> dict[str, Any]:
    from scheduler.jobs import _resume_most_recent_run
    from screener.stages import StageFailureGate, run_stage_b

    rid = run_id or _resume_most_recent_run(stage="A")
    if rid is None:
        raise HTTPException(400, "No completed Stage A run to resume.")
    try:
        state = await run_stage_b(rid)
    except StageFailureGate as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"run_id": rid, "selected": len(state.selected_tickers), "gate_funnel": state.gate_funnel}


@app.post("/screener/stage/c")
async def screener_stage_c(run_id: int | None = None, mode: str = "B") -> dict[str, Any]:
    from scheduler.jobs import _resume_most_recent_run
    from screener.stages import StageFailureGate, run_stage_c

    rid = run_id or _resume_most_recent_run(stage="B")
    if rid is None:
        raise HTTPException(400, "No completed Stage B run to resume.")
    try:
        summary = await run_stage_c(rid, mode)
    except StageFailureGate as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"run_id": rid, **summary}


# ── Skills (ADR-032) ─────────────────────────────────────────────────────

@app.get("/valuation/{ticker}")
async def valuation(
    ticker: str,
    years: int = 8,
    greenwald: bool = True,
    persist: bool = False,
) -> dict[str, Any]:
    """Both valuation engines for one ticker (ADR-027 / ADR-042).

    Thin pass-through to the same ``compute_valuation_payload`` the
    ``/intrinsic-value`` skill uses, so the UI, the CLI and the skill can never
    report different numbers for the same ticker.

    ``persist`` defaults to FALSE here, unlike the CLI. A UI render is a read;
    it should not silently write an IV row and a JSONL log line every time
    somebody clicks a button.

    The response always carries ``reliability.verdict``. A client MUST NOT
    render ``damodaran.intrinsic_value_per_share`` as a valuation when that
    verdict is ``unreliable`` — the whole point of ADR-030/042 is that a
    correct calculation on an inapplicable model anchors harder than no number.
    """
    from cli.skills.intrinsic_value import compute_valuation_payload

    payload = compute_valuation_payload(
        ticker, high_growth_years=years, persist=persist, include_greenwald=greenwald,
    )
    if payload.get("damodaran") is None and payload.get("errors"):
        raise HTTPException(404, "; ".join(payload["errors"]))
    return payload


@app.get("/skills")
async def skills_list() -> list[dict[str, Any]]:
    """Mirrors `invest skill list`, including its per-file error rows.

    Files starting with `_` (the generated `_lineage.md` index) are not skills.
    """
    from pathlib import Path

    from cli.skills.runtime import load_skill_frontmatter, shadow_mode_status

    skills_dir = Path(".claude/skills")
    out = []
    for p in sorted(skills_dir.glob("*.md")):
        if p.name.lower() == "readme.md" or p.name.startswith("_"):
            continue
        name = p.stem
        try:
            fm = load_skill_frontmatter(name)
            status = shadow_mode_status(name)
        except Exception as exc:  # noqa: BLE001 — mirrors cli/main.py::skill_list
            out.append({"name": name, "error": str(exc)})
            continue
        out.append({
            "name": name,
            "version": fm.get("version"),
            "dangerous": fm.get("dangerous", False),
            "description": fm.get("description"),
            "shadow_status": status,
        })
    return out


@app.get("/skills/{name}/status")
async def skill_status(name: str) -> dict[str, Any]:
    from cli.skills.runtime import shadow_mode_status

    try:
        return shadow_mode_status(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/skill/{name}/run")
async def skill_run(
    name: str,
    ticker: str | None = None,
    period_end: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """dangerous:true skills (currently only external-signals) require
    confirm=true — mirrors ADR-032 §2.4's confirmation gate exactly via
    `run_skill`'s own guard; this endpoint does not re-implement the check,
    it just surfaces the SkillResult's refusal as a 428 instead of a 200
    with success=false, so a UI can't accidentally treat a refusal as OK."""
    from cli.skills.runtime import run_skill

    args: dict[str, Any] = {}
    if ticker:
        args["ticker"] = ticker
    if period_end:
        args["period_end"] = period_end

    result = run_skill(name, args=args, confirm_dangerous=confirm)
    payload = dataclasses.asdict(result)
    if not result.success and "dangerous=true" in (result.error_message or ""):
        raise HTTPException(428, payload["error_message"])
    return payload


# ── Scheduler ────────────────────────────────────────────────────────────
# NOTE (follow-up, not built in this pass): `scheduler/jobs.py::_dispatch`
# calls `asyncio.run()` internally, which raises if invoked from inside an
# already-running event loop. That's exactly the situation an in-process
# AsyncIOScheduler (ADR-040 §3.4) would create — the embedded-scheduler
# half of §3.4 needs `_dispatch` reworked to be loop-safe (e.g. run the
# sync dispatch in a thread executor) before it can fire jobs live inside
# this API process. Job CRUD below is fully wired today; it writes the
# same `.ii_jobs.json` `invest scheduler start` reads — that CLI daemon
# remains the way registered jobs actually execute until the follow-up
# lands. Not silently glossed over: this is real, named, scoped work.

@app.get("/scheduler/jobs")
async def scheduler_jobs() -> list[dict[str, Any]]:
    from scheduler.jobs import list_jobs

    return list_jobs()


@app.post("/scheduler/jobs/deepdive")
async def scheduler_add_deepdive(
    name: str,
    tickers: str,
    cron: str,
    frameworks: str | None = None,
    tier: int = 1,
) -> dict[str, Any]:
    from scheduler.jobs import register_deepdive_job

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    fw_list = [f.strip().upper() for f in frameworks.split(",")] if frameworks else None
    register_deepdive_job(name, cron, ticker_list, framework_names=fw_list, tier=tier)
    return {"ok": True, "name": name}


@app.post("/scheduler/jobs/checkpoint")
async def scheduler_add_checkpoint(name: str, cron: str = "0 8 15 3 *") -> dict[str, Any]:
    from scheduler.jobs import register_checkpoint_job

    register_checkpoint_job(name, cron)
    return {"ok": True, "name": name}


@app.post("/scheduler/jobs/portfolio-reassessment")
async def scheduler_add_portfolio_reassessment(name: str, cron: str = "0 8 1 3 *") -> dict[str, Any]:
    from scheduler.jobs import register_portfolio_reassessment_job

    register_portfolio_reassessment_job(name, cron)
    return {"ok": True, "name": name}


@app.delete("/scheduler/jobs/{name}")
async def scheduler_remove_job(name: str) -> dict[str, Any]:
    from scheduler.jobs import remove_job

    remove_job(name)
    return {"ok": True, "name": name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
