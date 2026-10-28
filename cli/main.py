"""
Investment Intelligence CLI — invest <command>

All commands are lazy-load gated. Nothing runs without explicit user instruction.
Hard stops at every stage. Token cost proportional to what user explicitly requests.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from config.constants import DEFAULT_HISTORY_YEARS

# Force UTF-8 on Windows — prevents cp1252 UnicodeEncodeError from Rich Unicode glyphs
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = typer.Typer(
    name="invest",
    help="[bold]Investment Intelligence[/bold] - 7 academic frameworks, lazy-load screener.",
    add_completion=False,
    rich_markup_mode="rich",
)

overlay_app = typer.Typer(help="Diagnostic overlays (ICA / PSA / BEW).")
watchlist_app = typer.Typer(help="Manage watchlist (candidates being researched).")
portfolio_app = typer.Typer(
    help="Manage portfolio — actual holdings, tracked separately from the watchlist.",
)
scheduler_app = typer.Typer(help="Register and manage scheduled screener jobs.")
data_app = typer.Typer(help="Data management - refresh, gaps, cache.")
export_app = typer.Typer(help="Export deep dives and screener runs.")
task_app = typer.Typer(help="Warehouse filter tasks — list, run, check status.")

app.add_typer(overlay_app, name="overlay")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(scheduler_app, name="scheduler")
app.add_typer(data_app, name="data")
app.add_typer(export_app, name="export")
app.add_typer(task_app, name="task")

# force_terminal=True bypasses the legacy Windows console renderer (avoids Unicode glyphs crash)
console = Console(force_terminal=True)


class Mode(str, Enum):
    A = "A"   # F1, F2, F3 — top-journal peer-reviewed only
    B = "B"   # F1–F5 — full academic universe (default)
    C = "C"   # F1–F7 — includes practitioner-heavy F6/F7
    D = "D"   # custom


class OverlayType(str, Enum):
    ICA = "ICA"
    PSA = "PSA"
    BEW = "BEW"


class WatchlistRole(str, Enum):
    core = "core"
    satellite = "satellite"
    monitor = "monitor"


def _parse_cap(value: str) -> float:
    v = value.upper().strip()
    for suffix, mult in [("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)]:
        if v.endswith(suffix):
            return float(v[:-1]) * mult
    return float(v)


# ── Database init ─────────────────────────────────────────────────────────

@app.command("db-init")
def db_init() -> None:
    """Create or upgrade the database schema. Safe to re-run.

    Delegates to Alembic rather than ORM metadata, so the migration chain stays
    the single source of truth for schema and the stamp is always recorded.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    rprint("[green]Database schema is up to date.[/green]")


# ── Screen ────────────────────────────────────────────────────────────────

@app.command()
def screen(
    region: str = typer.Option("us", help="Region: us (only us today)"),
    cap_min: str = typer.Option("50M", help="Min market cap (e.g. 50M, 300M, 2B)"),
    cap_max: str = typer.Option("10B", help="Max market cap (e.g. 2B, 10B)"),
    sector: str | None = typer.Option(None, help="Sector substring filter"),
    exchange: str | None = typer.Option(
        None, help="Comma-separated exchange list (e.g. 'Nasdaq,NYSE')",
    ),
    policy: str | None = typer.Option(
        None,
        "--policy",
        help="Exclusion policy to apply (default: EXCLUSION_POLICY, which defaults to 'none').",
    ),
    mode: Mode | None = typer.Option(None, help="Framework mode A/B/C/D"),
    retain_days: int = typer.Option(
        30, "--retain-days",
        help="How long to retain screener_candidate ticker data before cleanup. "
             "Default 30. Override per-screen; tickers promoted to watchlist/dive "
             "are kept regardless.",
    ),
    top_after_frames: int = typer.Option(
        300, "--top-after-frames",
        help="Cap on the post-Tier-4 shortlist that proceeds to Tier 5 "
             "(per-ticker companyfacts + 7 hard gates). Tier 4 is rank-and-narrow, "
             "not a hard stop — deferred tickers re-enter on the next run.",
    ),
    warehouse: bool = typer.Option(
        False, "--warehouse",
        help="Query the warehouse instead of running the legacy 6-tier pipeline "
             "(ADR-017). Returns whatever data the per-filter tasks have populated. "
             "Run `invest task run --name <task>` first to populate columns.",
    ),
    top_n: int = typer.Option(
        30, "--top-n", help="Result limit (warehouse mode).",
    ),
    min_completeness: float = typer.Option(
        0.5, "--min-completeness",
        help="Min fraction of warehouse columns populated (warehouse mode). 0–1.",
    ),
    min_roic: float | None = typer.Option(
        None, "--min-roic", help="Min ROIC filter (warehouse mode).",
    ),
    max_debt_equity: float | None = typer.Option(
        None, "--max-debt-equity", help="Max D/E filter (warehouse mode).",
    ),
    min_fcf_margin: float | None = typer.Option(
        None, "--min-fcf-margin", help="Min FCF margin filter (warehouse mode).",
    ),
    min_framework_score: float | None = typer.Option(
        None, "--min-framework-score",
        help="Min framework composite score 0-10 (warehouse mode). "
             "Run `invest task run framework_score` to populate.",
    ),
    rank_by: str = typer.Option(
        "composite_score", "--rank-by",
        help="Rank by 'composite_score' (cheap rollup) or "
             "'framework_composite_score' (full F1-F7 verdict). Warehouse mode.",
    ),
) -> None:
    """
    Run the screener.

    Default: legacy 6-tier pipeline (Tier 0 → Tier 6, network-heavy).
    With ``--warehouse``: warehouse query mode — sub-second SQL over columns
    populated by FilterTasks (ADR-017). No network I/O. Run
    ``invest task list`` to see the tasks that maintain the warehouse.
    """
    if warehouse:
        _screen_warehouse(
            cap_min, cap_max, sector, policy, top_n,
            min_completeness, min_roic, max_debt_equity, min_fcf_margin,
            min_framework_score, rank_by,
        )
        return
    asyncio.run(_screen_async(
        region, cap_min, cap_max, sector, exchange, policy, mode,
        retain_days, top_after_frames,
    ))


def _resolve_policy(name: str | None) -> str:
    """The policy name to use; an unknown one is a usage error listing the valid names."""
    from screener.policies import UnknownPolicyError, get_policy

    try:
        return get_policy(name).name
    except UnknownPolicyError as exc:
        raise typer.BadParameter(str(exc), param_hint="--policy") from exc


