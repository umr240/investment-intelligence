<!--
Specification document. This is the specification of record for the seven frameworks, the screener gates, the composite scoring, and the database schema.

Read it as the design intent the code was built against, not as a description
of current behaviour. Where the two diverge, the code and the decision log
(docs/architecture/DECISIONS.md) are authoritative, and the divergence is
annotated inline below.
-->

# PROJECT_SPEC.md — Investment Intelligence System
## Full Technical Specification
### Version 1.0 — May 2026

---

## 1. SYSTEM OVERVIEW

### Purpose
Screen and deep-dive equities using 7 academic frameworks grounded in peer-reviewed finance research. Identify multi-bagger candidates (10x–100x potential) with priority on pre-discovery alpha in small/mid-cap markets. An optional exclusion policy can leave companies out of a screen; none is active by default (§11).

### Architecture layers

```
┌─────────────────────────────────────────────────┐
│  CLI LAYER  (Typer + Rich)                       │
│  User instruction gates — hard stops at each     │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│  ORCHESTRATION LAYER                             │
│  screener/pipeline.py + deepdive/orchestrator.py │
│  + overlays/detector.py (passive listener)       │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│  QUANTITATIVE LAYER  (zero AI tokens)            │
│  frameworks/f1–f7.py + overlays/ica|psa|bew.py  │
│  screener/gates.py + screener/proxy_scorer.py    │
│  deepdive/scorecard.py                           │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│  AI LAYER  (Anthropic SDK — qualitative only)    │
│  deepdive/narrative.py                           │
│  Receives pre-computed scorecard JSON            │
│  Returns: bull case, bear case, risk matrix,     │
│  overlay verdicts, composite narrative           │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│  DATA LAYER                                      │
│  data/api/fmp.py + data/api/alpha_vantage.py     │
│  data/cache/manager.py (TTL cache)               │
│  data/models/schema.py (SQLAlchemy ORM)          │
└─────────────────────────────────────────────────┘
```

---

## 2. DATABASE SCHEMA

```sql
-- companies: master ticker registry
CREATE TABLE companies (
    id              INTEGER PRIMARY KEY,
    ticker          TEXT NOT NULL UNIQUE,
    exchange        TEXT NOT NULL,          -- NASDAQ, NYSE, LSE, KOSDAQ, B3
    name            TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    market_cap_usd  REAL,
    currency        TEXT DEFAULT 'USD',
    ipo_date        DATE,
    parent_ticker   TEXT,                   -- for spinoff tracking (PSA overlay)
    listing_type    TEXT,                   -- 'spinoff' | 'demerger' | 'ipo' | 'standard'
    last_screened   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- financials: annual income statement + balance sheet + cash flow
CREATE TABLE financials (
    id                      INTEGER PRIMARY KEY,
    company_id              INTEGER REFERENCES companies(id),
    fiscal_year             INTEGER NOT NULL,
    period                  TEXT NOT NULL,  -- 'annual' | 'ttm'
    revenue                 REAL,
    gross_profit            REAL,
    gross_margin            REAL,
    operating_income        REAL,
    net_income              REAL,
    ebitda                  REAL,
    rd_expense              REAL,
    sga_expense             REAL,
    operating_cash_flow     REAL,
    free_cash_flow          REAL,
    capex                   REAL,
    total_assets            REAL,
    total_equity            REAL,
    total_debt              REAL,
    long_term_debt          REAL,
    cash_and_equivalents    REAL,
    accounts_receivable     REAL,
    current_assets          REAL,
    current_liabilities     REAL,
    shares_outstanding      REAL,
    eps_diluted             REAL,
    revenue_per_share       REAL,
    source                  TEXT DEFAULT 'fmp',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- price_history: weekly OHLCV for momentum calculations
CREATE TABLE price_history (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    date            DATE NOT NULL,
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume          INTEGER,
    adj_close       REAL,
    source          TEXT DEFAULT 'alpha_vantage',
    UNIQUE(company_id, date)
);

-- insider_transactions: Form 4 data
CREATE TABLE insider_transactions (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    filing_date         DATE NOT NULL,
    transaction_date    DATE,
    insider_name        TEXT,
    insider_title       TEXT,
    transaction_type    TEXT,  -- 'P' purchase | 'S' sale | 'A' award
    shares              REAL,
    price_per_share     REAL,
    value_usd           REAL,
    is_open_market      BOOLEAN DEFAULT TRUE,
    form_type           TEXT DEFAULT '4',
    source              TEXT DEFAULT 'fmp'
);

-- analyst_coverage: sell-side analyst count + estimates
CREATE TABLE analyst_coverage (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    as_of_date          DATE NOT NULL,
    analyst_count       INTEGER,
    consensus_rating    TEXT,  -- 'buy' | 'hold' | 'sell'
    price_target_mean   REAL,
    price_target_high   REAL,
    price_target_low    REAL,
    eps_estimate_next_q REAL,
    rev_estimate_next_q REAL,
    source              TEXT DEFAULT 'fmp'
);

-- earnings_history: surprise tracking for PEAD + F3/F4
CREATE TABLE earnings_history (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    fiscal_quarter      TEXT NOT NULL,  -- '2026Q1'
    report_date         DATE,
    eps_actual          REAL,
    eps_estimate        REAL,
    eps_surprise_pct    REAL,
    revenue_actual      REAL,
    revenue_estimate    REAL,
    rev_surprise_pct    REAL,
    source              TEXT DEFAULT 'fmp'
);

-- short_interest: bi-monthly short interest data
CREATE TABLE short_interest (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    settlement_date     DATE NOT NULL,
    short_interest      INTEGER,  -- shares short
    short_pct_float     REAL,
    days_to_cover       REAL,
    float_shares        INTEGER,
    source              TEXT DEFAULT 'fmp'
);

-- institutional_holders: 13F quarterly data
CREATE TABLE institutional_holders (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    report_date         DATE NOT NULL,
    holder_name         TEXT,
    shares_held         INTEGER,
    value_usd           REAL,
    pct_of_shares_out   REAL,
    change_in_shares    INTEGER,  -- positive = buying, negative = selling
    source              TEXT DEFAULT 'fmp'
);

-- framework_scores: computed scores per run
CREATE TABLE framework_scores (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    run_date            DATE NOT NULL,
    mode                TEXT NOT NULL,    -- 'A' | 'B' | 'C' | 'D'
    company_stage       TEXT,             -- 'pre_profitability' | 'mid_cap' | 'established'
    f1_score            REAL,
    f2_score            REAL,
    f3_score            REAL,
    f4_score            REAL,
    f5_score            REAL,
    f6_score            REAL,
    f7_score            REAL,
    composite_score     REAL,
    verdict             TEXT,  -- 'initiate' | 'watchlist' | 'monitor' | 'exclude'
    piotroski_score     INTEGER,
    overlay_ica_run     BOOLEAN DEFAULT FALSE,
    overlay_psa_run     BOOLEAN DEFAULT FALSE,
    overlay_bew_run     BOOLEAN DEFAULT FALSE,
    overlay_notes       TEXT,  -- JSON string of overlay results
    disqualified        BOOLEAN DEFAULT FALSE,
    disqualification_reasons TEXT,  -- JSON array
    scorecard_json      TEXT,  -- full pre-computed scorecard for AI layer
    narrative_json      TEXT,  -- AI-generated narrative sections
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- screener_runs: audit log of screener executions
CREATE TABLE screener_runs (
    id              INTEGER PRIMARY KEY,
    run_date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    region          TEXT,
    market_cap_min  REAL,
    market_cap_max  REAL,
    sector_filter   TEXT,
    ethics_filter   TEXT,                   -- name of the exclusion policy the run used
    mode            TEXT,
    universe_count  INTEGER,
    passed_gates    INTEGER,
    results_json    TEXT  -- full ranked table as JSON
);

-- watchlist: user's active watchlist
CREATE TABLE watchlist (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER REFERENCES companies(id),
    added_date      DATE DEFAULT CURRENT_DATE,
    entry_triggers  TEXT,  -- JSON array of trigger conditions
    stop_loss_note  TEXT,
    role            TEXT,  -- 'core' | 'satellite' | 'monitor'
    notes           TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);
```

