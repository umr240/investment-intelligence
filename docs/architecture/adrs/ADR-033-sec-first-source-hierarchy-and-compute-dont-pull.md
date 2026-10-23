# ADR-033 — SEC-First Source Hierarchy & Compute-Don't-Pull

| Field | Detail |
|---|---|
| **Status** | **Accepted** — formalises the architectural pattern empirically validated across Tier 1.1–2.5 this session |
| **Date** | 2026-05-15 |
| **Provenance** | User intervention 2026-05-15: *"the reason why I don't trust ratios of other sites is because we can derive them ourselves if we have pure raw complete data from SEC EDGAR and edgar tools instead of relying on APIs which I do not trust. Also there could be hidden tickers which do not have fundamentals listed on APIs like yfinance, FMP, polygon and SEC EDGAR might have them. Everything should be derived from SEC EDGAR and edgar tools and we need to keep searching for SEC EDGAR and edgar tools endpoints as alternatives first and then fallback to the APIs like yfinance, polygon, FMP etc. The reason I trust SEC EDGAR is because it is GAAP, verifiable source of truth and calculations based on those gets us accurate results."* |
| **Related** | ADR-021 (Peters-Taylor — our deterministic non-GAAP), ADR-022 (Methodology disclosure + source provenance), ADR-023 (Narrative personality), ADR-031 (Data Gap Register), ADR-032 (Project-local skills), CLAUDE.md §"AI layer boundary" |
| **Preserves** | All existing invariants — the AI-layer boundary (still 2 permitted Anthropic call sites), the deterministic data path for F1–F7, Peters-Taylor as the canonical non-GAAP adjustment. This ADR strengthens those rules; it does not relax them. |

---

## 0. Why this ADR exists

Across two working sessions (2026-05-14, 2026-05-15) the system shipped:
- A priority chain for CEO equity (ADR-031 §1.3)
- The external_signals LLM channel with isolation (ADR-031 §4.1)
- 3 starter skills under shadow-mode (ADR-032)
- 13 substitutions / additions across Tier 1.1–2.5 codified below

Each substitution was driven by a real correctness failure surfaced by deep-dive on a specific ticker. The pattern that emerged: **whenever we trusted an API-pulled value, we eventually found it was wrong against SEC-derived ground truth.** Concrete failures captured by this session:

| Failure | API source | Real SEC-derived value |
|---|---|---|
| HIMS industry "Software — Application" | yfinance | SIC 8011 "Offices & Clinics of Doctors of Medicine" |
| HIMS Dudum CEO equity 87.73% | DEF 14A column-misread | 11.1% (SC 13D Item 5 Row 13) |
| HIMS P/E 57.14× | yfinance forward/non-GAAP | **None** (TTM net income is negative — P/E undefined) |
| HIMS EV/EBITDA 134.16× | yfinance with SBC add-back | **202.95×** (no add-back per ADR-021) |
| INTA P/B 5.00× | yfinance | **3.08×** (60% lower than yfinance) |
| INTA EV/EBITDA −76.34× | yfinance "negative ratio" gibberish | **None** (EBITDA negative → ratio undefined) |
| FIG EV/EBITDA −7.03× | yfinance gibberish | **None** |
| MRVL P/E 59.47× | yfinance using forward EPS | **None** (GAAP TTM NI negative) |
| PATH F1 "gp_a_strong=True" | Universe-blind threshold | **False** — 65.1st pctile vs SIC 7372 software peers (below top tercile) |
| SHOP F1 "gp_a_strong=True" | Universe-blind threshold | **False** — 54th pctile vs software peers, BELOW sector median |
| MRVL CIK 1058057 (defunct entity) | Stale lookup | CIK 1835632 (post-redomiciliation, Apr 2021) |
| LULU CEO "Meghan Frank" | yfinance.info.companyOfficers | "Calvin McDonald" (SEC DEF 14A peo_name) |
| SHOP / NVDA / MRVL TTM denominators | Manual quarterly summing | edgartools.Company.get_ttm(concept) — period audit trail included |