def _screen_warehouse(
    cap_min: str,
    cap_max: str,
    sector: str | None,
    policy: str | None,
    top_n: int,
    min_completeness: float,
    min_roic: float | None,
    max_debt_equity: float | None,
    min_fcf_margin: float | None,
    min_framework_score: float | None,
    rank_by: str,
) -> None:
    """Synchronous warehouse query — no network I/O."""
    from data.db import get_session
    from screener.query import ScreenerQuery, run_screener

    sector_in = [sector] if sector else None
    policy_name = _resolve_policy(policy)
    q = ScreenerQuery(
        cap_min=_parse_cap(cap_min),
        cap_max=_parse_cap(cap_max),
        sector_in=sector_in,
        policy=policy_name,
        min_roic=min_roic,
        max_debt_equity=max_debt_equity,
        min_fcf_margin=min_fcf_margin,
        min_completeness=min_completeness,
        min_framework_score=min_framework_score,
        order_by=rank_by,
        top_n=top_n,
    )

    with get_session() as db:
        rows = run_screener(db, q)
        # Snapshot to dicts inside the session — Company instances detach
        # when the context manager closes the session.
        snapshots = [
            {
                "ticker": c.ticker,
                "name": c.name,
                "sector": c.sector,
                "market_cap_usd": c.market_cap_usd,
                "roic": c.roic,
                "fcf_margin": c.fcf_margin,
                "debt_to_equity": c.debt_to_equity,
                "composite_score": c.composite_score,
                "data_completeness": c.data_completeness,
                "framework_composite_score": c.framework_composite_score,
                "framework_verdict": c.framework_verdict,
            }
            for c in rows
        ]

    if not snapshots:
        rprint(
            "[yellow]Warehouse query returned 0 rows.[/yellow]\n"
            "[dim]Run `invest task status` to see how populated the warehouse is. "
            "Run `invest task run --name <task>` to populate columns.[/dim]"
        )
        return

    table = Table(
        title=f"Warehouse query (top {top_n}, exclusion policy: {policy_name})",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Ticker", style="bold cyan", width=8)
    table.add_column("Name", width=28)
    table.add_column("Sector", width=18)
    table.add_column("Cap ($B)", justify="right", width=10)
    table.add_column("ROIC", justify="right", width=8)
    table.add_column("FCF mg", justify="right", width=8)
    table.add_column("D/E", justify="right", width=8)
    table.add_column("Score", justify="right", width=8)
    table.add_column("F-Score", justify="right", width=8)
    table.add_column("Verdict", width=10)
    table.add_column("Comp.", justify="right", width=7)
    for i, s in enumerate(snapshots, 1):
        table.add_row(
            str(i), s["ticker"], (s["name"] or "")[:28],
            (s["sector"] or "—")[:18],
            f"{(s['market_cap_usd'] or 0) / 1e9:.2f}",
            f"{s['roic']:.2%}" if s["roic"] is not None else "—",
            f"{s['fcf_margin']:.2%}" if s["fcf_margin"] is not None else "—",
            f"{s['debt_to_equity']:.2f}" if s["debt_to_equity"] is not None else "—",
            f"{s['composite_score']:.3f}" if s["composite_score"] is not None else "—",
            f"{s['framework_composite_score']:.2f}"
            if s["framework_composite_score"] is not None else "—",
            s["framework_verdict"] or "—",
            f"{s['data_completeness']:.2f}" if s["data_completeness"] is not None else "—",
        )
    console.print(table)


async def _screen_async(
    region: str,
    cap_min: str,
    cap_max: str,
    sector: str | None,
    exchange: str | None,
    policy: str | None,
    mode: Mode | None,
    retain_days: int,
    top_after_frames: int,
) -> None:
    from data.models.api_models import ScreenerParams
    from screener.pipeline import run_screener

    console.print(Panel(
        "[bold cyan]Stage 0a — Parameters[/bold cyan]\n"
        f"  Region: [yellow]{region}[/yellow]  "
        f"Cap: [yellow]{cap_min}–{cap_max}[/yellow]  "
        f"Sector: [yellow]{sector or 'any'}[/yellow]  "
        f"Exclusion policy: [yellow]{_resolve_policy(policy)}[/yellow]\n\n"
        "Say [green]'ok'[/green] to confirm or override any parameter.",
        border_style="cyan",
    ))

    chosen_mode = mode
    if chosen_mode is None:
        console.print(Panel(
            "[bold cyan]Stage 0b — Framework Mode[/bold cyan]\n"
            "  A) F1, F2, F3 only        (★★★ top-journal, highest confidence)\n"
            "  B) F1–F5                   (full academic universe — [bold]default[/bold])\n"
            "  C) F1–F7                   (includes practitioner F6/F7)\n"
            "  D) Custom                  (specify subset)\n",
            border_style="cyan",
        ))
        chosen_str = typer.prompt("Mode", default="B")
        chosen_mode = Mode(chosen_str.upper())

    params = ScreenerParams(
        region=region,
        cap_min=_parse_cap(cap_min),
        cap_max=_parse_cap(cap_max),
        sector=sector,
        exchange=exchange,
        exclusion_policy=policy,
    )

    with console.status("[bold green]Running screener…[/bold green]"):
        try:
            result = await run_screener(
                params, chosen_mode.value,
                retention_days=retain_days,
                top_n_after_frames=top_after_frames,
            )
        except NotImplementedError as exc:
            rprint(f"\n[yellow]⚠ Phase complete:[/yellow] {exc}")
            return

    _render_screener_table(result)

    console.print(
        f"\n[bold]{len(getattr(result, 'clean_tier', []))} names[/bold] cleared the "
        "deep-dive threshold.\n\n"
        "Want tier-1 analysis? Name tickers or say [cyan]'top 5'[/cyan]. "
        "Say [red]'done'[/red] to stop here."
    )


@app.command("screen-ls")
def screen_ls(limit: int = typer.Option(20, help="Number of recent runs to list")) -> None:
    """List the most recent screener runs."""
    from screener.persistence import list_recent_runs
    runs = list_recent_runs(limit=limit)
    if not runs:
        rprint("[yellow]No screener runs stored yet. Run `invest screen` first.[/yellow]")
        return
    table = Table(title="Recent Screener Runs", show_lines=True)
    table.add_column("ID", style="dim", width=5)
    table.add_column("Date", width=20)
    table.add_column("Region", width=8)
    table.add_column("Mode", width=5)
    table.add_column("Universe", justify="right", width=10)
    table.add_column("Clean", justify="right", width=8)
    for r in runs:
        table.add_row(
            str(r["id"]), r["run_date"], r["region"], r["mode"],
            str(r["universe"]), str(r["passed_gates"]),
        )
    console.print(table)


@app.command("screen-show")
def screen_show(
    run_id: int = typer.Argument(..., help="Screener run ID (from `invest screen-ls`)"),
    tier: str = typer.Option("all", help="all | clean | flagged"),
    limit: int = typer.Option(50, help="Max rows to show"),
) -> None:
    """Show ranked top-N for a past screener run."""
    from screener.persistence import load_run_results
    rows = load_run_results(run_id, tier=tier, limit=limit)
    if not rows:
        rprint(f"[yellow]No results found for run {run_id} (tier={tier}).[/yellow]")
        return
    table = Table(title=f"Screener Run #{run_id} ({tier})", show_lines=True)
    # Identity columns never shrink; the wide ones give way on narrow terminals.
    table.add_column("#", style="dim", min_width=2, no_wrap=True)
    table.add_column("Ticker", style="bold cyan", min_width=6, no_wrap=True)
    table.add_column("Score", justify="right", min_width=5, no_wrap=True)
    table.add_column("Tier", min_width=7, no_wrap=True)
    table.add_column("Verdict", min_width=5)
    table.add_column("F-scores (1..7)", ratio=3)
    table.add_column("Gate Failures", ratio=2)
    for i, r in enumerate(rows, 1):
        fs = r["f_scores"]
        f_str = " ".join(
            f"{fs.get(k, 0) or 0:.1f}" for k in ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
        )
        clean_label = "[green]Clean[/green]" if r["clean"] else "[yellow]Flagged[/yellow]"
        gate_str = ", ".join(r["gate_failures"][:3])
        if len(r["gate_failures"]) > 3:
            gate_str += f" +{len(r['gate_failures']) - 3}"
        table.add_row(
            str(i), r["ticker"], f"{r['composite']:.1f}",
            clean_label, r["verdict"], f_str, gate_str,
        )
    console.print(table)


@app.command("screen-cleanup")
def screen_cleanup(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting"),
) -> None:
    """
    Archive stale screener_candidate tickers (older than retention_days).
    Drops their Financial / FinancialSourceLog / PriceHistory / etc. rows,
    sets Company.status='archived'. Watchlist + dive_history rows are
    untouched (protected).
    """
    from screener.cleanup import archive_stale_candidates
    report = archive_stale_candidates(dry_run=dry_run)

    rprint(
        f"\n[bold]{'DRY-RUN: would archive' if dry_run else 'Archived'}[/bold] "
        f"{len(report.archived_tickers)} tickers "
        f"(evaluated {report.candidates_evaluated}, "
        f"protected {len(report.skipped_protected)})"
    )
    if report.archived_tickers:
        rprint(f"[dim]archived: {', '.join(report.archived_tickers[:30])}"
               + (f" +{len(report.archived_tickers) - 30} more" if len(report.archived_tickers) > 30 else "")
               + "[/dim]")
    if report.rows_deleted_by_table:
        rprint("\n[bold]Rows deleted by table:[/bold]")
        for tbl, n in report.rows_deleted_by_table.items():
            rprint(f"  [cyan]{tbl}[/cyan]: {n}")
    if report.skipped_protected:
        rprint(f"\n[yellow]Protected (kept):[/yellow] {', '.join(report.skipped_protected[:10])}"
               + (f" +{len(report.skipped_protected) - 10} more" if len(report.skipped_protected) > 10 else ""))


@app.command("screen-stage")
def screen_stage(
    stage: str = typer.Argument(..., help="A | B | C"),
    run_id: int | None = typer.Option(None, help="Run ID to operate on"),
    mode: Mode = typer.Option(Mode.B, help="Framework mode (used for Stage C)"),
    cap_min: str = typer.Option("50M", help="Min cap (Stage A only)"),
    cap_max: str = typer.Option("10B", help="Max cap (Stage A only)"),
    sector: str | None = typer.Option(None, help="Sector filter (Stage A only)"),
    exchange: str | None = typer.Option(None, help="Exchange filter (Stage A only)"),
    ipo_after: str | None = typer.Option(
        None, "--ipo-after", help="Only keep tickers IPO'd on/after YYYY-MM-DD (Stage A only)",
    ),
    ipo_before: str | None = typer.Option(
        None, "--ipo-before", help="Only keep tickers IPO'd on/before YYYY-MM-DD (Stage A only)",
    ),
    tickers: str | None = typer.Option(
        None, "--tickers",
        help="Comma-separated test tickers (Stage A only) — bypasses SEC universe. "
             "Useful for live-testing without burning thousands of yfinance calls.",
    ),
    retain_days: int = typer.Option(30, "--retain-days"),
) -> None:
    """
    Run one stage of the staged screener pipeline.

    Stage A: universe + Tier 1-3 (yfinance heavy). Creates a NEW ScreenerRun.
    Stage B: Tier 4 frames. Resumes the most-recent run with Stage A complete.
    Stage C: Tier 5-6 + persist. Resumes the most-recent run with Stage B complete.

    Pass --run-id to operate on a specific run (e.g. retry a failed stage).
    """
    asyncio.run(_screen_stage_async(
        stage.upper(), run_id, mode, cap_min, cap_max, sector, exchange,
        ipo_after, ipo_before, tickers, retain_days,
    ))


async def _screen_stage_async(
    stage: str,
    run_id: int | None,
    mode: Mode,
    cap_min: str,
    cap_max: str,
    sector: str | None,
    exchange: str | None,
    ipo_after: str | None,
    ipo_before: str | None,
    tickers: str | None,
    retain_days: int,
) -> None:
    from data.models.api_models import ScreenerParams
    from scheduler.jobs import _resume_most_recent_run
    from screener.stages import (
        create_screener_run,
        run_stage_a,
        run_stage_b,
        run_stage_c,
    )

    if stage == "A":
        from datetime import datetime as _dt
        ipo_after_d = _dt.strptime(ipo_after, "%Y-%m-%d").date() if ipo_after else None
        ipo_before_d = _dt.strptime(ipo_before, "%Y-%m-%d").date() if ipo_before else None
        ticker_list = [t.strip().upper() for t in tickers.split(",")] if tickers else None
        params = ScreenerParams(
            region="us",
            cap_min=_parse_cap(cap_min), cap_max=_parse_cap(cap_max),
            sector=sector, exchange=exchange,
        )
        rid = run_id or create_screener_run(params, mode.value)
        rprint(f"[bold]Stage A[/bold] starting (run_id={rid})…")
        if ticker_list:
            rprint(f"[dim]Test list: {len(ticker_list)} tickers (bypassing SEC universe)[/dim]")
        if ipo_after_d or ipo_before_d:
            rprint(f"[dim]IPO window: {ipo_after_d or '...'} → {ipo_before_d or '...'}[/dim]")
        # No `console.status` spinner — it pollutes non-TTY output
        state = await run_stage_a(
            rid, params, retain_days,
            ipo_after=ipo_after_d, ipo_before=ipo_before_d,
            test_tickers=ticker_list,
        )
        rprint(f"[green]✓[/green] Stage A complete: {len(state.tier3_survivors)} survivors. "
               f"Funnel: {state.gate_funnel}")
        if state.tier3_survivors:
            rprint("[bold]Survivors:[/bold]")
            for s in state.tier3_survivors[:30]:
                rprint(f"  [cyan]{s['ticker']:8s}[/cyan] {s.get('name','')[:30]:30s} "
                       f"sector={s.get('sector','—'):20s} cap=${(s.get('market_cap') or 0)/1e9:.2f}B "
                       f"ipo=—")

    elif stage == "B":
        rid = run_id or _resume_most_recent_run(stage="A")
        if rid is None:
            rprint("[red]No completed Stage A to resume.[/red]")
            return
        rprint(f"[bold]Stage B[/bold] resuming run_id={rid}…")
        with console.status("[green]Stage B running…[/green]"):
            state = await run_stage_b(rid)
        rprint(f"[green]✓[/green] Stage B complete: {len(state.selected_tickers)} selected. "
               f"Funnel: {state.gate_funnel}")

    elif stage == "C":
        rid = run_id or _resume_most_recent_run(stage="B")
        if rid is None:
            rprint("[red]No completed Stage B to resume.[/red]")
            return
        rprint(f"[bold]Stage C[/bold] resuming run_id={rid}…")
        with console.status("[green]Stage C running…[/green]"):
            summary = await run_stage_c(rid, mode.value)
        rprint(f"[green]✓[/green] Stage C complete: {summary['scored_count']} scored "
               f"({summary['clean_count']} clean, {summary['flagged_count']} flagged). "
               f"Run #{rid} persisted.")
    else:
        rprint(f"[red]Unknown stage: {stage} (must be A, B, or C)[/red]")


@app.command("screen-candidates")
def screen_candidates(
    sector: str | None = typer.Option(None, help="Filter by sector substring"),
) -> None:
    """List current screener_candidate Company rows (eligible for promotion)."""
    from screener.persistence import list_screener_candidates
    rows = list_screener_candidates(sector=sector)
    if not rows:
        rprint("[yellow]No screener_candidate tickers. Run `invest screen` first.[/yellow]")
        return
    table = Table(title="Screener Candidates", show_lines=True)
    table.add_column("Ticker", style="bold cyan")
    table.add_column("Name", width=30)
    table.add_column("Sector", width=20)
    table.add_column("Cap ($B)", justify="right")
    table.add_column("Exclusion", width=10)
    table.add_column("Last Screened", width=12)
    table.add_column("Retention", justify="right")
    for r in rows[:200]:
        table.add_row(
            r["ticker"], r["name"][:30], r["sector"][:20],
            f"{r['market_cap_b']:.2f}", r["exclusion_status"] or "—",
            r["last_screened"], str(r["retention_days"]),
        )
    console.print(table)
    if len(rows) > 200:
        rprint(f"[dim]…showing first 200 of {len(rows)} candidates.[/dim]")


def _render_screener_table(result: object) -> None:
    table = Table(title="Screener Results (top 30)", show_lines=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Ticker", style="bold cyan", width=8)
    table.add_column("Company", width=28)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Tier", justify="center", width=8)
    table.add_column("Verdict", width=12)

    ranked = getattr(result, "ranked_tickers", [])
    for i, t in enumerate(ranked[:30], 1):
        clean = getattr(t, "clean", True)
        tier_style = "green" if clean else "yellow"
        tier_label = "Clean" if clean else "Flagged"
        table.add_row(
            str(i),
            getattr(t, "ticker", ""),
            getattr(t, "company_name", "")[:28],
            f"{getattr(t, 'total_score', 0.0):.1f}",
            f"[{tier_style}]{tier_label}[/{tier_style}]",
            getattr(t, "verdict", ""),
        )
    console.print(table)

    # Funnel summary
    funnel = getattr(result, "gate_funnel", {})
    if funnel:
        rprint("\n[bold]Funnel:[/bold]  " + "  →  ".join(
            f"[cyan]{k}[/cyan]={v}" for k, v in funnel.items()
        ))


@app.command("screen-winners")
def screen_winners(
    f1_min: float = typer.Option(4.0, "--f1-min", help="F1 minimum (default 4.0 = partial-or-better; 7.0 = strong_fit-only)"),
    f3_min: float = typer.Option(4.0, "--f3-min", help="F3 minimum (default 4.0 = partial-or-better; 7.0 = strong_fit-only)"),
    sample: int = typer.Option(0, "--sample", help="Limit pre-filter to top N candidates (0 = no limit; use for validation)"),
    no_watchlist: bool = typer.Option(False, "--no-watchlist", help="Skip auto-watchlist promotion"),
    no_redive: bool = typer.Option(False, "--no-redive", help="Use latest existing DeepDiveRun instead of force-rediving"),
    use_persisted_bew: bool = typer.Option(False, "--use-persisted-bew", help="Skip dives; read BEW from warehouse rollup (bew_overlay task). Pre-req: run `invest task run bew_overlay` first."),
    output_dir: str = typer.Option("exports", "--out-dir", help="Where to write the markdown report"),
) -> None:
    """Run the monthly extreme-winner screen across the universe.

    Selects tickers passing:
      F1 (Pre-Discovery Alpha) >= --f1-min  (default 7.0, strong_fit)
      F3 (Innovation Compounder) >= --f3-min  (default 7.0, strong_fit)
      BEW overlay verdict in {extreme_winner_candidate, moderate_winner_candidate}

    No LLM calls. No Damodaran IV. Pure deterministic SEC + framework + BEW.

    Examples:
      invest screen-winners --sample 10              # validate on 10 candidates
      invest screen-winners                          # full universe scan
      invest screen-winners --f1-min 6 --f3-min 6    # looser thresholds
      invest screen-winners --no-redive              # use existing dive data (faster)
    """
    from pathlib import Path
    from screener.tasks.winner_screen import run_winner_screen
    result = run_winner_screen(
        f1_min=f1_min,
        f3_min=f3_min,
        sample_limit=sample if sample > 0 else None,
        auto_watchlist=not no_watchlist,
        output_dir=Path(output_dir),
        force_redive=not no_redive,
        use_persisted_bew=use_persisted_bew,
    )
    rprint(f"\n[bold green]Screen complete.[/bold green]")
    rprint(f"  Universe: {result.universe_size:,}  Pre-filter candidates: {result.candidates_pre_filter}  "
           f"Winners: [bold]{result.winners_count}[/bold]")
    if result.report_path:
        rprint(f"  Report: [cyan]{result.report_path}[/cyan]")


# ── Score-card ────────────────────────────────────────────────────────────

@app.command("score-card")
def score_card(
    ticker: str = typer.Argument(..., help="Ticker to display"),
    mode: Mode | None = typer.Option(
        None, "--mode", help="Specific mode A/B/C (default: latest run regardless)",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Print the ScorecardView as JSON (machine-readable)",
    ),
    llm_context: bool = typer.Option(
        False, "--llm-context",
        help="Print the exact JSON the future AI narrative layer would consume",
    ),
    narrate: bool = typer.Option(
        False, "--narrate",
        help="Generate AI narrative (Bull/Bear/Risks) for this scorecard. "
             "Calls OpenAI by default (Anthropic fallback). Requires "
             "OPENAI_API_KEY / ANTHROPIC_API_KEY in .env. Output is "
             "validated against scorecard numbers — hallucinations are flagged.",
    ),
    narrate_provider: str | None = typer.Option(
        None, "--narrate-provider",
        help="Override provider for this call: openai | anthropic | "
             "openai_only | anthropic_only. Defaults to settings.narrative_provider.",
    ),
) -> None:
    """Render the latest scorecard for a ticker with all framework signals + overlay triggers.

    Reads from the most recent persisted dive (no API calls). Run
    [cyan]invest dive TICKER[/cyan] first if no scorecard exists yet.

    The same `ScorecardView` data structure is the contract for the future
    AI narrative layer (Phase 6) — both this CLI and the LLM consume the
    identical JSON, so any narrative the AI produces is grounded in the
    same numbers shown here.
    """
    from deepdive.scorecard_view import load_scorecard_view
    view = load_scorecard_view(ticker.upper(), mode=(mode.value if mode else None))
    if view is None:
        rprint(
            f"[yellow]No scorecard for {ticker.upper()}.[/yellow] "
            f"Run [cyan]invest dive {ticker.upper()}[/cyan] first."
        )
        raise typer.Exit(code=1)

    if json_output:
        console.print_json(view.to_llm_context())
        return
    if llm_context:
        rprint("[dim]LLM-prompt JSON (exactly what Phase 6 narrative layer would receive):[/dim]")
        console.print_json(view.to_llm_context())
        return

    _render_scorecard_view(view)

    if narrate:
        _render_narrative(view, narrate_provider)


def _render_scorecard_view(view: object) -> None:
    """Pretty-print a ScorecardView to the console using Rich panels + tables."""
    c = view.company
    cmp = view.composite

    # ── Header panel ────────────────────────────────────────────────────
    cap_str = (
        f"${c.market_cap_usd / 1e9:.2f}B" if c.market_cap_usd else "n/a"
    )
    ceo_block = c.ceo_name or "n/a"
    if c.is_founder_ceo:
        ceo_block += " (Founder)"
    if c.ceo_equity_pct is not None:
        state_marker = ""
        if (c.ceo_equity_pct_state or "") == "parser_uncertain":
            state_marker = " ⚠"
        ceo_block += f", {c.ceo_equity_pct}% equity{state_marker}"
    ipo_str = c.ipo_date.isoformat() if c.ipo_date else "n/a"

    def _ratio(value: float | None) -> str:
        """Two decimals — raw floats print 14 significant digits of noise."""
        return "n/a" if value is None else f"{value:.2f}"

    header_lines = [
        f"[bold]{c.name}[/bold] ({view.ticker})",
        f"[dim]{c.sector or 'n/a'}[/dim] / [dim]{c.industry or 'n/a'}[/dim]"
        f"   Cap [bold]{cap_str}[/bold]   Stage [bold]{view.stage.stage}[/bold]",
        f"CEO: {ceo_block}   IPO: {ipo_str}   Exchange: {c.exchange or 'n/a'}",
        f"P/E: {_ratio(c.pe_trailing)}   P/B: {_ratio(c.pb_ratio)}   "
        f"EV/EBITDA: {_ratio(c.ev_ebitda)}   Beta: {_ratio(c.beta)}",
    ]
    if c.latest_revenue is not None and c.latest_period_end is not None:
        header_lines.append(
            f"Latest annual: FY{c.latest_fiscal_year} (end {c.latest_period_end}) — "
            f"rev ${c.latest_revenue / 1e6:,.1f}M, NI ${(c.latest_net_income or 0) / 1e6:,.1f}M"
        )
    console.print(Panel(
        "\n".join(header_lines),
        title=f"[bold]{view.ticker}[/bold]  [dim]scorecard {view.run_date}  mode={view.mode_used}[/dim]",
        border_style="cyan",
    ))

    # ── Composite verdict panel ─────────────────────────────────────────
    # ADR-054: neutral colours; a high band is a ranking, not a signal to act.
    verdict_color = {
        "priority_watchlist": "cyan", "watchlist": "cyan", "monitor": "blue",
        "exclude": "red",
    }.get(cmp.verdict, "white")
    weights_str = "  ".join(
        f"{k}={v:.2f}" for k, v in sorted(cmp.weights_used.items())
    )
    composite_body = (
        f"[bold {verdict_color}]{cmp.verdict.replace('_', ' ').upper()}[/bold {verdict_color}]   "
        f"composite [bold]{cmp.score:.2f}/10[/bold]   "
        f"mode [bold]{cmp.mode_resolved}[/bold]\n"
        f"weights: {weights_str}"
    )
    if cmp.weights_renormalised:
        composite_body += "\n[dim](weights renormalised — some frameworks unfeasible)[/dim]"
    console.print(Panel(composite_body, title="[bold]Composite Verdict[/bold]",
                        border_style=verdict_color))

    # ── Framework cards (one compact line per framework + signals below) ─
    rprint("\n[bold cyan]Framework Scorecard[/bold cyan]")
    for fv in view.frameworks:
        if fv.is_unfeasible:
            rprint(
                f"  [dim]{fv.code}[/dim]  [dim]{fv.title:<24}[/dim]  "
                f"[dim]· · · · · · · · · ·[/dim]  "
                f"[dim]unfeasible — {fv.unfeasible_reason}[/dim]"
            )
            continue
        score_color = (
            "green" if fv.score >= 7.0
            else "yellow" if fv.score >= 4.0
            else "red"
        )
        bar = _score_bar(fv.score, fv.max_score)
        rprint(
            f"  [bold]{fv.code}[/bold]  {fv.title:<24}  "
            f"{bar}  "
            f"[{score_color}]{fv.score:>4.1f}/10  {fv.verdict}[/{score_color}]"
        )
        for label, val in fv.key_signals[:6]:
            rprint(f"        [dim]·[/dim] {label}: [bold]{val}[/bold]")
        if fv.notes and "contested" in fv.notes.lower():
            rprint("        [dim italic]contested signal per PROJECT_SPEC §F7[/dim italic]")

    # ── Overlay triggers ────────────────────────────────────────────────
    if view.overlay_triggers:
        ov_table = Table(title="Overlay Triggers (passive — not executed)",
                         show_lines=True, header_style="bold magenta")
        ov_table.add_column("Trigger", width=8, no_wrap=True)
        ov_table.add_column("Type", width=5, no_wrap=True)
        ov_table.add_column("Condition", overflow="fold")
        ov_table.add_column("Section", width=8, no_wrap=True)
        for t in view.overlay_triggers:
            ov_table.add_row(
                t.trigger_id, t.overlay_type, t.condition, t.framework_section,
            )
        console.print(ov_table)
        rprint(
            f"[dim]Run an overlay manually:[/dim] "
            f"[cyan]invest overlay run {view.ticker} --type ICA|PSA|BEW[/cyan]"
        )
    else:
        rprint("[dim]No overlay triggers fired.[/dim]")

    # ── External Signals (LLM-extracted) ────────────────────────────────
    # Strictly isolated from F1-F7 (above) — supplementary, audited.
    _render_external_signals(view.ticker)

    # ── Data gaps ───────────────────────────────────────────────────────
    all_gaps = list(view.fetch_data_gaps or [])
    for fv in view.frameworks:
        all_gaps.extend(fv.data_gaps or [])
    if all_gaps:
        gap_lines = "\n".join(f"  · {g}" for g in all_gaps[:12])
        if len(all_gaps) > 12:
            gap_lines += f"\n  · …and {len(all_gaps) - 12} more"
        console.print(Panel(gap_lines, title="[dim]Data gaps[/dim]",
                            border_style="dim"))


def _score_bar(score: float, max_score: float) -> str:
    """ASCII progress bar for a 0-10 score. Returns Rich-formatted text."""
    filled = int(round((score / max_score) * 10))
    filled = max(0, min(10, filled))
    color = "green" if score >= 7 else "yellow" if score >= 4 else "red"
    return f"[{color}]{'█' * filled}{'·' * (10 - filled)}[/{color}]"


def _render_narrative(view: object, provider_pref: str | None) -> None:
    """Generate + render the AI narrative panels for a scorecard view.

    Persists onto the most-recent DeepDiveRun row so re-running `score-card
    --narrate` re-generates fresh (use the persisted text via export). Guard
    warnings (hallucination flags) are surfaced loudly — the user sees them.
    """
    from deepdive.narrative import (
        NarrativeOnStaleDiveError,
        NarrativeUnavailableError,
        generate_narrative,
        persist_narrative,
    )
    from deepdive.narrative_output import (
        BearPoint,
        BullPoint,
        CasePoint,
        NarrativeBodyV2,
        NarrativeStatus,
    )

    rprint("\n[bold cyan]AI Narrative[/bold cyan]  [dim](generating...)[/dim]")

    try:
        narrative = generate_narrative(view, provider_pref=provider_pref)  # type: ignore[arg-type]
    except NarrativeOnStaleDiveError as e:
        rprint(f"[yellow]Narrative withheld:[/yellow] {e}")
        rprint(f"[dim]Re-run `invest dive {view.ticker}`, then --narrate.[/dim]")
        return
    except NarrativeUnavailableError as e:
        rprint(f"[red]Narrative unavailable:[/red] {e}")
        rprint(
            "[dim]Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY in .env, "
            "then re-run with --narrate.[/dim]"
        )
        return

    audit = (
        f"[dim]provider={narrative.provider.value}  model={narrative.model}  "
        f"prompt_tok={narrative.prompt_tokens}  comp_tok={narrative.completion_tokens}"
    )
    if narrative.fallback_used:
        audit += f"  [yellow]fallback used[/yellow] ({narrative.fallback_reason})"
    audit += "[/dim]"
    rprint(audit)

    body = narrative.rendered or narrative.body  # v2: placeholders filled in (ADR-045)
    rprint(Panel(
        f"[italic]{body.one_liner}[/italic]",
        title="[bold]Thesis[/bold]",
        border_style="cyan",
    ))
    if isinstance(body, NarrativeBodyV2):
        verdict_lines = [
            f"[bold]{body.verdict.value}[/bold]. {body.verdict_reason}",
            f"Owner-operator answer: {body.owner_operator_answer.value}  ·  "
            f"Moat direction: {body.moat_direction.value}",
            *(f"  · [dim]{t.field_id}[/dim]: {t.condition}" for t in body.triggers),
        ]
        rprint(Panel("\n".join(verdict_lines), title="[bold]Verdict[/bold]", border_style="cyan"))

    if body.bull:
        bull_lines: list[str] = []
        bull_points: list[BullPoint | BearPoint | CasePoint] = [*body.bull]
        for i, p in enumerate(bull_points, 1):
            cites = (" [dim]" + ", ".join(p.framework_codes) + "[/dim]") if p.framework_codes else ""
            bull_lines.append(f"[bold]{i}. {p.headline}[/bold]{cites}")
            bull_lines.append(f"   {p.detail}")
        rprint(Panel("\n".join(bull_lines), title="[green]Bull[/green]",
                     border_style="green"))

    if body.bear:
        bear_lines: list[str] = []
        bear_points: list[BullPoint | BearPoint | CasePoint] = [*body.bear]
        for i, p in enumerate(bear_points, 1):
            cites = (" [dim]" + ", ".join(p.framework_codes) + "[/dim]") if p.framework_codes else ""
            bear_lines.append(f"[bold]{i}. {p.headline}[/bold]{cites}")
            bear_lines.append(f"   {p.detail}")
        rprint(Panel("\n".join(bear_lines), title="[red]Bear[/red]",
                     border_style="red"))

    if body.risks:
        risk_lines = []
        for r in body.risks:
            sev_color = (
                "red" if r.severity.lower() == "high"
                else "yellow" if r.severity.lower() == "medium"
                else "dim"
            )
            risk_lines.append(
                f"[{sev_color}]●[/{sev_color}] [bold]{r.severity.upper():<6}[/bold] "
                f"{r.factor}  [dim](grounded: {r.grounded_in})[/dim]"
            )
        rprint(Panel(
            "\n".join(risk_lines) + (
                "\n\n[dim italic]Thesis-validation checkpoints — conditions to "
                "monitor across the 5-year hold, NOT stop-loss triggers.[/dim italic]"
            ),
            title="[magenta]Thesis-Validation Checkpoints[/magenta]",
            border_style="magenta",
        ))

    if body.data_caveats:
        caveat_text = "\n".join(f"  · {c}" for c in body.data_caveats)
        rprint(Panel(caveat_text, title="[dim]Data caveats (per LLM)[/dim]",
                     border_style="dim"))

    # Guard warnings — surface loudly. This is the safety net. Formatting notes
    # ride in the same list but are cosmetic, so they show separately and never
    # carry the grounding-failure verdict.
    grounding = [w for w in narrative.guard_warnings if not w.startswith("formatting: ")]
    formatting = [w for w in narrative.guard_warnings if w.startswith("formatting: ")]

    if narrative.status == NarrativeStatus.GUARD_FAILED and grounding:
        rprint(Panel(
            "\n".join(f"  ⚠ {w}" for w in grounding[:12])
            + (f"\n  …and {len(grounding) - 12} more" if len(grounding) > 12 else ""),
            title="[red]Hallucination guard warnings[/red]",
            border_style="red",
        ))
        rprint(
            "[red]Treat narrative with extra scrutiny — numeric/citation "
            "validation failed.[/red]"
        )

    if formatting:
        rprint(Panel(
            "\n".join(f"  · {w.removeprefix('formatting: ')}" for w in formatting),
            title="[yellow]Output trimmed to schema limits[/yellow]",
            border_style="yellow",
        ))

    # Persist (best-effort — silent if no DeepDiveRun row).
    try:
        if persist_narrative(narrative):
            rprint("[dim](narrative persisted to deepdive_runs)[/dim]")
    except NarrativeOnStaleDiveError as e:
        rprint(f"[yellow]Narrative not stored:[/yellow] {e}")


# ── Chat (Phase 5L — conversational dive) ────────────────────────────────


@app.command()
def chat(
    ticker: str = typer.Argument(..., help="Ticker to chat about. Must have a prior dive."),
    run_id: int | None = typer.Option(
        None, "--run-id",
        help="Specific DeepDiveRun ID to ground the conversation in. "
             "Defaults to the latest dive for the ticker.",
    ),
    provider: str | None = typer.Option(
        None, "--provider",
        help="Override LLM provider: openai | anthropic | openai_only | anthropic_only. "
             "Defaults to settings.narrative_provider.",
    ),
    budget_usd: float = typer.Option(
        2.0, "--budget",
        help="Per-session token-cost budget in USD. Warns at 50%, halts at 100% "
             "with a confirmation prompt to continue.",
    ),
) -> None:
    """Conversational dive — multi-turn LLM Q&A grounded in the latest scorecard.

    Loads the most recent DeepDiveRun for the ticker (or --run-id), then opens
    a REPL. Each turn passes the system prompt + frozen ScorecardView JSON +
    sliding window of last 8 turns + your message to the LLM. Replies are
    validated: every numeric_claim's field_path must resolve into the
    ScorecardView. Mismatches surface as guard warnings, not silent corruption.

    Persistence: every turn writes to deep_dive_conversations. On re-launch
    (same ticker + same DeepDiveRun) the prior conversation is replayed.

    Slash commands inside the REPL:
      /budget    show remaining session budget
      /history   list prior turns in this conversation (one-line each)
      /clear     start a fresh conversation against the same dive (writes new turn_index 0+)
      /exit      end the session (Ctrl-D / Ctrl-C also work)
    """
    asyncio.run(_chat_async(ticker.upper(), run_id, provider, budget_usd))


async def _chat_async(
    ticker: str,
    run_id: int | None,
    provider_pref: str | None,
    budget_usd: float,
) -> None:
    import json as _json

    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveConversation, DeepDiveRun
    from deepdive.conversation import (
        ChatTurn,
        generate_chat_response,
        load_conversation_history,
        persist_turn,
    )
    from deepdive.narrative import NarrativeOnStaleDiveError, NarrativeUnavailableError
    from deepdive.scorecard_view import load_frozen_scorecard_view

    # Resolve the DeepDiveRun this conversation grounds in
    with get_session() as db:
        co = db.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if not co:
            rprint(f"[red]No Company row for {ticker}.[/red] Run [cyan]invest dive {ticker}[/cyan] first.")
            raise typer.Exit(code=1)
        if run_id is not None:
            run = db.execute(
                select(DeepDiveRun).where(DeepDiveRun.id == run_id)
            ).scalar_one_or_none()
            if run is None or run.company_id != co.id:
                rprint(f"[red]Run id={run_id} not found or doesn't belong to {ticker}.[/red]")
                raise typer.Exit(code=1)
        else:
            run = db.execute(
                select(DeepDiveRun).where(DeepDiveRun.company_id == co.id)
                .order_by(desc(DeepDiveRun.id)).limit(1)
            ).scalar_one_or_none()
            if run is None:
                rprint(
                    f"[red]No dive runs found for {ticker}.[/red] "
                    f"Run [cyan]invest dive {ticker}[/cyan] first."
                )
                raise typer.Exit(code=1)
        active_run_id = int(run.id)
        active_run_mode = run.mode
        active_run_date = run.run_date

    from data.dive_staleness import run_withheld_reason

    withheld = run_withheld_reason(active_run_id)  # DEC-47
    if withheld:
        rprint(f"[yellow]Chat withheld:[/yellow] run #{active_run_id} is stale ({withheld}).")
        rprint(f"[dim]Re-run `invest dive {ticker}`, then chat.[/dim]")
        raise typer.Exit(code=1)

    view = load_frozen_scorecard_view(active_run_id)  # the view this dive saw, not today's
    if view is None:
        rprint(f"[red]Run #{active_run_id} has no readable frozen ScorecardView (DEC-46).[/red]")
        rprint(f"[dim]Re-run `invest dive {ticker}`, then chat.[/dim]")
        raise typer.Exit(code=1)

    # Load prior conversation for this run
    history = load_conversation_history(active_run_id)
    next_turn_index = len(history)

    # Tally prior cost
    spent = sum(t.cost_usd or 0.0 for t in history)

    rprint(Panel(
        f"[bold]{ticker}[/bold]  ·  run #{active_run_id}  ·  mode {active_run_mode}  ·  "
        f"composite {view.composite.score:.2f}  ·  verdict [bold]{view.composite.verdict}[/bold]\n"
        f"[dim]grounded in dive run dated {active_run_date}.[/dim]\n"
        f"[dim]prior turns: {next_turn_index}  ·  prior spend: ${spent:.4f} / budget ${budget_usd:.2f}[/dim]\n"
        f"[dim]commands: /budget · /history · /clear · /exit[/dim]",
        title="invest chat", border_style="cyan",
    ))

    if history:
        rprint(f"\n[dim]Resuming prior conversation ({next_turn_index} turns persisted)…[/dim]\n")

    try:
        while True:
            try:
                user_msg = console.input("[bold cyan]>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                rprint("\n[dim]session ended.[/dim]")
                break
            if not user_msg:
                continue

            # Slash commands
            if user_msg.startswith("/"):
                cmd = user_msg.lower().split()[0]
                if cmd in ("/exit", "/quit", "/bye"):
                    rprint("[dim]session ended.[/dim]")
                    break
                if cmd == "/budget":
                    remaining = budget_usd - spent
                    bar = "green" if remaining > budget_usd * 0.5 else "yellow" if remaining > 0 else "red"
                    rprint(
                        f"[{bar}]spent ${spent:.4f} / ${budget_usd:.2f}  "
                        f"({remaining:+.4f} remaining)[/{bar}]"
                    )
                    continue
                if cmd == "/history":
                    if not history:
                        rprint("[dim](no turns yet)[/dim]")
                    for i, t in enumerate(history):
                        snippet = t.content[:120].replace("\n", " ")
                        rprint(f"  [dim]{i}[/dim] [{t.role:9s}] {snippet}…")
                    continue
                if cmd == "/clear":
                    rprint("[yellow]Conversation cleared (DB rows preserved). New turns continue at the next index.[/yellow]")
                    history = []
                    continue
                rprint(f"[yellow]unknown command: {cmd}. try /budget /history /clear /exit[/yellow]")
                continue

            # Budget check
            if spent >= budget_usd:
                confirm = console.input(
                    f"[red]budget exhausted ($spent={spent:.4f} / cap=${budget_usd:.2f}). continue? (y/N) [/red]"
                ).strip().lower()
                if confirm != "y":
                    rprint("[dim]session ended (budget cap).[/dim]")
                    break
                budget_usd += 1.0    # add another $1 buffer

            # Persist the user turn first (so it's preserved even if the LLM call fails)
            persist_turn(
                deep_dive_run_id=active_run_id, ticker=ticker,
                turn_index=next_turn_index, role="user", content=user_msg,
            )
            history.append(ChatTurn(role="user", content=user_msg))
            next_turn_index += 1

            # Call the LLM
            try:
                with console.status("[dim]thinking…[/dim]"):
                    result = generate_chat_response(
                        view,
                        history[:-1] + [ChatTurn(role="user", content=user_msg)],
                        user_msg,
                        run_id=active_run_id,
                        provider_pref=provider_pref,
                    )
            except NarrativeOnStaleDiveError as exc:  # flagged mid-session
                rprint(f"[yellow]Chat withheld:[/yellow] {exc}. Re-run `invest dive {ticker}`.")
                break
            except NarrativeUnavailableError as exc:
                rprint(f"[red]LLM unavailable:[/red] {exc}")
                continue

            spent += result.cost_usd

            # Render the assistant turn
            rprint(Panel(
                result.output.reply,
                title=f"[dim]assistant · {result.provider}/{result.model}  ·  "
                      f"+${result.cost_usd:.4f}  ·  spent ${spent:.4f}/${budget_usd:.2f}[/dim]",
                border_style="green",
            ))
            if result.output.numeric_claims:
                rprint(f"[dim]  numeric claims grounded: {len(result.output.numeric_claims)}[/dim]")
            if result.guard_warnings:
                rprint("[yellow]  guard warnings:[/yellow]")
                for w in result.guard_warnings:
                    rprint(f"    [yellow]· {w}[/yellow]")

            # Persist the assistant turn
            persist_turn(
                deep_dive_run_id=active_run_id, ticker=ticker,
                turn_index=next_turn_index, role="assistant",
                content=result.output.reply,
                numeric_claims=result.output.numeric_claims,
                guard_warnings=result.guard_warnings,
                provider=result.provider, model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=result.cost_usd,
            )
            history.append(ChatTurn(
                role="assistant", content=result.output.reply,
                numeric_claims=result.output.numeric_claims,
                guard_warnings=result.guard_warnings,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=result.cost_usd,
            ))
            next_turn_index += 1

            # Budget warning at 50%
            if spent >= budget_usd * 0.5 and spent - result.cost_usd < budget_usd * 0.5:
                rprint(
                    f"[yellow]half-budget reached: ${spent:.4f} / ${budget_usd:.2f}[/yellow]"
                )
    finally:
        rprint(f"\n[dim]final spend: ${spent:.4f}  ·  turns: {next_turn_index}  ·  run #{active_run_id}[/dim]")


# ── Dive ──────────────────────────────────────────────────────────────────

@app.command()
def dive(
    tickers: list[str] = typer.Argument(..., help="Ticker(s) for deep-dive"),
    tier: int = typer.Option(1, min=1, max=2, help="Tier 1 (quick) or Tier 2 (full)"),
    mode: Mode | None = typer.Option(
        None, help="Optional preset mode (A/B/C). If omitted, runs all 7 frameworks.",
    ),
    frameworks: str | None = typer.Option(
        None, "--frameworks",
        help="Comma-separated framework override (e.g. 'F1' or 'F1,F5'). "
             "Takes precedence over --mode. The data layer fetches only what "
             "those frameworks declare in DATA_REQUIREMENT.",
    ),
    force: bool = typer.Option(
        False, "--force", "--full-refresh",
        help="Force a FULL refetch of fundamentals before scoring: bypasses "
             "the year-coverage gate AND the known-accessions skip list, so "
             "companyfacts is re-pulled from SEC. Composite score is "
             "recomputed and persisted to FrameworkScore on every dive "
             "regardless — this flag controls the upstream FETCH only.",
    ),
    no_overlays: bool = typer.Option(
        False, "--no-overlays",
        help="Skip the post-dive overlay confirmation prompt. Triggers are "
             "still detected and persisted; overlays just don't execute.",
    ),
    auto_overlays: bool = typer.Option(
        False, "--auto-overlays",
        help="Run every triggered overlay without prompting. Useful in scripts. "
             "CLAUDE.md 'Overlay detector is always passive' is preserved — "
             "this flag is the explicit user instruction that authorises execution.",
    ),
) -> None:
    """
    Deep-dive on one or more tickers.

    Default behaviour (no flags): runs ALL 7 frameworks. Frameworks unsuitable
    for the company (e.g. F7 10yr z-scores on a recent IPO) auto-skip with
    reason 'insufficient history' rather than crashing.

    Common overrides:
      invest dive NVDA                   # all 7
      invest dive NVDA --frameworks F1   # F1 only — minimal fetch (2yr)
      invest dive NVDA --mode A          # F1+F2+F3 (top-journal preset)
    """
    fw_list: list[str] | None = None
    if frameworks:
        fw_list = [f.strip().upper() for f in frameworks.split(",") if f.strip()]
    asyncio.run(_dive_async(
        [t.upper() for t in tickers], tier, mode, fw_list, force,
        no_overlays=no_overlays, auto_overlays=auto_overlays,
    ))


async def _dive_async(
    tickers: list[str],
    tier: int,
    mode: Mode | None,
    framework_names: list[str] | None,
    force: bool,
    *,
    no_overlays: bool = False,
    auto_overlays: bool = False,
) -> None:
    from deepdive.orchestrator import run_tier1, run_tier2

    mode_value = mode.value if mode else None

    for ticker in tickers:
        console.rule(f"[bold cyan]{ticker}[/bold cyan]")
        runner = run_tier1 if tier == 1 else run_tier2
        try:
            outcome = await runner(ticker, mode_value, framework_names, force_refresh=force)
        except NotImplementedError as exc:
            rprint(f"[yellow]⚠ {exc}[/yellow]")
            return

        _render_dive_outcome(outcome, tier)
        await _prompt_and_run_overlays(
            outcome, mode=mode_value or "default",
            no_prompt=no_overlays, auto=auto_overlays,
        )
        if tier == 2:
            break

    console.print(
        "\nDive complete. Say [cyan]'go TICKER --tier 2'[/cyan] to escalate, "
        "or [red]'done'[/red] to stop."
    )


# ── Overlay confirmation flow (Phase 5b — CLAUDE.md "passive detector") ──

async def _prompt_and_run_overlays(
    outcome: object,
    *,
    mode: str,
    no_prompt: bool,
    auto: bool,
) -> None:
    """Per CLAUDE.md "Overlay detector is always passive": the orchestrator
    has detected triggers and stored them on ``outcome``. This function
    presents them to the user, takes confirmation, runs only the confirmed
    overlays, and persists the results.

    Behaviour matrix:
      no_prompt=True            → skip entirely (triggers persisted, overlays don't run)
      auto=True                 → run all triggered overlay TYPES without prompting
      stdin is not a TTY        → skip the prompt, suggest manual command
      otherwise                 → prompt per overlay TYPE (ICA / PSA / BEW)
    """
    triggers = getattr(outcome, "overlay_triggers", None) or []
    ticker = getattr(outcome, "ticker", "")
    if not triggers or no_prompt:
        return

    # Group triggers by overlay type — one overlay run per type covers
    # all of its triggers (the overlay function evaluates every check).
    by_type: dict[str, list] = {}
    for t in triggers:
        otype = getattr(t, "overlay_type", "")
        if not otype:
            continue
        by_type.setdefault(otype, []).append(t)
    if not by_type:
        return

    # Phase 5j / DEC-30: ICA + PSA + BEW are all auto-run by the orchestrator
    # and feed the composite via a capped additive bonus. The CLI prompt
    # is preserved only for any *future* overlay types not in this set.
    auto_run_types = {"ICA", "PSA", "BEW"}
    if any(t in by_type for t in auto_run_types):
        ran = sorted(t for t in by_type if t in auto_run_types)
        rprint(
            f"\n[dim magenta]Auto-run overlays (no prompt): "
            f"{', '.join(ran)} — results in DeepDiveRun.overlays_results_json; "
            f"composite_score includes capped overlay bonus[/dim magenta]"
        )
    by_type = {k: v for k, v in by_type.items() if k not in auto_run_types}
    if not by_type:
        return

    interactive = sys.stdin.isatty()
    confirmed: list[str] = []
    if auto:
        confirmed = list(by_type.keys())
    elif not interactive:
        rprint(
            "\n[dim]Non-interactive shell — skipping overlay confirmation. "
            f"Re-run with `invest overlay run {ticker} --type X` to execute.[/dim]"
        )
        return
    else:
        rprint(
            f"\n[bold magenta]{len(triggers)} overlay trigger(s) fired across "
            f"{len(by_type)} overlay type(s).[/bold magenta] "
            "[dim]Confirm to run each — overlays read from stored data only "
            "(no API calls).[/dim]"
        )
        for otype, ts in by_type.items():
            tid_list = ", ".join(getattr(t, "trigger_id", "?") for t in ts)
            if typer.confirm(f"Run {otype} overlay? (triggered by {tid_list})", default=False):
                confirmed.append(otype)

    if not confirmed:
        rprint("[dim]No overlays confirmed.[/dim]")
        return

    results = await _run_confirmed_overlays(ticker, confirmed)
    _persist_overlay_results(ticker, mode=mode, results=results)


async def _run_confirmed_overlays(
    ticker: str,
    overlay_types: list[str],
) -> dict[str, dict]:
    """Execute each confirmed overlay; render compact result; return a
    map of overlay_type → result dict for persistence."""
    import json as _json

    from overlays.detector import run_overlay_by_type

    results: dict[str, dict] = {}
    for otype in overlay_types:
        try:
            result = await run_overlay_by_type(ticker, otype)
        except Exception as exc:    # noqa: BLE001
            rprint(f"[red]{otype} overlay failed: {exc}[/red]")
            results[otype] = {"ok": False, "error": str(exc)}
            continue
        if not isinstance(result, dict):
            results[otype] = {"ok": True, "raw": str(result)}
            console.print(result)
            continue

        results[otype] = result
        border = "green" if result.get("ok") else "yellow"
        title = f"[bold]{otype}[/bold] overlay — {ticker}"
        if not result.get("ok"):
            rprint(Panel(
                f"[yellow]Overlay returned ok=False[/yellow]\n"
                f"Reason: {result.get('reason', '?')}",
                title=title, border_style=border,
            ))
            continue
        parts: list[str] = []
        if "verdict" in result:
            parts.append(f"verdict: [bold]{result['verdict']}[/bold]")
        if "f5_verdict_revised" in result:
            parts.append(f"F5 revised: [bold]{result['f5_verdict_revised']}[/bold]")
        if "score" in result and "n_checks_evaluable" in result:
            parts.append(
                f"score: {result['score']}/{result['n_checks_evaluable']} checks"
            )
        if result.get("interpretation"):
            parts.append(f"\n{result['interpretation']}")
        rprint(Panel(
            "\n".join(parts) if parts else "(see JSON below)",
            title=title, border_style=border,
        ))
        rprint(f"[dim]{otype} JSON:[/dim]")
        console.print(_json.dumps(result, indent=2, default=str))

    return results


def _persist_overlay_results(
    ticker: str,
    *,
    mode: str,
    results: dict[str, dict],
) -> None:
    """Write the confirmed overlay results back to the latest DeepDiveRun
    row for this ticker, plus flip the overlay_*_run booleans on today's
    FrameworkScore. Idempotent within the same day.
    """
    if not results:
        return
    import json as _json
    from datetime import date as _date

    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun, FrameworkScore

    with get_session() as session:
        company = session.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if company is None:
            return

        latest_run = session.execute(
            select(DeepDiveRun)
            .where(DeepDiveRun.company_id == company.id)
            .order_by(desc(DeepDiveRun.run_date))
        ).scalars().first()
        if latest_run is not None:
            latest_run.overlays_results_json = _json.dumps(results, default=str)

        today_score = session.execute(
            select(FrameworkScore)
            .where(FrameworkScore.company_id == company.id)
            .where(FrameworkScore.run_date == _date.today())
            .where(FrameworkScore.mode == mode)
        ).scalar_one_or_none()
        if today_score is not None:
            today_score.overlay_ica_run = "ICA" in results
            today_score.overlay_psa_run = "PSA" in results
            today_score.overlay_bew_run = "BEW" in results
            today_score.overlay_notes = _json.dumps(
                {k: v.get("verdict") for k, v in results.items() if isinstance(v, dict)},
                default=str,
            )


_FLOAT_HEAVY_SECTORS = frozenset({
    # Industries where interest income from float (client funds, premium
    # reserves, merchant settlements) materially distorts operating_income.
    # Until FundsHeldForClients parser ships (task 5k-5), ROIC is overstated
    # for these tickers — we surface a banner.
    "Insurance — Life", "Insurance — Property & Casualty",
    "Insurance — Diversified", "Insurance — Reinsurance",
    "Insurance — Specialty", "Insurance Brokers",
    "Asset Management", "Capital Markets",
    "Banks — Diversified", "Banks — Regional",
})

_FLOAT_HEAVY_TICKERS = frozenset({
    # Curated supplement: payroll, payments, and known float carriers whose
    # yfinance industry strings don't reliably tag them as float-heavy.
    "PAYC", "PAYX", "ADP", "WDAY", "CDAY",        # payroll / HCM
    "FLT", "FIS", "FISV", "GPN", "WEX", "WU",     # payments / merchant float
    "BRK.B", "BRK.A", "MKL", "Y", "TRV", "PGR",   # insurance with large float
})


def _is_float_heavy(ticker: str, industry: str | None) -> bool:
    if ticker.upper() in _FLOAT_HEAVY_TICKERS:
        return True
    if industry and any(industry.startswith(s) for s in _FLOAT_HEAVY_SECTORS):
        return True
    return False


def _render_roic_summary(ticker: str, pt_result: dict | None = None) -> None:
    """Render the three ROIC views — ROIC (NOPAT/IC), Pre-tax (EBIT/IC), PT.

    Phase 5k / DEC-31: dropped the "GAAP" label. Prior formula
    `NetIncome / (Equity + Debt)` was three methodology errors at once
    (NI vs NOPAT, no cash subtract, no intangible adjust) and was never
    textbook GAAP. The rebuilt formula `NOPAT / (E + D − Cash)` follows
    Damodaran/McKinsey/Stewart standard with goodwill retained in IC and
    operating leases (ASC 842) included via Total Debt.

    `pt_result` carries mode info (full | oc_only | unavailable) from the
    inline dive computation. When None we fall back to warehouse columns.
    """
    try:
        from data.db import get_session
        from data.models.schema import Company, Financial
        from data.pipeline import _effective_tax_rate
        from sqlalchemy import select, desc
        with get_session() as db:
            co = db.execute(
                select(Company).where(Company.ticker == ticker.upper())
            ).scalar_one_or_none()
            if not co:
                return
            # Phase 5k transition: warehouse `Company.roic` may still hold the
            # OLD formula (NI / (E+D)) until bulk recompute lands. Per-period
            # `Financial.roic` is populated with the new formula on every
            # dive's --full-refresh, so prefer the latest Financial annual when
            # available — gives the user the corrected number immediately.
            latest_annual = db.execute(
                select(Financial)
                .where(Financial.company_id == co.id, Financial.period == "annual")
                .order_by(desc(Financial.fiscal_year)).limit(1)
            ).scalar_one_or_none()
            industry = co.industry
            # Phase 5k-5 industry-aware float adjustment: subtract
            # investment_income_interest from EBIT for non-insurers when
            # present. Insurers (where investment income IS the business)
            # keep the unadjusted Financial.roic value.
            is_insurer = bool(
                industry and industry.lower().startswith("insurance")
            )
            float_iie = (
                latest_annual.investment_income_interest if latest_annual else None
            )
            float_fhc = (
                latest_annual.funds_held_for_clients if latest_annual else None
            )
            if (
                latest_annual is not None
                and not is_insurer
                and float_iie is not None
                and float_iie > 0
                and latest_annual.operating_income
            ):
                # Recompute ROIC with float interest stripped out
                te = latest_annual.total_equity or 0.0
                td = latest_annual.total_debt or 0.0
                cs = latest_annual.cash_and_equivalents or 0.0
                ic = te + td - cs
                if ic > 0:
                    adj_ebit = latest_annual.operating_income - float_iie
                    etr = _effective_tax_rate(
                        latest_annual.net_income, latest_annual.income_tax_expense,
                    )
                    roic = (adj_ebit * (1 - etr)) / ic
                    pretax = adj_ebit / ic
                    float_adjusted = True
                else:
                    roic = latest_annual.roic
                    pretax = latest_annual.pretax_roic
                    float_adjusted = False
            elif latest_annual is not None:
                roic = latest_annual.roic
                pretax = latest_annual.pretax_roic
                float_adjusted = False
            else:
                roic = co.roic
                pretax = co.pretax_roic
                float_adjusted = False
            roic_pt = co.pt_adjusted_roic
        if roic is None and pretax is None and roic_pt is None:
            return

        def _fmt(v: float | None) -> str:
            return f"{v*100:.2f}%" if v is not None else "—"

        pt_mode = (pt_result or {}).get("mode")
        mode_tag = ""
        if pt_mode == "oc_only":
            mode_tag = "  [yellow](OC-only — R&D not disclosed)[/yellow]"
        elif pt_mode == "full":
            mode_tag = "  [dim](full Peters-Taylor)[/dim]"

        delta_block = ""
        if roic is not None and roic_pt is not None:
            delta = (roic_pt - roic) * 100
            sign = "+" if delta >= 0 else ""
            abs_delta = abs(delta)
            colour = "red" if abs_delta >= 3.0 else "yellow" if abs_delta >= 1.0 else "dim"
            delta_block = (
                f"   [bold {colour}]PT − ROIC = {sign}{delta:.2f}pp[/bold {colour}]"
            )

        rprint(
            "\n[bold]ROIC views[/bold] (NOPAT / IC; IC = E + D − Cash; "
            "goodwill in IC; operating leases in Debt per ASC 842):"
        )
        rprint(
            f"  [cyan]ROIC[/cyan]: [bold cyan]{_fmt(roic)}[/bold cyan]"
            f"   ·   [cyan]Pre-tax[/cyan]: [cyan]{_fmt(pretax)}[/cyan]"
            f"   ·   [cyan]Peters-Taylor (non-GAAP)[/cyan]: [cyan]{_fmt(roic_pt)}[/cyan]{mode_tag}{delta_block}"
        )

        if pt_mode == "oc_only":
            rprint(
                "[dim]OC-only mode: Eisfeldt-Papanikolaou (2013) — capitalises 25% "
                "of SG&A as organisational capital. Used when R&D isn't disclosed "
                "as a separate XBRL fact.[/dim]"
            )
        else:
            rprint(
                "[dim]Peters-Taylor (2017): capitalises R&D + 25% SG&A as "
                "off-balance-sheet intangibles. ICA-5 fires at |gap| ≥ 3pp; "
                "composite swaps in PT when gap ≥ +3pp (ADR-021).[/dim]"
            )

        # Float disclosure (Phase 5k-5). Shows the magnitude of float-related
        # XBRL items so users can audit by eye. When investment_income_interest
        # is reported and ticker is non-insurer, ROIC above is auto-adjusted.
        if float_fhc or float_iie:
            fhc_str = f"${float_fhc/1e9:.2f}B" if float_fhc else "n/a"
            iie_str = f"${float_iie/1e6:.1f}M" if float_iie else "n/a"
            rprint(
                f"\n[dim]Float disclosures (5k-5): "
                f"FundsHeldForClients={fhc_str}  ·  "
                f"InvestmentIncomeInterest={iie_str}[/dim]"
            )
            if float_adjusted:
                rprint(
                    f"  [green]✓ ROIC numerator auto-adjusted[/green] [dim]— "
                    f"subtracted ${float_iie/1e6:.1f}M float interest from EBIT "
                    f"(non-insurer, Buffett float treatment)[/dim]"
                )
            elif is_insurer:
                rprint(
                    "  [dim]Insurer: investment income IS the business — "
                    "kept in numerator (Buffett-on-insurance-float retained).[/dim]"
                )
            elif float_iie is None and _is_float_heavy(ticker, industry):
                rprint(
                    "  [yellow]⚠ Float-heavy industry, but no "
                    "InvestmentIncomeInterest XBRL fact reported.[/yellow] "
                    "[dim]Verify manually that float income is reported below "
                    "operating income (PAYC-style — no contamination) or that "
                    "we're missing a custom-namespace tag.[/dim]"
                )
        elif _is_float_heavy(ticker, industry):
            rprint(
                "  [yellow]⚠ Float-heavy industry — no float-related XBRL "
                "facts found.[/yellow] [dim]Manual verification recommended.[/dim]"
            )
    except Exception:    # noqa: BLE001
        return


def _data_source_tier_for(ticker: str) -> str:
    """ADR-039: read a ticker's data_source_tier for provenance display.
    Defaults to 'sec_edgar' on any miss (never over-claims Tier-3)."""
    if not ticker:
        return "sec_edgar"
    try:
        from data.db import get_session
        from data.models.schema import Company
        with get_session() as session:
            company = session.query(Company).filter_by(ticker=ticker.upper()).first()
            return (company.data_source_tier if company else None) or "sec_edgar"
    except Exception:  # noqa: BLE001
        return "sec_edgar"


def _jurisdiction_label(ticker: str) -> str:
    """ADR-041: human venue label for the methodology panel."""
    try:
        from data.sources.jurisdiction import jurisdiction_for
        jur = jurisdiction_for(ticker)
        return f"{jur.venue}, {jur.country}" if jur.venue else jur.country
    except Exception:  # noqa: BLE001
        return "EU/EEA"


def _render_dive_outcome(outcome: object, tier: int) -> None:
    from frameworks.base import DataRequirement
    requirement = getattr(outcome, "requirement", None)
    selected = getattr(outcome, "selected_frameworks", [])
    fetch_gaps = getattr(outcome, "fetch_gaps", [])
    results = getattr(outcome, "framework_results", {})
    unfeasible = getattr(outcome, "framework_unfeasible", {})

    # ── Stage 0c: methodology disclosure (ADR-022) ──────────────────────
    # Printed BEFORE framework scores so the reader sees provenance up-front.
    # Per Munger's triangulation principle: non-GAAP without GAAP context is
    # a trap; we declare both sources and what is/isn't adjusted so the
    # reader can audit the dive without reading the ADR.
    pt_mode = (getattr(outcome, "pt_result", None) or {}).get("mode")
    pt_method_line = (
        "Non-GAAP ROIC: Peters-Taylor capitalisation"
        if pt_mode != "oc_only"
        else "Non-GAAP ROIC: Eisfeldt-Papanikolaou OC-only (R&D not disclosed)"
    )
    rd_line = (
        "  ✓ R&D → Knowledge Capital (15%/yr amortisation)"
        if pt_mode != "oc_only"
        else "  • R&D not disclosed — KC component skipped"
    )
    # ADR-039: the source line must reflect the ACTUAL FundamentalsSource —
    # never silently label yfinance Tier-3 data as SEC-grade.
    tier = _data_source_tier_for(getattr(outcome, "ticker", ""))
    if tier == "yfinance_only":
        source_line = (
            "Source: yfinance [bold yellow]Tier-3[/bold yellow] fundamentals — SEC EDGAR XBRL "
            "unavailable (non-US filer; ADR-039).\n"
            "  ⚠ Depth ~4 annual periods (vs ~10yr for US issuers); F7 z-scores, "
            "insider/proxy/10-K-text signals unavailable.\n"
            "  ⚠ Native reporting currency; ratios are currency-neutral, "
            "absolute values carry fx_rate_to_usd."
        )
        border = "yellow"
    elif tier == "sedar_plus":
        source_line = "Source: SEDAR+ Tier-1B iXBRL (Canadian regulator filing; ADR-039 Phase C)"
        border = "dim"
    elif tier == "esef":
        # ADR-041. Filing-grade, but with two limits the reader must see
        # up-front: the regime is ANNUAL-only (quarterlies are supplemented
        # from yfinance and carry Tier-3 provenance per row), and the index
        # lags by country.
        jur = _jurisdiction_label(getattr(outcome, "ticker", ""))
        source_line = (
            f"Source: ESEF iXBRL [bold green]Tier-1B[/bold green] — EU/EEA regulator "
            f"filing via filings.xbrl.org ({jur}; ADR-041).\n"
            "  • Annual figures are FILING-GRADE (audited, IFRS taxonomy, "
            "validation-scored).\n"
            "  ⚠ ESEF is an ANNUAL regime: quarterly rows are supplemented from "
            "yfinance and remain Tier-3 — check Financial.source per row.\n"
            "  ⚠ Index lag is per-country; the newest fiscal year may be absent.\n"
            "  ⚠ Notes are block-tagged: customer concentration, insider and "
            "proxy signals are NOT extractable — they stay explicit gaps."
        )
        border = "green"
    else:
        source_line = "Source: SEC 10-K XBRL (companyfacts.json) — same accession for both legs"
        border = "dim"
    console.print(
        Panel(
            f"{source_line}\n"
            "GAAP ROIC: NetIncome / (Equity + Debt)\n"
            f"{pt_method_line}\n"
            f"{rd_line}\n"
            "  ✓ 25% SG&A → Organisation Capital (20%/yr amortisation)\n"
            "  ✗ NOT added back: SBC, restructuring, acquisitions, "
            "impairments, 'one-time' items",
            title="[bold]Methodology[/bold] (ADR-021 / ADR-022 / ADR-039)",
            border_style=border,
        )
    )

    if isinstance(requirement, DataRequirement):
        console.print(
            Panel(
                f"Frameworks: [bold cyan]{', '.join(selected)}[/bold cyan]\n"
                f"Data fetched: annual={requirement.annual_years}yr, "
                f"quarterly={requirement.quarterly_count}, "
                f"price={requirement.price_history_years}yr, "
                f"insiders={requirement.needs_insider_transactions}, "
                f"proxy={requirement.needs_proxy_ownership}, "
                f"customer={requirement.needs_customer_concentration}",
                title=f"[bold]Tier {tier}[/bold] dive plan",
                border_style="cyan",
            )
        )

    if results:
        table = Table(title="Framework Scores", show_lines=True)
        table.add_column("Framework", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("Verdict", width=12)
        for name, res in sorted(results.items()):
            score = getattr(res, "score", 0.0)
            verdict = getattr(res, "verdict", "—")
            style = "green" if score >= 7.0 else "yellow" if score >= 4.0 else "red"
            table.add_row(name, f"[{style}]{score:.1f}[/{style}]", verdict)
        console.print(table)

    # ── Dual composite (GAAP + Peters-Taylor non-GAAP) ───────────────────
    # ADR-021: when both bases are available we surface them side-by-side.
    # The gap (Δpp) is the divergence between GAAP and economic capital
    # efficiency feeding into the framework-weighted composite.
    composite_gaap = getattr(outcome, "composite_gaap", None)
    composite_non_gaap = getattr(outcome, "composite_non_gaap", None)
    if composite_gaap is not None or composite_non_gaap is not None:
        gaap_str = f"{composite_gaap:.2f}" if composite_gaap is not None else "—"
        ng_str = f"{composite_non_gaap:.2f}" if composite_non_gaap is not None else "—"
        delta_part = ""
        if composite_gaap is not None and composite_non_gaap is not None:
            delta = composite_non_gaap - composite_gaap
            sign = "+" if delta >= 0 else ""
            colour = "red" if abs(delta) >= 0.50 else "yellow" if abs(delta) >= 0.10 else "dim"
            delta_part = f"  [bold {colour}]Δ {sign}{delta:.2f}[/bold {colour}]"
        rprint(
            f"\n[bold]Composites[/bold] — "
            f"GAAP: [cyan]{gaap_str}[/cyan]  |  "
            f"non-GAAP (PT): [cyan]{ng_str}[/cyan]{delta_part}"
        )

    # ── ROIC summary (GAAP vs Peters-Taylor non-GAAP) ────────────────────
    # Always show both views when available so the user can see how
    # intangible-capital adjustment changes the picture (ADR-021 / DEC-28).
    ticker = getattr(outcome, "ticker", "")
    pt_result = getattr(outcome, "pt_result", None)
    if ticker:
        _render_roic_summary(ticker, pt_result=pt_result)

    if unfeasible:
        rprint("\n[yellow]Frameworks unable to run:[/yellow]")
        for name, reason in unfeasible.items():
            rprint(f"  [yellow]{name}[/yellow] — {reason}")

    # Phase 5j / DEC-30 + 5M / DEC-33: ICA/PSA trigger-gated; BEW mandatory on
    # every dive. Display both — triggered overlays under a "triggers
    # detected" header, BEW (mandatory) under its own row with the
    # evaluable-checks breakdown so partial scores aren't misread.
    triggers = getattr(outcome, "overlay_triggers", None) or []
    auto_overlay_results = getattr(outcome, "auto_overlay_results", None) or {}
    if triggers:
        triggered_types = sorted({getattr(t, "overlay_type", "") for t in triggers if getattr(t, "overlay_type", "")})
        rprint(
            f"\n[magenta]Overlay triggers detected (auto-executed: "
            f"{', '.join(triggered_types) or '—'}):[/magenta]"
        )
        for trig in triggers:
            tid = getattr(trig, "trigger_id", "?")
            cond = getattr(trig, "trigger_condition", "")
            rprint(f"  [magenta]{tid}[/magenta] — {cond}")

    sim_result = auto_overlay_results.get("SIM")
    if sim_result and sim_result.get("ok") is True:
        auto_pass = sim_result.get("auto_pass_count", 0)
        auto_total = sim_result.get("auto_total", 2)
        tests = sim_result.get("tests", {})
        verdict = sim_result.get("verdict", "?")
        verdict_colour = (
            "green" if auto_pass == auto_total
            else "yellow" if auto_pass >= 1
            else "dim"
        )
        rprint(
            f"\n[bold]SIM (Structural Intelligence Moat)[/bold] "
            f"[dim](soft overlay — tech sector only — ◯ heuristic-tier, "
            f"NOT in composite)[/dim]"
        )
        rprint(
            f"  Auto-detected: [{verdict_colour}]{verdict}[/{verdict_colour}]  "
            f"({auto_pass}/{auto_total} auto-tests pass)"
        )
        sim3 = tests.get("SIM-3_reasoning_vs_pattern_match", {})
        sim5 = tests.get("SIM-5_domain_specificity", {})
        s3_status = "✓ pass" if sim3.get("pass") else "✗ no signal"
        s5_status = "✓ pass" if sim5.get("pass") else "✗ no signal"
        rprint(f"    [dim]SIM-3 (ontology / knowledge-graph in 10-K): {s3_status}[/dim]")
        if sim3.get("positive_hits"):
            hits = ", ".join(sim3["positive_hits"][:3])
            rprint(f"      [dim]positive hits: {hits}[/dim]")
        rprint(f"    [dim]SIM-5 (domain narrowness): {s5_status}[/dim]")
        rprint(
            "  [yellow]Manual review needed:[/yellow] [dim]SIM-1 "
            "(structural embeddedness), SIM-2 (proprietary data), "
            "SIM-4 (intelligence compounding) — judgment calls, not "
            "auto-detectable. See overlays_results_json.tests for prompts.[/dim]"
        )

    bew_result = auto_overlay_results.get("BEW")
    if bew_result and bew_result.get("ok") is True:
        verdict = bew_result.get("verdict", "?")
        score = bew_result.get("score", 0)
        n_eval = bew_result.get("n_checks_evaluable", 0)
        verdict_colour = (
            "green" if verdict == "EXTREME_WINNER_CANDIDATE"
            else "yellow" if verdict == "moderate_winner_candidate"
            else "dim"
        )
        rprint(
            f"\n[bold]BEW (Bessembinder Extreme Winners)[/bold] "
            f"[dim](runs on every dive)[/dim]"
        )
        rprint(
            f"  Verdict: [{verdict_colour}]{verdict}[/{verdict_colour}]   "
            f"Score: [bold]{score}/{n_eval}[/bold] evaluable checks   "
            f"[dim](7 total — TAM + sector-EV/Rev not warehoused → unevaluable)[/dim]"
        )
        hold = bew_result.get("hold_period_recommendation")
        if hold and hold != "n/a":
            rprint(f"  Hold-period guidance: [bold]{hold}[/bold]")

    # External Signals (LLM-extracted) — strictly isolated channel.
    # Rendered ONLY in display; not read by F1-F7 scoring.
    _render_external_signals(getattr(outcome, "ticker", ""))

    if fetch_gaps:
        rprint("\n[dim]Data fetch notes:[/dim]")
        for gap in fetch_gaps[:10]:
            rprint(f"  [dim]· {gap}[/dim]")
        if len(fetch_gaps) > 10:
            rprint(f"  [dim]· …and {len(fetch_gaps) - 10} more[/dim]")


def _render_external_signals(ticker: str) -> None:
    """Render the ExternalSignal panel for the dive / score-card display.

    Architectural contract (CLAUDE.md §"AI layer boundary"):
      - This data is LLM-extracted and STRICTLY ISOLATED from the
        deterministic F1-F7 scoring path.
      - Every row carries audit-trail provenance: source URL,
        verbatim quote, confidence band, extraction model.
      - The panel border is yellow + the title says "LLM-extracted"
        explicitly so the reader cannot confuse these with the
        XBRL/regex-sourced framework signals above.
      - `not_disclosed` rows are shown (with dim styling) because the
        absence-of-finding is itself informative: it tells the reader
        we asked the LLM and the source genuinely didn't have it.
      - Renders nothing when no rows exist for the ticker (silent skip).
    """
    if not ticker:
        return
    try:
        from sqlalchemy import select
        from data.db import SessionLocal
        from data.models.schema import Company, ExternalSignalRecord
    except Exception:
        return

    with SessionLocal() as s:
        c = s.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        if c is None:
            return
        rows = s.execute(
            select(ExternalSignalRecord)
            .where(ExternalSignalRecord.company_id == c.id)
            .order_by(ExternalSignalRecord.extraction_confidence.desc(),
                      ExternalSignalRecord.signal_name)
        ).scalars().all()
        if not rows:
            return

        # Group provenance — usually all rows share a single source doc
        urls = {r.source_url for r in rows if r.source_url}
        accns = {r.source_accession for r in rows if r.source_accession}
        models = {r.extracted_model for r in rows if r.extracted_model}
        when = max((r.extracted_at for r in rows if r.extracted_at), default=None)

        # Header — clearly labelled as LLM/supplementary
        rprint(
            "\n[bold yellow]External Signals (LLM-extracted — supplementary,"
            " NOT in F1–F7 composite)[/bold yellow]"
        )
        if accns or urls or models or when:
            prov_bits = []
            if accns:
                prov_bits.append(f"accession {next(iter(accns))}")
            if models:
                prov_bits.append(f"model {next(iter(models))}")
            if when:
                prov_bits.append(f"extracted {when:%Y-%m-%d}")
            rprint(f"  [dim]source: {'  ·  '.join(prov_bits)}[/dim]")
            if urls:
                rprint(f"  [dim]url: {next(iter(urls))}[/dim]")

        # Per-row table
        table = Table(show_lines=False, show_edge=False, pad_edge=False, box=None)
        table.add_column("Signal", style="cyan", width=16)
        table.add_column("Value", justify="right", width=18)
        table.add_column("Conf", width=14)
        table.add_column("Source quote", overflow="fold")

        for r in rows:
            # Value formatting by unit
            if r.signal_value_numeric is None:
                val_str = "[dim]—[/dim]"
            elif (r.signal_unit or "") == "usd":
                v = r.signal_value_numeric
                if v >= 1e9:
                    val_str = f"${v / 1e9:.2f}B"
                elif v >= 1e6:
                    val_str = f"${v / 1e6:.1f}M"
                else:
                    val_str = f"${v:,.0f}"
            elif (r.signal_unit or "") == "pct":
                val_str = f"{r.signal_value_numeric:.1f}%"
            elif (r.signal_unit or "") == "count":
                val_str = f"{int(r.signal_value_numeric):,}"
            else:
                val_str = f"{r.signal_value_numeric}"

            conf = r.extraction_confidence or "?"
            conf_colour = {
                "high": "green",
                "medium": "yellow",
                "low": "yellow",
                "not_disclosed": "dim",
            }.get(conf, "dim")
            conf_str = f"[{conf_colour}]{conf}[/{conf_colour}]"

            quote = r.source_quote or ""
            if not quote and conf == "not_disclosed":
                quote = "[dim](LLM asked; source did not disclose)[/dim]"
            elif len(quote) > 140:
                quote = f'"{quote[:137]}…"'
            elif quote:
                quote = f'"{quote}"'

            name = r.signal_name
            if conf == "not_disclosed":
                name = f"[dim]{name}[/dim]"

            table.add_row(name, val_str, conf_str, quote)

        console.print(table)
        rprint(
            "  [dim]Isolation: F1–F7 scoring reads only the deterministic"
            " SEC-XBRL fields; these LLM-extracted values are supplementary."
            "[/dim]"
        )


def _render_tier1(ticker: str, result: object) -> None:
    score = getattr(result, "composite_score", 0.0)
    verdict = getattr(result, "verdict", "N/A")
    style = "green" if score >= 7.0 else "yellow" if score >= 5.0 else "red"
    console.print(
        Panel(
            f"Score: [{style}]{score:.1f}[/{style}] / 10  |  Verdict: [bold]{verdict}[/bold]",
            title=f"[bold]{ticker}[/bold] — Tier 1",
            border_style=style,
        )
    )


def _render_tier2(ticker: str, result: object) -> None:
    console.print(Panel(
        str(getattr(result, "scorecard_json", "Tier 2 result")),
        title=f"[bold]{ticker}[/bold] — Tier 2",
    ))


# ── Overlay ───────────────────────────────────────────────────────────────

@overlay_app.command("run")
def overlay_run(
    ticker: str = typer.Argument(...),
    overlay_type: OverlayType = typer.Option(..., "--type"),
) -> None:
    """Manually trigger a diagnostic overlay (ICA / PSA / BEW)."""
    asyncio.run(_overlay_run_async(ticker.upper(), overlay_type))


async def _overlay_run_async(ticker: str, overlay_type: OverlayType) -> None:
    import json

    from overlays.detector import run_overlay_by_type
    try:
        result = await run_overlay_by_type(ticker, overlay_type.value)
    except NotImplementedError as exc:
        rprint(f"[yellow]⚠ {exc}[/yellow]")
        return
    if not isinstance(result, dict):
        console.print(result)
        return

    border_color = "green" if result.get("ok") else "yellow"
    title = f"[bold]{overlay_type.value}[/bold] overlay — {ticker}"
    if not result.get("ok"):
        rprint(Panel(
            f"[yellow]Overlay returned ok=False[/yellow]\n"
            f"Reason: {result.get('reason', '?')}",
            title=title, border_style=border_color,
        ))
        return

    # Compact-but-informative rendering. Full JSON is also printed at the end
    # for the user that wants the audit trail.
    parts = []
    if "verdict" in result:
        parts.append(f"verdict: [bold]{result['verdict']}[/bold]")
    if "f5_verdict_revised" in result:
        parts.append(f"F5 revised: [bold]{result['f5_verdict_revised']}[/bold]")
    if "score" in result and "n_checks_evaluable" in result:
        parts.append(f"score: {result['score']}/{result['n_checks_evaluable']} checks")
    if result.get("interpretation"):
        parts.append(f"\n{result['interpretation']}")

    rprint(Panel(
        "\n".join(parts) if parts else "(see JSON below)",
        title=title, border_style=border_color,
    ))
    rprint("\n[dim]Full result JSON:[/dim]")
    console.print(json.dumps(result, indent=2, default=str))


@overlay_app.command("status")
def overlay_status(ticker: str = typer.Argument(...)) -> None:
    """Show detected overlay triggers for a ticker."""
    asyncio.run(_overlay_status_async(ticker.upper()))


async def _overlay_status_async(ticker: str) -> None:
    from overlays.detector import get_detected_triggers
    triggers = await get_detected_triggers(ticker)
    if not triggers:
        rprint(f"[green]No overlay triggers detected for {ticker}.[/green]")
        return
    for t in triggers:
        console.print(Panel(
            f"Trigger: [bold]{t.trigger_id}[/bold]\n{t.trigger_condition}",
            title=f"[yellow]⚡ {t.overlay_type}[/yellow]",
            border_style="yellow",
        ))


# ── Watchlist ─────────────────────────────────────────────────────────────

@watchlist_app.command("add")
def watchlist_add(
    ticker: str = typer.Argument(...),
    role: WatchlistRole = typer.Option(WatchlistRole.monitor),
    notes: str | None = typer.Option(None),
    no_fetch: bool = typer.Option(
        False, "--no-fetch",
        help="Don't auto-materialize a missing ticker via its FundamentalsSource.",
    ),
) -> None:
    """Add a ticker to the watchlist.

    If the ticker isn't in the DB yet, it is materialized via its resolved
    FundamentalsSource (ADR-039): US tickers → SEC EDGAR; Canadian (.TO/.V) and
    other foreign suffixes → yfinance Tier-3 bridge. This is how non-SEC names
    like VHI.TO (VitalHub) enter the system, ready for `invest dive`.
    """
    ticker = ticker.upper()
    from data.db import get_session
    from data.models.schema import Company, WatchlistEntry

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()

    if not company and not no_fetch:
        from data.sources import resolve_source
        src = resolve_source(ticker, None)
        rprint(
            f"[dim]{ticker} not in DB — materializing via "
            f"[bold]{src.name}[/bold] (tier={src.tier})…[/dim]"
        )
        asyncio.run(_data_refresh_async(ticker, False, 10))

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            rprint(
                f"[red]{ticker} could not be resolved by any FundamentalsSource. "
                f"Check the ticker + exchange suffix (e.g. VHI.TO for TSX).[/red]"
            )
            raise typer.Exit(1)
        # Promote out of screener_candidate so cleanup never archives it.
        if company.status in (None, "screener_candidate"):
            company.status = "watchlist"
        tier = company.data_source_tier or "sec_edgar"
        entry = WatchlistEntry(company_id=company.id, role=role.value, notes=notes)
        session.add(entry)
    tier_note = "" if tier == "sec_edgar" else f" [yellow](data: {tier})[/yellow]"
    rprint(f"[green]✓ {ticker} added to watchlist as [{role.value}].[/green]{tier_note}")


@watchlist_app.command("list")
def watchlist_list() -> None:
    """Show active watchlist."""
    from data.db import get_session
    from data.models.schema import Company, WatchlistEntry
    # Rows are read inside the session: the commit on exit expires loaded objects.
    with get_session() as session:
        rows = [
            (
                company.ticker,
                company.name,
                entry.role or "",
                str(entry.added_date or ""),
                entry.notes or "",
            )
            for entry, company in session.query(WatchlistEntry, Company)
            .join(Company)
            .filter(WatchlistEntry.is_active.is_(True))
        ]
    table = Table(title="Watchlist", show_lines=True)
    table.add_column("Ticker", style="cyan")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Added")
    table.add_column("Notes")
    for row in rows:
        table.add_row(*row)
    console.print(table)


@watchlist_app.command("remove")
def watchlist_remove(ticker: str = typer.Argument(...)) -> None:
    """Remove ticker from watchlist (soft delete)."""
    from data.db import get_session
    from data.models.schema import Company, WatchlistEntry
    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker.upper()).first()
        if not company:
            rprint(f"[red]{ticker} not found.[/red]")
            raise typer.Exit(1)
        (
            session.query(WatchlistEntry)
            .filter_by(company_id=company.id, is_active=True)
            .update({"is_active": False})
        )
    rprint(f"[green]✓ {ticker.upper()} removed from watchlist.[/green]")


# ── Scheduler ─────────────────────────────────────────────────────────────

@scheduler_app.command("add-job")
def scheduler_add_job(
    name: str = typer.Argument(..., help="Job name (e.g. quarterly-screener)"),
    cron: str = typer.Option(..., help="Cron expression (e.g. '0 9 15 */3 *')"),
) -> None:
    """Register a built-in scheduled job (does NOT start it)."""
    from scheduler.jobs import register_job
    register_job(name, cron)
    rprint(f"[green]✓ '{name}' registered (cron: {cron}).[/green]")
    rprint("[dim]Run 'invest scheduler start' to launch the daemon.[/dim]")


@scheduler_app.command("add-deepdive")
def scheduler_add_deepdive(
    name: str = typer.Argument(..., help="Job name (e.g. weekly-tech-dive)"),
    tickers: str = typer.Option(..., "--tickers", help="Comma-separated tickers"),
    cron: str = typer.Option(..., "--cron", help="Cron expression (e.g. '0 8 * * 1' for Monday 08:00)"),
    frameworks: str | None = typer.Option(
        None, "--frameworks",
        help="Comma-separated framework names (e.g. 'F1,F5'). Omit to run ALL 7 frameworks.",
    ),
    tier: int = typer.Option(1, min=1, max=2, help="Tier 1 (quick) or Tier 2 (full)"),
) -> None:
    """
    Register a recurring deep-dive job.

    Examples:
      # Default deep-dive (all 7 frameworks) every Monday morning:
      invest scheduler add-deepdive monday-watch --tickers NVDA,COST,ADBE --cron '0 8 * * 1'

      # F1+F5 only, tier-2, monthly:
      invest scheduler add-deepdive monthly-quality --tickers AAPL,MSFT \\
            --frameworks F1,F5 --tier 2 --cron '0 9 1 * *'
    """
    from scheduler.jobs import register_deepdive_job
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    fw_list = [f.strip().upper() for f in frameworks.split(",")] if frameworks else None
    register_deepdive_job(name, cron, ticker_list, framework_names=fw_list, tier=tier)
    label = f"frameworks={fw_list}" if fw_list else "frameworks=ALL"
    rprint(f"[green]✓ '{name}' registered as deepdive[/green] ({label}, tickers={ticker_list}, tier={tier}, cron={cron})")
    rprint("[dim]Run 'invest scheduler start' to launch the daemon.[/dim]")


@scheduler_app.command("add-portfolio-reassessment")
def scheduler_add_portfolio_reassessment(
    name: str = typer.Argument(..., help="Job name (e.g. annual-portfolio-reassessment)"),
    cron: str = typer.Option(
        "0 8 1 3 *", "--cron",
        help="Cron expression. Default '0 8 1 3 *' = Mar 1 at 08:00 system local "
             "(earliest after 10-K season — portfolio gets reassessed before "
             "watchlist's Mar 15 to keep holdings highest-priority).",
    ),
) -> None:
    """Register the annual portfolio reassessment job.

    Dives every active portfolio position once a year using all frameworks
    plus auto-overlays (BEW always runs; ICA and PSA are trigger-gated; SIM
    is a soft overlay for tech). Surfaces year-over-year warning signals and
    per-position context: years held, reconsideration-window status, and the
    original thesis text.

    Warnings are SURFACED, not actioned. The hold philosophy is
    forever-by-default with a 5-year minimum before reconsidering, so this is
    an early-warning instrument for holdings, NOT an exit-trigger system.

    Example:
      invest scheduler add-portfolio-reassessment annual-portfolio-reassessment
    """
    from scheduler.jobs import register_portfolio_reassessment_job
    register_portfolio_reassessment_job(name, cron)
    rprint(
        f"[green]✓ '{name}' registered as portfolio reassessment[/green] "
        f"(cron={cron}, target=active PortfolioPosition rows)"
    )
    rprint(
        "[dim]Fires once a year. Run 'invest scheduler start' to launch the daemon. "
        "Output goes to logger.[/dim]"
    )


@scheduler_app.command("add-checkpoint")
def scheduler_add_checkpoint(
    name: str = typer.Argument(..., help="Job name (e.g. yearly-watchlist-checkup)"),
    cron: str = typer.Option(
        "0 8 15 3 *", "--cron",
        help="Cron expression. Default '0 8 15 3 *' = Mar 15 at 08:00 system local "
             "(post 10-K filing season). Use '0 8 1 1 *' for Jan 1 instead.",
    ),
) -> None:
    """Register the yearly watchlist checkpoint job.

    Dives every active WatchlistEntry once a year, compares against the
    prior dive ≥10 months old, surfaces year-over-year warning signals:
    composite drops, verdict downgrades, framework regressions, PT-ROIC
    erosion, BEW band drops, ICA-5 newly firing.

    Warnings are SURFACED, not actioned. Per the hold philosophy
    (forever-default, 5-year minimum reconsideration), this is the
    early-warning instrument, NOT an exit-trigger. Read the warnings,
    revisit the thesis, decide.

    Example:
      invest scheduler add-checkpoint annual-health-check
      invest scheduler add-checkpoint annual-health-check --cron '0 8 1 1 *'
    """
    from scheduler.jobs import register_checkpoint_job
    register_checkpoint_job(name, cron)
    rprint(
        f"[green]✓ '{name}' registered as yearly checkpoint[/green] "
        f"(cron={cron}, target=active watchlist)"
    )
    rprint(
        "[dim]Fires once a year. Run 'invest scheduler start' to launch the daemon. "
        "Output goes to logger — set LOG_LEVEL=INFO and check the daemon's stdout/log file.[/dim]"
    )


@scheduler_app.command("list")
def scheduler_list() -> None:
    """List all registered jobs."""
    from scheduler.jobs import list_jobs
    jobs = list_jobs()
    if not jobs:
        rprint("[yellow]No jobs registered.[/yellow]")
        return
    table = Table(title="Scheduled Jobs", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Cron")
    table.add_column("Last Run")
    for job in jobs:
        table.add_row(job["name"], job["cron"], str(job.get("last_run") or "—"))
    console.print(table)


@scheduler_app.command("remove-job")
def scheduler_remove_job(name: str = typer.Argument(...)) -> None:
    """Remove a registered job."""
    from scheduler.jobs import remove_job
    remove_job(name)
    rprint(f"[green]✓ '{name}' removed.[/green]")


@scheduler_app.command("start")
def scheduler_start() -> None:
    """Start the APScheduler daemon (blocking). Ctrl+C to stop."""
    from scheduler.jobs import start_daemon
    start_daemon()


# ── Data ──────────────────────────────────────────────────────────────────

@data_app.command("refresh")
def data_refresh(
    ticker: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Force cache invalidation"),
    years: int = typer.Option(
        DEFAULT_HISTORY_YEARS, "--years",
        help="Historical depth in fiscal years. Must exceed F7's 10-year floor "
             "(ADR-030-A2); raise further for a longer z-score window.",
    ),
) -> None:
    """Fetch/refresh all data for a ticker (EDGAR + yfinance, deterministic)."""
    asyncio.run(_data_refresh_async(ticker.upper(), force, years))


async def _data_refresh_async(ticker: str, force: bool, years: int) -> None:
    from data.pipeline import refresh_ticker
    with console.status(f"[bold green]Refreshing {ticker} ({years}yr)…[/bold green]"):
        try:
            gaps = await refresh_ticker(ticker, force_refresh=force, years=years)
        except NotImplementedError as exc:
            rprint(f"[yellow]⚠ {exc}[/yellow]")
            return
    rprint(f"[green]✓ {ticker} refreshed.[/green]")
    if gaps:
        rprint("\n[yellow]Data gaps detected:[/yellow]")
        for gap in gaps:
            rprint(f"  ⚠ {gap}")


@data_app.command("gaps")
def data_gaps(ticker: str = typer.Argument(...)) -> None:
    """Show all data gaps for a ticker."""
    asyncio.run(_data_gaps_async(ticker.upper()))


async def _data_gaps_async(ticker: str) -> None:
    from data.pipeline import get_data_gaps
    try:
        gaps = await get_data_gaps(ticker)
    except NotImplementedError as exc:
        rprint(f"[yellow]⚠ {exc}[/yellow]")
        return
    if not gaps:
        rprint(f"[green]No data gaps for {ticker}.[/green]")
    else:
        rprint(f"\n[yellow]Data gaps for {ticker}:[/yellow]")
        for gap in gaps:
            rprint(f"  ⚠ {gap}")


def _contract_ids(contract: str | None) -> list[str] | None:
    from data.contracts import BY_ID

    if not contract:
        return None
    ids = [c.strip().upper() for c in contract.split(",") if c.strip()]
    unknown = sorted(set(ids) - set(BY_ID))
    if unknown or not ids:
        rprint(f"[red]Unknown contract {', '.join(unknown)}; known: {', '.join(BY_ID)}[/red]")
        raise typer.Exit(2)
    return ids


@data_app.command("check")
def data_check(
    contract: str | None = typer.Option(None, "--contract", help="Only these, e.g. C1,C5."),
    ticker: str | None = typer.Option(None, "--ticker", help="Check one ticker (C1-C4)."),
) -> None:
    """Run the data contracts over the DB and record the results (ADR-044). DB-only.

    Exits 1 when a blocking contract fails.
    """
    from data.contracts import BY_ID, CONTRACTS, evaluate, evaluate_all, record
    from data.db import get_session

    ids = _contract_ids(contract)
    with get_session() as session:
        if ticker:
            chosen = [BY_ID[i] for i in ids] if ids else [c for c in CONTRACTS if c.per_ticker]
            if not_per_ticker := [c.id for c in chosen if not c.per_ticker]:
                rprint(f"[red]{', '.join(not_per_ticker)} are not checked per ticker.[/red]")
                raise typer.Exit(2)
            results = [evaluate(session, c, ticker.upper()) for c in chosen]
        else:
            results = evaluate_all(session, ids)
    record(results, "check")

    table = Table(title="Data contracts (ADR-044)")
    for col in ("Contract", "Scope", "Severity"):
        table.add_column(col)
    for col in ("Failing", "Of", "Share", "Allowed", "Result"):
        table.add_column(col, justify="right")
    table.add_column("Failing keys (first 5)")
    for r in results:
        share = "—" if r.share is None else f"{r.share:.1%}"
        allowed = "reported" if r.threshold is None else f"{r.threshold:.0%}"
        verdict = {True: "[green]pass[/green]", False: "[red]FAIL[/red]", None: "—"}[r.passed]
        keys = ", ".join(r.sample[:5]) or (r.note or "")
        table.add_row(
            f"{r.contract.id} {r.contract.title}", r.scope, r.contract.severity,
            str(r.failing), str(r.total), share, allowed, verdict, keys,
        )  # fmt: skip
    console.print(table)
    if any(r.passed is False and r.contract.severity == "block" for r in results):
        raise typer.Exit(1)


@data_app.command("backfill")
def data_backfill(
    contract: str = typer.Option(..., "--contract", help="A company contract: C1-C4."),
    limit: int | None = typer.Option(None, "--limit", help="Refresh at most this many."),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation."),
) -> None:
    """Refresh the companies failing a contract (ADR-044 §2.5). Network-heavy: SEC + yfinance."""
    from data.contracts import ALL, BY_ID, evaluate, record
    from data.db import get_session
    from data.pipeline import refresh_ticker
    from frameworks.base import DataRequirement

    ids = _contract_ids(contract) or []
    if len(ids) != 1:
        rprint("[red]Backfill takes one contract.[/red]")
        raise typer.Exit(2)
    cid = ids[0]
    c = BY_ID[cid]
    if not c.per_ticker:
        rprint(f"[red]{cid} is not a company contract; backfill covers C1-C4.[/red]")
        raise typer.Exit(2)
    scope = ALL if ALL in c.thresholds else next(iter(c.thresholds))
    with get_session() as session:
        before = evaluate(session, c, scope)
    tickers = sorted(before.keys)[:limit]
    if not tickers:
        rprint(f"[green]{cid} ({scope}): nothing failing.[/green]")
        return
    rprint(
        f"{cid} ({scope}): {before.failing} of {before.total} {c.unit} failing; "
        f"refreshing {len(tickers)}: {', '.join(tickers[:10])}{' …' if len(tickers) > 10 else ''}"
    )
    if not yes and not typer.confirm("Fetch from SEC and yfinance for these?", default=False):
        raise typer.Exit(1)
    # Fundamentals only: the parser-version gate re-reads filings read by an older parser.
    req = DataRequirement(
        annual_years=DEFAULT_HISTORY_YEARS, quarterly_count=max(DEFAULT_HISTORY_YEARS, 8)
    )
    errors = 0
    for i, t in enumerate(tickers, 1):
        try:
            asyncio.run(refresh_ticker(t, requirement=req))
        except Exception as exc:  # noqa: BLE001 - one ticker's failure must not stop the rest
            errors += 1
            rprint(f"  [yellow]{t}: {type(exc).__name__}: {exc}[/yellow]")
        if i % 25 == 0:
            rprint(f"  {i}/{len(tickers)} refreshed")
    with get_session() as session:
        after = evaluate(session, c, scope)
    record([after], "backfill")
    rprint(
        f"{cid} ({scope}): {before.failing} → {after.failing} of {after.total} failing; "
        f"{errors} refresh errors"
    )


@data_app.command("plan")
def data_plan(
    ticker: str = typer.Argument(...),
    frameworks: str | None = typer.Option(
        None, "--frameworks",
        help="Comma-separated framework names (e.g. 'F1' or 'F1,F5'). "
             "Default: all frameworks (kitchen sink at --years).",
    ),
    years: int = typer.Option(DEFAULT_HISTORY_YEARS, "--years", help="History depth when no --frameworks given"),
) -> None:
    """
    Print what a refresh / dive would fetch for TICKER, without fetching.

    Shows the merged DataRequirement + the year-coverage decision (would the
    EDGAR companyfacts call run, would it skip due to full coverage, etc).
    """
    from frameworks.base import (
        DataRequirement,
        kitchen_sink_requirement,
        requirement_for_frameworks,
    )

    if frameworks:
        names = [f.strip().upper() for f in frameworks.split(",") if f.strip()]
        req = requirement_for_frameworks(names)
        label = f"frameworks={names}"
    else:
        req = kitchen_sink_requirement(years)
        label = f"kitchen-sink years={years}"

    table = Table(title=f"Data plan: {ticker.upper()} ({label})", show_lines=False)
    table.add_column("Field", style="cyan", width=32)
    table.add_column("Value", justify="right")
    table.add_row("annual_years", str(req.annual_years))
    table.add_row("quarterly_count", str(req.quarterly_count))
    table.add_row("price_history_years", str(req.price_history_years))
    table.add_row("needs_insider_transactions", str(req.needs_insider_transactions))
    table.add_row("needs_proxy_ownership", str(req.needs_proxy_ownership))
    table.add_row("needs_customer_concentration", str(req.needs_customer_concentration))
    table.add_row("needs_founder_status", str(req.needs_founder_status))
    table.add_row("needs_analyst_coverage", str(req.needs_analyst_coverage))
    table.add_row("needs_short_interest_history", str(req.needs_short_interest_history))
    table.add_row("needs_institutional_holders", str(req.needs_institutional_holders))
    table.add_row("needs_earnings_history", str(req.needs_earnings_history))
    console.print(table)

    if req == DataRequirement():
        rprint("[yellow]Empty requirement — refresh would be a no-op.[/yellow]")
        return

    # Coverage gate preview
    from data.pipeline import _decide_companyfacts_fetch, _load_known_accessions
    if req.annual_years > 0:
        decision = _decide_companyfacts_fetch(
            ticker.upper(), years=req.annual_years,
            force_refresh=False,
            known_accessions=_load_known_accessions(ticker.upper()),
            quarters=req.quarterly_count,
        )
        rprint(
            f"\n[bold]Coverage decision:[/bold] fetch_fundamentals="
            f"[cyan]{decision.fetch_fundamentals}[/cyan]  "
            f"keep_only_years={sorted(decision.keep_only_years) if decision.keep_only_years else None}\n"
            f"[dim]reason: {decision.reason}[/dim]"
        )


@data_app.command("cache-stats")
def data_cache_stats() -> None:
    """Show cache statistics."""
    from data.cache.manager import CacheManager
    cache = CacheManager()
    stats = cache.stats()
    table = Table(title="Cache Stats", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("Total entries", str(stats["total"]))
    table.add_row("Live (not expired)", str(stats["live"]))
    table.add_row("Expired", str(stats["expired"]))
    console.print(table)


@data_app.command("cache-clear")
def data_cache_clear(ticker: str | None = typer.Argument(None)) -> None:
    """Clear cache for a specific ticker (or all expired entries if no ticker given)."""
    from data.cache.manager import CacheManager
    cache = CacheManager()
    if ticker:
        n = cache.invalidate_ticker(ticker.upper())
        rprint(f"[green]✓ Cleared {n} cache entries for {ticker.upper()}.[/green]")
    else:
        n = cache.cleanup_expired()
        rprint(f"[green]✓ Removed {n} expired cache entries.[/green]")


# ── Export ────────────────────────────────────────────────────────────────

@export_app.command("deepdive")
def export_deepdive(
    ticker: str = typer.Argument(..., help="Ticker to export"),
    run_id: int | None = typer.Option(None, help="Specific run ID (default: latest)"),
    out: str | None = typer.Option(None, help="Output file path (default: stdout)"),
) -> None:
    """
    Export a deep-dive run as markdown.
    Uses only stored DB data — zero AI calls.
    """
    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun
    from deepdive.serializer import export_deepdive_markdown

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker.upper()).first()
        company_name = company.name if company else ticker.upper()

        query = session.query(DeepDiveRun).filter_by(ticker=ticker.upper())
        if run_id is not None:
            query = query.filter_by(id=run_id)
        run = query.order_by(DeepDiveRun.id.desc()).first()  # as the narrative gate does

        if not run:
            rprint(f"[red]No deep-dive run found for {ticker.upper()}.[/red]")
            if run_id is None:
                rprint(f"[dim]Run 'invest dive {ticker}' first.[/dim]")
            raise typer.Exit(1)

        markdown = export_deepdive_markdown(run, company_name)

    if out:
        from pathlib import Path
        Path(out).write_text(markdown, encoding="utf-8")
        rprint(f"[green]✓ Written to {out}[/green]")
    else:
        console.print(markdown)


@export_app.command("screener")
def export_screener(
    run_id: int | None = typer.Option(None, help="Specific run ID (default: latest)"),
    out: str | None = typer.Option(None, help="Output file path (default: stdout)"),
) -> None:
    """
    Export a screener run as CSV.
    Uses only stored DB data — zero AI calls.
    """
    from data.db import get_session
    from data.models.schema import ScreenerRun
    from deepdive.serializer import export_screener_csv

    with get_session() as session:
        query = session.query(ScreenerRun)
        if run_id is not None:
            query = query.filter_by(id=run_id)
        run = query.order_by(ScreenerRun.run_date.desc()).first()

        if not run:
            rprint("[red]No screener run found.[/red]")
            rprint("[dim]Run 'invest screen' first.[/dim]")
            raise typer.Exit(1)

        csv_text = export_screener_csv(run)

    if out:
        from pathlib import Path
        Path(out).write_text(csv_text, encoding="utf-8")
        rprint(f"[green]✓ Written to {out}[/green]")
    else:
        console.print(csv_text)


@export_app.command("list")
def export_list() -> None:
    """List all stored deep-dive runs and screener runs."""
    from data.db import get_session
    from data.models.schema import DeepDiveRun, ScreenerRun
    # Rows are read inside the session: the commit on exit expires loaded objects.
    with get_session() as session:
        dives = [
            (
                str(d.id),
                d.ticker,
                d.mode,
                str(d.tier),
                f"{d.composite_score:.1f}" if d.composite_score is not None else "—",
                d.verdict or "—",
                str(d.run_date)[:10] if d.run_date else "—",
            )
            for d in session.query(DeepDiveRun).order_by(DeepDiveRun.run_date.desc()).limit(20)
        ]
        runs = session.query(ScreenerRun).order_by(ScreenerRun.run_date.desc()).limit(10).all()
        session.expunge_all()

    if dives:
        table = Table(title="Deep-Dive Runs (latest 20)", show_lines=True)
        table.add_column("ID", style="dim", width=5)
        table.add_column("Ticker", style="bold cyan", width=8)
        table.add_column("Mode", width=5)
        table.add_column("Tier", width=5)
        table.add_column("Score", justify="right", width=7)
        table.add_column("Verdict", min_width=18, no_wrap=True)
        table.add_column("Date", width=12)
        for row in dives:
            table.add_row(*row)
        console.print(table)
    else:
        rprint("[yellow]No deep-dive runs stored yet.[/yellow]")

    if runs:
        table2 = Table(title="Screener Runs (latest 10)", show_lines=True)
        table2.add_column("ID", style="dim", width=5)
        table2.add_column("Mode", width=5)
        table2.add_column("Region", width=8)
        table2.add_column("Universe", justify="right", width=10)
        table2.add_column("Passed Gates", justify="right", width=12)
        table2.add_column("Date", width=12)
        for r in runs:
            run_date = str(r.run_date)[:10] if r.run_date else "—"
            table2.add_row(
                str(r.id), r.mode or "—", r.region or "—",
                str(r.universe_count or "—"), str(r.passed_gates or "—"), run_date,
            )
        console.print(table2)
    else:
        rprint("[yellow]No screener runs stored yet.[/yellow]")


# ── Warehouse FilterTasks (ADR-017 / Phase 4c) ────────────────────────────


@task_app.command("list")
def task_list() -> None:
    """Show registered FilterTasks + their cron grouping."""
    from screener.tasks.registry import CRON_GROUPS, TASK_REGISTRY

    table = Table(title="Warehouse FilterTasks", show_lines=True)
    table.add_column("Name", style="bold cyan", width=18)
    table.add_column("Source", width=10)
    table.add_column("Refresh", width=14)
    table.add_column("Concurrency", width=11)
    table.add_column("Cron group", width=24)

    name_to_group: dict[str, str] = {}
    for group_name, names in CRON_GROUPS.items():
        for n in names:
            name_to_group[n] = group_name

    for name, cls in TASK_REGISTRY.items():
        instance = cls()
        rt = instance.refresh_interval
        rt_str = (
            f"{rt.days}d" if rt.days else f"{int(rt.total_seconds()) // 3600}h"
        )
        conc = (
            str(instance.concurrency_override)
            if instance.concurrency_override is not None
            else "default"
        )
        table.add_row(
            name, instance.source, rt_str, conc,
            name_to_group.get(name, "—"),
        )
    console.print(table)
    rprint(
        "\n[dim]Universe refresh is a standalone bootstrap fn, called by the "
        "warehouse-yf-tasks cron handler before MetadataYFTask runs.[/dim]"
    )


@task_app.command("run")
def task_run(
    name: str = typer.Argument(..., help="Task name (see `invest task list`)"),
) -> None:
    """Execute a single FilterTask through the universal runner."""
    from data.db import get_session
    from screener.tasks.registry import get_task
    from screener.tasks.runner import run_task

    try:
        task = get_task(name)
    except KeyError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    async def _run() -> None:
        with get_session() as db:
            result = await run_task(task, db)
            rprint(
                f"\n[bold]{result.task}[/bold] → "
                f"status=[cyan]{result.status}[/cyan]  "
                f"processed={result.processed}  "
                f"failed={result.failed}  "
                f"duration={result.duration_seconds:.2f}s"
            )
            if result.failed_ciks:
                preview = ", ".join(result.failed_ciks[:10])
                more = f" +{len(result.failed_ciks) - 10}" if len(result.failed_ciks) > 10 else ""
                rprint(f"[yellow]Failed ciks/tickers:[/yellow] {preview}{more}")
            if result.error:
                rprint(f"[red]Error:[/red] {result.error}")

    asyncio.run(_run())


@task_app.command("status")
def task_status() -> None:
    """Snapshot of warehouse coverage + task_failures across all FilterTasks."""
    from datetime import datetime

    from sqlalchemy import func, select

    from data.db import get_session
    from data.models.schema import Company, TaskFailure
    from screener.tasks.registry import TASK_REGISTRY

    # Map task → the warehouse column whose *_fetched_at represents
    # whether the task has run for a given Company row. None = no single
    # column maps cleanly (in-memory tasks read from many).
    fetched_at_col: dict[str, str | None] = {
        "metadata_yf":            "market_cap_fetched_at",
        "exclusion_classify":     None,           # writes the policy status only
        "ipo_date":               "ipo_date_fetched_at",
        "fundamentals":           "fundamentals_fetched_at",
        "composite_score":        "composite_score_fetched_at",
        "framework_score":        "framework_scored_at",
        "polygon_current_price":  "latest_close_at",
        "polygon_weekly_price":   "weekly_prices_fetched_at",
        "polygon_short_interest": None,           # writes ShortInterestRecord rows
        "polygon_rsi":            "latest_rsi_14_fetched_at",
        "polygon_sma":            "latest_sma_50_fetched_at",
        "polygon_macd":           "latest_macd_fetched_at",
    }

    with get_session() as db:
        total_companies = db.execute(
            select(func.count()).select_from(Company)
        ).scalar() or 0
        active_companies = db.execute(
            select(func.count()).select_from(Company).where(
                Company.status.in_(["screener_candidate", "watchlist"])
            )
        ).scalar() or 0

        # Failure counts grouped by task_name
        failure_rows = db.execute(
            select(TaskFailure.task_name, func.count(), func.max(TaskFailure.failed_at))
            .group_by(TaskFailure.task_name)
        ).all()
        failures_by_task = {
            name: (cnt, max_at)
            for (name, cnt, max_at) in failure_rows
        }

        rprint(
            f"\n[bold]Warehouse coverage[/bold] — "
            f"total companies: [cyan]{total_companies}[/cyan]  "
            f"active (screener_candidate + watchlist): [cyan]{active_companies}[/cyan]"
        )

        table = Table(show_lines=True)
        table.add_column("Task", style="bold cyan", width=18)
        table.add_column("Pending", justify="right", width=10)
        table.add_column("Populated", justify="right", width=12)
        table.add_column("Most-recent fetch", width=22)
        table.add_column("Failures", justify="right", width=10)
        table.add_column("Last failure", width=22)

        now = datetime.now(UTC)
        for name, cls in TASK_REGISTRY.items():
            try:
                task = cls()
                pending = len(task.select_pending(db))
            except Exception as exc:
                pending_str = f"[red]err: {exc}[/red]"
            else:
                pending_str = str(pending)

            col = fetched_at_col.get(name)
            if col is None:
                populated_str = "—"
                most_recent_str = "—"
            else:
                col_attr = getattr(Company, col)
                populated = db.execute(
                    select(func.count()).select_from(Company).where(col_attr.isnot(None))
                ).scalar() or 0
                most_recent = db.execute(
                    select(func.max(col_attr))
                ).scalar()
                populated_str = str(populated)
                most_recent_str = (
                    _format_relative(most_recent, now) if most_recent else "never"
                )

            cnt, last_at = failures_by_task.get(name, (0, None))
            last_failure_str = _format_relative(last_at, now) if last_at else "—"

            table.add_row(
                name, pending_str, populated_str,
                most_recent_str, str(cnt), last_failure_str,
            )
        console.print(table)

        # ── Phase 5e gap-4: chronic-failure surfacing ───────────────────
        # Tickers that have failed retry_count >= 3 are surfaced here so
        # ops doesn't have to grep task_failures by hand. These are
        # likely candidates for manual investigation (delisted ticker,
        # SEC universe stale, yfinance permanently lacks the symbol).
        chronic_rows = db.execute(
            select(
                TaskFailure.task_name, TaskFailure.cik,
                TaskFailure.retry_count, TaskFailure.error,
                TaskFailure.failed_at,
            )
            .where(TaskFailure.retry_count >= 3)
            .order_by(TaskFailure.retry_count.desc())
        ).all()
        if chronic_rows:
            rprint(
                "\n[bold yellow]Chronic failures[/bold yellow] "
                "(retry_count ≥ 3 — manual investigation suggested):"
            )
            chronic_table = Table(show_lines=False)
            chronic_table.add_column("Task", style="cyan", width=18)
            chronic_table.add_column("Ticker/CIK", width=14)
            chronic_table.add_column("Retries", justify="right", width=8)
            chronic_table.add_column("Last failure", width=18)
            chronic_table.add_column("Error (truncated)", overflow="fold")
            for tname, cik, retries, err, last_at in chronic_rows[:25]:
                chronic_table.add_row(
                    tname, str(cik), str(retries),
                    _format_relative(last_at, now),
                    (err or "—")[:120],
                )
            console.print(chronic_table)
            if len(chronic_rows) > 25:
                rprint(
                    f"[dim]…and {len(chronic_rows) - 25} more chronic failures. "
                    f"Query task_failures directly for the full list.[/dim]"
                )
        else:
            rprint("\n[dim]No chronic failures (no ticker has retry_count ≥ 3).[/dim]")


def _format_relative(when: object, now: object) -> str:
    """Render a stored datetime as 'Nh ago' / 'Nd ago' for the status table."""
    from datetime import datetime as _dt
    if not isinstance(when, _dt):
        return "—"
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if not isinstance(now, _dt):
        now = _dt.now(UTC)
    delta = now - when
    secs = delta.total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{delta.days}d ago"


# ── Portfolio (DEC-35 — actual holdings, separate from watchlist) ──────────


@portfolio_app.command("add")
def portfolio_add(
    ticker: str = typer.Argument(..., help="Ticker (must already exist in universe)"),
    since: str = typer.Option(
        ..., "--since",
        help="Entry date YYYY-MM-DD. Anchors the 5-year reconsideration window.",
    ),
    role: str = typer.Option(
        "core", "--role",
        help="Position role: core | satellite | hedge (default core).",
    ),
    shares: float | None = typer.Option(None, "--shares", help="Shares held (optional)."),
    cost_basis_usd: float | None = typer.Option(
        None, "--cost-basis-usd",
        help="Total USD cost basis (optional).",
    ),
    thesis: str | None = typer.Option(
        None, "--thesis",
        help="Why you bought (free text). Lynch's 'story' — the reassessment uses "
             "this as the baseline for story-break detection.",
    ),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Add a position to the portfolio. entry_date is mandatory — it anchors the
    5-year reconsideration window."""
    from datetime import date as _date

    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import Company, PortfolioPosition

    try:
        entry_date = _date.fromisoformat(since)
    except ValueError as exc:
        rprint(f"[red]invalid --since '{since}': {exc}[/red]")
        raise typer.Exit(code=1) from exc

    with get_session() as db:
        co = db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not co:
            rprint(
                f"[red]{ticker.upper()} not found in Company table.[/red] "
                f"Run [cyan]invest data refresh {ticker.upper()}[/cyan] first "
                f"or check the ticker spelling."
            )
            raise typer.Exit(code=1)
        existing = db.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.company_id == co.id)
            .where(PortfolioPosition.entry_date == entry_date)
        ).scalar_one_or_none()
        if existing is not None:
            rprint(
                f"[yellow]Position {ticker.upper()} entered {entry_date} already exists "
                f"(id={existing.id}, active={existing.is_active}).[/yellow] "
                f"Use [cyan]invest portfolio update {ticker.upper()}[/cyan] to modify."
            )
            raise typer.Exit(code=1)
        cpps = (cost_basis_usd / shares) if (shares and cost_basis_usd) else None
        pos = PortfolioPosition(
            company_id=co.id, ticker=ticker.upper(),
            entry_date=entry_date, role=role,
            shares=shares, cost_basis_usd=cost_basis_usd,
            cost_basis_per_share=cpps,
            thesis=thesis, notes=notes,
            is_active=True,
        )
        db.add(pos)
        db.commit()
        rprint(
            f"[green]+ portfolio[/green] {ticker.upper()}  role={role}  "
            f"entered {entry_date}"
            + (f"  shares={shares}" if shares else "")
            + (f"  cost=${cost_basis_usd:,.2f}" if cost_basis_usd else "")
        )


@portfolio_app.command("list")
def portfolio_list(
    include_inactive: bool = typer.Option(
        False, "--include-inactive",
        help="Show closed positions too (audit trail).",
    ),
) -> None:
    """List portfolio positions with reconsideration-window status."""
    from datetime import date as _date

    from sqlalchemy import select

    from data.db import get_session
    from data.models.schema import PortfolioPosition

    today = _date.today()
    with get_session() as db:
        stmt = select(PortfolioPosition).order_by(PortfolioPosition.entry_date)
        if not include_inactive:
            stmt = stmt.where(PortfolioPosition.is_active.is_(True))
        # Snapshot inside session to dodge DetachedInstanceError on render.
        rows = [
            {
                "ticker": p.ticker, "role": p.role,
                "entry_date": p.entry_date, "is_active": p.is_active,
                "shares": p.shares, "cost_basis_usd": p.cost_basis_usd,
            }
            for p in db.execute(stmt).scalars().all()
        ]

    if not rows:
        rprint("[dim](no portfolio positions — use `invest portfolio add` to add one)[/dim]")
        return

    table = Table(title="Portfolio Positions")
    table.add_column("Ticker", style="cyan")
    table.add_column("Role")
    table.add_column("Entered")
    table.add_column("Years", justify="right")
    table.add_column("Reconsideration")
    table.add_column("Shares", justify="right")
    table.add_column("Cost basis", justify="right")
    table.add_column("Active")

    for p in rows:
        years_held = (today - p["entry_date"]).days / 365.25
        if years_held >= 5:
            d22 = "[green]reconsideration window OPEN[/green]"
        elif years_held >= 4:
            d22 = "[yellow]year-4 final monitoring[/yellow]"
        elif years_held >= 1:
            d22 = f"[dim]year-{int(years_held)+1} monitoring[/dim]"
        else:
            d22 = "[dim]year-1 monitoring[/dim]"
        active = "[green]✓[/green]" if p["is_active"] else "[dim]closed[/dim]"
        cost_str = f"${p['cost_basis_usd']:,.0f}" if p["cost_basis_usd"] else "—"
        shares_str = f"{p['shares']:,.2f}" if p["shares"] else "—"
        table.add_row(
            p["ticker"], p["role"] or "—",
            p["entry_date"].isoformat(), f"{years_held:.1f}",
            d22, shares_str, cost_str, active,
        )
    console.print(table)


@portfolio_app.command("update")
def portfolio_update(
    ticker: str = typer.Argument(...),
    since: str | None = typer.Option(
        None, "--since",
        help="Update entry_date (YYYY-MM-DD). Anchors the reconsideration window — use carefully.",
    ),
    role: str | None = typer.Option(None, "--role"),
    shares: float | None = typer.Option(None, "--shares"),
    cost_basis_usd: float | None = typer.Option(None, "--cost-basis-usd"),
    thesis: str | None = typer.Option(None, "--thesis"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Update fields on an active portfolio position."""
    from datetime import date as _date

    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, PortfolioPosition

    with get_session() as db:
        co = db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not co:
            rprint(f"[red]{ticker.upper()} not in Company table.[/red]")
            raise typer.Exit(code=1)
        pos = db.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.company_id == co.id)
            .where(PortfolioPosition.is_active.is_(True))
            .order_by(desc(PortfolioPosition.entry_date)).limit(1)
        ).scalar_one_or_none()
        if pos is None:
            rprint(
                f"[red]No active portfolio position for {ticker.upper()}.[/red] "
                f"Use [cyan]invest portfolio add[/cyan] first."
            )
            raise typer.Exit(code=1)

        changes: list[str] = []
        if since is not None:
            try:
                new_date = _date.fromisoformat(since)
            except ValueError as exc:
                rprint(f"[red]invalid --since '{since}': {exc}[/red]")
                raise typer.Exit(code=1) from exc
            old = pos.entry_date
            pos.entry_date = new_date
            changes.append(f"entry_date: {old} → {new_date}")
        if role is not None:
            pos.role = role
            changes.append(f"role={role}")
        if shares is not None:
            pos.shares = shares
            changes.append(f"shares={shares}")
        if cost_basis_usd is not None:
            pos.cost_basis_usd = cost_basis_usd
            changes.append(f"cost_basis_usd={cost_basis_usd}")
        if shares and cost_basis_usd:
            pos.cost_basis_per_share = cost_basis_usd / shares
        if thesis is not None:
            pos.thesis = thesis
            changes.append("thesis updated")
        if notes is not None:
            pos.notes = notes
            changes.append("notes updated")
        if not changes:
            rprint("[dim]nothing to update — pass at least one --flag[/dim]")
            return
        db.commit()
        rprint(
            f"[green]✓ updated[/green] {ticker.upper()} (id={pos.id}): "
            + ", ".join(changes)
        )


@portfolio_app.command("remove")
def portfolio_remove(
    ticker: str = typer.Argument(...),
    note: str | None = typer.Option(
        None, "--note",
        help="Exit note — why the position was closed. Audit trail; "
             "the row is preserved (is_active=False), never deleted.",
    ),
) -> None:
    """Mark a portfolio position closed (audit-preserving)."""
    from datetime import datetime as _dt

    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, PortfolioPosition

    with get_session() as db:
        co = db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not co:
            rprint(f"[red]{ticker.upper()} not in Company table.[/red]")
            raise typer.Exit(code=1)
        pos = db.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.company_id == co.id)
            .where(PortfolioPosition.is_active.is_(True))
            .order_by(desc(PortfolioPosition.entry_date)).limit(1)
        ).scalar_one_or_none()
        if pos is None:
            rprint(f"[yellow]No active position for {ticker.upper()}.[/yellow]")
            raise typer.Exit(code=1)
        pos.is_active = False
        pos.exited_at = _dt.utcnow()
        if note:
            existing_notes = pos.notes or ""
            pos.notes = (
                f"{existing_notes}\n[exit {_dt.utcnow().date()}] {note}"
                if existing_notes else f"[exit {_dt.utcnow().date()}] {note}"
            )
        db.commit()
        rprint(
            f"[green]✓ closed[/green] {ticker.upper()} (id={pos.id}, "
            f"held {(pos.exited_at.date() - pos.entry_date).days} days). "
            f"Row preserved in audit trail."
        )


@portfolio_app.command("show")
def portfolio_show(
    ticker: str = typer.Argument(...),
) -> None:
    """Show full detail for the active portfolio position of a ticker."""
    from datetime import date as _date

    from sqlalchemy import desc, select

    from data.db import get_session
    from data.models.schema import Company, PortfolioPosition

    with get_session() as db:
        co = db.execute(
            select(Company).where(Company.ticker == ticker.upper())
        ).scalar_one_or_none()
        if not co:
            rprint(f"[red]{ticker.upper()} not in Company table.[/red]")
            raise typer.Exit(code=1)
        pos = db.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.company_id == co.id)
            .where(PortfolioPosition.is_active.is_(True))
            .order_by(desc(PortfolioPosition.entry_date)).limit(1)
        ).scalar_one_or_none()
        if pos is None:
            rprint(f"[yellow]No active portfolio position for {ticker.upper()}.[/yellow]")
            raise typer.Exit(code=1)
        # Snapshot inside session to avoid DetachedInstanceError on render.
        snap = {
            "ticker": pos.ticker, "role": pos.role,
            "entry_date": pos.entry_date,
            "shares": pos.shares, "cost_basis_usd": pos.cost_basis_usd,
            "cost_basis_per_share": pos.cost_basis_per_share,
            "thesis": pos.thesis, "notes": pos.notes,
            "company_name": co.name, "sector": co.sector, "industry": co.industry,
        }

    today = _date.today()
    years_held = (today - snap["entry_date"]).days / 365.25
    cost_line = (
        f"Shares:       {snap['shares'] or '—'}    "
        f"Cost basis: ${snap['cost_basis_usd']:,.2f}"
        if snap["cost_basis_usd"]
        else f"Shares:       {snap['shares'] or '—'}    Cost basis:   —"
    )
    panel_lines = [
        f"[bold]{snap['ticker']}[/bold] — {snap['company_name'] or 'n/a'}",
        f"[dim]{snap['sector'] or 'n/a'} / {snap['industry'] or 'n/a'}[/dim]",
        "",
        f"Entered:      {snap['entry_date']}    Role: {snap['role'] or '—'}",
        f"Years held:   {years_held:.2f}    Reconsideration window: "
        + ("[green]OPEN at year-5[/green]" if years_held >= 5
           else f"[dim]opens at year 5 ({5-years_held:.1f}y away)[/dim]"),
        cost_line,
    ]
    if snap["cost_basis_per_share"]:
        panel_lines.append(f"Cost per share: ${snap['cost_basis_per_share']:.4f}")
    if snap["thesis"]:
        panel_lines.append("")
        panel_lines.append("[bold]Thesis (original story):[/bold]")
        panel_lines.append(f"  {snap['thesis']}")
    if snap["notes"]:
        panel_lines.append("")
        panel_lines.append("[dim]Notes:[/dim]")
        panel_lines.append(f"  [dim]{snap['notes']}[/dim]")
    console.print(Panel(
        "\n".join(panel_lines),
        title=f"Portfolio · {snap['ticker']}",
        border_style="cyan",
    ))