---

## 3. API CLIENTS

### 3.1 FMP Client (`data/api/fmp.py`)

```python
# Endpoints to implement — all via https://financialmodelingprep.com/api/v3/

# Financial statements (primary data source)
GET /income-statement/{symbol}?limit=5&apikey={key}
GET /balance-sheet-statement/{symbol}?limit=5&apikey={key}
GET /cash-flow-statement/{symbol}?limit=5&apikey={key}

# Company data
GET /profile/{symbol}?apikey={key}
GET /key-metrics/{symbol}?limit=5&apikey={key}
GET /key-metrics-ttm/{symbol}?apikey={key}
GET /ratios/{symbol}?limit=5&apikey={key}
GET /ratios-ttm/{symbol}?apikey={key}

# Screener
GET /stock-screener?marketCapMoreThan={min}&marketCapLowerThan={max}
    &isEtf=false&isActivelyTrading=true&apikey={key}

# Insider transactions (Form 4)
GET /insider-trading?symbol={symbol}&limit=50&apikey={key}

# Analyst data
GET /analyst-estimates/{symbol}?limit=4&apikey={key}
GET /price-target-summary/{symbol}?apikey={key}
GET /analyst-stock-recommendations/{symbol}?apikey={key}

# Earnings
GET /earnings-surprises/{symbol}?limit=8&apikey={key}
GET /historical/earning_calendar/{symbol}?apikey={key}

# Institutional ownership (13F)
GET /institutional-holder/{symbol}?apikey={key}

# Short interest
GET /historical/shares_float?symbol={symbol}&apikey={key}

# SEC filings
GET /sec_filings/{symbol}?type=10-K&page=0&apikey={key}
```

**Client class structure:**

```python
class FMPClient:
    def __init__(self, api_key: str, cache: CacheManager): ...

    # Returns Pydantic models, raises MissingDataError on None
    async def get_income_statements(self, ticker: str, years: int = 5) -> list[IncomeStatement]: ...
    async def get_balance_sheets(self, ticker: str, years: int = 5) -> list[BalanceSheet]: ...
    async def get_cash_flows(self, ticker: str, years: int = 5) -> list[CashFlow]: ...
    async def get_company_profile(self, ticker: str) -> CompanyProfile: ...
    async def get_key_metrics(self, ticker: str, years: int = 5) -> list[KeyMetrics]: ...
    async def get_insider_transactions(self, ticker: str, limit: int = 50) -> list[InsiderTransaction]: ...
    async def get_earnings_surprises(self, ticker: str, limit: int = 8) -> list[EarningsSurprise]: ...
    async def get_analyst_coverage(self, ticker: str) -> AnalystCoverage: ...
    async def get_short_interest(self, ticker: str) -> list[ShortInterest]: ...
    async def get_institutional_holders(self, ticker: str) -> list[InstitutionalHolder]: ...
    async def screen_universe(self, params: ScreenerParams) -> list[ScreenerResult]: ...
```

### 3.2 Alpha Vantage Client (`data/api/alpha_vantage.py`)

```python
# Endpoints to implement — all via https://www.alphavantage.co/query

# Price history for momentum calculations
GET ?function=TIME_SERIES_WEEKLY_ADJUSTED&symbol={symbol}&apikey={key}

# Earnings data (backup to FMP)
GET ?function=EARNINGS&symbol={symbol}&apikey={key}

# Quote for current price
GET ?function=GLOBAL_QUOTE&symbol={symbol}&apikey={key}
```

**Client class structure:**

```python
class AlphaVantageClient:
    def __init__(self, api_key: str, cache: CacheManager): ...

    async def get_weekly_prices(self, ticker: str, years: int = 3) -> list[WeeklyPrice]: ...
    async def get_current_quote(self, ticker: str) -> Quote: ...
    async def get_earnings(self, ticker: str) -> list[EarningsRecord]: ...
```

---

## 4. SCREENER PIPELINE

### 4.1 Hard Gates (`screener/gates.py`)

Evaluated at Tier 5 for every shortlisted ticker. Each returns
`GateResult(gate_id, severity, passed, reason)`. A ticker is clean only if every
hard gate passes; a soft failure moves it to the flagged tier, still ranked.

```python
G1_policy             # hard: the active exclusion policy's gate(); `none` passes
G2_market_cap         # hard: market cap present (range enforced at Tier 2)
G3_analyst_coverage   # soft: at least one covering analyst
G4_asset_growth       # hard if asset-growth decile 10, soft if decile 9
G5_external_financing # hard if severe equity/debt issuance, soft if mild
G6_piotroski          # soft: Piotroski subset >= 3
G7_momentum           # soft: momentum decile >= 2
```

Exclusion policies are described in §11.

### 4.2 Framework Proxy Scorer (`screener/proxy_scorer.py`)

Lightweight versions of full frameworks for screener efficiency. Each returns a score 0–10.

