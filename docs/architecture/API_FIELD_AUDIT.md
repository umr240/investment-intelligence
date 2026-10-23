# API-Field Audit — what's still API-sourced, what should be SEC-derived

> Supplements **SEC_ENDPOINTS_INVENTORY.md** with a field-by-field migration plan.
> Date: 2026-05-15.
> Anchor: ADR-033 §1.1 source hierarchy + ADR-033 §4 forbidden patterns.

For each `Company.*` / `Financial.*` field that currently has an API source, this audit records:
1. **Current source** (where in code)
2. **Tier** (1A SEC raw / 1B edgartools / 2 self-computed / 3 API / 4 LLM)
3. **SEC alternative** (if any)
4. **Recommendation** (migrate / partial / keep / SEC-blind)
5. **Effort** estimate

---

## Phase 2 status (in-progress, 2026-05-16)

| Audit item | Field | Status | Source post-migration |
|---|---|---|---|
| B.3 | `ipo_date` | ✅ Done (Phase 1) | `sec_submissions` (Tier 1A) |
| B.2 | `ceo_total_pay` | ✅ Done (2026-05-16) | `sec_def14a` via edgartools `proxy.peo_total_comp` (Tier 1A). NVDA: $36.3M, HIMS: $22.96M, LULU: $14.55M, INTA: $14.92M — all match DEF 14A Summary Compensation Table. |
| C.3 | `exchange` | ✅ Done (2026-05-16) | `edgartools` via `Company.get_exchanges()` (Tier 1B) |
| B.1 | `shares_float` | ⏭️ Deferred | `EntityPublicFloat` is USD-denominated; shares-conversion requires API current_price (hybrid Tier 1A+3b). Alternative: `EntityCommonStockSharesOutstanding` gives shares-outstanding (not float — overstates by insider holdings). Both paths violate field semantics. Park until schema gains separate `shares_outstanding_sec` column. |
| C.2 | `currency` | ⏭️ Deferred | `dei:EntityReportingCurrencyISOCode` returns 404 for most US filers (USD is implicit, not explicitly tagged). Keep yfinance fallback. |
| B.4 | `institution_pct_latest` | 📋 Phase 3 | 13F aggregator task (~150 LOC) |
| B.5 | `insider_pct_latest` | 📋 Phase 3 | BeneficialHoldingsRegistry from Form 3+4+SC 13D (~250 LOC) |

---

## A. Already migrated (sanity check — DO NOT regress)

These were yfinance/FMP/Polygon-sourced earlier in the project's history and were moved to SEC primary as part of the Tier-1.1-through-2.5 substitution cycle. Listed here so a future contributor doesn't accidentally rewire them.

