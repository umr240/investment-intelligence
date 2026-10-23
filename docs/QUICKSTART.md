# Quick start

Everything runs from a normal terminal with `uv run invest <command>`.

---

## 1. Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/umr240/investment-intelligence.git
cd investment-intelligence
uv sync
cp .env.example .env          # then edit EDGAR_IDENTITY
uv run invest db-init         # create or upgrade the schema; safe to re-run
```

`.env`:

```
# Required: SEC asks every client to identify itself (no key, 10 requests/sec)
EDGAR_IDENTITY="Your Name your.email@example.com"

# Recommended: Polygon's free tier covers prices, RSI/MACD/SMA and short-interest history
POLYGON_API_KEY=

# Optional: only for the prose narrative (`invest score-card TICKER --narrate`).
# OpenAI is the primary provider, Anthropic the fallback.
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Optional: FMP's bulk screener is a paid endpoint; leave empty unless you have it
FMP_API_KEY=
```

No API key is needed for data refreshes, framework scores or screens.

Check the install:

```bash
uv run invest --help
uv run invest task list        # registered warehouse tasks
```

---

## 2. Data sources

| Source | Cost | Used for |
|---|---|---|
| **SEC EDGAR** | free, 10 requests/sec | universe, fundamentals (companyfacts), frames, IPO dates. Canonical |
| **yfinance** | free, bans concurrency above 1 | metadata, price history, analyst coverage, ownership |
| **Polygon** | free tier, 5 requests/min | prices, OHLCV, short interest, RSI/MACD/SMA (opt-in) |
| **FMP** | bulk screener is paid | off unless `INVEST_USE_FMP_SCREENER=1` |

Polygon is preferred for what it covers; yfinance fills the fields Polygon does
not expose. A full-universe metadata fill on free tiers takes hours, so §5
fills it once and then keeps it fresh incrementally.

---

## 3. Deep dive on one ticker

```bash
uv run invest dive NVDA                      # all 7 frameworks
uv run invest dive NVDA --frameworks F1,F5   # fetch only what F1 and F5 need
uv run invest dive NVDA --mode A             # preset: A = F1–F3, B = F1–F5, C = F1–F7
uv run invest dive NVDA --tier 2             # full dive
uv run invest dive NVDA AAPL COST            # several tickers, each independent
uv run invest dive NVDA --force              # refetch fundamentals, bypassing the cache
```

Each dive scores the frameworks it can, marks the rest unfeasible with a
reason (a recent IPO cannot run F1, for example), and persists the result.
The ICA, PSA and BEW overlays run automatically when their triggers fire and
add a capped bonus to the composite.

```bash
uv run invest data plan NVDA --frameworks F1    # what a dive would fetch, without fetching
uv run invest score-card NVDA                    # latest scorecard
uv run invest iv NVDA                            # intrinsic value (Damodaran + Greenwald)
uv run invest export deepdive NVDA --out NVDA.md
uv run invest export list                        # dive and screener history
uv run invest overlay run NVDA --type ICA        # run one overlay by hand
uv run invest overlay status NVDA                # last detected triggers
```

---

## 4. Screen a ticker list

The staged screener runs three checkpointed stages (pipeline reference:
`docs/architecture/SCREENER_PIPELINE.md`). `--tickers` skips the full SEC
universe, which is the practical path on free API tiers:

```bash
uv run invest screen-stage A --tickers PAYC,INTA,DCBO,DOCN,BRZE,TENB,QLYS \
    --cap-min 500M --cap-max 10B
# prints a run id, e.g. 1

uv run invest screen-stage B --run-id 1              # SEC frames: rank and narrow
uv run invest screen-stage C --run-id 1 --mode B     # companyfacts, 7 gates, rank, persist

uv run invest screen-show 1 --tier all               # or clean / flagged
uv run invest screen-ls                              # past runs
```

Rough timings on free tiers: stage A ~10 s per ticker, stage B ~3 min, stage C
5–20 min depending on the shortlist (Polygon is paced at 5/min). A stage that
keeps fewer than 10% of its input fails with the reason instead of silently
returning nothing.

With a paid FMP plan, `INVEST_USE_FMP_SCREENER=1 uv run invest screen-stage A`
without `--tickers` screens the bulk universe.

---

## 5. Fill and query the warehouse

The warehouse is the `companies` table, one column per filter, kept fresh by
tasks. Fill it once:

```bash
uv run python scripts/fill_universe.py --max-tickers 50      # smoke run, ~2 min
uv run python scripts/fill_universe.py                       # full fill, ~1.5–2 h
uv run python scripts/fill_universe.py --skip-yfinance --skip-polygon   # SEC only, ~17 min
```

| # | Phase | Source | Time |
|---|---|---|---|
| 1 | Universe | SEC `company_tickers_exchange.json` | <1 s |
| 2 | IPO date + SIC sector | SEC `submissions.json` per company | ~17 min |
| 3 | Exclusion-policy classification | in memory (no-op under `none`) | seconds |
| 4 | Metadata | yfinance, 1/s | ~1.5 h |
| 5 | Backfill | Polygon, 5/min | recovers what yfinance missed |

Then compute scores. `fundamentals` reads SEC filings for every company in the
universe, serially at SEC's pace: roughly 1.5 hours the first time (estimated
from a partial run). After that a company is read again once its data is 90
days old. For a quick look at a handful of tickers, use the staged screen in §4
instead.

```bash
uv run invest task run fundamentals      # first run roughly 1.5 h
uv run invest task run composite_score
uv run invest task run framework_score
```

The warehouse query itself takes under a second:

```bash
uv run invest screen --warehouse --cap-min 500M --cap-max 10B \
    --rank-by framework_composite_score --min-framework-score 5.0 --top-n 30
