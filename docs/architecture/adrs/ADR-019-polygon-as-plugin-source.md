# ADR-019 — Polygon.io as a plugin source for price / momentum / technical tasks

| Field | Detail |
|---|---|
| **Status** | **Accepted** (Phase 5a complete, 2026-05-06; status updated 2026-05-17) — six Polygon FilterTasks shipped behind `POLYGON_API_KEY` (current price, weekly aggregates, RSI, SMA, MACD, short interest). Watchlist-scope only (5 req/min free-tier infeasible at universe scale). |
| **Date** | 2026-05-07 |
| **Extends** | ADR-017 (warehouse + task pattern) — adds Polygon as a 5th source |
| **Extends** | ADR-018 §A.3 — supersedes ADR-018's "Polygon doesn't help much" framing once `/v2/aggs` was probed |
| **Preserves** | CLAUDE.md determinism guarantee (zero LLM); SEC remains canonical for fundamentals |
| **Provenance** | User directive 2026-05-07: "frameworks related to momentum, current price, current trends, candles can be used with polygon.io is feasible? ... each task is INDEPENDENT, runs on its own cadence, retries its own failures, updates its own column(s)" |

---

## 0. The non-negotiable shape

Per the user directive (echoing ADR-017 §3): **no single API failure may produce a hard stop**. This ADR is only acceptable if its proposal:

1. Makes Polygon **opt-in** — POLYGON_API_KEY unset → behaviour identical to today
2. Uses Polygon as **one of several writers** to a shared table — F2 reads `price_history`, doesn't know Polygon exists
3. Leaves yfinance writers in place; Polygon adds rows, never *replaces* yfinance
4. Per-task failure isolation — Polygon task that 403s doesn't break Polygon task that 200s
5. Preserves the source-priority chain at READ time: if both sources have a row, the deterministic precedence rule wins

If any of those are violated, scrap the proposal. This document keeps them.

---

## 1. What I tested and what it returned

All probes 2026-05-07, free-tier API key, paced at 13s/call. Probe script archived (`adr019_probe_polygon_aggs.py`).

### 1.1 Endpoints that WORK free

| Endpoint | Tickers tested | Returns | Latency | Use for |
|---|---|---|---|---|
| `/v2/aggs/ticker/{t}/prev?adjusted=true` | AAPL, NVDA, INTA | yesterday's OHLCV bar | ~200ms | current-price proxy |
| `/v2/aggs/ticker/{t}/range/1/day/{from}/{to}` | AAPL, NVDA, INTA | daily bars (22 in 30-day window for all 3) | ~250ms | F2 daily resolution + future technical overlays |
| `/v2/aggs/ticker/{t}/range/1/week/{from}/{to}` | AAPL, NVDA, INTA | weekly bars (15 results page 1 + `next_url` for pagination) | ~250ms | **F2 12-1 momentum primary input** |
| `/v1/indicators/sma/{t}` | AAPL, NVDA, INTA | SMA values series | ~200ms | future technical-overlay frameworks |
| `/v1/indicators/rsi/{t}` | AAPL, NVDA, INTA | RSI values series | ~200ms | mean-reversion overlay |
| `/v1/indicators/macd/{t}` | AAPL, NVDA, INTA | MACD lines | ~200ms | trend overlay |
| `/v3/reference/tickers/{t}` (probed in ADR-018 §A.3) | all 3 | profile incl `list_date`, market_cap | ~250ms | IPO date cross-validator (D7) |
| `/vX/reference/financials` (ADR-018 §A.3) | all 3 incl small-cap INTA | structured income/balance/cashflow | ~300ms | fundamentals cross-validator only |
| `/stocks/v1/short-interest` (ADR-018 §A.3) | all 3 | settlement_date / short_interest / days_to_cover time series | ~250ms | **F4 short-interest history (PRIMARY — yfinance only has snapshot)** |
| `/v3/reference/dividends` (ADR-018 §A.3) | all 3 | dividend events | ~250ms | future dividend-yield framework |

### 1.2 Endpoints that 403 free-tier

| Endpoint | Why blocked |
|---|---|
| `/v2/snapshot/locale/us/markets/stocks/tickers/{t}` | "NOT_AUTHORIZED — upgrade your plan" — current real-time snapshot is paid only |

