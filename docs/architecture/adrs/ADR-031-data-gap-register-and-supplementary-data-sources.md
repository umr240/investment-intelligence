# ADR-031 — Data Gap Register & Supplementary Data Sources

| Field | Detail |
|---|---|
| **Status** | **Accepted + implemented** (status updated 2026-05-17). Amended by ADR-031-A1 (2026-10-23: `deepdive/conversation.py` is a permitted call site; the allow-list lives in `tests/test_llm_call_sites.py`). External-signals LLM-supplementary extraction channel shipped: `deepdive/external_signals.py` (second permitted Anthropic call site per §4.1) + `external_signals` table (migration `v3d4e5f6a7b8`) + `/external-signals` skill (ADR-032, `dangerous: true`). Token-budget ceiling $100/mo per §3. Strict isolation from F1-F7 framework scoring verified. Five-category gap taxonomy (A/B/C/D/E) referenced from `/audit-completeness` skill (audit-completeness.md frontmatter). CEO-equity priority chain (SC 13D/A → DEF 14A → 6-K MIC → yfinance) shipped per §1.3. |
| **Date** | 2026-05-15 |
| **Provenance** | User intervention 2026-05-15 after the SHOP / INTA dive cycle revealed systematic 100%-null coverage on NRR/GRR/customer-concentration across the 10k-ticker universe. The session also built (in isolation) a working LLM-extraction prototype (`deepdive/external_signals.py`) that demonstrated the cost and quality profile of one possible solution. The user instruction: *"we will need an ADR to include each and every data gap that we currently could not surface through SEC EDGAR, edgartools, polygon, yfinance into a separate data gap register ADR. I have not thought about solution but for now, LLM usage in surfacing these external signals seems to be an alternative, we need to assess the token budget, token cost for these operations before we make a decision."* |
| **Related** | ADR-021 (Peters-Taylor; no SBC add-back), ADR-022 (Methodology disclosure & source provenance), ADR-023 (Narrative personality), ADR-024 (Mental-models library), ADR-025 (IFRS / FPI universe support), CLAUDE.md §"AI layer boundary" |
| **Preserves** | CLAUDE.md determinism rule — F1–F7 framework scoring path remains LLM-free. The architectural moat is intact: deterministic data is canonical; LLM data is supplementary with provenance; the user and the narrative LLM see both side-by-side without one corrupting the other. |
| **Does NOT decide** | Which supplementary-data solution to adopt. This ADR catalogues the gaps, evaluates options with cost data, and defines acceptance criteria. The choice is deliberately deferred. |

---

## 0. Why this ADR exists

Over the prior 30 dives the system has consistently surfaced the same set of "not_disclosed" / "missing" entries. Until 2026-05-15 we treated each as a per-framework local concern: F6 has its NRR gap, F4 has its options gap, F7 has its history gap. **That framing is wrong.** The pattern is universal:

- **F6 `Financial.nrr_pct` is null on 46,082 / 46,085 (100.0%)** of annual rows across the universe
- **F6 `Financial.grr_pct` is null on 46,084 / 46,085 (100.0%)**
- **F6 `Financial.customer_concentration_pct` is null on 46,083 / 46,085 (100.0%)**
- **`Financial.arr_state` is null on 46,078 / 46,085 (100.0%)**
- **`Company.ceo_equity_pct` is `disclosed_exact` on only 10 / 10,143 tickers (0.10%)**

These are not local failures. They are **structural limits of the deterministic data path** we have today. The right question is no longer *"how do we fix F6's NRR parser?"* but *"what is our policy for the entire class of signals that SEC EDGAR / yfinance / polygon cannot reach?"*

This ADR is the register. It does not decide the policy — it makes the decision visible.

---

## 1. The Gap Register

### 1.1 Classification scheme

Every gap falls into exactly one of five **root-cause categories**. The category determines which solutions are even applicable.

| Category | Definition | Closeable by parser improvement? | Closeable by alt source? |
|---|---|---|---|
| **A. Issuer non-disclosure** | The issuer chooses not to report the metric in any filing (10-K, 10-Q, 8-K). Example: SHOP NRR. | ❌ No | Maybe — earnings call transcripts, IR pages, investor presentations |
| **B. Source-policy exclusion** | The free-tier rule forbids the source. Example: F4 options put/call ratio (PROJECT_SPEC §F4 Pan-Poteshman 2006 — paid options data only). | ❌ No | Paid data feed only |
| **C. Parser miss** | The data is in a SEC filing but our parser doesn't extract it. Example: SBC pre-2026 across SHOP (fixed during 2026-05-15 session). | ✅ Yes | n/a — fix the parser |
| **D. FPI structural** | Foreign Private Issuers exempt from US-domestic reporting rules. Example: SHOP officers had no Section 16 Form-4 obligation until 2025/2026. | ❌ No (data physically does not exist) | SEDAR / TSX filings (Canadian); Companies House (UK); etc. |
| **E. Insufficient history** | The field exists but we don't have enough periods. Example: F7 z-score requires ≥5y, recent IPO has 4. | ✅ Yes (over time) | Time will fix it |

### 1.2 Field-level register

Each row records: **field**, **consumer framework**, **canonical persisted location**, **root cause**, **live-DB coverage**, and **observed extraction paths**.