```

Other warehouse filters: `--min-roic`, `--max-debt-equity`, `--min-fcf-margin`,
`--min-completeness`, `--sector`. `uv run invest task status` shows how fresh
each column is.

Tasks you can run on their own (`uv run invest task run NAME`): `metadata_yf`,
`metadata_polygon`, `exclusion_classify`, `ipo_date`, `fundamentals`,
`composite_score`, `framework_score`, and with `POLYGON_API_KEY` the
`polygon_current_price`, `polygon_weekly_price`, `polygon_short_interest`,
`polygon_rsi`, `polygon_sma` and `polygon_macd` tasks.

---

## 6. Watchlist

```bash
uv run invest watchlist add NVDA --role core --notes "why it is here"   # core | satellite | monitor
uv run invest watchlist list
uv run invest watchlist remove NVDA
```

Watchlist tickers are never archived.

---

## 7. Scheduler

Register jobs once, then run the daemon:

```bash
uv run invest scheduler add-job warehouse-yf-tasks      --cron '0 2 * * *'
uv run invest scheduler add-job warehouse-sec-tasks     --cron '0 4 * * *'
uv run invest scheduler add-job warehouse-rollup-tasks  --cron '0 6 * * *'
uv run invest scheduler add-job polygon-watchlist-tasks --cron '0 3 * * *'
uv run invest scheduler add-job screener-cleanup        --cron '0 1 * * 0'

uv run invest scheduler add-deepdive monday-watch --tickers NVDA,COST,V --cron '0 8 * * 1'
uv run invest scheduler add-deepdive weekly-quality --tickers AAPL --frameworks F1,F5 --cron '0 9 * * 1'

uv run invest scheduler list
uv run invest scheduler remove-job monday-watch
uv run invest scheduler start          # blocking; Ctrl+C to stop
```

Jobs are stored in `.ii_jobs.json`. Nothing runs that you did not register.
Each task's refresh interval decides what a run actually fetches (metadata
24 h, SIC sector 30 d, IPO date 180 d, fundamentals 90 d), so most runs are
cheap.

To run the daemon outside a terminal, register `scripts/run_scheduler_daemon.sh`
with launchd or systemd, or `scripts/run_scheduler_daemon.bat` with Windows
Task Scheduler (`scripts/windows_task_scheduler_daemon.README.md`).
`scripts/run_weekly_screener.sh` / `.bat` wrap the weekly screen-and-dive
pipeline the same way.

---

## 8. Housekeeping

```bash
uv run invest screen-cleanup --dry-run      # preview: screener candidates past retention
uv run invest screen-cleanup                # archive them; watchlist and dive history are kept
uv run invest data refresh NVDA             # refresh one ticker without diving
uv run invest data refresh NVDA --years 20  # longer history for F7
uv run invest data gaps NVDA                # what is still missing, and why
uv run invest data cache-stats
uv run invest data cache-clear NVDA
uv run invest screen-candidates --sector Technology
```

---

## 9. Exclusion policies (optional)

Nothing is excluded by default (`EXCLUSION_POLICY=none`), and the exclusion
column is hidden in the UI. To leave out certain industries or companies,
install a package that registers a policy and set its name:

```bash
uv pip install -e ../my-policies
echo 'EXCLUSION_POLICY=mandate' >> .env
uv run invest screen --warehouse --policy mandate    # or per run
```

A policy never changes a score and records every exclusion with its reason.
How to write one: `screener/policies/README.md`.

---

## 10. Troubleshooting

**"Stage A retained X/Y survivors — below threshold".** An upstream API failed
mid-run, usually a yfinance ban. Test with `uv run invest data refresh AAPL`;
if it fails, wait 1–4 hours.

**"yfinance HTTP Error 401: Invalid Crumb".** Yahoo's anti-abuse layer. The
client retries three times; concurrency is already 1.

**F2 or F4 unfeasible.** They need price history and short-interest history.
The Polygon tasks cover only watchlist and portfolio tickers (§6), so either
add the ticker to the watchlist and run `uv run invest task run polygon_weekly_price`
and `uv run invest task run polygon_short_interest`, or dive again with `--force`.

**Polygon 429.** Handled: the client waits for `retry-after` and retries.

**"Stage B: no completed Stage A to resume".** Run stage A first, or pass
`--run-id`.

**Empty `invest task status`.** The database has no companies yet. Run
`scripts/fill_universe.py --max-tickers 50` (§5) or a stage A screen (§4).

---

## 11. A weekly routine

```bash
uv run invest task run metadata_yf
uv run invest task run fundamentals
uv run invest task run framework_score
uv run invest screen --warehouse --cap-min 500M --cap-max 10B \
    --rank-by framework_composite_score --min-framework-score 5.0
uv run invest dive INTA
uv run invest watchlist add INTA --role satellite
uv run invest export deepdive INTA --out INTA.md
```

---

## 12. Where to find more

- `README.md`: what the system does and why
- `docs/methodology/`: the frameworks, overlays and screener specification
- `docs/architecture/SCREENER_PIPELINE.md`: tiers, lifecycle and staged runs
- `docs/architecture/DATA_LAYER.md`: the framework-aware lazy load
- `docs/architecture/DECISIONS.md` and `docs/architecture/adrs/`: why things are the way they are