# ── Skill runner (ADR-032) ───────────────────────────────────────────────

skill_app = typer.Typer(
    no_args_is_help=True,
    help="Run a project-local skill from .claude/skills/ (ADR-032).",
)
app.add_typer(skill_app, name="skill")


@skill_app.command("list")
def skill_list() -> None:
    """List all project-local skills with their shadow-mode status."""
    from pathlib import Path
    from cli.skills.runtime import load_skill_frontmatter, shadow_mode_status
    skills_dir = Path(".claude/skills")
    if not skills_dir.exists():
        rprint("[red].claude/skills/ does not exist.[/red]")
        raise typer.Exit(code=1)
    # `_`-prefixed files (the generated `_lineage.md` index) are not skills.
    files = sorted(
        p for p in skills_dir.glob("*.md")
        if p.name.lower() != "readme.md" and not p.name.startswith("_")
    )
    table = Table(title="Project-local skills (ADR-032)", show_lines=False)
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Dangerous")
    table.add_column("Shadow status")
    table.add_column("Total inv.")
    table.add_column("Clean")
    for path in files:
        try:
            fm = load_skill_frontmatter(path.stem)
            status = shadow_mode_status(path.stem)
        except Exception as exc:  # noqa: BLE001
            table.add_row(path.stem, "—", "—", f"[red]ERROR: {exc}[/red]", "—", "—")
            continue
        danger = "[red]YES[/red]" if fm.get("dangerous") else "no"
        shadow = "[yellow]active[/yellow]" if status["currently_in_shadow"] else "graduated"
        table.add_row(
            path.stem,
            str(fm.get("version", "?")),
            danger,
            shadow,
            str(status["total_invocations"]),
            str(status["clean_invocations"]),
        )
    console.print(table)