### 1.3 Aggregate-bar field shape (uniform across daily/weekly)

```json
{
  "v":  40059432.0,    // volume
  "vw": 255.0165,      // volume-weighted average price (good current-price proxy)
  "o":  254.08,        // open
  "c":  255.63,        // close
  "h":  256.18,        // high
  "l":  253.33,        // low
  "t":  1775016000000, // milliseconds epoch (start of bar)
  "n":  616606         // transactions
}
```

`adjusted=true` applies splits + dividends (matches `auto_adjust=True` in yfinance).
Pagination via `next_url` for windows that exceed the limit.

---

## 2. Where Polygon outperforms yfinance / FMP

Concrete capabilities Polygon offers that we don't currently have:

| Capability | yfinance today | Polygon proposed | Why this matters |
|---|---|---|---|
| **No anti-abuse blocks at scale** | Anti-abuse 401s above ~1 req/sec, IP penalty boxes 1-4hrs (ADR-016 §Empirical) | Standard 5/min throttle on free tier; predictable 429 with retry-after | yfinance is unreliable at universe scale; Polygon is reliable but slow |
| **Time-series short interest** | `.info.shortPercentOfFloat` = 1 snapshot only | `/stocks/v1/short-interest` returns settlement-date series with days-to-cover | F4's "short interest delta" signal needs a time series, not a snapshot |
| **Built-in indicators** | None — must roll your own SMA/RSI/MACD from price history | Server-side `/v1/indicators/*` returns the values directly | Saves rolling-window math; reduces our code surface |
| **Daily granularity vs weekly** | Both supported; weekly is what we use | Both supported with adjusted-flag | Equivalent |
| **End-of-day reliability** | Yahoo backfills with delays / occasional bad data | Polygon paid for accuracy as a primary | Higher data quality |

### 2.1 Where Polygon does NOT help vs current

| Need | Why Polygon is wrong source |
|---|---|
| Per-period XBRL fundamentals | SEC companyfacts is canonical (ADR-018 §A.3); Polygon is fine but adds surface for no integrity gain |
| CEO name / founder / equity % | No CEO field on Polygon; ADR-018 D1/D2 already handled by FMP + edgartools |
| Customer concentration | Not in Polygon's data model |
| Insider trades (Form 4) | Not surfaced free; SEC + edgartools is the source per ADR-018 D5 |
| Real-time intraday quote | Free tier 403s |

**Rule**: Polygon writes to columns where it adds time-series breadth or reliability. It is NOT the fundamentals source of truth.

---

## 3. Free-tier quota math (the bound the architecture must respect)

Polygon free tier: **5 calls/min** sustained. Bursts above this hit 429. After 429 we wait 60s.

### 3.1 Per-dive cost (worst-case, all Polygon-eligible tasks active)

| Polygon task per dive | Calls |
|---|---|
| `aggs/ticker/{t}/range/1/week/{from}/{to}` (12-month window for F2 momentum) | 1 |
| `aggs/ticker/{t}/prev` (current-price snapshot proxy) | 1 |
| `stocks/v1/short-interest?ticker={t}` (F4 short-interest history) | 1 |
| `v3/reference/tickers/{t}` (IPO date cross-validate D7) | 1 |
| **Total per dive** | **4** |

At 5/min, **one dive ≈ 50 seconds wall-clock for Polygon's branches** if they run sequentially. Run them in parallel (4 calls inside one minute) and you're at the cap; need a TokenBucket to throttle.

### 3.2 Watchlist refresh cost (~600 tickers × momentum-weekly only)

- 600 tickers × 1 call = 600 calls
- At 5/min = **120 minutes wall-clock**

That's too slow for interactive use. Acceptable for **nightly cron**; unacceptable for "click refresh and wait".

### 3.3 Universe screener refresh (~10,000 tickers)

- Not viable on free tier. 10,000 × 1 call = 33 hours.
- **Decision**: Polygon is NOT a screener-Tier-2 source. Stays at the dive layer + nightly watchlist refresh layer.

### 3.4 Daily quota walls