**F1 Proxy (Pre-Discovery Alpha):**
```
Signal 1: ROA > 0 AND OCF > 0 AND gross margin expanding                → 0–2 pts
Signal 2: 3+ insider open-market buys in last 90 days (Form 4)          → 0–3 pts
Signal 3: analyst count ≤ 5 (use lowest source: Yahoo/TipRanks)         → 0–2 pts
Signal 4: GP/A in sector top 40% (gross_profit / total_assets)          → 0–2 pts
Signal 5: no material equity/debt raise last 12 months (S-1/S-3 check)  → 0–1 pt
```

**F2 Proxy (Momentum):**
```
Signal 1: 6–12 month price return top decile vs universe                 → 0–3 pts
Signal 2: within 5–10% of 52-week high (George-Hwang signal)            → 0–2 pts
Signal 3: current EV/Revenue or P/S below 10yr median                   → 0–2 pts
Signal 4: 12-month momentum still positive (not reversed)                → 0–2 pts
Signal 5: market cap > $300M (liquidity floor — Jegadeesh-Titman)       → 0–1 pt
```

**F3 Proxy (Innovation Compounder):**
```
Signal 1: gross margin expanded ≥200bps/year over last 2 years           → 0–2 pts
Signal 2: R&D/Revenue ratio 15–35% (sweet spot)                         → 0–2 pts
Signal 3: patents filed or major product/contract wins (news check)      → 0–2 pts
Signal 4: ≥2 consecutive quarterly revenue beats vs consensus            → 0–2 pts
Signal 5: forward revenue estimates revised upward last 90 days          → 0–2 pts
```

**F4 Proxy (Stealth Accumulation):**
```
Signal 1: short interest declining from >8% → <5% over 2–3 quarters     → 0–2 pts
Signal 2: 13F institutional holder count +10% over 3 quarters            → 0–2 pts
Signal 3: sequential quarterly EPS acceleration (3 quarters)             → 0–2 pts
Signal 4: revenue beat consensus for ≥2 consecutive quarters             → 0–2 pts
Signal 5: options put/call ratio declining vs sector peers               → 0–2 pts
```

**F5 Proxy (Growth Quality):**
```
Signal 1: revenue CAGR > 10% (3-year)                                   → 0–1 pt
Signal 2: FCF margin > 20% (TTM)                                         → 0–2 pts
Signal 3: ROIC > 15% OR GP/A in sector top 40%                          → 0–2 pts
Signal 4: debt/EBITDA < 2.0x                                             → 0–1 pt
Signal 5: buyback yield 2–5% (trailing 12m buybacks / market cap)        → 0–1 pt
Signal 6: CEO tenure ≥5 years OR founder-CEO with >5% equity stake       → 0–3 pts
```

**F6 Proxy (Platform Dominator — Mode C only):**
```
Academic anchors (60%):
Signal 1: founder-CEO with >5% equity stake (Fahlenbrach 2009)          → 0–2 pts
Signal 2: top customer relationship > 3 years + concentration (Patatoukas) → 0–2 pts
Signal 3: GP/A in sector top 40% (Novy-Marx 2013)                       → 0–2 pts

Practitioner heuristics ◯ (40% — confirmatory only):
Signal 4: recurring revenue > 70% OR estimated NRR > 110%               → 0–1 pt
Signal 5: Rule of 40 ≥ 35 (growth_rate + fcf_margin)                    → 0–1 pt
Signal 6: GRR > 90% OR net customer churn < 3%                          → 0–1 pt
Signal 7: identifiable network effects / switching costs / regulatory moat → 0–1 pt
```

**F7 Proxy (Smart Beta Timing — Mode C only, contested):**
```
Signal 1: sector EV/Revenue z-score < −1.0 vs 20yr history              → 0–3 pts
Signal 2: P/B z-score < −1.0 vs 20yr history                           → 0–2 pts
Signal 3: peer-relative valuation in cheapest quartile                   → 0–2 pts
Signal 4: mean-reversion setup vs broader market (52wk drawdown > 30%)  → 0–3 pts

ALWAYS append disclaimer: "F7 rests on contested academic ground —
Arnott (pro-timing) vs Asness/AQR (anti-timing). Weight ≤ 0.10."
```

### 4.3 Screener Pipeline (`screener/pipeline.py`)

```
run_screener(params: ScreenerParams, mode: ScoringMode) -> ScreenerOutput

Step 1: Fetch universe from FMP stock-screener endpoint
Step 2: Apply 7 hard gates sequentially → annotate failures
Step 3: Score remaining tickers on frameworks in selected mode
Step 4: Detect overlay triggers passively (no execution)
Step 5: Rank by total score descending
Step 6: Tier segregation: Clean (all gates pass) | Flagged (gate trip)
Step 7: Persist results to screener_runs table
Step 8: Return ScreenerOutput (ranked table + tier summary)
```

**Output format:**
```python
@dataclass
class ScreenerOutput:
    run_date: datetime
    mode: ScoringMode
    params: ScreenerParams
    universe_count: int
    gate_funnel: dict[str, int]          # count at each gate
    ranked_tickers: list[ScoredTicker]   # sorted by total score
    clean_tier: list[ScoredTicker]       # all gates passed
    flagged_tier: list[ScoredTicker]     # gate trip annotated
    pattern_observation: str             # 1–2 sentences on top-5 pattern
    overlay_triggers_detected: list[OverlayTrigger]  # passive — NOT executed
```

### 4.4 Composite Score Weights

**Mode A (F1, F2, F3 — equal weights):**
```python
composite = (f1 + f2 + f3) / 3
```

**Mode B stage weights (F1–F5):**
```python
WEIGHTS_B = {
    "pre_profitability": {"f1": 0.30, "f2": 0.10, "f3": 0.30, "f4": 0.15, "f5": 0.15},
    "mid_cap":           {"f1": 0.20, "f2": 0.20, "f3": 0.20, "f4": 0.15, "f5": 0.25},
    "established":       {"f1": 0.15, "f2": 0.20, "f3": 0.10, "f4": 0.15, "f5": 0.40},
}
```

**Mode C stage weights (F1–F7):**
```python
WEIGHTS_C = {
    "pre_profitability": {"f1": 0.25, "f2": 0.10, "f3": 0.25, "f4": 0.10, "f5": 0.05, "f6": 0.15, "f7": 0.10},
    "mid_cap":           {"f1": 0.15, "f2": 0.15, "f3": 0.15, "f4": 0.10, "f5": 0.20, "f6": 0.10, "f7": 0.15},
    "established":       {"f1": 0.10, "f2": 0.20, "f3": 0.05, "f4": 0.10, "f5": 0.30, "f6": 0.05, "f7": 0.20},
}
```