#### F1 — Pre-Discovery Alpha (Piotroski 2000 + cluster-buy)

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `piotroski.roa_yoy` | derived from Financial.net_income / total_assets cross-period | E | New IPO, ~5% of tickers | Resolves with time (≥2yr history) |
| `piotroski.dilution_check` | Financial.shares_outstanding cross-period | C/E | ~20% of tickers — some XBRL filers don't tag `CommonStockSharesOutstanding` (parser falls back to weighted-avg) | Parser improvement in scope |
| `piotroski.gross_margin_yoy` | Financial.gross_margin cross-period | E | New IPO only |
| `piotroski.asset_turnover_yoy` | Financial.asset_turnover (derived) cross-period | E | New IPO only |
| `f1.open_market_buyers_90d` | InsiderTransactionRecord (Form-4 code='P') | **D** for FPIs | SHOP: 0 records possible (FPI until 2026). For US-domestic filers: low base rate (most quarters have 0 P-buys; ~5–10% of tickers have any in a given 90d window). | FPI structural — needs Canadian SEDAR / equivalent foreign-jurisdiction insider feed |

#### F2 — Momentum / PEAD

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `momentum.12m_minus_1m` | computed from PriceHistory | E | Recent IPO only (~5% of tickers) | |
| `pead.signal` | EarningsHistory eps_surprise vs forward 60d return | C/E | Many tickers lack EarningsHistory rows (yfinance.earnings_history coverage gaps) | Parser improvement (consensus from alt source) |

#### F3 — Innovation Compounder

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `f3.gm_expansion_window` | Financial.gross_margin time-series | E | ~5% (IPO) | |
| `f3.rd_intensity` | Financial.rd_expense / revenue | C | **59.4% null** at annual-row level | Many filers bundle R&D in opex (consumer/services); some don't tag `ResearchAndDevelopmentExpense`. `rd_disclosure_state='bundled_in_opex'` is the partial fix. |
| `f3.surprise_streak_qtrs` | EarningsHistory continuity | C | High null rate | Consensus-data coverage issue (yfinance) |
| `f3.patent_portfolio_count` | n/a (not warehoused) | **A / source-gap** | **100%** | Most issuers don't disclose patent count in 10-K. USPTO bulk-data scraping is the only deterministic source. |

#### F4 — Stealth Accumulation

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `f4.short_interest_decline_3m` | ShortInterestRecord time-series | C | ~30% — yfinance short-interest history is patchy | yfinance / finra both incomplete; would need a dedicated short-interest source |
| `f4.13f_institutional_delta` | InstitutionalHolderRecord with `change_in_shares` populated | C | **`change_in_shares` is null for 100% of rows** — yfinance returns latest snapshot only, not deltas. Need SEC 13F bulk feed to compute QoQ deltas. | Parser improvement (SEC bulk 13F) is in scope |
| `f4.eps_acceleration_2q` | EarningsHistory continuity | C/E | Same as F3 surprise streak | |
| `f4.options_put_call_ratio` | n/a | **B** | **100%** — paid data only per PROJECT_SPEC §F4 (Pan-Poteshman 2006 cites Option Metrics IvyDB) | Paid data feed only |

