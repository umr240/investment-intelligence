"""EsefSource — Tier-1B filing-grade fundamentals for EU/EEA issuers.

ESEF (European Single Electronic Format) has been mandatory for EU/EEA-listed
annual financial reports since FY2020: issuers file inline-XBRL tagged against
the IFRS taxonomy with their national OAM. XBRL International aggregates a
large share of those filings at ``filings.xbrl.org`` and republishes each as an
**xBRL-JSON (OIM) fact document** — machine-readable, validation-scored, and
free with no API key.

That makes this adapter Tier-1B: audited regulator-filed numbers, the same
class of source as SEC companyfacts, as opposed to the yfinance Tier-3 scrape.

── Resolution chain ──────────────────────────────────────────────────────
    ticker (BONEX.ST)
      → Jurisdiction (SE / ESEF / SEK)            [data/sources/jurisdiction.py]
      → legal name (Company.name, else yfinance)
      → LEI via GLEIF, COUNTRY-SCOPED             [api.gleif.org, free]
      → filing index for that LEI                 [filings.xbrl.org]
      → xBRL-JSON facts per filing
      → EdgarFinancialRow per fiscal year

Each annual filing carries the current year AND its comparative, so N filings
yield up to N+1 fiscal years. Restatements are handled by preferring the fact
from the NEWEST filing that covers a given year.

── The wrong-company guard ───────────────────────────────────────────────
The ``VHI`` → Valhi collision that motivated ADR-039 has an exact analogue
here: GLEIF name search is fuzzy, and an unscoped query returns unrelated
entities (measured: an empty ISIN filter returned a German rowing club). So
resolution REQUIRES (a) the jurisdiction's country as a hard filter, (b) an
ACTIVE registration, and (c) an unambiguous winner — exact normalised-name
match, or exactly one active candidate. Anything else returns a data gap and
NO rows. Guessing which "AUTO1 Group" entity is the listed one is precisely
the failure this codebase refuses to make.

── Honest limits (surfaced as gaps, never silently) ──────────────────────
  * Index lag is per-country. Sweden's newest indexed period_end is
    2024-12-31 as of 2026-08-16, so a FY2025 figure is NOT available here and
    the chain falls back to yfinance for that year. Gaps name the boundary.
  * ESEF Phase-1 tagging covers the PRIMARY STATEMENTS in detail; notes are
    block-tagged. Segment data, customer concentration and insider dealings
    are NOT available — those remain data gaps exactly as they are today.
  * Company-specific extension concepts are not interpreted (see
    ``esef_concepts`` docstring).

Zero LLM involvement — deterministic HTTP + JSON parsing, per CLAUDE.md.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from data.sources.base import (
    TAG_ESEF,
    TIER_ESEF_IXBRL,
    FundamentalsResult,
    register,
)
from data.sources.esef_concepts import (
    ALLOWED_DIMENSION_KEYS,
    CONCEPT_MAP,
    SHARE_CONCEPTS,
    SUM_CONCEPT_MAP,
)
from data.sources.jurisdiction import SRC_ESEF, jurisdiction_for

if TYPE_CHECKING:
    from data.models.schema import Company

logger = logging.getLogger(__name__)

_GLEIF_API = "https://api.gleif.org/api/v1/lei-records"
_FILINGS_API = "https://filings.xbrl.org/api"
_FILINGS_BASE = "https://filings.xbrl.org"

_TIMEOUT = httpx.Timeout(60.0, connect=20.0)

# An annual period is a duration of roughly one year. Interim/quarterly
# durations in the same document must not be mistaken for the fiscal year.
_ANNUAL_MIN_DAYS = 330
_ANNUAL_MAX_DAYS = 400

# Legal-form suffixes stripped before name matching. "BONESUPPORT HOLDING AB"
# vs "Bonesupport Holding AB (publ)" must compare equal.
_LEGAL_FORMS = (
    "aktiebolag", "publ", "ab", "oyj", "abp", "asa", "as", "a/s", "nv", "n.v.",
    "bv", "b.v.", "se", "plc", "sa", "s.a.", "spa", "s.p.a.", "ag", "oy",
    "group", "holding", "holdings", "corporation", "corp", "inc", "ltd",
)


def _normalise_name(name: str) -> str:
    """Lowercase, strip punctuation and legal-form tokens, collapse spaces."""
    s = re.sub(r"[^\w\s]", " ", (name or "").lower())
    tokens = [t for t in s.split() if t not in _LEGAL_FORMS]
    return " ".join(tokens)


def _user_agent() -> str:
    try:
        from config.settings import get_settings
        ident = get_settings().edgar_identity
    except Exception:  # noqa: BLE001 — settings optional at this layer
        ident = ""
    return f"investment-intelligence/1.0 ({ident})" if ident else "investment-intelligence/1.0"


# ── Period handling ───────────────────────────────────────────────────────
# xBRL OIM represents an instant at 2024-12-31 as "2025-01-01T00:00:00" and a
# duration as the half-open interval [start, end). So the reportable period end
# is always `end - 1 day` for both shapes. Verified against BONESUPPORT FY2024:
# instant 2025-01-01 → total_assets 879,691,000 (the 2024-12-31 balance sheet).

def _parse_instant(token: str) -> date | None:
    try:
        return (datetime.fromisoformat(token.replace("Z", "+00:00")).date()
                - timedelta(days=1))
    except (ValueError, TypeError):
        return None


def _parse_period(period: str) -> tuple[date | None, date | None, bool]:
    """→ (start, end, is_duration). ``end`` is the inclusive reportable date."""
    if "/" in period:
        raw_start, raw_end = period.split("/", 1)
        try:
            start = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            start = None
        return start, _parse_instant(raw_end), True
    return None, _parse_instant(period), False


def _is_annual(start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return False
    return _ANNUAL_MIN_DAYS <= (end - start).days + 1 <= _ANNUAL_MAX_DAYS


# ── Fact extraction ───────────────────────────────────────────────────────

def _collect_facts(payload: dict[str, Any]) -> tuple[
    dict[int, dict[str, float]], dict[int, dict[str, float]], dict[int, date], set[str]
]:
    """Split a filing's facts into per-fiscal-year duration and instant maps.

    Returns (duration_by_year, instant_by_year, period_end_by_year, currencies).
    Only CONSOLIDATED facts survive — anything carrying a segment/member axis
    is dropped (``ALLOWED_DIMENSION_KEYS``).
    """
    durations: dict[int, dict[str, float]] = {}
    instants: dict[int, dict[str, float]] = {}
    period_ends: dict[int, date] = {}
    currencies: set[str] = set()

    for fact in payload.get("facts", {}).values():
        dims = fact.get("dimensions") or {}
        if not ALLOWED_DIMENSION_KEYS.issuperset(dims):
            continue  # segment / class-of-share breakdown — not a total
        concept, period, unit = dims.get("concept"), dims.get("period"), dims.get("unit")
        if not concept or not period or not unit:
            continue
        # Compound units ("iso4217:SEK/xbrli:shares") are per-share measures —
        # legitimate values (EPS), but their numerator must NOT be mistaken for
        # the filing's reporting currency.
        is_per_share = "/" in unit
        is_monetary = unit.startswith("iso4217:") and not is_per_share
        is_shares = unit in ("shares", "xbrli:shares")
        if not (is_monetary or is_shares or is_per_share):
            continue
        try:
            value = float(fact["value"])
        except (KeyError, TypeError, ValueError):
            continue

        start, end, is_duration = _parse_period(period)
        if end is None:
            continue
        if is_duration and not _is_annual(start, end):
            continue  # interim/quarterly duration — not the fiscal year

        year = end.year
        bucket = durations if is_duration else instants
        # setdefault: first writer wins WITHIN one filing (facts are unique per
        # concept+period there); across filings, the caller applies newest-first.
        bucket.setdefault(year, {}).setdefault(concept, value)
        if is_monetary:
            currencies.add(unit.split(":", 1)[-1])
        prev = period_ends.get(year)
        if prev is None or end > prev:
            period_ends[year] = end

    return durations, instants, period_ends, currencies


def _resolve_field(concepts: dict[str, float], synonyms: tuple[str, ...]) -> float | None:
    for concept in synonyms:
        if concept in concepts:
            return concepts[concept]
    return None


def _sum_field(concepts: dict[str, float], components: tuple[str, ...]) -> float | None:
    present = [concepts[c] for c in components if c in concepts]
    return sum(present) if present else None


def _build_row(
    ticker: str, year: int, duration: dict[str, float], instant: dict[str, float],
    period_end: date | None, currency: str, accession: str,
) -> Any:
    """Map one fiscal year's resolved concepts onto an EdgarFinancialRow."""
    from data.edgar_fetcher import EdgarFinancialRow

    merged = {**instant, **duration}  # duration wins on the rare overlap

    row = EdgarFinancialRow(
        ticker=ticker,
        fiscal_year=year,
        period="annual",
        source="esef",
        accession_number=accession,
        period_end_date=period_end,
        filed_date=None,
    )
    for field_name, synonyms in CONCEPT_MAP.items():
        value = _resolve_field(merged, synonyms)
        if value is not None:
            setattr(row, field_name, value)
    for field_name, components in SUM_CONCEPT_MAP.items():
        value = _sum_field(merged, components)
        if value is not None:
            setattr(row, field_name, value)

    shares = _resolve_field(merged, SHARE_CONCEPTS)
    if shares is not None:
        row.shares_outstanding = shares
    elif row.eps_basic:
        # ESEF Phase-1 tags the primary statements; share counts frequently
        # live in the block-tagged notes and so are absent (BONESUPPORT tags
        # EPS but never a share count). Weighted-average shares are still
        # RECOVERABLE from two facts that ARE tagged: ProfitLoss / BasicEPS.
        #
        # This is derivation, not fabrication — ADR-033 "compute, don't pull".
        # Both inputs are filing-grade and the identity is definitional. It
        # matters because F7 discards any annual row lacking shares
        # outstanding, so without this the whole framework is UNEVAL on most
        # European filers.
        #
        # Caveat kept honest: this yields the WEIGHTED-AVERAGE share count
        # used for EPS, not the period-end count. For F7's valuation-history
        # z-scores (EV/Revenue, P/B) that is an accepted proxy; for precise
        # dilution work it is not, hence the separate _source tag.
        basis = row.net_income
        if basis is not None and row.eps_basic != 0:
            derived = basis / row.eps_basic
            if derived > 0:
                row.shares_outstanding = derived

    # ── Derivations, mirroring the EDGAR/yfinance paths exactly ──
    if row.gross_profit is None and row.revenue is not None and row.cost_of_revenue is not None:
        row.gross_profit = row.revenue - abs(row.cost_of_revenue)
    if row.gross_margin is None and row.gross_profit is not None and row.revenue:
        row.gross_margin = row.gross_profit / row.revenue
    if row.capex is not None:
        row.capex = abs(row.capex)  # positive magnitude, per edgar_companyfacts
    if (row.free_cash_flow is None and row.operating_cash_flow is not None
            and row.capex is not None):
        row.free_cash_flow = row.operating_cash_flow - abs(row.capex)
    # R&D disclosure state: ESEF tags R&D explicitly or not at all — there is
    # no tax-footnote inference path here (that is a 10-K text pattern).
    if row.rd_expense is not None:
        row.rd_disclosure_state = "disclosed_exact"

    return row


