# Damodaran reference data — provenance log

All files in this directory are **vendored snapshots** from Aswath Damodaran's
public data pages at https://pages.stern.nyu.edu/~adamodar.

**Refresh discipline** (per ADR-027 §Resolutions):
- `implied_erp_*.json` — monthly (Damodaran updates first week of each month)
- `industry_betas_*.json` — quarterly (Jan / Apr / Jul / Oct)
- `country_erp_*.json` — quarterly
- `tax_rates_*.json` — annually (or when policy changes)
- `risk_free_rate.json` — weekly (10yr Treasury yield)

`IVResult.reference_data_staleness_days` auto-flags files older than 100 days
but does NOT block the calc. The calc keeps working with stale data; the
warning is loud in the dive output and the `data_gaps[]` list.

## How to refresh

Each JSON file has a `source_url` field pointing at Damodaran's specific
page. To refresh:

1. Download the latest XLS/HTML from `source_url`
2. Update the JSON file in place (preserve schema)
3. Bump `snapshot_date`
4. Commit with message: `refresh: damodaran <file> <new_snapshot_date>`

## Current snapshot status

| File | Source | Last refresh | Status as of 2026-08-16 |
|---|---|---|---|
| `risk_free_rate.json` | FRED DGS10 | **2026-08-13** | 3 days ✅ |
| `implied_erp.json` | Damodaran home page | **2026-08-01** | 15 days ✅ |
| `industry_betas_us.json` | Betas.html | **2026-01-01** (source data) | current ✅ — source itself is annual |
| `country_erp.json` | ctryprem.html | **2026-01-05** (source data) | current ✅ — source itself is annual |
| `tax_rates.json` | (statutory rates) | 2026-01-01 | 227 days (annual cadence — due Jan 2027) |
| `iso2_countries.json` | ISO-3166 → Damodaran country names | static | changes only when ADR-041's registry gains a jurisdiction |

**Cadence correction (2026-08-16).** This file previously claimed betas and
country premiums refresh *quarterly*. They do not — Damodaran recomputes both
each January ("Data used is as of January 2026"; "Last updated: January 5,
2026"). The old `snapshot_date` of 2026-04-01 on the beta file therefore
claimed a Q2-2026 publication **that has never existed**. Both files now carry
the true source dates and a 400-day staleness threshold matching the real
annual cadence.

## Refreshing

Do NOT hand-edit these files. Run:

```bash
uv run python scripts/refresh_damodaran_reference.py --dry-run   # show the diff
uv run python scripts/refresh_damodaran_reference.py             # apply
```

The script parses Damodaran's published HTML tables verbatim (httpx +
BeautifulSoup, deterministic, no API key) and prints a per-field diff before
writing. See the 2026-08-16 entry below for why this is a script and not a
documented manual procedure.

## Refresh log

### 2026-08-16 (part 2) — industry betas + country risk premiums

**This was not a staleness problem. The beta values were never sourced.**

INDEX.md's own "V0 calibration note" said the vendored values were
"approximate based on Damodaran's recent publications and macro conditions"
and instructed a real refresh "on first commit to main". That never happened.
Checked against the live table, **22 of 31 industries were off by more than
15%**:

| Industry | Was | Actual (Jan 2026) | Prior error |
|---|---|---|---|
| Financial Services (Non-bank) | 1.08 | **0.32** | +237% |
| Telecom Services | 0.78 | **0.37** | +111% |
| Real Estate (Development) | 0.95 | **0.48** | +98% |
| Healthcare Services | 0.85 | **0.55** | +55% |
| Insurance (General) | 0.82 | **0.56** | +46% |
| Education | 0.95 | **0.66** | +44% |
| Retail (Apparel) | 1.05 | **0.76** | +38% |
| Software (Internet) | 1.18 | **1.55** | −24% |
| Software (System & Application) | 1.05 | **1.23** | −15% |

Beta multiplies the ERP in the cost-of-equity term, so these fed straight into
every WACC and therefore every intrinsic value in the system. Most errors were
positive (beta too high → WACC too high → IV too low), but not all, so the bias
was not even consistent.

**Effect, measured across today's full reference pass** (rf + ERP + betas +
country premiums, start → now):

| Ticker | WACC | Forward IV | Franchise ratio |
|---|---|---|---|
| NVDA | 9.18% → **9.89%** | 59.66 → **56.78** | 4.11× → 3.82× |
| AAPL | 9.16% → **9.87%** | refused (both) | 3.49× → 3.24× |
| INTA | 9.17% → **9.88%** | 5.73 → **5.54** | −0.74× → −0.69× |
| BONEX.ST | 9.04% → **8.87%** | 38.15 → **38.94** | 1.30× → 1.33× |

Note the contrast with part 1: the rf+ERP refresh moved WACC ~6bps; the beta
correction moved US names ~71bps — **an order of magnitude more**. The file
flagged as "next" mattered far more than the one that was flagged as stale,
because staleness was never the real defect.

