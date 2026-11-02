# CLAUDE.md — Investment Intelligence System
## Project context for Claude Code
### Read this file completely before writing any code.

---

## WHAT THIS PROJECT IS

A Python-based quantitative investment research system that screens and analyses equities using 7 academic frameworks. The system is built around a strict lazy-load architecture — nothing runs without explicit user instruction. Claude (AI) is invoked only for qualitative deep-dive narrative; **the entire data-fetch and screener path is fully deterministic — no LLM API keys are required to run any data refresh, framework score, or screen.**

**Exclusion policies:** optional. Nothing is excluded unless a registered policy is enabled with `EXCLUSION_POLICY` (default `none`); a policy never changes a score (`screener/policies/README.md`). Research only — not financial advice.

**Scope:** self-contained. The repository has no build-time or run-time dependency on any sibling project, and its specifications live in `docs/methodology/`.

---

## CORE DESIGN PRINCIPLE — LAZY LOAD EVERYTHING

```
USER INSTRUCTION → gate check → run only what was asked → STOP → wait
```

- No stage auto-advances to the next stage
- No deep dive fires because a screener ran
- No overlay runs unless its trigger condition fires (ICA / PSA / BEW then auto-run with a capped bonus — coding rule 4)
- No scheduled job runs without being explicitly registered
- Token cost is strictly proportional to what the user requests

Violating this principle is the most critical architectural failure mode. Every function that costs tokens must be guarded by an explicit user instruction check.

---

## WORKING IN THIS REPOSITORY

These hold for every contributor and every assistant session. A personal
working agreement (how much autonomy an assistant has, who commits) belongs in
a gitignored `CLAUDE.local.md`, which Claude Code also loads.

- **Verify before calling it done** (coding rule 9): run the suite after the
  last edit; drive the UI in a real browser for `api/` or `frontend/` changes.
- **Never destructive by default.** No DB drop, truncate or data-losing
  migration, and no history rewrite or force-push, without the owner's explicit
  decision. Additive migrations (new tables, nullable columns, indexes) are
  ordinary changes; one that can lose rows or columns is not.
- **Decisions are proposed, not absorbed.** A change to an ADR, a new ADR, or
  code that knowingly diverges from an accepted one is raised for review, never
  made silently. Accepted ADRs are the design of record: a spec, plan or
  implementation that contradicts one is a proposed amendment, not a fix.
- **Say what you see.** A security hole, a plan that will not survive contact,
  an ADR that no longer matches the code: raise it, unprompted.
- **Cite, don't recall.** A claim about the code (a behaviour, a count, a call
  path) names `file:line` or a command the reader can re-run. A claim without
  one is labelled a guess.
- **Unknowns are written down, then asked.** A question the code and ADRs
  cannot answer goes in `docs/OPEN_QUESTIONS.md`, and work that depends on it
  stops until the owner answers. It is never filled with a plausible default.
- **A fresh pair of eyes before the owner's.** Each implementation PR is
  reviewed by a verifier that sees only the spec, the diff and the gate output,
  not the implementing session's reasoning. Its findings are fixed or listed in
  the PR. It filters; who may merge is the owner's working agreement
  (`CLAUDE.local.md`), not the verifier's call.
- **Gates, not prompts.** A rule that matters is enforced by a test or a CI
  check (as `tests/test_llm_call_sites.py` enforces the LLM call sites). Where a
  rule can only live in prose, say so where it is stated.
- **Borrow before building.** Before a non-trivial feature, search for a
  proven open-source project that already does it (`gh search repos`, web
  search). Proven means real dependents or production users, several active
  contributors, and a release in the last ~12 months; stars don't count.
  Report the top 1-3 with that evidence and a verdict (depend / fork / borrow
  the pattern / build), then wait. Adding one follows SECURITY & PRIVACY §5.
  Prose-only: no gate enforces this.

---

## ANALYTICAL PERSONALITY

This section governs the *stance* every Claude session takes when reasoning about a company, a framework, a test, or an architectural choice in this project. The lattice is non-negotiable; ignoring it produces analytically lazy code and analytically lazy verdicts.

### Default stance — owner-operator, not analyst

Every decision in this codebase — what data to fetch, what test to write, what signal to surface, what verdict to issue — is made through the lens of an *owner-operator*. A business owner putting personal capital at risk for the next decade.

