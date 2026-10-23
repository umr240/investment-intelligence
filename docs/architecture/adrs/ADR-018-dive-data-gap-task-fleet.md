# ADR-018 — Dive-data gaps: per-gap deterministic task fleet

| Field          | Detail                                                          |
|----------------|-----------------------------------------------------------------|
| **Status**     | **Accepted** (2026-05-17) — per-gap deterministic tasks shipped in `data/pipeline.py` + `data/edgar_fetcher.py` + `data/edgar_text_parser.py`; CLAUDE.md "AI layer boundary" preserved (zero LLM in gap-fill path) |
| **Date**       | 2026-05-05                                                      |
| **Extends**    | ADR-017 (warehouse + task pattern) to the dive-data layer.      |
| **Preserves**  | CLAUDE.md "AI layer boundary" (every gap-fill is deterministic — zero LLM). |
| **Provenance** | Triggered by user observation that dive(INTA) and dive(NVDA) both surface 4 identical "data fetch notes" (CEO name, Form 4, customer concentration, CEO equity). User directive: research before proposing; document gaps as ADR; no over-engineering; accuracy > speed. |

---

## 0. Operating principle for this ADR

> "Don't think of a solution unless you exactly know the solution."
> — User, 2026-05-05

Every numbered claim in §2-§5 is backed by an empirical probe in this
codebase against INTA + a control ticker (NVDA). Where I can't ground a
claim, the section is labelled **"Open question — needs validation"**
rather than wishful design. Where two endpoints could plausibly fill a
gap, I list both with the probe results and pick on accuracy first.

This doc is **research output and design proposal**, not an
implementation. No code is written by ADR-018. Implementation is
gated on user approval per gap.

---

## 1. The four gaps observed today

After the period_end-authoritative parser refactor (ADR pending — see
2026-05-05 commit), the INTA dive surfaces these four notes verbatim:

```
· INTA: yfinance CEO name not found in companyOfficers
· INTA: no Form 4 insider transactions found on EDGAR
· INTA: customer_concentration_pct — no XBRL or regex match in 10-K
· INTA: ceo_equity_pct — no DEF 14A HTML ownership table match
```

NVDA's dive surfaces the **identical four notes**. That uniformity is
the diagnostic clue: these are not ticker-specific data absences, they
are systemic parser bugs and missing source-of-truth wiring. None of
them are "INTA is small, has no data" — every gap has structured public
data behind it that the current pipeline isn't reaching.

In addition, an empty-by-default earnings_history table affects every
dive (F2 PEAD, F4 EPS-acceleration both depend on it).

---

## 2. Gap-by-gap research

### 2.1 Gap A: `Company.ceo_name` — yfinance officers row not matched

**Symptom**: `info.ceo_name = None` for both INTA and NVDA.

**Root cause** (verified by probing `yf.Ticker(t).info["companyOfficers"]`
in this session):

| Ticker | First officer's title | Current matcher result |
|---|---|---|
| NVDA | `"Co-Founder, CEO & Director"` | NO MATCH |
| INTA | `"Chairman & CEO"` | NO MATCH |

Current matcher (`data/api/yfinance_client.py:_parse_info`):
```python
for officer in raw.get("companyOfficers", []):
    title = (officer.get("title") or "").lower()
    if "chief executive" in title or title.strip() == "ceo":
        ...
```

The bug: titles use the abbreviation **"CEO"** as a comma- or
ampersand-separated token, never the full string `"chief executive"`.
And `title.strip() == "ceo"` requires the WHOLE title to be the string
`"ceo"` — never true when it's combined with "Chairman", "Co-Founder",
"& Director", etc.

**Solution (known)**: tokenise the title on `, & /` plus whitespace and
look for any token equal to `"ceo"`, OR substring `"chief executive
officer"` (3-word phrase) OR substring `"chief executive"` (legacy).
This is a 5-line fix to `_parse_info`, no new endpoint required.

**Fallback chain** (when the tokenised match still fails — e.g. the
officer order is wrong, the title is non-standard, or yfinance returns
empty `companyOfficers`):

| Source | What it returns | Probe result |
|---|---|---|
| **edgartools** `Company.proxy_season(0).proxy.peo_name` | "Principal Executive Officer" name from DEF 14A XBRL | INTA: `"Mr.\xa0Hall"` (non-breaking space, last name only — needs cross-reference) |
| **edgartools** `Company.proxy_season(0).proxy.beneficial_ownership` | DataFrame: `holder_name | holder_type | shares | percent_of_class` | INTA returned 16 rows, John Hall present as "5pct_holder" with 7.64% |

Cross-referencing PEO surname → beneficial_ownership.holder_name
resolves both the full name and the equity %. This single edgartools
call covers both Gap A AND Gap D below. **The DEF 14A XBRL beneficial
ownership table is structured data we are currently NOT touching.**

**Confidence**: known solution.

