"""
Screener pipeline — Phase 3a wires Tier 0–2 (universe + cap/sector).
Tier 3+ (exclusion policy, frames, gates, ranking) land in Phase 3b–3d.

Tier 0 — universe enumeration (SecUsUniverseProvider, weekly cache)
Tier 1 — exchange / listing-type filter (in-memory)
Tier 2 — yfinance metadata-lite (cap, sector, country, analyst count)
Tier 3 — exclusion-policy sector rule (screener/policies) — Phase 3b
Tier 4 — SEC frames-driven fundamentals filter — Phase 3c
Tier 5 — per-ticker companyfacts + 7 hard gates — Phase 3d
Tier 6 — composite rank, momentum decile, persist top-N — Phase 3d
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from config.constants import MAX_YF_CONCURRENCY, RETENTION_DAYS_DEFAULT
from sqlalchemy.orm import Session, selectinload

from data.db import get_session
from data.models.api_models import ScreenerParams
from data.models.schema import Company

if TYPE_CHECKING:
    from screener.policies.base import ExclusionPolicy

logger = logging.getLogger(__name__)


# ── Output types ─────────────────────────────────────────────────────────


@dataclass
class ScoredTicker:
    ticker: str
    company_name: str
    total_score: float
    clean: bool                                  # True = all 7 gates passed
    verdict: str                                 # 'deep_dive' | 'watch' | 'bench'
    gate_failures: list[str] = field(default_factory=list)
    f_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class ScreenerOutput:
    mode: str
    params: ScreenerParams
    universe_count: int = 0
    gate_funnel: dict[str, int] = field(default_factory=dict)
    ranked_tickers: list[ScoredTicker] = field(default_factory=list)
    clean_tier: list[ScoredTicker] = field(default_factory=list)
    flagged_tier: list[ScoredTicker] = field(default_factory=list)
    pattern_observation: str = ""
    overlay_triggers_detected: list = field(default_factory=list)


# ── Public entry point ───────────────────────────────────────────────────


async def run_screener(
    params: ScreenerParams,
    mode: str,
    retention_days: int = RETENTION_DAYS_DEFAULT,
    top_n_after_frames: int = 300,
) -> ScreenerOutput:
    """
    Phase 3a-3c wired Tier 0–4 (soft). Phase 3d wires Tier 5–6.

    `top_n_after_frames` (default 300) caps the post-Tier-4 shortlist that
    proceeds to Tier 5. Tier 4 is a RANK-and-narrow layer, not a hard stop —
    deferred tickers re-enter the funnel on the next run. See DECISIONS.md DEC-15.

    Persists `Company` rows for Tier-2 survivors with `status='screener_candidate'`
    and `retention_days=N` so the cleanup job can age them out
    per docs/architecture/SCREENER_PIPELINE.md §2.
    """
    output = ScreenerOutput(mode=mode, params=params)

    # ── Tier 0: enumerate region universe ─────────────────────────────────
    from data.universe import get_provider
    region_code = params.region.lower() if params.region else "us"
    provider = get_provider(region_code)
    universe = provider.fetch()
    output.universe_count = len(universe)
    output.gate_funnel["T0_universe"] = len(universe)
    logger.info("Tier 0: %d tickers in region '%s' universe", len(universe), region_code)

    if not universe:
        return output

    # ── Tier 1: exchange / listing-type filter (in-memory) ────────────────
    if params.exchange:
        wanted = {e.strip() for e in params.exchange.split(",")}
        universe = [u for u in universe if u.exchange in wanted]
    output.gate_funnel["T1_exchange"] = len(universe)
    logger.info("Tier 1 (exchange): %d remaining", len(universe))

    # ── Tier 2: yfinance metadata-lite (cap + sector) ─────────────────────
    enriched = await _fetch_metadata_bulk(universe)
    survivors = _apply_cap_sector(enriched, params)
    output.gate_funnel["T2_cap_sector"] = len(survivors)
    logger.info("Tier 2 (cap+sector): %d remaining", len(survivors))

    # ── Tier 3: exclusion-policy sector rule ─────────────────────────────
    from screener.policies import get_policy

    policy = get_policy(params.exclusion_policy)
    survivors, exclusions = _apply_exclusion_policy(survivors, policy)
    output.gate_funnel["T3_exclusion"] = len(survivors)
    logger.info(
        "Tier 3 (%s policy): %d remaining, %d excluded",
        policy.name, len(survivors), len(exclusions),
    )

    # Survivors persist as screener_candidates; exclusions as archived rows.
    _persist_screener_candidates(survivors, retention_days=retention_days, policy=policy)
    _persist_exclusions(exclusions, policy)

    if not survivors:
        return output

    # ── Tier 4: SEC frames rank-and-narrow (soft, see DECISIONS.md DEC-15) ──
    from data.edgar_frames import build_frames_universe_async
    from screener.tier4_frames import (
        build_tier4_snapshots, evaluate_tier4, rank_and_truncate,
        screener_concepts_periods,
    )
    from config.constants import MAX_SEC_CONCURRENCY

    concepts_periods = screener_concepts_periods()
    logger.info(
        "Tier 4: fetching %d SEC frames calls (concurrency=%d)",
        len(concepts_periods), MAX_SEC_CONCURRENCY,
    )
    frames = await build_frames_universe_async(
        concepts_periods, max_concurrency=MAX_SEC_CONCURRENCY,
    )
    snapshots = build_tier4_snapshots(frames)
    logger.info("Tier 4: %d CIKs in frames data; ranking candidates", len(snapshots))

    t4_results = evaluate_tier4(survivors, snapshots)
    selected, deferred, hard_failed = rank_and_truncate(t4_results, top_n_after_frames)
    output.gate_funnel["T4_frames_selected"] = len(selected)
    output.gate_funnel["T4_frames_deferred"] = len(deferred)
    output.gate_funnel["T4_frames_hard_failed"] = len(hard_failed)
    logger.info(
        "Tier 4: %d selected (top %d), %d deferred, %d hard-failed",
        len(selected), top_n_after_frames, len(deferred), len(hard_failed),
    )

    # Map back to enriched tickers; carry flags forward via a parallel dict
    selected_tickers = {r.ticker for r in selected}
    flagged_by_ticker = {r.ticker: r.flags for r in selected if r.flags}
    survivors = [s for s in survivors if s.ticker in selected_tickers]

    if not survivors:
        return output

    # ── Tier 5a: per-ticker companyfacts + price + analyst for shortlist ──
    refresh_errors = await _refresh_shortlist(survivors)
    output.gate_funnel["T5a_refresh_errors"] = len(refresh_errors)
    logger.info(
        "Tier 5a: refreshed shortlist of %d, %d errors",
        len(survivors), len(refresh_errors),
    )

    # ── Tier 5b/6: gates + composite scoring + ranking + persistence ──────
    scored = _run_gates_and_score(
        [s.ticker for s in survivors],
        flagged_by_ticker=flagged_by_ticker,
        mode=mode,
        policy=policy,
    )
    scored.sort(key=lambda s: s.total_score, reverse=True)

    clean_tier = [s for s in scored if s.clean]
    flagged_tier = [s for s in scored if not s.clean]
    output.gate_funnel["T6_clean"] = len(clean_tier)
    output.gate_funnel["T6_flagged"] = len(flagged_tier)
    output.ranked_tickers = scored
    output.clean_tier = clean_tier
    output.flagged_tier = flagged_tier
    logger.info(
        "Tier 6: %d ranked total — %d clean, %d flagged",
        len(scored), len(clean_tier), len(flagged_tier),
    )

    # Persist run + results (single transaction)
    from screener.persistence import persist_screener_run
    run_id = persist_screener_run(
        params=params, mode=mode,
        universe_count=output.universe_count,
        gate_funnel=output.gate_funnel,
        scored_tickers=scored,
    )
    logger.info("screener_run id=%d persisted", run_id)

    return output


def _run_gates_and_score(
    tickers: list[str],
    flagged_by_ticker: dict[str, list[str]],
    mode: str,
    policy: ExclusionPolicy | None = None,
) -> list[ScoredTicker]:
    """
    Tier 5b/6 (sync — runs against fully-refreshed local data, no network):
      - Compute universe-wide asset_growth + momentum deciles across the shortlist.
      - For each ticker: apply 7 gates, compute proxies, compute composite,
        derive verdict, build ScoredTicker.
    """
    from screener.gates import (
        apply_all_gates, hard_failures, is_clean, soft_failures,
    )
    from screener.proxy_scorer import composite, compute_all_proxies
    from screener.ranking import (
        compute_asset_growth_deciles, compute_asset_growth_yoy,
        compute_momentum_deciles, compute_twelve_month_return,
    )

    # Build universe-wide ranking inputs
    asset_growth_yoy: dict[str, float | None] = {
        t: compute_asset_growth_yoy(t) for t in tickers
    }
    twelve_month_returns: dict[str, float | None] = {
        t: compute_twelve_month_return(t) for t in tickers
    }
    asset_growth_deciles = compute_asset_growth_deciles(asset_growth_yoy)
    momentum_deciles = compute_momentum_deciles(twelve_month_returns)

    out: list[ScoredTicker] = []
    for ticker in tickers:
        ag_decile = asset_growth_deciles.get(ticker)
        mom_decile = momentum_deciles.get(ticker)

        gates = apply_all_gates(ticker, ag_decile, mom_decile, policy)
        proxies = compute_all_proxies(ticker, ag_decile, mom_decile)
        comp_score, _conf = composite(proxies, mode)

        clean = is_clean(gates)
        all_failures = hard_failures(gates) + soft_failures(gates)
        all_failures.extend(flagged_by_ticker.get(ticker, []))

        # Screener tiers (deep_dive / watch / bench) at the composite thresholds in constants.py
        if comp_score >= 7.0 and clean:
            verdict = "deep_dive"
        elif comp_score >= 5.0:
            verdict = "watch"
        else:
            verdict = "bench"

        # Look up company name (one DB hit per ticker — small n, acceptable)
        from data.db import get_session
        with get_session() as session:
            company = session.query(Company).filter_by(ticker=ticker).first()
            company_name = company.name if company else ticker

        out.append(ScoredTicker(
            ticker=ticker,
            company_name=company_name,
            total_score=comp_score,
            clean=clean,
            verdict=verdict,
            gate_failures=all_failures,
            f_scores={fw: ps.raw for fw, ps in proxies.items()},
        ))

    return out


# ── Tier 2 helpers ───────────────────────────────────────────────────────


@dataclass
class _EnrichedTicker:
    """Universe ticker + yfinance-lite metadata. Internal only."""
    ticker: str
    name: str
    cik: str | None
    exchange: str
    market_cap: float | None
    sector: str | None
    industry: str | None
    country: str | None
    currency: str | None
    analyst_count: int | None
    first_trade_date: "date | None" = None      # IPO proxy
    error: str | None = None


async def _fetch_metadata_bulk(universe: list) -> list[_EnrichedTicker]:
    """
    DEPRECATED: yfinance per-ticker metadata enrichment.

    Yahoo's anti-abuse layer rate-limits us at universe scale (proven
    empirically 2026-05-04: 1 survivor / 10,104 universe). Replaced by
    `_fetch_metadata_fmp` per ADR-016. Kept for reference / fallback only.
    """
    from data.api.yfinance_client import fetch_yfinance_metadata_only

    sem = asyncio.Semaphore(MAX_YF_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def _one(u) -> _EnrichedTicker:
        async with sem:
            try:
                meta = await loop.run_in_executor(
                    None, fetch_yfinance_metadata_only, u.ticker
                )
            except Exception as exc:    # noqa: BLE001
                return _EnrichedTicker(
                    ticker=u.ticker, name=u.name, cik=u.cik, exchange=u.exchange,
                    market_cap=None, sector=None, industry=None,
                    country=None, currency=None, analyst_count=None,
                    error=f"yfinance metadata error: {exc}",
                )
            return _EnrichedTicker(
                ticker=u.ticker,
                name=meta.name or u.name,
                cik=u.cik,
                exchange=meta.exchange or u.exchange,
                market_cap=meta.market_cap,
                sector=meta.sector,
                industry=meta.industry,
                country=meta.country,
                currency=meta.currency,
                analyst_count=meta.analyst_count,
                first_trade_date=meta.first_trade_date,
                error=meta.error,
            )

    return await asyncio.gather(*[_one(u) for u in universe])


async def _fetch_metadata_fmp(
    universe: list,
    cap_min: float | None = None,
    cap_max: float | None = None,
    sector: str | None = None,
    exchange: str | None = None,
) -> list[_EnrichedTicker]:
    """
    ONE bulk call to FMP `/v3/stock-screener` (per ADR-016).

    Returns the FMP screener result joined to the SEC universe by ticker:
      - Tickers in BOTH FMP and SEC universe → enriched _EnrichedTicker
      - Tickers in SEC universe but not in FMP screener result → dropped
        (means they didn't match the cap/exchange filter on FMP's side)
      - Tickers in FMP but not in SEC universe → dropped (we trust SEC for
        the canonical CIK list; non-SEC filers can't be screened later anyway)

    Server-side filters: FMP applies cap_min/cap_max/sector/exchange before
    returning. Client-side filter would still drop on cap_min if the
    server-side filter is unreliable.
    """
    from data.api.fmp_client import FMPClient
    from config.settings import settings

    if not settings.fmp_api_key:
        # No key — caller should fall back to yfinance path or fail.
        return [
            _EnrichedTicker(
                ticker=u.ticker, name=u.name, cik=u.cik, exchange=u.exchange,
                market_cap=None, sector=None, industry=None,
                country=None, currency=None, analyst_count=None,
                error="FMP_API_KEY not set; cannot enrich at universe scale",
            )
            for u in universe
        ]

    client = FMPClient(api_key=settings.fmp_api_key)
    loop = asyncio.get_event_loop()

    fmp_rows = await loop.run_in_executor(
        None,
        lambda: client.fetch_screener_universe(
            cap_min=cap_min,
            cap_max=cap_max,
            sector=sector,
            exchange=exchange,
            country="US",
            is_actively_trading=True,
        ),
    )
    logger.info(
        "FMP screener: %d FMP rows × %d SEC universe; intersecting on ticker",
        len(fmp_rows), len(universe),
    )

    fmp_by_ticker = {r.ticker: r for r in fmp_rows}
    universe_by_ticker = {u.ticker: u for u in universe}

    out: list[_EnrichedTicker] = []
    for ticker, fmp_row in fmp_by_ticker.items():
        u = universe_by_ticker.get(ticker)
        if u is None:
            continue    # FMP ticker not in SEC universe (foreign listing, etc.)
        out.append(_EnrichedTicker(
            ticker=ticker,
            name=fmp_row.name or u.name,
            cik=u.cik,
            exchange=fmp_row.exchange or u.exchange,
            market_cap=fmp_row.market_cap,
            sector=fmp_row.sector,
            industry=fmp_row.industry,
            country=fmp_row.country,
            currency=None,    # FMP screener doesn't return currency; default USD downstream
            analyst_count=None,    # not in FMP screener; deferred to dive-time yfinance
            first_trade_date=None,    # IPO date deferred (will be SEC submissions task per ADR-017)
            error=None,
        ))
    return out


def _apply_cap_sector(
    enriched: list[_EnrichedTicker],
    params: ScreenerParams,
    ipo_after: "date | None" = None,
    ipo_before: "date | None" = None,
) -> list[_EnrichedTicker]:
    """
    In-memory filter on cap_min/cap_max + optional --sector + optional IPO window.
    Drops error rows.

    `ipo_after` / `ipo_before` filter by yfinance `first_trade_date` (IPO proxy).
    Tickers without a first_trade_date are KEPT (defensive — yfinance gap
    shouldn't drop the whole ticker).
    """
    cap_min = params.cap_min
    cap_max = params.cap_max
    sector_filter = params.sector

    out: list[_EnrichedTicker] = []
    for e in enriched:
        if e.error:
            continue
        if e.market_cap is None:
            continue
        if e.market_cap < cap_min or e.market_cap > cap_max:
            continue
        if sector_filter and (not e.sector or sector_filter.lower() not in e.sector.lower()):
            continue
        if e.first_trade_date is not None:
            if ipo_after and e.first_trade_date < ipo_after:
                continue
            if ipo_before and e.first_trade_date > ipo_before:
                continue
        out.append(e)
    return out


async def _refresh_shortlist(
    candidates: list,                          # list[_EnrichedTicker]
) -> dict[str, list[str]]:
    """
    Tier 5a: fetch full companyfacts + price history + analyst for each
    Tier 4 survivor. Reuses Phase 2 `refresh_ticker(ticker, requirement)`
    with the screener-specific requirement (no DEF 14A / 10-K text / Form 4).

    Concurrency: capped at MAX_SEC_CONCURRENCY (SEC fair-use). yfinance
    runs inside refresh_ticker; we don't double-bound it here because
    refresh_ticker itself uses asyncio.gather across its phase-1 fetches
    (companyfacts + Form 4 + yfinance + 10-K) and SEC dominates.

    Returns {ticker: [error strings]} for tickers that hit issues. Empty list
    means refresh succeeded.
    """
    from data.pipeline import refresh_ticker
    from frameworks.base import screener_data_requirement
    from config.constants import MAX_SEC_CONCURRENCY

    requirement = screener_data_requirement()
    sem = asyncio.Semaphore(MAX_SEC_CONCURRENCY)
    errors: dict[str, list[str]] = {}

    async def _one(ticker: str) -> None:
        async with sem:
            try:
                gaps = await refresh_ticker(ticker, requirement=requirement)
                if gaps:
                    errors[ticker] = gaps
            except Exception as exc:    # noqa: BLE001
                errors[ticker] = [f"refresh_ticker failed: {exc}"]

    await asyncio.gather(*[_one(c.ticker) for c in candidates])
    return errors


def _apply_exclusion_policy(
    enriched: list[_EnrichedTicker],
    policy: ExclusionPolicy,
) -> tuple[list[_EnrichedTicker], list[tuple[_EnrichedTicker, str]]]:
    """Tier 3: (survivors, [(ticker, reason)]). Sector / industry only; G1 runs at Tier 5."""
    survivors: list[_EnrichedTicker] = []
    exclusions: list[tuple[_EnrichedTicker, str]] = []
    for e in enriched:
        verdict = policy.classify(e.sector, e.industry)
        if verdict.excluded:
            exclusions.append((e, verdict.reason or "unknown"))
        else:
            survivors.append(e)
    return survivors, exclusions


def _screen_stamp() -> datetime:
    """Today at midnight: `last_screened` is a DateTime column, compared by day."""
    return datetime.combine(date.today(), time())


def _existing_companies(session: Session, tickers: set[str]) -> dict[str, Company]:
    """Companies by ticker, with verdicts batch-loaded since the policy reads them per row."""
    rows = (
        session.query(Company)
        .options(selectinload(Company.exclusion_verdicts))
        .filter(Company.ticker.in_(tickers))
    )
    return {str(c.ticker): c for c in rows}


def _persist_exclusions(
    exclusions: list[tuple[_EnrichedTicker, str]],
    policy: ExclusionPolicy,
) -> None:
    """
    Persist Tier 3 exclusions as `status='archived'` rows, so the user can see
    WHY a ticker dropped (`invest screen show {id}`) until cleanup sweeps them.

    Watchlist + dive_history tickers are never downgraded: once promoted, the
    user has accepted them, and a re-evaluated rule must not kick them out.
    """
    if not exclusions:
        return
    today = _screen_stamp()
    protected = ("watchlist", "dive_history")

    with get_session() as session:
        tickers = {e.ticker for e, _ in exclusions}
        existing = _existing_companies(session, tickers)
        for e, reason in exclusions:
            company = existing.get(e.ticker)
            if company is None:
                company = Company(
                    ticker=e.ticker,
                    cik=e.cik,
                    exchange=e.exchange or "",
                    name=e.name or e.ticker,
                    sector=e.sector,
                    industry=e.industry,
                    market_cap_usd=e.market_cap,
                    currency=e.currency or "USD",
                    listing_type="standard",
                    status="archived",
                    retention_days=30,
                    last_screened=today,
                )
                policy.record_exclusion(company, reason)
                session.add(company)
                continue

            if e.cik and not company.cik:
                company.cik = e.cik
            policy.record_exclusion(company, reason)
            company.last_screened = today  # type: ignore[assignment]
            if company.status not in protected:
                company.status = "archived"


def _persist_screener_candidates(
    survivors: list[_EnrichedTicker],
    retention_days: int,
    policy: ExclusionPolicy | None = None,
) -> None:
    """
    Upsert each survivor as a `Company` row with `status='screener_candidate'`,
    `last_screened=today`, and the user-specified retention.

    If a ticker already exists with `status` in ('watchlist', 'dive_history'),
    we DO NOT downgrade — leave the higher status alone, but refresh
    `last_screened` so the cleanup job knows it was re-validated by this run.
    """
    if not survivors:
        return
    today = _screen_stamp()
    protected = ("watchlist", "dive_history")

    with get_session() as session:
        tickers = {e.ticker for e in survivors}
        existing = _existing_companies(session, tickers)

        for e in survivors:
            company = existing.get(e.ticker)
            if company is None:
                company = Company(
                    ticker=e.ticker,
                    cik=e.cik,
                    exchange=e.exchange or "",
                    name=e.name or e.ticker,
                    sector=e.sector,
                    industry=e.industry,
                    market_cap_usd=e.market_cap,
                    currency=e.currency or "USD",
                    listing_type="standard",
                    status="screener_candidate",
                    retention_days=retention_days,
                    last_screened=today,
                )
                session.add(company)
                continue

            # Update existing — but DON'T downgrade status
            if e.cik and not company.cik:
                company.cik = e.cik
            company.exchange = e.exchange or company.exchange
            if e.name:
                company.name = e.name
            if e.sector:
                company.sector = e.sector
            if e.industry:
                company.industry = e.industry
            if e.market_cap is not None:
                company.market_cap_usd = e.market_cap
            if e.currency:
                company.currency = e.currency
            company.last_screened = today  # type: ignore[assignment]
            if company.status not in protected:
                company.status = "screener_candidate"
                company.retention_days = retention_days
                if policy is not None:
                    policy.record_tier3_pass(company)
