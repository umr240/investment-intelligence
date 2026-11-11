# System reference

Reference material for the rules in `CLAUDE.md`: the stack, the layout, how the data layer loads only what a framework needs, the overlay policy, caching, environment variables and rate limits. `CLAUDE.md` holds the rules; this file holds the detail behind them.

## Tech stack

```
Language:        Python 3.11+
Package manager: uv (not pip, not poetry)
Database:        SQLite (dev) → PostgreSQL/Neon (prod) via SQLAlchemy 2.0
ORM:             SQLAlchemy with Alembic migrations
Data sources:    SEC EDGAR (companyfacts.json) — 10yr fundamentals default (override via --years),
                   DEF 14A HTML beneficial ownership tables, XBRL ConcentrationRiskPercentage
                 yfinance — 20yr price history, market cap, ownership %,
                   institutional holders, insider trades, analyst consensus
                 BeautifulSoup4 + regex — DEF 14A HTML parsing, 10-K text patterns
                 Anthropic / OpenAI Python SDKs — ONLY at the call sites allow-listed in
                   tests/test_llm_call_sites.py (ADR-031-A1). OpenAI is the primary
                   provider for narrative + chat; Anthropic is fallback.
                 FMP — screener metadata only (one bulk call per run, ADR-016);
                   optional, and never for per-ticker fundamentals
                 Alpha Vantage — not used
Scheduler:       APScheduler 3.x (BlockingScheduler for CLI daemon)
CLI:             Typer + Rich (tables, panels, progress bars)
HTTP client:     httpx (only via edgartools / yfinance internals)
Config:          python-dotenv + pydantic-settings
Testing:         pytest + pytest-asyncio + respx (mock httpx)
Linting:         ruff
Type checking:   mypy (strict mode)
```

## Project structure

```
investment-intelligence/
├── CLAUDE.md                        ← this file
├── AGENTS.md                        ← pointer here for other coding agents
├── pyproject.toml                   ← uv project file
├── .env.example
├── alembic.ini
├── alembic/
│   └── versions/
│
├── config/
│   ├── __init__.py
│   ├── settings.py                  ← pydantic-settings config
│   └── constants.py                 ← thresholds, weights, mode definitions
│
├── data/
│   ├── __init__.py
│   ├── db.py                        ← SQLAlchemy engine + session factory
│   ├── pipeline.py                  ← data refresh orchestration (deterministic, no LLM)
│   ├── edgar_fetcher.py             ← edgartools wrapper (10-K/10-Q/Form 4/DEF 14A)
│   ├── edgar_text_parser.py         ← regex + BeautifulSoup parser (zero-LLM extraction)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── yfinance_client.py       ← typed yfinance wrapper (snapshot + holders + history)
│   │   ├── fmp_client.py            ← screener metadata only, one bulk call (ADR-016)
│   │   ├── polygon_client.py        ← opt-in plugin source (ADR-019)
│   │   └── _retry.py                ← SEC/HTTP retry helpers
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schema.py                ← SQLAlchemy ORM models
│   │   └── api_models.py            ← Pydantic models for API responses
│   └── cache/
│       ├── __init__.py
│       └── manager.py               ← SQLite-backed TTL cache
│
├── screener/
│   ├── __init__.py
│   ├── gates.py                     ← hard gate filters (7 binary checks)
│   ├── proxy_scorer.py              ← framework proxy scores for screener
│   └── pipeline.py                  ← full screener orchestration
│
├── frameworks/
│   ├── __init__.py
│   ├── base.py                      ← FrameworkResult dataclass + MissingDataError
│   ├── f1_pre_discovery.py          ← Piotroski + insider + neglect + GP/A
│   ├── f2_momentum.py               ← momentum + 52-week-high + PEAD
│   ├── f3_innovation.py             ← GM expansion + R&D intensity + patents
│   ├── f4_stealth.py                ← short interest + 13F + EPS accel
│   ├── f5_growth_quality.py         ← FCF/ROIC/buyback/CEO checklist
│   ├── f6_platform.py               ← Fahlenbrach + Patatoukas + NRR heuristics
│   └── f7_smart_beta.py             ← valuation z-scores (contested — flagged)
│
├── overlays/
│   ├── __init__.py
│   ├── detector.py                  ← passive trigger scanner (zero tokens)
│   ├── ica.py                       ← Intangible Capital Adjustment (Peters-Taylor)
│   ├── psa.py                       ← Post-Spinoff Alpha (Cusatis-Desai-Jain)
│   └── bew.py                       ← Bessembinder Extreme Winners
│
├── deepdive/
│   ├── __init__.py
│   ├── orchestrator.py              ← deep dive flow controller
│   ├── scorecard.py                 ← pre-compute all quant signals → JSON
│   └── narrative.py                 ← Anthropic/OpenAI SDK calls (AI layer only)
│
├── scheduler/
│   ├── __init__.py
│   └── jobs.py                      ← APScheduler job definitions + registry
│
├── cli/
│   ├── __init__.py
│   └── main.py                      ← Typer CLI entrypoint
│
├── valuation/                       ← Damodaran + Greenwald ladders, EPV, reverse DCF
│
├── api/                             ← FastAPI local control plane (ADR-040)
│   └── app.py                       ← thin pass-through over the CLI engine
│
├── frontend/                        ← React + Vite client for the local UI
│
├── mental_models/                   ← the lattice (ADR-024); one file per model
│
├── docs/
│   ├── methodology/                 ← the specifications of record
│   └── QUICKSTART.md
│
├── scripts/                         ← re-runnable tools + ADR evidence probes
│
├── tools/
│   ├── gate/                        ← agentic-kit gate + merge check (gate.toml)
│   └── check_public_text.py         ← impersonal, dash-free public text
│
└── tests/
    ├── conftest.py
    ├── test_frameworks/
    ├── test_screener/
    ├── test_overlays/
    └── fixtures/
        └── sample_financials.json
```