These failures were not edge cases — they were the **typical** outcome whenever we accepted an API value without checking against SEC raw data. This ADR codifies the response: **when SEC has the data, SEC is the source. When SEC has the raw primitives but not the derived metric, we compute. APIs are reserved for what SEC structurally cannot provide.**

---

## 1. The decision

### 1.1 Four-tier source hierarchy

Every persisted field declares its source, ranked by trust:

| Tier | Source | Trust weight | When to use |
|---|---|---|---|
| **1A** | **SEC EDGAR raw** — companyfacts.json, submissions.json, frames endpoint, SC 13D/14A/MIC text | **1.00** | Primary for all GAAP fundamentals + classification (SIC, filer category, exchanges, FPI status, beneficial ownership). The verifiable source of truth. |
| **1B** | **edgartools structured APIs** — `Company.industry`, `get_ttm()`, `get_facts()`, `get_financials()`, `is_foreign`, `is_smaller_reporting_company` | **1.00** | Equivalent to 1A — edgartools is the typed wrapper over the same SEC endpoints. |
| **2** | **Self-computed from SEC primitives** — P/E = market_cap / TTM_net_income(SEC); P/B = market_cap / equity(SEC); EV/EBITDA = (mc + debt − cash) / TTM_EBITDA(SEC); beta from PriceHistory regression vs SPY; sector medians from SEC frames | **1.00** | Use SEC raw primitives to derive any metric an API would otherwise pre-compute. GAAP-uniform methodology, fully auditable. |
| **3** | **API fallback** — Polygon (prices), yfinance (price/short interest), FMP free-tier | **0.85** (yfinance), **0.95** (Polygon), **0.80** (FMP) | Reserved for what SEC structurally cannot provide: current/historical market prices, short interest (FINRA bi-monthly), real-time quotes. |
| **4** | **LLM supplementary** — `deepdive/external_signals.py` extraction from earnings press releases | **0.50** | Last-resort, supplementary only. Strict isolation in `external_signals` table; never read by F1-F7. Per ADR-031 §4.1. |

### 1.2 The compute-don't-pull invariant

**For any metric an API offers AND SEC raw primitives could compute, we compute.** The API's pre-computed value is not trusted, no matter how convenient. This rule is non-negotiable because:

1. **GAAP verifiability.** SEC XBRL is audited, fact-keyed to accession numbers. Our computation methodology is documented in code (`valuation/sec_derived_ratios.py`). The audit trail is end-to-end.
2. **Methodology variance.** yfinance's "P/E" might be forward-EPS-adjusted, non-GAAP-adjusted, or use a different TTM convention. We don't see their methodology; they don't tell us; the value is uninterpretable.
3. **Honest undefined-ness.** When TTM net income is negative, P/E is mathematically undefined. yfinance's "57.14x" for HIMS is fabricated from forward EPS. Our `None` is the truth.
4. **No silent SBC add-backs.** ADR-021 §4.1 explicitly rejects management non-GAAP. APIs that silently add SBC back (HIMS EV/EBITDA 134.16x yfinance vs 202.95x ours) smuggle in management non-GAAP without flagging it.

### 1.3 The search-SEC-first invariant

**Before falling back to an API for any new field, the implementation MUST search for SEC equivalents first.** Concrete checklist for any new field:

1. Is it in `companyfacts.json` (XBRL us-gaap concept)?
2. Is it in `submissions.json` (filer metadata: name, exchanges, SIC, fiscal year end, recent filings)?
3. Is it in the **frames** endpoint (cross-sectional XBRL across all filers)?
4. Is it in an edgartools structured API (`get_ttm`, `get_facts`, `get_financials`, `is_foreign`, etc.)?
5. Is it in 13D/13G/14A/8-K text (extractable deterministically via regex/BS4)?
6. Can it be computed from primitives in 1-5?
7. Only AFTER 1-6 all fail: consider API fallback with appropriate trust weight + provenance flag.

### 1.4 Universe enumeration

**Ticker universe is enumerated from SEC, not from APIs.** SEC EDGAR's `company_tickers.json` covers ~13,000 filers; yfinance's universe is biased toward actively-traded names. Per user 2026-05-15: *"there could be hidden tickers which do not have fundamentals listed on APIs like yfinance, FMP, polygon and SEC EDGAR might have them."*

