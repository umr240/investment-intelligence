"""
Staged screener pipeline (docs/architecture/SCREENER_PIPELINE.md §4, DECISIONS.md DEC-14).

Three stages, each independently runnable, checkpointed to `screener_stages`.

  Stage A:  universe + Tier 1 (exchange) + Tier 2 (yfinance metadata)
            + Tier 3 (exclusion policy). Persists Company rows. Heavy yfinance fan-out.

  Stage B:  Tier 4 frames-driven rank-and-narrow. Reads Stage A survivors,
            outputs top-N selected + flagged_by_ticker.

  Stage C:  Tier 5a (companyfacts shortlist refresh) + Tier 5b (7 gates) +
            Tier 6 (composite score + persist). Final ScreenerRun + ScreenerResult.

Each stage:
  - Creates/updates a `screener_stages` row keyed by (run_id, stage).
  - On success: status='completed', writes state_json for the next stage.
  - On failure: status='failed', error filled. Resumable via
    `invest screen run --stage X --run-id Y`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, cast

from data.db import get_session
from data.models.api_models import ScreenerParams
from data.models.schema import ScreenerRun, ScreenerStage
from data.universe.base import UniverseTicker

logger = logging.getLogger(__name__)


# ── Stage state types (JSON-serialised on ScreenerStage.state_json) ──────


@dataclass
class StageAState:
    """Output of Stage A — Tier 3 survivors."""
    tier3_survivors: list[dict]            # list[_EnrichedTicker as dict]
    exclusion_count: int
    gate_funnel: dict[str, int]
    # [{"ticker", "reason"}] — every Tier 3 exclusion is reported with its reason.
    exclusions: list[dict[str, str]] = field(default_factory=list)


@dataclass
class StageBState:
    """Output of Stage B — Tier 4 top-N selected."""
    selected_tickers: list[str]
    deferred_tickers: list[str]
    hard_failed_tickers: list[str]
    flagged_by_ticker: dict[str, list[str]]
    gate_funnel: dict[str, int]


# ── Public entrypoints (one per stage) ───────────────────────────────────


class StageFailureGate(RuntimeError):
    """Raised when a stage retained too few survivors to be useful.

    Phase 5c-5: previously stages would silently complete with 0 or
    near-0 survivors when an upstream API failed (yfinance ban, FMP 402,
    SEC frames missing). Cron handlers logged 'completed' even though the
    pipeline produced nothing. The gate makes that an explicit failure
    so the cron handler emits an alert and the next stage doesn't run on
    bogus state.
    """


def _enforce_survivor_gate(
    stage: str, input_count: int, output_count: int,
) -> None:
    """Fail the stage if survivor ratio is below the threshold."""
    from config.constants import (
        STAGE_MIN_ABSOLUTE_SURVIVORS,
        STAGE_MIN_SURVIVOR_RATIO,
    )
    if input_count == 0:
        # Nothing to evaluate — upstream stage failed to produce input.
        # Don't double-fail; just propagate.
        return
    ratio = output_count / input_count
    if (
        output_count < STAGE_MIN_ABSOLUTE_SURVIVORS
        or ratio < STAGE_MIN_SURVIVOR_RATIO
    ):
        raise StageFailureGate(
            f"Stage {stage} retained {output_count}/{input_count} "
            f"survivors ({ratio:.0%}) — below threshold "
            f"({STAGE_MIN_SURVIVOR_RATIO:.0%} or {STAGE_MIN_ABSOLUTE_SURVIVORS} abs). "
            f"Likely upstream API failure (yfinance anti-abuse / FMP 402 / "
            f"SEC frames missing). Aborting before next stage runs on bad state."
        )


def _test_universe(
    test_tickers: list[str], region_universe: list[UniverseTicker],
) -> list[UniverseTicker]:
    """Resolve test tickers against the region list; Stage B's frames join on CIK."""
    known = {u.ticker: u for u in region_universe}
    return [
        known.get(t.upper()) or UniverseTicker(
            ticker=t.upper(), name=t.upper(), exchange="", cik=None, source="test_list",
        )
        for t in test_tickers
    ]