## Framework-aware lazy load

The data layer is **framework-driven, not date-driven**. Each framework
declares what it needs; the orchestrator unions requirements across selected
frameworks; the pipeline fetches only the minimum superset.

```
User runs            invest dive NVDA --frameworks F1
                          ↓
Orchestrator         requirement_for_frameworks(['F1'])
                     → DataRequirement(annual_years=2,
                                        needs_insider_transactions=True,
                                        needs_analyst_coverage=True,
                                        ... all others False)
                          ↓
Pipeline             refresh_ticker(NVDA, requirement=req)
                       Phase 0: ensure Company row, load FinancialSourceLog
                       Phase 1a: year-coverage gate (DB-only)
                                  missing = needed - existing
                                  if missing == ∅: probe submissions.json
                                  if no new accn: SKIP companyfacts entirely
                       Phase 1: parallel asyncio.gather:
                                  - companyfacts (gated, parser keeps only
                                                  missing fiscal years)
                                  - Form 4 (gated by needs_insider_transactions)
                                  - yfinance .info (always — small)
                                  - yfinance .history() (gated by
                                                         price_history_years)
                                  - latest 10-K filing object (gated by
                                                               needs_*_concentration
                                                               / proxy / founder)
                       Phase 2: bulk persistence (single SELECT for dedup,
                                                   then add_all)
                       Phase 3: F6 deterministic signals (gated)
                       Phase 4: derived metrics (buyback_yield)
                          ↓
Frameworks           score_f1(ticker, CompanyDataReader(ticker))
                       reader.annuals(last_n=2)
                       reader.insider_transactions(within_days=90,
                                                    transaction_codes=('P',))
                       reader.latest_analyst_coverage()
                       → FrameworkResult or InsufficientHistoryError
                          ↓
Orchestrator         _check_feasibility (IPO-aware pre-flight)
                       walks DB; marks F2/F7 unfeasible if recent IPO
                       runs feasible frameworks; surfaces unfeasible by reason
                       NEVER crashes the dive
```

### Where things live

| Concern | Module | Public surface |
|---|---|---|
| Per-framework data needs | `frameworks/f{1..7}_*.py` | module-level `DATA_REQUIREMENT = DataRequirement(...)` |
| Requirement protocol | `frameworks/base.py` | `DataRequirement`, `merge_requirements`, `requirement_for_frameworks` |
| Read persistent data | `data/reader.py` | `CompanyDataReader(ticker).annuals(last_n=N)` etc. |
| Fetch / persist | `data/pipeline.py` | `refresh_ticker(ticker, requirement=req)` |
| Bulk SEC fetch | `data/edgar_companyfacts.py` | `parse_companyfacts(payload, keep_only_years=missing)` |
| Deep-dive flow | `deepdive/orchestrator.py` | `run_tier1/2`, `_check_feasibility`, `frameworks_for_mode` |
| Scheduler | `scheduler/jobs.py` | `register_deepdive_job(name, cron, tickers, frameworks=None)` |
| CLI | `cli/main.py` | `invest dive`, `invest data plan`, `invest scheduler add-deepdive` |

### Data contract (do NOT relax)

- `Financial` rows are keyed `(company_id, fiscal_year, period)` where period ∈ {`annual`, `Q1`, `Q2`, `Q3`, `Q4`}.
- Frameworks NEVER touch SQL or import schema directly, always go through `CompanyDataReader`.
- All EDGAR text/HTML extraction is deterministic (regex / BeautifulSoup). The data path is LLM-free; AI is restricted to `deepdive/narrative.py`.
- Missing data → `data_gaps[]` entry, never a hallucinated value.