**Three-state output** (per user's directive):
- `disclosed_exact` — yfinance officers tokeniser found CEO row, OR DEF
  14A `peo_name` matched a `beneficial_ownership` holder
- `parser_uncertain` — name string from one source doesn't match any
  row in the other source within a fuzzy threshold
- `not_disclosed` — both endpoints empty (extremely rare for SEC
  filers; would indicate the company is in a non-CEO governance form
  like LLC manager/general partner)

---

### 2.2 Gap B: Form 4 insider transactions — silent parser failure

**Symptom**: dive note "no Form 4 insider transactions found on EDGAR"
for INTA. But the DB also shows 135–150 yfinance-sourced insider rows,
and edgartools sees 20+ Form 4 filings (verified: `Company('INTA')
.get_filings(form='4').head(20)` returned filings dated 2026-02-20 with
real accession numbers).

**Root cause** (verified by probing `edgartools.Form4` object surface):

Current `_parse_form4` (`data/edgar_fetcher.py:457`) reads:
```python
transactions = (
    getattr(form4, "transactions", None)
    or getattr(form4, "non_derivative_transactions", None)
    or []
)
```

But edgartools' actual `Form4` attributes are:
```
common_stock_purchases   common_stock_sales       derivative_table
derivative_trades        non_derivative_table     market_trades
get_transaction_activities  to_dataframe         option_exercises
```

There is no `transactions` attribute and no `non_derivative_transactions`
attribute. **Our parser is silently looking up names that no longer
exist; it always falls through to `[]`.** The "no Form 4 found" note is
a lie — Form 4s are found; we just can't read them with our outdated
attribute names.

**Solution (known)**: replace the silent `getattr` chain with explicit
calls to `form4.to_dataframe()` (returns a structured DataFrame of
transactions) or `form4.get_transaction_activities()`.

`form4.to_dataframe()` columns to be confirmed in the implementation
PR — **this is the single API call I have not yet probed in detail**;
see Open question §6.1.

**Why we're not blocked today**: yfinance's `insider_transactions`
DataFrame (probed: 150 rows for INTA with `Insider | Position |
Transaction | Start Date | Ownership | Value`) DOES land in our
`insider_transactions` table via the existing yfinance fallback. So
the *gap* in the dive note is misleading: we have insider data, we
just don't have it from EDGAR.

**The signal we lose by relying solely on yfinance**: yfinance's
`Transaction` codes are non-standard ("Stock Award", "Sale", etc.),
not the SEC Form-4 transaction codes (P/S/A/M/F/G/D). F1's "cluster
buy" signal needs the **`P` (open-market purchase)** vs `M` (option
exercise) distinction — that's the strongest insider-buying signal in
the academic literature (Cohen-Malloy-Pomorski 2012). yfinance does
not preserve this distinction reliably.

So the fix for Gap B has two layers:
1. **Repair Form 4 parsing** with current edgartools attributes →
   restores Form 4 P/S/A code resolution
2. **Surface yfinance's `insider_purchases`** (probed: returns
   aggregated 6-month totals: net shares purchased, % buy, % sell, with
   47 purchases / 13 sales for INTA) as a secondary signal

**Confidence**: solution direction known; exact attribute names need
the probe at implementation time.

**Three-state output**:
- `disclosed_exact` — Form 4 parsed via `to_dataframe()` with txn_code in {P,S,A,M,F,G,D}
- `parser_uncertain` — Form 4 found but `to_dataframe()` raises or
  returns empty when filings are visible (edgartools format change)
- `not_disclosed` — no Form 4 filings exist for the ticker (rare for
  US issuers; common for foreign-private-issuer 6-K filers)

---

### 2.3 Gap C: Customer concentration — XBRL miss + regex miss + state confusion

**Symptom**: `customer_concentration_pct = None` for INTA.