| Field | Current source | Migration date | Reference |
|---|---|---|---|
| `pe_trailing` | `valuation/sec_derived_ratios.py` (mc/TTM-NI) | 2026-05-15 | ADR-033 §4 #1 |
| `pb_ratio` | `valuation/sec_derived_ratios.py` (mc/equity) | 2026-05-15 | ADR-033 §4 #1 |
| `ev_ebitda` | `valuation/sec_derived_ratios.py` ((mc+netdebt)/TTM-EBITDA) | 2026-05-15 | ADR-033 §4 #1 |
| `beta` | `valuation/sec_derived_beta.py` (PriceHistory vs SPY 5yr weekly) | Tier 2.5 | ADR-033 §1.1 |
| `industry` | `data/edgar_fetcher.py:fetch_sec_industry_classification` (SIC primary, yfinance fallback) | Tier 1.1 | `sector_source` column records origin |
| `sic_code`, `filer_category`, `is_smaller_reporting_company`, `is_financial_institution`, `is_fund` | edgartools `Company.*` flags | Tier 1.3 | schema.py:97-101 |
| `ceo_name` | `data/edgar_fetcher.py:fetch_edgar_proxy_ownership` (DEF 14A `peo_name`, yfinance fallback) | Tier 1, then 2026-05-15 LULU fix | Frank-vs-McDonald incident |
| `ceo_equity_pct` | SC 13D/A Item 5 Row 13 PRIMARY → DEF 14A SECONDARY → 6-K MIC TERTIARY | ADR-031 §1.3 priority chain | HIMS Dudum 11.1% case |
| `ceo_tenure_years` | DEF 14A proxy parser | pre-2026 | `data/edgar_fetcher.py:1412` |
| `is_founder_ceo` | DEF 14A + edgartools-derived | pre-2026 | |
| All `Financial.*` (revenue, net_income, FCF, etc.) | EDGAR `companyfacts.json` via `data/edgar_companyfacts.py` | Phase 2 | ADR-022 |
| `roic`, `pretax_roic`, `pt_adjusted_roic`, `fcf_margin`, `debt_to_equity`, `revenue_growth` | Self-computed from SEC XBRL primitives (`screener/tasks/composite.py`, fundamentals rollup) | Tier 2 | ADR-021 |
| `customer_concentration_pct`, `receivables_concentration_pct` | 10-K text regex + ConcentrationRiskPercentage XBRL | Phase 2 | `data/edgar_text_parser.py` |
| `share_based_compensation`, `goodwill`, `rd_expense` | SEC XBRL | Phase 2 | `data/edgar_companyfacts.py` |
| `exchange` | `data/edgar_fetcher.py:fetch_sec_exchange` (Tier 1B via `Company.get_exchanges()`) | **Phase 2.1 (2026-05-16)** | `exchange_source = 'edgartools'` |
| `ceo_total_pay` | `proxy.peo_total_comp` via `fetch_edgar_proxy_ownership` (Tier 1A DEF 14A SCT) | **Phase 2.2 (2026-05-16)** | `ceo_total_pay_source = 'sec_def14a'`; cross-validated NVDA/HIMS/LULU/INTA |
| Source-tag provenance (20 `_source` columns on `Company`) | `config/source_tags.py` constants + Alembic `y6a7b8c9d0e1` | **Phase 1 (2026-05-16)** | ADR-033 §6 Q1 RESOLVED |

---

## B. Still API-sourced — HIGH-PRIORITY migration candidates

These have a clean SEC path that's either fully ready or trivially wrappable. They violate ADR-033 §1.3 ("Search-SEC-first invariant") and should be moved next.

### B.1 `shares_float` — yfinance.info.floatShares

| | |
|---|---|
| Tier | 3b (yfinance) |
| Why it's wrong | Yahoo's "floatShares" is computed using their internal insider/restricted definitions — SEC has a canonical XBRL field. |
| SEC alternative | **`Company.facts.public_float`** (USD-denominated public float from DEI namespace). Alternative: `dei:EntityPublicFloat` via companyconcept endpoint. |
| Caveat | `public_float` is in USD, not shares. Convert via current price (already API-sourced; necessary). |
| Effort | ~30 LOC wrapper in `data/edgar_fetcher.py` (`fetch_public_float(ticker)`), wire into pipeline §1003 area |
| Priority | **HIGH** — eliminates one yfinance.info dependency entirely for the float field |

### B.2 `ceo_total_pay` — yfinance.info (compensation)

| | |
|---|---|
| Tier | 3b (yfinance) |
| Why it's wrong | DEF 14A Summary Compensation Table is THE GAAP-authoritative source. yfinance scrapes Yahoo Finance which scrapes second-hand. |
| SEC alternative | DEF 14A "Summary Compensation Table" — parse the Total column for the PEO row. We already parse `peo_name` and `pay_versus_performance` tables; total comp adjacent. |
| Pattern | Same parser used in `data/edgar_text_parser.py:parse_proxy_compensation`. Returns `peo_total_compensation` per most recent SCT year. |
| Effort | ~60 LOC: extend existing proxy parser to capture SCT totals row |
| Priority | **HIGH** — high-trust field used by F6 governance scoring |

### B.3 `ipo_date` — yfinance.info.firstTradeDateEpochUtc