# ── Remote lookups (all I/O lives below this line) ────────────────────────

def _name_variants(name: str) -> list[str]:
    """Progressively shorter query forms, longest first.

    GLEIF's ``filter[entity.legalName]`` is a LEADING-SUBSTRING match against
    the exact registered string, not a fuzzy search. Measured 2026-08-16:

        "Bonesupport Holding AB (publ)" → 0 hits   (registered without "(publ)")
        "Bonesupport Holding AB"       → 1 hit
        "Dometic Group AB (publ)"      → 1 hit     (registered WITH "(publ)")
        "Thule Group AB (publ)"        → 0 hits    (registered without)
        "ASML Holding N.V."            → 1 hit
        "ASML Holding NV"              → 0 hits    (punctuation is significant)

    Exchange listing names and GLEIF legal names therefore disagree in both
    directions, and no single query form wins. So we walk from the most
    specific form down, and stop at the first that returns anything — then the
    caller's unambiguity guard decides whether the hit is trustworthy.
    """
    variants: list[str] = []

    def _add(candidate: str) -> None:
        candidate = " ".join(candidate.split()).strip(" ,.-")
        if candidate and candidate not in variants:
            variants.append(candidate)

    _add(name)
    _add(re.sub(r"\s*\([^)]*\)", " ", name))  # drop "(publ)", "(the)", ...

    # Strip trailing legal-form tokens one at a time: "X Holding AB" → "X Holding" → "X".
    tokens = re.sub(r"\s*\([^)]*\)", " ", name).split()
    while len(tokens) > 1 and tokens[-1].lower().strip(".,") in _LEGAL_FORMS:
        tokens = tokens[:-1]
        _add(" ".join(tokens))
    if len(tokens) > 1:
        _add(tokens[0])
    return variants