**Root cause analysis** (verified by reading INTA's 10-K in this session):

I pulled INTA's `TenK.business` (45,150 chars) + `TenK.risk_factors`
(138,284 chars) and grepped for every plausible concentration phrase:
- `"customer concentration"` — 0 matches
- `"no single customer"` — 0 matches
- `"no customer accounted for"` — 0 matches
- `"largest customer"` — 0 matches
- `"10% of revenue"` — 0 matches
- `"single customer"` — 0 matches
- `"major customer"` — 0 matches

**INTA genuinely does not disclose customer concentration.** It serves
thousands of professional-services firms; no single customer crosses
the 10% materiality threshold that triggers SEC's mandatory disclosure
requirement (Reg S-K Item 101(c) / 10% rule). The absence of language
isn't a parser miss — it's a **business signal** ("no concentration
risk").

This perfectly illustrates the user's three-state model:

| Today's signal | Should be |
|---|---|
| "no XBRL or regex match" → treated as gap | `not_disclosed` (a positive signal — diversified customer base) |
| "regex matched 47%" | `disclosed_exact` |
| "regex matched a number that might or might not be customer-related" | `parser_uncertain` |

**Hardening for the `disclosed_exact` path** (when concentration IS
disclosed — e.g. AAPL with one >10% reseller, or NVDA with one big
hyperscaler customer):

| Source | Endpoint | Probe verdict |
|---|---|---|
| **SEC XBRL** | `us-gaap:ConcentrationRiskPercentage1` (and `…Percentage`) | already coded; works when company tags it. Many tag it; many don't. |
| **SEC frames** | `frames/us-gaap/ConcentrationRiskPercentage1/USD/CY2024Q4I.json` | universe-wide bulk fetch; one HTTP call returns every filer who tagged the concept. ~40-100 KB. |
| **edgartools 10-K** | `TenK.business` (45 KB) + `TenK.risk_factors` (138 KB) — narrowly-scoped subsections, no need to grep the full filing | confirmed: 1 call returns parsed strings |
| **Targeted-section regex** | Run existing `parse_customer_concentration` on the **business** + **risk_factors** strings only, not the whole filing | reduces false-positive surface (no proxy-statement noise) |
| **Wording expansions** | Add patterns: `"approximately X% of [our|total] [revenue\|net revenue\|sales\|billings]"`, `"largest customer accounted for X%"`, `"top X customers represented Y%"` (multi-customer concentration) | known-good wording from large-cap 10-Ks |

**FMP free-tier fallback**: `/v4/revenue-product-segmentation` and
`/v4/revenue-geographic-segmentation` are the closest FMP endpoints,
but they segment by product/region — neither exposes `customer name →
% of revenue`. **FMP free tier does not have a customer-concentration
endpoint.** This gap stays SEC-only.

**Confidence**:
- Three-state model: known design.
- Targeted-section regex: known solution (we have the section accessor).
- XBRL frame bulk-fetch: known solution; useful for screener Tier 4
  but not for dive (one-off).
- Wording-pattern expansion: needs an empirical validation set
  (5-10 known-disclosure 10-Ks). **Open question §6.2.**

**Three-state output**:
- `disclosed_exact` — XBRL tag fired OR targeted regex matched in
  business/risk_factors with a customer-attributed numeric near the %
- `parser_uncertain` — numeric % found in concentration-adjacent text
  but couldn't be reliably attributed to a customer (ambiguous —
  could be vendor concentration, geographic concentration, etc.)
- `not_disclosed` — neither XBRL nor regex fired AND known
  concentration-adjacent phrasing absent (this is the INTA case;
  store the absence as a positive signal)

---

### 2.4 Gap D: CEO equity % — covered by edgartools beneficial_ownership

**Symptom**: `ceo_equity_pct = None` for INTA.

**Root cause** (verified by probing `Company.proxy_season(0).proxy
.beneficial_ownership`):

INTA's DEF 14A's beneficial-ownership table is **fully structured XBRL**
in edgartools' parser:

```
   holder_name              holder_type       shares  percent_of_class
0  John Hall                5pct_holder    6,303,086              7.64
1  David Morton           director_officer    52,850              0.50
2  Don Coleman            director_officer 1,265,217              1.54
3  Thad Jampol            director_officer 1,143,212              1.39
...
```

`John Hall` (CEO) has **7.64% of class** — well above the threshold
that would trigger F6 founder-CEO scoring. Our current DEF 14A HTML
parser is regex-on-soup; edgartools delivers it as a typed DataFrame.

**Solution (known)**: replace the BeautifulSoup table parser with
edgartools' `proxy.beneficial_ownership` DataFrame access. Cross-
reference `peo_name` (last name) against `holder_name` to identify the
CEO row. Read `percent_of_class`. Done.

**Multi-class share consideration** (user-flagged in directive): for
companies with dual-class structures (Class A vs Class B), the
ownership table reports per-class percentages. The relevant signal for
F6 is **voting power %**, not nominal-class %. edgartools currently
reports `percent_of_class` only; voting-power computation requires
knowing the class share count and voting ratio (1:1, 1:10, etc.) from
the 10-K's "Description of Capital Stock" section.

**Open question §6.3** — for INTA (single class) this is moot. For
NVDA (single class) also moot. For META, GOOGL, BRK, SNAP — multi-
class. We need to decide whether voting-power computation is in scope
for v1 or deferred. Recommendation: **start with `percent_of_class`
and flag dual-class companies as `parser_uncertain` until the voting-
power piece lands.**

**Confidence**: solution known for single-class issuers (the majority).
Multi-class is the open question.

**Three-state output**:
- `disclosed_exact` — single-class, peo_name matched, percent_of_class read
- `parser_uncertain` — multi-class issuer (until voting-power logic
  added), OR peo_name didn't match any holder_name within fuzzy
  threshold, OR ownership table format edgartools couldn't parse
- `not_disclosed` — DEF 14A doesn't include a beneficial ownership
  table (extremely rare; would be a procedural anomaly)

---

### 2.5 Gap E (newly discovered): `earnings_history` table is empty

**Symptom**: `select count(*) from earnings_history where company_id =
INTA` returns 0. Also true for NVDA. The `_persist_yfinance_snapshot`
path doesn't populate this table at all today.

**Source** (probed): `yf.Ticker('INTA').earnings_dates` returns a
DataFrame indexed by report timestamp with columns `EPS Estimate`,
`Reported EPS`, `Surprise(%)`. INTA returned 20 quarters, latest 8:

```
Earnings Date                EPS Estimate  Reported EPS  Surprise(%)
2026-05-05 16:00:00-04:00          0.28           NaN          NaN
2026-02-03 16:00:00-05:00         -0.08         -0.07        10.01
2025-11-04 16:00:00-05:00         -0.11         -0.18       -67.80
2025-08-12 16:00:00-04:00          0.23          0.27        17.93
2025-05-06 16:00:00-04:00         -0.07         -0.04        38.68
2025-02-04 16:00:00-05:00          0.16          0.21        28.52
2024-11-04 16:00:00-05:00          0.13          0.21        61.77
2024-08-13 16:00:00-04:00          0.12          0.15        20.51
```

**This is exactly the `event_date` + `event_time` data the user
specified** in the previous turn ("Earnings date: May 7, 2026 - AMC")
— 16:00:00 timestamps confirm AMC; 09:00:00 timestamps would mean BMO.

**Solution (known)**: write `_persist_earnings_history` from the
yfinance snapshot. Map: `Earnings Date → event_date + event_time`,
`EPS Estimate → eps_estimate`, `Reported EPS → eps_actual`,
`Surprise(%) → eps_surprise_pct`. Same source for revenue surprise
exists at `yf.Ticker(t).calendar` (next quarter only) and could be
backfilled from `quarterly_income_stmt` for prior quarters.

**Confidence**: known solution.

**Adjacent newly-available data** (probed but not yet wired):

| yfinance attribute | Shape | Use case |
|---|---|---|
| `recommendations` | (2, 6) by period: strongBuy/buy/hold/sell/strongSell counts | F1 neglect signal more granularly than `analyst_count` |
| `upgrades_downgrades` | (106, 7) firm + ToGrade + FromGrade + Action + price targets | F4 catalyst detection |
| `analyst_price_targets` | dict: current/high/low/mean/median | already partially captured |
| `earnings_estimate` | (4, 7) forward 4 quarters consensus avg/low/high/numAnalysts/growth | F2 forward-looking expectation |
| `revenue_estimate` | (4, 7) same shape, revenue side | F2/F3 |
| `eps_trend` | (4, 6) consensus 7d/30d/60d/90d ago | F4 estimate revision velocity |
| `eps_revisions` | (4, 5) up/down counts in 7d/30d windows | F4 revision sentiment |
| `mutualfund_holders` | (10, 6) date/holder/pct/shares/value/pctChange | F4 institutional flow |
| `sec_filings` | list of 49 with date/type/edgarUrl | cross-validate FinancialSourceLog |

**These are not gaps in the strict sense** — they're adjacent
endpoints that aren't currently exploited. ADR-018 captures them in
§5 ("future task slots") rather than promising them in v1.

---

## 3. Pattern: each gap = one task, applied per ADR-017

ADR-017's task pattern was designed for the **screener** path (universe
→ warehouse columns). The same pattern applies cleanly to the **dive**
path: each gap-column on `Company` or per-row column on `Financial`,
`InsiderTransactionRecord`, `EarningsHistory` becomes its own task with
its own cadence, retries, and fallback chain.

