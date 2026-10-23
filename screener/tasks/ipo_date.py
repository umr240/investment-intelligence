"""IPO-date task — Phase 4b (ADR-017 §3.1).

Derives an IPO proxy from SEC ``submissions.json``: the earliest 10-K filing
date in the registrant's history. ``filings.recent`` caps at ~1000 filings, so
older ones are traversed via ``filings.files[]`` — without that, a long-history
filer reports whichever 10-K happened to fit in the recent page (CSGP: 2012,
against a 1998 listing).

The result is a floor, not a listing date. Registrants already listed when
EDGAR began carrying filings (1993-1996) cannot be dated from SEC data at any
depth, and stay ``parser_uncertain``; yfinance ``firstTradeDateMs`` or FMP
``/profile.ipoDate`` are the sources for those.

Refresh interval: 180 days. IPO dates barely change; the only motion comes
from rare ticker-restatement events.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from config.settings import settings
from data.models.schema import Company
from data.rate_limit import TokenBucket
from screener.tasks.base import FilterResult, RateLimitError

logger = logging.getLogger("task-runner")

_SEC_HEADERS = {
    "Accept-Encoding": "gzip",
    "Host": "data.sec.gov",
}


class IPODateTask:
    name = "ipo_date"
    source = "sec"
    refresh_interval = timedelta(days=180)
    concurrency_override = 1            # serial — SEC soft-blocks parallel bursts

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            .where(Company.cik.isnot(None))
            .where(Company.cik != "")
            .where(
                or_(
                    Company.ipo_date_fetched_at.is_(None),
                    Company.ipo_date_fetched_at < cutoff,
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
        headers = {"User-Agent": settings.edgar_identity, **_SEC_HEADERS}
        results: list[FilterResult] = []
        for c in companies:
            await bucket.acquire()
            cik_padded = (c.cik or "").zfill(10)
            url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
            try:
                r = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning(
                    "[%s] %s submissions.json error: %s", self.name, c.ticker, exc
                )
                continue
            if r.status_code == 429:
                raise RateLimitError("sec")
            if r.status_code != 200:
                logger.info(
                    "[%s] %s submissions.json status=%d",
                    self.name, c.ticker, r.status_code,
                )
                continue
            try:
                payload = r.json()
            except ValueError:
                continue

            # Traverse filings.files[] so long-history filers resolve to their
            # true earliest 10-K rather than the oldest one that happened to fit
            # in filings.recent (CSGP: 2012 from the recent page, 1998 with the
            # shard). Usually 0-1 extra requests, through the same bucket.
            pairs = _filing_pairs(payload)
            shards_exhausted = True
            for shard_url in shard_urls(payload):
                await bucket.acquire()
                try:
                    sr = await client.get(shard_url, headers=headers)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "[%s] %s shard error: %s", self.name, c.ticker, exc
                    )
                    shards_exhausted = False
                    break
                if sr.status_code == 429:
                    raise RateLimitError("sec")
                if sr.status_code != 200:
                    logger.info(
                        "[%s] %s shard status=%d", self.name, c.ticker, sr.status_code
                    )
                    shards_exhausted = False
                    break
                try:
                    pairs.extend(_filing_pairs(sr.json()))
                except ValueError:
                    shards_exhausted = False
                    break

            ipo = earliest_10k(pairs)
            state = classify_listing_state(ipo, shards_exhausted=shards_exhausted)
            # Phase 5e gap-3 + 5f follow-ups: also extract sicDescription
            # AND fiscalYearEnd from the same payload (zero extra HTTP).
            # Without fiscalYearEnd, refresh_universe()-seeded rows keep
            # the schema default of 12 even for off-calendar filers like
            # MSFT (June), AAPL (September), NVDA (January).
            sic_description = payload.get("sicDescription")
            fye_raw = payload.get("fiscalYearEnd")
            fye_month: int | None = None
            if (
                isinstance(fye_raw, str)
                and len(fye_raw) == 4
                and fye_raw.isdigit()
            ):
                m = int(fye_raw[:2])
                if 1 <= m <= 12:
                    fye_month = m
            results.append(FilterResult(
                cik=c.cik,
                values={
                    "ipo_date": ipo,
                    "ipo_date_state": state,
                    "sic_description": sic_description,
                    "fye_month": fye_month,
                },
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        # Local import — avoids a top-level cross-module dep just for the
        # SIC→(sector,industry) fallback path.
        from screener.tasks.metadata_polygon import _sector_industry_from_sic

        now = datetime.now(UTC)
        keys = [r.cik for r in results]
        rows = db.execute(
            select(Company).where(Company.cik.in_(keys))
        ).scalars().all()
        by_cik = {r.cik: r for r in rows}

        # Per-field source tagging (Phase 1) — IPODateTask derives the
        # IPO date from SEC submissions.json (earliest 10-K or proxy), so
        # writes record SEC_SUBMISSIONS (Tier 1A) provenance.
        from config.source_tags import SEC_SUBMISSIONS as _SRC_SUB
        for r in results:
            company = by_cik.get(r.cik)
            if company is None:
                continue
            company.ipo_date_fetched_at = now
            new_state = r.values["ipo_date_state"]
            new_date = r.values["ipo_date"]
            existing_date = company.ipo_date

            # Two guards, both learned from live data:
            #  - never trade stronger provenance for weaker (MSFT holds a correct
            #    1986 date from elsewhere; EDGAR's floor for it is 1994)
            #  - an earliest-known date only moves earlier as evidence improves.
            #    Shopify listed 2015 but its first 10-K is 2025, so an equal-rank
            #    write would push it a decade later.
            weaker = _state_rank(new_state) < _state_rank(company.ipo_date_state)
            later = (
                existing_date is not None
                and new_date is not None
                and new_date > existing_date
            )
            if weaker or later:
                logger.info(
                    "[%s] %s keeping %s/%s over %s/%s",
                    self.name, company.ticker, existing_date,
                    company.ipo_date_state, new_date, new_state,
                )
            else:
                company.ipo_date = new_date
                company.ipo_date_state = new_state
                if new_date is not None:
                    company.ipo_date_source = _SRC_SUB

            # Phase 5f follow-up: write fiscalYearEnd from submissions.json
            # so MSFT (June), AAPL (Sep), NVDA (Jan) etc. don't get stuck
            # at the default of 12 (calendar year-end). Required by
            # FundamentalsTask's parse_companyfacts.
            fye = r.values.get("fye_month")
            if fye is not None:
                company.fiscal_year_end_month = fye

            # Phase 5e gap-3 + Phase 5f fix: SEC SIC sector + industry
            # fallback. Only fill when each is currently NULL — never
            # overwrite a yfinance or Polygon value (those are more
            # precise / paid-grade respectively).
            sic_desc = r.values.get("sic_description")
            if sic_desc:
                derived = _sector_industry_from_sic(sic_desc)
                if derived is None:
                    continue
                sector, industry_hint = derived
                if company.sector is None and sector:
                    company.sector = sector
                    company.sector_source = "sec-sic"
                    company.sector_fetched_at = now
                # Industry hint is what an exclusion policy's industry-level
                # rules match against. Without it, sector-only classification
                # misses banks/insurance/etc that get sector="Financial
                # Services" but no industry.
                if company.industry is None and industry_hint:
                    company.industry = industry_hint
                    company.industry_fetched_at = now

        db.commit()


# Electronic filing on EDGAR was phased in 1993-1996. An earliest 10-K at or
# before this date means the registrant was already listed when EDGAR began, so
# its true listing date is unknowable from SEC data at any depth (AAPL's oldest
# EDGAR filing is 1994; it listed in 1980).
_EDGAR_ELECTRONIC_FLOOR = date(1996, 12, 31)


def shard_urls(payload: dict[str, Any]) -> list[str]:
    """Older-filing shard URLs named by ``filings.files[]``, oldest first."""
    files = (payload.get("filings") or {}).get("files") or []
    names = [f.get("name") for f in files if isinstance(f, dict) and f.get("name")]
    return [f"https://data.sec.gov/submissions/{n}" for n in reversed(names)]


def _filing_pairs(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """(form, filingDate) pairs from either a main payload or a shard payload."""
    block = (payload.get("filings") or {}).get("recent") or payload
    forms = block.get("form") or []
    filed = block.get("filingDate") or []
    return list(zip(forms, filed, strict=False))


_STATE_RANK = {"disclosed_exact": 3, "parser_uncertain": 2, "not_disclosed": 1}


def _state_rank(state: str | None) -> int:
    """Provenance strength, for refusing downgrades. Unset ranks lowest."""
    return _STATE_RANK.get(state or "", 0)


def _is_annual_report(form: str) -> bool:
    """Any annual report, domestic or foreign, is evidence of being listed.

    - 10-K variants: `10-K405` was the annual form from 1996-2002 (10-K plus the
      Rule 405 checkbox), so an exact "10-K" match skips the whole late-90s IPO
      cohort — NVDA's first three annual reports are 10-K405. Covers 10-KSB,
      10-KT and /A amendments too.
    - 20-F / 40-F: foreign private issuers file these instead. Shopify listed in
      2015 and filed 40-F until converting to domestic forms, so its first 10-K
      is 2025 — a decade late if foreign forms are ignored.
    """
    f = form.upper().replace("-", "")
    return f.startswith(("10K", "20F", "40F"))


def earliest_10k(pairs: list[tuple[str, str]]) -> date | None:
    earliest: date | None = None
    for form, fd in pairs:
        if not _is_annual_report(form):
            continue
        try:
            d = date.fromisoformat(fd)
        except (TypeError, ValueError):
            continue
        if earliest is None or d < earliest:
            earliest = d
    return earliest


def classify_listing_state(earliest: date | None, *, shards_exhausted: bool) -> str:
    """ADR-018 state for an earliest-10-K date, from provenance alone.

    Deliberately independent of wall-clock age: the previous rule returned
    `disclosed_exact` once the earliest known filing passed 10 years old, so the
    same payload classified differently depending on when the task ran.
    """
    if earliest is None:
        return "not_disclosed"
    if not shards_exhausted:
        return "parser_uncertain"
    if earliest <= _EDGAR_ELECTRONIC_FLOOR:
        # Listed before EDGAR carried it — this is a floor, not a listing date.
        return "parser_uncertain"
    return "disclosed_exact"


__all__ = ["IPODateTask"]