BONEX.ST moved the *other* way (−17bps) because healthcare betas corrected
downward and Sweden carries no country premium.

**Two composition decisions, both recorded in the JSON rather than buried:**

1. **US country risk premium zeroed.** Damodaran's Jan-2026 table now assigns
   the US a CRP of 0.23% (Moody's downgraded it to Aa1); his Aaa baseline ERP
   is 4.23%. But `compute_wacc` composes `mature_market_erp + CRP`, and sources
   `mature_market_erp` from `implied_erp.json` — the S&P-500-derived implied
   ERP, which *already embeds* US sovereign risk. Adding 0.23% on top
   double-counts. The lookup uses 0.0 for the US; Damodaran's verbatim 0.23% is
   preserved under `_detail["United States"]` and the reasoning under
   `_us_crp_zeroed`. Caught only because the refresh made the value non-zero
   for the first time.
2. **Industry-name mapping is now explicit.** Damodaran's row labels differ
   from our internal keys and contain typos ("Heathcare Information and
   Technology"). Each entry records `damodaran_industry` plus a `mapping`
   confidence: **18 exact, 7 renamed, 6 approximate**. The six approximations
   are our judgement calls (e.g. `Retail (Online)` → `Retail (Special Lines)`,
   `Healthcare Services` → `Hospitals/Healthcare Facilities`) and are labelled
   as such so they are never mistaken for sourced correspondences.

A process note worth keeping: the earlier analysis of this file initially
concluded 22 industry names "did not exist" in Damodaran's table. That was
wrong — a parser artifact. His HTML embeds newlines and tabs *inside* industry
names (`Software\n\t\t (System & Application)`), so an un-normalised parse
fails to match. The names existed; the values were wrong. `_norm()` in the
refresh script exists for exactly this reason.

### 2026-08-16 (part 1) — risk-free rate + implied ERP

| File | Before | After | Δ |
|---|---|---|---|
| `risk_free_rate.json` | 4.35% (2026-05-13) | **4.63%** (2026-08-13) | +28bps |
| `implied_erp.json` | 4.60% (2026-04-01) | **4.28%** (2026-08-01) | −32bps |

**Net effect on WACC: ≈ −6bps.** The two moves largely offset — the risk-free
rose while the equity risk premium compressed, the normal pattern when rates
rise without a change in risk appetite. Cost of equity for a beta-1.0 name went
8.95% → 8.91%.

Observed: NVDA 9.18% → 9.12%, AAPL 9.16% → 9.10%, INTA 9.17% → 9.11%,
BONEX.ST 9.04% → 9.00%. Forward IV moved correspondingly little
(NVDA $59.66 → $60.03).

**Read that result carefully.** The 95-day staleness was a real governance
failure but a small numerical one *this time*. Had both moved in the same
direction, the effect on a terminal-value-heavy DCF would have been material.
The reason to refresh is that you cannot know which case you are in until you
do — not that the last refresh happened to be cheap.

Sources (both public, no API key, deterministic parse):
- Risk-free: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`, last
  non-null observation taken verbatim (FRED marks holidays with `.`).
- ERP: Damodaran home-page headline — "Implied ERP on August 1, 2026 = 4.28%
  (Trailing 12 month, with adjusted payout)". He publishes five variants
  simultaneously (3.68%–6.25%); all five are recorded in the JSON, and the one
  selected is the measure he uses in his own valuations. **Choosing between
  variants moves cost of equity by up to 257bps — a larger decision than the
  refresh itself, and one worth revisiting deliberately.**

Damodaran paired his 4.28% with a treasury rate of 4.74% on 2026-08-01; we hold
4.63% from FRED on 2026-08-13. That 11bps mismatch is recorded in
`implied_erp.json._pairing_caveat` so it is not later rediscovered as a bug.

## V0 calibration note — ✅ RESOLVED 2026-08-16

> *Original text, kept for the record:* "The initial vendored values (May 2026)
> are **approximate** based on Damodaran's recent publications and macro
> conditions. For production use: 1. Download his current `wacc.xls` from the
> betas page 2. Replace the industry-beta values verbatim 3. Replace the
> implied ERP from `implpr.html` 4. Verify country premiums from
> `ctryprem.html`. Do this on first commit to main. The math machinery is
> correct; data freshness is a maintenance discipline."

All four steps are done, and the mechanism is now
`scripts/refresh_damodaran_reference.py` rather than a manual procedure.

The closing line of that note deserves amendment. "Data freshness is a
maintenance discipline" is what let approximate values sit in a file labelled
as vendored source data for three months, with a `snapshot_date` that made
them look freshly published. A discipline that depends on remembering to do
something, by hand, against a source that must be transcribed accurately, is
not a control — it is an intention.

The control is that a script cannot invent a beta. Anything in this directory
that cannot be regenerated by re-running the refresh script should be treated
as suspect until it can be.