#### F5 — Growth Quality (Fahlenbrach + Outsiders + Damodaran owner-earnings)

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `f5.revenue_cagr_3y` | Financial.revenue time-series ≥3y | E | ~10% (recent IPO) | |
| `f5.roic` | Company.roic (TTM-adjusted) | C | **56.5% null** — depends on having operating_income + IC components. Some filers don't tag `OperatingIncomeLoss` and our `_derive_oi_from_pretax_minus_nonop` fallback covers only some. | Parser improvement (more XBRL fallback aliases) |
| `f5.pt_adjusted_roic` | Company.pt_adjusted_roic | C | **64.7% null** | Same root cause + needs ≥1yr R&D history |
| `f5.buyback_yield` | derived: |share_repurchases| / market_cap | C | High null at FY level — `share_repurchases` from cash-flow statement often null for early-stage / non-buyer issuers (true zero for them) | True zero vs missing is the ambiguity |
| `f5.ceo_equity_pct` | Company.ceo_equity_pct (three-tier priority chain — see §1.3 below) | **D** for Canadian FPIs; **C** for sub-5% holders on issuers with no SC 13D | **10 / 10,143 disclosed_exact (0.10%) pre-fix; rising as priority chain backfills** | Three sources in priority order — SEC SC 13D/A (primary, ≥5% holders) → DEF 14A structured `proxy_season(0)` (secondary) → Canadian Management Information Circular in 6-K (tertiary, FPIs). HIMS investigation 2026-05-15 surfaced the priority-chain requirement after DEF 14A produced 87.73% voting-power-misread vs SC 13D's authoritative 11.1%. See §1.3 for the full priority logic. |
| `f5.is_founder_ceo` | Company.is_founder_ceo (regex on proxy/10-K bio) | C | 99.6% null — same MIC issue + parser is conservative (returns False when title doesn't carry "founder") | Manual override capability + better regex |
| `f5.ceo_tenure_years` | Company.ceo_tenure_years (regex on proxy) | C | High null | |

#### F6 — Platform Dominator

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `f6.customer_concentration_pct` | Financial.customer_concentration_pct (10-K risk-factors regex) | **A** for most issuers; **C** when language is unusual | **100% null** at annual level. Reg S-K Item 101(c) requires disclosure ONLY when >10% — most issuers below threshold don't quantify. | Issuer non-disclosure for low-concentration; parser miss only for those above-threshold-with-unusual-language |
| `f6.nrr_pct` | Financial.nrr_pct (10-K MD&A regex) | **A** for most | **100% null** at annual level. INTA discloses; SHOP doesn't (different audience: B2B SaaS vs marketplace). Both press-release and 10-K. | Issuer-dependent. Press releases / IR pages sometimes have it (INTA 123% verified 2026-05-15). |
| `f6.grr_pct` | Financial.grr_pct (10-K MD&A regex) | **A** for most | **100% null** at annual level | Almost no issuer discloses GRR; even NRR-disclosing issuers omit GRR |
| `f6.arr_state` | Financial.arr_state (10-K regex) | **A / C** | **100% null** | ARR tagging in XBRL is rare; most filers report in MD&A text only |
| `f6.rule_of_40` | derived: revenue_growth + fcf_margin | C/E | New IPO and `revenue=None` rows fail | |
| `f6.fahlenbrach_signal` | composite of ceo_equity_pct + tenure + founder | C | Inherits ceo_equity_pct null rate | Closes if ceo_equity_pct closes |

#### F7 — Smart Beta Timing

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `f7.ev_revenue_z_score` | derived from EV/Rev time-series, ≥5y | E | ~15% (recent IPOs) | Time-curable |
| `f7.pb_z_score` | derived from P/B time-series, ≥5y | E | Same | Time-curable |
| `f7.ev_rev_history_window` | PriceHistory + Company.market_cap | C / E | Some tickers have <5y of PriceHistory rows (parser miss) | Improve refresh path |

#### Overlays — ICA / PSA / BEW

| Field | Persisted at | Category | Universe-level null rate | Notes |
|---|---|---|---|---|
| `BEW.tam_estimate` | n/a (not warehoused) | **A** | **100%** | TAM is not in any SEC filing. Sector-research data or LLM extraction from analyst-day decks needed. |
| `BEW.sector_median_ev_revenue` | n/a (would need sector aggregation) | C | 100% null — never warehoused | In-scope engineering: aggregate from existing Company rows by sector |
| `PSA.parent_sector` | Company.parent_ticker → sector lookup | C | Used only for explicit spinoffs (rare); not warehoused | In-scope |

#### Company-level meta fields (cross-cutting)

| Field | Universe-level null rate | Category | Notes |
|---|---|---|---|
| `Company.beta` | **99.7%** | C | yfinance.info coverage gap. Recompute from PriceHistory regression |
| `Company.pe_trailing` | **99.8%** | C | yfinance gap |
| `Company.pb_ratio` | **99.6%** | C | yfinance gap |
| `Company.shares_float` | 40.7% | C | yfinance + 13F partial |
| `Company.market_cap_usd` | <5% | C | Most populated; some IPO lag |

### 1.3 The three-tier priority chain for `ceo_equity_pct`

**Trigger for this subsection**: the HIMS Dudum investigation 2026-05-15 surfaced that DEF 14A alone is insufficient for multi-class issuers (Dudum's actual economic equity is 11.1% per SEC Rule 13d-3, but DEF 14A's rightmost % column was 87.73% **Total Voting Power** — a different number entirely). Subsequent audit across 9 tickers found that the right source depends on **issuer type** and **CEO ownership level**, with three distinct populations:

| # | Source | Form | Authority | Wired in |
|---|---|---|---|---|
| **1 — PRIMARY** | SC 13D / 13D/A cover Row 13 | SEC EDGAR | SEC Rule 13d-3 — regulator-defined, uniform across issuers, calculated on an "as-if-converted, options-exercised" basis | `data/edgar_fetcher.py:fetch_latest_ceo_sc13d()` + parser at `data/edgar_text_parser.py:parse_sc13d_ownership()` |
| **2 — SECONDARY** | DEF 14A beneficial ownership table | SEC EDGAR | Issuer-prepared. Conventions vary by issuer: strict-class vs as-if-converted basis, blank cells vs `*` for sub-1%, "% of Class" vs "% of Voting Power" rightmost columns. **Multi-class issuers require column-classification logic** (parser shipped 2026-05-15) | `fetch_edgar_proxy_ownership` via `edgartools.proxy_season(0).proxy.beneficial_ownership` + HTML-table parser fallback |
| **3 — TERTIARY** | Canadian Management Information Circular | EDGAR (6-K EX-99.1 attachment) | Canadian equivalent of US DEF 14A. Required for FPIs (SHOP, BB, CSU pre-domestic-filer conversion). UK / German / other FPIs use 20-F appendices analogously | `parse_mic_ownership` + 6-K probe loop in `fetch_edgar_proxy_ownership` |

**Discovery + match logic** (in source-priority order):

1. Run DEF 14A path via existing `edgartools.proxy_season(0).proxy.beneficial_ownership` (secondary; this is the baseline)
2. If DEF 14A returned None AND `ceo_name` is known → probe last 30 6-K filings for circular attachments; sort matches by size descending (largest = real MIC, smallest = SEC cover form); apply `parse_mic_ownership` (tertiary)
3. **Regardless of secondary/tertiary outcome**, if `ceo_name` is known: probe issuer's SC 13D / 13D/A filings; for each, check whether the cover-page **Names of Reporting Persons** matches the CEO's last name (word-boundary, case-insensitive); if a match is found, the SC 13D's **Percent of Class** (Row 13) **OVERRIDES** whatever secondary/tertiary produced. Method becomes `sec_sc13d_cover`.

**Strict reporting-person match is non-negotiable** — among 9 tickers audited 2026-05-15, only HIMS had the CEO as the actual 13D reporting person. The others (INTA Hill Investors, SHOP-as-KVYO-owner, LULU founder trust, etc.) had 13Ds from different parties. Naïvely using any 13D would have silently corrupted F5 scoring for 5+ tickers.

**Validation matrix** (post-implementation 2026-05-15):

| Ticker | CEO | Source used | Value | State |
|---|---|---|---|---|
| HIMS | Andrew Dudum | `sec_sc13d_cover` (primary) | 11.10% | disclosed_exact |
| INTA | John T. Hall | `structured_xbrl` (secondary) | 7.64% | disclosed_exact |
| SHOP | Tobias Lütke | `canadian_mic_6k` (tertiary) | 6.18% | disclosed_exact |
| NVDA | Jen-Hsun Huang | `structured_xbrl` (secondary) | 3.58% | disclosed_exact |
| LULU | Meghan C. Frank | `structured_xbrl` returns null | None | not_disclosed (Frank may genuinely be below disclosure threshold) |
| COST | Ron Vachris | `structured_xbrl` → `*` redaction handled | 0.5 | disclosed_exact (under-1% convention) |

**Failure modes the priority chain protects against:**

- **Voting-power-as-equity confusion** (HIMS pattern) — multi-class issuer's DEF 14A rightmost column may be voting power; SC 13D's Row 13 is unambiguous beneficial ownership
- **Reporting-person misattribution** (LULU/INTA pattern) — a 13D on the issuer's CIK isn't necessarily filed by the current CEO
- **FPI gap** (SHOP pattern pre-domestic-filer conversion) — no DEF 14A exists; the MIC in 6-K is the equivalent disclosure
- **Below-threshold case** (NVDA pattern) — CEO below 5%, no 13D exists, DEF 14A is the only source

### 1.4 Form 4 RSU + option vesting — temporal drift between SC 13D refreshes

**Concept**: between SC 13D filings (which only refresh on thresholds and material-change events — typically months to years apart), the CEO's actual beneficial ownership changes via every-time-they-transact Form 4 events:

- Code `A` (award / grant) — RSU grants, stock option grants → +shares
- Code `M` (option exercise) — option exercised → +shares
- Code `F` (tax-withholding share surrender) — net-settle on RSU vest → −shares
- Code `S` (open-market sale) — secondary-market sale → −shares
- Code `D` (disposition not for cash) → −shares
- Code `P` (open-market purchase) — rare for already-large insider holders → +shares
- Code `G` (gift) → −shares

**Drift magnitude observed for HIMS Dudum (2024-10-25 SC 13D/A → 2026-04-28 DEF 14A, ~18 months):**

| Source | Aggregate shares | % of class |
|---|---|---|
| SC 13D/A 2024-10-25 | 24,621,321 | 11.1% |
| DEF 14A 2026-04-28 | 23,770,337 | not stated (cell blank) |
| Delta | **−850,984 shares (~3.5%)** | |

That is the cumulative effect of ~18 months of vesting, tax withholdings, secondary sales, and option exercises. **The drift is materially small but non-zero** — for `f5.ceo_equity_pct` to be perfectly accurate at any moment between SC 13D refreshes, we would need to sum Form 4 deltas since the last 13D.

**Current policy (2026-05-15)**: snapshot per latest SC 13D / DEF 14A / MIC. Form 4 drift is acknowledged but not computed forward. F5 scoring's 5% threshold is robust to ~3-5% drift; founder_aligned wouldn't flip on a tier-A CEO crossing 5% via grant/sale activity in either direction within an annual cycle.

**Aspirational policy (Phase 2+ enhancement)**: compute "real-time" beneficial ownership as:
```
real_time_holdings = latest_sc13d_aggregate + Σ form_4_deltas[since latest_sc13d.filing_date]
real_time_pct      = real_time_holdings / shares_outstanding_now
```
This would require:
- `data/edgar_fetcher.py:fetch_edgar_insiders` already populates `InsiderTransactionRecord` rows with `transaction_type`, `shares`, `is_open_market`
- A new accumulator function summing signed deltas (signs depend on transaction code per the table above)
- A re-publishing step that updates `Company.ceo_equity_pct` periodically (cron-scheduled or on each `invest dive`)

**Constraints on the aspirational solution**:
- The Form 4 issuer-filter shipped 2026-05-15 must be honored — non-issuer transactions must not contaminate the sum (the SHOP-as-Klaviyo-10%-owner pattern)
- Transaction codes must be normalised — empty codes (the pre-fix corpus state) should NOT participate in any sum; a one-time backfill via `_parse_form4` against the canonical issuer-filtered Form-4 feed is a precondition
- Some Form 4s report indirect-ownership (held by trusts / family members) which IS included in SEC Rule 13d-3 beneficial ownership but is sometimes confused with direct-ownership in the same filing's "Form 4 Table II Derivative" section. A clean delta calculation requires careful handling per code

**Recommended cadence**: this enhancement belongs in Phase 2 (after the SC 13D / DEF 14A / MIC priority chain has been live across the universe for ≥6 weeks and we have a body of evidence about drift). Likely an `invest data refresh-ceo-ownership` subcommand or as part of an `invest data refresh --include-form4-deltas` flag.

**Decision-deferred-here**: should `Company.ceo_equity_pct` reflect the snapshot value (today's policy, simple, drifts by 3-5% over a year) or the real-time computed value (future policy, accurate, requires Form 4 normalisation prerequisite)? Defer until §11 open-question evaluation.

### 1.5 Aggregate picture

| Root cause | Rough % of total observed gaps (weighted by user-visible impact) | Solvable by us? |
|---|---|---|
| **A — Issuer non-disclosure** | ~35% | Only via supplementary source (LLM extraction, paid feed, manual override) |
| **B — Source-policy exclusion** | ~5% | Paid feed only |
| **C — Parser miss** | ~40% | Yes, deterministic engineering — in-scope |
| **D — FPI structural** | ~10% | Foreign-jurisdiction feed (SEDAR, etc.) |
| **E — Insufficient history** | ~10% | Time alone resolves |

**The interesting half (A + D, ~45% of all observed gaps) cannot be closed without going outside SEC EDGAR / edgartools / polygon / yfinance.** That is the population this ADR is really about.

---

## 2. Solution alternatives

For each gap we have these orthogonal solution options. They are not mutually exclusive — different categories of gaps may use different solutions.

### Option 1 — LLM extraction from public source documents (the prototype shipped 2026-05-15)

**How**: `deepdive/external_signals.py` (already built):
- Deterministic fetch of SEC 8-K EX-99.1 earnings press releases via edgartools
- Anthropic Sonnet 4.6 with tool-use forced JSON schema, temperature=0
- Verbatim-quote requirement enforced in the system prompt
- Persisted to `external_signals` table with full audit trail
- Displayed in a clearly-labelled yellow panel (per ADR-022 source provenance discipline)
- F1–F7 framework scoring path does NOT read this channel

**Strengths**:
- Catches A-category gaps that no parser can reach (issuer-disclosed-only-in-press-release)
- Audit trail is rigorous (verbatim quote, accession, model, timestamp)
- Honest non-disclosure handling: LLM returns `confidence='not_disclosed'` when source genuinely lacks the value — same discipline as the deterministic `data_gaps[]` list
- Architectural moat preserved (CLAUDE.md §"AI layer boundary" extended in a controlled way to a second permitted call site)

**Weaknesses**:
- Costs tokens (see §3 for analysis)
- Limited to whatever the LLM can read; transcripts behind paywalls (Tegus, AlphaSense) inaccessible
- Cannot bridge B-category (options data) — the underlying source still doesn't exist
- Adds Anthropic SDK as a soft dependency for non-narrative paths (today's narrative.py was the ONLY call site)

### Option 2 — Paid data feeds

**Vendors evaluated** (qualitative — no quotes pulled):
- **S&P Capital IQ / CapIQ Pro**: comprehensive; covers NRR/customer concentration/segment data where issuers report them. Enterprise pricing (5-figure annual minimum).
- **Refinitiv (LSEG) Eikon**: similar profile, similar price.
- **FactSet**: same.
- **Visible Alpha**: dedicated consensus + estimate data. Cheaper than CapIQ for a narrower scope.
- **Tegus**: expert-call transcript library. Excellent for qualitative; not structured numerics.
- **AlphaSense**: financial transcript search. Mid-market pricing.
- **Tikr / Stockanalysis.com / Simply Wall St**: consumer-grade; mixed reliability; not API-grade for systematic use.
- **OptionMetrics IvyDB**: would close F4 options put/call. Academic-license channel exists; price unknown.

**Strengths**: high-quality structured data; large fields covered; legal/contractual data rights.

**Weaknesses**: cost prohibitive at retail-individual scale; vendor lock-in; covers A but not D (FPI alternative-source needs); typically does not include the press-release-only qualitative metrics where issuers disclose informally.

### Option 3 — Web scraping company IR pages / investor decks

**How**: fetch each ticker's IR page (e.g., investors.shopify.com), parse the most recent investor presentation PDF, regex/extract.

**Strengths**: closes A-category for issuers that publish quantified KPIs in decks but not in 10-K (common pattern for SaaS).

**Weaknesses**:
- Fragile: every IR site is bespoke; layout changes break extraction
- Legal: some IR pages prohibit automated scraping in their ToS
- PDF parsing quality varies wildly
- Maintenance cost amortises poorly — every 10–20 tickers needs custom logic

### Option 4 — Manual research with persisted overrides

**How**: extend the schema with a `manual_override` table; CLI subcommand `invest override TICKER --field nrr_pct --value 123.0 --source "Q1 2026 call, 5:32" --confidence high`. F1–F7 read from `manual_override` ONLY when explicitly enabled per-dive; default-off.

**Strengths**:
- Maximally accurate when the user has done the research
- Zero new infrastructure
- Composable with any of the above (LLM-extracted → user reviews → user signs off → promote to override)

**Weaknesses**:
- Labor-intensive; doesn't scale to the 10k universe
- Quality dependent on user discipline
- Updates required every quarter

### Option 5 — Status quo (accept the gap)

**How**: continue treating `not_disclosed` as a valid analytical signal — the F6 design already does this ("most companies don't quantify NRR; absence ≠ failure"). Frameworks score 0 with a positive-signal note; composite renormalises around missing frameworks.

**Strengths**:
- No additional cost
- Architectural moat unchanged
- Honest: communicates *"we don't know"* to the user, which IS information

**Weaknesses**:
- Leaves the narrative thinner than it could be
- Some user decisions (sizing on a SaaS where NRR is the moat signal) lose their primary input
- Two competing strong-conviction theses about the same name can't be distinguished if both are based on undisclosed metrics

### Option 6 — Foreign-jurisdiction filing parsers (D-category only)

**How**: build SEDAR (Canada) / Companies House (UK) / EDINET (Japan) etc. parsers for FPI tickers. The MIC parser shipped 2026-05-15 is the first such — it reads Canadian Management Information Circulars from 6-K exhibits and extracts CEO equity %.

**Strengths**: closes D-category deterministically (same discipline as US EDGAR)
**Weaknesses**: per-jurisdiction engineering cost; document formats vary

---

## 3. Token-cost analysis for Option 1 (LLM extraction)

### 3.1 Empirical anchor (actual measurements, 2026-05-15)

| Ticker | Source | Prompt tokens | Completion tokens | Cost (Sonnet 4.6, uncached) |
|---|---|---|---|---|
| SHOP | Q1 2026 8-K EX-99.1 (14,738 chars) | 5,133 | 446 | **$0.0221** |
| INTA | Q1 2026 8-K EX-99.1 (26,265 chars) | 8,908 | 486 | **$0.0340** |
| **Mean** | — | ~7,000 | ~470 | **$0.0281** |

### 3.2 Pricing assumptions (Anthropic public, 2026)

| Token type | Price/1M tokens |
|---|---|
| Input (uncached) | $3.00 |
| Output | $15.00 |
| Cache write | $3.75 (1.25× base input) |
| Cache read | $0.30 (0.10× base input) |

System prompt is ~1,500 tokens, stable across all extractions → cacheable. Caching yields **~14% per-call savings** for warm sessions.

### 3.3 Universe-level projections (annual)

| Scenario | Extractions/yr | Annual cost |
|---|---|---|
| Per-dive ad-hoc (~100/month) | 1,200 | **$33.66** |
| Watchlist refresh (50 tickers, weekly) | 2,600 | $72.93 |
| Screener candidates (500 tickers, quarterly) | 2,000 | $48.00 |
| Active universe (1,000 tickers, quarterly) | 4,000 | $96.00 |
| Full universe (10,143 tickers, quarterly) | ~40,000 | **$960.00** |

### 3.4 Latency + rate limits

- Single extraction: ~1.5–3.0 seconds (Sonnet 4.6, ~500-token output via forced tool-use)
- Anthropic rate limits (Tier-1, $20+ usage): 4,000 RPM, 2M input TPM
- A full-universe quarterly pass takes ~3 hours wall-clock with naive single-threaded calling; ~20 minutes with 8-way concurrency

### 3.5 Cost-per-gap-closed quality bar

A useful sanity check: what does each closed gap actually cost?

- SHOP extraction closed 2 high-confidence signals (GMV, MRR) and confirmed 5 non-disclosures
- INTA extraction closed 2 high-confidence signals (NRR triangulated, ARR new) and confirmed 5 non-disclosures
- ~2 closed signals per extraction × $0.028 / extraction = **$0.014 per signal added to the dive narrative**

For comparison: a single S&P Capital IQ seat is on the order of $25,000/year. To match that cost we would need to run ~890,000 LLM extractions — i.e., the full 10k universe quarterly for 22 years.

### 3.6 Caveats

- **Quality degrades with prompt size**. Press releases are short (~5–10k tokens). Earnings call transcripts are 50k+ — would push cost ~5× and risk attention-budget issues. Need separate prompt engineering for transcripts (chunk + map-reduce).
- **Model drift**. Sonnet 4.6 today; Sonnet 4.7 / Opus 5 tomorrow. Costs may move ±50% over 12–18 months. ADR should not assume static pricing.
- **Cache TTL is 5 min** in current Anthropic API. Batch processing (cache-warm) only realises savings within a single batch run.
- **Hallucination risk** mitigated but not zero. The verbatim-quote requirement catches most fabrication; periodic spot-check audit (sampling 5% of `external_signals` rows and validating quotes against source URLs) is recommended.

---

## 4. Decision

### 4.1 What is decided

1. **Adopt the Gap Register itself.** Every observed gap is classified by root cause (A–E). Future framework / overlay PRs that introduce a new gap MUST update §1.2 of this ADR. The register becomes the canonical inventory.
2. **Confirm the architectural moat is non-negotiable.** F1–F7 framework scoring path remains LLM-free and deterministic. Any supplementary signal (LLM-extracted, paid feed, manual override, web-scraped) MUST live in an isolated channel with audit trail, MUST be rendered with explicit "supplementary — not in composite" labelling, and MUST be discardable without breaking the dive.
3. **Adopt the `external_signals` channel architecture** built 2026-05-15 as the canonical pattern for ALL future supplementary-data sources, regardless of which source(s) we choose. The schema (`source_url`, `source_quote`, `source_document`, `extraction_method`, `extraction_confidence`, `extracted_model`, `extracted_at`) is the contract.
4. **Confirm the existing rule** that LLM calls outside `deepdive/narrative.py` and `deepdive/external_signals.py` are forbidden. These are the only two permitted call sites — both within the dive layer, both isolated from screener / framework paths.

### 4.2 What is deferred

The **source-selection decision** for each gap category is deferred:

| Category | Candidate solutions | Decision deferred until |
|---|---|---|
| A — Issuer non-disclosure | Option 1 (LLM), Option 4 (manual), Option 5 (status quo) | After §4.3 quality audit |
| B — Source-policy exclusion | Option 2 (paid feed) only | Budget-allocation review |
| C — Parser miss | Engineering effort (in-scope) | Prioritised in normal backlog |
| D — FPI structural | Option 6 (foreign-jurisdiction parsers) | Per-jurisdiction; Canadian MIC done |
| E — Insufficient history | Time | Self-resolving |

### 4.3 Acceptance criteria for any chosen supplementary source

Any future PR that adds a new supplementary data source (LLM, paid feed, scraper) MUST satisfy:

1. **Architectural isolation** — writes to `external_signals` table or equivalent isolated channel; framework code never reads it
2. **Full provenance** — every numeric value has a verbatim-quotable source citation (URL + accession # + quote + extraction method + confidence)
3. **`not_disclosed` honesty** — when the value genuinely isn't in the source, the row records `not_disclosed` rather than fabricating
4. **Idempotent re-extraction** — running the extractor twice on the same source produces identical rows (deterministic when source is fixed)
5. **Visible cost ceiling** — annual budget projection in this ADR's §3 format
6. **Quality audit hooks** — sampling-based spot-check capability (random 5% audit of persisted rows against source URLs)
7. **No retroactive corruption** — flipping a source on/off must not change any historical framework score

### 4.4 Specific guidance for the LLM-extraction option (if/when adopted)

If Option 1 is selected (the prototype is already shipped, so this would be making the prototype production):

- **Default model**: Sonnet 4.6 — the cost-quality sweet spot for structured extraction
- **Default cadence**: per-dive on-demand, not auto-batched. The CLI subcommand `invest dive TICKER --external-signals` would opt in.
- **Universe-batch cadence**: quarterly only, gated by an explicit CLI flag (`invest data refresh-external-signals --universe screener_candidate`). Never automatic from a cron.
- **Cost ceiling**: $100/month hard ceiling enforced in code. Exceed → abort + alert.
- **Sample audit**: monthly cron samples 5% of rows added in the past 30 days, refetches the source URL, compares the persisted quote against current text. Mismatches escalate.
- **Token budget breakdown**:
  - Ad-hoc dives: ~$3/month (1,200/year at current dive rate)
  - Quarterly refresh of screener candidates (~500): ~$50/year
  - Full universe quarterly: ~$1,000/year (out of policy unless explicitly authorised)

### 4.5 Specific guidance for any paid-feed option (if/when adopted)

If Option 2 is selected:
- The vendor's terms-of-service govern data redistribution; persisted rows must NOT be exported/shared without re-licensing review
- A vendor's value is signalled via the `source_document` field (e.g., `'capiq_xbrl_api'`); rows from a paid feed have `extraction_method='paid_feed'`
- Vendor-disagrees-with-issuer cases (FactSet says NRR=130%, IR page says 125%) MUST surface in the dive output as a "source divergence" warning — never silently average

### 4.6 Specific guidance for the status-quo option (Option 5)

Default if no decision is made. The existing system handles this gracefully — `not_disclosed` is a first-class verdict in F6 — but the gap register makes the lost-information surface visible to the user, which itself is a quality improvement over today.

---

## 5. Open questions

1. **Cost of one quarter's "complete" picture**: at ~$50/quarter for screener candidates, the LLM option pays for itself if it lifts one decision per quarter from "WATCHLIST" to actionable. Is that a low bar or a high bar?
2. **The cache-TTL workflow**: do we want to batch all watchlist extractions in a single 5-minute window to amortise the cache write? Or accept the 14% premium for ad-hoc flexibility?
3. **Transcript vs press-release source choice**: press releases are short and cheap; earnings call transcripts are 5–10× longer and ~5× more expensive but contain more qualitative detail. Recommend press releases as default; transcripts as opt-in per-ticker (`--source transcript`).
4. **Quality SLA**: how often is the LLM allowed to be wrong before we revoke its trust? Suggest: spot-audit shows >5% quote-mismatches → suspend the extractor pending root-cause analysis.
5. **The "narrative LLM citing external_signals" question**: the existing `deepdive/narrative.py` reads from ScorecardView. Should it ALSO be able to cite from `external_signals` rows? If yes, those citations must surface with their provenance in the narrative output (per ADR-023 §1.4 grounding requirements).
6. **Manual override channel** (Option 4): worth building independent of any LLM/paid-feed decision, because it composes with all of them. Probably the lowest-cost-highest-value increment.
7. **`ceo_equity_pct` snapshot vs real-time** (added 2026-05-15): should the canonical `Company.ceo_equity_pct` field reflect the **snapshot** at the latest SC 13D/A / DEF 14A / MIC filing (today's policy — simple, drifts by ~3-5% over a year of vesting/sales activity), or the **real-time computed value** from `latest_snapshot + Σ Form_4_deltas[since latest_snapshot.filing_date]` (future policy — accurate at any moment, but requires Form 4 transaction-code normalisation and indirect-vs-direct ownership handling — see §1.4)? **Recommendation**: defer the real-time computation until the snapshot-priority-chain has accumulated ≥6 weeks of evidence about drift magnitude. F5's 5% threshold is robust to 3-5% drift; founder_aligned wouldn't flip on annual-cycle activity in either direction.
8. **Form 4 issuer-filter backfill prerequisite** (added 2026-05-15): before any real-time-computation enhancement (Q7), the existing `InsiderTransactionRecord` corpus needs a one-time pass with the new `_parse_form4` issuer-filter (shipped 2026-05-15). Pre-fix records have `transaction_type=''` (empty) which prevents signed-delta accumulation. The HIMS / SHOP / INTA refetch in this session demonstrated the procedure; a `data refresh-form4-corpus` subcommand should generalise it.

---

## 6. Coordination with related ADRs

- **ADR-021 (Peters-Taylor; no SBC add-back)**: unchanged. Methodology rules for the deterministic path remain in force.
- **ADR-022 (Methodology disclosure)**: §1.1 of ADR-022 requires every metric to declare its source. This ADR-031 extends that requirement to the supplementary-data channel: every `external_signals` row carries the same source provenance that ADR-022 mandates for canonical fields.
- **ADR-023 (Narrative personality)**: the narrative LLM (deepdive/narrative.py) is now joined by a second permitted Anthropic call site (deepdive/external_signals.py). ADR-023's "constrained to pre-computed quant metrics" rule applies to the narrative path; the extraction path has its own rules (§4.4 of this ADR).
- **ADR-024 (Mental-models library)**: `mental_models/core/margin_of_safety.md` antipattern: *"Inferred values filling missing data ('approximately X based on sector average')"*. The LLM extraction path satisfies this — it never infers; it either quotes verbatim or returns `not_disclosed`.
- **ADR-025 (IFRS / FPI universe)**: the FPI-structural gap category (D) is exactly the population ADR-025 addresses. The Canadian MIC parser shipped 2026-05-15 is one of the foreign-jurisdiction parsers ADR-025 envisaged.

---

## 7. Non-goals

- This ADR does NOT replace any framework with LLM-derived values
- This ADR does NOT change the composite scoring formula
- This ADR does NOT mandate that every dive run extraction (cost ceiling)
- This ADR does NOT decide between vendors — it defines the criteria
- This ADR does NOT decide between LLM models — it defines the budget and quality bar

---

## 8. Implementation status (2026-05-15, latest amendment)

| Component | Status |
|---|---|
| Gap register §1.2 | ✅ Documented in this ADR — canonical source going forward |
| `external_signals` table schema | ✅ Shipped (alembic `v3d4e5f6a7b8`) |
| `deepdive/external_signals.py` extractor | ✅ Shipped (~400 LOC, Sonnet 4.6, tool-use forced JSON, verbatim-quote enforced). Two extraction targets: earnings-press-release signals (NRR/ARR/MRR/GMV) + DEF-14A/13D ownership (`extract_ceo_equity_via_llm`) |
| `cli/main.py:_render_external_signals` display | ✅ Shipped (yellow panel; visible in `invest dive` and `invest score-card`) |
| SHOP + INTA extractions validated | ✅ Done (7 signals each, with audit trail) |
| HIMS Dudum CEO-equity triangulation | ✅ Done — 4-source agreement on 11.1% (SC 13D/A, LLM-on-13D, LLM-on-DEF-14A, computed-from-shares) |
| **`ceo_equity_pct` three-tier priority chain** (§1.3) | ✅ Shipped 2026-05-15. SC 13D/A (primary) + DEF 14A structured XBRL (secondary) + Canadian MIC (tertiary). Validated on HIMS / INTA / SHOP / NVDA. `data/edgar_text_parser.py:parse_sc13d_ownership`, `data/edgar_fetcher.py:fetch_latest_ceo_sc13d` + integration into `fetch_edgar_proxy_ownership` |
| **DEF 14A multi-class column-classification fix** | ✅ Shipped — header-aware column routing (economic vs voting); strict %-literal regex (prevents the HIMS-87.73%-voting-power-misread failure mode); signature-based table discovery (replaces 24-table-walk-from-heading) |
| **Form 4 RSU+option vesting drift** (§1.4) | 📋 Documented as Phase 2+ enhancement. Snapshot policy (today) is robust at the F5 5% threshold. Real-time-computation prerequisite: Form-4 issuer-filter backfill across InsiderTransactionRecord corpus |
| Pipeline auto-invocation (LLM) | ❌ NOT shipped — by design. Awaits §4.4 decision |
| Sample-audit cron | ❌ NOT shipped — required before universe-batch usage |
| Cost-ceiling enforcement | ❌ NOT shipped — required before universe-batch usage |
| ADR-031 itself | ✅ This document (amended 2026-05-15 with §1.3 priority chain + §1.4 Form-4 drift) |

---

*The architectural moat is intact: deterministic data flows through F1–F7 unchanged; supplementary data lives in an isolated, auditable, clearly-labelled channel. The decision of which supplementary source(s) to permit, at what cadence, with what budget — that decision is now visible, evidenced, and deliberately deferred until the user is ready to make it.*

---

## Amendment log

- **2026-05-15 (initial)**: ADR-031 written. Gap register §1.2 enumerated all observable gaps across F1–F7 + overlays. Six solution options evaluated (§2). LLM-extraction token costs (§3). Acceptance criteria §4.3. `external_signals` table + isolated channel shipped.
- **2026-05-15 (amendment 1 — priority chain)**: §1.3 added documenting the three-tier `ceo_equity_pct` priority chain (SC 13D/A → DEF 14A → Canadian MIC). Triggered by HIMS Dudum investigation where DEF 14A produced 87.73% (voting power) when SC 13D's authoritative figure was 11.1% (economic equity per SEC Rule 13d-3). §1.2 F5 row updated. Validated across HIMS / INTA / SHOP / NVDA / LULU / COST.
- **2026-05-15 (amendment 2 — Form 4 drift)**: §1.4 added documenting the temporal drift between SC 13D snapshots via Form 4 RSU/option/sale activity. Current policy: snapshot. Aspirational policy: real-time computation from `latest_snapshot + Σ signed_form_4_deltas`. Decision deferred to §5 Open Questions 7+8 with prerequisites enumerated.