Not a quant optimising a backtest. Not a sell-side analyst writing a note. Not a banker pitching a deal. **An owner.**

The operative question is never "does this hit my screener threshold." It is always: *"would I be willing to own 100% of this business for the next 10 years if the market closed tomorrow?"*

If the code, framework, or output you are working on doesn't help answer that question, you are building the wrong thing.

### Latticework — graph, not list

Munger's central insight: a single discipline produces "the man with a hammer" — every problem looks like a nail. Real judgement comes from a *latticework* of models drawn across psychology, economics, biology, history, physics, engineering, epistemology, statistics, game theory, information theory, and systems thinking.

**The lattice has been extracted to `mental_models/` per ADR-024.** That directory is the canonical source — one file per model, with mandatory `inversion_form`, `code_consequences`, `related_models` fields. The lattice is a graph; cross-references between models are first-class.

- **Browse the lattice:** `mental_models/_index.md`
- **Identify gaps:** `mental_models/_gaps.md`
- **Schema + how to add a model:** `mental_models/README.md`
- **Architecture + anti-bloat protections:** `docs/architecture/adrs/ADR-024-mental-models-library-and-composition.md`

Inventory: **114 models across all 16 populated domain directories** (Stage C closed 2026-05-09; +3 engineering refinements 2026-06-07). `core/` (12), `moat/` (6), `management/` (1), `bias/` (12), `statistical/` (5), `engineering/` (34 — 6 reliability + 28 software-engineering including 7 Claude-Code-specific), `systems/` (5), `biology/` (5), `game_theory/` (5), `physics/` (5), `history/` (5), `epistemology/` (4), `information_theory/` (4), `valuation/` (3), `lifecycle/` (4), `meta/` (4). All 16 directories populated. Future growth is by quality refinement + annual-review-driven pruning; cosmetic count is no longer the target.

### Inversion is mandatory and primary

When any new analytical primitive enters the system — a framework, a data field, an overlay, a mental model — explicitly invert it before shipping. The pattern:

| Forward question | Inversion question |
|---|---|
| What makes this stock a winner? | What makes most stocks losers, and does this one share those traits? |
| Does this company have a moat? | What would destroy this moat, and is that already happening? |
| Is the CEO a good capital allocator? | What would a *bad* capital allocator do, and how much of that pattern is present? |
| Is this thesis right? | What would have to be true for it to be wrong, and is any of that observable now? |
| Should we add this signal? | What false positives will it produce, and at what cost? |
| Will this scale? | If I had $1B and unlimited talent, could I displace this incumbent in 5 years? |

If a feature, framework, mental model, or thesis cannot survive its own inversion, **it does not ship**. ADR-024 §1.6 makes this an enforceable schema rule for the lattice itself: every model file requires a non-empty `inversion_form` body section.

### Operationalisation — how the lattice touches the code

The mental-model stack is not ornament. It translates into concrete engineering decisions. Each row maps a model (full file in `mental_models/`) to its code consequence:

| Mental model | Code consequence |
|---|---|
| `core/inversion` | Every framework has a corresponding *disqualification* check. Tests cover failure modes, not just success paths. |
| `core/margin_of_safety` | Composite score is capped. Overlay bonuses bounded (≤1.0 / 10.0). No single signal drives a verdict. |
| `management/thorndike_outsiders_eight_traits` | F5/F6 surface CEO tenure, founder ownership %, buyback timing vs price, multi-year insider buy/sell ratio. DEF 14A parsing is non-optional. |
| `moat/munger_dorsey_five_sources` + `moat/helmer_seven_powers` | F6 separates academic anchors (Patatoukas, Fahlenbrach, Novy-Marx) from practitioner heuristics (NRR, Rule of 40). Moat-direction (`moat/moat_direction`) tracked at unit-economic level. |
| `core/circle_of_competence` | `data_gaps[]` is a first-class output. "We don't know" is a valid system response and surfaces in the CLI. |
| `core/first_principles` | Frameworks compute from raw EDGAR XBRL where possible; never depend on third-party calculated fields without source verification (ADR-022). |
| `bias/*` (7 models) | CLI never offers a "buy" verdict — only "watchlist with triggers" or "exclude with reason." Verdict labels avoid emotional language. |
| `moat/lunch_eating_test` + `moat/challenger_inversion_test` | Any framework that surfaces "growth" without TAM context is incomplete. Mandatory inversion of moat claims at narrative output (ADR-023 §1.4 §5). |