**Verdict thresholds:**
```python
VERDICTS = {
    "initiate":   (7.0, 10.0),
    "watchlist":  (5.0, 6.99),
    "monitor":    (3.0, 4.99),
    "exclude":    (0.0, 2.99),
}
```

---

## 5. FULL FRAMEWORK IMPLEMENTATIONS

### F1 — Pre-Discovery Alpha (`frameworks/f1_pre_discovery.py`)

**Piotroski F-Score (9 binary signals):**

```python
# PROFITABILITY GROUP (4 signals)
P1_roa_positive        = net_income / total_assets > 0
P2_ocf_positive        = operating_cash_flow > 0
P3_roa_increasing      = current_roa > prior_roa
P4_accruals_low        = (operating_cash_flow / total_assets) > (net_income / total_assets)

# LEVERAGE / LIQUIDITY / FUNDING GROUP (3 signals)
L5_lt_debt_decreasing  = current_lt_debt_ratio < prior_lt_debt_ratio
                         # lt_debt_ratio = long_term_debt / avg_total_assets
L6_current_ratio_up    = current_current_ratio > prior_current_ratio
                         # current_ratio = current_assets / current_liabilities
L7_no_new_shares       = current_shares_outstanding <= prior_shares_outstanding * 1.02
                         # 2% tolerance for small option exercises

# OPERATING EFFICIENCY GROUP (2 signals)
O8_gross_margin_up     = current_gross_margin > prior_gross_margin
O9_asset_turnover_up   = (current_revenue / current_avg_assets) > (prior_revenue / prior_avg_assets)

f_score = sum([P1, P2, P3, P4, L5, L6, L7, O8, O9])
# Interpretation: 8–9 = strong, 7 = good, 0–2 = short candidate
```

**Sloan Accruals (quality check):**
```python
accruals_ratio = (net_income - operating_cash_flow) / avg_total_assets
# Negative = cash earnings exceed GAAP earnings = HIGH QUALITY
# Positive and large = earnings quality concern
```

**Gross Profitability (Novy-Marx 2013):**
```python
gp_a = gross_profit / total_assets
# Compute sector percentile ranking
# Target: top 40% of sector
```

**Insider Cluster Check (Lakonishok-Lee 2001):**
```python
# Scan Form 4 data: last 90 days
# Count unique insiders with transaction_type='P' AND is_open_market=True
# Threshold: >= 3 insiders = cluster buy signal
# Note: predictive in small firms only (market_cap < $2B)
```

**Analyst Coverage (Hong-Lim-Stein 2000):**
```python
# Source from FMP analyst-estimates endpoint
# Use LOWEST count across Yahoo Finance / TipRanks / FMP
# Threshold: <= 3 analysts = neglect premium
```

**External Financing (Bradshaw-Richardson-Sloan 2006):**
```python
# Flag if equity issued > 5% of market cap in last 12 months
# Check S-1, S-3 filings via FMP SEC filings endpoint
# Flag if net debt issuance > 20% of prior year debt
```

**Asset Growth (Cooper-Gulen-Schill 2008):**
```python
asset_growth = (current_total_assets - prior_total_assets) / prior_total_assets
# Top decile (>25% growth) = disqualification flag
# Bottom decile (<5% growth) = positive signal
```

---

### F2 — Momentum + Mean Reversion (`frameworks/f2_momentum.py`)

```python
# Price returns (from Alpha Vantage weekly adjusted)
return_6m   = (current_price - price_26wk_ago) / price_26wk_ago
return_12m  = (current_price - price_52wk_ago) / price_52wk_ago
return_1m   = (current_price - price_4wk_ago) / price_4wk_ago  # skip (J-T skip-1-month)

# Adjusted momentum (Jegadeesh-Titman skip-1-month convention)
momentum_signal = return_12m excluding last month (use 2–12 month window)

# 52-week high proximity (George-Hwang 2004)
pct_from_52wk_high = (price_52wk_high - current_price) / price_52wk_high
near_52wk_high     = pct_from_52wk_high <= 0.10  # within 10% = bullish signal

# Valuation z-score (vs 10yr history from FMP key-metrics)
ev_revenue_history = [ev_revenue_year_N ... ev_revenue_year_0]  # 10yr
z_score_ev_revenue = (current_ev_revenue - mean(history)) / std(history)
# z < -1.0 = historically cheap

# PEAD proxy (Bernard-Thomas 1989)
last_2_earnings_surprises = earnings_history[-2:]
pead_positive = all(s.eps_surprise_pct > 0 for s in last_2_earnings_surprises)
pead_negative = all(s.eps_surprise_pct < 0 for s in last_2_earnings_surprises)
```

---

### F3 — Innovation Compounder (`frameworks/f3_innovation.py`)

```python
# Gross margin trajectory (≥200bps/year for 2+ years)
gm_changes = [
    financials[i].gross_margin - financials[i+1].gross_margin
    for i in range(min(4, len(financials)-1))
]
avg_annual_gm_expansion = mean(gm_changes)  # target: >= 0.02 (200bps)

# R&D intensity (sweet spot 15–35%)
rd_intensity = rd_expense / revenue  # target: 0.15 <= x <= 0.35

# Revenue surprise streak (Jegadeesh-Livnat 2006)
surprise_streak = count consecutive quarters with rev_surprise_pct > 0

# Estimate revision trend
# Compare current quarter estimates to 90 days ago
# Positive revision = estimate moving up

# Innovative Efficiency proxy (Hirshleifer-Hsu-Li 2013)
# Full EMI requires patent citation data (PatStat/USPTO)
# Proxy: patents_filed / (rd_expense / 1M)
# If patent data unavailable: flag as data gap, skip signal
```

---

### F4 — Stealth Accumulation (`frameworks/f4_stealth.py`)

```python
# Short interest trajectory (Desai et al. 2002, Boehmer et al. 2008)
si_history = short_interest[-6:]  # last 6 bi-monthly readings
si_current = si_history[-1].short_pct_float
si_peak    = max(s.short_pct_float for s in si_history)
si_declining = si_peak > 0.08 and si_current < 0.05  # high → low transition

# 13F institutional holder count (conviction filter — Cohen-Polk-Silli 2010)
holder_counts = [
    len(institutional_holders_on_date(q)) for q in last_4_quarters
]
holder_count_increasing = holder_counts[-1] > holder_counts[0] * 1.10  # +10%

# Earnings acceleration (Chan-Jegadeesh-Lakonishok 1996)
eps_sequence = [e.eps_actual for e in earnings_history[-4:]]
eps_accelerating = all(
    eps_sequence[i] > eps_sequence[i-1]
    for i in range(1, len(eps_sequence))
)

# Revenue beat streak
rev_beat_streak = count consecutive quarters with rev_surprise_pct > 0

# Options signal (Pan-Poteshman 2006, Johnson-So 2012)
# If options data available via CBOE/Market Chameleon:
put_call_ratio = put_volume / call_volume  # low = bullish
# If unavailable: flag as data gap
```