The dive-side properties differ from the screener side:

| Dimension | Screener tasks (ADR-017) | Dive tasks (ADR-018) |
|---|---|---|
| Universe | 5,000-10,000 tickers | 1 ticker per dive |
| Trigger | scheduled cron | user-initiated (`invest dive TICKER`) |
| Latency budget | quarterly batch (minutes OK) | interactive (~30 sec target) |
| Failure mode | per-chunk retry, others advance | per-task retry, dive completes regardless |
| Source priority | reliability > coverage > speed | accuracy > coverage > speed |

The user's directive — **accuracy is #1, speed is #2** — maps directly
onto the priority chain in each task:

```python
class DiveTask(Protocol):
    name: str
    columns_written: list[str]            # which DB columns this task fills
    refresh_interval: timedelta
    state_column: str                     # the *_state column with the 3-state value

    # Source chain in PRIORITY ORDER. Each task tries them in turn until one
    # produces `disclosed_exact`. Falling through to a lower-priority source
    # is allowed; falling through to "no source available" produces
    # `not_disclosed` or `parser_uncertain` per the task's logic.
    sources: list[Source]                 # ['sec_xbrl', 'edgartools_structured', 'yfinance', 'fmp_fallback']

    def fetch_one(self, ticker: str, *, sec_bucket, yf_bucket, fmp_bucket
                 ) -> TaskResult:        # returns three-state value + provenance
        ...

    def persist(self, db, ticker: str, result: TaskResult) -> None:
        ...
```

The runner is the same ~50-LOC `run_task()` from ADR-017 §4 — no new
infrastructure. Per-task `concurrency_override = 1` for dive tasks
(they're already inside an interactive request).

---

## 4. Concrete tasks proposed (the gap → task fleet)

| # | Task | Writes columns | Source priority chain | Refresh interval | State column |
|---|---|---|---|---|---|
| **D1** | `CEONameTask` | `Company.ceo_name`, `ceo_name_state` | `(yf.officers tokeniser)` → `(edgartools.proxy.peo_name + beneficial_ownership cross-ref)` | 90 days | `ceo_name_state` |
| **D2** | `CEOEquityTask` | `Company.ceo_equity_pct`, `ceo_equity_pct_state` | `(edgartools.beneficial_ownership[holder=peo_name])` → `(yfinance heldPercentInsiders / officers count)` aggregate-only | 365 days | `ceo_equity_pct_state` |
| **D3** | `FounderStatusTask` | `Company.is_founder_ceo`, `is_founder_ceo_state` | `(yf.officers title contains 'co-founder')` → `(edgartools.TenK.business regex)` → `(proxy biographical regex)` | 180 days | `is_founder_ceo_state` |
| **D4** | `CustomerConcentrationTask` | `Financial.customer_concentration_pct`, `..._state` | `(SEC XBRL ConcentrationRiskPercentage1)` → `(edgartools.TenK.business + risk_factors regex with expanded patterns)` → `not_disclosed` | per 10-K | `customer_concentration_state` |
| **D5** | `Form4InsidersTask` | `InsiderTransactionRecord.*` | `(edgartools.Form4.to_dataframe())` → `(yfinance.insider_transactions)` | per Form 4 filing event | row-level: source column |
| **D6** | `EarningsHistoryTask` | `EarningsHistory.*` (rows) | `(yfinance.earnings_dates)` → `(yfinance.calendar for next-quarter forward)` | quarterly | row-level |
| **D7** | `IPODateTask` | `Company.ipo_date`, `ipo_date_state` | `(yf.firstTradeDateMilliseconds)` → `(yf.ipoExpectedDate)` → `(edgartools first-filing-date proxy)` | 365 days | already mostly working post-2026-05-05 fix |

**What's NOT proposed for v1** (deferred to keep scope tight):

- Multi-class voting-power calc (Open Q §6.3)
- FMP-backed fallback for any of D1-D6 (FMP free tier 250/day; needed
  only when SEC + yfinance both fail; see §6.4)
- Analyst-revision tasks (§2.5 adjacent surface — useful but no
  framework consumes them yet)
- Customer NRR / net revenue retention (10-K disclosure varies wildly;
  needs its own ADR)

**What's intentionally untouched**: the financial-statement parsing
(`edgar_companyfacts.py`) just got reworked for period_end-authoritative
labelling. ADR-018 doesn't touch that.

---

## 5. Schema changes (additive, per ADR-017 column-per-filter pattern)

```sql
-- One *_state per gap-column, three-state value as TEXT
-- ('disclosed_exact' | 'not_disclosed' | 'parser_uncertain' | NULL=not yet attempted)
ALTER TABLE companies ADD COLUMN ceo_name_state TEXT;
ALTER TABLE companies ADD COLUMN ceo_name_fetched_at TIMESTAMP;
ALTER TABLE companies ADD COLUMN ceo_equity_pct_state TEXT;
ALTER TABLE companies ADD COLUMN ceo_equity_pct_fetched_at TIMESTAMP;
ALTER TABLE companies ADD COLUMN is_founder_ceo_state TEXT;
ALTER TABLE companies ADD COLUMN is_founder_ceo_fetched_at TIMESTAMP;

ALTER TABLE financials ADD COLUMN customer_concentration_state TEXT;
ALTER TABLE financials ADD COLUMN customer_concentration_fetched_at TIMESTAMP;

-- task_failures table from ADR-017 §7 already covers per-task per-ticker failure.
-- No additional infra needed.
```

The state column makes the dive's "data fetch notes" output much
sharper:

| State | Dive note rendering |
|---|---|
| `disclosed_exact` | (silent — show the value) |
| `not_disclosed` | "INTA: customer concentration — none disclosed (no >10% customer)" |
| `parser_uncertain` | "INTA: customer concentration — possible match but ambiguous; manual review recommended" |
| NULL / absent | "INTA: customer concentration — not yet fetched" |

---

## 6. Open questions / what I do NOT know yet

The user's bar: "don't propose unless you exactly know". These are
the spots in the design where I do not know the exact shape and would
need a follow-up probe at implementation time.

### 6.1 `edgartools.Form4.to_dataframe()` column shape

I confirmed the method exists on the Form4 object surface but did not
call it on a real Form 4 in this session (would have required
downloading a specific Form 4 filing and inspecting). The columns
needed: insider_name, insider_title, transaction_date, transaction_code
(P/S/A/M/F/G/D), shares, price_per_share. **Implementation gate**: a
2-line probe at start of D5 implementation; if columns differ,
`get_transaction_activities()` is the alternate.

### 6.2 Customer-concentration wording validation set

For Gap C, I have not built a corpus of known-disclosure 10-Ks to
validate the expanded regex set. **Implementation gate**: pick 5
tickers known to disclose customer concentration (AAPL big-reseller
disclosure, NVDA's 2024 hyperscaler concentration disclosure, FAST
distributor concentration, etc.) and run the proposed regex set
against their `TenK.business + risk_factors`. Iterate patterns until
all 5 hit `disclosed_exact` AND INTA + a half-dozen no-concentration
controls hit `not_disclosed`.

### 6.3 Multi-class voting power computation

For Gap D in companies with dual-class structures, `percent_of_class`
under-counts CEO voting power. The 10-K "Description of Capital
Stock" section disclose the voting ratio (e.g. GOOGL: Class B = 10:1
voting). Parsing this requires either a structured XBRL tag (likely
none exists for voting ratios) or text regex on the Description of
Capital Stock section. **Recommendation**: defer to v2; flag dual-
class companies as `parser_uncertain` in v1. Identifying dual-class
is itself a probe: `len(set(beneficial_ownership.holder_type)) > 2`
or examining `Company.shares_outstanding` for class breakdown.