The frames endpoint demonstrates the gap empirically: 6,241 filers reported `Assets` for Q4 2024; yfinance's covered universe is ~10k but heavily biased to actively-traded names. SEC sees the long tail of micro-caps, OTC names, recently-IPO'd, and FPIs that APIs miss.

### 1.5 Per-field source provenance

Every persisted field SHOULD declare its source via one of:

- A dedicated `<field>_source` column (e.g. `Company.sector_source` already exists; values: `'sec_sic'`, `'yfinance'`, `'polygon_sic'`)
- A `<field>_state` column for 3-state confidence (`'disclosed_exact'`, `'parser_uncertain'`, `'not_disclosed'`) — already exists for `ceo_name`, `ceo_equity_pct`, `is_founder_ceo`, `ipo_date`
- The `external_signals.extraction_method` column for LLM-extracted supplementary data

**Current state**: 4 fields have full provenance tracking; ~75 fields don't. Phase 2+ work to extend provenance to every field — codified in the OPEN QUESTIONS section.

### 1.6 LLM supplementary channel remains isolated

LLM-derived data lives ONLY in the `external_signals` table (ADR-031 §4.1). F1–F7 framework scoring NEVER reads from it. The narrative LLM (`deepdive/narrative.py`) can cite from it with explicit provenance.

The two permitted Anthropic call sites are unchanged:
- `deepdive/narrative.py` — bull/bear/risk narrative generation
- `deepdive/external_signals.py` — DEF 14A / 8-K / proxy ownership extraction with strict verbatim-quote requirement

No third call site permitted without a new ADR.

---

## 2. Implementation status — what's shipped

### Tier 1 substitutions (high-impact, low-risk)

| # | Substitution | File | Test |
|---|---|---|---|
| **1.1** | yfinance.info.industry → `edgartools.Company.industry` (SIC-derived) | `data/edgar_fetcher.py:fetch_sec_industry_classification`, `data/pipeline.py` | 8 tickers corrected (HIMS "Drug Manufacturers" → "Offices & Clinics of Doctors of Medicine"; INTA/SHOP/PATH/FIG "Software-Application" → "Services-Prepackaged Software"; etc.) |
| **1.2** | Manual quarterly TTM summing → `edgartools.Company.get_ttm(concept)` | `valuation/sec_derived_ratios.py:_compute_ttm` | HIMS / SHOP / NVDA / LULU TTM values consistent; period audit trail preserved |
| **1.3** | 40-F filing-history probe → `edgartools.Company.is_foreign` (with 40-F fallback for ex-FPIs like SHOP) | `cli/skills/audit_completeness.py:_is_former_fpi` v1.0.3 | SHOP correctly flagged as ex-FPI; HIMS / NVDA / etc. correctly non-FPI |

### Tier 2 substitutions (frames-based peer comparison)

| # | Substitution | File | Test |
|---|---|---|---|
| **2.1** | Sector medians not warehoused (data_gap) → SEC frames endpoint cross-sectional | `data/sec_frames.py` (~250 LOC) | 4,724 filers in revenue-concept union; 1,094 in GP/Rev distribution |
| **2.2** | Sector-blind ratios → peer-percentile aggregation | `data/sec_frames.py:compute_ratio_distribution`, `get_percentile_rank` | NVDA GP/A 99.5th pctile vs 107 SIC-3674 peers, sector median 22.3% |
| **2.3** | (validation) | smoke test | HIMS R&D ranked vs SIC-80 healthcare; SHOP GP/A reveals software-sector-relative position |
| **2.4** | No persistent SIC code on Company → `sic_code` + classification columns + universe backfill | alembic `x5f6a7b8c9d0`, `data/models/schema.py`, a one-off backfill script (archived) | 6,447 dived tickers backfilled with SIC + filer_category + is_smaller_reporting_company + is_financial_institution + is_fund |
| **2.5** | F1 GP/A universe-blind top-tercile → SIC-filtered percentile | `frameworks/f1_pre_discovery.py:_compute_gp_a` | PATH 7.83 → 6.83 (gp_a_strong False); SHOP 7.17 → 6.17 |
| **2.5** | F3 R&D peer-context augmentation | `frameworks/f3_innovation.py:_rd_peer_percentile` | NVDA R&D 42.5th pctile (below sector median — surprising signal); MRVL 77.6th |

