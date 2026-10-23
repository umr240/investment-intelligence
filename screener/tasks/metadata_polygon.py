"""Polygon metadata task — fallback for MetadataYFTask (Phase 5c / ADR-019).

Uses Polygon's ``/v3/reference/tickers/{t}`` to populate the same warehouse
columns that ``MetadataYFTask`` writes. Per source-priority chain (MetadataYF
primary, MetadataPolygon fallback):

  - ``select_pending`` returns Company rows whose metadata is missing AND
    yfinance has already failed (``market_cap_fetched_at`` set but
    ``market_cap_usd`` is NULL — i.e. yfinance was tried recently and
    didn't deliver). Fresh tickers without any prior attempt are left for
    yfinance first.
  - 5/min throttle via shared :data:`POLYGON_BUCKET`.
  - Returns ``None`` when ``POLYGON_API_KEY`` unset (task short-circuits).

What Polygon gives us (free tier, verified per ADR-019 §1):

  - market_cap (`results.market_cap`)
  - sector  → derived from `sic_description` (best-effort string match)
  - list_date → IPO-date proxy
  - primary_exchange
  - weighted_shares_outstanding

What Polygon does NOT give (yfinance only on free tier):

  - analyst_count / recommendation / price_target
  - insider_pct, institution_pct, short_pct_float
  - beta, P/E trailing, P/B, EV/EBITDA
  - earnings history

For full coverage of those fields, ``MetadataYFTask`` remains the primary
metadata writer and Polygon supplements only what fits.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from data.api.polygon_client import PolygonClient
from data.models.schema import Company
from screener.policies import not_excluded
from screener.tasks.base import FilterResult

if TYPE_CHECKING:
    from data.rate_limit import TokenBucket

logger = logging.getLogger("task-runner")


# Coarse-grained yfinance-style sector + industry mapping derived from SIC.
# Polygon and SEC return sic_description like "STATE COMMERCIAL BANKS"; we
# map to (sector, industry_hint) so an exclusion policy's industry-level rules,
# written against yfinance-style strings like "Banks—Diversified", still match.
# Hints are emitted only for sectors where industry matters (banks, insurance,
# tobacco, casinos, ...); the strings are part of the policy contract.
#
# This is a SOFT classification; if yfinance later runs and overwrites
# Company.sector / .industry, the precise yfinance values win (UPSERT
# precedence: yfinance > polygon-sic-derived > sec-sic-derived).
_SIC_SECTOR_HINTS: tuple[tuple[str, str, str | None], ...] = (
    # (needle, sector, industry_hint)
    ("SOFTWARE",        "Technology",            None),
    ("COMPUTER",        "Technology",            None),
    ("SEMICONDUCTOR",   "Technology",            None),
    ("ELECTRONIC",      "Technology",            None),
    ("DATA PROCESSING", "Technology",            None),
    ("PHARMACEUTICAL",  "Healthcare",            None),
    ("MEDICAL",         "Healthcare",            None),
    ("BIOLOGICAL",      "Healthcare",            None),
    ("HOSPITAL",        "Healthcare",            None),

    # Energy / oil & gas — matched by "oil & gas e&p" / "drilling" rules
    ("CRUDE PETROLEUM",                "Energy", "Oil & Gas E&P"),
    ("PETROLEUM REFINING",             "Energy", "Oil & Gas Refining"),
    ("OIL & GAS",                      "Energy", "Oil & Gas E&P"),
    ("NATURAL GAS",                    "Energy", "Oil & Gas E&P"),
    ("DRILLING OIL",                   "Energy", "Oil & Gas Drilling"),
    ("OIL AND GAS FIELD SERVICES",     "Energy", "Oil & Gas Drilling"),

    ("MINING",          "Basic Materials",       None),
    ("CHEMICAL",        "Basic Materials",       None),

    # Banking — matched by "banks" needle
    ("STATE COMMERCIAL BANKS",   "Financial Services", "Banks—Diversified"),
    ("NATIONAL COMMERCIAL BANKS","Financial Services", "Banks—Diversified"),
    ("SAVINGS INSTITUTION",      "Financial Services", "Banks—Regional"),
    ("BANK HOLDING",             "Financial Services", "Banks—Diversified"),
    ("BANK",                     "Financial Services", "Banks—Diversified"),
    ("BANKING",                  "Financial Services", "Banks—Diversified"),

    # Insurance — matched by "life insurance" / "insurance—property"
    ("LIFE INSURANCE",                  "Financial Services", "Life Insurance"),
    ("ACCIDENT AND HEALTH INSURANCE",   "Financial Services", "Life Insurance"),
    ("FIRE, MARINE & CASUALTY INSURANCE","Financial Services","Insurance—Property"),
    ("HOSPITAL & MEDICAL SERVICE PLANS","Financial Services", "Insurance—Diversified"),
    ("INSURANCE AGENTS",                "Financial Services", "Insurance Brokers"),
    ("INSURANCE",                       "Financial Services", "Insurance—Diversified"),

    # Investment banking / brokerage — matched by "investment banking" / "brokerage"
    ("SECURITY BROKERS, DEALERS",  "Financial Services", "Capital Markets"),
    ("INVESTMENT ADVICE",          "Financial Services", "Capital Markets"),
    ("INVESTMENT",                 "Financial Services", "Capital Markets"),

    # Alcohol — matched by "breweries"/"distilleries"/"wineries"
    ("BEVERAGES, ALCOHOLIC",  "Consumer Defensive", "Breweries"),
    ("MALT BEVERAGES",        "Consumer Defensive", "Breweries"),
    ("BEVERAGES, BOTTLED",    "Consumer Defensive", "Beverages—Non-Alcoholic"),
    ("BREWERIES",             "Consumer Defensive", "Breweries"),
    ("DISTILLERIES",          "Consumer Defensive", "Distilleries"),
    ("WINERIES",              "Consumer Defensive", "Wineries"),

    # Tobacco — matched by "tobacco"
    ("CIGARETTES",  "Consumer Defensive", "Tobacco"),
    ("TOBACCO",     "Consumer Defensive", "Tobacco"),

    # Gambling — matched by "gambling"/"casinos"
    ("SERVICES-AMUSEMENT & RECREATION SERVICES", "Consumer Cyclical", "Gambling"),
    ("CASINOS",  "Consumer Cyclical", "Resorts & Casinos"),
    ("GAMBLING", "Consumer Cyclical", "Gambling"),

    # Defense — matched by "aerospace & defense"
    ("ORDNANCE",          "Industrials", "Aerospace & Defense"),
    ("AIRCRAFT ENGINES",  "Industrials", "Aerospace & Defense"),
    ("AIRCRAFT",          "Industrials", "Aerospace & Defense"),
    ("GUIDED MISSILES",   "Industrials", "Aerospace & Defense"),

    # Other sectors (no industry hint needed)
    ("BEVERAGES",       "Consumer Defensive",    None),
    ("FOOD",            "Consumer Defensive",    None),
    ("RETAIL",          "Consumer Cyclical",     None),
    ("APPAREL",         "Consumer Cyclical",     None),
    ("RESTAURANTS",     "Consumer Cyclical",     None),
    ("MOTOR VEHICLE",   "Consumer Cyclical",     None),
    ("HOTEL",           "Consumer Cyclical",     None),
    ("AIR TRANSPORT",   "Industrials",           None),
    ("RAILROAD",        "Industrials",           None),
    ("TRUCKING",        "Industrials",           None),
    ("ENGINEERING",     "Industrials",           None),
    ("CONSTRUCTION",    "Industrials",           None),
    ("ELECTRIC SERVICES","Utilities",            None),
    ("GAS DISTRIBUTION","Utilities",             None),
    ("WATER SUPPLY",    "Utilities",             None),
    ("REAL ESTATE",     "Real Estate",           None),
    ("TELEPHONE",       "Communication Services", None),
    ("RADIO",           "Communication Services", None),
    ("TELEVISION",      "Communication Services", None),
    ("ADVERTISING",     "Communication Services", None),
)


def _sector_from_sic(sic_desc: str | None) -> str | None:
    """Backwards-compat helper — returns sector only.

    New code should call :func:`_sector_industry_from_sic` to get both.
    """
    result = _sector_industry_from_sic(sic_desc)
    return result[0] if result else None


def _sector_industry_from_sic(
    sic_desc: str | None,
) -> tuple[str, str | None] | None:
    """Map SEC/Polygon sicDescription to (sector, industry_hint).

    Returns None when no rule matches. Sectors that need no industry hint
    (Technology, Healthcare) return industry=None. First-match-wins on the
    SIC needle.
    """
    if not sic_desc:
        return None
    upper = sic_desc.upper()
    for needle, sector, industry in _SIC_SECTOR_HINTS:
        if needle in upper:
            return (sector, industry)
    return None


class MetadataPolygonTask:
    """Polygon-backed metadata fallback. Runs only after yfinance has failed."""

    name = "metadata_polygon"
    source = "polygon"
    refresh_interval = timedelta(hours=24)
    concurrency_override = 1            # 5/min global bucket already serialises

    def select_pending(self, db: Session) -> list[Company]:
        client = PolygonClient()
        if not client.has_key:
            return []
        cutoff = datetime.now(UTC) - self.refresh_interval
        # Pending = active Company where market cap is missing AND
        # (yfinance has been tried OR not at all). Polygon backfills gaps.
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            # Don't spend Polygon quota on companies the policy excluded.
            .where(not_excluded())
            .where(Company.market_cap_usd.is_(None))
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
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        polygon = PolygonClient()
        if not polygon.has_key:
            return []
        results: list[FilterResult] = []
        for c in companies:
            try:
                resp = await asyncio.to_thread(
                    polygon.fetch_ticker_details, c.ticker,
                )
            except Exception as exc:
                logger.warning(
                    "[%s] %s threw: %s", self.name, c.ticker, exc,
                )
                continue
            if not resp.ok or not resp.rows:
                continue
            details = resp.rows[0]
            sic_pair = _sector_industry_from_sic(details.sic_description)
            sector_hint = sic_pair[0] if sic_pair else None
            industry_hint = sic_pair[1] if sic_pair else None
            results.append(FilterResult(
                cik=c.cik or c.ticker,
                values={
                    "ticker": c.ticker,
                    "market_cap_usd": details.market_cap,
                    "sector_hint": sector_hint,
                    "industry_hint": industry_hint,
                    "list_date": details.list_date,
                    "primary_exchange": details.primary_exchange,
                    "shares_outstanding": details.weighted_shares_outstanding,
                    "sic_description": details.sic_description,
                    "name": details.name,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(
                Company.cik.in_(keys) | Company.ticker.in_(keys)
            )
        ).scalars().all()
        by_key = {(r.cik or r.ticker): r for r in rows}

        for r in results:
            company = by_key.get(r.cik)
            if company is None:
                continue
            v = r.values
            # Per-field source tagging (Phase 1) — Polygon writes record
            # Tier 3a (0.95) provenance via `_source='polygon'`.
            from config.source_tags import POLYGON as _SRC_PG
            if v["market_cap_usd"] is not None:
                company.market_cap_usd = v["market_cap_usd"]
                company.market_cap_fetched_at = now
                company.market_cap_usd_source = _SRC_PG
            # Sector — only fill when missing. Don't overwrite a yfinance
            # sector value with a SIC-derived one (yfinance is more precise).
            if company.sector is None and v.get("sector_hint") is not None:
                company.sector = v["sector_hint"]
                company.sector_source = "polygon-sic"     # 5e gap-2: source audit
                company.sector_fetched_at = now
            # Industry hint feeds the exclusion policy's industry-level rules
            # (Phase 5f fix): sector "Financial Services" alone can't tell a bank.
            if company.industry is None and v.get("industry_hint") is not None:
                company.industry = v["industry_hint"]
                company.industry_fetched_at = now
            # List date — IPO proxy, fill only when missing
            if company.ipo_date is None and v["list_date"] is not None:
                company.ipo_date = v["list_date"]
                company.ipo_date_fetched_at = now
                company.ipo_date_state = "disclosed_exact"
                company.ipo_date_source = _SRC_PG
            if v["shares_outstanding"] is not None:
                company.shares_float = v["shares_outstanding"]
                company.shares_float_source = _SRC_PG

        db.commit()


__all__ = ["MetadataPolygonTask"]