@skill_app.command("status")
def skill_status(
    name: str = typer.Argument(..., help="Skill name (e.g. audit-completeness)"),
) -> None:
    """Show shadow-mode status + recent invocations for a skill."""
    from cli.skills.runtime import shadow_mode_status
    try:
        status = shadow_mode_status(name)
    except FileNotFoundError:
        rprint(f"[red]No skill at .claude/skills/{name}.md[/red]")
        raise typer.Exit(code=1)
    console.print(Panel(
        f"Skill: [bold]{name}[/bold]  v{status['version']}\n"
        f"Total invocations: {status['total_invocations']}\n"
        f"Clean invocations: {status['clean_invocations']} / 10 to graduate\n"
        f"Shadow until: {status['shadow_mode_until']} "
        f"({status['days_remaining']} days remaining)\n"
        f"Currently in shadow: {status['currently_in_shadow']}",
        title="Shadow-mode status",
    ))


@skill_app.command("run")
def skill_run(
    name: str = typer.Argument(..., help="Skill name (e.g. audit-completeness)"),
    ticker: str | None = typer.Argument(None, help="Ticker arg (most skills)"),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="Required for dangerous: true skills (per ADR-032 §2.4)",
    ),
    period_end: str | None = typer.Option(
        None, "--period-end",
        help="ISO date for external-signals target period (default: latest calendar quarter)",
    ),
) -> None:
    """Run a skill by name.

    Examples:
      invest skill run audit-completeness SHOP
      invest skill run dive-complete SHOP
      invest skill run external-signals SHOP --confirm
    """
    from cli.skills.runtime import run_skill
    args: dict[str, Any] = {}
    if ticker:
        args["ticker"] = ticker
    if period_end:
        args["period_end"] = period_end
    result = run_skill(name, args=args, confirm_dangerous=confirm)

    if result.render_output:
        console.print(result.render_output)

    # Postcondition summary
    if result.postconditions:
        rprint("\n[bold]Postconditions:[/bold]")
        for p in result.postconditions:
            mark = "[green]PASS[/green]" if p.pass_ else "[red]FAIL[/red]"
            rprint(f"  {mark} {p.name}")

    # Anomalies
    if result.anomalies:
        rprint("\n[yellow]Anomalies (shadow-mode):[/yellow]")
        for a in result.anomalies:
            rprint(f"  · {a}")

    # Telemetry summary
    rprint(
        f"\n[dim]success={result.success}  "
        f"cost=${result.cost_usd:.4f}  "
        f"prompt_tok={result.tokens_prompt}  comp_tok={result.tokens_completion}[/dim]"
    )

    if not result.success:
        if result.error_message:
            rprint(f"[red]Error:[/red] {result.error_message}")
        raise typer.Exit(code=1)


