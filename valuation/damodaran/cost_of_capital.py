"""Cost of capital — CAPM cost of equity, after-tax cost of debt, WACC.

Implements Damodaran's standard CAPM + WACC framework (ADR-027 Phase A):

  cost_of_equity = risk_free_rate + relevered_beta × (mature_market_ERP + country_RP)

  cost_of_debt_pretax = interest_expense / (avg total_debt)   ← effective rate
                       OR risk_free_rate + synthetic_credit_spread  ← when company-level data missing

  cost_of_debt_aftertax = cost_of_debt_pretax × (1 − marginal_tax_rate)

  weight_equity = market_cap / (market_cap + total_debt)
  weight_debt   = total_debt / (market_cap + total_debt)

  WACC = weight_equity × cost_of_equity + weight_debt × cost_of_debt_aftertax

Damodaran's discipline carried over (ADR-027 §Context):
  - Implied ERP, not historical.
  - Industry beta (unlevered) re-levered to company's specific D/E.
  - MARGINAL tax rate (statutory + state-weighted), not effective.
  - Country risk premium for non-US filers.

Public API:
  compute_wacc(ticker_data, ref_data) -> WACCResult

`ticker_data` is a duck-typed Company/Financial snapshot. `ref_data` is the
loaded Damodaran reference dict. Both kept loose to avoid coupling to the
broader project schema in this Phase-A unit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any


# ── Constants ────────────────────────────────────────────────────────────

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference" / "damodaran"

# Sanity bounds (per ADR-027 §Risks — flag if outside, do not silently clamp)
_BETA_MIN, _BETA_MAX = 0.20, 3.00          # Damodaran's published betas rarely outside this
_WACC_MIN, _WACC_MAX = 0.04, 0.25          # 4-25% WACC reasonable range
_EQUITY_WEIGHT_MIN = 0.20                  # Below this, company is debt-heavy; flag
_COD_FALLBACK_SPREAD_BPS = 200             # Default credit spread (BBB-ish) when no company data

# Damodaran industry mapping — maps our sector labels (yfinance / Polygon) into
# his 95-industry taxonomy. Lossy mapping — flagged in data_gaps when forced.
_SECTOR_TO_DAMODARAN_INDUSTRY: dict[str, str] = {
    # Generic-sector buckets (yfinance "sector" field) → best-fit Damodaran industry
    "Technology": "Software (System & Application)",       # most common; specific tickers should override
    "Healthcare": "Healthcare Information Tech",           # most common in our mid-cap universe
    "Consumer Cyclical": "Retail (General)",
    "Consumer Defensive": "Food & Beverage",
    "Communication Services": "Advertising",
    "Industrials": "Industrials (Diversified)",
    "Financial Services": "Financial Services (Non-bank)",
    "Basic Materials": "Basic Materials (Mining)",
    "Energy": "Industrials (Diversified)",                  # imperfect; the subset has no energy row
    "Real Estate": "Real Estate (Development)",
    "Utilities": "Industrials (Diversified)",               # imperfect
}


# ── Result dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class WACCResult:
    """All inputs + outputs of the WACC calc. Frozen so callers can hash / cache."""

    ticker: str

    # Inputs
    risk_free_rate: float                  # decimal (e.g. 0.0435 for 4.35%)
    mature_market_erp: float               # decimal
    country_risk_premium: float            # decimal
    total_erp: float                       # mature_market_erp + country_risk_premium
    industry: str                          # Damodaran industry name actually used
    industry_beta_unlevered: float
    debt_to_equity: float
    marginal_tax_rate: float               # decimal
    beta_relevered: float

    # Cost-of-debt path
    cost_of_debt_pretax: float
    cost_of_debt_pretax_source: str        # "effective_interest_rate" | "synthetic_spread" | "data_gap"
    cost_of_debt_aftertax: float

    # Capital structure (market-value weights)
    market_cap: float
    total_debt: float
    weight_equity: float
    weight_debt: float

    # Outputs
    cost_of_equity: float
    wacc: float

    # Diagnostics
    data_gaps: list[str] = field(default_factory=list)
    reference_data_staleness_days: int = 0  # max across all loaded refs
    # ADR-043 provenance: which currency's sovereign yield the rate came from,
    # which FRED series, and the country actually resolved. Recorded so a reader
    # can CONFIRM the rate matches the cash-flow currency instead of trusting it.
    risk_free_currency: str = "USD"
    risk_free_series: str = "DGS10"
    country_resolved: str = "United States"


# ── Reference data loaders ───────────────────────────────────────────────


def _load_reference(filename: str) -> dict[str, Any]:
    path = REFERENCE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Damodaran reference data missing: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_all_reference() -> dict[str, dict[str, Any]]:
    return {
        "risk_free_rate": _load_reference("risk_free_rate.json"),
        "implied_erp": _load_reference("implied_erp.json"),
        "industry_betas": _load_reference("industry_betas_us.json"),
        "country_erp": _load_reference("country_erp.json"),
        "tax_rates": _load_reference("tax_rates.json"),
    }


def _staleness_days(snapshot_date_str: str, as_of_date_str: str) -> int:
    """Days between snapshot and as-of (positive = snapshot is older)."""
    from datetime import datetime
    snap = datetime.strptime(snapshot_date_str, "%Y-%m-%d").date()
    as_of = datetime.strptime(as_of_date_str, "%Y-%m-%d").date()
    return (as_of - snap).days


# ── Industry beta lookup ─────────────────────────────────────────────────


# ADR-043 §2.4 — yfinance INDUSTRY label → our internal industry key.
# Consulted before the sector map. Motivating case: BONESUPPORT's industry is
# "Medical Instruments & Supplies", but keying on sector="Healthcare" alone
# assigned it "Healthcare Information Tech" (beta 0.99) instead of
# "Healthcare Products" (0.83) — a device maker priced as a software company.
_INDUSTRY_TO_DAMODARAN_INDUSTRY: dict[str, str] = {
    "Medical Instruments & Supplies": "Healthcare Products",
    "Medical Devices": "Healthcare Products",
    "Medical Instruments & Equipment": "Healthcare Products",
    "Health Information Services": "Healthcare Information Tech",
    "Medical Care Facilities": "Healthcare Services",
    "Diagnostics & Research": "Healthcare Products",
    "Biotechnology": "Drugs (Biotechnology)",
    "Drug Manufacturers - General": "Drugs (Pharmaceutical)",
    "Drug Manufacturers - Specialty & Generic": "Drugs (Pharmaceutical)",
    "Medical Distribution": "Retail (Distributors)",
    "Semiconductors": "Semiconductor",
    "Semiconductor Equipment & Materials": "Semiconductor Equipment",
    "Software - Application": "Software (System & Application)",
    "Software - Infrastructure": "Software (System & Application)",
    "Information Technology Services": "Computer Services",
    "Internet Content & Information": "Software (Internet)",
    "Electronic Gaming & Multimedia": "Software (Entertainment)",
    "Communication Equipment": "Telecom Equipment",
    "Telecom Services": "Telecom Services",
    "Specialty Industrial Machinery": "Industrials (Machinery)",
    "Industrial Distribution": "Retail (Distributors)",
    "Internet Retail": "Retail (Online)",
    "Specialty Retail": "Retail (General)",
    "Apparel Retail": "Retail (Apparel)",
    "Restaurants": "Restaurants/Dining",
    "Packaged Foods": "Food & Beverage",
    "Real Estate - Development": "Real Estate (Development)",
    "Building Products & Equipment": "Construction Supplies",
    "Auto Parts": "Auto & Truck",
    "Insurance - Property & Casualty": "Insurance (General)",
    "Education & Training Services": "Education",
    "Other Industrial Metals & Mining": "Basic Materials (Mining)",
    "Advertising Agencies": "Advertising",

    # ── SEC SIC descriptions ──────────────────────────────────────────────
    # EDGAR-sourced companies carry SIC office descriptions, NOT yfinance
    # labels, so the two vocabularies must BOTH be mapped. Missing this was
    # why the beta fix appeared to leave every US ticker untouched: the map
    # was written against yfinance names after testing on an ESEF ticker.
    "Semiconductors & Related Devices": "Semiconductor",
    "Semiconductors & Related Devices (No Manufacturing)": "Semiconductor",
    "Electronic Computers": "Computers/Peripherals",
    "Computer Peripheral Equipment": "Computers/Peripherals",
    "Services-Prepackaged Software": "Software (System & Application)",
    "Services-Computer Programming, Data Processing, Etc.": "Computer Services",
    "Services-Computer Programming Services": "Computer Services",
    "Surgical & Medical Instruments & Apparatus": "Healthcare Products",
    "Electromedical & Electrotherapeutic Apparatus": "Healthcare Products",
    "Orthopedic, Prosthetic & Surgical Appliances & Supplies": "Healthcare Products",
    "In Vitro & In Vivo Diagnostic Substances": "Healthcare Products",
    "Biological Products (No Diagnostic Substances)": "Drugs (Biotechnology)",
    "Pharmaceutical Preparations": "Drugs (Pharmaceutical)",
    "Services-Health Services": "Healthcare Services",
    "Retail-Catalog & Mail-Order Houses": "Retail (Online)",
    "Retail-Variety Stores": "Retail (General)",
    "Retail-Eating Places": "Restaurants/Dining",
    "Telephone Communications (No Radiotelephone)": "Telecom Services",
    "Radio & Tv Broadcasting & Communications Equipment": "Telecom Equipment",
    "Services-Advertising Agencies": "Advertising",
    "Services-Educational Services": "Education",
}


def _industry_unlevered_beta(
    company_sector: str | None,
    industry_betas: dict[str, Any],
    data_gaps: list[str],
    ticker: str,
    company_industry: str | None = None,
) -> tuple[float, str]:
    """Map company.sector → Damodaran industry → unlevered beta.

    Damodaran's taxonomy doesn't match yfinance/Polygon sectors 1:1, so we use
    a coarse sector→industry mapping. Tickers that need a specific industry
    override (e.g. a healthcare ticker that's actually biotech vs medical
    device) can be patched per-ticker in a future enhancement.

    Returns (unlevered_beta, damodaran_industry_used). Flags a data_gap when
    the sector falls through to the default.
    """
    industries = industry_betas.get("industries", {})

    # ADR-043 §2.4 — INDUSTRY first. It is strictly more specific than sector,
    # so consulting sector first throws away information we already hold.
    if company_industry:
        if company_industry in industries:
            return industries[company_industry]["unlevered_beta"], company_industry
        by_industry = _INDUSTRY_TO_DAMODARAN_INDUSTRY.get(company_industry)
        if by_industry and by_industry in industries:
            return industries[by_industry]["unlevered_beta"], by_industry

    # Try exact match on sector (sector IS the damodaran industry name)
    if company_sector and company_sector in industries:
        return industries[company_sector]["unlevered_beta"], company_sector

    # Coarse sector → industry mapping. Reached only when the industry label is
    # absent or unmapped, so note the loss of specificity rather than hiding it.
    mapped = _SECTOR_TO_DAMODARAN_INDUSTRY.get(company_sector or "")
    if mapped and mapped in industries:
        if company_industry:
            data_gaps.append(
                f"{ticker}: industry {company_industry!r} has no Damodaran "
                f"mapping; fell back to the {company_sector!r} sector beta "
                f"({mapped}). Add it to _INDUSTRY_TO_DAMODARAN_INDUSTRY."
            )
        return industries[mapped]["unlevered_beta"], mapped

    # Fallback default (industry_betas_us.json has "_fallback_default")
    fallback = industries.get("_fallback_default", {})
    fb_beta = fallback.get("unlevered_beta", 1.00)
    data_gaps.append(
        f"{ticker}: sector '{company_sector}' not in Damodaran industry taxonomy; "
        f"using fallback unlevered_beta={fb_beta}. Edit _SECTOR_TO_DAMODARAN_INDUSTRY "
        f"in cost_of_capital.py if this ticker needs a specific industry."
    )
    return fb_beta, "_fallback_default"


# ── Re-leveraging ────────────────────────────────────────────────────────


def relevel_beta(unlevered_beta: float, debt_to_equity: float, marginal_tax_rate: float) -> float:
    """Damodaran's standard relevering formula:

        β_levered = β_unlevered × (1 + (1 − t) × D/E)

    The Damodaran formula uses MARKET-VALUE D/E (market cap for equity,
    market value of debt — or book value when market unavailable). Caller is
    responsible for computing D/E correctly.
    """
    if debt_to_equity is None or debt_to_equity < 0:
        # Net-cash position or invalid — assume zero debt for levering. Damodaran
        # caps at unlevered = levered for cash-rich filers; the negative D/E
        # case is degenerate (book equity < cash and no debt) and not common.
        return unlevered_beta
    return unlevered_beta * (1.0 + (1.0 - marginal_tax_rate) * debt_to_equity)


# ── Cost of equity ──────────────────────────────────────────────────────


def compute_cost_of_equity(
    risk_free_rate: float,
    relevered_beta: float,
    mature_market_erp: float,
    country_risk_premium: float = 0.0,
) -> float:
    """CAPM with country premium adjustment:

        cost_of_equity = risk_free_rate + β × (ERP_mature + CRP)
    """
    total_erp = mature_market_erp + country_risk_premium
    return risk_free_rate + relevered_beta * total_erp


# ── Cost of debt ────────────────────────────────────────────────────────


def _company_effective_interest_rate(
    interest_expense: float | None,
    total_debt: float | None,
) -> float | None:
    """Effective pre-tax interest rate from the income statement, if computable.

    Damodaran prefers MARKET cost of debt (yield on outstanding bonds + sovereign
    credit spread for unrated debt), but most mid-caps don't have liquid bonds.
    Effective interest rate (interest expense / avg debt) is the next-best signal
    when available — better than a flat synthetic spread.

    Returns None if either input is None or zero / negative.
    """
    if interest_expense is None or total_debt is None:
        return None
    if interest_expense <= 0 or total_debt <= 0:
        return None
    rate = interest_expense / total_debt
    # Sanity clamp: anything > 20% is likely a data error (or distressed debt)
    if rate > 0.20:
        return None
    return rate


def compute_after_tax_cost_of_debt(
    interest_expense: float | None,
    total_debt: float | None,
    risk_free_rate: float,
    marginal_tax_rate: float,
    data_gaps: list[str],
    ticker: str,
) -> tuple[float, str]:
    """Returns (after_tax_cost_of_debt, source_label).

    Resolution order:
      1. Effective interest rate from financials (preferred when company has real debt)
      2. Synthetic spread: risk_free_rate + 200bps default (BBB-equivalent)

    The synthetic fallback is intentionally conservative — Damodaran's discipline
    is to FLAG the assumption rather than fabricate precision. data_gaps[] gets
    the entry so the user can override per-ticker.
    """
    eff_rate = _company_effective_interest_rate(interest_expense, total_debt)
    if eff_rate is not None:
        return eff_rate * (1.0 - marginal_tax_rate), "effective_interest_rate"

    # Fall back to synthetic spread
    spread = _COD_FALLBACK_SPREAD_BPS / 10000.0
    pretax = risk_free_rate + spread
    data_gaps.append(
        f"{ticker}: cost-of-debt computed via synthetic BBB-equivalent spread "
        f"(risk_free + {_COD_FALLBACK_SPREAD_BPS}bps = {pretax:.2%} pre-tax). "
        f"Effective interest rate unavailable — likely net-cash or no public debt. "
        f"Damodaran flag: use sovereign + credit-spread when bond data available."
    )
    return pretax * (1.0 - marginal_tax_rate), "synthetic_spread"


# ── Marginal tax rate lookup ────────────────────────────────────────────


@cache
def _iso2_to_damodaran_country() -> dict[str, str]:
    """ISO alpha-2 → Damodaran country name (data/reference/damodaran/iso2_countries.json)."""
    return dict(_load_reference("iso2_countries.json")["countries"])


def _resolve_country(ticker: str, data_gaps: list[str]) -> str:
    """Ticker → Damodaran country name, via ADR-041's jurisdiction registry."""
    try:
        from data.sources.jurisdiction import jurisdiction_for
        iso2 = jurisdiction_for(ticker).country
    except Exception as exc:  # noqa: BLE001 — registry is a soft dependency here
        data_gaps.append(
            f"{ticker}: jurisdiction lookup failed ({exc.__class__.__name__}); "
            f"country risk premium and tax rate unresolved"
        )
        return "United States"
    name = _iso2_to_damodaran_country().get(iso2)
    if name is None:
        data_gaps.append(
            f"{ticker}: country {iso2!r} has no Damodaran mapping — country risk "
            f"premium and marginal tax rate are UNRESOLVED, not zero. Add it to "
            f"data/reference/damodaran/iso2_countries.json."
        )
        return iso2
    return name


