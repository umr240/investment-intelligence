"""Refresh vendored Damodaran reference data from source, verbatim.

    uv run python scripts/refresh_damodaran_reference.py [--dry-run]

Why this exists as a SCRIPT rather than a documented manual procedure:

The previous values in ``industry_betas_us.json`` were hand-vendored and
described in INDEX.md as "approximate based on Damodaran's recent
publications". Checked against the live source on 2026-08-16, 22 of 31
industries were off by more than 15%, and several by far more —
Financial Svcs. (Non-bank) 1.08 vs 0.32 actual (+237%), Telecom. Services
0.78 vs 0.37 (+111%), Real Estate (Development) 0.95 vs 0.48 (+98%).

Those are not stale numbers. They are numbers that were never sourced. Every
WACC computed from them carried an unquantified error into every intrinsic
value in the system, and a manual "refresh discipline" is exactly the process
that let plausible-looking estimates sit in a file labelled as vendored data
for three months.

A script cannot invent a beta. That is the entire point (ADR-033
"compute don't pull" → here, "fetch, don't estimate"; CLAUDE.md
§"first principles ... never depend on third-party calculated fields without
source verification").

Deterministic: httpx + BeautifulSoup, no LLM, no API key. Every value is taken
verbatim from the published table; nothing is interpolated or smoothed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

REF_DIR = Path("data/reference/damodaran")
BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
CTRY_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_UA = {"User-Agent": "investment-intelligence research (deterministic reference refresh)"}

# ── Risk-free rates BY CURRENCY (ADR-043 §2.2) ────────────────────────────
# Damodaran's first consistency check: the risk-free rate must be denominated
# in the currency of the cash flows. Before ADR-043 this file held a single USD
# rate and every SEK/EUR/NOK filer was discounted at the US Treasury yield.
#
# USD uses DGS10 (daily). Everything else uses the OECD "long-term interest
# rates" series (10yr government bond), which is MONTHLY — hence the separate,
# looser staleness thresholds below. Verified live 2026-08-17: all 12 series
# resolve and return observations.
_RF_SERIES: dict[str, tuple[str, str, int]] = {
    # currency: (FRED series id, cadence, staleness_warning_days)
    "USD": ("DGS10", "daily", 7),
    "SEK": ("IRLTLT01SEM156N", "monthly", 75),
    "EUR": ("IRLTLT01EZM156N", "monthly", 75),
    "GBP": ("IRLTLT01GBM156N", "monthly", 75),
    "NOK": ("IRLTLT01NOM156N", "monthly", 75),
    "DKK": ("IRLTLT01DKM156N", "monthly", 75),
    "CAD": ("IRLTLT01CAM156N", "monthly", 75),
    "CHF": ("IRLTLT01CHM156N", "monthly", 75),
    "AUD": ("IRLTLT01AUM156N", "monthly", 75),
    "PLN": ("IRLTLT01PLM156N", "monthly", 75),
    "JPY": ("IRLTLT01JPM156N", "monthly", 75),
    "KRW": ("IRLTLT01KRM156N", "monthly", 75),
    "ISK": ("IRLTLT01ISM156N", "monthly", 75),
}


def _norm(text: str) -> str:
    """Collapse whitespace. Damodaran's HTML embeds newlines+tabs INSIDE industry
    names ("Software\\n\\t\\t (System & Application)"), so a naive parse silently
    fails to match and reports industries as missing. Learned the hard way."""
    return re.sub(r"\s+", " ", text).strip()


def _pct(text: str) -> float | None:
    try:
        return float(text.replace("%", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _fetch(url: str) -> BeautifulSoup:
    resp = httpx.get(url, headers=_UA, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ── Industry betas ────────────────────────────────────────────────────────
# Our sector map (cost_of_capital._SECTOR_TO_DAMODARAN_INDUSTRY) uses stable
# internal keys. Damodaran's row labels differ and occasionally carry typos
# ("Heathcare"). This map is the ONLY place that translation lives, and each
# entry declares how confident the mapping is so an approximate one is never
# mistaken for an exact match.
#   exact       — identical label
#   renamed     — same industry, different label (incl. Damodaran's typos)
#   approximate — OUR judgement call; the closest available industry
INDUSTRY_MAP: dict[str, tuple[str, str]] = {
    "Software (System & Application)": ("Software (System & Application)", "exact"),
    "Software (Internet)": ("Software (Internet)", "exact"),
    "Software (Entertainment)": ("Software (Entertainment)", "exact"),
    "Information Services": ("Information Services", "exact"),
    "Computer Services": ("Computer Services", "exact"),
    "Semiconductor": ("Semiconductor", "exact"),
    "Computers/Peripherals": ("Computers/Peripherals", "exact"),
    "Electronics (General)": ("Electronics (General)", "exact"),
    "Semiconductor Equipment": ("Semiconductor Equip", "renamed"),
    "Healthcare Information Tech": ("Heathcare Information and Techno logy", "renamed"),
    "Drugs (Biotechnology)": ("Drugs (Biotechnology)", "exact"),
    "Drugs (Pharmaceutical)": ("Drugs (Pharmaceutical)", "exact"),
    "Healthcare Products": ("Healthcare Products", "exact"),
    "Healthcare Services": ("Hospitals/Healthcare Facilities", "approximate"),
    "Healthcare Support Services": ("Healthcare Support Services", "exact"),
    "Retail (General)": ("Retail (General)", "exact"),
    "Retail (Online)": ("Retail (Special Lines)", "approximate"),
    "Retail (Apparel)": ("Apparel", "approximate"),
    "Retail (Distributors)": ("Retail (Distributors)", "exact"),
    "Food & Beverage": ("Food Processing", "approximate"),
    "Restaurants/Dining": ("Restaurant/Dining", "renamed"),
    "Telecom Services": ("Telecom. Services", "renamed"),
    "Telecom Equipment": ("Telecom. Equipment", "renamed"),
    "Advertising": ("Advertising", "exact"),
    "Real Estate (Development)": ("Real Estate (Development)", "exact"),
    "Construction Supplies": ("Construction Supplies", "exact"),
    "Industrials (Diversified)": ("Diversified", "approximate"),
    "Industrials (Machinery)": ("Machinery", "renamed"),
    "Auto & Truck": ("Auto & Truck", "exact"),
    "Financial Services (Non-bank)": ("Financial Svcs. (Non-bank & Insur ance)", "renamed"),
    "Insurance (General)": ("Insurance (General)", "exact"),
    "Education": ("Education", "exact"),
    "Basic Materials (Mining)": ("Metals & Mining", "approximate"),
}


def scrape_betas() -> tuple[dict[str, dict[str, Any]], str]:
    soup = _fetch(BETAS_URL)
    header = _norm(soup.get_text(" "))
    m = re.search(r"Data used is as of (\w+ \d{4})", header)
    as_of = m.group(1) if m else "unknown"

    table = soup.find("table")
    if table is None:
        raise RuntimeError("betas page has no table — layout changed")

    raw: dict[str, dict[str, Any]] = {}
    for row in table.find_all("tr")[1:]:
        cells = [_norm(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        if len(cells) < 8 or not cells[0]:
            continue
        unlev, unlev_cash = _pct(cells[5]), _pct(cells[7])
        if unlev is None:
            continue
        try:
            firms = int(cells[1].replace(",", ""))
        except ValueError:
            continue
        raw[cells[0]] = {
            "firm_count": firms,
            "unlevered_beta": unlev,
            "unlevered_beta_corrected_for_cash": unlev_cash,
        }
    return raw, as_of


def build_betas_payload(raw: dict[str, dict[str, Any]], as_of: str) -> dict[str, Any]:
    industries: dict[str, Any] = {
        "_doc": (
            "Subset of Damodaran's ~96 US industries covering the screened universe. "
            "Keys are OUR stable internal labels (see cost_of_capital."
            "_SECTOR_TO_DAMODARAN_INDUSTRY); `damodaran_industry` records the exact "
            "source row each value came from, and `mapping` declares whether that "
            "correspondence is exact, a rename, or our own approximation."
        ),
    }
    unmatched: list[str] = []
    for our_key, (src_name, confidence) in INDUSTRY_MAP.items():
        if src_name not in raw:
            unmatched.append(f"{our_key} -> {src_name}")
            continue
        entry = dict(raw[src_name])
        entry["damodaran_industry"] = src_name
        entry["mapping"] = confidence
        industries[our_key] = entry

    return {
        "_doc": (
            "Damodaran's industry-level UNLEVERED betas for US-listed companies. "
            "Re-levered to each company's specific debt/equity ratio at WACC "
            "computation time."
        ),
        "_source": "Damodaran 'Betas by Sector (US)' — Betas.html, parsed verbatim",
        "_refresh_cadence": (
            "annual — Damodaran recomputes betas each January. The previous "
            "'quarterly' claim in this file was wrong and caused a snapshot_date "
            "(2026-04-01) that post-dated any publication that ever existed."
        ),
        "_staleness_warning_days": 400,
        "_methodology": (
            "Unlevered beta = levered beta / (1 + (1-tax)(D/E)), computed by "
            "Damodaran across all US-listed firms in the industry."
        ),
        "_relevering_formula": "levered_beta = unlevered_beta * (1 + (1 - marginal_tax) * (D/E))",
        "_refreshed_by": "scripts/refresh_damodaran_reference.py",
        "_refreshed_on": date.today().isoformat(),
        "snapshot_date": "2026-01-01",
        "publication": f"Data used is as of {as_of} (per the source page header)",
        "_unmatched_mappings": unmatched,
        "source_url": BETAS_URL,
        "industries": industries,
    }


# ── Country risk premiums ─────────────────────────────────────────────────

def scrape_country() -> tuple[dict[str, dict[str, Any]], str]:
    soup = _fetch(CTRY_URL)
    m = re.search(r"Last updated:\s*([A-Za-z]+ \d{1,2}, \d{4})", _norm(soup.get_text(" ")))
    updated = m.group(1) if m else "unknown"

    target = None
    for table in soup.find_all("table"):
        first = table.find_all("tr")[0]
        head = [_norm(c.get_text(" ", strip=True)) for c in first.find_all(["td", "th"])]
        if head and head[0].lower() == "country":
            target = table
            break
    if target is None:
        raise RuntimeError("country page has no Country table — layout changed")

    out: dict[str, dict[str, Any]] = {}
    for row in target.find_all("tr")[1:]:
        cells = [_norm(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        if len(cells) < 5 or not cells[0]:
            continue
        crp, erp = _pct(cells[3]), _pct(cells[4])
        if crp is None:
            continue
        out[cells[0]] = {
            "moodys_rating": cells[1] or None,
            "adj_default_spread_pct": _pct(cells[2]),
            "country_risk_premium_pct": crp,
            "total_equity_risk_premium_pct": erp,
            "corporate_tax_rate_pct": _pct(cells[5]) if len(cells) > 5 else None,
        }
    return out, updated


def build_country_payload(raw: dict[str, dict[str, Any]], updated: str) -> dict[str, Any]:
    # ── US CRP must be zeroed for OUR composition, and here is why ──
    # Damodaran's Jan-2026 table uses a mature-market base ERP of 4.23% (every
    # Aaa sovereign — Germany, Sweden, Canada — shows CRP 0.00 and total ERP
    # 4.23%). The US is no longer in that group: Moody's rates it Aa1, so it
    # carries CRP 0.23% and a total ERP of 4.46%.
    #
    # But `compute_wacc` composes total_erp = mature_market_erp + CRP, and
    # sources mature_market_erp from implied_erp.json — the implied ERP derived
    # from S&P 500 prices and cash flows. That number is ALREADY the US equity
    # risk premium; it embeds whatever risk the US market carries. Adding the
    # 0.23% US CRP on top double-counts US sovereign risk.
    #
    # Two coherent conventions exist:
    #   (a) US-implied ERP as the US total  → US CRP = 0        ← ours
    #   (b) Aaa base + country CRP          → US = 4.23 + 0.23
    # Mixing them is the error. So the lookup used by the WACC engine gets 0.0
    # for the US, while Damodaran's verbatim 0.23% is preserved in `_detail`
    # for audit. This is composing two sources correctly, not overriding data.
    lookup = {k: v["country_risk_premium_pct"] for k, v in raw.items()}
    us_verbatim = lookup.get("United States")
    lookup["United States"] = 0.0

    return {
        "_doc": (
            "Country risk premiums (CRP) added to the base equity risk premium for "
            "non-US filers. Damodaran computes these from sovereign default spreads "
            "scaled by an equity-vs-bond volatility ratio."
        ),
        "_source": ("Damodaran 'Country Default Spreads and Risk Premiums' — "
                    "ctryprem.html, parsed verbatim"),
        "_refresh_cadence": "annual — Damodaran updates in early January",
        "_staleness_warning_days": 400,
        "_methodology": (
            "Total ERP = mature_market_erp + country_risk_premium. Damodaran's Aaa "
            "baseline ERP in this table is 4.23%; the US carries CRP 0.23% (Moody's "
            "Aa1). We zero the US — see _us_crp_zeroed."
        ),
        "_us_crp_zeroed": {
            "damodaran_verbatim_pct": us_verbatim,
            "used_in_lookup_pct": 0.0,
            "reason": (
                "implied_erp.json is the S&P-500-derived US equity risk premium and "
                "already embeds US sovereign risk. Adding Damodaran's US CRP "
                f"({us_verbatim}%, Moody's Aa1) on top would double-count it. "
                "Verbatim value retained under _detail['United States']."
            ),
        },
        "_refreshed_by": "scripts/refresh_damodaran_reference.py",
        "_refreshed_on": date.today().isoformat(),
        "snapshot_date": "2026-01-05",
        "publication": f"Last updated: {updated} (per the source page header)",
        "source_url": CTRY_URL,
        # Flat lookup consumed by cost_of_capital._country_risk_premium.
        "country_premiums_pct": lookup,
        "_detail": raw,
    }


def scrape_risk_free_rates() -> tuple[dict[str, Any], list[str]]:
    """One sovereign 10yr yield per currency, verbatim. → (rates, failures).

    A series that 404s or returns no observations is reported as a FAILURE and
    omitted — never silently backfilled from USD. ADR-043 §2.2: a silent USD
    fallback would recreate the exact bug this ADR fixes, while leaving a
    provenance trail claiming it was fixed.
    """
    rates: dict[str, Any] = {}
    failures: list[str] = []

    for currency, (series, cadence, stale_days) in _RF_SERIES.items():
        try:
            resp = httpx.get(FRED_CSV, params={"id": series}, headers=_UA,
                             timeout=60, follow_redirects=True)
        except httpx.HTTPError as exc:
            failures.append(f"{currency}/{series}: {exc.__class__.__name__}")
            continue
        if resp.status_code != 200 or "," not in resp.text:
            failures.append(f"{currency}/{series}: HTTP {resp.status_code}")
            continue
        # FRED marks non-observations with '.'; keep the last real datapoint.
        rows = [ln for ln in resp.text.strip().splitlines()[1:] if not ln.endswith(",.")]
        if not rows:
            failures.append(f"{currency}/{series}: no observations")
            continue
        obs_date, raw = rows[-1].split(",")
        value = _pct(raw)
        if value is None:
            failures.append(f"{currency}/{series}: unparseable value {raw!r}")
            continue
        rates[currency] = {
            "pct": value,
            "snapshot_date": obs_date,
            "series": series,
            "cadence": cadence,
            "staleness_warning_days": stale_days,
        }
    return rates, failures


def build_risk_free_payload(rates: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    usd = rates.get("USD", {})
    return {
        "_doc": (
            "Sovereign 10yr government bond yield PER CURRENCY. Used as the "
            "risk-free rate for cash flows in that currency, and as the ceiling "
            "on terminal growth. Damodaran's first consistency check is that the "
            "risk-free rate matches the cash-flow currency (ADR-043)."
        ),
        "_source": "FRED — DGS10 for USD; OECD long-term interest rates (IRLTLT01*) otherwise",
        "_refresh_cadence": "weekly for USD (daily series); monthly for the OECD series",
        "_selection_rule": (
            "Look up by the filer's REPORTING currency (Company.currency). A "
            "currency absent from rates_by_currency is a data gap and the "
            "valuation refuses — it is NEVER silently substituted with USD."
        ),
        "_refreshed_by": "scripts/refresh_damodaran_reference.py",
        "_refreshed_on": date.today().isoformat(),
        "_unresolved_series": failures,
        # Back-compat: pre-ADR-043 readers expect these two top-level keys.
        # Retained so a stale consumer degrades to the USD rate it already
        # assumed, rather than KeyError-ing.
        "snapshot_date": usd.get("snapshot_date"),
        "ten_year_treasury_yield_pct": usd.get("pct"),
        "_staleness_warning_days": 7,
        "currency": "USD",
        "source_url": "https://fred.stlouisfed.org/series/DGS10",
        "rates_by_currency": rates,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print a diff, write nothing")
    args = ap.parse_args()

    raw_betas, as_of = scrape_betas()
    betas = build_betas_payload(raw_betas, as_of)
    raw_ctry, updated = scrape_country()
    ctry = build_country_payload(raw_ctry, updated)
    raw_rf, rf_failures = scrape_risk_free_rates()
    rf = build_risk_free_payload(raw_rf, rf_failures)

    print(f"betas:     {len(raw_betas)} industries parsed (source as of {as_of})")
    print(f"           {len(betas['industries']) - 1} mapped into our universe")
    if betas["_unmatched_mappings"]:
        print(f"           UNMATCHED: {betas['_unmatched_mappings']}")
    print(f"countries: {len(raw_ctry)} parsed (last updated {updated})")
    print(f"risk-free: {len(raw_rf)}/{len(_RF_SERIES)} currencies resolved")
    if rf_failures:
        print(f"           UNRESOLVED (omitted, NOT defaulted to USD): {rf_failures}")
    for cur, meta in sorted(raw_rf.items()):
        print(f"             {cur}  {meta['pct']:5.2f}%  {meta['snapshot_date']}"
              f"  ({meta['series']})")

    # Diff against what is on disk so a refresh never lands silently.
    for fname, payload, key in (
        ("industry_betas_us.json", betas, "industries"),
        ("country_erp.json", ctry, "country_premiums_pct"),
        ("risk_free_rate.json", rf, "rates_by_currency"),
    ):
        path = REF_DIR / fname
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8")).get(key, {})
            new = payload[key]
            print(f"\n-- {fname} changes --")
            for k in sorted(set(old) | set(new)):
                if k.startswith("_"):
                    continue
                o = old.get(k)
                n = new.get(k)
                def _val(x):
                    if not isinstance(x, dict):
                        return x
                    # betas keep "unlevered_beta"; risk-free entries keep "pct"
                    return x.get("unlevered_beta", x.get("pct"))
                ov, nv = _val(o), _val(n)
                if ov != nv and (ov is not None or nv is not None):
                    delta = ""
                    if isinstance(ov, (int, float)) and isinstance(nv, (int, float)) and nv:
                        delta = f"  ({(ov - nv) / nv * 100:+.1f}% prior error)"
                    print(f"   {k:42} {ov} -> {nv}{delta}")
        if not args.dry_run:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            print(f"   WROTE {path}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
