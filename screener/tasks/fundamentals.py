"""Fundamentals task — Phase 4b port of legacy Tier 5 (per-ticker companyfacts).

Pulls SEC ``companyfacts.json`` per ticker, parses every fiscal period,
persists ``Financial`` rows via the existing ``_persist_financials`` helper
in ``data.pipeline``, and rolls up the latest annual values onto
``Company`` warehouse columns (``roic``, ``fcf_margin``, ``debt_to_equity``,
``revenue_growth``).

Refresh interval: 90 days. Companies file 10-K once per year and 10-Q
quarterly; checking every 90 days covers the cadence with one safety margin.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from config.settings import settings
from data.cache.manager import CacheManager
from data.edgar_companyfacts import parse_companyfacts
from data.models.schema import Company, Financial
from data.pipeline import _persist_financials
from data.rate_limit import TokenBucket
from screener.policies import not_excluded
from screener.tasks.base import FilterResult, RateLimitError

logger = logging.getLogger("task-runner")

_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_CACHE_TTL_SEC = 30 * 24 * 3600       # 30 days for screener_candidate (DEC-11)
_SEC_HEADERS = {
    "Accept-Encoding": "gzip",
    "Host": "data.sec.gov",
}


class FundamentalsTask:
    name = "fundamentals"
    source = "sec"
    refresh_interval = timedelta(days=90)
    concurrency_override = 1            # serial — SEC soft-blocks parallel bursts

    def __init__(self) -> None:
        self._cache = CacheManager()

    def select_pending(self, db: Session) -> list[Company]:
        cutoff = datetime.now(UTC) - self.refresh_interval
        stmt = (
            select(Company)
            .where(Company.status.in_(["screener_candidate", "watchlist"]))
            .where(Company.cik.isnot(None))
            .where(Company.cik != "")
            # Skip companies the active exclusion policy excluded.
            .where(not_excluded())
            .where(
                or_(
                    Company.fundamentals_fetched_at.is_(None),
                    Company.fundamentals_fetched_at < cutoff,
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
            cik_int = int(c.cik or 0)
            cache_key = f"companyfacts:{cik_int}"
            payload: dict[str, Any] | None = self._cache.get(cache_key)

            if payload is None:
                await bucket.acquire()
                url = _COMPANYFACTS_URL.format(cik=cik_int)
                try:
                    r = await client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "[%s] %s companyfacts error: %s",
                        self.name, c.ticker, exc,
                    )
                    continue
                if r.status_code == 429:
                    raise RateLimitError("sec")
                if r.status_code == 404:
                    logger.info("[%s] %s no companyfacts (404)", self.name, c.ticker)
                    continue
                if r.status_code != 200:
                    logger.info(
                        "[%s] %s companyfacts status=%d",
                        self.name, c.ticker, r.status_code,
                    )
                    continue
                try:
                    payload = r.json()
                except ValueError:
                    continue
                self._cache.set(cache_key, payload, ttl=_CACHE_TTL_SEC)

            if not payload:
                continue

            fye_month = c.fiscal_year_end_month or 12
            try:
                rows = parse_companyfacts(
                    ticker=c.ticker,
                    payload=payload,
                    annual_years_limit=10,
                    fiscal_year_end_month=fye_month,
                )
            except Exception as exc:
                logger.warning(
                    "[%s] %s parse_companyfacts threw: %s",
                    self.name, c.ticker, exc,
                )
                continue

            if not rows:
                continue

            results.append(FilterResult(
                cik=c.cik,
                values={"rows": rows, "ticker": c.ticker},
            ))
        return results

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if not results:
            return
        now = datetime.now(UTC)

        # Persist Financial rows via the existing helper (it manages its own
        # session; the data has been committed by the time we proceed).
        for r in results:
            ticker = r.values["ticker"]
            rows = r.values["rows"]
            _persist_financials(ticker, rows)

        # Roll up latest-annual ratios onto the Company warehouse row using
        # this task's session. Read after the helper above has committed so
        # we see the freshly-persisted Financial rows.
        keys = [r.cik for r in results]
        companies = db.execute(
            select(Company).where(Company.cik.in_(keys))
        ).scalars().all()
        by_cik = {c.cik: c for c in companies}

        for r in results:
            company = by_cik.get(r.cik)
            if company is None:
                continue
            company.fundamentals_fetched_at = now
            self._rollup_warehouse_columns(db, company, now)

        db.commit()

    @staticmethod
    def _rollup_warehouse_columns(
        db: Session,
        company: Company,
        now: datetime,
    ) -> None:
        """Snapshot latest annual ratios onto the warehouse row.

        Reads the two most recent ``period='annual'`` rows for this company
        for the standard ratios, and up to 10 annuals for the Peters-Taylor
        adjusted ROIC perpetual-inventory calculation.

        Writes:
          • ``roic``               — latest annual GAAP roic
          • ``fcf_margin``         — latest annual fcf_margin
          • ``debt_to_equity``     — latest annual debt_to_equity
          • ``revenue_growth``     — latest_annual_revenue / prior - 1
          • ``pt_adjusted_roic``   — Peters-Taylor (2017 JFE) economic ROIC
                                     using same KC+OC formula as
                                     ``overlays/ica.py``. Phase 5i / ADR-021.
        """
        annuals_short = db.execute(
            select(Financial)
            .where(Financial.company_id == company.id)
            .where(Financial.period == "annual")
            .order_by(Financial.fiscal_year.desc())
            .limit(2)
        ).scalars().all()

        if not annuals_short:
            return

        latest = annuals_short[0]
        prior = annuals_short[1] if len(annuals_short) > 1 else None

        # Phase 5k-5 industry-aware float adjustment: subtract
        # investment_income_interest from EBIT for non-insurers when the
        # XBRL tag is present. Insurers (where investment income IS the
        # business) keep the unadjusted Financial.roic value.
        is_insurer = bool(
            company.industry and company.industry.lower().startswith("insurance")
        )
        float_iie = latest.investment_income_interest
        adj_roic = latest.roic
        adj_pretax = latest.pretax_roic
        if (
            not is_insurer
            and float_iie is not None
            and float_iie > 0
            and latest.operating_income is not None
        ):
            te = latest.total_equity or 0.0
            td = latest.total_debt or 0.0
            cs = latest.cash_and_equivalents or 0.0
            ic = te + td - cs
            if ic > 0:
                from data.pipeline import _effective_tax_rate
                adj_ebit = latest.operating_income - float_iie
                etr = _effective_tax_rate(
                    latest.net_income, latest.income_tax_expense,
                )
                adj_roic = (adj_ebit * (1 - etr)) / ic
                adj_pretax = adj_ebit / ic

        # Per-field source tagging (Phase 1) — these are self-computed from
        # SEC XBRL primitives in `data/edgar_companyfacts.py` + ratio
        # derivation in `data/pipeline.py:_apply_financial_row`. Tier 2.
        from config.source_tags import SELF_COMPUTED as _SRC_SC
        if adj_roic is not None:
            company.roic = adj_roic
            company.roic_fetched_at = now
            company.roic_source = _SRC_SC
        if adj_pretax is not None:
            company.pretax_roic = adj_pretax
            company.pretax_roic_fetched_at = now
            company.pretax_roic_source = _SRC_SC
        if latest.fcf_margin is not None:
            company.fcf_margin = latest.fcf_margin
            company.fcf_margin_fetched_at = now
            company.fcf_margin_source = _SRC_SC
        if latest.debt_to_equity is not None:
            company.debt_to_equity = latest.debt_to_equity
            company.debt_to_equity_fetched_at = now
            company.debt_to_equity_source = _SRC_SC

        if (
            prior is not None
            and latest.revenue is not None
            and prior.revenue
            and prior.revenue > 0
        ):
            company.revenue_growth = latest.revenue / prior.revenue - 1.0
            company.revenue_growth_fetched_at = now
            company.revenue_growth_source = _SRC_SC

        # ── Peters-Taylor adjusted ROIC (Phase 5i / ADR-021) ────────────
        # Same math as overlays/ica.py:run_ica. We compute it at warehouse
        # rollup so the screener composite_score can use it without
        # waiting for a dive. Only fires when ≥2 annuals have BOTH
        # rd_expense AND sga_expense — the perpetual-inventory build needs
        # cumulative R&D + SG&A history. Tickers that don't disclose R&D
        # (e.g., consumer goods, financials) skip silently — pt_adjusted_roic
        # stays NULL and the composite falls back to GAAP roic.
        annuals_long = db.execute(
            select(Financial)
            .where(Financial.company_id == company.id)
            .where(Financial.period == "annual")
            .order_by(Financial.fiscal_year.desc())
            .limit(10)
        ).scalars().all()
        pt_roic = _compute_pt_adjusted_roic(annuals_long)
        if pt_roic is not None:
            company.pt_adjusted_roic = pt_roic
            company.pt_adjusted_roic_fetched_at = now
            company.pt_adjusted_roic_source = _SRC_SC


# Peters-Taylor parameters (paper defaults — must stay in sync with overlays/ica.py)
_KC_DEPRECIATION_RATE = 0.15           # R&D amortises at 15%/yr
_OC_DEPRECIATION_RATE = 0.20           # SG&A organisational at 20%/yr
_OC_SGA_FRACTION = 0.25                # 25% of SG&A treated as organisational capital
_PT_GROWTH_RATE = 0.05                 # initial-stock growth assumption (5%)
_PT_TAX_RATE = 0.21                    # US corporate effective rate fallback


# Mode strings on the result dict. Stable names — consumers (CLI display,
# dual-composite logic) key off these.
PT_MODE_FULL = "full"        # Peters-Taylor (2017): KC from R&D + OC from SG&A
PT_MODE_OC_ONLY = "oc_only"  # Eisfeldt-Papanikolaou (2013): OC from SG&A only
                              # (used when company doesn't disclose R&D as a separate
                              # XBRL fact, e.g. consumer telehealth, marketing-led)
PT_MODE_UNAVAILABLE = "unavailable"  # neither R&D nor SG&A history sufficient


def _compute_pt_adjusted_roic(annuals_desc: list) -> float | None:
    """Backward-compatible scalar accessor. See ``compute_pt_adjusted_full``
    for the rich result dict — this thin wrapper returns just the value.
    """
    out = compute_pt_adjusted_full(annuals_desc)
    return out.get("value") if out else None


def compute_pt_adjusted_full(annuals_desc: list) -> dict | None:
    """Peters-Taylor (2017 JFE ★★★) adjusted ROIC with graceful R&D-missing
    fallback to Eisfeldt-Papanikolaou (2013 JF ★★★) organisation-capital-only.

    Reads ``Financial`` rows in DESCENDING fiscal_year order. Returns a dict:

      {
        "value": float | None,         # the adjusted ROIC (None if unavailable)
        "mode": "full" | "oc_only" | "unavailable",
        "components": {
          "knowledge_capital": float | None,
          "organisational_capital": float | None,
          "kc_series": [float, ...] | None,
          "oc_series": [float, ...],
          "n_annuals_used": int,
          "fiscal_years": [int, ...],
          "gaap_nopat": float | None,
          "adj_nopat": float | None,
          "adj_ic": float | None,
          "book_ic": float | None,
        },
        "data_gaps": [str, ...],
      }

    Crucially this does NOT add back SBC (per ADR-021 §4.1 — that would
    be management non-GAAP, rejected).

    Mode selection:
      • ``full``    — ≥2 annuals with both rd_expense AND sga_expense
      • ``oc_only`` — ≥2 annuals with sga_expense only; rd_expense missing
                      or zero across history. KC is set to 0; OC perpetual
                      inventory still builds. NOPAT add-back skipped.
      • ``unavailable`` — fewer than 2 annuals with sga_expense, or latest
                          operating_income / invested capital missing.
    """
    if not annuals_desc:
        return {
            "value": None, "mode": PT_MODE_UNAVAILABLE,
            "components": {}, "data_gaps": ["no annual rows available"],
        }

    # The TRUE latest annual — current-period balance sheet / income items
    # must always anchor here (see below), never to whichever year last
    # happened to disclose R&D separately. Companies routinely fold R&D
    # into OpEx after early filings; anchoring "latest" to a stale
    # rd_expense year silently ages the whole ROIC calc by however many
    # years disclosure has lapsed.
    true_latest = annuals_desc[0]

    all_chrono = list(reversed(annuals_desc))   # oldest → newest
    rd_valid = [
        a for a in all_chrono
        if a.rd_expense is not None and a.rd_expense > 0
    ]
    oc_valid = [a for a in all_chrono if a.sga_expense is not None]

    if len(rd_valid) >= 2:
        mode = PT_MODE_FULL
    elif len(oc_valid) >= 2:
        mode = PT_MODE_OC_ONLY
    else:
        return {
            "value": None, "mode": PT_MODE_UNAVAILABLE, "components": {},
            "data_gaps": [
                f"need ≥2 annuals with sga_expense; have {len(oc_valid)}",
            ],
        }
    if len(oc_valid) < 2:
        return {
            "value": None, "mode": PT_MODE_UNAVAILABLE, "components": {},
            "data_gaps": [
                f"need ≥2 annuals with sga_expense; have {len(oc_valid)}",
            ],
        }

    gaps: list[str] = []

    # ── Organisational capital perpetual inventory (always computed) ──
    # Independent of R&D availability — spans every year SG&A is disclosed,
    # through the TRUE latest year, not gated by whether that same year
    # also had R&D (Eisfeldt-Papanikolaou doesn't need R&D at all).
    oc_init = (
        _OC_SGA_FRACTION * (oc_valid[0].sga_expense or 0.0)
        / (_PT_GROWTH_RATE + _OC_DEPRECIATION_RATE)
    )
    oc_series: list[float] = [oc_init]
    for a in oc_valid[1:]:
        oc_prev = oc_series[-1]
        oc_t = (
            (1 - _OC_DEPRECIATION_RATE) * oc_prev
            + _OC_SGA_FRACTION * (a.sga_expense or 0.0)
        )
        oc_series.append(oc_t)
    organisational_capital = oc_series[-1]

    # ── Knowledge capital perpetual inventory (full mode only) ──
    # Built from the first year R&D was disclosed through the TRUE latest
    # year. Years where R&D disclosure has lapsed still depreciate the
    # existing stock (no new capitalisation) rather than freezing KC at
    # its last-disclosed value and pairing it with a much-later balance
    # sheet.
    if mode == PT_MODE_FULL:
        first_rd_idx = next(
            i for i, a in enumerate(all_chrono)
            if a.rd_expense is not None and a.rd_expense > 0
        )
        kc_chrono = all_chrono[first_rd_idx:]
        kc_init = (kc_chrono[0].rd_expense or 0.0) / (
            _PT_GROWTH_RATE + _KC_DEPRECIATION_RATE
        )
        kc_series: list[float] = [kc_init]
        for a in kc_chrono[1:]:
            kc_prev = kc_series[-1]
            kc_t = (1 - _KC_DEPRECIATION_RATE) * kc_prev + (a.rd_expense or 0.0)
            kc_series.append(kc_t)
        knowledge_capital = kc_series[-1]
        fiscal_years = [int(a.fiscal_year) for a in kc_chrono]
        n_annuals_used = len(kc_chrono)

        last_disclosed_rd_year = max(a.fiscal_year for a in rd_valid)
        if true_latest.fiscal_year != last_disclosed_rd_year:
            gaps.append(
                f"R&D not separately disclosed in XBRL since FY{last_disclosed_rd_year} "
                f"(latest annual is FY{true_latest.fiscal_year}) — knowledge capital "
                f"carried forward via depreciation-only (no new capitalisation) for "
                f"FY{last_disclosed_rd_year + 1}–FY{true_latest.fiscal_year}"
            )
    else:
        kc_series = None
        knowledge_capital = 0.0
        fiscal_years = [int(a.fiscal_year) for a in oc_valid]
        n_annuals_used = len(oc_valid)
        gaps.append(
            "rd_expense missing across history — knowledge-capital component "
            "skipped; using OC-only Eisfeldt-Papanikolaou (2013) adjustment"
        )

    # ── Adjusted NOPAT — anchored to the TRUE latest annual ──
    if true_latest.operating_income is None:
        return {
            "value": None, "mode": PT_MODE_UNAVAILABLE,
            "components": {
                "knowledge_capital": knowledge_capital,
                "organisational_capital": organisational_capital,
                "kc_series": kc_series, "oc_series": oc_series,
                "n_annuals_used": n_annuals_used,
                "fiscal_years": fiscal_years,
            },
            "data_gaps": gaps + ["operating_income missing on latest annual"],
        }

    gaap_nopat = true_latest.operating_income * (1 - _PT_TAX_RATE)
    if mode == PT_MODE_FULL and kc_series is not None:
        rd_t = true_latest.rd_expense or 0.0   # naturally 0 if not currently disclosed
        kc_prev_for_dep = kc_series[-2] if len(kc_series) >= 2 else kc_series[0]
        adj_nopat = gaap_nopat + rd_t - _KC_DEPRECIATION_RATE * kc_prev_for_dep
    else:
        # OC-only: no R&D add-back, no KC depreciation. NOPAT = GAAP NOPAT.
        # Eisfeldt-Papanikolaou's contribution is to the denominator only
        # (capitalised SG&A inflates invested capital).
        adj_nopat = gaap_nopat

    # ── Adjusted invested capital — anchored to the TRUE latest annual ──
    book_ic = (true_latest.total_equity or 0.0) + (true_latest.total_debt or 0.0)
    adj_ic = book_ic + knowledge_capital + organisational_capital
    if adj_ic <= 0:
        return {
            "value": None, "mode": PT_MODE_UNAVAILABLE,
            "components": {
                "knowledge_capital": knowledge_capital,
                "organisational_capital": organisational_capital,
                "kc_series": kc_series, "oc_series": oc_series,
                "n_annuals_used": n_annuals_used,
                "fiscal_years": fiscal_years,
                "book_ic": book_ic,
            },
            "data_gaps": gaps + ["invested capital ≤ 0"],
        }

    pt_roic = adj_nopat / adj_ic
    if pt_roic != pt_roic or pt_roic > 5.0 or pt_roic < -5.0:
        return {
            "value": None, "mode": PT_MODE_UNAVAILABLE,
            "components": {}, "data_gaps": gaps + ["non-finite or out-of-range ROIC"],
        }

    return {
        "value": pt_roic,
        "mode": mode,
        "components": {
            "knowledge_capital": knowledge_capital,
            "organisational_capital": organisational_capital,
            "kc_series": kc_series,
            "oc_series": oc_series,
            "n_annuals_used": n_annuals_used,
            "fiscal_years": fiscal_years,
            "gaap_nopat": gaap_nopat,
            "adj_nopat": adj_nopat,
            "adj_ic": adj_ic,
            "book_ic": book_ic,
        },
        "data_gaps": gaps,
    }


def compute_pt_for_ticker(ticker: str, *, persist: bool = True) -> dict | None:
    """Single-ticker Peters-Taylor compute helper for callers that don't want
    to run the bulk FundamentalsTask. Reads the latest 10 annuals from the
    warehouse, runs the perpetual-inventory build, and (when ``persist=True``)
    writes the result back to ``Company.pt_adjusted_roic`` /
    ``Company.pt_adjusted_roic_fetched_at``.

    Returns the same rich dict as ``compute_pt_adjusted_full`` plus a ``ticker``
    key, or ``None`` if the company isn't in the warehouse.

    Used by deepdive/orchestrator.py during Phase-1 data prep so the dive
    always has fresh non-GAAP figures, regardless of when the bulk
    FundamentalsTask last ran.
    """
    from datetime import datetime

    from data.db import get_session
    from data.models.schema import Company, Financial

    with get_session() as db:
        company = (
            db.execute(
                select(Company).where(Company.ticker == ticker.upper())
            ).scalar_one_or_none()
        )
        if not company:
            return None
        annuals = db.execute(
            select(Financial)
            .where(Financial.company_id == company.id)
            .where(Financial.period == "annual")
            .order_by(Financial.fiscal_year.desc())
            .limit(10)
        ).scalars().all()
        result = compute_pt_adjusted_full(annuals)
        result["ticker"] = ticker.upper()
        if persist and result.get("value") is not None:
            from config.source_tags import SELF_COMPUTED as _SRC_SC
            company.pt_adjusted_roic = result["value"]
            company.pt_adjusted_roic_fetched_at = datetime.utcnow()
            company.pt_adjusted_roic_source = _SRC_SC
        return result


__all__ = [
    "FundamentalsTask",
    "compute_pt_adjusted_full",
    "compute_pt_for_ticker",
    "PT_MODE_FULL",
    "PT_MODE_OC_ONLY",
    "PT_MODE_UNAVAILABLE",
]
