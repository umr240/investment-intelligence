"""Jurisdiction registry — ticker suffix → country / region / filing regime.

This module is the SINGLE SOURCE OF TRUTH for "what market is this ticker
from, and which fundamentals sources can serve it, in what order of fidelity".

Before this module, ``resolve_source`` held two flat frozensets
(``_CANADIAN_SUFFIXES`` / ``_FOREIGN_SUFFIXES``) and a hand-written if-ladder.
That worked for three sources but does not express what a fourth needs to know:
a Swedish ticker and a German ticker are BOTH ``.EU``-regime ESEF filers de
jure, yet only one of them is actually reachable — and encoding that as another
``if`` is how the ladder ADR-039 §1.2 warned about grows back.

So the routing knowledge lives here as DATA (one row per market), and
``resolve_source`` becomes a three-line walk over ``Jurisdiction.source_chain``.
Adding a market = adding a row. Adding a source = adding a name to some chains
plus one adapter module. Neither re-opens the resolver (Open/Closed).

Mental models: ``single_source_of_truth`` (routing lives once),
``illegal_states_unrepresentable`` (a suffix maps to a typed Jurisdiction, not
a bare string compared against ad-hoc sets), ``parse_dont_validate`` (suffix is
parsed into a Jurisdiction once, at the edge), ``chestertons_fence`` (the
US-default and BRK.B behaviour of the old sets is preserved verbatim — see
``UNKNOWN_SUFFIX_DEFAULTS_TO_US``).

NO I/O happens in this module. It is a lookup table and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Regions ───────────────────────────────────────────────────────────────
# Coarse buckets used for reporting/grouping, NOT for routing. Routing is
# per-jurisdiction via source_chain — two countries in the same region can
# legitimately have different chains (see DE vs SE below).
REGION_NORTH_AMERICA = "north_america"
REGION_EU_EEA = "eu_eea"
REGION_UK = "uk"
REGION_APAC = "apac"
REGION_MEA = "mea"

# ── Filing regimes (what the issuer is legally required to file) ──────────
# NOTE: regime is a statement about REGULATION, not about REACHABILITY.
# Germany's regime is genuinely ESEF; its filings are simply not syndicated to
# the index we can read. Keeping those two facts in separate fields is the
# whole point — conflating them is what produces "it should work" bug reports.
REGIME_SEC_XBRL = "sec_xbrl"       # US — SEC EDGAR companyfacts
REGIME_ESEF = "esef"               # EU/EEA — ESEF iXBRL, mandatory FY2020+
REGIME_SEDAR = "sedar"             # Canada — SEDAR+, no XBRL mandate
REGIME_UK_CH = "uk_companies_house"  # UK — Companies House iXBRL accounts
REGIME_NONE = "none"               # No machine-readable structured regime

# ── Adapter names (must match FundamentalsSource.name) ────────────────────
SRC_SEC = "sec_edgar"
SRC_ESEF = "esef"
SRC_SEDAR = "sedar_plus"
SRC_YFINANCE = "yfinance"
SRC_COMPANIES_HOUSE = "companies_house"  # not built — reserved, see UK rows

# Unknown suffixes default to the US chain. This preserves the pre-existing
# behaviour exactly: bare tickers AND US class-share dotted tickers (BRK.B,
# BF.B) route to SEC. Demoting an unrecognised suffix to Tier-3 would be a
# silent fidelity regression for US filers — the anti-degradation guard.
UNKNOWN_SUFFIX_DEFAULTS_TO_US = True


@dataclass(frozen=True)
class Jurisdiction:
    """One listing venue's routing facts."""

    suffix: str                    # Yahoo-style exchange suffix, "" for US
    mic: str                       # ISO-10383 Market Identifier Code
    country: str                   # ISO-3166-1 alpha-2
    region: str                    # REGION_*
    currency: str                  # expected reporting currency, ISO-4217
    regime: str                    # REGIME_* — de jure filing obligation
    source_chain: tuple[str, ...]  # adapter names, HIGHEST FIDELITY FIRST
    venue: str = ""                # human label for CLI/methodology panels
    note: str = ""                 # why the chain looks like it does

    @property
    def structured_reachable(self) -> bool:
        """True when a filing-grade (non-yfinance) source is in the chain.

        This is the honest answer to "can we get filing-grade numbers here",
        as distinct from ``regime`` which only says what the issuer must file.
        """
        return any(s != SRC_YFINANCE for s in self.source_chain)


def _esef(suffix: str, mic: str, country: str, currency: str, venue: str,
          *, indexed: bool = True, note: str = "") -> Jurisdiction:
    """EU/EEA row. ``indexed=False`` means the country's OAM does not syndicate
    to filings.xbrl.org, so the ESEF adapter is left OUT of the chain rather
    than being called and guaranteed to fail (measured 2026-08-16, §census)."""
    return Jurisdiction(
        suffix=suffix, mic=mic, country=country, region=REGION_EU_EEA,
        currency=currency, regime=REGIME_ESEF, venue=venue,
        source_chain=(SRC_ESEF, SRC_YFINANCE) if indexed else (SRC_YFINANCE,),
        note=note,
    )