class MissingRiskFreeRateError(RuntimeError):
    """No risk-free rate exists for the filer's reporting currency.

    Raised rather than falling back to USD. ADR-043 §2.2: a silent USD
    substitution is the original defect — it produced a plausible WACC for a
    SEK filer discounted at US Treasury yields, with nothing in the output to
    say so. Refusing is the only behaviour that surfaces the gap.
    """


def _resolve_risk_free(
    rf_data: dict[str, Any],
    reporting_currency: str | None,
    data_gaps: list[str],
    ticker: str,
) -> tuple[float, str, str, str, int]:
    """→ (rate_decimal, currency, series, snapshot_date, staleness_limit_days).

    ``reporting_currency=None`` means the caller did not know, which for this
    universe means a US SEC filer — USD is the correct answer, not a fallback.
    A currency that IS known but has no published rate raises: see
    ``MissingRiskFreeRateError``.
    """
    table = rf_data.get("rates_by_currency") or {}
    currency = (reporting_currency or "USD").upper()

    if not table:
        # Pre-ADR-043 file shape. Honour it for USD only; anything else would be
        # the exact silent substitution this ADR removes.
        if currency != "USD":
            raise MissingRiskFreeRateError(
                f"{ticker}: risk_free_rate.json predates ADR-043 (no "
                f"rates_by_currency) and the filer reports {currency}. Run "
                f"scripts/refresh_damodaran_reference.py."
            )
        return (
            rf_data["ten_year_treasury_yield_pct"] / 100.0, "USD",
            "DGS10", rf_data["snapshot_date"],
            int(rf_data.get("_staleness_warning_days", 7)),
        )

    entry = table.get(currency)
    if entry is None:
        raise MissingRiskFreeRateError(
            f"{ticker}: no risk-free rate published for reporting currency "
            f"{currency}. Available: {', '.join(sorted(table))}. Add the FRED "
            f"series to scripts/refresh_damodaran_reference.py::_RF_SERIES — "
            f"do NOT substitute USD (ADR-043 §2.2)."
        )
    if currency != "USD":
        data_gaps.append(
            f"{ticker}: risk-free rate {entry['pct']:.2f}% is the {currency} "
            f"sovereign yield ({entry['series']}), matching the filer's "
            f"reporting currency — not the US Treasury yield"
        )
    return (
        entry["pct"] / 100.0, currency, entry["series"], entry["snapshot_date"],
        int(entry.get("staleness_warning_days", 75)),
    )