@skill_app.command("compose")
def skill_compose(
    name: str | None = typer.Argument(
        None,
        help="Skill name (e.g. dive-complete). Omit for cross-skill graph.",
    ),
    validate: bool = typer.Option(
        False, "--validate",
        help="Exit non-zero on any composition validation error (CI gate).",
    ),
) -> None:
    """Show a skill's composition (dependencies) per ADR-036.

    Default: cross-skill dependency graph (all edges).
    With a skill name: that skill's tree view.
    With --validate: exit 1 on any error finding.
    """
    from cli.skills.composability import (
        load_all_compositions, load_skill_composition,
        render_composition_tree, render_dependency_graph, render_findings,
    )
    from cli.skills.runtime import load_skill_frontmatter

    if name:
        try:
            comp, findings = load_skill_composition(name)
        except FileNotFoundError:
            rprint(f"[red]No skill named {name!r} in .claude/skills/[/red]")
            raise typer.Exit(code=1)
        fm = load_skill_frontmatter(name)
        rprint(render_composition_tree(comp, current_version=fm.get("version", "?")))

        # Mental models block (documentary — see ADR-024). Always shown
        # when declared; typo warnings surface alongside but do NOT trigger
        # --validate exit (linkage is documentary, not runtime).
        from cli.skills.mental_model_refs import (
            load_skill_mental_models, render_mental_models_block,
        )
        model_refs, model_findings = load_skill_mental_models(name)
        if model_refs:
            rprint("")
            rprint(render_mental_models_block(model_refs))
        if model_findings:
            rprint("")
            for f in model_findings:
                rprint(f.render_line())

        if findings:
            rprint(render_findings(findings))
        if validate and any(f.severity == "error" for f in findings):
            raise typer.Exit(code=1)
        return

    comps, findings = load_all_compositions()
    rprint(render_dependency_graph(comps))
    if findings:
        rprint(render_findings(findings))
    if validate and any(f.severity == "error" for f in findings):
        rprint(f"\n[red]Composition validation failed.[/red]")
        raise typer.Exit(code=1)