async def run_stage_a(
    run_id: int,
    params: ScreenerParams,
    retention_days: int,
    ipo_after: date | None = None,
    ipo_before: date | None = None,
    test_tickers: list[str] | None = None,
) -> StageAState:
    """
    Stage A: universe → exchange → cap/sector → exclusion policy. Heavy yfinance.
    Persists Company rows. Returns survivors for Stage B.

    If `test_tickers` is provided, BYPASSES Tier 0 (SEC universe) and uses
    that list directly as the input. Useful for iterative live-testing without
    burning ~10000 yfinance calls.
    """
    stage_row = _begin_stage(run_id, "A")
    try:
        from config.settings import settings
        from data.universe import get_provider
        from screener.pipeline import (
            _apply_cap_sector,
            _apply_exclusion_policy,
            _fetch_metadata_bulk,
            _fetch_metadata_fmp,
            _persist_exclusions,
            _persist_screener_candidates,
        )
        from screener.policies import get_policy

        funnel: dict[str, int] = {}

        # Tier 0 — region universe OR explicit test list
        if test_tickers:
            universe = _test_universe(
                test_tickers, get_provider((params.region or "us").lower()).fetch(),
            )
        else:
            region = (params.region or "us").lower()
            provider = get_provider(region)
            universe = provider.fetch()
        funnel["T0_universe"] = len(universe)

        # Tier 1 — exchange (no-op if test_tickers since exchange is empty)
        if params.exchange and not test_tickers:
            wanted = {e.strip() for e in params.exchange.split(",")}
            universe = [u for u in universe if u.exchange in wanted]
        funnel["T1_exchange"] = len(universe)

        # Tier 2 (cap + sector + optional IPO date window)
        #
        # Phase 5c: FMP `/stable/company-screener` was the original fast path
        # (ADR-016) but returns HTTP 402 on free tier as of 2026-05-08. We
        # now go yfinance-primary with Polygon as a post-hoc backfill via
        # MetadataPolygonTask (NOT in this hot path — runs separately).
        #
        # Source priority for Stage A metadata enrichment:
        #   1. yfinance .info per-ticker (concurrency=1; reliable but slow)
        #   2. (legacy) FMP bulk screener — only if explicitly enabled AND
        #      a paid plan unlocks /stable/company-screener.
        #
        # Default behaviour: yfinance only. To opt into the legacy FMP path,
        # set INVEST_USE_FMP_SCREENER=1 in env (off by default).
        import os as _os
        use_fmp = (
            _os.environ.get("INVEST_USE_FMP_SCREENER") == "1"
            and settings.fmp_api_key and not test_tickers
        )
        if use_fmp:
            try:
                enriched = await _fetch_metadata_fmp(
                    universe,
                    cap_min=params.cap_min,
                    cap_max=params.cap_max,
                    sector=params.sector,
                    exchange=params.exchange,
                )
            except RuntimeError as exc:
                # FMP 402 / paid-tier escalation — fall through to yfinance
                logger.warning(
                    "FMP screener failed (%s); falling back to yfinance "
                    "per-ticker enrichment", exc,
                )
                enriched = await _fetch_metadata_bulk(universe)
        else:
            enriched = await _fetch_metadata_bulk(universe)
        survivors = _apply_cap_sector(
            enriched, params,
            ipo_after=ipo_after, ipo_before=ipo_before,
        )
        funnel["T2_cap_sector"] = len(survivors)

        # Tier 3, under the policy recorded on the run so a re-run of Stage A
        # and Stage C's gate G1 always agree.
        policy = get_policy(_run_policy(run_id, params.exclusion_policy))
        survivors, exclusions = _apply_exclusion_policy(survivors, policy)
        funnel["T3_exclusion"] = len(survivors)

        # Persist
        _persist_screener_candidates(survivors, retention_days=retention_days, policy=policy)
        _persist_exclusions(exclusions, policy)

        state = StageAState(
            tier3_survivors=[_enriched_to_dict(s) for s in survivors],
            exclusion_count=len(exclusions),
            gate_funnel=funnel,
            exclusions=[{"ticker": e.ticker, "reason": reason} for e, reason in exclusions],
        )
        _enforce_survivor_gate(
            "A",
            input_count=funnel.get("T0_universe", 0),
            output_count=len(survivors),
        )
        _complete_stage(stage_row.id, output_count=len(survivors),
                        state=_dataclass_to_json(state))
        return state
    except Exception as exc:
        _fail_stage(stage_row.id, str(exc))
        raise