def _marginal_tax_rate(
    country: str,
    tax_rates: dict[str, Any],
    data_gaps: list[str],
    ticker: str,
    country_erp: dict[str, Any] | None = None,
) -> float:
    """Get MARGINAL tax rate by country. Damodaran's strict teaching: marginal,
    not effective.

    ADR-043 §2.3 adds a second source before the fallback. ``tax_rates.json``
    covers only a handful of jurisdictions (Sweden absent), so a Swedish filer
    silently received the 25% global median while ``country_erp.json`` — which
    the 2026-08-16 refresh populated for all 178 countries — held Sweden's
    actual 20.6% statutory rate, unread. Two files, one of them complete, and
    the incomplete one won.
    """
    rates = tax_rates.get("marginal_tax_rates_pct", {})
    if country in rates:
        return rates[country]["combined"] / 100.0

    # Damodaran's country table carries a statutory corporate rate per country.
    # It is the same author and the same publication cycle, so preferring it to
    # a global median is a strict improvement, not a new assumption.
    detail = (country_erp or {}).get("_detail", {}).get(country) or {}
    from_ctry = detail.get("corporate_tax_rate_pct")
    if from_ctry is not None:
        data_gaps.append(
            f"{ticker}: marginal tax rate {from_ctry:.2f}% for {country} taken "
            f"from Damodaran's country table (statutory) — tax_rates.json does "
            f"not cover this jurisdiction"
        )
        return float(from_ctry) / 100.0

    fallback = rates.get("_fallback_default", {"combined": 25.0})
    data_gaps.append(
        f"{ticker}: country '{country}' absent from BOTH tax_rates.json and "
        f"Damodaran's country table; using global median "
        f"{fallback['combined']}%. This is an assumption, not a lookup."
    )
    return fallback["combined"] / 100.0


