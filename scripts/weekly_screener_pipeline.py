"""Weekly screener → auto-dive pipeline ($100M-$2B mid-caps).

Why this exists
---------------
The warehouse screener can't evaluate moat overlays (ICA already
propagates per DEC-30, but PSA/BEW need price-history + parent-co data
not in the screener's scope) or full Munger/Dorsey moat narrative
— those live in the dive layer. This pipeline closes the gap by
running an actual `invest dive` on the top-N candidates each week,
producing an enriched watchlist with BEW + ICA + PSA + SIM signals
per ticker.

What it does
------------
1. Pulls the top-N (default 30) $100M-$2B tickers the active exclusion
   policy confirms eligible, ranked by Company.composite_score
2. Runs `invest dive TICKER --auto-overlays` on each. The dive
   computes all 7 frameworks, runs every triggered overlay (BEW
   mandatory per DEC-33), persists a FrameworkScore + DeepDiveRun
   row. NO LLM narrative is fired (`--narrate` is opt-in on the
   scorecard command, not dive) — keeps the run cheap and fast.
3. Aggregates the fresh FrameworkScore rows + overlay-run flags
   into a ranked report.
4. Writes the report + per-ticker dive log to narrative_dumps/.

Runtime
-------
~3 min per dive × 30 tickers = 90 min. Plus initial query +
report assembly. Schedule for Sunday 20:00; finishes by ~21:30.

Triggered by the Windows Task Scheduler task "Weekly Midcap Screener".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, RuntimeError):
    pass

from sqlalchemy import select

from data.db import SessionLocal
from data.models.schema import Company, FrameworkScore
from screener.policies import ExclusionPolicy, get_policy


CAP_MIN = 100_000_000
CAP_MAX = 2_000_000_000
TOP_N = 30
OUTPUT_DIR = Path("narrative_dumps")
LOG_PREFIX = "weekly_screener"
DIVE_TIMEOUT_SEC = 600    # 10 min per ticker — enough for full-refresh + 7 frameworks + overlays


def _log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _load_top_n(n: int, policy: ExclusionPolicy) -> list[str]:
    """Return top-N policy-eligible $100M-$2B tickers by Company.composite_score."""
    with SessionLocal() as s:
        rows = s.execute(
            select(Company.ticker)
            .where(
                policy.eligible(),
                Company.market_cap_usd >= CAP_MIN,
                Company.market_cap_usd <= CAP_MAX,
                Company.composite_score.isnot(None),
            )
            .order_by(Company.composite_score.desc())
            .limit(n)
        ).all()
    return [r[0] for r in rows]


def _run_dive(ticker: str) -> tuple[bool, str]:
    """Subprocess `invest dive TICKER --auto-overlays`. Returns (ok, log_tail)."""
    cp = subprocess.run(
        [
            "uv", "run", "invest", "dive", ticker,
            "--auto-overlays",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=DIVE_TIMEOUT_SEC,
    )
    ok = cp.returncode == 0
    # Tail of combined output for the log
    tail_lines = (cp.stdout + cp.stderr).strip().splitlines()
    tail = "\n".join(tail_lines[-20:])
    return ok, tail


def _collect_results(tickers: list[str], run_date: date, policy: ExclusionPolicy) -> list[dict]:
    """Pull today's FrameworkScore rows for the dived tickers + company metadata."""
    results: list[dict] = []
    with SessionLocal() as s:
        for t in tickers:
            co = s.execute(select(Company).where(Company.ticker == t)).scalar_one_or_none()
            if not co:
                continue
            fs = s.execute(
                select(FrameworkScore)
                .where(
                    FrameworkScore.company_id == co.id,
                    FrameworkScore.run_date == run_date,
                )
                .order_by(FrameworkScore.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if not fs:
                continue
            results.append({
                "ticker": t,
                "name": co.name,
                "market_cap_usd": co.market_cap_usd,
                "sector": co.sector,
                "composite": fs.composite_score,
                "verdict": fs.verdict,
                "f1": fs.f1_score, "f2": fs.f2_score, "f3": fs.f3_score,
                "f4": fs.f4_score, "f5": fs.f5_score, "f6": fs.f6_score, "f7": fs.f7_score,
                "piotroski": fs.piotroski_score,
                "bew_ran": bool(fs.overlay_bew_run),
                "ica_ran": bool(fs.overlay_ica_run),
                "psa_ran": bool(fs.overlay_psa_run),
                "overlay_notes": fs.overlay_notes,    # JSON
                "disqualified": bool(fs.disqualified),
                "pt_roic": co.pt_adjusted_roic,
                "roic": co.roic,
                "exclusion": policy.status_of(co),
            })
    # Re-rank by FRESH composite (the warehouse rank that drove top-N selection
    # could differ from the dive's freshly-computed composite — show whichever
    # is more recent in the report).
    results.sort(key=lambda r: (r["composite"] or -1), reverse=True)
    return results


def _format_report(results: list[dict], run_date: date) -> str:
    """Plain-text ranked report. Wide format so all signals fit on a single line."""
    out: list[str] = []
    out.append(f"# Weekly $100M-$2B screener + auto-dive — {run_date.isoformat()}")
    out.append("")
    cap = f"[\${CAP_MIN/1e6:.0f}M, \${CAP_MAX/1e9:.1f}B]"
    out.append(f"Universe filter: policy-eligible, cap {cap}, top-{TOP_N} by composite.")
    out.append(f"All dives ran with --auto-overlays (BEW + ICA + PSA + SIM auto-fire on trigger).")
    out.append(f"No LLM narrative — run `invest scorecard TICKER --narrate` on individual tickers for deep moat analysis.")
    out.append("")
    out.append("## Rank")
    out.append("")
    header = (
        "Rank | Ticker | Comp  | F1  | F2  | F3  | F4  | F5  | F6  | F7  | "
        "Verdict     | BEW | ICA | PSA | Piotr | ROIC   | PT-ROIC | Cap    | Sector"
    )
    out.append(header)
    out.append("-" * len(header))
    for i, r in enumerate(results, start=1):
        def _fmt_pct(x: float | None) -> str:
            return f"{x*100:>6.1f}%" if x is not None else "   --  "
        def _fmt_score(x: float | None) -> str:
            return f"{x:>4.1f}" if x is not None else " -- "
        def _y(v: bool) -> str:
            return " Y " if v else " . "
        cap_b = (r["market_cap_usd"] or 0) / 1e9
        row = (
            f"{i:>4} | {r['ticker']:<6} | {_fmt_score(r['composite'])} | "
            f"{_fmt_score(r['f1'])} | {_fmt_score(r['f2'])} | {_fmt_score(r['f3'])} | "
            f"{_fmt_score(r['f4'])} | {_fmt_score(r['f5'])} | {_fmt_score(r['f6'])} | "
            f"{_fmt_score(r['f7'])} | {(r['verdict'] or '?'):<11} | "
            f"{_y(r['bew_ran'])} | {_y(r['ica_ran'])} | {_y(r['psa_ran'])} | "
            f"{(r['piotroski'] if r['piotroski'] is not None else '--'):>5} | "
            f"{_fmt_pct(r['roic'])} | {_fmt_pct(r['pt_roic'])} | "
            f"\${cap_b:>5.2f}B | {(r['sector'] or '?')[:18]}"
        )
        out.append(row)

    # Overlay-fired highlight section — bring forward tickers where overlays
    # fired (these are the ones with extra signal beyond raw F-scores).
    out.append("")
    out.append("## Overlay-fired highlights")
    out.append("")
    overlayed = [r for r in results if r["bew_ran"] or r["ica_ran"] or r["psa_ran"]]
    if not overlayed:
        out.append("(none — no PSA/ICA/BEW triggers fired this run)")
    else:
        for r in overlayed:
            tag_bits = []
            if r["bew_ran"]: tag_bits.append("BEW")
            if r["ica_ran"]: tag_bits.append("ICA")
            if r["psa_ran"]: tag_bits.append("PSA")
            tags = ",".join(tag_bits)
            notes_summary = ""
            try:
                if r["overlay_notes"]:
                    notes_summary = " — " + json.dumps(json.loads(r["overlay_notes"]))[:200]
            except (json.JSONDecodeError, TypeError):
                pass
            out.append(f"- **{r['ticker']}** [{tags}] composite={r['composite']:.2f} verdict={r['verdict']}{notes_summary}")
    out.append("")
    return "\n".join(out)


def main() -> int:
    started = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_date = date.today()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = OUTPUT_DIR / f"{LOG_PREFIX}_dives_{timestamp}.log"
    report_path = OUTPUT_DIR / f"{LOG_PREFIX}_report_{timestamp}.md"
    dive_log_lines: list[str] = []

    _log("=== Weekly $100M-$2B screener → auto-dive pipeline ===")
    policy = get_policy()
    tickers = _load_top_n(TOP_N, policy)
    _log(f"top-{TOP_N} from warehouse: {len(tickers)} tickers — {tickers}")

    if not tickers:
        _log("nothing to do — warehouse returned 0 tickers. Composite_score may be unpopulated.")
        return 1

    # ── Phase 1: auto-dive each top-N candidate ──────────────────────────
    _log(f"phase 1: dive {len(tickers)} tickers (auto-overlays, no narrative)")
    ok_count = 0
    fail_count = 0
    for i, t in enumerate(tickers, start=1):
        _log(f"  ({i}/{len(tickers)}) dive {t}…")
        try:
            ok, tail = _run_dive(t)
            if ok:
                ok_count += 1
                dive_log_lines.append(f"--- {t} OK ---\n{tail}\n")
            else:
                fail_count += 1
                dive_log_lines.append(f"--- {t} FAILED ---\n{tail}\n")
                _log(f"    FAILED")
        except subprocess.TimeoutExpired:
            fail_count += 1
            dive_log_lines.append(f"--- {t} TIMEOUT (>{DIVE_TIMEOUT_SEC}s) ---\n")
            _log(f"    TIMEOUT")
    log_path.write_text("\n".join(dive_log_lines), encoding="utf-8")
    _log(f"phase 1 done: {ok_count} ok, {fail_count} failed → log: {log_path}")

    # ── Phase 2: aggregate + report ──────────────────────────────────────
    _log("phase 2: assemble report from fresh FrameworkScore rows")
    results = _collect_results(tickers, run_date, policy)
    report = _format_report(results, run_date)
    report_path.write_text(report, encoding="utf-8")
    _log(f"phase 2 done: {len(results)} scorecards collected → report: {report_path}")

    elapsed = time.time() - started
    _log(f"=== complete in {elapsed:.0f}s ({elapsed/60:.1f}min) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