### 6.4 FMP free-tier fallback feasibility

The user mentioned FMP free tier as a fallback. I did NOT probe the
following endpoints because no FMP key is currently set on this
machine (and quarterly probing would consume the 250/day quota
unnecessarily):
- `/v3/profile/{ticker}` — has `ceoName`, `ipoDate`. Known coverage,
  but documented quota = 1 call per ticker.
- `/v4/insider-trading?symbol={ticker}` — Form 4-equivalent feed with
  transaction codes. Documented free tier coverage unknown.
- `/v3/key-executives/{ticker}` — full executive roster including
  founder flag. Documented free tier coverage unknown.

**Implementation gate for FMP**: when the FMP key is present in env,
run a one-off probe script (5 tickers × 3 endpoints = 15 calls of
quota) to confirm response shape and free-tier visibility, then wire
as the lowest-priority fallback in D1, D5, D7. Do NOT add FMP to D2
or D4 (FMP doesn't expose CEO equity % or customer concentration).

### 6.5 Rate-limit defaults across the dive

ADR-017 specified `SEC_BUCKET = 8.0/16` and `YF_BUCKET = 2.0/4` for
universe-scale screening. For a single-ticker dive, the relevant
question is: how many concurrent dive tasks should run? With 7 tasks
each doing ~1 SEC call + ~1 yfinance call, sequential is ~14 calls;
parallel-at-7 with shared buckets is ~5 sec wall-clock. **Open**:
should the dive runner serialise tasks (predictable) or run them in
parallel (faster but adds coordination)? Recommend **parallel with
asyncio.gather**, identical to current `refresh_ticker` Phase 1.

---

## 7. Implementation phasing (when approved)

The user's directive: don't overengineer. Each gap is independently
shippable. Recommended order, by accuracy impact:

| Phase | Gap | Effort estimate | Why first |
|---|---|---|---|
| 1 | **D1 + D2** (CEO name + equity via edgartools beneficial_ownership) | 0.5 day | Single edgartools probe fixes BOTH gaps; biggest pipe-fix per LoC; no schema risk because both columns exist. |
| 2 | **D5** (Form 4 via `to_dataframe()`) | 0.5 day | Replaces silent failure with the academically-strongest insider signal (P-code purchases). |
| 3 | **D6** (earnings_history backfill) | 0.5 day | Wholly new data; unblocks F2 PEAD + F4 EPS-acceleration when those frameworks land. Also writes the event_date/event_time pattern from the prior ADR. |
| 4 | **D4** (customer concentration 3-state, targeted-section regex) | 1 day | Most subtle (3-state semantics); requires the validation corpus from Open Q §6.2. |
| 5 | **D3** (founder status — already partially works; add yf.officers title check) | 0.25 day | Cheap win. |
| 6 | **D7** (IPO date — already works post 2026-05-05 yfinance key fix; just needs state column) | 0.25 day | Already wired; just adds the `_state` column. |

**Total: ~3 days end-to-end.** Each phase is a separate PR. If we
stop at phase 2, the system is materially better than today.

Each phase ships with:
- A unit test against the empirical probe data captured in this ADR
- A second-ticker test against NVDA (calendar-year filer control)
- A `not_disclosed` test against a known no-disclosure case (INTA for
  Gap C, single-class for Gap D)

---

## 8. Why this preserves CLAUDE.md's data-layer guarantee

CLAUDE.md §"AI layer boundary": *every gap-fill outside
`deepdive/narrative.py` must be deterministic; no LLM*.

Every endpoint named in this ADR is deterministic:
- yfinance JSON `.info` parsing — string tokenisation
- edgartools `Form4.to_dataframe()` — XBRL-structured deterministic parser
- edgartools `proxy.beneficial_ownership` — DEF 14A XBRL deterministic parser
- SEC XBRL frames endpoint — JSON
- Targeted regex on `TenK.business` / `risk_factors` — deterministic patterns

No LLM appears in any task in §4. The three-state model preserves
the principle that **a missing value is captured as a missing value
(plus its reason), never substituted by an LLM guess.**

---

## 9. References

- **Probes performed in this session** (all reproducible from this
  repo with EDGAR_IDENTITY set):
  - `yf.Ticker('NVDA').info["companyOfficers"]` → 10 officers, first
    title `"Co-Founder, CEO & Director"`
  - `yf.Ticker('INTA').info["companyOfficers"]` → 10 officers, first
    title `"Chairman & CEO"`
  - `yf.Ticker('INTA').earnings_dates` → DataFrame (20, 3)
  - `yf.Ticker('INTA').insider_transactions` → DataFrame (150, 9)
  - `yf.Ticker('INTA').insider_purchases` → DataFrame (7, 3)
  - `yf.Ticker('INTA').insider_roster_holders` → DataFrame (10, 7)
  - `yf.Ticker('INTA').upgrades_downgrades` → DataFrame (106, 7)
  - `yf.Ticker('INTA').recommendations` → DataFrame (2, 6)
  - `Company('INTA').proxy_season(0).proxy.peo_name` → `"Mr.\xa0Hall"`
  - `Company('INTA').proxy_season(0).proxy.beneficial_ownership` →
    DataFrame (16, 4) with John Hall at 7.64%
  - `Company('INTA').get_filings(form='4').head(20)` → 20 Form 4
    filings dated 2026-02-20 (refutes "no Form 4 found" dive note)
  - `Company('INTA').latest_tenk` → TenK with `.business` (45 KB),
    `.risk_factors` (138 KB), `.subsidiaries` (1 row), `.directors_
    officers_and_governance` (6.7 KB)
  - INTA's 10-K business + risk_factors greppped: 0 customer-
    concentration disclosure phrases (genuine `not_disclosed`)
- ADR-017 — warehouse + task pattern (the pattern this ADR extends)
- CLAUDE.md — data-layer determinism guarantee
- yfinance docs: https://github.com/ranaroussi/yfinance/wiki
- edgartools docs: https://github.com/dgunning/edgartools

---

## 10. Decision-pending checklist

- [ ] User confirms three-state model is the right ergonomic for the
  dive output (`disclosed_exact | not_disclosed | parser_uncertain`)
- [ ] User confirms Phase 1 (D1+D2 via edgartools `beneficial_ownership`)
  as first ship
- [ ] User confirms parallel-task execution within the dive (vs
  serial)
- [ ] User confirms FMP fallback is opt-in (only fires when both SEC
  and yfinance return `parser_uncertain` or empty), gated on
  `FMP_API_KEY` being set
- [ ] User confirms multi-class voting-power calc (Open Q §6.3) is
  out-of-scope for v1

---

*ADR-018 | The Boardroom Lab | 2026-05-05*

*Research is the work. Each gap was probed against the actual API
surface in this session before any solution was written down. Where
a probe wasn't possible, the section is labelled an open question.*

---

## Appendix A — Probe results 2026-05-05 (FMP, Polygon, regex corpus)

This appendix records the empirical findings from FMP/Polygon endpoint
probes (§6.4) and the customer-concentration regex calibration (§6.2)
performed once the user supplied the FMP and Polygon API keys.

The probe scripts (`adr018_probe_fmp.py`, `adr018_probe_polygon.py`,
`adr018_probe_concentration.py`) are archived; they ran with `FMP_API_KEY`
and `POLYGON_API_KEY` set in `.env`.

### A.1 FMP free-tier probe — landscape change finding

**Critical finding (also affects ADR-016)**: FMP retired all `/api/v3/`
and `/api/v4/` endpoints on **2025-08-31**. The new endpoint surface
is `/stable/...` with `?symbol=` query parameter (replacing path-style
`/profile/{ticker}`). The legacy endpoints return:

> `HTTP 403 — Legacy Endpoint: only available for legacy users who
> have valid subscriptions prior August 31, 2025.`

**Impact on ADR-016**: ADR-016's recommended Tier-2 wiring
(`/api/v3/stock-screener?...`) is no longer reachable on free tier.
Anyone implementing ADR-016 today must use `/stable/company-screener`
or equivalent. This needs a separate amendment to ADR-016 — **not
scoped into ADR-018 implementation**, just flagged for visibility.

### A.2 FMP `/stable/` endpoint coverage matrix

Three test tickers (AAPL, NVDA, INTA) ran against six endpoints. **The
"INTA / 402" cell is the most important finding** — FMP free tier has
silent paid-only escalations on smaller-cap stocks even within
nominally-free endpoints.

| Endpoint | AAPL | NVDA | INTA | Verdict |
|---|---|---|---|---|
| `/stable/profile?symbol=` | ✅ ceo+ipoDate+cik | ✅ ceo+ipoDate+cik | ✅ ceo+ipoDate+cik | **PRIMARY for Gap A (CEO name) and IPO** |
| `/stable/key-executives?symbol=` | ✅ 16 execs | ✅ 11 execs | ❌ HTTP 402 | Unreliable on small caps |
| `/stable/insider-trading/latest?symbol=` | ⚠️ symbol-filter ignored — returns platform-wide latest | (same) | (same) | **NOT USABLE** for symbol-specific Form 4 |
| `/stable/income-statement?symbol=` | ✅ FY2025 rev=$416B | ✅ FY2026 rev=$216B | ❌ HTTP 402 | Unreliable on small caps |
| `/stable/revenue-product-segmentation?symbol=` | ✅ iPhone $209B etc. | ✅ Data Center $193B etc. | ❌ HTTP 402 | Useful but not customer-concentration |
| `/stable/revenue-geographic-segmentation?symbol=` | ✅ Americas/Europe etc. | ✅ Taiwan/USA/China | ❌ HTTP 402 | Useful but not customer-concentration |
| `/stable/senate-trades?symbol=` | (not in original probe — surfaced via experiment) | ✅ STOCK Act discl. | ✅ | Different signal class |
| `/stable/house-trades?symbol=` | ✅ | ✅ | ✅ | Different signal class |

**Confirmed values for the 3 tickers (proves response correctness)**:

| | AAPL | NVDA | INTA |
|---|---|---|---|
| `companyName` | "Apple Inc." | "NVIDIA Corporation" | "Intapp, Inc." |
| `ceo` | "Timothy D. Cook" | "Jen-Hsun Huang" | "John T. Hall" |
| `ipoDate` | 1980-12-12 | 1999-01-22 | 2021-06-30 |
| `cik` | 0000320193 | 0001045810 | 0001565687 |
| `fullTimeEmployees` | 164000 | 36000 | 1235 |

**FMP /stable/profile response pattern** is consistent and reliable
for our gap matrix. **This is the single most useful FMP endpoint for
ADR-018 D1 (CEO) and D7 (IPO date) tasks.**

### A.3 Polygon free-tier probe (5 calls/min, end-of-day data)

Six endpoints x 3 tickers, paced at 13s/call. Key finding: **Polygon's
free tier is materially more generous than FMP for fundamentals and
small caps** — INTA returned full data on every endpoint where FMP
402'd.

| Endpoint | AAPL | NVDA | INTA | Verdict |
|---|---|---|---|---|
| `/v3/reference/tickers/{t}` | ✅ all fields | ✅ all fields | ✅ all fields | **Equivalent to FMP /profile but more reliable on small caps** — except no `ceo` field |
| `/vX/reference/financials` | ✅ FY2025 | ✅ FY2026 | ✅ FY2025 | **Full structured fundamentals; could replace SEC companyfacts** |
| `/stocks/v1/short-interest` | ✅ 4 settlements | ✅ 4 settlements | ✅ 4 settlements | New time-series we don't currently capture |
| `/v3/reference/dividends` | ✅ 3 events | ✅ 3 events | ✅ empty (correct — INTA pays no dividend) | Auxiliary |
| `/v2/reference/news` | ✅ 3 articles + AI insights | ✅ | ✅ | Sentiment data |
| `/v1/marketstatus/now` | ✅ | — | — | Health probe |

**Polygon `/v3/reference/tickers` returns**:
- `list_date` — equivalent of FMP's `ipoDate` (matches: AAPL=1980-12-12,
  NVDA=1999-01-22, INTA=2021-06-30)
