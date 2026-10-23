# ADR-038 — Non-SEC International Issuer Fundamentals (Canadian + European + Australian + AIM)

**Status**: Draft
**Date**: 2026-05-19
**Phase**: TBD
**Related**: ADR-022 (source-provenance discipline), ADR-025 (IFRS / FPI universe — SEC-filing only), ADR-031 (data gap register), ADR-033 (SEC-first compute-don't-pull)
**Resolves**: Enables deep-dive on issuers that do NOT file 20-F/40-F with SEC — Canadian TSX/TSX-V, UK AIM/LSE, European ESEF (Sweden / Norway / Germany / Poland), Australian ASX. Today these tickers fail at the Company-row level because the universe builder is SEC-EDGAR-only.

## Context

### What ADR-025 already covers — and what it doesn't

ADR-025 (Accepted + Implemented Phase 5W, 2026-05-17) extended `data/edgar_companyfacts.py` to read the `ifrs-full` XBRL taxonomy in addition to `us-gaap`. This unlocks Foreign Private Issuers (FPIs) like SRAD (Swiss-domiciled, NASDAQ-listed) that file 20-F annual reports with the SEC tagged in IFRS.

**The constraint ADR-025 does not address**: it only covers issuers that file SEC reports at all. The data path is still `SEC EDGAR companyfacts.json → keyed by CIK`. Issuers without a CIK don't have a path.

Most of the international quality-investor watchlist universe never files with the SEC:

| Ticker | Name | Exchange | Filer regime |
|---|---|---|---|
| TOI.V | Topicus | TSX Venture | SEDAR+ (Canadian) — 40-F lite via parent CSU |
| LMN.V | Lumine Group | TSX Venture | SEDAR+ |
| CHG.DE | Chapters Group | Frankfurt (Xetra) | BaFin / ESEF iXBRL |
| KPG.AX | Kelly Partners Group | ASX | ASX continuous disclosure |
| TEQ.ST | Teqnion | Stockholm | Finansinspektionen / ESEF iXBRL |
| ROKO.ST | Roko | Stockholm | ESEF iXBRL |
| DNP.WA | Dino Polska | Warsaw | ESEF iXBRL |
| AT.L | Ashtead Technology | London AIM | UK Companies House iXBRL |
| TVK.TO | TerraVest Industries | TSX | SEDAR+ |
| VHI.TO | VitalHub | TSX | SEDAR+ |
| SMCRT.OL | SmartCraft | Oslo | ESEF iXBRL |
| JDG.L | Judges Scientific | London AIM | Companies House iXBRL |
| SDI.L | SDI Group | London AIM | Companies House iXBRL |

Empirical universe state (2026-05-19): of the 14-ticker user wishlist, only 2 have Company rows (TOI as a stub with no data, KFS as a US filer). The other 12 cannot be deep-dived today because:

1. **No Company row exists** — universe build is bound to SEC EDGAR (`data/universe.py`)
2. **No fundamentals fetcher path** — `FundamentalsTask` queries `companyfacts/CIK{cik}.json` which 404s for non-filers
3. **No yfinance-fundamentals adapter** — yfinance is currently used for `info` snapshot + price history + earnings_dates (EPS), NOT multi-year revenue / income statement / balance sheet

Quality-compounder and serial-acquirer research is meaningfully constrained by this gap: Topicus, Lumine, Judges Scientific and Teqnion are exactly the kind of names a quality-tilted screen surfaces.

### Constraint: ADR-022 §1.4 source-provenance discipline

ADR-022 requires every Financial field to carry a source tag. The deterministic path is:
- **Tier 1A**: SEC XBRL (us-gaap / ifrs-full) — primary
- **Tier 1B**: edgartools
- **Tier 2**: self-computed
- **Tier 3**: third-party APIs (Polygon 0.95, yfinance 0.85, FMP 0.80)
- **Tier 4**: manual / LLM

Pulling fundamentals from yfinance for non-SEC issuers means populating `Financial.revenue` (and friends) with **Tier 3 data** rather than the Tier 1A SEC XBRL we use for US issuers. This is methodology asymmetry: US tickers get audited SEC primary data; international tickers get scraped Yahoo data.

ADR-025 chose **path 1** (extend SEC parser) over **path 2** (yfinance adapter) precisely because path 2 violates source-provenance discipline. This ADR has to confront the same trade-off honestly, because for non-SEC issuers, **there is no SEC primary data to extend**.

### What the proper per-jurisdiction parsers would require

| Jurisdiction | Primary source | Format | API access | Effort estimate |
|---|---|---|---|---|
| Canada (SEDAR+) | sedarplus.ca | iXBRL since 2024 transition | No public REST API; HTML scraping required | High (4-6 wk) |
| UK (Companies House) | find-and-update.company-information.service.gov.uk | iXBRL for annual accounts | Free REST API with key | Medium (2-3 wk) |
| EU (ESEF) | ESMA OAM Hub OR per-country OAM | iXBRL since 2020 | OAM Hub: aggregated; per-country: scattered | High (8-12 wk for full coverage) |
| Australia (ASX) | asx.com.au announcements | PDFs primarily; iXBRL adoption limited | Free announcements API; financial data scraping required | Medium-High (4-6 wk) |

Full Phase-2 build = **~20-30 weeks of focused work** across 4 data planes. Not feasible as a near-term unlock.

### What yfinance can actually deliver

yfinance exposes `Ticker.financials` (income statement, 4 years annual + 4Q), `Ticker.balance_sheet` (4yr + 4Q), `Ticker.cashflow` (4yr + 4Q) for international tickers including the wishlist above. Validation needed — historical depth varies by ticker (some return only 3 years; small AIM names sometimes blank).

Field mapping is straightforward — yfinance returns DataFrames with standardised line-item names that map cleanly to our `Financial` schema (revenue, operating_income, net_income, total_assets, total_equity, total_debt, operating_cash_flow, capex, etc.).

What yfinance **does not** provide:
- Form 4 insider transactions (US-only by construction)
- DEF 14A proxy / management compensation
- 10-K text (no patent disclosure, no MD&A language ratio)
- Per-XBRL-concept granularity (no separate R&D line if the filer bundles it)
- ROIC consistency over long history (4 years is the typical depth)

This means a yfinance-fundamentals-based deep dive can produce:
- F1 (Piotroski) with limited 4yr history — feasible
- F3 (Innovation) — GM trajectory feasible; R&D intensity often missing for non-tech non-pharma
- F5 (Growth Quality) — limited 4yr history hurts
- F7 (Smart Beta valuation z-scores) — needs 10yr history; infeasible
- BEW overlay — feasible (uses price + market_cap + sector)
- ICA overlay — limited (needs R&D + SG&A history; often unavailable from yfinance for non-US)
- Damodaran IV — feasible at Tier A (mature, profitable) with the 4yr window; cyclical normalization infeasible

A yfinance-tier non-SEC deep dive is structurally **shallower** than a US deep dive. That's an honest constraint, not a hidden one.

## Decision

### Two-phase commitment

**Phase 1 (this ADR's scope)** — **yfinance fundamentals adapter for non-SEC issuers**, plug into deep dive only. Universe screener integration deferred.

**Phase 2 (deferred)** — proper per-jurisdiction XBRL parsers, prioritized by user demand:
- Phase 2a: UK Companies House (easiest API; covers JDG.L / SDI.L / AT.L)
- Phase 2b: ESEF EU (TEQ.ST / ROKO.ST / DNP.WA / CHG.DE / SMCRT.OL)
- Phase 2c: SEDAR+ Canada (TOI.V / LMN.V / TVK.TO / VHI.TO)
- Phase 2d: ASX Australia (KPG.AX)

Phase 2 is in scope for separate ADRs, not this one.

### Phase 1 design — yfinance fundamentals adapter

**1. New ticker resolution path**

`data/universe.py` currently builds Company rows from SEC EDGAR `companyfacts/*` enumeration. Add a parallel `add_non_sec_ticker(ticker, exchange, ...)` helper that:
- Skips the CIK requirement
- Sets `cik=None`, `status='watchlist'` (NOT `screener_candidate` — keeps non-SEC names out of bulk screening until Phase 2 lifts the data-quality concern)
- Pulls metadata from `yfinance.Ticker.info` (longName, sector, industry, exchange, market_cap)
- Tags `Company.data_source_tier = 'yfinance_only'` (new column) so downstream consumers know this row's fundamentals are Tier-3 sourced

User-facing CLI command: `invest watchlist add TOI.V` resolves the symbol via yfinance and creates the row, ready for `invest dive`.

**2. New fundamentals fetcher path**

`data/pipeline.py:refresh_ticker` decision tree:
```
if company.cik is set and SEC companyfacts available:
    → existing SEC EDGAR path (Tier 1A — ADR-025 IFRS-extended)
else:
    → new yfinance fundamentals adapter (Tier 3)
```

The yfinance adapter (`data/api/yfinance_fundamentals.py`, new file) pulls `Ticker.financials` / `.balance_sheet` / `.cashflow`, maps to `Financial` schema, persists with `Financial.{field}_source = 'yfinance'` per ADR-022 source-tagging.

**3. Source-tagging propagates downstream**

Existing `composite_score` / `data_completeness` calculations already differentiate source tiers (per ADR-033). A yfinance-tier-3 ticker will score lower on completeness than a SEC-tier-1A ticker — that's intentional: the watchlist UI should make the data-quality difference visible.

`framework_score`'s `_classify_company_stage` and downstream signals run unchanged on the resulting `Financial` rows. F7 (10yr z-scores) will return `InsufficientHistoryError` for most non-SEC names — that's the existing graceful-degradation path, not a bug.

**4. Currency handling**

yfinance returns numbers in the filer's reporting currency. Per ADR-025 §1.3, we already have `Financial.reporting_currency` + `fx_rate_to_usd` columns. The yfinance adapter uses `Ticker.info.financialCurrency` to populate `reporting_currency`, then applies the same ECB FX conversion ADR-025 already uses. **No new currency infrastructure needed.**

**5. Provenance disclosure in the dive output**

When `invest dive TICKER` runs on a yfinance-tier-3 ticker, the methodology disclosure panel (Stage 0c per ADR-022) explicitly states:
> *"This dive uses yfinance Tier-3 fundamentals data. SEC EDGAR primary XBRL is not available because {ticker} files only with {jurisdiction-regulator}. Data depth is limited to ~4 annual periods; F7 valuation z-scores (10yr requirement) unavailable; insider/proxy/10-K text signals unavailable. See ADR-038."*

This is the discipline relaxation — yfinance becomes a documented data path with an explicit caveat, not a silent fallback.

### What this ADR does NOT decide

- **No universe-screener integration**: non-SEC tickers stay in `status='watchlist'`, not `screener_candidate`. They're invisible to `invest screen-winners`. (Per the user's stated scope: "think about universe screener or screener workflow later.")
- **No automatic enrichment**: `invest watchlist add TOI.V` requires user invocation per ticker. No bulk ingestion of foreign exchanges.
- **No new framework adjustments**: F1-F7 run as-is; gaps surface via existing `InsufficientHistoryError` / `data_gaps`.
- **No FX-rate backfill**: existing ECB FX table per ADR-025 §1.3 is reused.

## Architecture

```
data/
├── universe.py
│     add_non_sec_ticker(ticker, exchange) — NEW helper
├── pipeline.py
│     refresh_ticker() — branches on cik presence
├── api/
│   ├── yfinance_client.py            (unchanged — info / price / earnings_dates)
│   └── yfinance_fundamentals.py      NEW — multi-year financials / balance / cashflow
└── ...

cli/main.py
│  watchlist add TOI.V — NEW resolves + materializes via yfinance adapter
└─ dive TOI.V — works after add (existing command, unchanged)
```

Schema migration: add `Company.data_source_tier TEXT` column.

```sql
ALTER TABLE companies ADD COLUMN data_source_tier TEXT DEFAULT 'sec_edgar';
```

Existing rows default to `'sec_edgar'`. Phase-1 non-SEC ingests set `'yfinance_only'`.

## Constraints (per CLAUDE.md + existing ADRs)

- **Deterministic** — yfinance is a deterministic-given-time data source. No LLM, no judgement calls in the data layer. Tier-3 tag makes the data-quality difference auditable.
- **Lazy-load** — Non-SEC tickers ingested only on explicit `invest watchlist add`. No background bulk fetch.
- **Source-provenance preserved** — Every `Financial.{field}_source` carries the actual source (`yfinance` vs `sec_xbrl`). `composite_score` and `data_completeness` already penalize Tier-3 fields.
- **ADR-031 two-permitted-Anthropic-call-sites rule preserved** — yfinance is a third-party deterministic API, not an LLM call.
- **Watchlist-scope only** — Per user's stated scope. No universe-screener pollution.

## Alternatives considered

### Alt 1 — Wait for Phase 2 (proper per-jurisdiction XBRL parsers)

**Pros**: Preserves ADR-022 source-provenance discipline fully. All Financial rows are Tier-1A regulator XBRL.

**Cons**: 20-30 weeks of work. Owner has named 14 tickers TODAY that they want to evaluate. The proper-engineering ideal blocks the user's actual research need by months.

**Verdict**: Rejected. Phase 1 yfinance adapter is the **pragmatic bridge**. Phase 2 still ships, just doesn't block today's work.

### Alt 2 — Use Financial Modeling Prep (FMP) instead of yfinance

**Pros**: FMP has cleaner international fundamentals than yfinance for some jurisdictions. Already in the project dependency list (per `pyproject.toml`).

**Cons**: FMP's free tier (250 req/day) is fragile for any usage above watchlist-scale. Paid tier costs money. yfinance is rate-limited but free at scale.

**Verdict**: yfinance preferred for Phase 1. FMP could be added later as a yfinance-failover ("if yfinance returns < 2 years of revenue, try FMP") if empirical coverage gaps justify.

### Alt 3 — Manual JSON ingestion for the 14 named tickers

**Pros**: Bypasses all data-source plumbing. User pastes fundamentals from any source they trust.

**Cons**: Doesn't scale beyond the immediate 14. Defeats the purpose of an investment-research system. Manual data entry introduces transcription errors that no source-tag can detect.

**Verdict**: Rejected.

### Alt 4 — Skip non-SEC issuers entirely; document as out-of-scope

**Pros**: Cleanest scope discipline. The system stays US-focused.

**Cons**: Eliminates ~30% of the quality-compounder universe (UK AIM smallcaps, Canadian serial acquirers like the Constellation Software family, EU industrial compounders). Owner's FIRE thesis is explicitly international.

**Verdict**: Rejected. The screened universe is meant to be broader than the US.

## Consequences

### Code surface added

| File | Lines (est) | Purpose |
|---|---|---|
| `data/api/yfinance_fundamentals.py` | ~250 | Multi-year financials adapter |
| `data/universe.py` (extension) | ~80 | `add_non_sec_ticker()` helper |
| `data/pipeline.py` (extension) | ~50 | Branch on cik presence in `refresh_ticker` |
| `cli/main.py` (extension) | ~30 | `invest watchlist add` command |
| `alembic/versions/aa1b...py` | ~15 | `companies.data_source_tier` migration |
| `tests/test_yfinance_fundamentals.py` | ~150 | Fixture-based unit tests |

**Total**: ~575 LOC. Realistic effort: 4-8 hours of focused dev + 2-4 hours of validation on the 14-ticker set.

### Warehouse impact

- New column `data_source_tier` on `companies` (default 'sec_edgar' for existing 10,143 rows)
- New `Financial` rows for the 12 currently-missing tickers, marked `_source='yfinance'`
- TOI's empty stub row gets fundamentals (it has a CIK but no SEC data — branch detection: `if cik IS NOT NULL but companyfacts returns 404 then route to yfinance`)
- Watchlist gets 14 new entries with `data_source_tier='yfinance_only'`
- `screener_candidate` table unchanged — no Phase 1 pollution of universe screen

### Behavioural changes

- `invest watchlist add TOI.V` creates Company row + fetches fundamentals — new behavior, opt-in per ticker
- `invest dive TOI.V` works post-add, runs F1/F3/F5/etc. on yfinance-Tier-3 data, surfaces "Data source: yfinance" panel in output
- `data_completeness` reports lower scores for yfinance-tier tickers (correct behaviour per ADR-033)
- `invest screen-winners` unaffected — non-SEC tickers stay in watchlist scope, not universe scope

### What users will see

For a successful Phase 1 ingest of, say, JDG.L (Judges Scientific):

```
$ invest watchlist add JDG.L
→ Resolving JDG.L via yfinance...
→ Company: Judges Scientific plc (London AIM, GBP)
→ Fetching fundamentals (yfinance Tier-3, 4yr depth)...
→ FX: GBPUSD applied at period end dates
→ Persisted 4 annual + 4 quarterly Financial rows
→ Status: watchlist (data_source_tier=yfinance_only)

$ invest dive JDG.L --tier 2 --auto-overlays
=== Methodology disclosure (ADR-038) ===
Source: yfinance Tier-3 (JDG.L files with UK Companies House;
SEC EDGAR XBRL not available)
Depth: 4 annual periods (vs typical 10yr for US issuers)
Unavailable: F7 z-scores, insider transactions, proxy data, patent disclosure
======================================
... [normal dive output] ...
```

The user gets a working dive that's clearly labeled as yfinance-tier. Composite scores comparable to US issuers on a like-for-like basis (F1, F3, F5 use the data we have; F7 surfaces "unfeasible" cleanly).

## Risks

| Risk | Mitigation |
|---|---|
| yfinance International coverage is patchy (some tickers return < 2 years) | The Financial-row INSERT fails gracefully; `InsufficientHistoryError` propagates to the dive layer; user sees explicit "insufficient yfinance history" rather than silent zero. |
| yfinance rate-limits (Yahoo soft-blocks above 1 req/sec sustained per ADR-019) | Reuse existing `YF_BUCKET` in `data/rate_limit.py` (1 req/sec); add per-ticker request budget. |
| FX rate distortion for cyclical currencies (e.g., TRY, ARS) | Out of Phase-1 scope; user's wishlist is GBP/EUR/CAD/AUD/SEK/NOK/PLN — all G7/G20 with stable ECB-published rates. |
| yfinance's `financialCurrency` field occasionally wrong (e.g., reports USD for non-US filer) | Cross-check against exchange suffix (`.TO`→CAD, `.L`→GBP, `.ST`→SEK); emit data_gap on mismatch. |
| Source-provenance discipline degradation (slippery slope: once yfinance-tier-3 fundamentals are accepted, future tickers default to yfinance even when SEC data exists) | Hard rule in `refresh_ticker`: cik-present + companyfacts-200-ok → SEC path mandatory. yfinance path **only** when SEC returns 404 OR cik is None. |
| Non-SEC tickers pollute future screener runs | `screener_candidate` status guard. Phase 2 ADRs revisit when proper XBRL parsers ship. |
| User confuses watchlist depth (yfinance) with screener depth (SEC) | Stage 0c methodology panel surfaces tier explicitly per dive. Watchlist CLI list view tags each row with tier. |

## Validation plan

### Acceptance criteria for Phase 1

Phase 1 ships if and only if:

1. **All 14 named tickers ingest cleanly** via `invest watchlist add` — minimum 3 years of annual `revenue` populated for each, with `financialCurrency` correctly identified.
2. **At least 10 of 14 produce a successful Tier-2 dive** with F1 (Piotroski) + F3 (Innovation) + BEW overlay all running (F5/F7 may fail gracefully on history).
3. **No silent failures** — every degradation surfaces via `data_gaps` entry.
4. **Source-provenance audit passes** — `Financial.{field}_source = 'yfinance'` for every Phase-1-ingested row; existing SEC-tier rows untouched.
5. **Backward-compatibility test** — re-running `invest task run fundamentals` does NOT overwrite a yfinance-tier-3 row with `cik=None` failures. (Already covered by existing pending-set logic but re-verify.)

### Spot-check expectations on the 14-ticker wishlist

| Ticker | Expected outcome | Why |
|---|---|---|
| TOI (Topicus, stub w/ CIK) | yfinance path triggered (CIK present but companyfacts empty); 4yr data; F1+F3 runable | Edge case: has CIK but no data |
| LMN.V (Lumine) | New row + yfinance data; F1+F3 runable | Pure Canadian, no SEC presence |
| JDG.L (Judges Scientific) | 4yr fundamentals in GBP→USD; F1 passes (profitable serial acquirer); F7 unfeasible | UK AIM — known good yfinance coverage |
| DNP.WA (Dino Polska) | PLN→USD; F1+F3 runable; F5 partial | Polish retailer — yfinance coverage less validated; possible blank fields |
| KPG.AX (Kelly Partners) | AUD→USD; small-cap; F1 likely tight on history | ASX small-cap; data depth varies |
| KFS (already in DB) | No change — existing SEC path runs | Already works |

### Failure modes the validation should catch

- A ticker that yfinance can resolve as `Ticker.info` (name + sector populated) but `.financials` returns empty → `InsufficientDataError` surfaced cleanly
- A ticker where yfinance returns financials in USD but the filer reports in CAD → `financialCurrency` cross-check fires; data_gap added
- A ticker where 1 of 4 expected annual rows is missing → Financial-row INSERT succeeds for the 3 valid years; F5 graceful-degrades

## Out of scope

- Phase 2 proper XBRL parsers (Companies House / ESEF / SEDAR+ / ASX) — separate ADRs
- Bulk ingestion of foreign exchanges (e.g., "import all FTSE-AIM") — explicitly per-ticker only in Phase 1
- Universe-screener integration (`invest screen-winners` access to non-SEC tickers) — deferred per user's stated scope
- Alternative international fundamentals providers (FMP / Alpha Vantage / SimplyWallSt) — Phase-3 consideration if yfinance proves inadequate
- DEF 14A / proxy equivalents for non-US filers (UK AR&A, Canadian Information Circular, EU Annual Reports) — separate text-parser ADR
- Non-G20 currencies (TRY / ARS / RUB / etc.) — current FX table per ADR-025 §1.3 covers G7/G20

## Why this ADR exists

User intervention 2026-05-19: requested deep dives on a 14-ticker international wishlist (Topicus, Lumine, Chapters Group, Kelly Partners, Teqnion, Roko, Dino Polska, Ashtead Technology, TerraVest, Kingsway, VitalHub, SmartCraft, Judges Scientific, SDI Group). Empirical universe-presence check revealed 12 of 14 missing entirely; 1 stub-only (TOI); 1 working (KFS, full US filer). The owner explicitly scoped this as a **plug-into-dive** request, not a universe-screener integration: "for now let's write an ADR to plug into the deep dives if it easy and think about universe screener or screener workflow later."

This ADR is the proper alternative to the prior session's anti-pattern (shipping F3 multiplier changes without an ADR, then reverting under pushback). Discipline this time: write the ADR first; validate the data path empirically before code; accept that yfinance-Tier-3 is methodologically inferior to SEC-Tier-1A and document the trade-off explicitly.

## References

- ADR-022 — Methodology disclosure and source provenance (Tier 1-4 framework)
- ADR-025 — IFRS / FPI universe support (SEC-filing FPIs only; this ADR extends to non-SEC)
- ADR-031 — Data gap register
- ADR-033 — SEC-first source hierarchy (Phase 1 yfinance fundamentals is the explicit exception)
- yfinance project documentation: https://github.com/ranaroussi/yfinance (Ticker.financials / .balance_sheet / .cashflow surface)
- ESMA ESEF reporting: https://www.esma.europa.eu/policy-activities/corporate-disclosure/european-single-electronic-format (Phase 2 reference)
- Companies House developer hub: https://developer.company-information.service.gov.uk (Phase 2 reference)
- SEDAR+ data: https://www.sedarplus.ca (Phase 2 reference; no public API as of 2026)