@skill_app.command("eval")
def skill_eval(
    name: str | None = typer.Argument(
        None,
        help="Skill name (e.g. dive-complete). Omit to evaluate all skills.",
    ),
    validate: bool = typer.Option(
        False, "--validate",
        help="Exit non-zero on any FAIL (CI gate per ADR-035 §4).",
    ),
) -> None:
    """Evaluate a skill (or all skills) across the four Anthropic eval
    dimensions: frontmatter_structure, script_execution, output_quality,
    triggering_accuracy.

    Per ADR-035, the deterministic dimensions (frontmatter + script) gate
    CI. output_quality is permissive today (output_schema declaration is
    optional). triggering_accuracy is deferred — always SKIPs (no LLM
    eval runner yet).
    """
    from cli.skills.evals import (
        has_any_failures, render_summary, run_all_skill_evals,
        run_skill_evals,
    )

    if name:
        rep = run_skill_evals(name)
        rprint(rep.render())
        if validate and rep.has_failure:
            raise typer.Exit(code=1)
        return

    reports = run_all_skill_evals()
    rprint(render_summary(reports))
    rprint("")
    for rep in reports:
        rprint(rep.render())
        rprint("")
    if validate and has_any_failures(reports):
        rprint("[red]Validation failed: one or more skills have FAIL findings.[/red]")
        raise typer.Exit(code=1)