- `market_cap`, `share_class_shares_outstanding`, `weighted_shares_outstanding`
- `sic_code` + `sic_description` (more current than SEC submissions)
- `total_employees` (AAPL 166000, NVDA 42000, INTA 1336 — slightly
  different from FMP, both within ±1000)
- `address`, `phone_number`, `homepage_url`
- **No `ceo` field — Polygon does not expose CEO name**

**Polygon `/vX/reference/financials` already does period_end-authoritative
labelling**: e.g. INTA's annual ending 2025-06-30 returns
`fiscal_year=2025, fiscal_period=FY` — exactly the convention we just
spent half a day implementing in our companyfacts parser. This is
notable but not actionable: keeping SEC companyfacts as the canonical
source is the right call (provenance + auditability), but **Polygon
financials are a viable cross-check for our parser correctness**.

### A.4 Source-priority chain — final design (revised from §4)

Per the empirical findings:

| # | Task | Updated source priority chain |
|---|---|---|
| **D1** | `CEONameTask` | `(FMP /stable/profile.ceo)` → `(yf.officers tokeniser fix)` → `(edgartools proxy.peo_name + beneficial_ownership cross-ref)` |
| **D2** | `CEOEquityTask` | `(edgartools proxy.beneficial_ownership)` — no fallback (only SEC has this) |
| **D3** | `FounderStatusTask` | `(yf.officers title contains 'co-founder' / 'founder')` → `(edgartools TenK.business regex)` → `(proxy biographical regex)` |
| **D4** | `CustomerConcentrationTask` | `(SEC XBRL ConcentrationRiskPercentage1)` → `(edgartools sections [Item 1, 1A, 7, 8] + v6 regex set)` → `not_disclosed`. **NO FMP fallback** (no concentration endpoint). |
| **D5** | `Form4InsidersTask` | `(edgartools Form4.to_dataframe())` → `(yfinance.insider_transactions — non-SEC codes)`. **NO FMP fallback** (`/stable/insider-trading/latest` ignores `?symbol=`). |
| **D6** | `EarningsHistoryTask` | `(yfinance.earnings_dates)` → `(yfinance.calendar for next quarter)` |
| **D7** | `IPODateTask` | `(yf.firstTradeDateMilliseconds)` → `(FMP /stable/profile.ipoDate)` → `(Polygon /v3/reference/tickers.list_date)` — three sources cross-validate |