async def run_stage_b(run_id: int) -> StageBState:
    """
    Stage B: SEC frames Tier 4 rank-and-narrow.
    Reads Stage A's state, outputs top-N + flagged_by_ticker.
    """
    stage_row = _begin_stage(run_id, "B")
    try:
        prev = _load_state(run_id, "A")
        if not prev or "tier3_survivors" not in prev:
            raise RuntimeError("Stage A state missing — cannot run Stage B")

        from config.constants import MAX_SEC_CONCURRENCY
        from data.edgar_frames import build_frames_universe_async
        from screener.tier4_frames import (
            build_tier4_snapshots,
            evaluate_tier4,
            rank_and_truncate,
            screener_concepts_periods,
        )

        # Re-hydrate _EnrichedTicker-like objects (we only need `.ticker` and `.cik`)
        survivors = [_dict_to_enriched(d) for d in prev["tier3_survivors"]]

        concepts_periods = screener_concepts_periods()
        frames = await build_frames_universe_async(
            concepts_periods, max_concurrency=MAX_SEC_CONCURRENCY,
        )
        snapshots = build_tier4_snapshots(frames)

        results = evaluate_tier4(survivors, snapshots)
        top_n = _resolve_top_n(run_id)
        selected, deferred, hard_failed = rank_and_truncate(results, top_n)

        funnel = dict(prev.get("gate_funnel", {}))
        funnel["T4_frames_selected"] = len(selected)
        funnel["T4_frames_deferred"] = len(deferred)
        funnel["T4_frames_hard_failed"] = len(hard_failed)

        state = StageBState(
            selected_tickers=[r.ticker for r in selected],
            deferred_tickers=[r.ticker for r in deferred],
            hard_failed_tickers=[r.ticker for r in hard_failed],
            flagged_by_ticker={r.ticker: r.flags for r in selected if r.flags},
            gate_funnel=funnel,
        )
        # Stage B's input is the Tier-3 survivors from Stage A.
        # selected + deferred together is "useful output" — both are
        # still candidates; only hard_failed is unrecoverable.
        useful_output = len(selected) + len(deferred)
        # Stage A states written before the policy hook used a policy-specific T3 key.
        fallback = len(selected) + len(hard_failed) + len(deferred)
        t3 = next((v for k, v in funnel.items() if k.startswith("T3_")), None)
        input_count = fallback if t3 is None else int(t3)
        _enforce_survivor_gate(
            "B", input_count=input_count, output_count=useful_output,
        )
        _complete_stage(stage_row.id, output_count=len(selected),
                        state=_dataclass_to_json(state))
        return state
    except Exception as exc:
        _fail_stage(stage_row.id, str(exc))
        raise