5/min × 60 × 24 = 7,200 calls/day theoretical. Documented free-tier daily caps (per Polygon docs) are looser than the per-minute cap when averaged. In practice the per-minute throttle dominates.

**Conclusion**: budget Polygon for **dives** (rare, low concurrency) and **scheduled watchlist refreshes** (≤ once per day per ticker), not for **screener runs** (universe-scale).

---

## 4. Architecture — Polygon as a TaskSource per ADR-017

### 4.1 The independence guarantees, made concrete

```
Per the user's directive, every Polygon-backed task implements:

class PolygonTask(Protocol):
    name: str                     # unique e.g. 'polygon_weekly_prices'
    refresh_interval: timedelta   # cadence: daily, weekly, monthly
    columns_written: list[str]    # what this task fills (e.g. ['price_history.*'])
    polygon_endpoint: str         # the single endpoint it touches

    def select_pending(db) -> list[Company]:
        # tickers where my column(s) are stale or empty
        ...

    async def fetch_one(ticker, *, polygon_bucket: TokenBucket) -> Result | Failure:
        # one ticker, one Polygon call (or pagination chain), bucket-throttled
        ...

    def persist(db, ticker, result):
        # idempotent UPSERT into the ticker's column(s)
        ...
```

The `TokenBucket(rate=5/60, burst=5)` is shared across ALL Polygon tasks process-wide. Even if 4 tasks run concurrently, the bucket serializes them at 5/min total.

### 4.2 What a "Polygon failure" looks like and what it does NOT do

| Failure mode | Polygon task behaviour | Framework (F2 etc.) impact |
|---|---|---|
| POLYGON_API_KEY unset | Task short-circuits; logs once; no rows written | F2 reads price_history — yfinance rows still present → no impact |
| HTTP 403 (paid endpoint) | Task records `task_failures` row, exits | Other Polygon tasks unaffected (different endpoint) |
| HTTP 429 (rate limit) | Task waits retry-after, retries up to 3x | Per-dive latency +60s; eventually succeeds |
| Network timeout | Task records failure, exits chunk | Next refresh-interval-cron tries again |
| Bad payload (parse error) | Task logs + skips ticker | One ticker missing data; others unaffected |

**The contract**: F2 NEVER imports Polygon. F2 reads `price_history` table. Whoever wrote those rows (yfinance, Polygon, both) is invisible to F2.

### 4.3 Source precedence at READ time

When `price_history` has rows from BOTH yfinance and Polygon for the same `(company_id, date)`, we need a tiebreaker. Already handled by the existing `source` column on `PriceHistory`:

```
PRECEDENCE: polygon > yfinance
```

Why: Polygon is paid-grade end-of-day data; yfinance is scraped. Reader sorts by source priority on duplicate dates.

But — the `__table_args__` already has `UniqueConstraint("company_id", "date")` so we can't have both rows. The task must UPSERT, not append. Polygon task overwrites yfinance row when both exist. yfinance task respects existing Polygon row (don't overwrite).

This rule lives in the persist function, not in F2.

### 4.4 Tasks proposed (concrete fleet)

| # | Task name | Endpoint | Columns | Cadence | Failure tolerance |
|---|---|---|---|---|---|
| **P1** | `PolygonWeeklyPriceTask` | `/v2/aggs/{t}/range/1/week/...` | `price_history.*` (weekly) | daily for watchlist; on-demand for dive | F2 falls back to yfinance rows |
| **P2** | `PolygonDailyPriceTask` | `/v2/aggs/{t}/range/1/day/...` | `price_history.*` (daily) | optional; off by default | not used by F1-F7 yet |
| **P3** | `PolygonShortInterestTask` | `/stocks/v1/short-interest?ticker={t}` | `short_interest.*` | weekly | F4 falls back to single yfinance snapshot |
| **P4** | `PolygonIPODateValidateTask` | `/v3/reference/tickers/{t}` | `Company.ipo_date_state` (validation only — never overwrites) | monthly | D7 reconciliation already works without it |
| **P5** | `PolygonRSITask` *(deferred)* | `/v1/indicators/rsi/{t}` | new column `latest_rsi_14`? | weekly | no framework consumes yet |
| **P6** | `PolygonSMA50Task` *(deferred)* | `/v1/indicators/sma/{t}?window=50` | new column? | weekly | no framework consumes yet |

