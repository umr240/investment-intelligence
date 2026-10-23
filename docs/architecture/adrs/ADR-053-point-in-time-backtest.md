# ADR-053 — Point-in-Time Backtest With Multiple-Testing Control

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off. Blocked on a price-data decision (§2.1).** |
| **Phase** | Methodology validation |
| **Extends** | `docs/methodology/SCREENER_WORKFLOW.md` (multiple-testing note), ADR-026 (data freshness tiers) |
| **Provenance** | Data-readiness measurement 2026-10-21 |

---

## 1. Context

The composite thresholds (initiate 7.0, watchlist 5.0, monitor 3.0) and the
mode weights have never been tested out of sample in this repository.
`SCREENER_WORKFLOW.md` already names the problem: under multiple testing,
Harvey, Liu & Zhu (2016) argue for t > 3.0.

Data readiness, measured on the author DB:

| Requirement | State |
|---|---|
| Fundamentals dated by filing | `filed_date` populated on 198,886 of 198,937 financial rows — **ready** |
| Prices for the universe | `price_history` covers **88 companies** (2014-08-18 → 2026-10-12) — **not ready** |
| Delisted companies | Universe comes from SEC's current `company_tickers_exchange.json`, so current filers only — **survivorship bias** |
| Historical metadata | `companies` holds the latest snapshot only (market cap, sector) — **not point-in-time** |
| Restated comparatives | Later filings restate earlier periods (ADR-030-A2); naive joins leak the future |

A backtest on today's data would mostly measure survivorship.

## 2. Decision (staged)

### 2.1 Stage 0 — data (blocking; a user decision)

- **Universe with delisted filers:** CIKs that filed 10-Ks in each historical year, from EDGAR's full index.
- **Prices for the full universe, including delisted names.** yfinance lacks delisted history, so this needs a source decision: a paid dataset or an alternative free source, with licence checked.
- **As-of joins:** a signal at date *t* uses only rows with `filed_date ≤ t`, and the first-filed value, not the restated one.

### 2.2 Stage 1 — engine

- `backtest/` (new): periodic rebalance, composite recomputed as of each date, transaction costs, benchmark.
- Every configuration tried (modes, thresholds, rebalance frequency) is logged to a trials table, so the number of trials is counted honestly.

### 2.3 Stage 2 — statistics

- Report the Sharpe ratio together with the **deflated Sharpe ratio** (Bailey & López de Prado, 2014), using the trial count from §2.2.
- Also report the Harvey-Liu-Zhu t > 3 hurdle.
- A hold-out period is frozen before the first run and evaluated once.
- No performance claim appears in the README unless it is reported with these statistics.

### 2.4 What this ADR does NOT decide

- Any trading or execution capability. This is research validation only.

## 3. Inversion (mandatory)

- **Backtest overfitting:** iterating until the history looks good. Mitigations: trial counting, deflated Sharpe, frozen hold-out.
- **Survivorship and look-ahead:** the two classic killers. Mitigations: §2.1, both blocking.
- **A null result.** That is a valid and valuable outcome; it is reported, not buried.

## 4. Alternatives considered

- **Backtest on the 88 companies with prices:** rejected. Biased sample, no statistical power.
- **Skip validation:** leaves every threshold an assumption.

## 5. Consequences

- Large effort, dominated by data acquisition.
- The project gains the one piece of evidence that its composite means anything.

## 6. References

- Bailey, D. H., López de Prado, M. (2014). *The Deflated Sharpe Ratio.* Journal of Portfolio Management 40(5).
- Harvey, C. R., Liu, Y., Zhu, H. (2016). *…and the Cross-Section of Expected Returns.* Review of Financial Studies 29(1).
- `docs/methodology/SCREENER_WORKFLOW.md`
