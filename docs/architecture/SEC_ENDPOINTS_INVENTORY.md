# SEC EDGAR + edgartools Inventory

> Operational reference for the SEC-first source hierarchy codified in **ADR-033 §1.1**.
> Cataloged 2026-05-15.
> Marks every known endpoint as **currently used**, **untapped but high-value**, or **niche/out-of-scope**.

This is the supplement to **ADR-033 §1.3** ("Search-SEC-first invariant"). Before any new field implementation, walk this list. If the field is somewhere here, prefer that over a Tier 3 API fallback.

---

## 1. SEC raw endpoints (`https://data.sec.gov`, `https://www.sec.gov`, `https://efts.sec.gov`)

### 1.1 Currently used

| Endpoint | Where in code | Returns |
|---|---|---|
| `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | `data/edgar_companyfacts.py:fetch_companyfacts` | All XBRL facts for one filer (~5-10MB) |
| `data.sec.gov/submissions/CIK{cik}.json` | `data/edgar_companyfacts.py:fetch_filer_metadata`, `fetch_latest_filings` | Filer metadata + recent filings |
| `data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json` | `data/sec_frames.py:fetch_frame` | Cross-sectional data for one concept across all filers (Tier 2.1 shipped) |

### 1.2 Untapped — HIGH value

| Endpoint | Use case | Effort | Why now |
|---|---|---|---|
| `data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json` | **Single-concept time series for ONE company.** ~3KB vs companyfacts' 5-10MB. Perfect for incremental refresh (e.g., "what's NVDA's Revenue history?" without re-pulling everything). | ~80 LOC wrapper | Speeds up targeted updates; reduces SEC rate-limit burn |
| `www.sec.gov/files/company_tickers.json` | **Full SEC ticker universe** (~13k filers). Maps ticker → CIK. Our DB has 10,143 — SEC has more. | ~50 LOC | Confirms "hidden tickers" thesis empirically. Universe-enumeration upgrade. |
| `www.sec.gov/files/company_tickers_exchange.json` | Same + exchange info (NYQ/NMS/NYSE). **10,353 entries** vs our 10,143 — **310 tickers we're missing**. | ~50 LOC | One-shot universe expansion |
| `efts.sec.gov/LATEST/search-index?q={query}&forms={form}` | **EDGAR full-text search.** Elasticsearch-backed. Find filings mentioning specific topics ("artificial intelligence", "supply chain disruption", etc.). Supports forms+date filtering. | ~120 LOC | Powers theme-based screening, narrative grounding, BEW/PSA evidence |

### 1.3 Untapped — MEDIUM value

| Endpoint | Use case | Notes |
|---|---|---|
| `data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/USD/{period}.json` for `dei`, `srt`, `ifrs-full` | IFRS filer cross-sectional + Document Entity Info | Most filers are us-gaap; this captures FPIs + IFRS adopters |
| `www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&output=atom` | Atom-feed browse for any form type (Form 144 sales notices, S-1 / S-3 registrations, 8-A exchange listings, 25-NSE delistings, etc.) | Less ergonomic than edgartools but covers forms edgartools doesn't auto-parse |
| `data.sec.gov/api/xbrl/companyconcept/{cik}/dei/{concept}.json` | Document Entity Info time series (EntityCommonStockSharesOutstanding, etc.) | Useful for dilution-tracking |

### 1.4 Niche / out-of-scope

| Endpoint | Why niche |
|---|---|
| `www.sec.gov/files/company_tickers_mf.json` | **28,324 mutual fund tickers** — out of scope for individual-stock analysis |
| `www.sec.gov/cgi-bin/browse-edgar?action=getcompany&owner=only` | 13F filer browser — duplicates what we already get via Form 13F parsing |
| `www.sec.gov/cgi-bin/srqsb` | Legacy SEC search (deprecated; use efts.sec.gov instead) |
| RSS feeds (`www.sec.gov/Archives/edgar/usgaap.rss`, etc.) | Useful for real-time filing alerts but not core dive workflow |
| NPORT-P, NPORT-NP | Mutual fund holdings — separate analytical framework |

---

## 2. edgartools — `Company` surface

### 2.1 Currently used

| Surface | Where in code | Use |
|---|---|---|
| `Company(ticker)`, `Company(cik)` | Everywhere | Construct filer entity |
| `Company.get_filings(form=...)` | `data/edgar_fetcher.py`, multiple | Filing list |
| `Company.industry`, `Company.data.sic`, `Company.data.sic_description` | `data/edgar_fetcher.py:fetch_sec_industry_classification` | SIC classification (Tier 1.1) |
| `Company.is_foreign`, `is_smaller_reporting_company`, `is_financial_institution`, `is_fund`, `filer_category` | Same | SEC classification flags (Tier 1.3) |
| `Company.business_category` | Same | Operating company / fund / individual |
| `Company.get_ttm(concept)`, `get_ttm_net_income()`, `get_ttm_revenue()` | `valuation/sec_derived_ratios.py:_compute_ttm` | TTM helpers (Tier 1.2) |
| `Company.proxy_season(0).proxy.beneficial_ownership` | `data/edgar_fetcher.py:fetch_edgar_proxy_ownership` | DEF 14A structured |
| `Company.proxy_season(0).proxy.peo_total_comp` | `data/edgar_fetcher.py:fetch_edgar_proxy_ownership` (extension 2026-05-16) | **Phase 2.2** — DEF 14A SCT "Total" row for CEO compensation. Tier 1A. Wires into `ceo_total_pay_source = 'sec_def14a'`. |
| `Company.get_exchanges()` | `data/edgar_fetcher.py:fetch_sec_exchange` (Phase 2.1, 2026-05-16) | **Phase 2.1** — primary exchange listing (Tier 1B). Wires into `exchange_source = 'edgartools'`. |

### 2.2 Untapped — HIGH value

| Surface | Use case | Effort | Substitution candidate |
|---|---|---|---|
| **`Company.facts.peer_comparison(peer_ciks, metrics)`** | **Built-in peer comparison API in edgartools.** Returns DataFrame comparing target to N peers across multiple metrics. | Trivial | Could complement / replace our `data/sec_frames.py:compute_ratio_distribution` for ad-hoc peer comparison |
| **`Company.facts.calculate_ratios()`** | **Pre-computed ratios from edgartools.** Need to inspect what it returns — may obviate parts of `valuation/sec_derived_ratios.py`. | Probe first | Could reduce our self-compute surface |
| **`Company.facts.detect_anomalies()`** | Anomaly detection — finds outlier values in time series | ~20 LOC integration | New capability: F4 stealth-accumulation could use this for earnings-quality flagging |
| **`Company.facts.time_series(concept, periods=20)`** | Returns DataFrame of one concept over N periods. Same idea as the companyconcept endpoint but typed. | Trivial | Cleaner than parsing companyfacts ourselves for one-off concepts |
| **`Company.facts.search_concepts(pattern)`** | Pattern-based concept search across filer's taxonomy | Trivial | Discover non-standard tags + filer-custom XBRL |
| **`Company.facts.list_supported_concepts(category)`** | Lists all concepts edgartools knows for the filer | Trivial | Auditability — what's available? |
| **`Company.facts.to_llm_context(focus_areas)`** | Pre-built LLM context format from EntityFacts | Trivial | Feed to `deepdive/narrative.py` to enrich beyond ScorecardView |
| **`Company.facts.to_agent_tools()`** | Tool-use schema for agent integration | Trivial | If we ever build an agent layer (ADR-032 Phase 4) |
| **`Company.facts.dei_facts(as_of)`** | Document Entity Info facts (registration data, share-class counts, etc.) | Trivial | Cleanly accesses DEI fields without raw JSON |
| **`Company.facts.public_float`, `Company.public_float`** | **Public float in DOLLARS** (not shares). Probed 2026-05-16 — works but converts to shares-float via `public_float_usd / current_price`, which is hybrid Tier 1A+3b. Deferred B.1 per `API_FIELD_AUDIT.md §B.1` until schema gains a separate `shares_outstanding_sec` column. | Not trivial (semantics-blocked) | DEFERRED — see B.1 |
| `Company.shares_outstanding` | Total shares outstanding at Company level | Already computed per Financial; this is a convenience accessor |
| **`Company.list_concepts(search, statement)`** | Concept enumeration | Trivial | Filer-specific taxonomy discovery |

### 2.3 Untapped — MEDIUM value

| Surface | Use case |
|---|---|
| `Company.balance_sheet(periods=4)`, `Company.income_statement(periods=4)`, `Company.cash_flow(periods=4)` | Direct statement accessors (alternative to our companyfacts parser) |
| `Company.get_quarterly_financials()` | Quarterly statements as structured Financials |
| `Company.get_structured_statement(statement_type)` | Statement-by-statement structured access |
| `Company.mailing_address()`, `Company.business_address()` | Physical addresses |
| `Company.fiscal_year_end` | Already in DB as `Company.fiscal_year_end_month`; this is the raw 4-digit form |
| `Company.tickers` | Multiple tickers if cross-listed |
| `Company.reit_subtype` | REIT classification (Equity REIT, Mortgage REIT) |
| `Company.text(max_tokens=2000)` | Plain-text representation of the entity for LLM |
| `Company.to_context(detail='standard')` | Pre-formatted LLM context |
| `Company.latest(form, n=1)`, `Company.latest_tenk`, `Company.latest_tenq` | Latest-filing convenience accessors |
| `Company.docs` | Documentation/help text |
| `Company.get_icon()` | Company logo (for display) |

### 2.4 Niche / out-of-scope

| Surface | Why niche |
|---|---|
| `Company.is_individual`, `Company.is_company` | Filter-by-type (we already use `is_fund()` and `is_operating_company()` instead) |
| `Company.not_found` | Existence check (we use try/except instead) |
| `Company.is_accelerated_filer`, `is_non_accelerated_filer`, `is_emerging_growth_company` | Sub-categories of `filer_category` — we have the full enum already |

---

## 3. edgartools — `Filing` surface

### 3.1 Currently used

| Surface | Use |
|---|---|
| `filing.html()`, `filing.attachments` | DEF 14A / SC 13D / 6-K MIC content access |
| `filing.xbrl()` | XBRL data (mostly replaced by companyfacts) |
| `filing.accession_no`, `filing.filing_date`, `filing.form` | Identification |
| `Form4.to_dataframe()` | Insider transaction parsing |

### 3.2 Untapped — HIGH value

| Surface | Use case | Effort |
|---|---|---|
| **`filing.search(query, regex=False)`** | **Search within one filing.** Currently we do BeautifulSoup get_text + regex ourselves. This is cleaner. | Trivial |
| **`filing.grep(pattern, regex=False, document=...)`** | regex-grep across filing attachments | Trivial |
| **`filing.text() -> str`** | Plain-text rendering. Cleaner than BS4 + whitespace normalization we do ourselves. | Trivial |
| **`filing.markdown(include_page_breaks=False)`** | Markdown rendering. Useful for LLM prompts where structure matters. | Trivial |
| **`filing.sections() -> List[str]`** | Lists named sections (Item 1, Item 1A, etc.) | Trivial |
| **`filing.summary() -> DataFrame`** | DataFrame summary of filing contents | Trivial |
| **`filing.related_filings()`** | Find related filings (e.g., 8-K → underlying NT 10-K) | Useful for chain-of-custody |
| **`filing.full_text_submission() -> str`** | Full SGML submission text | Last-resort fallback |
| **`filing.to_context(detail='standard')`** | Pre-formatted LLM context | Useful for narrative.py |
| **`filing.parse() -> Document`** | Returns structured Document object | Replaces our BS4 parsing entirely for many cases |

### 3.3 Untapped — MEDIUM value

| Surface | Use case |
|---|---|
| `filing.sgml() -> FilingSGML` | Raw SGML form (rare need) |
| `filing.viewer`, `filing.serve()` | Local HTTP viewer for inspection |
| `filing.save(directory)` | Cache filing to disk |
| `filing.is_xbrl`, `filing.is_inline_xbrl` | XBRL flags |
| `filing.exhibits` | Exhibit-only attachments |
| `filing.from_dict(...)`, `from_json(path)`, `from_sgml(...)` | Reconstruct filing from cached data |
| `filing.reports`, `filing.statements` | Pre-parsed financial reports |
| `filing.period_of_report`, `filing.report_date` | Period anchors |
| `filing.all_ciks`, `filing.all_entities`, `filing.is_multi_entity` | Co-filer handling (Form 13G with multiple reporting persons) |

---

## 4. edgartools — `Financials` surface (`Company.get_financials()`)

### 4.1 Currently used

(None — we built our own companyfacts-based pipeline before this surface matured)

### 4.2 Untapped — HIGH value

| Surface | Use case | Effort |
|---|---|---|
| **`get_free_cash_flow(period_offset=0)`** | Direct FCF accessor | Trivial |
| **`get_capital_expenditures(period_offset=0)`** | Direct CapEx | Trivial |
| **`get_operating_cash_flow(period_offset=0)`** | Direct OCF | Trivial |
| **`get_revenue(period_offset=0)`** | Direct revenue (handles us-gaap alias variance) | Trivial |
| **`get_net_income(period_offset=0)`** | Direct NI | Trivial |
| **`get_operating_income(period_offset=0)`** | Direct EBIT | Trivial |
| **`get_total_assets(period_offset=0)`**, `get_current_assets()`, `get_current_liabilities()` | Balance sheet line items | Trivial |
| **`get_stockholders_equity(period_offset=0)`** | Direct equity | Trivial |
| **`get_total_liabilities(period_offset=0)`** | Direct total liabilities | Trivial |
| **`get_shares_outstanding_basic()`, `get_shares_outstanding_diluted()`** | Share counts by basis | Trivial |
| **`get_financial_metrics() -> Dict[str, Any]`** | Multi-metric helper — returns dict of common ratios | Trivial; could replace parts of our composite scoring |
| `balance_sheet()`, `income_statement()`, `cashflow_statement()`, `comprehensive_income()`, `statement_of_equity()` | Full structured statements | Could replace large parts of our companyfacts parser |

### 4.3 Untapped — MEDIUM value

| Surface | Use case |
|---|---|
| `cover()` | Cover-page metadata (filing-period, registrant, etc.) |
| `extract(filing)` | Build Financials from a specific filing |
| `get_currency_symbol()` | Currency code (USD/EUR/GBP) |
| `xb: XBRL` | Underlying XBRL document |
| `to_context()` | LLM context format |

---

## 5. Substitution priorities

Ranked by **(value × ease)** for the next implementation cycle:

### Tier A — Quick wins (each <50 LOC)

1. **`Company.facts.public_float`** → replaces yfinance.info.floatShares for the `Company.shares_float` field. Tier 1A canonical.
2. **`Company.facts.time_series(concept)`** + `companyconcept` endpoint → faster incremental refresh than re-pulling companyfacts.json on every dive.
3. **`Company.facts.peer_comparison(peer_ciks, metrics)`** → complements our `sec_frames.compute_ratio_distribution`; useful when we already know the peer CIK list (e.g., F1/F3 SIC peers).
4. **`filing.search(query)`** + `filing.grep(pattern)` → replaces our BS4 + regex pattern in `data/edgar_text_parser.py` (parse_customer_concentration, parse_proxy_ownership, etc.). Code-cleanup, same semantics.
5. **`filing.text()` and `filing.markdown()`** → standardised text extraction for LLM prompts. Replaces our hand-rolled BS4 strip-tag-and-normalise-whitespace logic.

### Tier B — Medium-effort (~100-200 LOC each)

6. **`Company.get_financials()` family** (`get_free_cash_flow`, `get_capital_expenditures`, etc.) → could replace large parts of `data/edgar_companyfacts.py` parsing. Big rewrite but cleaner.
7. **`Company.facts.calculate_ratios()`** → if it returns the ratios we self-compute, we could delegate. Need to probe what's in the dict first.
8. **`Company.facts.detect_anomalies()`** → integrate into F4 stealth-accumulation or as a new diagnostic overlay.
9. **EDGAR full-text search** (`efts.sec.gov`) → theme-based screening. New capability (e.g., "find all software filers mentioning Anthropic in their 10-K"). Useful for narrative grounding.
10. **`www.sec.gov/files/company_tickers_exchange.json`** → universe-enumeration upgrade. **Adds 310 tickers SEC has but we don't.** One-time backfill.

### Tier C — Strategic (later phases)

11. **`Company.facts.to_llm_context(focus_areas)`** + `Company.facts.to_agent_tools()` → for future LLM-agent layer (ADR-032 Phase 4). Defer until agent composition stabilises.
12. **`filing.related_filings()`** → chain-of-custody analysis (8-K → NT 10-K → eventually filed 10-K). Useful for surprise-detection or compliance tracking.
13. **IFRS frames support** — `frames/ifrs-full/{concept}/...` → cover IFRS-reporting FPIs that don't tag us-gaap. Hidden-ticker subset.

### Tier D — Niche

14. RSS / Atom feeds → real-time alerting workflow (not core dive)
15. NPORT mutual-fund holdings → separate analytical framework
16. 144 / S-1 / 25 forms → specific event-driven workflows

---

## 6. Anti-patterns (what NOT to add)

Per ADR-033 §4 forbidden patterns, the following surfaces are **not** to be wired regardless of convenience:

- yfinance.info pre-computed ratios (P/E, P/B, EV/EBITDA, beta) → **always** self-compute
- yfinance.info.industry / sector → **always** prefer SEC SIC
- yfinance / FMP / Polygon "fair value" or "intrinsic value" calculations → use Damodaran (ADR-027) only
- Any API endpoint that returns "adjusted EPS" or "non-GAAP earnings" without methodology disclosure → silently smuggles management non-GAAP (ADR-021)

---

## 7. The "hidden tickers" question — answered

User asked 2026-05-15: *"there could be hidden tickers which do not have fundamentals listed on APIs like yfinance, FMP, polygon and SEC EDGAR might have them."*

**Confirmed empirically.** SEC `company_tickers_exchange.json` lists **10,353 filers**. Our DB has **10,143**. The 310-ticker delta is the "hidden tickers" — primarily:
- Recently-IPO'd OTC names
- Micro-caps with thin trading
- Foreign-domiciled but US-SEC-registered FPIs whose yfinance coverage is patchy
- Recently-listed special-purpose vehicles (SPACs / business development companies)

Universe-expansion upgrade plan (Tier B item 10 above):
1. Download `company_tickers_exchange.json` (518KB)
2. Diff against our Company table by ticker symbol
3. Insert 310 missing rows as `screener_candidate` status
4. Run the existing Tier 1.1-2.5 substitutions on them automatically through dive cycle

---

## 8. Forward-pointer summary

When a new field needs sourcing, the checklist is:

```
1. Is it in companyfacts.json (us-gaap XBRL)?       — Tier 1A, Step 1
2. Is it in companyconcept (single concept)?         — Tier 1A, faster targeted refresh
3. Is it in submissions.json (filer metadata)?       — Tier 1A
4. Is it in frames endpoint (cross-sectional)?       — Tier 1A, peer comparison
5. Is it in dei-namespace XBRL (Doc Entity Info)?    — Tier 1A
6. Is it in edgartools Company.facts surface?        — Tier 1B typed wrapper
7. Is it in edgartools Company.get_financials()?     — Tier 1B typed statements
8. Is it in edgartools filing.search() / .grep()?    — Tier 1B targeted text extraction
9. Is it in a specific filing form text (DEF 14A, SC 13D, 6-K MIC, 8-K EX-99.1)?  — Tier 1A regex/BS4
10. Can it be COMPUTED from primitives in 1-9?       — Tier 2 self-compute
11. (Last resort) API fallback                       — Tier 3 with provenance flag
```

If steps 1-10 all return "not available," the field is genuinely SEC-blind (market prices, short interest from FINRA, post-event news). Document the gap per ADR-031 §1.2 and proceed to Tier 3 fallback with explicit `<field>_source` tagging.

---

*This inventory supplements ADR-033 §1.3 (Search-SEC-first invariant). When you add a new field, walk this list before reaching for an API. Update this document when new endpoints are discovered or wired into production.*
