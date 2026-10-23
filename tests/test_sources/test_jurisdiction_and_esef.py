"""ADR-041 — jurisdiction registry + ESEF adapter.

Pure tests: no network. The ESEF parser is exercised against a hand-built
xBRL-JSON payload shaped exactly like a real filings.xbrl.org document
(structure captured from BONESUPPORT's FY2024 filing on 2026-08-16).

Emphasis is on FAILURE modes, per CLAUDE.md — the parser must refuse segment
facts, refuse interim durations, refuse ambiguous identity, and report index
lag rather than presenting a stale year as current.
"""
from __future__ import annotations

from datetime import date

import pytest

from data.sources.base import FIDELITY_FILING_GRADE, FIDELITY_NORMALISED, fidelity_of
from data.sources.esef import (
    _build_row,
    _collect_facts,
    _is_annual,
    _name_variants,
    _normalise_name,
    _parse_period,
)
from data.sources.jurisdiction import (
    REGIME_ESEF,
    SRC_ESEF,
    SRC_SEC,
    SRC_YFINANCE,
    all_jurisdictions,
    jurisdiction_for,
)


# ── Jurisdiction registry ──────────────────────────────────────────────────

def test_unknown_suffix_defaults_to_us_chain():
    """Anti-degradation guard: a stray suffix must never demote a US filer."""
    for ticker in ("NVDA", "BRK.B", "BF.B", "SOMETHING.ZZZ"):
        j = jurisdiction_for(ticker)
        assert j.country == "US"
        assert j.source_chain[0] == SRC_SEC


def test_every_chain_terminates_at_yfinance():
    """Resolution can never fail — yfinance is the universal terminator."""
    for j in all_jurisdictions():
        assert j.source_chain[-1] == SRC_YFINANCE, j.suffix


def test_no_duplicate_suffixes():
    suffixes = [j.suffix for j in all_jurisdictions()]
    assert len(suffixes) == len(set(suffixes))


def test_german_regime_is_esef_but_chain_is_not():
    """Regime (de jure) and reachability (de facto) are separate facts.

    Germany mandates ESEF filing, but the Bundesanzeiger does not syndicate to
    filings.xbrl.org — 0 DE filings indexed, verified 2026-08-16. Conflating
    these two produces a guaranteed-empty fetch on every German dive.
    """
    j = jurisdiction_for("AG1.DE")
    assert j.regime == REGIME_ESEF
    assert SRC_ESEF not in j.source_chain
    assert j.structured_reachable is False


def test_nordic_venues_are_esef_reachable():
    for ticker in ("BONEX.ST", "KEMPOWR.HE", "NOD.OL", "DEMANT.CO"):
        j = jurisdiction_for(ticker)
        assert SRC_ESEF in j.source_chain, ticker
        assert j.structured_reachable is True


def test_fidelity_ordering_separates_triage_from_thesis():
    from data.sources import get_source
    assert fidelity_of(get_source("esef")) == FIDELITY_FILING_GRADE
    assert fidelity_of(get_source("sec_edgar")) == FIDELITY_FILING_GRADE
    assert fidelity_of(get_source("yfinance")) == FIDELITY_NORMALISED
    assert fidelity_of(get_source("esef")) > fidelity_of(get_source("yfinance"))


# ── Period parsing (the OIM half-open-interval convention) ────────────────

def test_instant_is_previous_day():
    """OIM encodes the 2024-12-31 balance sheet as instant 2025-01-01."""
    start, end, is_duration = _parse_period("2025-01-01T00:00:00")
    assert is_duration is False
    assert end == date(2024, 12, 31)
    assert start is None


def test_duration_end_is_inclusive_previous_day():
    start, end, is_duration = _parse_period(
        "2024-01-01T00:00:00/2025-01-01T00:00:00"
    )
    assert is_duration is True
    assert start == date(2024, 1, 1)
    assert end == date(2024, 12, 31)