### SEC-derived valuation ratios (separate from Tier hierarchy)

| Ratio | Old source | New source | Replaces |
|---|---|---|---|
| P/E trailing | yfinance.info.trailingPE | `market_cap / TTM_NI_from_SEC` | yfinance silently substitutes forward EPS when GAAP NI is negative |
| P/B | yfinance.info.priceToBook | `market_cap / total_equity_from_SEC` | yfinance INTA P/B 5.00x vs SEC 3.08x divergence |
| EV/EBITDA | yfinance.info.enterpriseToEbitda | `(mc + debt − cash) / TTM_EBITDA_from_SEC` | yfinance silently adds SBC back per management non-GAAP |
| P/FCF | yfinance | `market_cap / TTM_FCF_from_SEC` | New — yfinance didn't expose this |

Honesty invariants enforced:
- When TTM net income ≤ 0 → P/E = `None` (not substituted)
- When total equity ≤ 0 → P/B = `None`
- When TTM EBITDA ≤ 0 → EV/EBITDA = `None`

Persisted to Company table; method label `'sec_xbrl_derived'`.

---

## 3. Empirical evidence (validation matrix)

### 3.1 Industry classification (Tier 1.1)

| Ticker | yfinance (wrong) | SEC SIC (correct) | Why it matters |
|---|---|---|---|
| **HIMS** | Drug Manufacturers — Specialty & Generic | 8011 Offices & Clinics of Doctors of Medicine | HIMS is telehealth, not drug-mfg. Wrong sector → wrong peer comparison → wrong F-framework verdicts |
| INTA | Software — Application | 7372 Services-Prepackaged Software | More precise SEC bucket |
| SHOP, PATH, FIG | Software — Application | 7372 Services-Prepackaged Software | Same |
| NVDA, MRVL | Semiconductors | 3674 Semiconductors & Related Devices | More precise |
| LULU | Apparel Retail | 2300 Apparel & Other Finished Products | SEC classifies as manufacturer, not retail |

### 3.2 Valuation ratios (compute-don't-pull)

| Ticker | yfinance | SEC self-computed | Variance |
|---|---|---|---|
| SHOP P/E | 95.51× | 94.91× | 0.6% — within rounding (no controversial adjustments) |
| NVDA P/E | 48.11× | 47.55× | 1.2% |
| LULU P/E | 9.13× | 8.99× | 1.5% |
| **HIMS P/E** | **57.14×** | **None** (GAAP loss) | **yfinance fabricated from forward EPS** |
| **HIMS EV/EBITDA** | **134.16×** | **202.95×** | **50% — yfinance smuggled in SBC add-back** |
| **INTA P/B** | **5.00×** | **3.08×** | **−38% — different equity basis** |
| **INTA EV/EBITDA** | **−76.34×** (gibberish) | **None** | yfinance produced nonsense negative ratio |
| FIG EV/EBITDA | −7.03× (gibberish) | None | Same |
| MRVL P/E | 59.47× (forward) | None (GAAP loss) | Forward-EPS substitution |

### 3.3 Peer-relative scoring (Tier 2.5)

**NVDA in Semiconductors (SIC 3674), CY2024 frame**:
- 107 SIC-3674 peers reporting GrossProfit + Assets
- NVDA GP/A: 74.21%
- NVDA percentile: **99.5** (best of 107)
- Sector median: 22.3%

**SHOP in Software (SIC 7372), CY2024 frame**:
- 162 SIC-7372 peers
- SHOP GP/A: 36.57%
- SHOP percentile: **54.0** (BELOW software sector median 34.45%)
- Universe-blind threshold gave SHOP a false-positive `gp_a_strong=True`

**Two corrections from sector-blind to sector-relative**:
- PATH: F1 7.83 → 6.83 (`gp_a_strong` flipped True → False — 65.1st pctile, below P67 top tercile)
- SHOP: F1 7.17 → 6.17 (54th pctile, below software sector median)

### 3.4 The "hidden tickers" thesis confirmed