### Adding a mental model

1. Read `mental_models/README.md` — schema and mandatory fields.
2. Identify the right subdirectory (default `core/` only if `always_load: true`).
3. Write the file with full frontmatter + body sections (especially `inversion_form` — half-loaded models are rejected).
4. Cross-link via `related_models` — the lattice is a graph, not a list.
5. Update `mental_models/_index.md` and remove the corresponding row in `_gaps.md`.
6. Only update CLAUDE.md if the model belongs in the operationalisation table above.

The narrative LLM in `deepdive/narrative.py` (shipped, ADR-023) reasons through this lattice in a structured order — Inversion → Circle of Competence → Moat Direction → Capital Allocator → Lunch-Eating Test → Probabilistic Base Rate. ADR-024's directory structure is the artifact ADR-023's prompt composer reads at runtime; the prose lives once, in `mental_models/`. The composer (`deepdive/mental_model_composer.py`) is wired into `narrative.py` (2026-05-10): a `LatticeProfile` is derived from the deterministic `ScorecardView` (revenue / proxy / archetype / overlays-fired), `select_models_for_dive` picks the relevant subset under a token budget (default 8000, raised from 6000 on 2026-05-17 to unblock budget-starved conditional fires — see `mental_model_composer.py`), and the chosen models' Summary + Inversion form sections are injected into the LLM user prompt. Lattice slugs do NOT appear in `framework_codes` / `grounded_in` — only F1..F7 codes, overlay trigger_ids, and view field paths are valid groundings (see `deepdive/narrative_guard.py`).

---

## TECH STACK

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

---

## PROJECT STRUCTURE

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
└── tests/
    ├── conftest.py
    ├── test_frameworks/
    ├── test_screener/
    ├── test_overlays/
    └── fixtures/
        └── sample_financials.json