**Key correction vs §4**:
- FMP fallback for D5 (insider trades) is **removed** — endpoint broken.
- FMP fallback for D4 (customer concentration) is **removed** — no
  endpoint exists.
- FMP `/stable/profile` is now **PRIMARY** for D1 (was tertiary). It
  works for all 3 test tickers including small-cap INTA.
- Polygon added as a tertiary cross-validator for D7.

### A.5 Customer-concentration regex calibration (§6.2)

Test corpus: 7 tickers. After 6 iterations the v6 pattern set hits
ground truth on every working ticker:

| Ticker | Expected | v6 result | Verdict |
|---|---|---|---|
| AAPL | receivables concentration in Item 8 | `disclosed_exact` rec=38% (carriers) + 12% (one cust) | ✓ |
| NVDA | revenue 22% one direct customer (FY2026) | `disclosed_exact` rev=22% | ✓ |
| FAST | diversified — no concentration | `not_disclosed` | ✓ |
| AMSC | revenue 14% (Inox) FY2024 | `disclosed_exact` rev=14% | ✓ |
| TSLA | variable | `not_disclosed` (current 10-K) | ✓ acceptable |
| INTA | none | `not_disclosed` | ✓ |
| MSFT | "no sales to an individual customer ≥10%" | `not_disclosed` (Microsoft-style negative phrase caught) | ✓ |