def test_interim_duration_is_not_annual():
    """A Q1 duration in the same document must not become the fiscal year."""
    assert _is_annual(date(2024, 1, 1), date(2024, 3, 31)) is False
    assert _is_annual(date(2024, 1, 1), date(2024, 6, 30)) is False
    assert _is_annual(date(2024, 1, 1), date(2024, 12, 31)) is True
    assert _is_annual(None, date(2024, 12, 31)) is False


# ── Name normalisation + GLEIF query ladder ───────────────────────────────

def test_normalise_strips_legal_forms():
    assert _normalise_name("BONESUPPORT HOLDING AB") == "bonesupport"
    assert _normalise_name("Bonesupport Holding AB (publ)") == "bonesupport"
    assert _normalise_name("Kempower Oyj") == "kempower"


def test_name_variants_walk_from_specific_to_general():
    variants = _name_variants("Bonesupport Holding AB (publ)")
    assert variants[0] == "Bonesupport Holding AB (publ)"
    assert "Bonesupport Holding AB" in variants
    assert "Bonesupport" in variants
    # Ordering matters: the most specific form is tried first.
    assert variants.index("Bonesupport Holding AB") < variants.index("Bonesupport")


# ── Fact collection: what must be REFUSED ─────────────────────────────────

def _fact(concept, period, value, unit="iso4217:SEK", **extra_dims):
    dims = {"concept": concept, "entity": "scheme:LEI", "period": period, "unit": unit}
    dims.update(extra_dims)
    return {"value": str(value), "decimals": -3, "dimensions": dims}


FY24 = "2024-01-01T00:00:00/2025-01-01T00:00:00"
FY24_END = "2025-01-01T00:00:00"


def test_segment_facts_are_refused():
    """A revenue-by-geography fact must never be read as consolidated revenue."""
    payload = {"facts": {
        "f1": _fact("ifrs-full:Revenue", FY24, 898_727_000),
        "f2": _fact("ifrs-full:Revenue", FY24, 295_000_000,
                    **{"ifrs-full:GeographicalAreasAxis": "US"}),
    }}
    durations, _, _, _ = _collect_facts(payload)
    assert durations[2024]["ifrs-full:Revenue"] == 898_727_000


def test_per_share_units_do_not_pollute_currency_detection():
    payload = {"facts": {
        "f1": _fact("ifrs-full:Revenue", FY24, 100.0, unit="iso4217:SEK"),
        "f2": _fact("ifrs-full:BasicEarningsLossPerShare", FY24, 2.13,
                    unit="iso4217:SEK/xbrli:shares"),
    }}
    _, _, _, currencies = _collect_facts(payload)
    assert currencies == {"SEK"}


def test_interim_duration_excluded_from_annual_map():
    payload = {"facts": {
        "f1": _fact("ifrs-full:Revenue", FY24, 898_727_000),
        "f2": _fact("ifrs-full:Revenue",
                    "2024-01-01T00:00:00/2024-04-01T00:00:00", 200_000_000),
    }}
    durations, _, _, _ = _collect_facts(payload)
    assert durations[2024]["ifrs-full:Revenue"] == 898_727_000


def test_non_numeric_fact_is_skipped_not_fatal():
    payload = {"facts": {
        "f1": _fact("ifrs-full:Revenue", FY24, 898_727_000),
        "f2": {"value": "not-a-number", "dimensions": {
            "concept": "ifrs-full:Assets", "entity": "e",
            "period": FY24_END, "unit": "iso4217:SEK"}},
    }}
    durations, instants, _, _ = _collect_facts(payload)
    assert durations[2024]["ifrs-full:Revenue"] == 898_727_000
    assert 2024 not in instants or "ifrs-full:Assets" not in instants[2024]


# ── Row building: synonyms, sums, derivations ─────────────────────────────

def test_revenue_synonym_precedence_across_filers():
    """Three real filers, three different revenue concepts, one canonical field."""
    for concept in ("ifrs-full:Revenue",
                    "ifrs-full:RevenueFromSaleOfGoods",
                    "ifrs-full:RevenueFromContractsWithCustomers"):
        row = _build_row("X.ST", 2024, {concept: 500.0}, {}, date(2024, 12, 31),
                         "SEK", "acc")
        assert row.revenue == 500.0, concept