---

### F5 — Growth Quality + Capital Allocation (`frameworks/f5_growth_quality.py`)

```python
# Revenue CAGR 3-year
cagr_3yr = (revenue_current / revenue_3yr_ago) ** (1/3) - 1
# Threshold: > 0.10 (heuristic ◯)

# FCF margin
fcf_margin = free_cash_flow / revenue
# Threshold: > 0.20 (heuristic ◯)

# ROIC (primary) — with ICA overlay trigger check
nopat   = operating_income * (1 - effective_tax_rate)
invested_capital = total_equity + total_debt - cash_and_equivalents
roic    = nopat / invested_capital
# Threshold: > 0.15
# TRIGGER ICA OVERLAY if roic < 0.15 AND (rd_intensity > 0.10 OR sector in innovation_sectors)

# GP/A (validated proxy — Novy-Marx ★★★)
gp_a = gross_profit / total_assets

# Debt/EBITDA
debt_ebitda = total_debt / ebitda
# Threshold: < 2.0 (heuristic ◯)

# Buyback yield
buyback_yield = share_repurchases_ttm / market_cap
# Threshold: 0.02–0.05 (heuristic ◯)

# CEO assessment (Fahlenbrach 2009 ★★)
ceo_tenure_years = (today - ceo_start_date).days / 365
is_founder_ceo   = ceo_is_founder
ceo_equity_pct   = ceo_shares_owned / shares_outstanding
# Threshold: tenure >= 5 OR (founder AND equity > 0.05)
```

---

### F6 — Platform Dominator (`frameworks/f6_platform.py`)

**Academic anchors (60% of score):**

```python
# Founder-CEO equity (Fahlenbrach 2009 ★★ — documented 4.4–8.3% premium)
founder_ceo_signal = is_founder_ceo AND ceo_equity_pct > 0.05

# Customer concentration — mature relationship (Patatoukas 2012 ★★★)
# Positive effect after 3+ years of relationship
# Source from 10-K: "largest customer" or "significant customers" disclosure
top_customer_pct        = parse_10k_customer_concentration()
relationship_years      = estimate_from_10k_history()
concentration_signal    = (0.15 <= top_customer_pct <= 0.30) AND relationship_years >= 3

# Gross profitability (Novy-Marx 2013 ★★★)
gp_a_signal = gp_a_percentile >= 60  # top 40% of sector
```

**Practitioner heuristics ◯ (40% of score — flagged, confirmatory only):**

```python
# NRR (not peer-reviewed — practitioner metric)
nrr_signal = estimated_nrr >= 1.10  # > 110%

# Rule of 40 (Brad Feld blog post — ◯)
rule_of_40 = revenue_growth_rate + fcf_margin
rule_of_40_signal = rule_of_40 >= 35

# GRR proxy
grr_proxy  = 1 - net_revenue_churn_rate
grr_signal = grr_proxy >= 0.90

# Switching costs / network effects (qualitative — scored by AI layer)
# Flag for AI narrative, not computed in Python
```

---

### F7 — Smart Beta Timing (`frameworks/f7_smart_beta.py`)

```python
# CONTESTED — Arnott (pro) vs Asness/AQR (anti). Always flag.
# Skip if < 36 months listed history (triggers PSA overlay check).

# Valuation z-scores (requires 10–20yr history)
def compute_z_score(current: float, history: list[float]) -> float:
    return (current - mean(history)) / std(history)

ev_revenue_z = compute_z_score(current_ev_revenue, ev_revenue_10yr)
pb_z         = compute_z_score(current_pb, pb_10yr)

# Peer-relative valuation
sector_ev_revenue_median = sector_percentile(current_ev_revenue, 0.25)
cheap_vs_peers = current_ev_revenue < sector_ev_revenue_median

# ALWAYS append to output:
F7_DISCLAIMER = (
    "F7 rests on contested academic ground. Arnott (Research Affiliates) "
    "argues valuation z-scores predict factor returns; Asness (AQR) argues "
    "the effect is exaggerated and inapplicable. AQR manages $100B+ on the "
    "opposite view. Score weighted ≤ 0.10. Use with explicit knowledge of dispute."
)
```

---

## 6. DIAGNOSTIC OVERLAYS

### 6.1 Trigger Detector (`overlays/detector.py`)

Passive scanner — zero token cost. Runs silently after each framework. Returns trigger list, never executes overlays.

```python
@dataclass
class OverlayTrigger:
    overlay_type: Literal["ICA", "PSA", "BEW"]
    trigger_id: str        # e.g., "ICA-1", "PSA-3", "BEW-2"
    trigger_condition: str # human-readable explanation
    relevant_numbers: dict # the specific values that triggered it
    framework_section: str # which framework to append output to

class OverlayDetector:
    def scan(self, scorecard: ScorecardData) -> list[OverlayTrigger]: ...
```

**ICA trigger conditions:**
```python
ICA_1 = scorecard.f5_roic < 0.15 and scorecard.rd_intensity >= 0.10
ICA_2 = scorecard.f5_roic < 0.15 and scorecard.sector in INNOVATION_SECTORS
ICA_3 = scorecard.gaap_net_income < 0 and (
    scorecard.operating_cash_flow / abs(scorecard.gaap_net_income) > 2.0
)
ICA_4 = (scorecard.pb_ratio > 4.0
         and scorecard.gp_a_percentile >= 60
         and scorecard.rd_intensity > 0.15)
# ICA_5: user language trigger — handled in CLI layer
```

**PSA trigger conditions:**
```python
PSA_1 = (
    scorecard.months_since_listing < 36
    and scorecard.listing_type in ("spinoff", "demerger", "carve_out")
)
PSA_2 = scorecard.financials_comparable == False  # flagged from 10-K parsing
PSA_3 = scorecard.f7_skipped_reason == "insufficient_history"
PSA_4 = scorecard.f1_piotroski_score <= 4 and scorecard.f1_ocf_positive and scorecard.gp_a_percentile >= 60
# PSA_5: user language trigger — handled in CLI layer
```