def _gleif_lookup(name: str, country: str, client: httpx.Client) -> tuple[str | None, str]:
    """Resolve a legal name + country to a single LEI. → (lei, note).

    Returns ``(None, reason)`` whenever the match is not unambiguous. There is
    no "best guess" branch by design — an ambiguous identity produces a data
    gap and zero rows, never a plausible-looking wrong company.
    """
    target = _normalise_name(name)
    tried: list[str] = []

    for variant in _name_variants(name):
        tried.append(variant)
        try:
            resp = client.get(_GLEIF_API, params={
                "filter[entity.legalName]": variant,
                "filter[entity.legalAddress.country]": country,
                "page[size]": 25,
            })
        except httpx.HTTPError as exc:
            return None, f"GLEIF unreachable ({exc.__class__.__name__})"
        if resp.status_code != 200:
            return None, f"GLEIF HTTP {resp.status_code}"

        active = [
            r for r in resp.json().get("data", [])
            if r.get("attributes", {}).get("entity", {}).get("status") == "ACTIVE"
        ]
        if not active:
            continue

        # Guard 1 — exact match on the NORMALISED original name wins outright.
        exact = [
            r for r in active
            if _normalise_name(r["attributes"]["entity"]["legalName"]["name"]) == target
        ]
        if len(exact) == 1:
            return exact[0]["attributes"]["lei"], ""
        # Guard 2 — a single active candidate in-country is unambiguous.
        if len(active) == 1:
            return active[0]["attributes"]["lei"], ""
        # Guard 3 — several plausible entities (operating co vs holding co vs
        # services sub). Refuse. This is the VHI→Valhi lesson generalised.
        names = ", ".join(
            r["attributes"]["entity"]["legalName"]["name"] for r in active[:4]
        )
        return None, (
            f"ambiguous GLEIF match for {name!r} in {country} "
            f"({len(active)} active: {names}) — refusing to guess"
        )

    return None, (
        f"no ACTIVE GLEIF entity in {country} matching {name!r} "
        f"(tried {len(tried)} name forms)"
    )