def test_capex_sums_components_rather_than_first_match():
    """PP&E and intangibles purchases are additive, not synonyms."""
    duration = {
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": 1_530_000.0,
        "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities": 4_310_000.0,
        "ifrs-full:CashFlowsFromUsedInOperatingActivities": 65_760_000.0,
    }
    row = _build_row("BONEX.ST", 2024, duration, {}, date(2024, 12, 31), "SEK", "acc")
    assert row.capex == pytest.approx(5_840_000.0)
    # FCF derivation must match the EDGAR/yfinance formula exactly.
    assert row.free_cash_flow == pytest.approx(59_920_000.0)


def test_gross_profit_derived_when_absent():
    row = _build_row("X.ST", 2024,
                     {"ifrs-full:Revenue": 100.0, "ifrs-full:CostOfSales": 20.0},
                     {}, date(2024, 12, 31), "SEK", "acc")
    assert row.gross_profit == 80.0
    assert row.gross_margin == pytest.approx(0.80)


def test_by_nature_filer_leaves_gross_profit_none_not_zero():
    """A by-nature presenter has no COGS. That is UNEVAL, never 0."""
    row = _build_row("KEMPOWR.HE", 2025, {"ifrs-full:Revenue": 251_295_300.0},
                     {}, date(2025, 12, 31), "EUR", "acc")
    assert row.revenue == 251_295_300.0
    assert row.gross_profit is None
    assert row.gross_margin is None


def test_extension_concepts_are_not_interpreted():
    """A company-specific tag must not be guessed into a canonical field."""
    row = _build_row("BONEX.ST", 2024, {"BON:SomeCompanySpecificRevenueLine": 999.0},
                     {}, date(2024, 12, 31), "SEK", "acc")
    assert row.revenue is None


def test_shares_derived_from_eps_when_untagged():
    """ESEF Phase-1 often omits share counts; ProfitLoss/BasicEPS recovers them.

    Real case: BONESUPPORT FY2024 tags EPS 2.04 and ProfitLoss 133,754,000 but
    no share count. 133,754,000 / 2.04 = 65,565,686 — matches the ~65.5m
    actually outstanding. F7 discards rows without shares, so this is the
    difference between F7 running and F7 being UNEVAL on most EU filers.
    """
    row = _build_row("BONEX.ST", 2024, {
        "ifrs-full:ProfitLoss": 133_754_000.0,
        "ifrs-full:BasicEarningsLossPerShare": 2.04,
    }, {}, date(2024, 12, 31), "SEK", "acc")
    assert row.shares_outstanding == pytest.approx(65_565_686, rel=1e-4)


def test_tagged_share_count_beats_derivation():
    row = _build_row("X.AS", 2024, {
        "ifrs-full:ProfitLoss": 100.0,
        "ifrs-full:BasicEarningsLossPerShare": 2.0,
        "ifrs-full:NumberOfSharesOutstanding": 77.0,
    }, {}, date(2024, 12, 31), "EUR", "acc")
    assert row.shares_outstanding == 77.0


def test_loss_making_year_does_not_derive_negative_share_count():
    """Negative EPS with negative income divides to a positive count; a sign
    mismatch must NOT produce a negative share count."""
    row = _build_row("X.ST", 2022, {
        "ifrs-full:ProfitLoss": -68_167_000.0,
        "ifrs-full:BasicEarningsLossPerShare": 1.06,   # sign mismatch
    }, {}, date(2022, 12, 31), "SEK", "acc")
    assert row.shares_outstanding is None


def test_row_is_tagged_with_esef_provenance():
    row = _build_row("BONEX.ST", 2024, {"ifrs-full:Revenue": 1.0}, {},
                     date(2024, 12, 31), "SEK", "fxo-id-123")
    assert row.source == "esef"
    assert row.period == "annual"
    assert row.fiscal_year == 2024
    assert row.accession_number == "fxo-id-123"