- SEC frames endpoint for `Assets/CY2024Q4I.json`: **6,241 filers**
- Revenue concept union (`Revenues` + `RevenueFromContractWithCustomerExcludingAssessedTax`): **4,724 unique CIKs**
- Single concept alone misses ~600+ filers per concept due to ASC 606 transition variance
- yfinance universe: ~10k but heavily biased to actively-traded; misses micro-caps, recent IPOs, OTC names

---

## 4. Forbidden patterns

The following are non-negotiable architectural prohibitions (violating any requires a new ADR):

1. **No API ratios.** P/E, P/B, EV/EBITDA, etc. are self-computed. Pulling pre-computed ratios from yfinance / FMP / Polygon is forbidden.
2. **No yfinance industry without SEC SIC override.** Industry classification flows from SEC SIC when available; yfinance is fallback only.
3. **No silent SBC add-backs.** Peters-Taylor (ADR-021) is the canonical non-GAAP adjustment. API values that add SBC back without flagging contaminate the methodology.
4. **No forward-EPS substitution for GAAP P/E.** When GAAP TTM net income is negative, P/E is `None`. Forward EPS is not GAAP and is not a substitute.
5. **No CEO equity from non-SEC sources for F5 scoring.** Priority chain: SC 13D/A (primary, Rule 13d-3) → DEF 14A → MIC (Canadian FPIs). yfinance officers list is too noisy (LULU "Frank as CEO" misattribution).
6. **No LLM data in F1–F7 scoring.** External_signals channel is supplementary only (ADR-031 §4.1).
7. **No third Anthropic call site.** The two permitted sites are `deepdive/narrative.py` and `deepdive/external_signals.py`. Adding a third requires a new ADR amending CLAUDE.md.
8. **No API-based universe enumeration.** Ticker discovery flows from SEC `company_tickers.json` and `submissions.json`. yfinance's universe is biased and incomplete.

---

## 5. Acceptance criteria for any new field

Any future PR adding a persisted field MUST satisfy:

1. **Source-priority documented** — which tier (1A/1B/2/3/4) sources this field, and why no higher tier was available
2. **SEC search executed** — explicit check that companyfacts / submissions / frames / edgartools structured / 10-K text / SC 13D / DEF 14A / MIC don't have it before falling to API
3. **Provenance column** — either `<field>_source` text column OR documented in a JSON `field_provenance` blob
4. **Honest undefined values** — when mathematically undefined (negative denominator, etc.), value is `None`. No silent substitution.
5. **No silent unit conversion** — yfinance can return market_cap in mixed scales (USD vs USD millions vs USD billions); always normalise to base USD with explicit handling
6. **Verifiability test** — the field's computation must be reproducible from the persisted SEC primitives (or the API call must be deterministic given a fixed timestamp)
7. **F1–F7 impact disclosed** — if the field feeds framework scoring, prior baseline AND new baseline must both be tested. Tier 2.5 PATH/SHOP corrections are the canonical example.

---

## 6. Open questions / deferred work

1. **Per-field `_source` columns universe-wide** — **RESOLVED 2026-05-16 (Phase 1 plumbing)** via Alembic migration `y6a7b8c9d0e1`. Twenty `_source` columns added to `Company` covering the WAREHOUSE_COLUMNS warehouse fields, the valuation ratios (P/E, P/B, EV/EBITDA, beta), and the high-priority Phase 2 migration targets (shares_float, ceo_total_pay, exchange, currency, institution_pct, insider_pct, short_pct_float, pretax_roic, pt_adjusted_roic). Source tag constants codified in `config/source_tags.py` with `tier_weight()` resolver. `compute_data_completeness` formula rewritten Σ(w·p)/N (replaced the self-normalizing Σ(w·p)/Σw which masked source upgrades — a fully-yfinance row scored 1.0 same as fully-SEC, eliminating any incentive for migration to surface). New formula range:
   - Empty row: 0.00
   - Pre-migration (NULL `_source`): 0.77 — pressure to migrate
   - Fully yfinance: 0.88
   - Fully SEC: 0.94 (a policy status field at 0.50 weight capped it; policy fields left the completeness score on 2026-05-17)