**P1, P3 ship in v1.** P4 is cheap and adds triangulation. P2/P5/P6 wait for a consuming framework.

### 4.5 What this means for F2 today

**F2 doesn't change.** It still reads `reader.price_history(within_days=420)`. The behaviour difference is:

- **Before P1**: price_history rows are from yfinance. Sometimes the .history() call fails silently → F2 has fewer bars to work with → noisier 12-1 momentum.
- **After P1**: price_history rows are from Polygon (preferred) AND/OR yfinance (fallback). Stronger guarantee that F2 has data to compute on.

INTA's F2 score (3.0) wouldn't change. NVDA's (10.0) wouldn't change. AAPL's (9.0) wouldn't change. The DATA improves, not the FORMULA. That's the right boundary.

---

## 5. Schema additions (additive)

```sql
-- Add 'source' to PriceHistory if not already constrained
-- (already exists with default='yfinance' per current schema)

-- Time-series short interest already has the schema (ShortInterestRecord);
-- Polygon task just writes more rows. No DDL needed for P1 and P3.

-- Future per-task scheduling visibility (matches ADR-017 §7)
CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY,
    task_name TEXT NOT NULL,
    ticker TEXT,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,   -- 'success' | 'failed' | 'skipped'
    error TEXT,
    rows_written INTEGER DEFAULT 0
);
CREATE INDEX idx_task_runs_task ON task_runs(task_name, started_at DESC);
```

`task_runs` makes "did Polygon successfully refresh INTA today?" answerable in SQL without log-grepping. ADR-017 §7 already declared a `task_failures` table; `task_runs` is a superset (success + failure).

---

## 6. The single concrete change to existing code

`data/api/polygon_client.py` (new, ~120 LoC) — slim client implementing TokenBucket + retry + the four endpoint wrappers we use. Pattern mirrors `data/api/fmp_client.py`:

```python
class PolygonClient:
    BASE = "https://api.polygon.io"
    BUCKET = TokenBucket(rate=5/60, burst=5)

    def fetch_weekly_aggs(self, ticker, start, end) -> list[PolygonBar]: ...
    def fetch_short_interest(self, ticker, limit=8) -> list[PolygonShortInterest]: ...
    def fetch_ticker_details(self, ticker) -> PolygonTickerDetails: ...
```

Each method handles its own pagination + 429 backoff + 403 short-circuit (matches the FMP 402 short-circuit pattern from ADR-018).

**Per the user directive**: each method is independent. Failure of `fetch_short_interest` doesn't affect `fetch_weekly_aggs`.

---

## 7. Decision recommendations — what I would actually ship

### 7.1 Ship now (v1)

1. **`data/api/polygon_client.py`** — slim wrapper, 4 methods, opt-in via POLYGON_API_KEY
2. **P1: Polygon weekly prices** — wire as ADDITIVE writer to `price_history`. yfinance writer stays. Source priority `polygon > yfinance` enforced in persist.
3. **P3: Polygon short-interest history** — wire as PRIMARY writer to `short_interest` table. yfinance snapshot stays as fallback when Polygon fails.
4. **`task_runs` table** — visibility for "did this task succeed" in SQL.

### 7.2 Defer (no consumer yet)

- P2 daily prices — unless a framework needs daily granularity
- P5/P6 indicators — only when an overlay or new framework consumes them
- P4 IPO date cross-validate — D7 already works; P4 is cheap to add but low value

### 7.3 Don't do

- ❌ Don't move fundamentals to Polygon. SEC companyfacts is canonical (ADR-018 reaffirmed this).
- ❌ Don't use Polygon at universe scale (5/min × 10K tickers = 33 hours).
- ❌ Don't replace yfinance. Polygon is additive. yfinance remains the fallback.

---

## 8. What this preserves vs what changes

| Preserved | What changes |
|---|---|
| F1-F7 framework code (zero changes) | Data layer gains a 5th source |
| CLAUDE.md determinism (zero LLM) | Polygon as opt-in plugin |
| ADR-017 task pattern (each task independent) | New tasks P1/P3 added to the registry |
| ADR-018 source priority chains | Polygon slots in as new tier of priority for price + short interest |
| yfinance fallback semantics | Polygon is preferred but never required |
| Dive call-trace from previous session | One additional optional Polygon branch (gated on POLYGON_API_KEY) |