def _list_filings(lei: str, client: httpx.Client) -> tuple[list[dict[str, Any]], str]:
    """Annual ESEF filings for an LEI, NEWEST FIRST."""
    try:
        resp = client.get(f"{_FILINGS_API}/entities/{lei}/filings",
                          params={"page[size]": 40})
    except httpx.HTTPError as exc:
        return [], f"filings.xbrl.org unreachable ({exc.__class__.__name__})"
    if resp.status_code != 200:
        return [], f"filings.xbrl.org HTTP {resp.status_code}"

    out: list[dict[str, Any]] = []
    today = date.today().isoformat()
    for item in resp.json().get("data", []):
        attrs = item.get("attributes", {})
        json_url, period_end = attrs.get("json_url"), attrs.get("period_end")
        if not json_url or not period_end:
            continue
        # Guard against index typos — a Swedish filing indexed at period_end
        # 2029-05-01 exists today. A future period_end is not a real filing.
        if period_end > today:
            continue
        out.append({
            "period_end": period_end,
            "json_url": json_url,
            "error_count": attrs.get("error_count"),
            "fxo_id": attrs.get("fxo_id") or "",
        })
    out.sort(key=lambda f: f["period_end"], reverse=True)
    return out, ""


def _fetch_sync(ticker: str, requirement: Any, company_name: str | None,
                cached_lei: str | None) -> FundamentalsResult:
    jur = jurisdiction_for(ticker)
    result = FundamentalsResult(
        ticker=ticker, source_tier=TAG_ESEF, reporting_currency=jur.currency,
    )
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}

    with httpx.Client(headers=headers, timeout=_TIMEOUT, follow_redirects=True) as client:
        # ── 1. LEI ──
        lei = cached_lei
        if not lei:
            name = company_name or _yfinance_name(ticker)
            if not name:
                result.gaps.append(
                    f"{ticker}: no legal name available to resolve an LEI — "
                    f"ESEF lookup needs a company name"
                )
                return result
            lei, note = _gleif_lookup(name, jur.country, client)
            if not lei:
                result.gaps.append(f"{ticker}: ESEF unavailable — {note}")
                return result
        result.metadata["lei"] = lei

        # ── 2. Filing index ──
        filings, note = _list_filings(lei, client)
        if not filings:
            result.gaps.append(
                f"{ticker}: no ESEF filing indexed for LEI {lei}"
                + (f" ({note})" if note else
                   f" — {jur.country} issuers may not syndicate to filings.xbrl.org")
            )
            return result

        # ── 3. Fetch newest-first until the year budget is covered ──
        # Each filing yields ~2 fiscal years (current + comparative), so
        # ceil(years/2)+1 filings is the honest fetch budget. Lazy by
        # construction: nothing beyond what DataRequirement asked for.
        want_years = max(int(getattr(requirement, "annual_years", 5) or 5), 2)
        budget = min(len(filings), want_years // 2 + 2)

        durations: dict[int, dict[str, float]] = {}
        instants: dict[int, dict[str, float]] = {}
        period_ends: dict[int, date] = {}
        currencies: set[str] = set()
        accessions: dict[int, str] = {}

        for filing in filings[:budget]:
            url = _FILINGS_BASE + filing["json_url"]
            try:
                resp = client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                result.gaps.append(
                    f"{ticker}: ESEF filing {filing['period_end']} unreadable "
                    f"({exc.__class__.__name__})"
                )
                continue

            f_dur, f_inst, f_ends, f_cur = _collect_facts(payload)
            currencies |= f_cur
            # Merge PER CONCEPT, not per year. Newest filing still wins on any
            # concept it tagged (restatements are respected), but an older
            # filing can still contribute concepts the newer one's COMPARATIVE
            # column omitted. Comparatives are routinely tagged less
            # completely than the current year — merging at year granularity
            # silently dropped ifrs-full:Assets for every prior period.
            for year, concepts in f_dur.items():
                target = durations.setdefault(year, {})
                for concept, value in concepts.items():
                    target.setdefault(concept, value)
                accessions.setdefault(year, filing["fxo_id"])
            for year, concepts in f_inst.items():
                target = instants.setdefault(year, {})
                for concept, value in concepts.items():
                    target.setdefault(concept, value)
            for year, end in f_ends.items():
                period_ends.setdefault(year, end)

        if not durations and not instants:
            result.gaps.append(
                f"{ticker}: ESEF filings found but no consolidated facts parsed "
                f"(unexpected taxonomy shape) — falling back"
            )
            return result

        # ── 4. Currency ──
        if len(currencies) == 1:
            result.reporting_currency = currencies.pop()
        elif len(currencies) > 1:
            # Pick the jurisdiction default if present, else flag.
            if jur.currency in currencies:
                result.reporting_currency = jur.currency
            else:
                result.reporting_currency = sorted(currencies)[0]
            result.gaps.append(
                f"{ticker}: ESEF filing reports multiple currencies "
                f"({', '.join(sorted(currencies))}) — using {result.reporting_currency}"
            )
        if result.reporting_currency != jur.currency:
            # Not an error: e.g. Nordic Semiconductor (.OL) reports in USD.
            result.gaps.append(
                f"{ticker}: reporting currency {result.reporting_currency} differs "
                f"from {jur.venue} default {jur.currency} — using the filing's unit"
            )

        # ── 5. Build rows ──
        rows = []
        for year in sorted(set(durations) | set(instants), reverse=True):
            row = _build_row(
                ticker, year, durations.get(year, {}), instants.get(year, {}),
                period_ends.get(year), result.reporting_currency,
                accessions.get(year, ""),
            )
            if row.revenue is None and row.total_assets is None:
                continue  # nothing usable for this year
            rows.append(row)

        result.financials = rows[:want_years] if want_years else rows

        # ── 6. Honest coverage reporting ──
        if result.financials:
            # IFRS permits expense analysis BY FUNCTION (cost of sales →
            # gross profit) or BY NATURE (materials / employee benefits /
            # depreciation, with NO gross-profit line). Kempower and many
            # Nordic industrials use by-nature, so a missing gross margin is a
            # presentation choice, not a fetch failure — say which, because a
            # bare "gross_profit: None" reads like a bug and invites someone
            # to "fix" it with a fabricated subtraction.
            latest = result.financials[0]
            if latest.revenue is not None and latest.gross_profit is None:
                result.gaps.append(
                    f"{ticker}: no gross profit — filer presents expenses BY NATURE "
                    f"(IAS 1.99 permits this); gross-margin frameworks are UNEVAL, "
                    f"not zero"
                )
            if latest.rd_expense is None:
                result.gaps.append(
                    f"{ticker}: no ifrs-full:ResearchAndDevelopmentExpense tag — "
                    f"R&D either not separately disclosed or carried in a "
                    f"company-specific extension concept (not interpreted)"
                )
            newest = max(r.fiscal_year for r in result.financials)
            this_year = date.today().year
            if newest < this_year - 1:
                result.gaps.append(
                    f"{ticker}: newest ESEF filing covers FY{newest}; "
                    f"FY{newest + 1}+ not yet indexed for {jur.country} "
                    f"(index lag) — recent periods unavailable at Tier-1B"
                )
            if len(result.financials) < 2:
                result.gaps.append(
                    f"{ticker}: only {len(result.financials)} ESEF annual period(s) "
                    f"— YoY frameworks (F1) will degrade"
                )
        else:
            result.gaps.append(f"{ticker}: ESEF facts parsed but no usable annual rows")

    _supplement_with_yfinance(ticker, result)
    result.fx_rate_to_usd = _fx_to_usd(result.reporting_currency)
    return result


def _supplement_with_yfinance(ticker: str, result: FundamentalsResult) -> None:
    """Fill what ESEF structurally cannot supply, WITHOUT downgrading it.

    ESEF is an ANNUAL-REPORT regime. There are no quarterly ESEF filings — EU
    interim reports are not iXBRL-tagged. So an ESEF-only ticker persists zero
    quarterly rows, and every framework declaring ``quarterly_count`` is marked
    unfeasible. Filing-grade annuals that no framework can consume are not a
    win.

    The fix is a HYBRID, not a fallback: ESEF owns the annual periods it
    covers; yfinance contributes (a) quarterly rows, and (b) annual years newer
    than the index reaches (Sweden lags ~1.5yr as of 2026-08). Provenance stays
    honest at ROW granularity — each row keeps ``source='esef'`` or
    ``source='yfinance'``, so a reader can always tell which number is
    filing-grade. This is the "screening fidelity is not thesis fidelity"
    separation made concrete: a normalised quarterly is fine for momentum;
    a thesis number should come off the annual filing.

    ESEF rows are NEVER overwritten — an ESEF-covered fiscal year wins over
    yfinance's version of the same year (ADR-033 source hierarchy: the
    unofficial scraper never overrides a regulator filing).
    """
    esef_years = {r.fiscal_year for r in result.financials}
    try:
        from data.sources.yfinance_fund import _fetch_sync as _yf_fetch
        supplement = _yf_fetch(ticker)
    except Exception as exc:  # noqa: BLE001 — supplementation is best-effort
        result.gaps.append(
            f"{ticker}: quarterly supplementation unavailable ({exc.__class__.__name__}) "
            f"— ESEF annual rows only; quarterly-dependent frameworks will not run"
        )
        return

    added_quarters = 0
    added_annuals: list[int] = []
    for row in supplement.financials:
        if row.period == "annual":
            if row.fiscal_year in esef_years:
                continue  # regulator filing wins — never overwritten
            added_annuals.append(row.fiscal_year)
        else:
            added_quarters += 1
        result.financials.append(row)

    if added_quarters:
        result.gaps.append(
            f"{ticker}: {added_quarters} quarterly period(s) supplemented from "
            f"yfinance (Tier-3) — ESEF has no quarterly regime; annual rows "
            f"remain filing-grade"
        )
    else:
        result.gaps.append(
            f"{ticker}: no quarterly data from any source — quarterly-dependent "
            f"frameworks (F1-F6) will be UNEVAL"
        )
    if added_annuals:
        result.gaps.append(
            f"{ticker}: FY{'/'.join(str(y) for y in sorted(added_annuals, reverse=True))} "
            f"sourced from yfinance (Tier-3) — beyond ESEF index coverage; "
            f"treat as triage-grade, not thesis-grade"
        )


def _yfinance_name(ticker: str) -> str | None:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return info.get("longName") or info.get("shortName")
    except Exception as exc:  # noqa: BLE001 — name lookup is best-effort
        logger.debug("yfinance name lookup failed for %s: %s", ticker, exc)
        return None


def _fx_to_usd(currency: str) -> float | None:
    if currency == "USD":
        return 1.0
    from data.sources.yfinance_fund import _fetch_fx_to_usd
    return _fetch_fx_to_usd(currency)


class EsefSource:
    """Tier-1B EU/EEA adapter. See module docstring."""

    name = SRC_ESEF
    tier = TIER_ESEF_IXBRL
    available = True

    def supports(self, ticker: str, company: Company | None) -> bool:
        # Cheap, no I/O: the jurisdiction table decides. A country whose OAM
        # does not syndicate (DE, IE) has no 'esef' in its chain, so this is
        # False for them even though their regime IS ESEF.
        return SRC_ESEF in jurisdiction_for(ticker).source_chain

    async def fetch(
        self, ticker: str, requirement: Any, *, force_refresh: bool = False
    ) -> FundamentalsResult:
        company_name, cached_lei = _company_hints(ticker)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: _fetch_sync(ticker, requirement, company_name, cached_lei)
        )


def _company_hints(ticker: str) -> tuple[str | None, str | None]:
    """Read the cached name + LEI off the Company row, if one exists.

    Caching the LEI turns every subsequent refresh into a two-hop fetch
    (index + filings) instead of three — GLEIF is only paid once per company.
    """
    try:
        from data.db import get_session
        from data.models.schema import Company
        with get_session() as session:
            company = session.query(Company).filter(Company.ticker == ticker).first()
            if company is None:
                return None, None
            name = company.name
            lei = getattr(company, "lei", None)
            # `_ensure_company_row` seeds name=ticker as a placeholder before
            # any snapshot lands. Treating "BONEX.ST" as a legal name sends a
            # ticker string to GLEIF and guarantees a miss — mirror the
            # placeholder test pipeline._persist_yfinance_snapshot already uses.
            if not name or str(name) == ticker:
                return None, (str(lei) if lei else None)
            return str(name), (str(lei) if lei else None)
    except Exception as exc:  # noqa: BLE001 — DB optional at this layer
        logger.debug("company hints unavailable for %s: %s", ticker, exc)
        return None, None


register(EsefSource())