2. **Weighted `data_completeness` formula** — **RESOLVED 2026-05-15** in `screener/tasks/composite.py:compute_data_completeness`. Per-field default tier (yfinance 0.85, SEC-derived 1.00, manual 0.50). `industry` resolves conditionally via `Company.sector_source`: `sec_sic` → 1.00, else 0.85. Universe-wide effect (10,143 tickers, 7,662 updated):
   ```
   Average weighted completeness by sector_source:
     sec_sic    (n=6364) avg 0.6951  ← high quality
     yfinance   (n=2036) avg 0.4947
     sec-sic    (n= 902) avg 0.3727  (legacy format string)
     NULL       (n= 841) avg 0.0733  (barely populated)
   ```
   LLM-derived canonical fields would receive 0.50 tier weight if/when introduced (none today per ADR-031 §4.1 isolation rule — LLM data lives only in external_signals, which is NOT a WAREHOUSE_COLUMNS field).
3. **Non-December-FYE frame alignment.** NVDA / LULU / MRVL Jan-FYE filers' data falls in `CY{year-1}` not `CY{year}` for frame lookups. Tier 2.5 added year-1 fallback in `_compute_gp_a` and `_rd_peer_percentile`. June-FYE filers (legacy AAPL, INTA) — same fallback works but is brittle. Long-term: build a fiscal-period mapper.
4. **Self-compute beta from PriceHistory** (Task #48). β = cov(stock_returns, SPY_returns) / var(SPY_returns) over 5yr daily returns. PriceHistory has the data; just need the regression.
5. **Universe-level pipeline refresh.** SEC industry backfill (Tier 2.4) ran on dived universe (6,447); the remaining 3,696 non-dived tickers still have yfinance or NULL industry. Phase 2 work.
6. **Self-compute insider %, institutional %**. Currently from yfinance; could be derived as `sum(InsiderTransactionRecord.shares) / shares_outstanding_from_SEC` and `sum(InstitutionalHolderRecord.shares_held) / shares_outstanding`. Deferred (Phase 3 strategic — `API_FIELD_AUDIT.md §B.4/§B.5`).
7. **Sector median EV/Revenue (BEW closure).** Frames endpoint gives revenue per filer. EV needs market_cap (requires price × shares). When market_cap is populated for enough peers, BEW sector-median EV/Rev becomes computable. Currently still listed as data_gap.
8. **`exchange` field** — **RESOLVED 2026-05-16 (Phase 2.1)** via `data/edgar_fetcher.py:fetch_sec_exchange()` wrapping `edgartools.Company.get_exchanges()` (Tier 1B). Wired in `data/pipeline.py` as SEC primary, yfinance fallback. `exchange_source` column set to `'edgartools'` on SEC-derived writes. Smoke-tested across NVDA, SHOP, HIMS, INTA, ASML, LULU.
9. **`ceo_total_pay` field** — **RESOLVED 2026-05-16 (Phase 2.2)** via extension to `data/edgar_fetcher.py:fetch_edgar_proxy_ownership()` capturing `edgartools.proxy.peo_total_comp` (Tier 1A — DEF 14A Summary Compensation Table). `ceo_total_pay_source` column set to `'sec_def14a'` when proxy resolves. Cross-validated against canonical DEF 14A SCT totals: NVDA $36.3M (Jen-Hsun Huang), HIMS $22.96M (Andrew Dudum), LULU $14.55M (Calvin McDonald), INTA $14.92M (John T. Hall). SHOP returns yfinance fallback because Canadian FPI files MIC not DEF 14A.
10. **`shares_float` migration** — DEFERRED. `dei:EntityPublicFloat` is USD-denominated; shares conversion requires API current_price (hybrid Tier 1A+3b). Alternative: `dei:EntityCommonStockSharesOutstanding` gives shares-outstanding (not float — overstates by insider holdings). Both paths violate field semantics. Park until schema gains separate `shares_outstanding_sec` column (see `API_FIELD_AUDIT.md §B.1`).
11. **`currency` migration** — DEFERRED. `dei:EntityReportingCurrencyISOCode` returns 404 for most US filers (USD implicit, not tagged). yfinance fallback stays for now (see `API_FIELD_AUDIT.md §C.2`).

---

## 7. Coordination with related ADRs

- **ADR-021 (Peters-Taylor; no management non-GAAP)** — unchanged. Strengthened by this ADR: the "no SBC add-back" rule is now an architectural prohibition (§4 #3), not just an internal methodology choice.
- **ADR-022 (Methodology disclosure & source provenance)** — this ADR extends ADR-022's per-metric source declaration to be the universal pattern. Every metric has a tier (§1.1) and a source column.
- **ADR-023 (Narrative personality)** — unchanged. The narrative LLM still reads ScorecardView; the SEC-derived ratios populated by this ADR are the canonical numbers it cites.
- **ADR-024 (Mental-models library)** — `mental_models/core/margin_of_safety.md` antipattern *"Inferred values filling missing data"* is now codified architecturally: API pre-computed ratios are inferred relative to our SEC raw fundamentals, so they fail the margin-of-safety test.
- **ADR-031 (Data Gap Register)** — §1.3 priority chain is the CEO-equity-specific instance of the general pattern this ADR codifies. §1.4 Form-4-RSU drift is similarly SEC-derived. The four-tier hierarchy is the general form of "priority chain" used throughout.
- **ADR-032 (Project-local skills)** — `/audit-completeness` skill v1.0.3 uses Tier 1.3 (is_foreign primary). Future skills MUST respect §1.1's source priority.
- **CLAUDE.md §"AI layer boundary"** — unchanged. Still 2 permitted Anthropic call sites.

---

## 8. Non-goals

- This ADR does NOT replace any framework's scoring formula (except where Tier 2.5 explicitly changed F1's GP/A signal — the formula stayed; the input changed)
- This ADR does NOT mandate universe-level refresh on every change — gradual backfill is the operational pattern
- This ADR does NOT prohibit using APIs entirely — Tier 3 (price data, short interest) genuinely needs them
- This ADR does NOT add a third Anthropic call site
- This ADR does NOT introduce new third-party data vendors (CapIQ, FactSet, Refinitiv — all still out of scope per ADR-031 §2)
- This ADR does NOT decide weighted `data_completeness` formula — that's an open question (§6 Q2)

---

## 9. Files this ADR codifies

| File | Role |
|---|---|
| `data/edgar_companyfacts.py` | Tier 1A — companyfacts.json parsing + filer metadata + frames |
| `data/edgar_fetcher.py` | Tier 1B — edgartools wrappers (`fetch_sec_industry_classification`, `fetch_latest_ceo_sc13d`, etc.) |
| `data/edgar_text_parser.py` | Tier 1A text parsing — SC 13D / DEF 14A / MIC ownership tables |
| `data/sec_frames.py` | Tier 1A frames endpoint — cross-sectional peer comparison |
| `valuation/sec_derived_ratios.py` | Tier 2 — self-compute P/E, P/B, EV/EBITDA, P/FCF |
| `data/api/yfinance_client.py` | Tier 3 fallback — used only for fields SEC can't provide |
| `data/api/polygon_client.py`, `fmp_client.py` | Tier 3 fallback |
| `deepdive/narrative.py`, `deepdive/external_signals.py` | Tier 4 LLM (permitted sites) |
| `data/models/schema.py:Company` | `sic_code`, `filer_category`, `is_smaller_reporting_company`, `is_financial_institution`, `is_fund`, `sector_source` — provenance columns |
| `data/models/schema.py:ExternalSignalRecord` | Tier 4 isolated channel |
| `frameworks/f1_pre_discovery.py` | Tier 2.5 — SIC-filtered GP/A |
| `frameworks/f3_innovation.py` | Tier 2.5 — peer-context augmentation |

---

## 10. Summary in one sentence

**Compute from SEC raw GAAP fundamentals. Search SEC alternatives before any API fallback. APIs are reserved for what SEC structurally cannot provide (market prices, short interest). LLM data is supplementary only with full provenance. The architectural moat — deterministic data canonical, LLM data isolated, no silent management-non-GAAP smuggling — is now law.**

---

*Trust is verification. Verification is GAAP-uniform XBRL with accession-number provenance. Everything else is taking someone else's word for it.*