async def run_stage_c(run_id: int, mode: str) -> dict[str, Any]:
    """
    Stage C: companyfacts shortlist + 7 gates + composite + persist.
    Reads Stage B's state, writes final ScreenerResult rows.
    """
    stage_row = _begin_stage(run_id, "C")
    try:
        prev = _load_state(run_id, "B")
        if not prev or "selected_tickers" not in prev:
            raise RuntimeError("Stage B state missing — cannot run Stage C")

        from screener.persistence import persist_screener_run
        from screener.pipeline import (
            _EnrichedTicker,
            _refresh_shortlist,
            _run_gates_and_score,
        )
        from screener.policies import get_policy

        # Resolved before the long refresh/prefetch: a run recorded under a policy
        # that is no longer installed fails here rather than gating under another.
        params = _load_run_params(run_id)
        policy = get_policy(params.exclusion_policy)

        tickers = list(prev["selected_tickers"])
        flagged_by_ticker = dict(prev.get("flagged_by_ticker", {}))
        funnel = dict(prev.get("gate_funnel", {}))

        # Re-hydrate minimal _EnrichedTicker for _refresh_shortlist
        survivors = [
            _EnrichedTicker(
                ticker=t, name=t, cik=None, exchange="",
                market_cap=None, sector=None, industry=None,
                country=None, currency=None, analyst_count=None,
            )
            for t in tickers
        ]

        # Tier 5a: refresh fundamentals (companyfacts) for the shortlist
        refresh_errors = await _refresh_shortlist(survivors)
        funnel["T5a_refresh_errors"] = len(refresh_errors)

        # Tier 5a.5: Polygon prefetch (Phase 5c-4) — run on shortlist only.
        # Closes the data-completeness gap that produced F2=0 / F4=0 for
        # tickers with no price-history or short-interest rows. 5/min throttle
        # × ~6 calls per ticker × N shortlist = bounded; e.g. 30 tickers = ~36 min.
        # Skipped automatically when POLYGON_API_KEY unset.
        polygon_results = await _prefetch_polygon_for_shortlist(tickers)
        funnel["T5a_polygon_prefetched"] = polygon_results["prefetched"]
        funnel["T5a_polygon_errors"] = polygon_results["errors"]

        # Tier 5b/6: gates + score + rank
        scored = _run_gates_and_score(tickers, flagged_by_ticker, mode, policy)
        scored.sort(key=lambda s: s.total_score, reverse=True)
        clean = [s for s in scored if s.clean]
        flagged = [s for s in scored if not s.clean]
        funnel["T6_clean"] = len(clean)
        funnel["T6_flagged"] = len(flagged)

        # UPDATE the existing run (created at start of staged execution)
        persist_screener_run(
            params=params, mode=mode,
            universe_count=funnel.get("T0_universe", 0),
            gate_funnel=funnel,
            scored_tickers=scored,
            run_id=run_id,
        )

        result_summary = {
            "scored_count": len(scored),
            "clean_count": len(clean),
            "flagged_count": len(flagged),
            "gate_funnel": funnel,
        }
        # Stage C's input is the Stage B selected list. Useful output is
        # scored — clean + flagged both count (flagged still got a verdict;
        # only hard-fail-on-fetch tickers are missing).
        _enforce_survivor_gate(
            "C", input_count=len(tickers), output_count=len(scored),
        )
        _complete_stage(stage_row.id, output_count=len(scored),
                        state=json.dumps(result_summary))
        return result_summary
    except Exception as exc:
        _fail_stage(stage_row.id, str(exc))
        raise


# ── Internal helpers ─────────────────────────────────────────────────────