| | |
|---|---|
| Tier | 3b (yfinance) |
| Why it's wrong | SEC has the registrant's first filing date — for post-1993 IPOs this is more reliable than Yahoo's trade-date heuristic (which conflates IPO with ticker-change reissuance). |
| SEC alternative | Earliest filing date from `submissions.json` recent-filings list. Or S-1 effective date if available. |
| Caveat | Pre-1993 EDGAR data is sparse — for old issuers (KO, IBM), Yahoo's earliest trade date is more useful. Keep yfinance as fallback for `first_filing_date < 1994`. |
| Effort | ~50 LOC: add `fetch_ipo_date_from_submissions(ticker)` to `edgar_fetcher.py`, wire as primary in pipeline §1003 |
| Priority | **HIGH** — used by F2 momentum, F5 lifecycle, recent-IPO feasibility gates |

### B.4 `institution_pct_latest` — yfinance.info.heldPercentInstitutions

| | |
|---|---|
| Tier | 3b (yfinance) |
| Why it's wrong | yfinance reports a stale snapshot. SEC 13F filings are the authoritative source for institutional ownership and edgartools already parses them. |
| SEC alternative | Aggregate Form 13F-HR positions across all filers within the most recent quarter, summed per issuer. **edgartools has a 13F surface ready.** |
| Caveat | 13F is quarterly with 45-day lag (not real-time). For "latest" we accept the lag — yfinance has the same lag in practice (it sources 13F too, just earlier in the pipeline). |
| Effort | ~150 LOC: 13F aggregator task, runs as monthly job. Cache by CIK. |
| Priority | **HIGH** — F4 stealth-accumulation framework depends on this signal; SEC source improves accuracy |

### B.5 `insider_pct_latest` — yfinance.info.heldPercentInsiders

| | |
|---|---|
| Tier | 3b (yfinance) |
| Why it's wrong | yfinance counts include some directors and 5% holders inconsistently. SEC Section 16 filings (Form 3/4/5) and SC 13G/D are the canonical sources. |
| SEC alternative | Sum all currently-held shares across Form 3/4 filings + SC 13G/13D filings, divide by shares_outstanding. Already have Form 4 transaction history. |
| Caveat | Form 4 records transactions, not holdings — we'd track cumulative beneficial position. Complex but tractable. |
| Effort | ~250 LOC: build BeneficialHoldingsRegistry task; reconcile Form 3 baseline + Form 4 deltas. |
| Priority | **MEDIUM-HIGH** — F1 pre-discovery and F4 stealth-accumulation use this. SEC-derived would also unlock the SC 13D ratchet detection. |

---

## C. Still API-sourced — MEDIUM-PRIORITY migration candidates

These have a SEC path but the effort/value ratio is less compelling, OR the SEC path requires changes elsewhere.

### C.1 `sector` — yfinance.info.sector

| | |
|---|---|
| Tier | 3b (yfinance) |
| SEC alternative | SIC 2-digit → sector mapping (already implemented partially in `data/sec_frames.py:SIC_2DIGIT_SECTORS`). |
| Why deferred | The 2-digit mapping in `sec_frames.py` is built for peer-cohort identification. Pushing it to a Company-level "sector" column requires aligning with Yahoo's sector taxonomy (Technology / Healthcare / etc.) — not 1-1 mappable. |
| Effort | ~80 LOC: extend `SIC_2DIGIT_SECTORS` to emit a coarser "yahoo-equivalent sector" name; backfill `Company.sector` when `sector_source='sec_sic'` |
| Priority | **MEDIUM** — `industry` is already SEC-primary; `sector` is the coarser sibling and matters less |

### C.2 `currency` — yfinance.info.currency

| | |
|---|---|
| Tier | 3b (yfinance) |
| SEC alternative | `dei:EntityReportingCurrencyISOCode` via companyconcept endpoint, OR `Company.facts.entity_info().reporting_currency` |
| Why deferred | ~95% of US-filers are USD — defaulted in schema. Only matters for cross-listed FPIs (SHOP CAD, ASML EUR, etc.). |
| Effort | ~20 LOC |
| Priority | **MEDIUM** — useful for FPI handling correctness |

### C.3 `exchange` — yfinance.info.exchange