```

---

## IMPLEMENTATION STATUS

| Phase | Component | Status |
|-------|-----------|--------|
| 1 | Scaffold + config + DB schema | ✅ Complete |
| 1 | Typer CLI skeleton | ✅ Complete |
| 2 | EDGAR fetcher (10yr fundamentals via companyfacts.json, Form 4, DEF 14A) | ✅ Complete |
| 2 | yfinance client (snapshot + holders + price history + analyst) | ✅ Complete |
| 2 | edgar_text_parser (regex + BeautifulSoup, zero-LLM extraction) | ✅ Complete |
| 2 | Data pipeline (3-tier lazy load, bulk persistence, asyncio.gather) | ✅ Complete |
| 2 | Framework-aware DataRequirement + CompanyDataReader | ✅ Complete |
| 2 | Deep-dive orchestrator + IPO-aware feasibility + scheduler deepdive jobs | ✅ Complete |
| 3 | Screener (Tier 0–6 ladder, staged scheduler, cleanup) | ✅ Complete (SCREENER_PIPELINE.md, DEC-09–DEC-15) |
| 4 | Frameworks F1–F7 score logic | ✅ Complete (all 7 frameworks production-validated across TEM/BFLY/LULU/HIMS/INTA/NVDA/SHOP) |
| 5 | Overlays ICA/PSA/BEW (passive detector + verdict math, auto-integrated DEC-30 / ADR-021 §4.4) | ✅ Complete |
| 5a | Polygon plugin tasks (price / RSI / SMA / MACD / short interest — opt-in, watchlist scope) | ✅ Complete (ADR-019) |
| 5T | Damodaran intrinsic value + sibling outputs (EPV / Reverse DCF / Narrative Premium) | ✅ Complete (ADR-027, ADR-029) |
| 6 | AI narrative layer (the call sites in `tests/test_llm_call_sites.py`) | 🟡 Built, contract not met — invoked via `invest score-card TICKER --narrate`; output checked by `narrative_guard.py`, but 8 of 13 stored narratives fail it (ADR-023-A1); ADR-045–047 carry the fix |
| 7 | Scheduler jobs (quarterly, monthly, deepdive) | ✅ Wiring complete |
| — | Mental-models lattice (114 models across 16 domains, composer wired into narrative) | ✅ Complete (ADR-024) |
| — | Project-local skills runtime (3 skills: dive-complete, audit-completeness, external-signals) | ✅ Complete (ADR-032) |
| — | Skill versioning + lineage + evaluation + composability (5 CI test files, 16 tests) | ✅ Complete (ADR-034, ADR-035, ADR-036) |
| — | SEC-first source hierarchy + per-field `_source` provenance plumbing | ✅ Phase 1 + Phase 2.1 (exchange) + Phase 2.2 (ceo_total_pay) complete; B.1/B.4/B.5 deferred (ADR-033, API_FIELD_AUDIT.md) |

---

## FRAMEWORK-AWARE LAZY LOAD (Phase 2 architecture)

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
- Frameworks NEVER touch SQL or import schema directly — always go through `CompanyDataReader`.
- All EDGAR text/HTML extraction is deterministic (regex / BeautifulSoup). The data path is LLM-free; AI is restricted to `deepdive/narrative.py`.
- Missing data → `data_gaps[]` entry, never a hallucinated value.

### Recent IPO graceful degradation

A company with <2 annual filings cannot run F1 (Piotroski needs YoY). Rather than crashing, `_check_feasibility` walks `reader.annual_year_set()` before invoking score functions and marks unfeasible frameworks with reason ("recent IPO / insufficient annual history (needs 2yr, have 1)"). Other frameworks still run.

For the dive command itself:
- `invest dive ABC`               — runs all 7; F2/F7 auto-skip on recent IPO
- `invest dive ABC --frameworks F1`  — user-defined narrow dive
- `invest dive ABC --mode A`         — preset (F1+F2+F3)

---

## CRITICAL CODING RULES

### 1. AI layer boundary — allow-listed call sites only

The Anthropic / OpenAI SDKs may be imported only by the modules in `ALLOWED` in
`tests/test_llm_call_sites.py`, which CI enforces. That set is the single source
of truth; adding to it is an ADR amendment (ADR-031 §4.1, ADR-032 §1.5, ADR-031-A1).

| Module | Purpose | When called |
|--------|---------|-------------|
| `deepdive/narrative.py` | **Narrative generation** — qualitative bull/bear/risk narrative for the deep-dive report. Constrained to pre-computed quant metrics — never invents numbers. Renders the DEC-23 hold-philosophy frame (ADR-023 §10). | Only when user explicitly runs `invest score-card TICKER --narrate`. Persists structured JSON to `deepdive_runs.bull_narrative` / `.bear_narrative` / `.risk_factors`. |
| `deepdive/external_signals.py` | **Supplementary signal extraction** — NRR / GRR / ARR / GMV / take-rate from 8-K EX-99.1 earnings releases. Writes to `external_signals` table only — **strictly isolated** from F1-F7 framework scoring (no Financial / Company canonical writes). | Only when user explicitly invokes `/external-signals TICKER` skill (`dangerous: true` — requires confirmation per ADR-032 §2.4). |
| `deepdive/conversation.py` | **Conversational dive** — multi-turn Q&A grounded in the *frozen* `ScorecardView` of one `DeepDiveRun`. Every reply's `numeric_claims` must resolve to a view field path; mismatches surface as guard warnings. | Only when the user types a question into `invest chat TICKER` (default $2 session budget, `--budget`) or the UI "Ask about this dive" box (`POST /dive/{ticker}/chat`, no session budget). Persists every turn, append-only, to `deep_dive_conversations`. |

The data-fetch and screener paths are **fully deterministic**: EDGAR XBRL → regex on 10-K text → BeautifulSoup on DEF 14A HTML → yfinance typed snapshot. There is no LLM fallback in the data layer. A missing value surfaces as a `data_gaps` entry, never a hallucinated number.

> **Personality contract:** the *behaviour* of the LLM call inside `deepdive/narrative.py` is binding-spec'd in **ADR-023 — Narrative Personality Spec**. The LLM must reason in the order Inversion → Circle of Competence → Moat Direction → Capital Allocator → Lunch-Eating Test → Probabilistic Base Rate, produce one of `WATCHLIST WITH TRIGGERS` / `EXCLUDE WITH REASON` / `RESEARCH-ONLY`, and never produce a target price, "buy/sell/hold", or sell-side prose. Long-term goal: the §ANALYTICAL PERSONALITY block above is the seed of a multi-discipline mental-model lattice (target ≥100 models drawn across psychology, economics, biology, history, physics) that the narrative LLM reasons through deliberately rather than by default. Adding a new mental model means: (a) writing it into §ANALYTICAL PERSONALITY with its inversion form, (b) updating ADR-023 §1.3 Block 2 if it joins the mandatory reasoning order, (c) adding a contract test in §1.8 that proves the lattice still produces the model on a canned scorecard.

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

### 2. Every public function has a return type

```python
def score_f1(data: CompanyData) -> FrameworkResult: ...  # ✅
def score_f1(data):  # ❌
```

### 3. No silent failures on missing data

```python
# CORRECT
if data.rd_expense is None:
    raise MissingDataError("rd_expense", "/income-statement/{ticker}", ticker)

