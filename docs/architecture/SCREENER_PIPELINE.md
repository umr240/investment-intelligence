# Screener pipeline

Reference for the staged screener: the tier ladder, ticker lifecycle, the
time model it ranks on, and how the stages run. Decisions behind it are in
`DECISIONS.md` (DEC-09 to DEC-15); the warehouse-query path that sits beside
it is ADR-017.

## 1. Tier ladder

| Tier | What | I/O | Stage |
|---|---|---|---|
| 0 | Universe: SEC `company_tickers_exchange.json` (ticker, CIK, name, exchange), cached 7 days | 1 SEC call | A |
| 1 | Exchange and listing type: requested exchanges only; units, warrants, preferreds dropped by ticker pattern | none | A |
| 2 | Market cap and sector from yfinance metadata; `cap_min ≤ market cap ≤ cap_max`, optional sector | 1 yfinance call per ticker | A |
| 3 | Exclusion policy: the active policy's `classify()` on sector and industry. Under `none` nothing is excluded | none | A |
| 4 | SEC `frames.json` snapshot: one call returns one concept for every filer. Ranks on a quality score and keeps the top N (default 300); only missing revenue or assets is a hard drop | ~13 SEC calls | B |
| 5 | Per-ticker companyfacts for the shortlist, then the seven gates (§5) | 1 SEC call per ticker | C |
| 6 | Composite score by mode, momentum decile, rank, persist `ScreenerRun` + `ScreenerResult` | yfinance history for the shortlist | C |

Funnel counts are stored per run as `T0_universe` … `T6_flagged`.

## 2. Ticker lifecycle and retention

`Company.status`:

| Status | Meaning | Retention |
|---|---|---|
| `screener_candidate` | Survived a run; not promoted | `retention_days` after `last_screened` (default 30, `--retain-days` per run; the latest run wins) |
| `watchlist` | Added by the user | Until removed |
| `dive_history` | Has been dived | Kept for audit |
| `archived` | Aged out | Data dropped by cleanup |

The weekly cleanup (`screener/cleanup.py`) archives stale candidates and drops
their Financial, source-log and price rows, keeping the Company row for audit.
It never touches `watchlist` or `dive_history`. Screening is exploratory: a
rejected ticker is re-fetched if it reappears.

## 3. Time model

Companies report on their fiscal calendar; cross-company ranking needs a
calendar one. Each `Financial` row stores both: `fiscal_year` / `period` as
reported, and `period_end_date` (authoritative), `period_start_date` and
`filed_date`. Cross-company ranking buckets by the calendar quarter of
`period_end_date`; per-company analysis uses the fiscal labels.

TTM is never stored. The reader derives it on demand (`ttm_at`,
`latest_annual_or_ttm`), so there is one source of truth.

`frames.json` buckets by the calendar period a fact ends in, which is fuzzy for
off-calendar filers. That is acceptable for Tier 4 ranking; Tier 5 uses
per-ticker companyfacts with exact fiscal alignment. yfinance values are
date-keyed snapshots and never supply fundamentals, so they need no mapping.

## 4. Staged execution

The full screen runs as three scheduled jobs (`screener-stage-A/B/C`), each
with its own concurrency cap (`MAX_YF_CONCURRENCY`, `MAX_SEC_CONCURRENCY`):

- **A**: Tiers 0–3, creates the `ScreenerRun`.
- **B**: Tier 4, resumes the latest incomplete run.
- **C**: Tiers 5–6, finalises the run.

Each stage checkpoints to `ScreenerStage`, reads the previous stage's state,
and can be re-run on its own (`invest screen-stage`). A stage that keeps fewer
than `STAGE_MIN_SURVIVOR_RATIO` of its input fails loudly. A failed stage does
not block the daemon; the next run starts a new `ScreenerRun`.

## 5. Hard gates (Tier 5)

| Gate | Rule | Severity |
|---|---|---|
| G1_policy | The active exclusion policy's `gate()`; `none` passes | hard |
| G2 | Market cap present | hard |
| G3 | Analyst coverage ≥ 1 | soft |
| G4 | Asset-growth decile: 10 hard, 9 soft | hard / soft |
| G5 | External financing: severe hard, mild soft | hard / soft |
| G6 | Piotroski subset ≥ 3 | soft |
| G7 | Momentum decile ≥ 2 | soft |

A ticker is clean only if every hard gate passes; soft failures move it to
the flagged tier, still ranked and persisted.
