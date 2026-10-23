# Data Layer Contract

This is the **architectural contract** for the lab's data layer. It is locked
unless explicitly superseded in `DECISIONS.md`.

## 1. Determinism rule

**The data path is fully deterministic. Zero LLM calls.** AI usage is
restricted to `deepdive/narrative.py` (Phase 6, sole permitted Anthropic call
site). Any code path that imports `anthropic` or `openai` outside that file
is a bug.

Missing values surface as `data_gaps[]` strings. We never invent numbers.
This rule is enforced by reviewing diffs — there is no runtime guard.

## 2. Schema invariants

### Financial table

Keyed by `(company_id, fiscal_year, period)` where `period ∈ {annual, Q1, Q2, Q3, Q4}`.
Restatements (10-K/A) overwrite the existing row. The `extraction_confidence`
column records source quality: `1.0` = XBRL/HTML verbatim, `0.6` = regex, `0.0` = missing.

### FinancialSourceLog

Tier-0 cache. One row per parsed accession number. Phase A's companyfacts
parser reads this set on entry and skips facts whose `accn` is in it. Never
mutated post-write.

### Insider, holder, short-interest, analyst tables

Snapshot-style: each row carries a date stamp. Time series accumulate via
the monthly scheduler job. Never deleted; old rows are how we compute trends.

## 3. companyfacts parser (`data/edgar_companyfacts.py`)

Materializes one `EdgarFinancialRow` per `(fiscal_year, period)` from SEC's
bulk endpoint. Four invariants (verified on synthetic fixtures, see Phase 2
session log):

1. **Form whitelist**: only `10-K, 10-K/A, 10-Q, 10-Q/A, 20-F, 20-F/A, 40-F, 40-F/A`.
2. **Restatement**: for each `(fy, fp)`, the bucket whose accn has the latest `filed` date wins.
3. **Span resolution**: for flow concepts (Revenues, NetIncome) where SEC
   reports both YTD-cumulative AND just-the-period values, the parser picks
   the entry with the shortest `start → end` span.
4. **Unit selection**: explicit per-concept (`USD` for monetary, `shares` for
   share counts, `USD/shares` for per-share).

## 4. Three-tier lazy load (EDGAR fundamentals)

```
Tier 0   FinancialSourceLog        DB read, 0 network
         skip already-parsed accessions

Tier 1   submissions.json          ~50KB GET
         probe whether a new 10-K has filed since last refresh

Tier 2   companyfacts.json          ~5MB GET, cached 24h
         single bulk fetch; parser keeps only missing fiscal years
         via `keep_only_years` filter
```

Decision flow in `_decide_companyfacts_fetch()`:
- `force_refresh` → fetch full window
- cold cache → fetch full window
- partial gap → fetch with `keep_only_years={missing FYs}`
- full coverage + new filing → fetch with `keep_only_years=None` (parser
  uses skip_accessions to write only the new accession)
- full coverage + no new filing → SKIP companyfacts entirely

## 5. Framework-aware lazy load

Each framework declares `DATA_REQUIREMENT = DataRequirement(...)`. The
orchestrator unions requirements across selected frameworks via
`merge_requirements()`. The pipeline gates each fetch step:

| requirement field | gates |
|---|---|
| `annual_years > 0` | EDGAR companyfacts fetch (also bounds the year window) |
| `quarterly_count > 0` | quarter materialization (max(N, 8)) |
| `price_history_years > 0` | yfinance `.history()` download |
| `needs_insider_transactions` | EDGAR Form 4 fetch |
| `needs_proxy_ownership` | DEF 14A HTML fetch + table parse |
| `needs_customer_concentration` | 10-K XBRL + text regex |
| `needs_founder_status` | 10-K + DEF 14A founder regex |

yfinance `.info` always fetches (single small call, populates company
profile, valuation snapshot, analyst count).

## 6. Read API (`data/reader.py`)

Frameworks consume `CompanyDataReader(ticker)`. They never:
- import schema directly,
- query SQLAlchemy directly,
- open `get_session()`.

Reader methods return typed lists, most-recent-first, or `None`. Empty result
is empty list, never an exception.