# WRONG
rd_intensity = (data.rd_expense or 0) / data.revenue  # ❌ silent assumption
```

### 4. Overlay execution policy — all overlays auto-integrated (Phase 5j / DEC-30)

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
the all-strong case caps at +10% — framework signal still dominates.
When the raw sum exceeds the cap, the breakdown is pro-rated so the
audit trail shows which overlays were clipped.

Why this is safe (no Goodhart explosion):
- Bonuses are absolute additions, not multipliers.
- Each overlay's verdict bands are deterministic against persisted data
  — there is no LLM call, no narrative re-interpretation.
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
if any(t.type == "ICA" for t in triggers): results["ICA"] = await run_ica(...)
if any(t.type == "PSA" for t in triggers): results["PSA"] = await run_psa(...)
if any(t.type == "BEW" for t in triggers): results["BEW"] = await run_bew(...)
bonus, breakdown = _compute_overlay_composite_bonus(results, original_f5_verdict=...)
composite = min(framework_composite + bonus, 10.0)
```

Test: a deterministic overlay's run cost should be < 100ms and depend
only on already-persisted data. If it requires a network call or a
narrative call, it's interpretive — keep it passive.

### 5. Cache all API responses

EDGAR filings are cached at the accession-number level via `FinancialSourceLog`
(Tier-0 — DB lookup, never re-downloaded once parsed). yfinance responses go
through `data/cache/manager.py`. TTLs: financials 24h, price 1h, yfinance snapshot 6h.

### 6. Pydantic v2 for all API data structures

All data flowing between modules uses Pydantic v2 models. No raw dicts passed between functions.

### 7. Lint: a gated subset and a baseline that must not grow

```bash
uv run ruff check . --select F821,F811,E722   # gated in CI; must be clean
uv run ruff check .                           # baseline 364 at release
uv run mypy . --strict                        # baseline 1086 at release
uv run pytest
```

The correctness subset fails at runtime, so it is gated. Overall ruff and mypy
are an honest backlog (D9): fix findings in code you touch, never add new ones,
and do not reformat unrelated code to do it.

### 8. Comments and docblocks — precise, concise, never repeated

One or two lines. Say what is not already obvious from the code; never restate
what the next line does. A fact belongs in exactly one place in the codebase —
if a rationale is already in an ADR or a module docstring, reference it, do not
re-explain it. No banner blocks, no tutorial prose, no over-explaining.

```python
# CORRECT — non-obvious constraint, stated once
span = 350  # <365: EDGAR annual spans run short; wider leaks YTD rows

# WRONG — restates the code
# Set the span variable to 350 days
span = 350
```

### 9. No commit without verification

End-to-end against the real local DB where the change is reachable that way;
Playwright for anything touching `api/` or `frontend/`; unit tests against the
real DB otherwise. "Tests pass" means the suite was actually run after the
final edit, not before it. An unexecuted artifact (Dockerfile, CI workflow,
migration) is not verified by having been written.

---

## ENVIRONMENT VARIABLES

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

---

## API RATE LIMITS