### Recent IPO graceful degradation

A company with <2 annual filings cannot run F1 (Piotroski needs YoY). Rather than crashing, `_check_feasibility` walks `reader.annual_year_set()` before invoking score functions and marks unfeasible frameworks with reason ("recent IPO / insufficient annual history (needs 2yr, have 1)"). Other frameworks still run.

For the dive command itself:
- `invest dive ABC`: runs all 7; F2/F7 auto-skip on recent IPO
- `invest dive ABC --frameworks F1`: user-defined narrow dive
- `invest dive ABC --mode A`: preset (F1+F2+F3)

## AI layer boundary: call sites and examples


The Anthropic / OpenAI SDKs may be imported only by the modules in `ALLOWED` in
`tests/test_llm_call_sites.py`, which CI enforces. That set is the single source
of truth; adding to it is an ADR amendment (ADR-031 §4.1, ADR-032 §1.5, ADR-031-A1).

| Module | Purpose | When called |
|--------|---------|-------------|
| `deepdive/narrative.py` | **Narrative generation**: qualitative bull/bear/risk narrative for the deep-dive report. Constrained to pre-computed quant metrics, never invents numbers. Renders the DEC-23 hold-philosophy frame (ADR-023 §10). | Only when user explicitly runs `invest score-card TICKER --narrate`. Persists structured JSON to `deepdive_runs.bull_narrative` / `.bear_narrative` / `.risk_factors`. |
| `deepdive/external_signals.py` | **Supplementary signal extraction**: NRR / GRR / ARR / GMV / take-rate from 8-K EX-99.1 earnings releases. Writes to `external_signals` table only, **strictly isolated** from F1-F7 framework scoring (no Financial / Company canonical writes). | Only when user explicitly invokes `/external-signals TICKER` skill (`dangerous: true`: requires confirmation per ADR-032 §2.4). |
| `deepdive/conversation.py` | **Conversational dive**: multi-turn Q&A grounded in the *frozen* `ScorecardView` of one `DeepDiveRun`. Every reply's `numeric_claims` must resolve to a view field path; mismatches surface as guard warnings. | Only when the user types a question into `invest chat TICKER` (default $2 session budget, `--budget`) or the UI "Ask about this dive" box (`POST /dive/{ticker}/chat`, no session budget). Persists every turn, append-only, to `deep_dive_conversations`. |

The data-fetch and screener paths are **fully deterministic**: EDGAR XBRL → regex on 10-K text → BeautifulSoup on DEF 14A HTML → yfinance typed snapshot. There is no LLM fallback in the data layer. A missing value surfaces as a `data_gaps` entry, never a hallucinated number.

> **Personality contract:** the *behaviour* of the LLM call inside `deepdive/narrative.py` is binding-spec'd in **ADR-023, Narrative Personality Spec**. The LLM must reason in the order Inversion → Circle of Competence → Moat Direction → Capital Allocator → Lunch-Eating Test → Probabilistic Base Rate, produce one of `WATCHLIST WITH TRIGGERS` / `EXCLUDE WITH REASON` / `RESEARCH-ONLY`, and never produce a target price, "buy/sell/hold", or sell-side prose. Long-term goal: the §ANALYTICAL PERSONALITY block above is the seed of a multi-discipline mental-model lattice (target ≥100 models drawn across psychology, economics, biology, history, physics) that the narrative LLM reasons through deliberately rather than by default. Adding a new mental model means: (a) writing it into §ANALYTICAL PERSONALITY with its inversion form, (b) updating ADR-023 §1.3 Block 2 if it joins the mandatory reasoning order, (c) adding a contract test in §1.8 that proves the lattice still produces the model on a canned scorecard.

```python
# CORRECT — quant layer (no AI tokens)
def compute_piotroski(financials: FinancialData) -> PiotroskiResult:
    roa = financials.net_income / financials.total_assets
    return PiotroskiResult(roa_positive=roa > 0, ...)

# CORRECT — deterministic text extraction (data/edgar_text_parser.py)
def parse_customer_concentration(text: str) -> CustomerSignals:
    for pattern in _CONC_PATTERNS:
        for m in pattern.finditer(text):
            ...  # regex, deterministic, zero tokens
    return CustomerSignals(concentration_pct=max(candidates), ...)

# WRONG — AI calls from any data / framework / screener / overlay module
def compute_piotroski(financials: FinancialData) -> PiotroskiResult:
    response = anthropic.messages.create(...)  # ❌ NEVER outside the allow-listed sites
                                                #    (tests/test_llm_call_sites.py)
```