---

## 9. Open questions before implementation

1. **`task_runs` granularity** — log every refresh attempt, or only failures? Recommend **every attempt** for v1; cheap and gives ops visibility. ~50 rows/day on dive-only usage.

2. **Polygon weekly bar timestamp interpretation** — the probe shows `t` = millisecond epoch of the BAR START. Our existing `PriceHistory.date` is an end-of-period date (Friday for weekly). Need to convert: bar start = Monday → `date = bar_start + 4 days`. Verify on actual data before P1 implementation.

3. **Pagination chain for full 52-week history** — probe showed `next_url` returned alongside 15 results. Does `next_url` count against the 5/min budget? Almost certainly yes (it's a separate GET). For 52 weekly bars in ~3-4 pages = 3-4 calls per ticker for full history. After cold backfill, incremental fetches are 1 page. Worth measuring.

4. **Polygon's `vw` (volume-weighted avg) vs `c` (close)** — yfinance gives close. Polygon gives both. Recommend storing `c` to match (column already exists). Could add `vw` as a new column later for VWAP-based signals.

5. **Single-machine TokenBucket vs multi-process** — if the screener cron and dive command run in different processes, they need a shared rate-limit view. SQLite-backed TokenBucket? Or accept that two processes hit 5+5 = 10/min and risk 429s? Recommend file-locked SQLite bucket for safety. Adds ~20 LoC.

---

## 10. Time-to-ship estimate

If approved as scoped in §7.1:

| Step | LoC | Effort |
|---|---|---|
| `polygon_client.py` (4 methods + TokenBucket + retry) | ~120 | 0.5 day |
| `tasks/polygon_weekly_price_task.py` (P1) | ~80 | 0.25 day |
| `tasks/polygon_short_interest_task.py` (P3) | ~60 | 0.25 day |
| `task_runs` schema migration + index | ~20 | 0.1 day |
| Wire P1 + P3 into dive Phase 1 (one new branch in `pipeline.py`) | ~30 | 0.25 day |
| Validation: dive INTA/NVDA/AAPL → confirm Polygon rows in price_history with correct precedence | — | 0.25 day |

**Total ~1.5 days** to ship a fully-isolated Polygon plugin that improves F2's data reliability without altering F2's logic.

---

## 11. References

- **Probes** (reproducible from this repo with POLYGON_API_KEY in `.env`):
  - `adr019_probe_polygon_aggs.py` (archived) — aggs + indicators + snapshot
  - `adr018_probe_polygon.py` (archived) — ticker details + financials + short interest + dividends + news (ADR-018 §A.3)
- **Polygon docs**: https://polygon.io/docs/stocks/
- ADR-017 — task pattern (`each task is independent`)
- ADR-018 §A.3 — original Polygon assessment (this ADR supersedes it for the price/momentum dimension)
- CLAUDE.md "AI layer boundary"

---

## 12. Decision-pending checklist

- [ ] Confirm scope: ship P1 (weekly prices) + P3 (short-interest history) only in v1; defer P2/P4/P5/P6
- [ ] Confirm precedence rule on `price_history` duplicates: `polygon > yfinance`
- [ ] Confirm `task_runs` table is acceptable additive schema
- [ ] Confirm Polygon stays opt-in (POLYGON_API_KEY unset → behaviour identical to today)
- [ ] Confirm Polygon is NOT used for screener Tier 2 (free-tier quota math forbids it)
- [ ] Confirm SEC remains canonical for fundamentals (Polygon `/vX/reference/financials` is for cross-validation only, never primary)

---

*ADR-019 | The Boardroom Lab | 2026-05-07*

*Polygon is a higher-quality, higher-latency price/short-interest source than yfinance. The right shape is "additive plugin with ADR-017's per-task independence", not "replace yfinance". Free-tier quota math forbids universe-scale use, so this lives at the dive + watchlist layer only. Each task fails independently; F2 reads from the table, never from Polygon.*