**BEW trigger conditions:**
```python
BEW_1 = (
    scorecard.f3_score >= 7.0
    and scorecard.f6_score >= 7.0
    and scorecard.ev_revenue_z_score > 0  # expensive by own history
)
BEW_2 = (
    scorecard.f1_score >= 6.0
    and scorecard.f3_score >= 6.0
    and scorecard.ev_revenue_vs_sector_median > 1.0  # above sector median
)
BEW_3 = scorecard.return_12m > 0.50  # compounded >50% — user asking hold/add
BEW_5 = (
    scorecard.idiosyncratic_vol > 0.30
    and scorecard.rd_intensity >= 0.33  # top tercile
    and scorecard.market_cap_usd < 2_000_000_000
)
# BEW_4: user language trigger — handled in CLI layer
```

### 6.2 ICA Overlay (`overlays/ica.py`)

```python
def run_ica(financials: list[FinancialData], g: float) -> ICAResult:
    """
    Peters & Taylor (2017) JFE ★★★
    Eisfeldt & Papanikolaou (2013) JF ★★★
    """
    # Step 1: Build knowledge capital (R&D capitalisation)
    # KK_0 = rd_expense_0 / (g + 0.15)
    kk = [financials[-1].rd_expense / (g + 0.15)]
    for f in reversed(financials[:-1]):
        kk.append((1 - 0.15) * kk[-1] + f.rd_expense)

    # Step 2: Build organisational capital (SG&A fraction)
    # OC_0 = 0.25 * sga_0 / (g + 0.20)
    oc = [0.25 * financials[-1].sga_expense / (g + 0.20)]
    for f in reversed(financials[:-1]):
        oc.append((1 - 0.20) * oc[-1] + 0.25 * f.sga_expense)

    total_intangible_stack = kk[-1] + oc[-1]

    # Step 3: Adjusted book equity and ROIC
    adj_book_equity    = financials[0].total_equity + total_intangible_stack
    adj_nopat          = (financials[0].operating_income * (1 - effective_tax_rate)
                          + financials[0].rd_expense
                          - 0.15 * kk[-2])  # amortise prior period KK
    adj_invested_capital = (financials[0].total_equity
                            + financials[0].total_debt
                            - financials[0].cash
                            + total_intangible_stack)
    adj_roic = adj_nopat / adj_invested_capital

    return ICAResult(
        knowledge_capital=kk[-1],
        organisational_capital=oc[-1],
        total_intangible_stack=total_intangible_stack,
        gaap_roic=gaap_roic,
        adjusted_roic=adj_roic,
        adjusted_pb=market_cap / adj_book_equity,
        f5_verdict_revised="pass" if adj_roic > 0.15 else "fail",
    )
```

### 6.3 PSA Overlay (`overlays/psa.py`)

```python
def run_psa(company: CompanyData, financials: list[FinancialData],
            industry_medians: dict) -> PSAResult:
    """
    Cusatis, Miles & Woolridge (1993) JFE ★★★
    Desai & Jain (1999) JFE ★★★
    """
    # Step 1: Adjusted Piotroski
    # Replace YoY change signals (3, 5, 6, 8, 9) with industry-median comparatives
    adjusted_score = compute_piotroski_psa_adjusted(financials, industry_medians)

    # Step 2: Structural mispricing (4 binary checks)
    psa_a = company.parent_sector != company.sector  # forced selling
    psa_b = company.market_cap < company.parent_market_cap * 0.10  # size mandate
    psa_c = company.analyst_count < 3  # information asymmetry intact
    psa_d = company.ejected_from_index or not company.in_major_index  # tracker selling

    mispricing_score = sum([psa_a, psa_b, psa_c, psa_d])

    # Step 3: Desai-Jain focus test
    same_sic2 = company.sic_2digit == company.parent_sic_2digit
    focus_type = "focus_neutral" if same_sic2 else "focus_increasing"
    documented_excess_return = 0.18 if same_sic2 else 0.33

    return PSAResult(
        original_piotroski=original_score,
        adjusted_piotroski=adjusted_score,
        structural_mispricing=mispricing_score,
        psa_checks={"A": psa_a, "B": psa_b, "C": psa_c, "D": psa_d},
        focus_type=focus_type,
        documented_excess_return=documented_excess_return,
    )
```

### 6.4 BEW Overlay (`overlays/bew.py`)

```python
def run_bew(company: CompanyData, scorecard: ScorecardData) -> BEWResult:
    """
    Bessembinder (2018) JFE ★★★
    Bessembinder et al. (2019) JFE ★★★
    """
    checks = {
        "A_small_at_acquisition":  company.market_cap_usd < 2_000_000_000,
        "B_high_idio_vol":         scorecard.idiosyncratic_vol > 0.30,
        "C_positive_skewness":     scorecard.return_skewness_3yr > 0,
        "D_growth_industry":       company.sector in BESSEMBINDER_GROWTH_SECTORS,
        "E_not_cheap":             scorecard.ev_revenue > scorecard.sector_median_ev_revenue,
        "F_long_runway":           (company.tam_estimate / company.revenue) > 20 if company.tam_estimate else None,
        "G_innovation_compounding": scorecard.f3_score >= 7.0 or scorecard.avg_gm_expansion >= 0.02,
    }

    score = sum(v for v in checks.values() if v is True)

    if score >= 6:
        verdict = "EXTREME_WINNER_CANDIDATE"
        hold_period = "5–15 years minimum"
        concentration_note = "Concentration is necessary — 2% position in 10x = 0.2% portfolio return"
    elif score >= 4:
        verdict = "PARTIAL_PROFILE"
        hold_period = "3–7 years"
        concentration_note = "Conventional valuation discipline applies alongside BEW"
    else:
        verdict = "CONVENTIONAL_VALUATION_APPLIES"
        hold_period = "Standard"
        concentration_note = "Standard position sizing"

    return BEWResult(
        checks=checks,
        score=score,
        verdict=verdict,
        hold_period=hold_period,
        concentration_note=concentration_note,
    )
```

---

## 7. DEEP DIVE ORCHESTRATOR

### 7.1 Scorecard Builder (`deepdive/scorecard.py`)

Pre-computes all quantitative signals into a structured JSON before any AI call. This is what gets sent to Claude — not raw filings.