async def _prefetch_polygon_for_shortlist(
    tickers: list[str],
) -> dict[str, int]:
    """Phase 5c-4: prime PriceHistory + ShortInterestRecord with Polygon data
    for the Stage C shortlist before framework scoring runs.

    Closes the data-completeness gap that produced F2=0 / F4=0 in run #4 —
    those tickers had no price history or short interest rows because
    Stage A's yfinance .info doesn't fetch .history(). Polygon's weekly
    aggs + short-interest endpoints fill the gap reliably (paid-grade
    end-of-day data, predictable 429 backoff).

    Returns {'prefetched': N_success, 'errors': N_failed}. Skipped
    entirely when POLYGON_API_KEY is unset (every Polygon task short-circuits).

    NOTE on quota math: 5 calls/min sustained means a 30-ticker shortlist
    × 2 tasks (weekly + short_interest) = 60 calls = ~12 min wall-clock.
    The 4 indicator tasks (current_price, RSI, SMA×2, MACD) are skipped
    here — they're per-ticker rollups for the watchlist, not screener
    inputs. F2/F4 only need the time series.
    """
    from data.api.polygon_client import PolygonClient
    from data.db import get_session
    from data.models.schema import Company
    from screener.tasks.polygon import (
        PolygonShortInterestTask,
        PolygonWeeklyPriceTask,
    )
    from screener.tasks.runner import run_task

    if not PolygonClient().has_key:
        logger.info(
            "_prefetch_polygon: POLYGON_API_KEY unset — skipping. "
            "F2/F4 may score 0 for tickers without legacy yfinance data.",
        )
        return {"prefetched": 0, "errors": 0}

    if not tickers:
        return {"prefetched": 0, "errors": 0}

    # Force a refresh regardless of freshness: clear the weekly-bars stamp on
    # the shortlist so PolygonWeeklyPriceTask picks every row up.
    with get_session() as session:
        rows = (
            session.query(Company)
            .filter(Company.ticker.in_(tickers))
            .all()
        )
        for c in rows:
            c.weekly_prices_fetched_at = None
        session.commit()

    prefetched = 0
    errors = 0
    for cls in (PolygonWeeklyPriceTask, PolygonShortInterestTask):
        try:
            with get_session() as session:
                # Scoped to the shortlist: run_task selects again, so a
                # filtered copy of select_pending would be ignored.
                task = cls(tickers=tickers)
                result = await run_task(task, session)
                prefetched += result.processed
                errors += result.failed
                logger.info(
                    "_prefetch_polygon: %s processed=%d failed=%d duration=%.1fs",
                    cls.__name__, result.processed, result.failed,
                    result.duration_seconds,
                )
        except Exception as exc:    # noqa: BLE001
            logger.warning(
                "_prefetch_polygon: %s failed (%s) — continuing",
                cls.__name__, exc,
            )
            errors += 1

    return {"prefetched": prefetched, "errors": errors}