## 7. Recent-IPO graceful degradation

`_check_feasibility(ticker, framework_names)` walks `reader.annual_year_set()`
BEFORE invoking any score function. Frameworks whose `DATA_REQUIREMENT`
exceeds what the DB holds get marked unfeasible with reason — they don't
get invoked at all.

Score functions still raise `InsufficientHistoryError` for finer-grained
gaps (e.g. F4 needs 4Q EPS but we have 3); orchestrator catches and surfaces
this too.

The dive NEVER crashes on an unsuitable framework. Output shows:
- `framework_results: {F1: ...result..., F2: ...}`
- `framework_unfeasible: {F7: "recent IPO / insufficient annual history (needs 10yr, have 1)"}`

## 8. Performance characteristics (single ticker)

| Phase | Cold cache | Warm cache (no new filings) |
|---|---|---|
| companyfacts fetch | 1 HTTP, ~5MB | skipped via Tier-0 + submissions probe |
| Form 4 | 1 listing + parse | 1 listing + parse |
| yfinance `.info` | 1 HTTP, small | 1 HTTP, small (TTL cache 6h) |
| yfinance `.history()` | 1 HTTP, small | 1 HTTP, small (gated by req) |
| DEF 14A | 1 listing + HTML download | 1 listing (gated) |
| **Total** | **~5-15s** | **~2-5s** |

## 9. What NOT to add

- No Alpha Vantage. FMP is screener metadata only (ADR-016); Polygon is an opt-in plugin (ADR-019)
- No LLM in the data path — restricted to `deepdive/narrative.py`
- No new tables without a migration — schema is in `data/models/schema.py`
- No N+1 queries — bulk persistence pattern is mandatory (one SELECT for
  dedup keys, then `session.add_all`)
- No raw dict passing between modules — Pydantic v2 / dataclasses only

## 10. SEC `frames.json` — period bucketing rules (Phase 3c)

The `frames.json` endpoint at
`https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json`
returns ONE concept across ALL filers for a given period. We use it for the
Tier 4 universe-wide fundamentals filter (~30 calls cover the screener).

### Period naming
- `CYxxxx`        — duration concept, full calendar year
- `CYxxxxQn`      — duration concept, calendar quarter (3 months)
- `CYxxxxQnI`     — instantaneous (point-in-time, suffix `I`)

### Off-fiscal-year companies — empirical findings

Status: **TO BE VALIDATED EMPIRICALLY**. Run:
```bash
python -m data.edgar_frames_validation NVDA AAPL COST
```
once the env permits and APPEND findings here. The validator fetches each
ticker's latest 3 annual revenues via both companyfacts AND frames, prints
which `CY{year}` window each appears in, and flags divergence.

**Working hypothesis** (verified on SEC docs but not on live data yet):
- A company's value appears under `CY{year}` whose calendar period CONTAINS
  the value's `end` date.
- NVDA FY2024 ended ~Jan 28, 2024 → revenue appears in **`CY2024`** (end is in
  Jan 2024 = calendar Q1 2024 = part of CY2024). Confirm.
- AAPL FY2024 ended ~Sep 28, 2024 → revenue appears in **`CY2024`** (end is
  in calendar Q3 2024). Confirm.
- COST FY2024 ended early Sep 2024 → **`CY2024`**. Confirm.

If the hypothesis holds, our Tier 4 logic (always query the most recent
complete calendar year) captures every filer regardless of fiscal-year-end.
Each `FrameEntry.end` carries the canonical date so downstream ranking can
disambiguate.

### Loose-cut policy at Tier 4

Tier 4 only DROPS a candidate when an explicit value FAILS a threshold. Missing
fields are OK at Tier 4 (Tier 5 will fetch full companyfacts and refine).
The two exceptions: `revenue` and `assets` — without these we can't even rank,
so missing == fail.

### Cache key

`frames:{concept}:{period}:{unit}` in the SQLite TTL cache, default 24h.
Frames data only changes when new filings land, so daily refresh is safe.

### Empirical findings log (append per validation run)

(none yet — fill in after first live `python -m data.edgar_frames_validation NVDA AAPL COST`)
