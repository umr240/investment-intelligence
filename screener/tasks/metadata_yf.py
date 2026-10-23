"""yfinance metadata task — populates Company.market_cap, sector, industry,
currency, country, and analyst count from yfinance ``.info``.

This is the warehouse-model port of legacy Tier 2. ADR-017 §11 names this
``MetadataFMPTask`` because FMP was the planned replacement, but FMP
plumbing isn't built yet — we keep yfinance to avoid scope creep. Swapping
to FMP later is a one-class rewrite (``MetadataFMPTask`` replaces this).

Yahoo's anti-abuse layer rate-limits us hard (see constants.MAX_YF_CONCURRENCY),
so this task runs at ``concurrency_override=1`` and acquires a single
YF_BUCKET token per ticker. Per-ticker yfinance hiccups are tolerated
silently — the next refresh cycle picks them up.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.api.yfinance_client import fetch_yfinance_metadata_only
from data.models.schema import Company
from data.rate_limit import TokenBucket
from screener.policies import not_excluded
from screener.tasks.base import FilterResult

logger = logging.getLogger("task-runner")


class MetadataYFTask:
    name = "metadata_yf"
    source = "yf"
    refresh_interval = timedelta(hours=24)
    concurrency_override = 1            # Yahoo bans us above this

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            # Don't spend yfinance quota on companies the policy excluded.
            # Run exclusion_classify BEFORE this task at universe scale.
            .where(not_excluded())
            .where(
                or_(
                    Company.market_cap_fetched_at.is_(None),
                    Company.market_cap_fetched_at < cutoff,
                )
            )
        )
        return list(db.execute(stmt).scalars().all())

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,        # unused — yfinance has its own client
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        # Phase 5e gap-1 fix: emit a FilterResult for EVERY ticker we attempted,
        # even on failure. persist() bumps market_cap_fetched_at = now whenever
        # `_yf_attempted` is True so we don't keep retrying chronically-broken
        # symbols every cron run. The cap stays NULL on failure so
        # MetadataPolygonTask still picks it up via its `cap IS NULL` filter.
        results: list[FilterResult] = []
        for c in companies:
            await bucket.acquire()
            try:
                # yfinance is synchronous; offload so we don't block the loop.
                meta = await asyncio.to_thread(fetch_yfinance_metadata_only, c.ticker)
            except Exception as exc:
                logger.warning(
                    "[%s] yfinance threw for %s: %s", self.name, c.ticker, exc
                )
                results.append(FilterResult(
                    cik=c.cik or c.ticker,
                    values={"_yf_attempted": True, "_yf_error": f"{type(exc).__name__}: {exc}"},
                    notes=[f"yfinance threw: {exc}"],
                ))
                continue
            if meta.error:
                logger.info(
                    "[%s] %s skipped: %s", self.name, c.ticker, meta.error
                )
                results.append(FilterResult(
                    cik=c.cik or c.ticker,
                    values={"_yf_attempted": True, "_yf_error": meta.error},
                    notes=[meta.error],
                ))
                continue
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "_yf_attempted": True,
                    "_yf_success": True,
                    "market_cap_usd": meta.market_cap,
                    "sector": meta.sector,
                    "industry": meta.industry,
                    "currency": meta.currency,
                    "shares_float": meta.float_shares,
                    "first_trade_date": meta.first_trade_date,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        # Map back from cik (or ticker fallback) to the Company.id for the UPDATE
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                or_(Company.cik.in_(keys), Company.ticker.in_(keys))
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            v = r.values
            # Phase 5e gap-1: bump fetched_at whenever we attempted, regardless
            # of success. Stops yfinance from re-attempting broken tickers
            # every cron run inside the refresh window.
            if v.get("_yf_attempted"):
                company.market_cap_fetched_at = now

            # On failure, leave actual columns alone — Polygon (or SEC SIC)
            # backfills via cap IS NULL / sector IS NULL filters.
            if not v.get("_yf_success"):
                continue

            # Per-field source tagging (Phase 1) — every yfinance write
            # records `_source='yfinance'` for tier-weighted completeness.
            from config.source_tags import YFINANCE as _SRC_YF
            mc = v.get("market_cap_usd")
            if mc is not None:
                company.market_cap_usd = mc
                company.market_cap_usd_source = _SRC_YF
            if v.get("sector") is not None:
                company.sector = v["sector"]
                company.sector_source = "yfinance"   # 5e gap-2: source audit
                company.sector_fetched_at = now
            if v.get("industry") is not None:
                company.industry = v["industry"]
                company.industry_fetched_at = now
            if v.get("currency") is not None:
                company.currency = v["currency"]
                company.currency_source = _SRC_YF
            if v.get("shares_float") is not None:
                company.shares_float = v["shares_float"]
                company.shares_float_source = _SRC_YF
            # Set ipo_date from first_trade_date IF Company.ipo_date is missing.
            # IPODateTask owns this column long-term; we only seed it here.
            if v.get("first_trade_date") is not None and company.ipo_date is None:
                company.ipo_date = v["first_trade_date"]
                company.ipo_date_fetched_at = now
                company.ipo_date_state = "disclosed_exact"
                company.ipo_date_source = _SRC_YF

        db.commit()


__all__ = ["MetadataYFTask"]