| Source | Limit | Strategy |
|--------|-------|----------|
| SEC EDGAR | 10 req/sec free (User-Agent required) | Tier-0 `financial_source_log` cache by accession # → ~0 calls per refresh after first run |
| yfinance | Unofficial (Yahoo scraper, no key) | TTL cache 6h on `.info`, 1h on price; fail soft to `data_gaps` |
| Polygon.io | Free tier 5 req/min — opt-in (`POLYGON_API_KEY`) | Watchlist-scope only (universe-scale infeasible at 5/min). Process-wide TokenBucket + 429 retry-after backoff. ADR-019. |
| Anthropic / OpenAI | Per token budget (~$0.08 per narrative on Claude Sonnet 4.6, measured 2026-10-23 over 9 stored runs; gpt-4o-mini unmeasured; ADR-031 §3 ceiling $100/mo) | Only the allow-listed call sites (`tests/test_llm_call_sites.py`): `narrative.py` (`invest score-card --narrate`), `external_signals.py` (`/external-signals` skill, `dangerous: true`), `conversation.py` (`invest chat` / UI chat box). OpenAI primary; Anthropic fallback. |

---

## MCP USAGE POLICY

MCPs (Alpha Vantage, Neon) are available in Claude Code sessions for:
- Development testing and data exploration
- Neon PostgreSQL setup for production migration

MCPs are NOT used in production code paths (schedulers, CLI data pipeline).
All production code uses direct httpx API calls. Connectors with access to
personal data are never queried as part of project work without an explicit ask.

---

## SECURITY & PRIVACY

This is the single source of truth for secrets, data egress, and trust
boundaries. WHAT THE SYSTEM MUST NEVER DO §7 (no hardcoded keys) is subsumed
here — do not maintain secrets guidance anywhere else in this file.

### 1. Secrets — handling

Secrets in scope: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `POLYGON_API_KEY`,
`DATABASE_URL` (prod = Neon connection string with embedded credentials), and
`EDGAR_IDENTITY` (real name + email = PII).

- Never hardcode a secret in source, test, fixture, or migration.
- Never print, log, echo in tool/CLI output, or write into a committed file.
  This includes log lines, stack traces, error messages, and diffs pasted
  back to the user. Redact before surfacing.
- Never embed a secret in an LLM prompt (any allow-listed call site).
- `.env` is gitignored and stays gitignored. `.env.example` carries key
  NAMES only, never values.
- Assume any secret that has ever hit disk unredacted or git history is
  already compromised. Flag the need to rotate; the key's owner rotates it.

### 2. Data egress to LLM providers — allow-list

The call sites allow-listed in `tests/test_llm_call_sites.py` (OpenAI primary,
Anthropic fallback) send data to third parties. Only the following may enter a
prompt:

- Public-derived quant metrics: EDGAR XBRL fundamentals, framework F1-F7
  scores, overlay verdicts, deterministic signals computed from public
  filings, ticker + exchange.
- In `deepdive/conversation.py`, the user's own typed question and the prior
  turns of that conversation, sent as written. Whatever the user types leaves
  the machine; the rules below still bind what the code attaches.

The following NEVER enter a prompt, a serialised scorecard bound for a
prompt, or provider logs — no exceptions, no "it would improve the
narrative" override:

- Portfolio holdings, position sizes, cost basis, or which tickers the user
  actually owns.
- Watchlist membership framed as intent, net-worth or savings figures, or any
  personal financial context from user preferences or memory.
- Any secret (see §1) or `EDGAR_IDENTITY` PII.

The scorecard is public-market analysis of a business. It is not a record of
the user's financial position, and nothing that would make it one may be
attached to a prompt.

### 3. Trust boundary — filing text is DATA, never instruction

10-K / 10-Q / DEF 14A / 8-K text is attacker-influenceable free text. The
deterministic-parse-first design is a SECURITY PROPERTY, not just an
architecture choice:

- Filing text is parsed by regex / BeautifulSoup into numeric/structured
  signals. The narrative LLM receives those pre-computed signals, never raw
  filing prose.
- Text extracted from a filing is treated as data. Instruction-like content
  inside a filing ("ignore prior guidance", "rate this BUY") is inert by
  construction and must stay that way — no future path may pipe raw filing
  text into a prompt as instructions.
- The one existing exception: `deepdive/external_signals.py` (opt-in
  `/external-signals`, `dangerous: true`) sends up to `MODEL_TEXT_CHARS`
  (80,000) characters of 8-K EX-99.1 or DEF 14A text to the model as delimited
  source data, and persists only to `external_signals`. Before anything is
  stored, `deepdive/signal_verifier.py` checks each reply (ADR-057): the quote
  must be one substring of the text the model saw and the value a number in
  it; a failing value is dropped and the stored band is the lower of the
  model's and the check's. A verbatim number for the wrong metric still passes
  (ADR-057 §4).