| | |
|---|---|
| Tier | 3b (yfinance) |
| SEC alternative | **`Company.get_exchanges()`** — returns list of exchange tickers (e.g., `['NMS', 'NYSE']`) |
| Why deferred | Schema field is just a string; need to pick canonical one. |
| Effort | ~30 LOC |
| Priority | **MEDIUM** — display-only field; doesn't affect scoring |

### C.4 `EarningsHistory.eps_actual` — yfinance

| | |
|---|---|
| Tier | 3b (yfinance) |
| SEC alternative | `Financial.eps_diluted` (already SEC-derived). Quarterly EPS is in `us-gaap:EarningsPerShareDiluted`. |
| Why deferred | Currently the EarningsHistory table is fed by yfinance which provides actual + estimate + surprise in one shot. Splitting actual (SEC) from estimate (yfinance) doubles the wiring. |
| Effort | ~100 LOC + schema-source tagging |
| Priority | **MEDIUM** — partial migration; estimates and surprise_pct stay sell-side |

### C.5 `InstitutionalHolderRecord.*` — yfinance summary

| | |
|---|---|
| Tier | 3b (yfinance) |
| SEC alternative | Same as B.4 — 13F aggregator. The summary view (top 10 holders) is downstream of the same 13F data. |
| Effort | Bundled with B.4 |
| Priority | **MEDIUM-HIGH** — pairs with B.4 |

---

## D. SEC-BLIND — keep API source (no migration possible)

These fields don't exist in SEC filings by structural design. APIs are the correct source.

| Field | Current source | Why SEC-blind |
|---|---|---|
| `latest_close`, all daily price data | Polygon / yfinance | SEC publishes filings, not market data. Exchange = source. |
| `PriceHistory.*` (OHLCV) | yfinance | Same as above |
| `latest_rsi_14`, `latest_sma_*`, `latest_macd_*` | Polygon-derived | Technical indicators are price-derived, not fundamentals |
| `short_pct_float_latest`, `ShortInterestRecord.*` | yfinance / FINRA | Short interest is a FINRA disclosure, not SEC. |
| `AnalystCoverageRecord.*` (ratings, targets, estimates) | yfinance | Sell-side opinions are private — not SEC-filed |
| `EarningsHistory.eps_estimate`, `revenue_estimate`, `*_surprise_pct` | yfinance | Estimates are sell-side; surprises depend on estimates |
| `market_cap_usd` | yfinance (shares × price) | Half SEC (shares from XBRL) + half API (price). Compromise required. |

**Constraint reminder per ADR-033 §4 forbidden patterns:**
- Even though `market_cap_usd` needs API price, we MUST self-compute it from SEC `shares_outstanding × current_price` rather than trusting `yfinance.info.marketCap` (which uses its own share-count snapshot that drifts).

---

## E. Source-provenance gap (cross-cutting)

**Observation:** Most Company columns have a `*_fetched_at` timestamp but only `sector_source` records the actual origin (sec_sic | yfinance | polygon-sic). Without per-field source tags, the weighted `data_completeness` formula in `screener/tasks/composite.py:226-237` falls back to `FIELD_DEFAULT_TIER` — a static guess at typical source rather than ground-truth.

**Recommendation:** Add per-field `<field>_source` columns for migration candidates. E.g.:
- `shares_float_source` ∈ `{'sec_dei', 'yfinance'}`
- `ipo_date_source` ∈ `{'sec_submissions', 'yfinance'}`
- `ceo_total_pay_source` ∈ `{'sec_def14a', 'yfinance'}`

Then `compute_data_completeness` reads the actual source and applies the correct tier weight, not a default.

This is the precondition for actually rewarding SEC-primary fields in the data_completeness metric — without it, a tier upgrade looks identical in the score, removing the incentive.

**Effort:** ~6 schema columns (1 Alembic migration), updates to 3 fetcher functions to set them, +20 LOC to `compute_data_completeness`. **HIGH priority** infrastructure work — gates the value of all migrations in section B.

---

## F. Recommended migration sequence

Ordered by `(value × ease)` similar to inventory section 5:

