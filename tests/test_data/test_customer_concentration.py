"""ADR-018 §6.2's validation gate, as an executable test.

§6.2 required a corpus of known-disclosure 10-Ks to validate the concentration
regex set. It was satisfied manually and recorded only as a comment in
edgar_text_parser.py ("validated against AAPL/NVDA/AMSC/FAST/MSFT/INTA/TSLA —
7/7"), so nothing prevented silent regression. This is that gate.

Every expectation below was verified by reading the cited filing text, NOT by
copying §6.2's control list — which turned out to be wrong about FAST.

Corpus: tests/fixtures/filings/, built by scripts/build_concentration_corpus.py.
Offline and network-free: the point is that a regex must not false-positive
across 160-340 KB of real filing prose.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from data.edgar_text_parser import parse_customer_concentration

FIXTURES = Path(__file__).parent.parent / "fixtures" / "filings"


def _sections(ticker: str) -> str:
    path = FIXTURES / f"{ticker}_10k_sections.txt.gz"
    if not path.exists():
        pytest.skip(f"corpus missing: {path.name} — run scripts/build_concentration_corpus.py")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


# ── Positive controls: issuer discloses a >=10% customer ─────────────────────


def test_nvda_top_direct_customer_revenue_share() -> None:
    """"sales to one direct customer represented 22% of total revenue" (FY2026)."""
    r = parse_customer_concentration(_sections("NVDA"))
    assert r.state == "disclosed_exact"
    assert r.concentration_pct == 22.0
    assert r.extraction_method == "regex"


def test_amsc_captures_top_customer_in_shared_target_sentence() -> None:
    """"In fiscal 2025, Inox accounted for 15% and Fuji Bridex ... 10% of revenues".

    The top customer's figure is not adjacent to the revenue target, so the
    single-entity pattern binds only to Fuji's 10%.
    """
    r = parse_customer_concentration(_sections("AMSC"))
    assert r.state == "disclosed_exact"
    assert r.concentration_pct == 15.0


def test_aapl_receivables_uses_current_period_figure() -> None:
    """"carriers accounted for 34% and 38% ... as of Sept 27 2025 and Sept 28 2024"."""
    r = parse_customer_concentration(_sections("AAPL"))
    assert r.state == "disclosed_exact"
    assert r.receivables_concentration_pct == 34.0


def test_top_n_pattern_reads_percentage_not_customer_count() -> None:
    """Guards the group-selection change: 'top 5 customers ... 40%' is 40, not 5."""
    text = "Our top 5 customers accounted for 40% of our total revenues in 2025."
    assert parse_customer_concentration(text).concentration_pct == 40.0


@pytest.mark.xfail(
    strict=True,
    reason="Period-blindness remains latent: candidates are pooled across fiscal "
    "years and max() wins, so a DECLINING concentration reports the older, "
    "higher figure. Not observable in the current corpus (AMSC/AAPL both rise), "
    "so the fix needs its own validated cohort before shipping.",
)
def test_declining_concentration_reports_current_not_peak_year() -> None:
    text = (
        "In fiscal 2025, Acme Corporation accounted for 12% of our total revenues. "
        "In fiscal 2024, Acme Corporation accounted for 20% of our total revenues."
    )
    assert parse_customer_concentration(text).concentration_pct == 12.0


def test_aapl_detects_receivables_not_revenue_concentration() -> None:
    """AAPL's disclosure is a receivables concentration; revenue must stay unset.

    Guards ADR-018 D4's rule that the two signals are never silently merged.
    """
    r = parse_customer_concentration(_sections("AAPL"))
    assert r.state == "disclosed_exact"
    assert r.receivables_concentration_pct is not None
    assert r.concentration_pct is None


# ── Negative controls: issuer explicitly discloses the ABSENCE ───────────────


def test_msft_explicit_no_concentration_is_negative_phrase() -> None:
    r = parse_customer_concentration(_sections("MSFT"))
    assert r.state == "not_disclosed"
    assert r.extraction_method == "negative_phrase"


def test_fast_five_percent_threshold_is_an_explicit_negative() -> None:
    """"no single customer represented 5% or more of our consolidated net sales".

    Below the Reg S-K 10% threshold and phrased with 'consolidated' — both
    previously blocked the match.
    """
    r = parse_customer_concentration(_sections("FAST"))
    assert r.state == "not_disclosed"
    assert r.extraction_method == "negative_phrase"


def test_inta_genuine_absence_of_disclosure() -> None:
    """ADR-018 §9 verified INTA has 0 concentration phrases — true absence.

    Distinct from MSFT/FAST: nothing was said either way, so the weaker
    'none' method is correct here.
    """
    r = parse_customer_concentration(_sections("INTA"))
    assert r.state == "not_disclosed"
    assert r.extraction_method == "none"
    assert r.concentration_pct is None


# ── No false positives across large real documents ──────────────────────────


@pytest.mark.parametrize("ticker", ["MSFT", "FAST", "INTA"])
def test_no_revenue_concentration_invented_for_diversified_issuers(ticker: str) -> None:
    """160-340 KB of prose full of percentages must not yield a bogus value."""
    r = parse_customer_concentration(_sections(ticker))
    assert r.concentration_pct is None
    assert r.receivables_concentration_pct is None


# ── Empty / partial input must not read as a diversification signal ─────────


def test_unreadable_sections_are_not_a_diversification_signal() -> None:
    """An empty read means 'not attempted', never 'no concentration'.

    Live relevance: TSLA's latest 10-K returns {} from _read_tenk_sections
    (edgartools exposes only part_iii/part_iv), so this path is reachable.
    """
    assert parse_customer_concentration("").state == "none"


def test_whitespace_only_sections_are_not_a_diversification_signal() -> None:
    assert parse_customer_concentration("   \n\n  \t ").state == "none"


def test_negative_disclosure_above_threshold_is_not_diversification() -> None:
    """"no customer over 50%" says nothing about diversification."""
    weak = "No single customer accounted for more than 50% of our total revenues."
    assert parse_customer_concentration(weak).extraction_method == "none"


# ── Corpus provenance ───────────────────────────────────────────────────────


def test_corpus_manifest_records_provenance() -> None:
    """Every fixture is traceable to an accession — ADR-022 source provenance."""
    manifest_path = FIXTURES / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("corpus not built")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest, "manifest is empty"
    for entry in manifest:
        assert entry["accession"]
        assert entry["cik"]
        assert entry["filing_date"]
        assert entry["total_chars"] > 10_000
        assert (FIXTURES / entry["file"]).exists()