def _plain(suffix: str, mic: str, country: str, region: str, currency: str,
           venue: str, regime: str = REGIME_NONE, note: str = "") -> Jurisdiction:
    """Venue with no reachable structured source — yfinance Tier-3 only."""
    return Jurisdiction(
        suffix=suffix, mic=mic, country=country, region=region,
        currency=currency, regime=regime, venue=venue,
        source_chain=(SRC_YFINANCE,), note=note,
    )


# ── The registry ──────────────────────────────────────────────────────────
# Ordering within this literal is cosmetic; lookup is by dict key.
_JURISDICTIONS: dict[str, Jurisdiction] = {j.suffix: j for j in (

    # ── United States — the bare-ticker default ──────────────────────────
    Jurisdiction(
        suffix="", mic="XNYS", country="US", region=REGION_NORTH_AMERICA,
        currency="USD", regime=REGIME_SEC_XBRL, venue="NYSE / Nasdaq",
        source_chain=(SRC_SEC, SRC_YFINANCE),
        note="SEC EDGAR companyfacts — Tier-1A, ~10yr depth.",
    ),

    # ── Canada — SEDAR+ scaffolded (ADR-039 Phase C), falls to yfinance ───
    Jurisdiction(suffix="TO", mic="XTSE", country="CA", region=REGION_NORTH_AMERICA,
                 currency="CAD", regime=REGIME_SEDAR, venue="Toronto Stock Exchange",
                 source_chain=(SRC_SEDAR, SRC_YFINANCE),
                 note="SEDAR+ has no public API; adapter is an unavailable scaffold "
                      "so the chain falls through to yfinance Tier-3."),
    Jurisdiction(suffix="V", mic="XTSX", country="CA", region=REGION_NORTH_AMERICA,
                 currency="CAD", regime=REGIME_SEDAR, venue="TSX Venture",
                 source_chain=(SRC_SEDAR, SRC_YFINANCE)),
    Jurisdiction(suffix="CN", mic="XCNQ", country="CA", region=REGION_NORTH_AMERICA,
                 currency="CAD", regime=REGIME_SEDAR, venue="Canadian Securities Exchange",
                 source_chain=(SRC_SEDAR, SRC_YFINANCE)),
    Jurisdiction(suffix="NE", mic="NEOE", country="CA", region=REGION_NORTH_AMERICA,
                 currency="CAD", regime=REGIME_SEDAR, venue="NEO Exchange",
                 source_chain=(SRC_SEDAR, SRC_YFINANCE)),

    # ── EU/EEA — ESEF reachable via filings.xbrl.org ──────────────────────
    # Verified live 2026-08-16: filing counts + newest indexed period_end.
    _esef("ST", "XSTO", "SE", "SEK", "Nasdaq Stockholm",
          note="1,415 filings indexed; newest period_end 2024-12-31 (~1.5yr lag — "
               "most recent FY falls back to yfinance)."),
    _esef("HE", "XHEL", "FI", "EUR", "Nasdaq Helsinki",
          note="1,168 filings; index current to 2026-01."),
    _esef("OL", "XOSL", "NO", "NOK", "Oslo Bors",
          note="958 filings; index current to 2025-03. NB: several Norwegian "
               "issuers report in USD — trust the filing's unit, not the suffix."),
    _esef("CO", "XCSE", "DK", "DKK", "Nasdaq Copenhagen",
          note="2,126 filings; index current to 2026-06 — best-covered market."),
    _esef("IC", "XICE", "IS", "ISK", "Nasdaq Iceland", note="119 filings."),
    _esef("AS", "XAMS", "NL", "EUR", "Euronext Amsterdam",
          note="656 filings; index current to 2026-03."),
    _esef("PA", "XPAR", "FR", "EUR", "Euronext Paris",
          note="1,178 filings; index current."),
    _esef("BR", "XBRU", "BE", "EUR", "Euronext Brussels", note="709 filings."),
    _esef("LS", "XLIS", "PT", "EUR", "Euronext Lisbon", note="128 filings."),
    _esef("MI", "XMIL", "IT", "EUR", "Borsa Italiana",
          note="872 filings; index current to 2026-01."),
    _esef("MC", "XMAD", "ES", "EUR", "Bolsa de Madrid",
          note="542 filings; index current to 2025-01."),
    _esef("VI", "XWBO", "AT", "EUR", "Wiener Borse", note="601 filings."),
    _esef("WA", "XWAR", "PL", "PLN", "Warsaw Stock Exchange",
          note="877 filings; newest period_end 2024-03 — lagging."),
    _esef("AT", "ASEX", "GR", "EUR", "Athens Exchange", note="189 filings."),

    # ── EU/EEA — ESEF regime, but NOT reachable ──────────────────────────
    # Germany's Bundesanzeiger does not syndicate to filings.xbrl.org.
    # Measured 2026-08-16: filter[country]=DE returns ZERO filings, and
    # AUTO1 Group SE (LEI 391200S2LPXG5ZD5G304) has no indexed filing despite
    # being a mandatory ESEF filer. Same for IE. These rows carry the true
    # regime but a yfinance-only chain, so a German dive does not pay for a
    # guaranteed-empty round trip. Flip to _esef(indexed=True) the day a
    # Bundesanzeiger feed exists.
    _plain("DE", "XETR", "DE", REGION_EU_EEA, "EUR", "Xetra", REGIME_ESEF,
           note="ESEF filer de jure, but Bundesanzeiger does not syndicate to "
                "filings.xbrl.org (0 DE filings indexed, verified 2026-08-16). "
                "Needs a national-OAM adapter, not the ESEF index adapter."),
    _plain("F", "XFRA", "DE", REGION_EU_EEA, "EUR", "Frankfurt", REGIME_ESEF,
           note="See .DE — no indexed ESEF."),
    _plain("BE", "XBER", "DE", REGION_EU_EEA, "EUR", "Berlin", REGIME_ESEF,
           note="See .DE — no indexed ESEF."),
    _plain("MU", "XMUN", "DE", REGION_EU_EEA, "EUR", "Munich", REGIME_ESEF,
           note="See .DE — no indexed ESEF."),
    _plain("IR", "XDUB", "IE", REGION_EU_EEA, "EUR", "Euronext Dublin", REGIME_ESEF,
           note="0 IE filings indexed (verified 2026-08-16)."),

    # ── UK — Companies House regime; adapter not built ───────────────────
    # SRC_COMPANIES_HOUSE is listed first so the day that adapter registers,
    # UK tickers upgrade with zero edits here. Unregistered names are skipped
    # by the resolver, so today this behaves as yfinance-only.
    Jurisdiction(suffix="L", mic="XLON", country="GB", region=REGION_UK,
                 currency="GBP", regime=REGIME_UK_CH, venue="London Stock Exchange / AIM",
                 source_chain=(SRC_COMPANIES_HOUSE, SRC_YFINANCE),
                 note="UK left the ESEF regime; accounts are iXBRL via the free "
                      "Companies House API. Adapter not built — chain currently "
                      "resolves to yfinance. Verified: no UK filings in the ESEF index."),
    Jurisdiction(suffix="IL", mic="XLON", country="GB", region=REGION_UK,
                 currency="GBP", regime=REGIME_UK_CH, venue="LSE International",
                 source_chain=(SRC_COMPANIES_HOUSE, SRC_YFINANCE)),

    # ── Switzerland — outside EU/EEA, no ESEF obligation ─────────────────
    _plain("SW", "XSWX", "CH", REGION_EU_EEA, "CHF", "SIX Swiss Exchange",
           note="Non-EEA — no ESEF mandate; SIX does not publish an open XBRL feed."),

    # ── APAC / MEA — genuinely PDF-land or needs a national adapter ───────
    _plain("AX", "XASX", "AU", REGION_APAC, "AUD", "ASX",
           note="ASX announcements are PDF; no XBRL mandate. Genuine LLM-extraction "
                "candidate."),
    _plain("NZ", "XNZE", "NZ", REGION_APAC, "NZD", "NZX"),
    _plain("HK", "XHKG", "HK", REGION_APAC, "HKD", "HKEX"),
    _plain("KS", "XKRX", "KR", REGION_APAC, "KRW", "KOSPI",
           note="OpenDART offers a free structured API — future adapter, one name "
                "in the universe today so not yet prioritised."),
    _plain("KQ", "XKOS", "KR", REGION_APAC, "KRW", "KOSDAQ"),
    _plain("SA", "BVMF", "BR", REGION_APAC, "BRL", "B3 Brasil",
           note="CVM publishes structured DFP/ITR datasets — future adapter."),
    _plain("IS", "XIST", "TR", REGION_MEA, "TRY", "Borsa Istanbul",
           note="KAP standardised reports — semi-structured."),
    _plain("TA", "XTAE", "IL", REGION_MEA, "ILS", "Tel Aviv Stock Exchange"),
    _plain("JO", "XJSE", "ZA", REGION_MEA, "ZAR", "Johannesburg Stock Exchange"),
)}


def jurisdiction_for(ticker: str) -> Jurisdiction:
    """Resolve a ticker to its Jurisdiction. Never raises; never does I/O.

    Unknown suffixes fall back to the US row (``UNKNOWN_SUFFIX_DEFAULTS_TO_US``)
    so class-share tickers like ``BRK.B`` keep routing to SEC exactly as they
    did before this module existed.
    """
    suffix = ticker.rsplit(".", 1)[-1].upper() if "." in ticker else ""
    j = _JURISDICTIONS.get(suffix)
    if j is not None:
        return j
    return _JURISDICTIONS[""]


def all_jurisdictions() -> tuple[Jurisdiction, ...]:
    """Every registered market — for CLI listing / coverage reporting."""
    return tuple(_JURISDICTIONS.values())


def suffixes_for_source(source_name: str) -> tuple[str, ...]:
    """Which suffixes route to a given adapter (used by adapters' ``supports``)."""
    return tuple(
        j.suffix for j in _JURISDICTIONS.values() if source_name in j.source_chain
    )