@skill_app.command("lineage")
def skill_lineage(
    name: str | None = typer.Argument(
        None,
        help="Skill name (e.g. dive-complete). Omit to see the cross-skill view.",
    ),
    rebuild: bool = typer.Option(
        False, "--rebuild",
        help="Regenerate .claude/skills/_lineage.md from current frontmatter.",
    ),
    validate: bool = typer.Option(
        False, "--validate",
        help="Exit non-zero if any lineage validation error is found (CI gate).",
    ),
) -> None:
    """Show skill version lineage — Anthropic's Evaluation/Versioning/Composability
    "Versioning" pillar (per ADR-034).

    Without arguments: cross-skill chronological timeline (newest first).
    With a skill name: that skill's per-version timeline (oldest first).
    With --rebuild: regenerate the canonical _lineage.md index.
    With --validate: error out if any version<->changelog inconsistency.
    """
    from pathlib import Path
    from cli.skills.lineage import (
        load_all_skill_lineages, load_skill_lineage,
        render_cross_skill_timeline, render_skill_timeline,
        render_findings, rebuild_lineage_index,
    )

    if rebuild:
        body = rebuild_lineage_index()
        target = Path(".claude/skills/_lineage.md")
        target.write_text(body, encoding="utf-8")
        rprint(f"[green]Rebuilt[/green] {target} ({len(body)} chars).")
        return

    if name:
        try:
            ln, findings = load_skill_lineage(name)
        except FileNotFoundError:
            rprint(f"[red]No skill named {name!r} in .claude/skills/[/red]")
            raise typer.Exit(code=1)
        rprint(render_skill_timeline(ln))
        if findings:
            rprint(render_findings(findings))
        return

    # Cross-skill view
    lineages, findings = load_all_skill_lineages()
    rprint(render_cross_skill_timeline(lineages))
    if findings:
        rprint(render_findings(findings))

    if validate:
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            rprint(f"\n[red]Validation failed: {len(errors)} error(s).[/red]")
            raise typer.Exit(code=1)


# ── Intrinsic value (ADR-027 / 028 / 029 / 030) ──────────────────────────────
# Named `iv` because the SKILL is named `intrinsic-value`, and .claude/skills/
# README forbids a skill shadowing a CLI subcommand name.

# Reliability verdicts for the headline forward-DCF number.
_IV_RELIABLE = "reliable"
_IV_QUALIFIED = "qualified"
_IV_UNRELIABLE = "unreliable"


def _iv_reliability(result: object) -> tuple[str, list[str]]:
    """Decide whether the headline forward IV may be presented as a number.

    The engine is arithmetically correct in every case below; the question
    this answers is different — whether the MODEL APPLIES to this company.
    ADR-030 was written because a correct calculation on inapplicable inputs
    (INTA: $5 IV vs $24 price) is more dangerous than no number at all, since
    it looks like an answer.

    Returns (verdict, reasons).
    """
    reasons: list[str] = []
    tier = str(getattr(result, "tier", "") or "")
    gaps = list(getattr(result, "data_gaps", []) or [])
    iv = getattr(result, "intrinsic_value_per_share", None)

    if iv is None:
        reasons.append(
            f"engine refused to emit an IV (tier {tier!r}) — this is the "
            f"correct outcome, not a failure"
        )
        return _IV_UNRELIABLE, reasons

    # (1) Young without a scenario — ADR-030's originating failure.
    if tier.endswith("_young"):
        reasons.append(
            f"tier {tier}: ROIC is below mature-peer level or unstable, so "
            f"fundamental growth (g = ROIC x reinvestment) understates the "
            f"business. ADR-030 routes this to an ADR-028 scenario DCF — but "
            f"no scenario was supplied, so the number shown is the fundamental "
            f"DCF that ADR-030 exists to prevent being taken at face value"
        )

    # (2) The growth cap binds — the projection is no longer the story.
    for gap in gaps:
        low = gap.lower()
        if "capped to wacc" in low or ">= wacc" in low:
            reasons.append(
                "fundamental growth exceeded WACC and was capped to WACC-50bps; "
                "the high-growth phase is being modelled at a rate the company "
                "is not growing at, which biases IV DOWN"
            )
            break

    # (3) Stale macro — every WACC in the system inherits this.
    stale = [g for g in gaps if "stale" in g.lower()]
    if stale:
        reasons.append(
            f"{len(stale)} macro reference input(s) stale (risk-free rate / ERP) "
            f"— WACC, and therefore every discounted value, is built on them"
        )

    if any(r.startswith("tier ") for r in reasons):
        return _IV_UNRELIABLE, reasons
    if reasons:
        return _IV_QUALIFIED, reasons
    return _IV_RELIABLE, reasons