def _begin_stage(run_id: int, stage: str) -> ScreenerStage:
    """Create or reset a screener_stages row for (run_id, stage). Returns the row."""
    with get_session() as session:
        existing = (
            session.query(ScreenerStage)
            .filter_by(screener_run_id=run_id, stage=stage)
            .first()
        )
        if existing is not None:
            existing.status = "running"
            existing.started_at = datetime.now()
            existing.completed_at = None
            existing.error = None
            session.flush()
            session.refresh(existing)
            session.expunge(existing)
            return existing
        row = ScreenerStage(
            screener_run_id=run_id,
            stage=stage,
            status="running",
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def _complete_stage(stage_id: int, output_count: int, state: str) -> None:
    with get_session() as session:
        row = session.query(ScreenerStage).filter_by(id=stage_id).first()
        if not row:
            return
        row.status = "completed"
        row.completed_at = datetime.now()
        row.output_count = output_count
        row.state_json = state


def _fail_stage(stage_id: int, error: str) -> None:
    with get_session() as session:
        row = session.query(ScreenerStage).filter_by(id=stage_id).first()
        if not row:
            return
        row.status = "failed"
        row.completed_at = datetime.now()
        row.error = error[:5000]


def _load_state(run_id: int, stage: str) -> dict | None:
    """Load a completed stage's state_json. None if not present or not completed."""
    with get_session() as session:
        row = (
            session.query(ScreenerStage)
            .filter_by(screener_run_id=run_id, stage=stage, status="completed")
            .first()
        )
        if row is None or not row.state_json:
            return None
        try:
            return json.loads(row.state_json)
        except (TypeError, ValueError) as exc:
            logger.warning("stage %s state_json parse failed: %s", stage, exc)
            return None


def _load_run_params(run_id: int) -> ScreenerParams:
    with get_session() as session:
        row = session.query(ScreenerRun).filter_by(id=run_id).first()
        if row is None:
            raise RuntimeError(f"ScreenerRun id={run_id} not found")
        return ScreenerParams(
            region=row.region or "us",
            cap_min=row.market_cap_min or 0.0,
            cap_max=row.market_cap_max or 1e12,
            sector=row.sector_filter,
            exclusion_policy=cast("str | None", row.ethics_filter),
        )


def _run_policy(run_id: int, requested: str | None) -> str | None:
    """The policy recorded on the run; an explicit request for another one is an error."""
    from screener.policies import get_policy

    recorded = _load_run_params(run_id).exclusion_policy
    # Compare resolved names: an entry-point name may differ from the policy's own.
    if requested is not None and recorded is not None and get_policy(requested).name != recorded:
        raise ValueError(
            f"run {run_id} was created under exclusion policy {recorded!r}, not {requested!r}; "
            "start a new run to screen under another policy"
        )
    return recorded if recorded is not None else requested


def _policy_name(params: ScreenerParams) -> str:
    """The resolved policy name recorded on the run (column kept as `ethics_filter`)."""
    from screener.policies import get_policy

    return get_policy(params.exclusion_policy).name


def _resolve_top_n(run_id: int) -> int:
    """
    Default top-N for Stage B is 300. Future: read from a per-run override
    column if we want different behaviour per scheduled job.
    """
    return 300


def _enriched_to_dict(e: Any) -> dict:
    """Serialise _EnrichedTicker for JSON state."""
    return {
        "ticker": e.ticker,
        "name": e.name,
        "cik": e.cik,
        "exchange": e.exchange,
        "market_cap": e.market_cap,
        "sector": e.sector,
        "industry": e.industry,
        "country": e.country,
        "currency": e.currency,
        "analyst_count": e.analyst_count,
    }


def _dict_to_enriched(d: dict) -> Any:
    """Re-hydrate _EnrichedTicker from JSON state."""
    from screener.pipeline import _EnrichedTicker
    return _EnrichedTicker(
        ticker=d.get("ticker", ""),
        name=d.get("name", ""),
        cik=d.get("cik"),
        exchange=d.get("exchange", ""),
        market_cap=d.get("market_cap"),
        sector=d.get("sector"),
        industry=d.get("industry"),
        country=d.get("country"),
        currency=d.get("currency"),
        analyst_count=d.get("analyst_count"),
    )


def _dataclass_to_json(obj: Any) -> str:
    """Serialise a dataclass instance to JSON via its __dict__."""
    return json.dumps(obj.__dict__, default=str)


# ── Run-row creation (called once at the start of a fresh screen) ────────


def create_screener_run(
    params: ScreenerParams,
    mode: str,
) -> int:
    """
    Insert a new ScreenerRun row at the START of a staged screen so all 3
    stages can write screener_stages rows under the same run_id.

    The run row's `passed_gates` and `results_json` get filled in by Stage C
    via persist_screener_run (which UPSERTs by run_id... actually it INSERTs
    a NEW run, hmm).

    To avoid the duplicate-insert problem: Stage C's persist_screener_run
    needs to be modified to UPDATE an existing run rather than INSERT.
    For now, document the contract: legacy single-shot path inserts the run;
    staged path must NOT call create_screener_run (Stage C creates it).
    """
    with get_session() as session:
        run = ScreenerRun(
            run_date=datetime.now(),
            region=params.region,
            market_cap_min=params.cap_min,
            market_cap_max=params.cap_max,
            sector_filter=params.sector,
            ethics_filter=_policy_name(params),
            mode=mode,
            universe_count=0,        # filled by stages
            passed_gates=0,
        )
        session.add(run)
        session.flush()
        return run.id