**Key principle**: explicit data gaps are better than LLM approximations. A missing value flagged as a gap can be patched later with better source code; a hallucinated value silently corrupts every downstream framework score.

## Overlay execution policy (DEC-30)


Supersedes the DEC-28 split. All three overlays (ICA / PSA / BEW) auto-run in
the dive flow whenever their triggers fire and contribute a small, capped
additive bonus to the framework-weighted composite. There is no user
confirmation prompt anywhere in the path.

| Overlay | Trigger types | Auto-run? | Composite bonus |
|---|---|---|---|
| ICA | ICA-1..4 | yes | up to +0.6 (0.3 per F5 verdict-band step it climbs) |
| PSA | PSA-1..4 | yes | +0.5 (strong) / +0.25 (moderate) / 0 |
| BEW | BEW-1..3,5 | yes | +0.5 (extreme winner) / +0.25 (moderate) / 0 |

**Total bonus capped at 1.0** out of the 0-10 composite scale, so even
the all-strong case caps at +10%; framework signal still dominates.
When the raw sum exceeds the cap, the breakdown is pro-rated so the
audit trail shows which overlays were clipped.

Why this is safe (no Goodhart explosion):
- Bonuses are absolute additions, not multipliers.
- Each overlay's verdict bands are deterministic against persisted data:
  there is no LLM call and no narrative re-interpretation.
- ICA's headline contribution (Peters-Taylor restated ROIC) is already
  baked into `Company.pt_adjusted_roic` at the screener layer (DEC-28); the
  dive-level additive bonus is for the F5-band-step uplift only.
- The screener composite at the warehouse layer doesn't get PSA/BEW
  bonuses (they need price history / parent-company data not in
  `fill_universe.py` scope). Only ICA propagates to the warehouse.

```python
# CORRECT — all three overlays auto-integrate, capped contribution
triggers = overlay_detector.scan(scorecard)
results = {}
if any(t.type == "ICA" for t in triggers):
    results["ICA"] = await run_ica(...)
if any(t.type == "PSA" for t in triggers):
    results["PSA"] = await run_psa(...)
if any(t.type == "BEW" for t in triggers):
    results["BEW"] = await run_bew(...)
bonus, breakdown = _compute_overlay_composite_bonus(results, original_f5_verdict=...)
composite = min(framework_composite + bonus, 10.0)
```

Test: a deterministic overlay's run cost should be < 100ms and depend
only on already-persisted data. If it requires a network call or a
narrative call, it's interpretive: keep it passive.

## Caching


EDGAR filings are cached at the accession-number level via `FinancialSourceLog`
(Tier-0: DB lookup, never re-downloaded once parsed). yfinance responses go
through `data/cache/manager.py`. TTLs: financials 24h, price 1h, yfinance snapshot 6h.

## Environment variables

```bash
# .env (can live at project root or repo root — settings.py finds it)
EDGAR_IDENTITY="Your Name your.email@example.com"   # SEC fair-use header (no key)
ANTHROPIC_API_KEY=                                   # OPTIONAL — LLM call sites only
OPENAI_API_KEY=                                      # OPTIONAL — narrative/chat primary; falls back to Anthropic
DATABASE_URL=sqlite:///./investment_intelligence.db
LOG_LEVEL=INFO
ENVIRONMENT=development
```

The data path runs end-to-end without `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. Set them only when narrative generation (`invest score-card TICKER --narrate`), chat (`invest chat` / the UI chat box) or `/external-signals` skill invocation is needed.

## API rate limits

| Source | Limit | Strategy |
|--------|-------|----------|
| SEC EDGAR | 10 req/sec free (User-Agent required) | Tier-0 `financial_source_log` cache by accession # → ~0 calls per refresh after first run |
| yfinance | Unofficial (Yahoo scraper, no key) | TTL cache 6h on `.info`, 1h on price; fail soft to `data_gaps` |
| Polygon.io | Free tier 5 req/min, opt-in (`POLYGON_API_KEY`) | Watchlist-scope only (universe-scale infeasible at 5/min). Process-wide TokenBucket + 429 retry-after backoff. ADR-019. |
| Anthropic / OpenAI | Per token budget (~$0.08 per narrative on Claude Sonnet 4.6, measured 2026-10-23 over 9 stored runs; gpt-4o-mini unmeasured; ADR-031 §3 ceiling $100/mo) | Only the allow-listed call sites (`tests/test_llm_call_sites.py`): `narrative.py` (`invest score-card --narrate`), `external_signals.py` (`/external-signals` skill, `dangerous: true`), `conversation.py` (`invest chat` / UI chat box). OpenAI primary; Anthropic fallback. |