### Phase 1 — Plumbing (1 PR) — ✅ DONE 2026-05-16
- **F.1**: ✅ Added 20 per-field `_source` columns via Alembic migration `y6a7b8c9d0e1` (E above).
- **F.2**: ✅ `compute_data_completeness` rewritten Σ(w·p)/N reading actual sources via `config/source_tags.tier_weight()`.
- **F.3**: ⏭ Dive output per-field provenance display — DEFERRED to a future PR (not blocking).

### Phase 2 — Quick wins (each <100 LOC) — partial
1. ✅ **B.3 `ipo_date`** — first-filing-date from submissions.json (DONE in Phase 1; IPODateTask sets `_source='sec_submissions'`).
2. ⏭ **B.1 `shares_float`** — DEFERRED. `dei:EntityPublicFloat` is USD-denominated; conversion to shares needs API current_price (hybrid Tier 1A+3b). Park until schema gains separate `shares_outstanding_sec` column.
3. ✅ **B.2 `ceo_total_pay`** — DONE 2026-05-16. DEF 14A SCT via `edgartools proxy.peo_total_comp` (Tier 1A `sec_def14a`). Cross-validated: NVDA $36.3M, HIMS $22.96M, LULU $14.55M, INTA $14.92M.
4. ✅ **C.3 `exchange`** — DONE 2026-05-16. `data/edgar_fetcher.py:fetch_sec_exchange()` wrapping `Company.get_exchanges()` (Tier 1B `edgartools`).
5. ⏭ **C.2 `currency`** — DEFERRED. `dei:EntityReportingCurrencyISOCode` returns 404 for most US filers (USD implicit, not tagged). yfinance fallback stays.

### Phase 3 — Strategic (~150-300 LOC each) — NEXT-UP
6. **B.4 `institution_pct_latest`** + **C.5 InstitutionalHolderRecord** — 13F aggregator task (bundle, ~150 LOC)
7. **B.5 `insider_pct_latest`** — BeneficialHoldingsRegistry from Form 3+4+SC 13D (~250 LOC)
8. **C.1 `sector`** — SIC 2-digit → Yahoo-equivalent sector mapping (~80 LOC)
9. **C.4 `EarningsHistory.eps_actual`** — split actual (SEC) from estimate (yfinance)

### Phase 4 — Universe expansion (separate workstream)
- **10**: Backfill 310 missing tickers from `company_tickers_exchange.json` (per inventory §7)

---

## G. Forbidden migrations (no SEC alternative exists — do NOT attempt)

Per ADR-033 §4 + section D above:
- Daily prices, OHLCV, technical indicators, beta inputs (price returns), market_cap multiplicand
- Short interest, days-to-cover, short_pct_float
- Analyst ratings, price targets, EPS estimates, revenue estimates, surprise %
- Real-time quotes, intraday data

Attempting to source any of these from SEC is wasted effort; SEC filings are not the market.

---

## H. Validation invariants

After each migration in section F, the following invariants must hold:

1. **Data completeness must INCREASE** (post-tier-weighting, per ADR-033 §6.Q2) for tickers where the migrated field successfully sourced from SEC. If it doesn't, the source weight or completeness formula is wrong.
2. **No silent fallback chains.** Every field has a `_source` column populated. NULL `_source` is a bug (not "implicit yfinance").
3. **Honesty invariant survives.** If SEC sources are unreachable (network, parse error, concept not reported), the field falls back to API tier OR remains None — never silently substitutes a different-methodology value.
4. **Dive output displays per-field provenance.** A user running `invest dive NVDA` sees:
   ```
   shares_float: 24.1B [sec_dei]
   ipo_date: 1999-01-22 [sec_submissions]
   exchange: NMS [sec_companyfacts]
   ```
   rather than the current undifferentiated values.

---

*Next concrete step (post Phase 2.1+2.2, 2026-05-17):* Phase 3 strategic migrations — bundle B.4 (institution_pct via 13F aggregator) + C.5 (InstitutionalHolderRecord) as one PR (~150 LOC), then B.5 (insider_pct via BeneficialHoldingsRegistry from Form 3+4+SC 13D, ~250 LOC). Phase 1 plumbing and Phase 2 quick wins are complete — see updated checkmarks in §F above. The `_source` infrastructure makes every Phase 3 win immediately visible in `data_completeness`.