```python
@dataclass
class ScorecardData:
    # Company metadata
    ticker: str
    name: str
    exchange: str
    sector: str
    market_cap_usd: float
    price: float
    ev: float
    listing_date: date
    listing_type: str

    # F1 signals
    piotroski_score: int
    piotroski_signals: dict[str, bool]  # all 9 signals
    sloan_accruals_ratio: float
    gp_a: float
    gp_a_sector_percentile: float
    insider_cluster_90d: int  # count of unique open-market buyers
    analyst_count: int
    asset_growth_yoy: float
    asset_growth_decile: int  # 1=lowest, 10=highest
    external_financing_flag: bool

    # F2 signals
    return_6m: float
    return_12m: float
    momentum_decile: int  # vs universe
    pct_from_52wk_high: float
    near_52wk_high: bool
    ev_revenue_z_score: float | None
    pb_z_score: float | None
    pead_direction: str  # 'positive' | 'negative' | 'mixed'

    # F3 signals
    gross_margins: list[float]  # 5 years
    avg_gm_expansion_bps: float
    rd_intensity: float
    rd_intensity_in_range: bool  # 15–35%
    revenue_surprise_streak: int
    estimate_revision_direction: str  # 'up' | 'down' | 'flat'

    # F4 signals
    si_current: float
    si_peak_6m: float
    si_declining: bool
    institutional_holder_count_trend: list[int]  # 4 quarters
    eps_sequence: list[float]  # 4 quarters
    eps_accelerating: bool
    revenue_beat_streak: int

    # F5 signals
    revenue_cagr_3yr: float
    fcf_margin: float
    gaap_roic: float
    gp_a_top40: bool
    debt_ebitda: float
    buyback_yield: float
    ceo_tenure_years: float
    is_founder_ceo: bool
    ceo_equity_pct: float

    # F6 signals (Mode C)
    founder_ceo_equity_signal: bool
    customer_concentration_pct: float | None
    customer_relationship_years: float | None
    estimated_nrr: float | None
    rule_of_40: float
    estimated_grr: float | None

    # F7 signals (Mode C)
    ev_revenue_10yr_history: list[float] | None
    pb_10yr_history: list[float] | None
    ev_revenue_z: float | None
    pb_z: float | None

    # Framework scores (computed)
    f1_score: float
    f2_score: float
    f3_score: float
    f4_score: float | None
    f5_score: float | None
    f6_score: float | None
    f7_score: float | None
    composite_score: float
    verdict: str

    # Overlay trigger detection results
    overlay_triggers: list[OverlayTrigger]
    overlay_results: dict  # populated only if overlays were run

    # Disqualification
    disqualified: bool
    disqualification_reasons: list[str]

    # Data gaps (fields that couldn't be sourced)
    data_gaps: list[str]
    idiosyncratic_vol: float | None
    return_skewness_3yr: float | None
    tam_estimate: float | None
```

### 7.2 Narrative Generator (`deepdive/narrative.py`)

The ONLY module that calls Anthropic SDK. Receives pre-computed `ScorecardData`, returns structured narrative sections.

```python
SYSTEM_PROMPT = """
You are an investment research analyst applying peer-reviewed academic frameworks
to pre-computed quantitative scorecards. You receive a fully computed scorecard
as JSON — do not recompute numbers, do not assume missing data.

Your job is qualitative analysis only:
- Business model assessment and competitive moat
- CEO track record narrative
- Bull case / Bear case (max 200 words each)
- Risk matrix with probability and severity ratings
- Entry triggers and stop-loss indicators
- Overlay qualitative verdicts (only if overlay_results present in scorecard)
- Final composite narrative (max 150 words)

Rules:
- No data → No conclusion. If a field is null, state the data gap explicitly.
- Never dress inference up as analysis.
- Always state the framework mode used and its academic confidence level.
- Acknowledge replication crisis context: realistic net alpha is 2–5%, not 15%+.
"""

async def generate_narrative(
    scorecard: ScorecardData,
    mode: ScoringMode,
    overlay_results: dict | None = None,
) -> NarrativeOutput:
    client = Anthropic()
    response = await client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Generate deep-dive narrative for:\n{scorecard.model_dump_json(indent=2)}"
        }]
    )
    return parse_narrative_response(response)
```

---

## 8. CLI INTERFACE

### Commands (`cli/main.py` via Typer)

```bash
# Stage 0: parameter elicitation
$ invest screen

# Outputs prompt asking for region, market cap, sector, exclusion policy, mode
# HARD STOP — waits for user input

# Stage 1: run screener (after parameters confirmed)
$ invest screen --region us --cap-min 50M --cap-max 10B --mode B

# Stage 2: tier-1 deep dive on selected tickers
$ invest dive INTA PINE --tier 1

# Stage 3: full tier-2 deep dive
$ invest dive INTA --tier 2 --mode C

# Overlay management
$ invest overlay run INTA --type ICA    # manually trigger overlay
$ invest overlay status INTA             # show detected triggers

# Watchlist management
$ invest watchlist add INTA --role core
$ invest watchlist list
$ invest watchlist remove INTA

# Scheduler
$ invest scheduler add-job quarterly-screener --cron "0 9 15 */3 *"
$ invest scheduler list
$ invest scheduler remove-job quarterly-screener

# Data management
$ invest data refresh INTA               # force cache invalidation + re-fetch
$ invest data gaps INTA                  # show all data gaps for ticker
```

### Rich CLI output format

```python
# Screener output: Rich Table with colour-coded tiers
# - Green: clean tier, score >= threshold
# - Yellow: borderline / flagged tier
# - Red: disqualified (show reason)

# Deep-dive output: Rich Panels per framework
# - Panel title: "F1 — Pre-Discovery Alpha | Score: 7.5/10"
# - Panel content: signal table + verdict
# - Overlay trigger: ⚡ yellow panel asking Y/N

# Overlay prompt format:
console.print(Panel(
    f"[yellow]⚡ {trigger.overlay_type} TRIGGER FIRED[/yellow]\n"
    f"Condition: {trigger.trigger_id} — {trigger.trigger_condition}\n\n"
    f"Run {trigger.overlay_type} overlay? (~{cost} tokens) [Y/N]",
    border_style="yellow"
))
```

---

## 9. SCHEDULER JOBS

### Job definitions (`scheduler/jobs.py`)