@app.command("iv")
def intrinsic_value(
    ticker: str = typer.Argument(..., help="Ticker, e.g. NVDA or BONEX.ST"),
    years: int = typer.Option(8, "--years", "-y", help="High-growth phase length."),
    terminal_growth: float | None = typer.Option(
        None, "--terminal-growth", help="Override terminal g (decimal). Default: risk-free."
    ),
    scenario: Path | None = typer.Option(
        None, "--scenario", help="JSON file of ADR-028 ScenarioInputs (young companies)."
    ),
    show_gaps: bool = typer.Option(True, "--gaps/--no-gaps", help="Print the data-gap register."),
    persist: bool = typer.Option(True, "--persist/--no-persist", help="Write to warehouse + JSONL log."),
    greenwald: bool = typer.Option(
        True, "--greenwald/--no-greenwald",
        help="Run the Greenwald ladder (asset value → EPV → franchise test).",
    ),
) -> None:
    """Intrinsic value via BOTH frameworks, deterministically.

    Damodaran (forward FCFF DCF, ADR-027) prices an explicit story: growth,
    fade, terminal value. Greenwald (ADR-042) refuses to forecast and instead
    asks whether current earning power exceeds what a competitor would spend to
    reproduce the assets — a moat test denominated in currency.

    They answer different questions, so they are reported side by side rather
    than reconciled into one number. Where they disagree, the disagreement is
    the finding.
    """
    import json as _json

    from valuation.damodaran import compute_and_persist
    from valuation.damodaran.loader import (
        CompanyNotFoundError,
        InsufficientDataError,
    )

    tk = ticker.upper()

    scenario_obj = None
    if scenario is not None:
        if not scenario.exists():
            rprint(f"[red]Scenario file not found: {scenario}[/red]")
            raise typer.Exit(code=1)
        from valuation.damodaran.young_company import ScenarioInputs
        try:
            payload = _json.loads(scenario.read_text(encoding="utf-8"))
            scenario_obj = ScenarioInputs(**payload)
        except (ValueError, TypeError) as exc:
            # ADR-028 story discipline: scenario_name is mandatory and the
            # constructor refuses anonymous defaults. Surface that verbatim.
            rprint(f"[red]Invalid scenario ({exc.__class__.__name__}): {exc}[/red]")
            raise typer.Exit(code=1) from exc

    try:
        result = compute_and_persist(
            tk,
            high_growth_years=years,
            growth_rate_terminal=terminal_growth,
            young_company_scenario=scenario_obj,
            log_run=persist,
        )
    except CompanyNotFoundError:
        rprint(f"[red]{tk} not in DB.[/red] Run: invest data refresh {tk}")
        raise typer.Exit(code=1) from None
    except InsufficientDataError as exc:
        rprint(f"[yellow]{tk}: insufficient data — {exc}[/yellow]")
        raise typer.Exit(code=1) from None

    verdict, reasons = _iv_reliability(result)
    price = getattr(result, "current_price", None) or 0.0
    iv = getattr(result, "intrinsic_value_per_share", None)
    epv = getattr(result, "epv_per_share", None)
    tier = str(getattr(result, "tier", "?"))
    maturity = getattr(getattr(result, "maturity_classification", None), "tier", None)
    src_tier = _data_source_tier_for(tk)

    header = {
        _IV_RELIABLE: "[green]HEADLINE IV USABLE[/green]",
        _IV_QUALIFIED: "[yellow]HEADLINE IV QUALIFIED[/yellow]",
        _IV_UNRELIABLE: "[red]HEADLINE IV NOT USABLE AS A VALUATION[/red]",
    }[verdict]
    rprint(Panel(
        f"{header}\nTier: [bold]{tier}[/bold]  ·  maturity: {maturity}  ·  "
        f"fundamentals source: {src_tier}",
        title=f"Intrinsic Value — {tk}", border_style={
            _IV_RELIABLE: "green", _IV_QUALIFIED: "yellow", _IV_UNRELIABLE: "red"}[verdict],
    ))

    table = Table(title="Three lenses", show_header=True)
    table.add_column("Lens"); table.add_column("Value", justify="right")
    table.add_column("vs price", justify="right"); table.add_column("Reads as")

    def _pct(v: float | None) -> str:
        return f"{v * 100:+.1f}%" if v is not None else "—"

    table.add_row("Market price", f"{price:,.2f}", "—", "what you pay today")
    table.add_row(
        "Forward DCF (ADR-027)",
        f"{iv:,.2f}" if iv is not None else "[red]refused[/red]",
        _pct(getattr(result, "margin_of_safety_pct", None)),
        "growth + fade + terminal" if verdict != _IV_UNRELIABLE
        else "[red]do not quote[/red]",
    )
    table.add_row(
        "EPV floor (Greenwald)", f"{epv:,.2f}" if epv is not None else "—",
        _pct(getattr(result, "mos_vs_epv_pct", None)),
        "value if growth = 0 forever",
    )
    implied_g = getattr(result, "reverse_implied_growth_rate", None)
    feas = getattr(result, "reverse_implied_growth_feasibility", None)
    table.add_row(
        "Market-implied growth", _pct(implied_g), "—",
        f"feasibility: {feas}" if feas else "—",
    )
    rprint(table)

    # The reverse solver bisects growth_rate_high, but the projection caps
    # growth below WACC. When the solve lands on that ceiling, the number is
    # the MODEL's limit, not the market's expectation — say so rather than
    # letting it be read as "the market implies 8.7%".
    if feas in ("extreme", "unsolvable_above_ceiling") and implied_g is not None:
        rprint(
            "[yellow]  ⚠ Market-implied growth saturated at the model's growth "
            "ceiling (WACC−50bps). Read as 'the market implies MORE growth than "
            "this model can express', not as a point estimate.[/yellow]"
        )

    if reasons:
        rprint("\n[bold]Why the headline is qualified:[/bold]")
        for r in reasons:
            rprint(f"  • {r}")

    if verdict == _IV_UNRELIABLE and tier.endswith("_young"):
        rprint(
            "\n[bold]To value this properly[/bold] supply an ADR-028 scenario "
            "(a stated story, not a default):\n"
            f"  invest iv {tk} --scenario my_scenario.json\n"
            "  {\"scenario_name\": \"...\", \"revenue_year_N\": 0.0, "
            "\"target_op_margin\": 0.0, \"sales_to_capital_ratio\": 0.0}"
        )

    # ── Greenwald ladder (ADR-042) ────────────────────────────────────────
    gw = None
    if greenwald:
        from valuation.greenwald import (
            EPV_APPLICABLE,
            EPV_INFLECTING,
            compute_greenwald_valuation,
        )
        try:
            gw = compute_greenwald_valuation(tk)
        except Exception as exc:  # noqa: BLE001
            rprint(f"[yellow]Greenwald ladder unavailable: {exc}[/yellow]")

    if gw is not None:
        av, ep, fr = gw.asset_value, gw.earnings_power, gw.franchise
        ep_used = gw.epv_recent_regime or ep
        rprint(Panel(
            f"Discounted at the SAME WACC as the Damodaran ladder: "
            f"[bold]{gw.wacc_used:.2%}[/bold] ({gw.wacc_source})",
            title="Greenwald — Asset Value → Earnings Power → Franchise",
            border_style="cyan",
        ))

        ladder = Table(show_header=True)
        ladder.add_column("Rung"); ladder.add_column("Per share", justify="right")
        ladder.add_column("Reads as")
        ladder.add_row(
            "1. Asset reproduction value",
            f"{av.asset_value_per_share:,.2f}" if av.asset_value_per_share is not None else "—",
            "cost for a competitor to rebuild the asset base",
        )
        ladder.add_row(
            "2. Earnings power (full history)",
            f"{ep.epv_per_share:,.2f}" if ep.epv_per_share is not None else "—",
            f"median margin {ep.normalized_op_margin:.1%} capitalised at WACC"
            if ep.normalized_op_margin is not None else "—",
        )
        if gw.epv_recent_regime is not None:
            r = gw.epv_recent_regime
            ladder.add_row(
                "2b. Earnings power (recent regime)",
                f"[bold]{r.epv_per_share:,.2f}[/bold]" if r.epv_per_share is not None else "—",
                f"post-inflection years only, median {r.normalized_op_margin:.1%}"
                if r.normalized_op_margin is not None else "—",
            )
        ladder.add_row("3. Market price", f"{gw.current_price:,.2f}" if gw.current_price else "—",
                       "what the market says today")
        rprint(ladder)

        if gw.epv_applicability != EPV_APPLICABLE:
            style = "yellow" if gw.epv_applicability == EPV_INFLECTING else "red"
            rprint(f"[{style}]  ⚠ EPV applicability: {gw.epv_applicability} — "
                   f"{gw.epv_applicability_reason}[/{style}]")

        verdict_colour = {
            "franchise": "green", "no_franchise": "yellow",
            "value_destruction": "red", "indeterminate": "dim",
        }.get(fr.verdict, "dim")
        ratio_txt = f"{fr.epv_to_av_ratio:.2f}x" if fr.epv_to_av_ratio is not None else "n/a"
        rprint(Panel(
            f"[bold]{fr.verdict.replace('_', ' ').upper()}[/bold]  ·  EPV / AV = {ratio_txt}\n\n"
            f"{fr.interpretation}",
            title="Franchise test — is growth worth paying for?",
            border_style=verdict_colour,
        ))

        # ── Cross-engine synthesis: the disagreement IS the finding ──
        rprint("\n[bold]Cross-engine reading[/bold]")
        dcf_ok = verdict == _IV_RELIABLE
        franchise_ok = fr.growth_is_worth_paying_for
        if franchise_ok is None:
            rprint("  • Franchise test indeterminate — treat the forward DCF as "
                   "unanchored: nothing independent confirms its growth assumption.")
        elif franchise_ok and dcf_ok:
            rprint("  • Both engines agree: a franchise exists AND the forward model "
                   "applies. This is the only configuration where a DCF growth "
                   "assumption is independently supported.")
        elif franchise_ok and not dcf_ok:
            rprint("  • Franchise confirmed, but the forward DCF is not usable here. "
                   "The Greenwald ladder is the defensible anchor; growth has value "
                   "but this model cannot size it.")
        elif not franchise_ok and iv is not None:
            rprint("  • [yellow]Divergence:[/yellow] the forward DCF prices growth, but the "
                   "franchise test says returns have competed to reproduction cost. "
                   "In commodity economics growth is worth ~zero — a DCF will still "
                   "assign it value because g is an input, not a finding. Weight the "
                   "EPV floor, not the DCF.")
        if ep_used.epv_per_share and gw.current_price:
            gap_to_epv = (gw.current_price - ep_used.epv_per_share) / gw.current_price
            rprint(f"  • {gap_to_epv:+.0%} of today's price sits ABOVE earnings power — "
                   f"that portion is paid for growth and franchise durability, not "
                   f"current earnings.")

    if show_gaps:
        gaps = list(getattr(result, "data_gaps", []) or [])
        if gw is not None:
            gaps = gaps + [f"[greenwald] {g}" for g in gw.data_gaps]
        if gaps:
            rprint(f"\n[dim]Data gaps ({len(gaps)}):[/dim]")
            for g in gaps:
                rprint(f"  [dim]· {g}[/dim]")

    inversions = list(getattr(result, "inversion_questions", []) or [])
    if inversions:
        rprint("\n[bold]Inversion — what must be true for this to be wrong:[/bold]")
        for q in inversions:
            rprint(f"  ? {q}")
        if gw is not None and gw.franchise.growth_is_worth_paying_for:
            rprint("  ? The franchise test says barriers exist. Name them — and name "
                   "what would remove them (moat/challenger_inversion_test).")


def main() -> None:
    """Console-script entrypoint. Turns setup errors into guidance, not tracebacks."""
    from sqlalchemy.exc import OperationalError

    from config.settings import MissingEdgarIdentityError
    try:
        app()
    except MissingEdgarIdentityError as exc:
        rprint("[bold red]Setup incomplete[/bold red]")
        rprint("")
        rprint(str(exc))
        raise SystemExit(2) from None
    except OperationalError as exc:
        # An unmigrated database is the likeliest first-run mistake; anything
        # else is a real fault and keeps its traceback.
        if "no such table" not in str(exc):
            raise
        rprint("[bold red]Database schema is missing[/bold red]")
        rprint("")
        rprint("Create it, then re-run this command:")
        rprint("")
        rprint("    uv run invest db-init      [dim](or `invest db-init` on an active venv)[/dim]")
        raise SystemExit(2) from None


# ── LLM call records (ADR-048) ──────────────────────────────────────────────

llm_app = typer.Typer(help="Read the recorded LLM calls (ADR-048). Free: no model is called.")
app.add_typer(llm_app, name="llm")


@llm_app.command("stats")
def llm_stats(
    days: int = typer.Option(30, "--days", help="Look back this many days."),
) -> None:
    """Calls, failures, latency and cost by call site, model and prompt version."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import case, func, select

    from data.db import get_session
    from data.models.schema import LlmCall

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)  # created_at is UTC
    failed = func.sum(case((LlmCall.status != "ok", 1), else_=0))
    ok_priced = func.sum(case((LlmCall.status == "ok", case((LlmCall.cost_usd.is_not(None), 1)))))
    q = (
        select(
            LlmCall.call_site, func.coalesce(LlmCall.purpose, "use"), LlmCall.model,
            LlmCall.prompt_version,
            func.count(), failed, func.avg(LlmCall.latency_ms),
            func.sum(LlmCall.cost_usd), func.count(LlmCall.cost_usd), ok_priced,
        )
        .where(LlmCall.created_at >= since)
        .group_by(LlmCall.call_site, LlmCall.purpose, LlmCall.model, LlmCall.prompt_version)
        .order_by(LlmCall.call_site, LlmCall.purpose, LlmCall.model, LlmCall.prompt_version)
    )  # fmt: skip
    with get_session() as session:
        rows = session.execute(q).all()
    if not rows:
        rprint(f"No LLM calls recorded in the last {days} days.")
        return
    table = Table(title=f"LLM calls, last {days} days")
    for col in ("Call site", "Purpose", "Model"):
        table.add_column(col)
    for col in ("Prompt v", "Calls", "Failed", "Avg latency", "Cost", "Per ok call"):
        table.add_column(col, justify="right")
    # Eval runs (ADR-047) are their own rows, so real-use cost is never mixed with them.
    for site, purpose, model, version, n, n_failed, latency, cost, priced, ok_n in rows:
        # Unpriced calls are counted, not costed; failed attempts cost nothing but are not calls.
        per_call = f"${cost / ok_n:.4f}" if ok_n else "—"
        unpriced = "" if priced == n else f" ({n - priced} unpriced)"
        total = f"${cost:.4f}{unpriced}" if priced else "—"
        table.add_row(
            site, purpose, model, str(version), str(n), str(n_failed or 0),
            f"{(latency or 0) / 1000:.1f}s", total, per_call,
        )  # fmt: skip
    console.print(table)


narrative_app = typer.Typer(help="Narrative evaluation (ADR-047).")
eval_app = typer.Typer(help="The golden set, graders and replay; only `run` calls a model.")
narrative_app.add_typer(eval_app, name="eval")
app.add_typer(narrative_app, name="narrative")


@eval_app.command("export")
def narrative_eval_export(
    out: Path = typer.Option(Path("tests/fixtures/narrative_golden"), "--out"),
    write: bool = typer.Option(False, "--write", help="Write cases; otherwise report only."),
) -> None:
    """Export each company's latest frozen dive view as a golden-set case. DB-only."""
    from data.db import get_session
    from deepdive.narrative_eval.export import (
        TEST, TRAIN, collect_cases, coverage, write_cases,
    )  # fmt: skip

    with get_session() as session:
        cases = collect_cases(session)
    n_test = sum(c.split == TEST for c in cases)
    rprint(f"{len(cases)} cases: {len(cases) - n_test} train, {n_test} test")
    table = Table(title="Strata (ADR-047 §2.1)")
    table.add_column("Stratum")
    for col in (TRAIN, TEST):
        table.add_column(col, justify="right")
    for stratum, n in coverage(cases).items():
        missing = "[red]0[/red]"
        table.add_row(stratum, str(n[TRAIN] or missing), str(n[TEST] or missing))
    console.print(table)
    withheld = sum(len(c.withheld) for c in cases)
    rprint(f"{withheld} third-party values withheld across {len(cases)} cases")
    if write:
        paths = write_cases(cases, out)
        rprint(f"[green]Wrote {len(paths)} files under {out}[/green]")


@eval_app.command("replay")
def narrative_eval_replay(
    golden: Path = typer.Option(Path("tests/fixtures/narrative_golden"), "--golden"),
    record: bool = typer.Option(False, "--record", help="Write grades.json; else compare."),
) -> None:
    """Re-grade every stored output against its case. Free: no model is called.

    Exits 1 when a case or output no longer replays, or a grade differs from grades.json.
    """
    import json as _json

    from deepdive.narrative_eval.export import TEST, TRAIN
    from deepdive.narrative_eval.graders import (
        VERDICT_GRADERS, grades_path, replay, serialise, summary,
    )  # fmt: skip

    result = replay(golden)
    for line in result.drift:
        rprint(f"[red]drift: {line}[/red]")
    changed = []
    for (model, version), by_case in sorted(result.grades.items()):
        table = Table(title=f"{model}, prompt v{version}")
        table.add_column("Split")
        for col in ("Cases", *VERDICT_GRADERS, "Cost", "p50", "p95"):
            table.add_column(col, justify="right")
        for split in (TEST, TRAIN):
            s = summary(by_case, result.splits, split)
            rates = ["—" if s[g] is None else f"{s[g]:.0%}" for g in VERDICT_GRADERS]
            cost = "—" if s["cost_per_narrative"] is None else f"${s['cost_per_narrative']:.4f}"
            p50, p95 = (
                "—" if s[k] is None else f"{s[k] / 1000:.1f}s"
                for k in ("latency_p50_ms", "latency_p95_ms")
            )
            table.add_row(split, str(s["cases"]), *rates, cost, p50, p95)
        console.print(table)
        path, grades = grades_path(golden, model, version), serialise(by_case)
        if record:
            path.write_text(_json.dumps(grades, indent=2) + "\n", "utf-8")
        elif not path.exists() or _json.loads(path.read_text("utf-8")) != grades:
            changed.append(str(path))
    for where in changed:
        rprint(f"[red]grades differ from {where}; rerun with --record if intended[/red]")
    if not result.grades:
        rprint("No stored outputs to grade.")
    if result.drift or changed:
        raise typer.Exit(1)


@eval_app.command("run")
def narrative_eval_run(
    provider: str = typer.Option(..., "--provider", help="anthropic or openai."),
    model: str = typer.Option(..., "--model", help="Must have a row in config/llm_prices.py."),
    split: str = typer.Option("test", "--split", help="test, train or all."),
    limit: int | None = typer.Option(None, "--limit", help="At most this many cases."),
    golden: Path = typer.Option(Path("tests/fixtures/narrative_golden"), "--golden"),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation."),
) -> None:
    """Generate one narrative per golden-set case. SPENDS TOKENS, after a priced confirmation.

    Cases that already have an output for this model and prompt version are skipped.
    """
    from config.llm_prices import UnpricedModelError
    from deepdive.narrative import PROMPT_VERSION, NarrativeUnavailableError
    from deepdive.narrative_eval.runner import (
        MAX_CONSECUTIVE_FAILURES,
        estimate_cost,
        output_path,
        refusal,
        run_case,
        select_cases,
        write_output,
    )
    from deepdive.narrative_output import NarrativeProvider

    if split not in ("test", "train", "all"):
        rprint("[red]--split is test, train or all.[/red]")
        raise typer.Exit(2)
    try:
        chosen = NarrativeProvider(provider.lower())
    except ValueError:
        rprint("[red]--provider is anthropic or openai.[/red]")
        raise typer.Exit(2) from None
    cases = [
        c for c in select_cases(golden, split)
        if not output_path(golden, model, PROMPT_VERSION, c["case_id"]).exists()
    ][:limit]  # fmt: skip
    if not cases:
        rprint(f"Nothing to run: every {split} case has an output for {model} v{PROMPT_VERSION}.")
        return
    if why := refusal(chosen, model):
        rprint(f"[red]Not starting: {why}.[/red]")
        raise typer.Exit(2)
    try:
        estimate = estimate_cost(cases, model)
    except UnpricedModelError as exc:
        rprint(f"[red]{exc}. Copy its price row first (ADR-048).[/red]")
        raise typer.Exit(2) from None
    rprint(
        f"{len(cases)} {split} cases on {chosen.value}/{model}, prompt v{PROMPT_VERSION}: "
        f"estimated ${estimate:.2f} (input from prompt length, ~3.8k output tokens each)"
    )
    if not yes and not typer.confirm("Spend this?", default=False):
        raise typer.Exit(1)
    written = failed = streak = 0
    for i, case in enumerate(cases, 1):
        try:
            write_output(golden, run_case(case, chosen, model))
            written += 1
            streak = 0
        except NarrativeUnavailableError as exc:
            failed += 1
            streak += 1
            rprint(f"  [yellow]{case['case_id']}: {exc}[/yellow]")
        rprint(f"  {i}/{len(cases)} {case['case_id']}")
        if streak == MAX_CONSECUTIVE_FAILURES and i < len(cases):
            rprint(f"[red]Stopping: {streak} failures in a row. Rerun to resume.[/red]")
            break
    not_run = len(cases) - written - failed
    rprint(
        f"{written} written, {failed} failed, {not_run} not run. Grade them with "
        "`invest narrative eval replay --record`; actual spend is in `invest llm stats`."
    )
    if not_run:
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