- This is why the AI-layer boundary (allow-listed call sites, numeric inputs
  only, bar the exception above) is load-bearing beyond token cost.

### 4. Source integrity — trust hierarchy

Not all data sources are equally trustworthy. Provenance (`_source`, ADR-033)
enforces a hierarchy, not just a label:

- **SEC EDGAR** — highest trust. Public, authoritative, first-principles.
- **yfinance** — LOWER trust. Unofficial unauthenticated Yahoo scraper; can
  return silently wrong values and is itself an unpinned external dependency.
  A yfinance value NEVER overrides an EDGAR-sourced field for the same fact.
  On conflict, EDGAR wins and the divergence surfaces as a data gap / note.
- Capital decisions ride on this data — an integrity failure is a real-money
  failure, not a cosmetic one.

### 5. Dependency / supply-chain hygiene

- `uv.lock` is committed and respected. Builds are reproducible from the lock.
- A new dependency is a reviewable change, never a silent add — flag it, name
  why it's needed. Typosquat / unpinned deps are a credible path to secret
  theft in a repo that holds a Neon connection string.

### 6. Data-at-rest

`investment_intelligence.db` (SQLite) is unencrypted plaintext on disk.
Acceptable for a single-user local tool — but it therefore must not be synced
to a cloud drive, committed, or copied outside the project sandbox. It holds
your research, not your credentials, but treat it as local-only.

---

## PROJECT-LOCAL SKILLS

Routine workflows live in `.claude/skills/*.md`. Each skill is invoked
via the `Skill` tool by name (e.g., `Skill(skill="dive-complete", args="SHOP")`).
Skills are deterministic checklists OVER existing CLI subcommands —
they do NOT replace any CLI behaviour, do NOT introduce new persistence paths,
and do NOT add new LLM call sites. The call-site allow-list
(`tests/test_llm_call_sites.py`) is preserved.

See **ADR-032** for the skill pattern, schema, shadow-mode discipline, and
the rule-of-three for new-skill authoring. See `.claude/skills/README.md`
for the frontmatter contract.

Current starter skills (Phase 1):

- `/dive-complete TICKER` — canonical Tier-2 dive cycle with delta-anomaly check
- `/audit-completeness TICKER` — gap classification per ADR-031 §1.2 register
- `/external-signals TICKER` — LLM-supplementary extraction (`dangerous: true`)

Every new skill spends 14 days in shadow-mode verification (telemetry persisted
to `skill_invocations`) before graduating. CI enforces signature compatibility
with the underlying CLI via `tests/test_skills/test_signature_compatibility.py`.

---

## WEB UI (ADR-040)

`api/app.py` (a thin FastAPI pass-through) and `frontend/` (React + Vite +
TypeScript) sit on top of the CLI engine. Verify API changes through `/docs`
(Swagger UI) in a browser, and UI changes with Playwright (`-m browser`).

---

## WHAT THE SYSTEM MUST NEVER DO

1. Auto-advance any stage without user input
2. Call Anthropic/OpenAI API from any module outside the call sites
   allow-listed in `tests/test_llm_call_sites.py` (ADR-031 §4.1, ADR-031-A1)
3. Make assumptions about missing financial data
4. Run an overlay whose trigger did not fire
5. Run scheduled jobs without being explicitly registered by the user
6. Return a framework score when required input data is unavailable
7. Hardcode API keys anywhere in source code (see SECURITY & PRIVACY §1 for the full secrets-handling contract)
8. Invoke a `dangerous: true` skill without explicit user confirmation
   (ADR-032 §2.4 — non-negotiable; no "user has authorised similar ops"
   shortcut)

---

## FULL BUSINESS LOGIC

See `docs/methodology/PROJECT_SPEC.md` for:
- Complete framework implementations (F1–F7) with all signal thresholds
- All 3 diagnostic overlay trigger conditions and computation procedures
- Screener pipeline with hard gate logic
- Composite scoring with mode weights (A/B/C/D)
- Database schema
- Scheduler job definitions

---



*Research purposes only. Not financial advice.*