```python
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

# Quarterly screener re-run (mid-month after quarter-end filings)
# Suggested: mid-Feb, mid-May, mid-Aug, mid-Nov
@scheduler.scheduled_job('cron', month='2,5,8,11', day='15', hour='9', minute='0')
def quarterly_screener():
    """Re-run screener with last saved parameters. No deep dive."""
    params = load_last_screener_params()
    result = run_screener(params)
    notify_user(f"Quarterly screener complete: {len(result.clean_tier)} tickers in clean tier")

# Mid-quarter refresh: short interest + 13F flow only (no re-scoring)
@scheduler.scheduled_job('cron', day='1', hour='8', minute='0')
def monthly_signal_refresh():
    """Refresh short interest and 13F holder counts for watchlist tickers."""
    watchlist = load_active_watchlist()
    for ticker in watchlist:
        refresh_short_interest(ticker)
        refresh_institutional_holders(ticker)

# Annual re-run (post 10-K filing season)
@scheduler.scheduled_job('cron', month='3', day='15', hour='9', minute='0')
def annual_full_rerun():
    """Full screener + rescore all watchlist tickers on updated annual financials."""
    pass
```

**Important:** Scheduler jobs are **registered explicitly by the user** via `invest scheduler add-job`. They do NOT start on app launch. No job runs without user registration.

---

## 10. UNIVERSAL DISQUALIFICATION CHECKS

Run on every ticker regardless of framework mode.

```python
DISQUALIFICATION_CHECKS = {
    "heavy_external_financing": lambda d: (
        d.equity_issued_12m > d.market_cap * 0.05
        or d.net_debt_issued > d.prior_total_debt * 0.20
    ),
    "asset_growth_top_decile": lambda d: d.asset_growth_decile >= 9,
    "negative_gross_profitability": lambda d: d.gp_a < 0,
    "zero_insider_ownership": lambda d: d.insider_ownership_pct < 0.01,
    "market_cap_below_liquidity_floor": lambda d: d.market_cap_usd < 300_000_000,
    "material_weakness_icfr": lambda d: d.has_material_weakness,
    "negative_gross_margin": lambda d: d.gross_margin < 0,
}
# Any True = disqualified with reason logged
```

---

## 11. EXCLUSION POLICIES (optional)

Every company that clears the data and quality gates is scored the same way.
An exclusion policy, registered by an add-on package and selected with
`EXCLUSION_POLICY` (default `none`), can leave companies out:

- at Tier 3 from sector and industry (`classify`), before fundamentals are fetched;
- at gate G1 from persisted fundamentals (`gate`), as a hard gate failure;
- in warehouse queries and task selectors (`eligible`, `not_excluded`).

A policy never changes a framework score, is deterministic (no network or LLM
calls), fails closed on missing inputs, and records every exclusion with its
reason in `exclusion_verdicts`. A policy verdict is the output of a rule, not a
certification of anything. Contract and registration: `screener/policies/README.md`.

---

## 12. ERROR HANDLING

```python
# Custom exceptions
class MissingDataError(Exception):
    """Raised when required data is unavailable from APIs."""
    def __init__(self, field: str, endpoint: str, ticker: str):
        self.field = field
        self.endpoint = endpoint
        self.ticker = ticker
        super().__init__(
            f"Missing '{field}' for {ticker}. "
            f"Source from: {endpoint}"
        )

class APIRateLimitError(Exception):
    """Raised when API rate limit hit — triggers backoff."""

class InsufficientHistoryError(Exception):
    """Raised when <2yr comparable financials available (PSA trigger candidate)."""
    # Automatically registers PSA overlay trigger when raised in F1

class OverlayNotConfirmedError(Exception):
    """Raised if overlay computation attempted without user confirmation."""
```

---

## 13. TESTING STRATEGY

```
tests/
├── conftest.py                     ← shared fixtures, mock API responses
├── fixtures/
│   ├── sample_financials.json      ← FMP response mocks
│   ├── sample_prices.json          ← Alpha Vantage response mocks
│   └── sample_insiders.json        ← Form 4 data mocks
├── test_frameworks/
│   ├── test_f1_piotroski.py        ← all 9 signals with known inputs/outputs
│   ├── test_f2_momentum.py
│   ├── test_f3_innovation.py
│   ├── test_f4_stealth.py
│   ├── test_f5_growth_quality.py
│   ├── test_f6_platform.py
│   └── test_f7_smart_beta.py
├── test_screener/
│   ├── test_gates.py               ← each gate with pass/fail cases
│   ├── test_proxy_scorer.py
│   └── test_pipeline.py
├── test_overlays/
│   ├── test_detector.py            ← trigger condition unit tests
│   ├── test_ica.py                 ← Peters-Taylor computation accuracy
│   ├── test_psa.py
│   └── test_bew.py
└── test_deepdive/
    ├── test_scorecard.py           ← scorecard builder integration test
    └── test_narrative.py           ← mock Anthropic response parsing
```

**Key test principle:** Every framework function has a test with known financial inputs and expected output values. No framework logic is tested against live APIs — all API calls are mocked.

---

## 14. DEPENDENCIES (`pyproject.toml`)

```toml
[project]
name = "investment-intelligence"
version = "0.1.0"
requires-python = ">=3.11"

[project.dependencies]
httpx = ">=0.27"
tenacity = ">=8.2"              # retry logic for API calls
pydantic = ">=2.7"
pydantic-settings = ">=2.3"
sqlalchemy = ">=2.0"
alembic = ">=1.13"
anthropic = ">=0.28"
apscheduler = ">=3.10"
typer = ">=0.12"
rich = ">=13.7"
python-dotenv = ">=1.0"
aiosqlite = ">=0.20"            # async SQLite driver
pandas = ">=2.2"                # for momentum percentile calculations

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "responses>=0.25",          # HTTP mocking
    "ruff>=0.4",
    "mypy>=1.10",
]

[project.scripts]
invest = "cli.main:app"
```

---

## 15. SYSTEM LIMITATIONS (encode in code comments)

1. **Piotroski requires 2yr comparable financials** — raises `InsufficientHistoryError` if unavailable, which auto-triggers PSA detector
2. **F7 requires 10–20yr valuation history** — skip with explicit flag if <36 months listed
3. **Exclusion verdicts are rule outputs, not certifications** — a policy reports what its rules matched, with the reason
4. **Insider effect concentrated in small firms** — Lakonishok-Lee: restrict cluster signal weight to companies with market_cap < $2B
5. **Realistic net alpha: 2–5%** — encode this as a constant in output, never claim more
6. **McLean-Pontiff decay** — all alpha numbers are pre-decay gross; surfaced in narrative
7. **F6 and F7 Mode C only** — never compute for Mode A or B runs
8. **Overlays run only when triggered** — ICA / PSA / BEW auto-run on their triggers and add a bonus capped at 1.0 of 10 (DEC-30)
9. **LLM calls in two modules only** — `deepdive/narrative.py` and `deepdive/external_signals.py`; enforced by test

---

*Research purposes only. Not financial advice.*
*Version 1.0 — May 2026*