**Three pattern-set design decisions validated**:

1. **Section scope = Items 1, 1A, 7, 8** (not the whole filing) — Item 8
   (financial statement notes) is where AAPL and MSFT hide their
   concentration disclosures. business+risk_factors alone misses them.

2. **Revenue vs receivables concentration must be separate columns**.
   They are different SEC disclosures (Reg S-K Item 101(c) vs FASB
   ASC 825). F6's moat signal is revenue-only; receivables concentration
   is a credit-risk signal that belongs to a different framework.

3. **Customer-context filter for the `[Named entity] X%` pattern** — a
   capitalized-noun + "accounted for X% of revenue" pattern matches
   "Grid business segment accounted for 84%" without the filter. The
   filter requires "customer" within ±300 chars of the match, which
   keeps "Inox accounted for 14%" (preceded by "two large customers,
   Inox Wind Limited") and rejects segment language.

4. **Negative-disclosure phrasing diversity** — different filers use
   meaningfully different language:
   - AAPL: *"one customer that represented 10% or more of total trade receivables"* (split into 2 phrases across a comma)
   - NVDA: *"sales to one direct customer represented 22% of total revenue"* (positive disclosure, no negative)
   - AMSC: *"No other customer accounted for more than 10%"* (qualifier after a positive disclosure)
   - MSFT: *"No sales to an individual customer or country other than the United States accounted for more than 10%"* (subject = sales, not customer)

   The v6 negative pattern set covers all four. Any new filer with a
   different phrasing would need a pattern addition — visible in
   `NEGATIVE_DISCLOSURE_PATTERNS` in the archived concentration probe.

### A.6 Consequences for the implementation plan

The user-stated priority is **accuracy first, speed second**, with
"don't overengineer" as a hard constraint. Updated phasing:

| Phase | Gap | Effort | Justification post-probe |
|---|---|---|---|
| **1** | D1 (CEO name) | 0.25 day | FMP /stable/profile + cached → 1-line replacement of broken yfinance matcher |
| **2** | D2 (CEO equity) | 0.5 day | edgartools `proxy.beneficial_ownership` is structured DataFrame; cross-ref `peo_name` → `holder_name`. Single-source. |
| **3** | D5 (Form 4) | 0.5 day | `Form4.to_dataframe()` replaces broken attribute lookup. No fallback needed for accuracy — yfinance secondary. |
| **4** | D6 (earnings_history) | 0.5 day | `yf.earnings_dates` is fully sufficient — wholly new data, no current parser to refactor. |
| **5** | D4 (customer concentration) | 1 day | v6 pattern set validated; just need three-state column + ergonomic dive output. |
| **6** | D3 (founder status) | 0.25 day | yfinance `Co-Founder` title check + existing regex. |
| **7** | D7 (IPO date state) | 0.25 day | Already wired post-2026-05-05 fix; just adds the `_state` column for traceability. Polygon as cross-validator. |

**Total revised: ~3.25 days.** Each phase is independently shippable.
The order changed from §7 because FMP-primary CEO is faster than
edgartools-primary CEO (FMP /stable/profile is one HTTP call returning
the value directly; edgartools requires `proxy_season(0).proxy.peo_name`
which is slower and returns "Mr.\xa0Hall" needing cross-ref).

### A.7 Decision points still open after probes

- [ ] Confirm FMP `/stable/profile` 250/day quota is acceptable for
      universe-scale screener back-fill (one CEO refresh per quarter
      per active ticker; ~600 tickers × 4/year = 2,400 calls/year ≈
      10/day — fine).
- [ ] Confirm Polygon free tier 5/min is acceptable for IPO-date
      cross-validation (rare event; most tickers IPO once and never
      again).
- [ ] §6.3 (multi-class voting power) — **deferred to v2 per user
      directive 2026-05-05**.

---

## Appendix B — Side findings worth a separate ADR

These were discovered during ADR-018 probes but don't fit ADR-018's
gap-task scope. Listed for follow-up:

1. **ADR-016 amendment** — FMP `/v3/...` retired 2025-08-31. The
   recommended Tier-2 wiring needs to switch to `/stable/...` endpoints
   with `?symbol=` query params. ~5 LoC change but architectural sig.

2. **edgartools section-key drift** — TenK uses two different key
   conventions across filings:
   - new: `tk["part_ii_item_8"]` (works for AAPL)
   - legacy: `tk["Item 8"]` (only works for MSFT in this corpus)
   The probe script handles this with a fallback chain. Production
   code (`data/edgar_text_parser.py`) currently uses neither;
   `_safe_text` falls back to whole-filing text. This should be
   updated to use the section accessors with the same fallback —
   makes parsing ~10× faster and ~10× more precise.

3. **FMP STOCK Act endpoints** (`senate-trades`, `house-trades`)
   are FREE on stable tier — political-insider-trade signal. Not
   in current framework set but could power a future "smart political
   money" overlay. One-line per ticker with `?symbol=` works.

4. **Polygon `/vX/reference/financials` cross-validator** — could
   add a periodic correctness probe that compares our SEC companyfacts
   parse against Polygon's pre-parsed financials for a sample of
   tickers. Would catch our parser drift without needing a new
   golden-truth corpus.

*Appendix added 2026-05-05 after FMP + Polygon API keys provided.*