def _country_risk_premium(country: str, country_erp: dict[str, Any], data_gaps: list[str], ticker: str) -> float:
    """Damodaran country risk premium (decimal). 0 for US/mature markets."""
    crps = country_erp.get("country_premiums_pct", {})
    if country in crps:
        val = crps[country]
        if isinstance(val, (int, float)):
            return val / 100.0
    fb = crps.get("_fallback_default", 1.5)
    if country and country != "United States":
        data_gaps.append(
            f"{ticker}: country '{country}' not in Damodaran CRP table; "
            f"using fallback {fb}%. Refresh country_erp.json."
        )
    return fb / 100.0 if country and country != "United States" else 0.0


# ── Main public entry point ─────────────────────────────────────────────


def compute_wacc(
    *,
    ticker: str,
    sector: str | None,
    # ADR-043 §2.3: None → resolve from the jurisdiction registry, which already
    # knows every ticker's country. The old "United States" default is what made
    # `country` read as n/a for foreign filers and silently handed them a US tax
    # rate and CRP=0.0 — right for Sweden by accident, wrong for Brazil.
    country: str | None = None,
    # ADR-043 §2.2: the currency the filer REPORTS in, which selects the
    # risk-free rate. None → USD (correct for a US SEC filer, not a fallback).
    reporting_currency: str | None = None,
    # ADR-043 §2.4: yfinance industry label, consulted BEFORE sector so a
    # medical-device maker does not receive the healthcare-IT beta.
    industry: str | None = None,
    market_cap: float,
    total_debt: float,
    cash_and_equivalents: float | None = None,
    short_term_investments: float | None = None,
    interest_expense: float | None = None,
    # None → today. This was previously a hardcoded "2026-05-13", which meant
    # the staleness baseline itself aged: every day that passed, the default
    # comparison point drifted further into the past. Refreshing the reference
    # data on 2026-08-16 exposed it — fresh snapshots read as NEGATIVE staleness
    # (92 days "in the future") against the frozen literal. A staleness check
    # anchored to a constant is not a staleness check.
    as_of_date: str | None = None,
    reference_data: dict[str, dict[str, Any]] | None = None,
) -> WACCResult:
    """Compute WACC for a company using Damodaran's framework.

    Args:
        ticker: For diagnostics + data_gaps attribution.
        sector: yfinance/Polygon sector label, mapped to Damodaran industry.
        country: Headquarters country (ISO English name matching tax_rates.json keys).
        market_cap: Equity market cap in USD.
        total_debt: Total debt INCLUDING ASC 842 operating leases (matches our
                    Financial.total_debt; ADR-021 ROIC denominator).
        cash_and_equivalents: Used only for net-debt diagnostics, not in WACC weights.
        short_term_investments: Same.
        interest_expense: From latest annual/LTM, used to estimate effective cost of debt.
        as_of_date: For staleness flagging.
        reference_data: Pre-loaded reference dict; if None, loaded from disk.

    Returns:
        WACCResult with full provenance.

    Notes:
        - WACC weights use MARKET values: market_cap for equity, total_debt for
          debt (book value as a proxy when bond market values unavailable).
        - For net-cash filers, the equity weight will be ~1.0 — Damodaran's
          treatment is fine with this (WACC ≈ cost_of_equity).
        - data_gaps[] is populated for every fallback or missing input.
    """
    if reference_data is None:
        reference_data = _load_all_reference()

    if as_of_date is None:
        from datetime import date as _date
        as_of_date = _date.today().isoformat()

    data_gaps: list[str] = []

    # ── Country: resolve from the jurisdiction registry (ADR-043 §2.3) ────
    # ADR-041 already maps every ticker to an ISO-2 country; nothing consumed it.
    if country is None:
        country = _resolve_country(ticker, data_gaps)

    # ── Risk-free rate, IN THE CURRENCY OF THE CASH FLOWS (ADR-043 §2.2) ──
    rf_data = reference_data["risk_free_rate"]
    rf, rf_currency, rf_series, rf_snapshot, rf_stale_limit = _resolve_risk_free(
        rf_data, reporting_currency, data_gaps, ticker
    )
    rf_staleness = _staleness_days(rf_snapshot, as_of_date)
    if rf_staleness > rf_stale_limit:
        data_gaps.append(
            f"{ticker}: risk-free rate for {rf_currency} ({rf_series}) is "
            f"{rf_staleness}d stale (>{rf_stale_limit}d threshold)"
        )

    # Implied ERP
    erp_data = reference_data["implied_erp"]
    erp = erp_data["implied_erp_pct"] / 100.0
    erp_staleness = _staleness_days(erp_data["snapshot_date"], as_of_date)
    if erp_staleness > erp_data.get("_staleness_warning_days", 35):
        data_gaps.append(
            f"{ticker}: implied_erp.json is {erp_staleness}d stale"
        )

    # Country risk premium
    crp = _country_risk_premium(country, reference_data["country_erp"], data_gaps, ticker)

    # Marginal tax rate
    tax = _marginal_tax_rate(country, reference_data["tax_rates"], data_gaps, ticker,
                             country_erp=reference_data["country_erp"])

    # Industry unlevered beta
    beta_unlevered, industry_used = _industry_unlevered_beta(
        sector, reference_data["industry_betas"], data_gaps, ticker,
        company_industry=industry,
    )

    # D/E for relevering (book D / market E — Damodaran's practical default)
    if market_cap <= 0:
        de_ratio = 0.0
        data_gaps.append(f"{ticker}: market_cap <= 0, defaulting D/E to 0 for relevering")
    else:
        de_ratio = max(0.0, total_debt / market_cap)

    beta_relevered = relevel_beta(beta_unlevered, de_ratio, tax)
    if not (_BETA_MIN <= beta_relevered <= _BETA_MAX):
        data_gaps.append(
            f"{ticker}: relevered_beta={beta_relevered:.2f} outside sanity bounds "
            f"[{_BETA_MIN}, {_BETA_MAX}]; check sector mapping + D/E"
        )

    # Cost of equity
    coe = compute_cost_of_equity(rf, beta_relevered, erp, crp)

    # Cost of debt
    cod_aftertax, cod_source = compute_after_tax_cost_of_debt(
        interest_expense, total_debt, rf, tax, data_gaps, ticker
    )
    # Pretax for diagnostics
    if cod_source == "effective_interest_rate":
        cod_pretax = (interest_expense or 0.0) / max(total_debt, 1.0)
    else:
        cod_pretax = rf + (_COD_FALLBACK_SPREAD_BPS / 10000.0)

    # Capital structure weights
    total_capital = market_cap + total_debt
    if total_capital <= 0:
        # Degenerate — assume all equity (cost_of_equity drives WACC)
        we, wd = 1.0, 0.0
        data_gaps.append(f"{ticker}: market_cap + total_debt <= 0; assuming all-equity")
    else:
        we = market_cap / total_capital
        wd = total_debt / total_capital
    if we < _EQUITY_WEIGHT_MIN:
        data_gaps.append(
            f"{ticker}: equity weight {we:.1%} < {_EQUITY_WEIGHT_MIN:.0%}; "
            f"highly levered — verify total_debt computation"
        )

    # WACC
    wacc = we * coe + wd * cod_aftertax
    if not (_WACC_MIN <= wacc <= _WACC_MAX):
        data_gaps.append(
            f"{ticker}: WACC={wacc:.2%} outside sanity bounds "
            f"[{_WACC_MIN:.0%}, {_WACC_MAX:.0%}]; inspect inputs"
        )

    return WACCResult(
        ticker=ticker,
        risk_free_rate=rf,
        risk_free_currency=rf_currency,
        risk_free_series=rf_series,
        country_resolved=country,
        mature_market_erp=erp,
        country_risk_premium=crp,
        total_erp=erp + crp,
        industry=industry_used,
        industry_beta_unlevered=beta_unlevered,
        debt_to_equity=de_ratio,
        marginal_tax_rate=tax,
        beta_relevered=beta_relevered,
        cost_of_debt_pretax=cod_pretax,
        cost_of_debt_pretax_source=cod_source,
        cost_of_debt_aftertax=cod_aftertax,
        market_cap=market_cap,
        total_debt=total_debt,
        weight_equity=we,
        weight_debt=wd,
        cost_of_equity=coe,
        wacc=wacc,
        data_gaps=data_gaps,
        reference_data_staleness_days=max(rf_staleness, erp_staleness),
    )
