"""One-shot universe-warehouse fill (Phase 5f).

Runs the full chain that turns an empty DB into a queryable universe of
US-listed Company rows with market caps populated:

  Phase 1 — refresh_universe()
            SEC company_tickers_exchange.json → ~10K Company rows seeded
            with ticker / cik / exchange / name. 1 HTTP, cached 7 days.

  Phase 2 — IPODateTask
            SEC submissions.json per CIK → ipo_date + sector via SIC
            (Layer-3 fallback per Phase 5e gap-3). ~10K @ 10/sec ≈ 17 min.
            ALSO populates Company.fiscal_year_end_month — used by
            FundamentalsTask later.

  Phase 3 — exclusion_classify
            The active exclusion policy classifies each company from sector
            and industry (a no-op under the default `none`). Runs in
            seconds. Companies it excludes are skipped by Phases 4/5
            (MetadataYFTask.select_pending).

  Phase 4 — MetadataYFTask
            yfinance .info per ticker not excluded → market_cap,
            sector (refines from coarse SIC bucket to yfinance string),
            industry, currency, shares_float, beta, P/E, P/B, EV/EBITDA.
            ~5-7K @ 1/sec ≈ 1.5-2 hrs. Failures bump fetched_at (Phase
            5e gap-1) so we don't retry chronically broken tickers.

  Phase 5 — MetadataPolygonTask  (optional — POLYGON_API_KEY required)
            Backfills tickers where yfinance left market_cap NULL via
            Polygon /v3/reference/tickers/{t}. 5/min throttle ⇒ slow,
            but recovers most tickers yfinance permanently lacks.

After this completes, `invest screen --warehouse --cap-min 100M
--cap-max 10B` is a sub-second SQL query forever (until
*_fetched_at columns expire and tasks pick them up again on cron).

Usage:
    uv run python scripts/fill_universe.py                  # full fill
    uv run python scripts/fill_universe.py --max-tickers 100   # smoke
    uv run python scripts/fill_universe.py --skip-yfinance      # SIC + classification only
    uv run python scripts/fill_universe.py --skip-polygon       # no Polygon backfill
    uv run python scripts/fill_universe.py --no-universe-refresh  # use existing rows

Idempotent: re-runs skip already-fresh rows via the FilterTask
*_fetched_at freshness gates. Stop and restart safely — each phase
checkpoints to the DB.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

logger = logging.getLogger("fill_universe")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _humanize_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


def _phase_header(label: str, n: int) -> None:
    print()
    print("=" * 72)
    print(f"  PHASE {n} — {label}")
    print("=" * 72)


async def main() -> int:
    p = argparse.ArgumentParser(description="One-shot universe-warehouse fill")
    p.add_argument(
        "--max-tickers", type=int, default=None,
        help="Cap the number of tickers processed in each phase. "
             "Useful for smoke runs (e.g. --max-tickers 50).",
    )
    p.add_argument(
        "--skip-yfinance", action="store_true",
        help="Skip Phase 4 (yfinance metadata). Useful when you only "
             "want SEC SIC sector classification.",
    )
    p.add_argument(
        "--skip-polygon", action="store_true",
        help="Skip Phase 5 (Polygon backfill of yfinance failures).",
    )
    p.add_argument(
        "--no-universe-refresh", action="store_true",
        help="Skip Phase 1 (universe seed). Use when Company rows already "
             "exist and you just want to refresh metadata.",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    args = p.parse_args()

    _setup_logging(args.verbose)
    started = time.monotonic()

    # ── Phase 1: universe seed ─────────────────────────────────────────────
    if args.no_universe_refresh:
        print("\n[skip] Phase 1 (--no-universe-refresh)")
    else:
        _phase_header("Universe seed (SEC company_tickers_exchange.json)", 1)
        from data.db import get_session
        from screener.tasks.universe import refresh_universe
        with get_session() as db:
            summary = refresh_universe(db)
        print(
            f"  fetched={summary.fetched}  "
            f"inserted={summary.inserted}  "
            f"updated={summary.updated}  "
            f"({_humanize_seconds(summary.duration_seconds)})"
        )

    # ── Phase 2: IPO date + SEC SIC sector ─────────────────────────────────
    _phase_header("IPO date + SEC SIC sector (submissions.json)", 2)
    await _run_named_task(
        "ipo_date",
        max_tickers=args.max_tickers,
        expected_rate_per_min=600,    # 10/sec → 600/min
    )

    # ── Phase 3: exclusion-policy classification ──────────────────────────
    _phase_header("Exclusion-policy classification", 3)
    await _run_named_task(
        "exclusion_classify",
        max_tickers=args.max_tickers,
        expected_rate_per_min=10_000_000,    # in-memory; effectively instant
    )
    _print_exclusion_split()

    # ── Phase 4: yfinance metadata (companies not excluded) ───────────────
    if args.skip_yfinance:
        print("\n[skip] Phase 4 (--skip-yfinance)")
    else:
        _phase_header(
            "yfinance metadata for companies not excluded",
            4,
        )
        await _run_named_task(
            "metadata_yf",
            max_tickers=args.max_tickers,
            expected_rate_per_min=60,    # 1/sec → 60/min
        )

    # ── Phase 5: Polygon backfill ──────────────────────────────────────────
    if args.skip_polygon:
        print("\n[skip] Phase 5 (--skip-polygon)")
    else:
        _phase_header("Polygon ticker-details backfill (failures only)", 5)
        await _run_named_task(
            "metadata_polygon",
            max_tickers=args.max_tickers,
            expected_rate_per_min=5,     # 5/min throttle on free tier
        )

    elapsed = time.monotonic() - started
    print()
    print("=" * 72)
    print(f"  DONE — total wall clock: {_humanize_seconds(elapsed)}")
    print("=" * 72)
    print()
    print("Universe is now queryable. Try:")
    print(
        '  uv run invest screen --warehouse '
        '--cap-min 100M --cap-max 10B --top-n 30'
    )
    return 0


async def _run_named_task(
    name: str,
    *,
    max_tickers: int | None,
    expected_rate_per_min: int,
) -> None:
    """Run a registered FilterTask; cap pending list when --max-tickers set."""
    from data.db import get_session
    from screener.tasks.registry import get_task
    from screener.tasks.runner import run_task

    started = time.monotonic()
    task = get_task(name)

    with get_session() as db:
        pending = task.select_pending(db)
        n_full = len(pending)
        n_actual = min(n_full, max_tickers) if max_tickers else n_full
        eta = _humanize_seconds(60.0 * n_actual / expected_rate_per_min)
        if max_tickers and n_full > max_tickers:
            print(
                f"  pending={n_full}  capped to {max_tickers} "
                f"(--max-tickers); estimated {eta}"
            )
        else:
            print(
                f"  pending={n_full}; estimated {eta} "
                f"@ {expected_rate_per_min}/min"
            )

        if n_actual == 0:
            print("  nothing pending — skipping")
            return

        # When capping, monkey-patch select_pending to return only the first N.
        # Idempotency is preserved because the next run will pick up the rest.
        if max_tickers and n_full > max_tickers:
            limited = pending[:max_tickers]
            task.select_pending = lambda _db: limited        # type: ignore[method-assign]

        result = await run_task(task, db)

    elapsed = time.monotonic() - started
    print(
        f"  status={result.status}  "
        f"processed={result.processed}  "
        f"failed={result.failed}  "
        f"({_humanize_seconds(elapsed)})"
    )
    if result.failed_ciks and len(result.failed_ciks) <= 10:
        print(f"  failed: {', '.join(result.failed_ciks[:10])}")
    elif result.failed_ciks:
        print(
            f"  failed: {', '.join(result.failed_ciks[:10])} "
            f"+{len(result.failed_ciks) - 10} more"
        )


def _print_exclusion_split() -> None:
    """Verdict counts for the configured policy; companies without one are unclassified."""
    from sqlalchemy import func, select

    from data.db import get_session
    from data.models.schema import Company, ExclusionVerdict
    from screener.policies import get_policy

    policy = get_policy().name
    with get_session() as db:
        stats = db.execute(
            select(ExclusionVerdict.status, func.count())
            .where(ExclusionVerdict.policy == policy)
            .group_by(ExclusionVerdict.status)
        ).all()
        total = db.execute(select(func.count()).select_from(Company)).scalar_one()
        counts = {str(status): int(n) for status, n in stats}
        counts["unclassified"] = total - sum(counts.values())
        print(f"\n  Exclusion policy '{policy}' across {total} Company rows:")
        for status, n in sorted(counts.items(), key=lambda x: -x[1]):
            pct = 100.0 * n / total if total else 0.0
            print(f"    {status:<13s}  {n:>6d}  ({pct:5.1f}%)")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
