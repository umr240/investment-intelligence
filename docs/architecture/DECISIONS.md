# Architectural Decisions (Locked)

Each decision below is locked. Override by APPENDING a new entry that says
"supersedes DEC-nn", never by editing in place. This is the audit trail.

> **Public-release edit (2026-10).** References to working documents retired
> at release (the lab and screener plans, status snapshots, session logs,
> one-off scripts) were repointed or marked *archived*, and wording specific
> to the author's own exclusion policy was generalised. No decision changed.
> The original text is kept in the private archive repository.

## Identifiers

Decisions are `DEC-nn`, numbered chronologically and unique. They were
previously `D<n>`, which is why older references in code and ADRs use that
form; the table below resolves every one of them.

Two things made the old labels unusable as an audit trail, and both are fixed
here rather than left for a reader to untangle:

**Numbers were reused.** Eleven labels (`D17`-`D27`) were each applied to two
different decisions, because two series were maintained in parallel — a
detailed working log and a terser index of ADRs — and they overlapped. `D17`
named three separate entries. A reference to "D19" could not be resolved
without guessing.

**Two decisions were recorded twice.** The Peters-Taylor ROIC decision was
logged on 2026-05-09 and again on 2026-05-10; the TTM/MRQ/FY freshness model
on 2026-05-11 and again on 2026-05-14. Each pair is now a single entry that
absorbs anything the duplicate said uniquely, marked `**Merged**`.

> **`D<n>` also means something else elsewhere.** ADR-018 numbers its
> *data-gap tasks* `D1`-`D7` — `D7` there is `IPODateTask`, not the decision
> about Form 4 limits. `data/api/yfinance_client.py` and
> `data/pipeline.py` use that ADR-018 namespace too. Those are untouched:
> `D<n>` inside an ADR-018 context is a gap ID, `DEC-nn` is always a decision.

| Historical label | Date | Decision | Now |
|---|---|---|---|
| `D1` | 2026-05-02 | Drop FMP and Alpha Vantage from the data path | **DEC-01** |
| `D2` | 2026-05-03 | Zero LLM in the data path | **DEC-02** |
| `D3` | 2026-05-03 | companyfacts.json single-call replaces per-filing XBRL | **DEC-03** |
| `D4` | 2026-05-03 | Framework-aware lazy load | **DEC-04** |
| `D5` | 2026-05-03 | Default deep-dive runs ALL 7 frameworks | **DEC-05** |
| `D6` | 2026-05-03 | Reader API as single source of truth for read access | **DEC-06** |
| `D7` | 2026-05-03 | Form 4 limit dropped 200 → 50 | **DEC-07** |
| `D8` | 2026-05-03 | `.claude/` session-persisting layer at lab root | **DEC-08** |
| `D9` | 2026-05-03 | Screener uses SEC frames.json for universe-wide fundamentals | **DEC-09** |
| `D10` | 2026-05-03 | Screener does NOT auto-dive | **DEC-10** |
| `D11` | 2026-05-03 | Tiered ticker storage with cleanup | **DEC-11** |
| `D12` | 2026-05-03 | Canonical time anchor on Financial: `period_end_date` | **DEC-12** |
| `D13` | 2026-05-03 | One in-memory exclusion rule set at Tier 3 | **DEC-13** |
| `D14` | 2026-05-03 | Screener split into staged scheduler jobs with per-stage caps | **DEC-14** |
| `D15` | 2026-05-04 | Tier 4 is rank-and-narrow, NOT a hard stop | **DEC-15** |
| `D16` | 2026-05-06 | Screener becomes a warehouse query (ADR-017 accepted) | **DEC-16** |
| `D17` | 2026-05-08 | Per-chunk persist in the task runner (ADR-020 option b) | **DEC-17** |
| `D18` | 2026-05-09 | ICA auto-integrates into composite scoring; PSA/BEW remain passive | **DEC-18** |
| `D19` | 2026-05-09 | All overlays auto-run + capped composite bonus; F6 feasibility gate wi | **DEC-19** |
| `D17` | 2026-05-09 | Economic ROIC adjustment uses Peters-Taylor, not management non-GAAP | **DEC-20** |
| `D20` | 2026-05-10 | ROIC formula fix: NOPAT / (E + D − Cash); pretax_roic added; F6 custom | **DEC-21** |
| `D21` | 2026-05-10 | Persistent conversational dive (`invest chat TICKER`) | **DEC-22** |
| `D22` | 2026-05-11 | Hold philosophy: forever-default, 5-year minimum reconsideration | **DEC-23** |
| `D26` | 2026-05-11 | TTM/MRQ/FY three-tier data freshness; 10-Q text reader (ADR-026) | **DEC-24** |
| `D25` | 2026-05-11 | Portfolio concept separate from watchlist; annual reassessment cron | **DEC-25** |
| `D24` | 2026-05-11 | Yearly watchlist checkpoint with warning-signal detection | **DEC-26** |
| `D23` | 2026-05-11 | BEW mandatory on every dive; ICA/PSA stay trigger-gated; SIM scoped to | **DEC-27** |
| `D18` | 2026-05-11 | Methodology disclosure + source provenance mandatory | **DEC-28** |
| `D27` | 2026-05-12 | Phase 5R: data-quality signals (SBC, goodwill, dilution, revenue traje | **DEC-29** |
| `D19` | 2026-05-12 | Narrative LLM personality + structured output (D22 hold-philosophy) | **DEC-30** |
| `D20` | 2026-05-13 | Mental-models lattice library + composition pipeline | **DEC-31** |
| `D21` | 2026-05-14 | IFRS / FPI universe support | **DEC-32** |
| `D23` | 2026-05-15 | Damodaran intrinsic-value module + young-company target-margin DCF + u | **DEC-33** |
| `D24` | 2026-05-15 | Maturity classifier + young-tier routing | **DEC-34** |
| `D25` | 2026-05-15 | Data Gap Register + LLM-supplementary extraction channel | **DEC-35** |
| `D26` | 2026-05-15 | Project-local skills runtime + two-permitted-call-sites rule | **DEC-36** |
| `D27` | 2026-05-15 | SEC-first source hierarchy + compute-don't-pull | **DEC-37** |
| `D28` | 2026-05-16 | Skill versioning + lineage protocol | **DEC-38** |
| `D29` | 2026-05-16 | Skill evaluation protocol (Anthropic four-dimension framing) | **DEC-39** |
| `D30` | 2026-05-16 | Skill composability protocol + DAG validation | **DEC-40** |
| `D31` | 2026-05-17 | PSA verdict-aware archetype gating + lattice budget bump | **DEC-41** |
| `D17` | 2026-05-10 | Economic ROIC adjustment (Peters-Taylor, not management non-GAAP) | merged into **DEC-20** |
| `D22` | 2026-05-14 | TTM / MRQ / FY three-tier data freshness | merged into **DEC-24** |

---

## DEC-01 — Drop FMP and Alpha Vantage from the data path

**Date**: 2026-05-02
**Decision**: All fundamentals come from SEC EDGAR; all market data from yfinance.
**Why**: FMP free tier has 250 req/day cap and a screener run blows through it. yfinance is unofficial-but-free with no rate limit. EDGAR is authoritative XBRL with no key required. Two paid APIs replaced by two free, more authoritative sources.
**Trade-off**: 2 specific signals lost (historical short-interest snapshots, earnings-vs-consensus history). Acceptable for a research lab; we accumulate SI snapshots over time via the monthly scheduler.
**See**: the lab plan (archived)

## DEC-02 — Zero LLM in the data path

**Date**: 2026-05-03
**Decision**: The data fetch / screener / framework-score paths are 100% deterministic. Anthropic SDK may only be called from `deepdive/narrative.py` (Phase 6).
**Why**: Hallucinated numbers silently corrupt every downstream framework score. Explicit `data_gaps[]` entries are recoverable; bad numbers are not. Cost discipline: data fetch should be free.
**Implementation**: replaced `data/edgar_nlp_extractor.py` (Haiku-based) with `data/edgar_text_parser.py` (regex + BeautifulSoup). Founder/CEO equity / customer concentration all extracted deterministically.
**See**: `CLAUDE.md` "AI layer boundary — ONE permitted location only"

## DEC-03 — companyfacts.json single-call replaces per-filing XBRL

**Date**: 2026-05-03
**Decision**: Primary fundamentals fetch is SEC's `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` bulk endpoint, not per-filing `filing.xbrl()`.
**Why**: 30× fewer EDGAR roundtrips on cold cache (1 HTTP vs 40+). Same authoritative XBRL data; companyfacts contains every fact every filing tagged.
**Safety**: per-filing parser retained as fallback when companyfacts returns 404 (rare — small/foreign filers with poor tagging).
**Invariants**: form whitelist + latest-filed-wins restatement + shortest-span period selection (verified on synthetic fixtures).

## DEC-04 — Framework-aware lazy load

**Date**: 2026-05-03
**Decision**: Each framework declares `DATA_REQUIREMENT = DataRequirement(...)`. The orchestrator unions requirements across selected frameworks; the pipeline fetches only the minimum superset.
**Why**: F1 (Piotroski) needs 2 years; F7 (z-scores) needs 10. Running F1 alone shouldn't trigger 10yr fetch + DEF 14A + 10-K text parsing.
**Trade-off**: The kitchen-sink `refresh_ticker(years=10)` API still works for the screener / scheduler watchlist refresh. Framework-aware mode is opt-in via `requirement=` parameter.

## DEC-05 — Default deep-dive runs ALL 7 frameworks

**Date**: 2026-05-03
**Decision**: `invest dive TICKER` (no flags) runs all of F1–F7. `_check_feasibility` pre-flight auto-marks frameworks unsuitable for the company (recent IPO → F7 unfeasible) without crashing.
**Why**: User intent for "deep dive" = comprehensive. Selecting frameworks should be the EXCEPTION (`--frameworks F1`), not the default.
**Trade-off**: Default fetch is heavier than necessary for a recent IPO (we fetch 10yr but only use 2). This is fine — companyfacts is a single bulk download regardless of year window.

## DEC-06 — Reader API as single source of truth for read access

**Date**: 2026-05-03
**Decision**: Frameworks consume `CompanyDataReader(ticker)`. They never import schema or query SQLAlchemy.
**Why**: Decouples framework code from persistence. Future migration to PostgreSQL/Neon requires zero changes to framework files. The reader is the only place that needs to evolve when the schema does.

## DEC-07 — Form 4 limit dropped 200 → 50

**Date**: 2026-05-03
**Decision**: Default `fetch_edgar_insiders(limit=50)`.
**Why**: F1's 90-day insider cluster window only needs ~30 most-recent filings; 50 covers 1-2 months of activity for active filers. 200 was 4× wasteful.
**Override**: callers may pass `limit=200` for richer history when needed (e.g. a tier-2 deep dive examining multi-year insider patterns).

## DEC-08 — `.claude/` session-persisting layer at lab root

**Date**: 2026-05-03
**Decision**: Lab keeps its own `.claude/` directory for session continuity, mirroring the layout of an earlier, separate project.
**Why**: The lab needed its own audit trail, independent of any other codebase.
**Files**: `architecture/DATA_LAYER.md`, `architecture/DECISIONS.md` (this file). The status snapshot and session logs were retired at public release (archived); `.claude/README.md` describes what remains.

## DEC-09 — Screener uses SEC frames.json for universe-wide fundamentals

**Date**: 2026-05-03
**Decision**: Tier 4 of the screener (universe-wide fundamentals filter) fetches via SEC's `data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{period}.json` endpoint. Each call returns ONE concept across ALL filers for a given period. ~30 calls cover the entire screen vs ~10000 with per-ticker companyfacts.
**Why**: 3× fewer HTTP calls per quarterly screen run. Matches the Fiscal.ai / Finviz pattern of querying the warehouse, not each ticker.
**Per-ticker companyfacts** is reserved for the top-200 shortlist (Tier 5), where we need full fundamentals + history.
**Trade-off**: frames.json is calendar-period-keyed; companies with off-calendar fiscal years (NVDA Jan, AAPL Sep) report under their fiscal calendar, so cross-period comparisons require care. To be empirically verified during Phase 3c.
**See**: `docs/architecture/SCREENER_PIPELINE.md` §1

## DEC-10 — Screener does NOT auto-dive

**Date**: 2026-05-03
**Decision**: The screener produces a ranked candidate list. The user is the only escalator from `screener_candidate` → `watchlist` → `dive`. There are no earnings-triggered jobs, no auto-promotion, no alerts.
**Why**: User direction. Keeps the `lazy-load` rule pure — every escalation is an explicit user action. Avoids the operational complexity of v1's Phase 3d (earnings polling, diff renderers, alert sidecars).
**v1's Phase 3d work** (next_earnings_date, auto_dive_on_earnings columns, diff/alert system) is deferred indefinitely. May reappear in a future phase if the user asks for it.
**See**: `docs/architecture/SCREENER_PIPELINE.md`. The v1 and v2 screener plans are archived.

## DEC-11 — Tiered ticker storage with cleanup

**Date**: 2026-05-03
**Decision**: `Company.status ∈ {screener_candidate, watchlist, dive_history, archived}`. Only `watchlist` and `dive_history` retain data forever. `screener_candidate` rows age out after `Company.retention_days` (default 30; per-screen override `--retain-days N`) via the `screener-cleanup` cron job. The `companyfacts.json` cache TTL is extended to 30 days for top-N tickers to enable cache-reuse if user promotes during the window.
**Why**: User direction: "we are not going to keep the data of the tickers which are not included in either watchlist or deep dive". Storage discipline; the screener is exploratory and the universe is large.
**Cleanup runs**: weekly cron (`screener-cleanup`). Manual via `invest screen cleanup [--dry-run]`.
**See**: `docs/architecture/SCREENER_PIPELINE.md` §2

## DEC-12 — Canonical time anchor on Financial: `period_end_date`

**Date**: 2026-05-03
**Decision**: Add `period_end_date`, `period_start_date`, `filed_date` to `Financial`. `period_end_date` is THE canonical calendar anchor for cross-company decile ranking and frames-based filtering. `fiscal_year` / `period` remain for per-company / report-as-filed analysis. **TTM is computed on demand** by `reader.ttm_at(date)` — never persisted.
**Why**: Companies have different fiscal year-ends (NVDA Jan, AAPL Sep). Cross-company ranking needs calendar alignment. Bloomberg/FactSet store both views; we follow that pattern. Persisting TTM would create dual-source-of-truth drift.
**Empirical validation**: Phase 3c will run frames.json against NVDA's off-calendar fiscal year and document divergence in `docs/architecture/DATA_LAYER.md`.
**See**: `docs/architecture/SCREENER_PIPELINE.md` §3

## DEC-13 — One in-memory exclusion rule set at Tier 3

**Date**: 2026-05-03
**Decision**: Tier 3 applies a single sector/industry exclusion rule set, in memory. A second, curated company-level exclusion list was considered and not built.
**Why**: User direction: the extra list cost calls and run time for little decision value at screen time; company-level exclusions can be applied by hand at watchlist or dive time.
**Since the public release**: the rule set is supplied by the active exclusion policy (`EXCLUSION_POLICY`, default `none`; `screener/policies/README.md`), and verdicts live in `exclusion_verdicts`.
**See**: `docs/architecture/SCREENER_PIPELINE.md` §1

## DEC-14 — Screener split into staged scheduler jobs with per-stage caps

**Date**: 2026-05-03
**Decision**: Three staggered cron jobs replace the single `quarterly-screener` job:
- Stage A: universe + Tier 1–3 (yfinance heavy, `MAX_YF_CONCURRENCY=5`)
- Stage B: Tier 4 frames (~30 SEC calls, `MAX_SEC_CONCURRENCY=5`)
- Stage C: Tier 5–6 (per-ticker companyfacts + ranking)
Each stage checkpoints to a new `screener_stages` table. A failed stage is recoverable via `invest screen run --stage X --run-id Y`.
**Why**: User direction: "perhaps split into multiple cron/scheduler jobs ... with max cap on each scheduler/cron queue". Rate-limit safety, partial-progress recovery, smoother resource usage.
**See**: `docs/architecture/SCREENER_PIPELINE.md` §4

## DEC-15 — Tier 4 is rank-and-narrow, NOT a hard stop

**Date**: 2026-05-04
**Decision**: Tier 4 (SEC frames-driven universe filter) only HARD-DROPS on truly missing data (no CIK, no XBRL data, missing revenue, missing assets). The previously-hard cuts (ROIC<5%, D/E>1.0, FCF<0, OCF<0) become SOFT FLAGS carried forward into Tier 5 via `Tier4Result.flags: list[str]`. Universe narrowing happens via `rank_and_truncate(results, top_n)` — sort survivors by composite quality_score desc, take top N (default 300). Tickers below the cutoff are deferred, NOT marked failed; next run re-evaluates from scratch.
**Why**: User direction: "I'm not comfortable with tier 4 as a hard stop". A single calendar-year snapshot (one bad year, capex cycle, M&A absorption, turnaround story) is too thin a signal to permanently exclude a ticker. The actual hard stops live in Tier 5's 7 gates, which have full Financial history to evaluate against.
**Trade-off**: Tier 5 receives up to 300 candidates instead of ~200 — slightly more companyfacts calls. Acceptable.
**Composite quality score**: ROIC×1.5 + FCF-margin×1.0 + (1 − D/E_capped)×0.5 + revenue_growth×0.5. Each component normalised to [-1, 1] before summing.
**See**: `screener/tier4_frames.py:tier4_quality_score`, `evaluate_tier4`, `rank_and_truncate`

## DEC-16 — Screener becomes a warehouse query (ADR-017 accepted)

**Date**: 2026-05-06
**Decision**: The 6-tier linear screener pipeline is replaced by a wide-table warehouse + per-filter task model. The warehouse is the existing `Company` table widened with one column per filter dimension and a paired `*_fetched_at` column for freshness. Each filter is a `FilterTask` class with three methods: `select_pending(db)`, `fetch_chunk(...)`, `persist(db, results)`. A ~50-line universal `run_task()` runner handles chunking + asyncio.gather + retry/backoff. The screener itself collapses to `screener/query.py:run_screener()` — a SQL builder that reads from the populated warehouse in <1 second. D14's three staggered cron slots survive but their handlers become lists of independent tasks rather than monolithic stage functions.
**Why**: User direction after researching how Finviz / TradingView / Fiscal.ai / StockAnalysis.com architect their production screeners — none use a linear pipeline. The pipeline model breaks down when adding new filters (re-tier debate), composing filter logic, recovering from per-source failures, or letting a user iterate on filter parameters interactively. The warehouse model resolves all four — adding a filter is one column + one task class, filter logic composes via SQL `WHERE`, per-task failures don't block other tasks, and warm-cache reads are <1s.
**Preserves**: D9 (SEC frames as a data source — now `FramesRevenueTask` etc.), D10 (no auto-dive — query never writes to watchlist), D11 (status lifecycle + `retention_days`), D12 (`period_end_date` canonical anchor), D13 (one exclusion rule set at Tier 3), D15 (soft Tier 4 — now per-task quality scoring writing to `composite_score` column).
**Amends**: D14 (three cron slots survive; each is now a list of independent tasks).
**Supersedes**: the linear funnel model of the v2 screener plan (archived). The `screener/stages.py` + `screener/pipeline.py` linear orchestration is deprecated and will be deleted after the warehouse path has shadowed for one quarterly run (per ADR-017 §14 step 5).
**Migration**: forward-compatible. Phase 4a builds the framework alongside existing code (additive — no deletion until Phase 4d).
**See**: `docs/architecture/adrs/ADR-017-screener-as-warehouse-query.md` for the full architecture, task abstraction, runner, query builder, schema migration, and 4-day phase plan.

---

## DEC-17 — Per-chunk persist in the task runner (ADR-020 option b)

**Date**: 2026-05-08
**Decision**: `screener/tasks/runner.py:run_task` now calls `task.persist(db, chunk_results)` immediately after each successful chunk fetch instead of accumulating all chunks' results and persisting once at the end. Persist calls are serialised across concurrent chunks via an `asyncio.Lock` because SQLAlchemy Sessions are loop-bound. Per-chunk persist failures are recorded to `task_failures` and don't crash the whole task.
**Why**: The previous single-shot persist created a process-crash mid-run window where N hours of fetched data could be lost (a 5K-ticker yfinance fill at 1/sec is ~80 minutes and the persist only fires at the end). With per-chunk persist, a crash loses at most one chunk (50 tickers). Universal benefit across every FilterTask — closes Problem P1 from ADR-020.
**Stays inside ADR-017**: no orchestrator state, no DAG, no task-level dependencies, no `select_pending` monkey-patching. Just changes WHEN persist runs, not WHO calls it or WHAT feedback loops exist.
**Trade-off**: TaskResult.processed semantics now mean "rows successfully fetched AND persisted" rather than "rows fetched". A persist failure now counts as a per-chunk failure (recorded to `task_failures` like any other chunk failure). Persist contracts didn't need to change — every existing task's persist was already idempotent and chunk-scoped.
**What stays out of scope**: Problem P2 (Yahoo ban → 4K wasted calls before next cron) is NOT solved by per-chunk persist. Mid-run yf→pg fallback requires either the warden (a parked draft, archived) OR a deeper runner amendment that would formally amend ADR-017. Both options remain available; cron-cadence fallback is the standard behaviour.
**See**: `docs/architecture/adrs/ADR-020-warden-pattern-for-mid-run-fallback.md`

## DEC-18 — ICA auto-integrates into composite scoring; PSA/BEW remain passive

**Date**: 2026-05-09
**Decision**: The "Overlay detector is always passive" rule (CLAUDE.md §4) is split per overlay class. **ICA auto-runs** during the dive flow whenever ICA-* triggers fire — no user confirmation. The result lands in `DeepDiveRun.overlays_results_json` and (via warehouse rollup) `Company.pt_adjusted_roic`. The composite_score formula uses `max(roic, pt_adjusted_roic)` when PT materially exceeds GAAP (≥3pp). **PSA and BEW remain user-gated** — they're interpretive overlays whose output depends on narrative context.
**Why**: ICA is pure deterministic computation against persisted Financial rows (R&D + SG&A history). No API cost. No narrative ambiguity. The original "always passive" rule was too coarse — designed for narrative-heavy overlays, but ICA isn't one. Auto-integration eliminates unnecessary friction and surfaces the academically-defensible economic ROIC at both screener and dive layers.
**Implementation**: `deepdive/orchestrator.py:_persist_dive_results` auto-invokes `overlays/ica.py:run_ica` when triggers fire. `screener/tasks/fundamentals.py:_rollup_warehouse_columns` mirrors the Peters-Taylor calculation at warehouse-rollup time, populating `Company.pt_adjusted_roic`. `screener/tasks/composite.py:compute_composite` accepts `pt_adjusted_roic=` and uses `max(roic, pt)` when PT > GAAP + 3pp. CLI `_prompt_and_run_overlays` skips ICA confirmation; PSA/BEW prompt unchanged.
**Reverts in this turn (Phase 5i drift fixes)**:
  - `INNOVATION_SECTORS` (config/constants.py): reverted from {saas, biotech, semis, deep_tech, pharma, software, technology} → original 5. ICA-2 was being broadened by silent drift.
  - ICA-4 GP/A: ADR-021 §3 said "top 40%"; canonical spec is "top sector tercile". Aligned ADR + detector.py comments.
**See**: `adrs/ADR-021-economic-roic-peters-taylor.md`, migration `j1e2f3a4b5c6_pt_adjusted_roic.py`

---

## DEC-19 — All overlays auto-run + capped composite bonus; F6 feasibility gate widened

**Date**: 2026-05-09
**Decision**: Supersedes D18 partially. **All three overlays (ICA + PSA + BEW) now auto-run** in the dive flow when their triggers fire — no CLI confirmation. Each overlay produces a small, capped additive contribution to the framework-weighted composite (ICA up to 0.6, PSA up to 0.5, BEW up to 0.5; total bonus capped at 1.0). The original "interpretive overlays stay user-gated" half of D18 is reversed.
**Why**: The user-gated CLI prompt was a friction point that prevented PSA/BEW from feeding composite in batch flows or non-interactive shells. Their academic anchors (Cusatis-Desai-Jain, Bessembinder) are sound; the original concern about narrative ambiguity is mitigated by capping the contribution at <10% of the 0-10 composite scale, so a strong framework signal still dominates. Overlay verdict bands are deterministic given persisted data — there is no LLM call.
**Implementation**:
- `deepdive/orchestrator.py`: orchestrator now invokes `run_psa` and `run_bew` in addition to `run_ica` when the corresponding trigger types fire. `_persist_dive_results` populates `FrameworkScore.overlay_psa_run / overlay_bew_run` flags and writes summaries into `overlay_notes`. New `_compute_overlay_composite_bonus()` translates verdicts → capped bonuses (ICA: 0.3 per F5 verdict-band step; PSA: 0.5 strong / 0.25 moderate; BEW: 0.5 extreme / 0.25 moderate). Pro-rates breakdown when raw total exceeds the global cap so the user can see what was clipped.
- `cli/main.py`: confirmation prompt skipped for all three; one-line "Auto-run overlays" summary remains.
- `_render_dive_outcome`: trigger panel relabelled "Overlay triggers detected (auto-executed: ...)". New `_render_roic_summary` panel shows GAAP vs Peters-Taylor non-GAAP ROIC side-by-side with delta.
**F6 feasibility fix (5j-1)**: `deepdive/orchestrator.py:_check_feasibility`'s `have_customer` predicate previously required `customer_concentration_pct IS NOT NULL`. F6's docstring (line 25-26) explicitly treats `state='not_disclosed'` as a positive diversification signal — Patatoukas zero plus a note. Gate widened to `customer_concentration_state IS NOT NULL` so the parser's three valid outcomes (`disclosed_exact`, `parser_uncertain`, `not_disclosed`) are all feasible.
**Goodhart guardrails**: bonuses are absolute additions, not multipliers. Total cap (1.0 / 10.0 = 10%) keeps overlays from dominating composite even in the all-strong case. Pro-rated breakdown surfaces the cap action transparently.
**See**: `deepdive/orchestrator.py:_compute_overlay_composite_bonus`, `cli/main.py:_render_roic_summary`

---

## DEC-20 — Economic ROIC adjustment uses Peters-Taylor, not management non-GAAP

**Date**: 2026-05-09
**Decision**: Economic adjustment of GAAP ROIC for intangible-heavy firms is done via the Peters-Taylor (2017 JFE ★★★) capitalisation of R&D and SG&A — already implemented in `overlays/ica.py`. Management non-GAAP ROIC (SBC + amortization + restructuring add-backs) is **rejected** as a warehouse-level adjustment. The SBC add-back specifically denies real economic dilution; building it as a first-class column would institutionalise the worst SaaS cosmetic.
**Why**: Three-view hierarchy: (1) GAAP = regulatory; (2) management non-GAAP = advocacy; (3) Peters-Taylor = peer-reviewed research. (2) and (3) are NOT the same thing — conflating them is how investors get rinsed. INTA's $103M GAAP→non-GAAP swing is mostly SBC, but the ~10%/yr dilution from those shares is real cash future shareholders must absorb.
**Rejected**: any `Company.non_gaap_roic`, `Company.non_gaap_operating_income`, or `--min-non-gaap-roic` flag.
**Accepted**: `overlays/ica.py` stays canonical at the dive (tier-2) layer; coarse "growth-compounder" multi-factor pre-filter at the screener layer is permitted but must NOT be labelled "non-GAAP ROIC" — it is a Novy-Marx + Sloan + Piotroski-anchored proxy, deliberately distinct.
**Deferred**: `Company.pt_adjusted_roic` warehouse-scale Peters-Taylor (open option per ADR-021 §4.4).
**Reverted in this session**: the universe query script's (archived) `--mode growth-compounder` and `--min-gross-margin` additions from the prior turn — to be re-shipped only after the methodology audit settles.
**Formula**: perpetual-inventory capitalisation of R&D + 25% of SG&A. The ICA overlay fires when |PT − GAAP ROIC| ≥ 3pp.
**Concrete impact**: BFLY GAAP ROIC -110.7% → PT-adjusted -13.9% (gap +96.76pp); TEM gap +109.17pp; LULU gap +4.31pp (ICA-5 fires). All same-methodology, same-source.
**Merged**: this entry absorbs a duplicate record of the same decision logged 2026-05-10 as D17; the duplicate is not retained.
**See**: `adrs/ADR-021-economic-roic-peters-taylor.md`

---

## DEC-21 — ROIC formula fix: NOPAT / (E + D − Cash); pretax_roic added; F6 customer reframe

**Date**: 2026-05-10
**Decision**: The pre-Phase-5k `Company.roic = NetIncome / (TotalEquity + TotalDebt)` formula was wrong on three axes simultaneously: (a) numerator used NetIncome (post-tax, includes interest income from float) instead of NOPAT, (b) denominator did NOT subtract cash, (c) no intangible adjustment knob. This made ROIC incomparable to Peters-Taylor PT-ROIC (where all three differ in opposite directions for SaaS/biotech). Net effect: the prior "GAAP vs Peters-Taylor" comparison was methodologically incoherent — three knobs turned at once, not one.

Replaced with textbook **`ROIC = NOPAT / (Equity + Debt − Cash)`** following Damodaran/McKinsey/Stewart. Effective tax rate derived per fiscal year from `income_tax_expense / pretax_income` with statutory 21% fallback and clamp `[0%, 40%]`. Goodwill stays in IC via Total Equity (Stewart/Mauboussin standard — stripping it flatters serial acquirers). Operating leases (ASC 842) already roll into Total Debt per `edgar_companyfacts.py:643-655` — verified, kept.

Added **`Company.pretax_roic` + `Financial.pretax_roic`** (`EBIT / (E + D − Cash)`) as a third disclosed view — pre-tax ROIC removes ETR variation across companies/years and is the cleanest cross-sectional comparison anchor.

Dropped the misleading "GAAP" label entirely from dive + screener output. The prior formula wasn't textbook GAAP anyway. New three-column rendering: **`ROIC | Pre-tax | Peters-Taylor`**.

**F6 reframe**: `customer_concentration_state='not_disclosed'` is the correct Patatoukas (2012) diversified base case for businesses without top-customer disclosure (PAYC has 36k customers — literally no top customer to disclose). Schema column unchanged; presentation layer relabels to `diversified_base_case` so users and the LLM narrative no longer treat it as a data gap.

**Float-heavy banner**: until `FundsHeldForClients` parser ships (task 5k-5), dive output now warns explicitly when the ticker is in a known float-heavy industry (payroll, payments, insurance) that ROIC is overstated because client-funds interest income remains in `operating_income` AND those funds aren't subtracted from IC.

**Implementation**:
- `data/pipeline.py`: new `_effective_tax_rate()` helper + rewritten ROIC computation in `_apply_financial_row`.
- `data/reader.py`: snapshot helper aligned to same formula.
- `data/models/schema.py`: `Company.pretax_roic` + `Company.pretax_roic_fetched_at` + `Financial.pretax_roic` added with intent comments.
- `alembic/versions/k2f3a4b5c6d7_pretax_roic.py`: schema migration.
- `cli/main.py:_render_roic_summary`: three-view rendering + float-heavy banner.
- `deepdive/scorecard_view.py`: F6 `not_disclosed` → `diversified_base_case` relabel at presentation layer.
- The universe query script (archived): ROIC | Pre-tax | PT columns + footer methodology block.

**Bulk recompute deferred** per user instruction: do not re-run FundamentalsTask + CompositeScoreTask until Phase 5k-5 (FundsHeldForClients parser), 5k-6 (PatentsView for F3 patent-citation), and 5k-7 (NRR regex for F6) all land. The transition strategy in `_render_roic_summary` reads the latest `Financial.roic` + `Financial.pretax_roic` directly when warehouse columns are stale, so individual dives surface the corrected number immediately.

**What was NOT shipped in 5k-1..4** (queued):
- ~~5k-5 `FundsHeldForClients` parser + IC handling~~ — **shipped 2026-05-10**
- ~~5k-6 PatentsView integration~~ — **shipped 2026-05-10 as 5k-6 partial** (10-K text fallback). Full USPTO API integration queued as **5k-6b** pending user-side `USPTO_API_KEY`.
- ~~5k-7 NRR/GRR regex over 10-K MD&A free text for F6~~ — **shipped 2026-05-10**
- 5k-8 bulk recompute — UNBLOCKED. User can now run when ready (will be re-blocked on 5k-6b if user wants the full HHL signal first).
- ~~5k-9 ADP-style operating_income XBRL alias gap~~ — **shipped 2026-05-10**

## DEC-22 — Persistent conversational dive (`invest chat TICKER`)

**Date**: 2026-05-10
**Decision**: Build a multi-turn LLM Q&A on top of the existing one-shot narrative path. Same hard constraints as `narrative.py`: every numeric value in the assistant reply must come with a `field_path` into the dive's frozen `ScorecardView` JSON, validated by walking the path. Mismatches surface as guard warnings, not silent corruption.
**Why**: The one-shot bull/bear/risks narrative answers "what does the data say" once; users want "let me dig in" — follow-up questions, comparisons across frameworks, "what would change my mind" thinking. This is also the prototype for a planned feature, The Boardroom (Q&A with investor personas + conviction scoring).
**Architecture**:
- `deepdive/conversation.py` — `ChatTurnOutput` Pydantic schema (reply + numeric_claims), `generate_chat_response()` with provider routing mirroring narrative.py, `validate_chat_turn()` reusing `narrative_guard._walk_path` for field-path validation.
- `deep_dive_conversations` table (migration `o6d7e8f9a0b1`) — append-only audit log, one row per turn keyed by `(deep_dive_run_id, turn_index)`. Stores role, content, numeric_claims_json, guard_warnings_json, provider/model, token counts, cost_usd.
- `cli/main.py:chat` — REPL command. Loads latest `DeepDiveRun` for the ticker (or `--run-id`), opens stdin loop. Slash commands: `/budget`, `/history`, `/clear`, `/exit`. Sliding context window of last 8 turns to bound prompt cost as conversations grow.
- Provider stack: OpenAI primary by default, Anthropic Sonnet 4.6 fallback (Haiku 4.5 unreliable for tool-use schema fills). User-pinnable via `--provider anthropic_only`.
**Why ground in a frozen `ScorecardView`**: the conversation is a snapshot interrogation, not a live data feed. Re-dive creates a new run + a fresh conversation; old conversations stay queryable as historical artifacts. Avoids the "the data we discussed yesterday no longer matches today" bug where multi-day chats drift against changing fundamentals.
**Budget cap**: per-session default $2 USD, warns at 50%, halts at 100% with continue-prompt that adds $1 buffer if confirmed. Cost rates table in `_PRICING_USD_PER_M` covers Sonnet/Haiku/4o/4o-mini.
**Empirical cost**: ~$0.02-0.025 per turn for Sonnet 4.6 at typical ScorecardView size (~5k input tokens). $2 budget ≈ 80-100 turns of headroom.
**Smoke validation (PAYC)**: 4 turns spanning two CLI invocations, resumed cleanly, multi-turn coherence (replies reference earlier turn framings without re-grounding), zero guard warnings, all numeric claims resolved into ScorecardView paths.
**Forward path to Boardroom**: the conversation_log JSON shape is intentionally portable — same numeric_claim schema as `narrative.py`, same field_path validator. Adding the persona layer (Architect/Engineer/Contrarian) means selecting per-turn `system_prompt_persona` rather than rebuilding the data path.
**See**: `deepdive/conversation.py`, `cli/main.py:_chat_async`, migration `o6d7e8f9a0b1`.

---

**5k-6 partial addendum (2026-05-10)**: F3 patent disclosure via 10-K text regex.
- **External finding**: PatentsView (the free no-key API) was decommissioned in 2024 — `api.patentsview.org` redirects to a USPTO transition guide, and `search.patentsview.org` no longer resolves via DNS. The replacement, `api.uspto.gov`, returns 403 without authentication and requires a developer-portal API key (user-side action: register at developer.uspto.gov). My original 2-3 day estimate for 5k-6 was based on the no-key PatentsView path that no longer exists.
- **Honest scope adjustment**: Shipped a partial solution — `parse_patent_count()` regex parser in `data/edgar_text_parser.py` captures self-reported portfolio sizes from 10-K narrative ("approximately 25,000 issued patents", "patent portfolio of 1,200 patents", etc.) with negation suppression and value-range gating (1 ≤ count ≤ 200,000). New `Financial.patent_count_disclosed` + `Financial.patent_disclosure_state` columns (migration `n5c6d7e8f9a0`). F3 `_compute_patent_disclosure` scores 1.0pt for ≥1000 patents, 0.5pt for ≥100 patents, 0pt below or `not_disclosed`. Scorecard view extended to surface the count.
- **Empirical hit rate**: Lower than expected. Big-tech (QCOM, INTC, IBM tested) increasingly describe portfolios qualitatively ("extensive", "vast majority", "broad coverage") without integer counts — modern 10-K disclosure norm trend. Regex correctly returns `not_disclosed` for these. Hit rate likely concentrated in mid-cap pharma/biotech and older filers that still quantify.
- **Full HHL signal SHELVED (2026-05-10)**: `developer.uspto.gov` requires US-side ID verification (SSN-tied developer account). That is a structural access blocker for this project, not a TODO. The schema is in place if a future contributor with US access wants to add the integration; alternatives (Google Patents BigQuery, EPO OPS, Lens.org) exist if F3's patent gap ever becomes critical enough to reach for them. F3 stays at the 10-K text-regex fallback indefinitely.

**5k-7 + 5k-9 addenda (2026-05-10)**: F6 NRR/GRR + ADP-style operating_income parser.
- 5k-7: Added `Financial.nrr_pct`, `Financial.grr_pct`, `Financial.retention_state`, `Financial.retention_fetched_at` (migration `m4b5c6d7e8f9`). New `parse_retention_metrics()` regex parser in `data/edgar_text_parser.py` matching "net (revenue|dollar) retention", "dollar-based net retention", "NRR", "NDRR", "net expansion rate", "gross retention" with proximity rules + negation suppression + value-range gating (NRR 60-200%, GRR 50-110%). New `fetch_edgar_retention_metrics()` reuses the same TenK section reader as customer concentration. F6 score function replaces the 0-points NRR/GRR data-gap stubs with `_compute_nrr` + `_compute_grr` (NRR ≥110% best-in-class → 1.0pt, ≥100% stable → 0.5pt; GRR ≥90% best-in-class → 1.0pt, ≥85% acceptable → 0.5pt). Empirical hit rate validated on Snowflake (NRR=125%) and Insight Enterprises (Cloud NRR=120%); PAYC + ServiceNow correctly classified `not_disclosed` (PAYC: payroll, no NRR concept; NOW: uses "renewal rate" terminology not yet matched). Scorecard view extended to surface NRR/GRR rows in F6 with band labels.
- 5k-9: ADP-style `operating_income` derivation. ADP doesn't tag `OperatingIncomeLoss` directly; only reports geo-split `IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic / Foreign` plus aggregate `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`. New parser fields `pretax_income`, `pretax_income_domestic`, `pretax_income_foreign`, `nonoperating_income_expense` enable derivation: `operating_income = pretax_income − nonoperating_income_expense` when `OperatingIncomeLoss` is absent. Verified on ADP (FY2025 derived OI ≈ $4,956M; F5 score lifted 3.5 → 6.5; ROIC = 49.22% post-5k-5 float adjustment). Same fallback applies to FLT, V, MA, etc., though those filers also report `OperatingIncomeLoss` directly.

**5k-5 addendum (2026-05-10)**: Float-related disclosures landed.
- `Financial.funds_held_for_clients` + `Financial.investment_income_interest` columns added (migration `l3a4b5c6d7e8`).
- Parser maps `FundsHeldForClients` (PAYC-style) → `RestrictedCashAndCashEquivalents` (fallback) and `InvestmentIncomeInterest` (ADP-style) → `InterestIncomeOperating` (fallback).
- ROIC numerator subtraction is **industry-aware**: applied at the dive renderer + warehouse rollup layers when ticker is non-insurer AND `investment_income_interest > 0`. Insurers (industry starts with "Insurance") keep float in operating ROIC because investment income IS their business — Buffett-on-insurance-float retained, NOT stripped.
- Per-period `Financial.roic` is intentionally industry-blind (operating-income-as-reported); the adjustment is applied at the consumption boundary so the same Financial row serves both insurer and non-insurer screens correctly.
- PAYC empirical finding: `cash_and_equivalents = $370M` correctly excludes the $5.14B `FundsHeldForClients`; PAYC reports float interest below operating income (in `OtherNonoperatingIncomeExpense`), so `OperatingIncomeLoss = $567M` is already clean. PAYC's post-5k-1 ROIC of 28.60% is methodologically correct — the prior banner was over-conservative.
- ADP empirical finding: reports `InvestmentIncomeInterest = $319.5M` discretely; would auto-adjust IF its `OperatingIncomeLoss` were tagged. ADP currently doesn't report that concept, exposing a separate parser-coverage gap (out of 5k-5 scope).
- Banner refined: shows magnitudes for both float fields, plus a status indicator — `✓ ROIC numerator auto-adjusted` (subtraction applied), insurer-retention note, or "no XBRL fact" warning when the parser found nothing for a known float-heavy ticker.

**Goodhart safeguards**: ROIC + pretax_roic + pt_adjusted_roic shown side-by-side by default. No single column drives the verdict; composite already caps overlay bonus at 1.0 (D19). Adding an SBC-capitalisation knob is explicitly REJECTED per user — Mauboussin/Damodaran consensus that SBC is a real expense; PT methodology already excludes SBC capitalisation.

**See**: `data/pipeline.py:_effective_tax_rate`, `_apply_financial_row`; migration `k2f3a4b5c6d7_pretax_roic.py`

---

## DEC-23 — Hold philosophy: forever-default, 5-year minimum reconsideration

**Date**: 2026-05-11
**Decision**: Codify the latticework-convergent hold logic into the narrative layer and CLI rendering. Default state is hold forever. The reconsideration window opens at 5 years — years 1-4 are early-warning monitoring only. Risk-factor outputs are reframed as **thesis-validation checkpoints** (conditions to monitor across the hold), NOT stop-loss triggers (price levels to exit at).
**Why this convergence is load-bearing**: Six independent thinkers across 80+ years arrive at the same operational answer when asked "what holding period optimises long-term compounding?":
- Buffett/Munger — "Our favourite holding period is forever"
- Nick Sleep — scale-economies-shared compounds indefinitely
- Chuck Akre — three-legged stool: business + management + reinvestment runway
- Terry Smith — "buy good companies, don't overpay, do nothing" (sub-2% turnover)
- Tom Russo — "capacity to suffer" — tolerate drawdowns for long-duration capture
- Bessembinder (2018, JFE ★★★) — empirical: 4% of stocks deliver all market wealth across rolling 5-15 year windows

Six different vocabularies, one operational prescription. The convergence isn't coincidence — it's what truth looks like when triangulated through independent lenses. The latticework gives conviction that survives a 50% drawdown; any single framework taken alone won't. Bessembinder's data is brutally explicit on this — the entire wealth-creation distribution sits in the long right tail you'd never reach if you exit on conventional valuation triggers.

**What this means for risk-factor framing**: Stop-loss-on-valuation-mean-reversion is the most expensive mistake retail investors make — they truncate extreme winners at 2-3x because the chart "looks expensive". The narrative layer must NOT recommend price-level exits. Risks are described as conditions to MONITOR over years 1-5, with high-severity items reserved for thesis-BREAK conditions (structural moat breach, fraud, terminal disruption, capital-allocator failure — Outsiders 8 traits inverted), not mark-to-market noise.

**Implementation**:
- `deepdive/narrative.py` `_SYSTEM_PROMPT` adds rule #10 (HOLD-LOGIC FRAMING) instructing the LLM to phrase risks as thesis-validation checkpoints and bear points as structural-headwind analysis.
- `cli/main.py` narrative renderer relabels the "Risk Factors" panel → "Thesis-Validation Checkpoints" with an italic footnote: "conditions to monitor across the 5-year hold, NOT stop-loss triggers (D22)".
- Schema unchanged — `RiskFactor.factor` / `severity` / `grounded_in` stay. Persisted narratives stay readable across the rename. The reframing happens at LLM-output time and at display time, not at the data layer.
- D24's yearly checkpoint cron is the operational instrument that compiles the year-over-year warning signals (composite drops, framework regressions, PT-ROIC erosion, BEW band drops). D22 is the philosophy; D24 is its scheduled execution layer.

**What this does NOT do**:
- No automatic exits, no portfolio-rebalancing logic, no position-sizing changes. The system stays a research-and-monitoring tool; portfolio actions remain the human's job. The hold-philosophy reframe is a *framing change* in how the LLM and CLI present analytical output — it doesn't move money.
- Mental-model latticework weaving (#6 from the Phase-5 plan) stays shelved. The latticework is already invoked in narrative rule #9 (ADR-023 reasoning blocks); explicit per-model citations across framework docs is deferred.

**See**: `deepdive/narrative.py:_SYSTEM_PROMPT` rule #10, `cli/main.py` narrative renderer panel title.

---

## DEC-24 — TTM/MRQ/FY three-tier data freshness; 10-Q text reader (ADR-026)

**Date**: 2026-05-11
**Decision**: Per ADR-026. Adopt the institutional three-tier data model:
- **LTM** (rolling 4 quarters) for current-state ratios — ROIC, FCF margin, GP/A, Debt/EBITDA.
- **MRQ** (most recent quarter) for balance-sheet snapshots — cash, debt, equity, IC.
- **FY** (latest annual) for academic-framework anchors and multi-year trajectories.
- **10-Q text reader** added alongside existing 10-K reader for SaaS-specific MD&A disclosures (NRR, GRR, Cloud ARR, Total ARR) which refresh quarterly.

**Why**: The user's INTA cross-check (May 2026) found that our previous annual-default produced a 6-11 month freshness gap — Cloud NRR read 120% when reality was 123%, R&D intensity 27.3% vs reality 29%, revenue growth 17% vs 13% quarterly run-rate. Cloud ARR ($459M, the forward-looking SaaS metric) wasn't extracted at all. Industry standard (Bloomberg/FactSet/Morningstar) is LTM for ratios, MRQ for snapshots, FY for trajectories. We're adopting the standard.

**Implementation (Phase 5Q)**:
- `data/reader.py` — `CompanyDataReader.ttm()` + `.mrq()` public methods. `mrq()` sorts by `period_end_date.desc()` (fixing a latent bug where the legacy `_financials` sort returned Q1 first within a fiscal year).
- `data/edgar_fetcher.py` — `fetch_latest_10q_filing()` + `_read_tenq_sections()` mirroring 10-K patterns. `fetch_edgar_retention_metrics()` + `fetch_edgar_arr_metrics()` read BOTH 10-K and 10-Q, take the freshest disclosure (10-Q wins by filing date in normal cases).
- `data/edgar_text_parser.py` — `parse_arr_metrics()` with separate Cloud-ARR and Total-ARR regex patterns, proximity-gated growth-rate attribution, value-range validation (1M-100B), unit normalisation (million/billion).
- `data/models/schema.py` + migration `q8e9f0a1b2c3` — `Financial.cloud_arr_usd`, `cloud_arr_growth_yoy_pct`, `total_arr_usd`, `total_arr_growth_yoy_pct`, `arr_state`, `arr_fetched_at`.
- `frameworks/base.py` — new `DataRequirement.needs_arr_metrics` flag.
- `frameworks/f5_growth_quality.py` — current-state ratio signals (FCF margin, ROIC, GP/A, Debt/EBITDA) now use `reader.ttm()` with fallback to latest annual. Revenue CAGR + buyback yield stay on annuals. Each signal carries a `source` field (`"LTM"` or `"FY annual"`). New `arr_disclosure` signal block surfaces Cloud + Total ARR for transparency (display-only, not scored — calibration of ARR-growth bands deferred).
- `TTMSnapshot` extended with `ebitda` (op_inc + D&A) and `debt_to_ebitda` (MRQ debt / LTM EBITDA), `pretax_roic` properly populated.

**Empirical validation on INTA (May 2026 cross-check)**:
- NRR: stale 120% → fresh **123%** (from Q3 FY26 10-Q MD&A) ✓
- Cloud ARR: not extracted → **$459.3M, +31% YoY** (exact match to earnings call) ✓
- Total ARR: not extracted → **$559.9M, +23% YoY** (exact match) ✓
- ROIC: stale -9.43% (FY25 annual) → LTM -16.93% (captures Q3 FY26 deterioration that annual hides) ✓
- F5 score: 5.5 → 4.5 (correctly reflects the fresher, weaker LTM ROIC instead of the stale annual)

The score drop on INTA isn't a bug — it's the staleness correction. The composite was reading INTA based on June 2025 numbers when March 2026 reality is materially weaker. Now it reflects reality.

**What this does NOT do**:
- No quarterly framework scoring — F1, F3, F5, F7 still emit per-annual scores. Only current-state inputs shifted to LTM.
- No full per-claim source-provenance infrastructure (Layer 2 deferred). F5 signals carry a per-signal `source` tag (LTM vs FY annual); other frameworks unchanged.
- No streaming/real-time data. 10-Q files ~45 days after quarter-end — that's the freshness ceiling.
- No backfill of existing DeepDiveRun rows. They stay as-is per the audit trail rule. Re-diving any ticker after 5Q ships populates the new fields automatically.

**Access pattern**: `reader.ttm_at(date)` is canonical.
**Merged**: this entry absorbs a duplicate record of the same decision logged 2026-05-14 as D22; the duplicate is not retained.
**See**: ADR-026 (full decision record), migration `q8e9f0a1b2c3_arr_metrics.py`.

---

## DEC-25 — Portfolio concept separate from watchlist; annual reassessment cron

**Date**: 2026-05-11
**Decision**: Introduce `PortfolioPosition` as a structurally distinct concept from `WatchlistEntry`. New table, new CLI namespace (`invest portfolio`), new scheduler job type (`portfolio_reassessment`). New migration `p7d8e9f0a1b2`.

**Why two separate tables**: `WatchlistEntry` tracks CANDIDATES (names being researched, may buy). `PortfolioPosition` tracks HOLDINGS (names actually owned, with cost basis and entry_date). Different lifecycle, different field needs, different reassessment cadence. Conflating them under a single table with a `role` enum loses the semantic distinction and pollutes queries — when you ask "what are my holdings?" you want zero risk of accidentally including watchlist-only names.

**Schema**:
- `entry_date` (NOT NULL) — anchors the D22 5-year reconsideration window. Years 1-4 are monitoring-only; year 5+ opens reconsideration.
- `role` — `core` | `satellite` | `hedge`. Soft classification; doesn't affect reassessment cadence (every active position dives equally).
- `shares`, `cost_basis_usd`, `cost_basis_per_share` — optional. NULL just means the system doesn't render position-level economics.
- `thesis` — free text. The "original story" against which Lynch's story-break test compares at reassessment.
- `is_active` — append-only audit trail. `remove` flips this to False + sets `exited_at`; never deletes the row. A position held 3 years then sold should remain queryable as a learning artifact.

**CLI commands** (`cli/main.py`):
- `invest portfolio add TICKER --since YYYY-MM-DD [--role X --shares N --cost-basis-usd X --thesis "..."]`
- `invest portfolio list [--include-inactive]` — renders years-held + D22 reconsideration-window status per position.
- `invest portfolio update TICKER --since X --role Y ...`
- `invest portfolio remove TICKER --note "exit reason"` — audit-preserving.
- `invest portfolio show TICKER` — detail panel with D22-window status + thesis.

**Annual reassessment scheduler** (5P-3 / `scheduler/jobs.py:_run_portfolio_reassessment_job`):
- New job type `portfolio_reassessment`. Default cron `0 8 1 3 *` = Mar 1 at 08:00 system local (earliest after 10-K filing season; portfolio reassessed BEFORE watchlist's Mar 15 since holdings are higher priority than candidates).
- For each active PortfolioPosition: runs tier-1 dive (all 7 frameworks + auto-overlays — BEW mandatory per D23, ICA/PSA trigger-gated, SIM soft overlay for tech), then `build_checkpoint_report` for year-over-year warning detection (same D24 detector — composite/F5/PT-ROIC erosion, verdict downgrades, BEW band drops, ICA-5 newly firing), then logs per-position context including years_held + D22-window status + original thesis text (so the human reviewer can run Lynch's story-break test against the baseline).
- Warnings SURFACED, never actioned (per D22). Mental-model latticework invoked at narrative-output time when the user later runs `invest score-card --narrate`.

**Initial population**: User's 7 portfolio tickers — LULU, NVDA, PATH, HIMS, FIG, MRVL, NBIS — added 2026-05-11 with today as placeholder `entry_date`. The user updates actual entry dates via `invest portfolio update TICKER --since YYYY-MM-DD`. Placeholder `notes` field reminds them to do so.

**Three crons now registered**:
| Name | Cron | Target |
|---|---|---|
| `hims-q1-fy26` | `0 8 12 5 *` | One-off HIMS Q1 earnings dive (May 12) |
| `annual-health-check` | `0 8 15 3 *` | D24 — active WatchlistEntry |
| `annual-portfolio-reassessment` | `0 8 1 3 *` | D25 — active PortfolioPosition |

**Why no ADR**: like D24, this is straightforward additive infrastructure (new table, new CLI, new scheduler dispatcher — all following the patterns already established by WatchlistEntry + D24's checkpoint job). The architectural decision is the *concept separation*, which D25 itself documents.

**See**: `data/models/schema.py:PortfolioPosition`, `cli/main.py:portfolio_app`, `scheduler/jobs.py:register_portfolio_reassessment_job` + `_run_portfolio_reassessment_job`, migration `p7d8e9f0a1b2_portfolio_positions.py`.

---

## DEC-26 — Yearly watchlist checkpoint with warning-signal detection

**Date**: 2026-05-11
**Decision**: Add a `checkpoint` job type to the scheduler. Runs once per year (default Mar 15 08:00 — post 10-K filing season). For each active `WatchlistEntry`: (a) runs a fresh tier-1 deep-dive, (b) compares the new `DeepDiveRun` against the most-recent prior run ≥ 305 days old (~10 months — avoids same-quarter noise), (c) emits structured warning signals. New module `deepdive/checkpoint.py` implements `detect_warnings()` + `build_checkpoint_report()`. New CLI: `invest scheduler add-checkpoint NAME --cron "0 8 15 3 *"`.
**Why**: User's hold philosophy (D22 forthcoming — forever-default, 5-year minimum reconsideration) requires an EARLY-WARNING instrument distinct from stop-loss logic. Stop-losses don't fire on mark-to-market noise. But fundamentals genuinely cracking (composite drops 2pts, F5 erodes, verdict downgrades, PT-ROIC erodes 3pp) is signal worth surfacing — without firing an automatic exit. Reading the warnings is the human's job; the cron just compiles them.
**Warning categories** (severity bands):
- **HIGH**: framework_verdict downgrade (initiate→watchlist→monitor→exclude); composite drop ≥ 1.5; F5 Growth Quality drop ≥ 2.0 (F5 is the moat signal — its erosion is structural).
- **MEDIUM**: any other framework drop ≥ 2.0; PT-adjusted ROIC drop ≥ 3pp; BEW band drop (extreme → moderate → no-pattern).
- **LOW**: ICA-5 trigger newly firing (PT vs GAAP gap widened past 3pp — methodology now materially affects the moat read).
**Scope-tight by intent**: this is NOT a screener-wide rerun. Only `WatchlistEntry.is_active=True` is dived — tickers the user has actively elevated past universe screening. Per the user's preference: "deep dive only the watchlist tickers" — keeps cron cost bounded (typical watchlist size 10-50 names; ~10-20 min wall clock vs hours for the universe).
**Warnings are SURFACED, not actioned**: logger emits structured per-ticker reports + a summary line at end. No DB writes beyond the DeepDiveRun rows the dives produce. No auto-exit, no auto-rebalance, no auto-notification. The user reads the logs Mar 15 morning, decides per name. Compatible with the broader hold philosophy where year-1..4 are reassessment-only and year-5+ opens the reconsideration window.
**Default cron**: `0 8 15 3 *` — Mar 15 at 08:00 system local, post 10-K filing season (most US listings file 10-K by late Feb / mid-Mar; this timing ensures the dives use the freshest annual data).
**Why no ADR**: this is straightforward analytics over existing rows (no schema changes, no architectural shift). The existing scheduler `job_type` field already supports new dispatchers — adding `checkpoint` follows the same pattern as `deepdive`. D24 itself documents the contract.
**See**: `deepdive/checkpoint.py`, `scheduler/jobs.py:_run_checkpoint_job` + `register_checkpoint_job`, `cli/main.py:scheduler_add_checkpoint`.

---

## DEC-27 — BEW mandatory on every dive; ICA/PSA stay trigger-gated; SIM scoped to AI-tech sub-universe

**Date**: 2026-05-11
**Decision (BEW mandatory)**: Partially supersedes D19. ICA and PSA remain trigger-gated (they fire only when their detector conditions match — ICA-1..5, PSA-1..4). BEW now runs **on every dive regardless of trigger conditions**. The BEW invocation moves out of the `if "BEW" in triggered_types:` gate in `deepdive/orchestrator.py`; it's always called inside the same try/except. Composite bonus rules unchanged (BEW contributes 0 for `no_winner_pattern` verdicts, capped 0.5 for `moderate`, 0.5 for `EXTREME_WINNER_CANDIDATE`).
**Why mandatory**: Bessembinder's empirical work (1926-2016, JFE ★★★) shows ~4% of stocks produce all market wealth creation. Every long-horizon investor must confront the question "is this name in the 4% or the 96%?" on every dive — making it conditional on trigger fires hides this question on most names. The user's holding philosophy ("favourite holding period is forever, 5-year minimum reconsideration") is structurally incompatible with stop-loss-on-valuation-mean-reversion logic, so the Bessembinder lens needs to be present by default.
**Honest about data gaps**: BEW has known unevaluable checks — TAM ratio (BEW-F) and sector-median EV/Rev (BEW-E) aren't warehoused. CLI display now surfaces `score/n_evaluable` (e.g. "Score: 3/6 evaluable checks · 7 total · TAM + sector-EV/Rev not warehoused"). Mandatory execution shouldn't produce false-negative reads on partial-data tickers.
**Implementation**: ~10 lines changed in `deepdive/orchestrator.py` (move BEW invocation outside the trigger conditional; add `auto_overlay_results` field on `DeepDiveOutcome` so the renderer can show it uniformly). CLI `_render_dive_outcome` adds a BEW panel that always renders, with verdict + hold-period guidance + evaluable-check disclosure. Smoke-tested on PAYC (`no_winner_pattern, 2/6 evaluable`) and HIMS (`no_winner_pattern, 3/6 evaluable`).

**Decision (SIM scope)**: New SIM (Structural Intelligence Moat) framework — when built — will be:
- **Deep-dive only** (NOT a screener pre-filter — Constellation Software, Costco, Visa would all fail SIM but sit in Bessembinder's 4%; pre-screening risks systematic exclusion of non-AI compounders).
- **Scoped to technology-sector tickers** (SIC-derived sector OR yfinance industry starts with "Software"/"Information Technology Services"/"Semiconductors" etc.). Non-tech tickers don't even compute SIM.
- **Soft gate / overlay output** — produces a separate scorecard panel with the 5 binary tests, NOT a hard exclusion. The user reads SIM verdict alongside F1-F7 and weighs both.
- **NOT part of composite_score** — SIM scores are presented but never feed the 0-10 composite. Avoids polluting the academically-validated framework weights with a ◯-tier architectural hypothesis.
- **Epistemic tier ◯** — explicitly tagged as "architectural hypothesis, no academic validation". Same convention as F6 NRR/GRR practitioner heuristics. Once the literature catches up (5-10 years on AI-native moats), the tier can be upgraded.

**5N addendum (2026-05-11)**: SIM overlay shipped. `overlays/sim.py` with `run_sim()`, tech-sector gate via `is_ai_relevant_sector()`, two auto-detected tests (SIM-3 ontology/knowledge-graph keyword regex over 10-K Item 1+7; SIM-5 domain-narrowness heuristic from industry string + Item 1 vertical-vs-horizontal phrasing), three manual_review placeholders (SIM-1/2/4 — structural embeddedness, proprietary knowledge accumulation, intelligence compounding). Verdict bands: `auto_passes_ontology_and_narrowness` (2/2), `auto_partial_one_test_only` (1/2), `auto_fails_no_ontology_signal` (0/2). Calibration validated on three cases: PLTR passes 2/2 (canonical ontology-native), ADBE 1/2 (narrow but no ontology), PAYC 1/2 (narrow but traditional HCM SaaS). SIM verdict NEVER enters composite_score; surfaces as its own CLI panel. Healthcare/biotech tickers (HIMS smoke-tested) correctly skip SIM via the sector gate.

**See**: `deepdive/orchestrator.py` (BEW unconditional invocation, `auto_overlay_results` on outcome), `cli/main.py:_render_dive_outcome` (BEW mandatory panel).

---

## DEC-28 — Methodology disclosure + source provenance mandatory

**Date**: 2026-05-11
**Decision**: Every numeric output in the dive must be traceable to its source via methodology citations + per-field source tags. No black-box "adjusted" numbers; if it's not from raw XBRL or self-computed from primitives, it doesn't ship.
**See**: `ADR-022-methodology-disclosure-and-source-provenance.md`.

---

## DEC-29 — Phase 5R: data-quality signals (SBC, goodwill, dilution, revenue trajectory)

**Date**: 2026-05-12
**Decision**: Ship four data-quality signals as display-only F5 sub-signals + year-over-year warning detectors. Direct response to the INTA cross-check (May 2026) which exposed gaps the prior framework missed.

**The four signals**:

1. **SBC intensity (`sbc_intensity`)** — `share_based_compensation / revenue`. Bands: ≤10% healthy, 10-20% concerning, ≥20% red flag. Per ADR-021 we do NOT add SBC back to operating income for ROIC; this signal surfaces the dilution magnitude as a separate read. Damodaran/Mauboussin: SBC is real cost; "non-GAAP profitability" headlines are SBC add-backs.

2. **Goodwill concentration (`goodwill_concentration`)** — `goodwill / total_assets`. Bands: <15% organic, 15-40% moderate M&A, ≥40% serial acquirer. Per D20 goodwill stays in IC (Stewart standard); this signal flags acquisitive-growth profiles for separate capital-allocator evaluation.

3. **Share dilution (`share_dilution`)** — YoY change in `shares_outstanding`, plus cumulative change across the persisted history. Bands: ≥5% net dilution/yr `high_dilution`, 2-5% `moderate_dilution`, ±2% flat, ≤-2% net buyback `net_accretive`. Outsiders capital-allocator inversion check.

4. **Revenue trajectory (`revenue_trajectory`)** — monotonic-deceleration detector across last 4 periods (3 annuals + LTM). Bands: `decelerating` (monotonic + >30% growth-rate compression — Lynch story-break candidate), `mildly_decelerating`, `lumpy_decline`, `stable_or_accelerating`.

**Why display-only, not scoring**: Calibrating "how many points should F5 deduct for SBC at 17% vs 25%" requires a calibration study that isn't in scope. Surfacing the signal honestly with a banded interpretation lets the reader apply latticework judgment (Outsiders capital-allocator, Mauboussin expectations, Lynch story-break) without the system pretending a precision it doesn't have. Same pattern as ADR-026's ARR signal.

**Year-over-year detection (5R-4)**: `deepdive/checkpoint.py:_detect_5r_warnings()` extends D24/D25's warning detector. Emits MEDIUM warnings on:
- SBC intensity rising YoY ≥3pp
- Goodwill concentration rising YoY ≥5pp (significant M&A this period)
- Share dilution accelerating ≥2pp (Outsiders inversion)
- Revenue trajectory newly firing `decelerating` band (Lynch trip)

**Schema**: migration `r9f0a1b2c3d4` adds `Financial.share_based_compensation`, `sbc_pct_of_revenue`, `goodwill`, `goodwill_pct_of_assets`. XBRL tags `ShareBasedCompensation` + `Goodwill` mapped in `edgar_companyfacts.py`. Derived ratios computed in `_apply_financial_row`.

**Empirical validation on INTA (FY2025 data)**:
- SBC: $88.1M = **17.47% of revenue** → `concerning` band (LTM hits 19.5%, on the boundary of `red_flag`)
- Goodwill: $326.3M = **36.49% of total assets** → `moderate_m_and_a` (LTM after Q3 acquisitions: ~46%)
- Share dilution: **+33.64% cumulative, 10.22%/yr average** (61M → 82M shares across 3 annuals) → `high_dilution`
- Revenue trajectory: **29.0% → 22.7% → 17.1% → 10.0% LTM** — `decelerating`, monotonic, latest is 34% of earliest (well below 70% threshold) → **Lynch story-break candidate**

The revenue trajectory detection matches the user's exact diagnosis from the cross-check ("29% → 23% → 17% → 13%"). All four signals now structurally observable in the dive output — the integrity gaps from the INTA review are closed.

**Files touched**:
- `data/edgar_companyfacts.py` — new XBRL tag mappings
- `data/edgar_fetcher.py:EdgarFinancialRow` — new fields
- `data/pipeline.py:_apply_financial_row` — copy + derive
- `data/models/schema.py:Financial` — 4 new columns
- `alembic/versions/r9f0a1b2c3d4_*.py` — migration
- `frameworks/f5_growth_quality.py` — 4 new signal helpers + integration into `score_f5`
- `deepdive/checkpoint.py` — `_detect_5r_warnings()` + `_parse_f5_signals()`

---

## DEC-30 — Narrative LLM personality + structured output (D22 hold-philosophy)

**Date**: 2026-05-12
**Decision**: `deepdive/narrative.py` is the ONLY permitted Anthropic call site for narrative generation (the second site `deepdive/external_signals.py` is added later by D26). Narrative LLM is bound by ADR-023 §1.3 reasoning order (Inversion → Circle of Competence → Moat Direction → Capital Allocator → Lunch-Eating Test → Probabilistic Base Rate), §1.5 forbidden-language list (no "buy/sell/hold", no "compelling/attractive/tailwinds"), and §10 D22 hold-philosophy framing (forever-default, 5-year minimum reconsideration, risks-as-monitoring-checkpoints not stop-loss triggers). Structured output validated by `narrative_guard.py`.
**See**: `ADR-023-narrative-personality-spec.md`.

---

## DEC-31 — Mental-models lattice library + composition pipeline

**Date**: 2026-05-13
**Decision**: 111 mental models organized across 16 domain directories under `mental_models/`. Every model has mandatory frontmatter (slug, name, school, citation_tier, always_load, related_models, code_consequences) + mandatory body sections (Summary, Inversion form). Composer `deepdive/mental_model_composer.py:select_models_for_dive()` derives a `LatticeProfile` from the deterministic `ScorecardView` and selects a subset within a token budget. Skill mental_model references are documentary-only (typo-caught by `mental_model_refs.py`).
**See**: `ADR-024-mental-models-library-and-composition.md`.

---

## DEC-32 — IFRS / FPI universe support

**Date**: 2026-05-14
**Decision**: Foreign Private Issuers (FPIs) and IFRS-reporting filers are first-class citizens. edgartools `Company.is_foreign` is the primary FPI detection signal (with 40-F/20-F filing-history fallback for redomiciliation cases like SHOP). Canadian filers use 6-K MIC for beneficial ownership when DEF 14A is unavailable.
**See**: `ADR-025-ifrs-fpi-universe-support.md`.

---

## DEC-33 — Damodaran intrinsic-value module + young-company target-margin DCF + universal sibling outputs

**Date**: 2026-05-15
**Decision**: Intrinsic value computed via Damodaran's three-tier classifier:
- **Tier A — mature**: clean GAAP-based DCF for profitable, predictable filers (LULU $210.47 IV, 42.4% MoS — example)
- **Tier B — pt_rescued**: loss-maker on GAAP but profitable on Peters-Taylor; uses adjusted basis
- **Tier C — insufficient**: loss-maker even after R&D rescue; system returns None rather than forward-EPS-substituted target (BFLY case)

Three universal sibling outputs computed alongside Damodaran: **EPV** (Earnings Power Value, Greenwald), **Reverse DCF** (back out implied growth from current price), **Narrative Premium %** (gap between intrinsic + reverse DCF).
**See**: `ADR-027-damodaran-intrinsic-value-skill.md`, `ADR-028-young-company-target-margin-dcf.md`, `ADR-029-sibling-outputs-epv-reverse-dcf.md`.

---

## DEC-34 — Maturity classifier + young-tier routing

**Date**: 2026-05-15
**Decision**: Three-stage maturity classification (pre_profitability / mid_cap / established) drives composite weight selection + framework-applicability gates. Young / pre-profitability companies route through young-tier-specific DCF and weight matrices.
**See**: `ADR-030-maturity-classifier-and-young-tier-routing.md`.

---

## DEC-35 — Data Gap Register + LLM-supplementary extraction channel

**Date**: 2026-05-15
**Decision**: Five-category data-gap taxonomy: **A** issuer non-disclosure / **B** source-policy exclusion / **C** parser miss / **D** FPI structural / **E** insufficient history. `external_signals` table (NRR / GRR / ARR / GMV / take-rate) + LLM-supplementary extraction channel for Category-A closure, **strictly isolated** from F1-F7 framework scoring. Token-budget ceiling $100/month.

CEO-equity priority chain established: **SC 13D/A Item 5 Row 13 → DEF 14A beneficial_ownership → 6-K MIC (Canadian FPI) → yfinance fallback**. Form-4 issuer-filter applied (SHOP-as-KVYO-insider rows correctly dropped).
**See**: `ADR-031-data-gap-register-and-supplementary-data-sources.md`.

---

## DEC-36 — Project-local skills runtime + two-permitted-call-sites rule

**Date**: 2026-05-15
**Decision**: Project-local skills live under `.claude/skills/*.md` with strict frontmatter contract (≥3 `do_not_invoke_when:` negative examples, postconditions, shadow_mode_until). Three production skills: `dive-complete`, `audit-completeness`, `external-signals`. Runtime in `cli/skills/runtime.py`; telemetry in `skill_invocations` table.

**Two-permitted-call-sites rule**: Anthropic SDK may be called ONLY from `deepdive/narrative.py` (narrative generation per D19) AND `deepdive/external_signals.py` (LLM-supplementary extraction per D25). Any new permitted site requires an ADR amendment.

Rule-of-three for new skills (3 invocations across sessions before authoring); rule-of-three inverse for retirement (no invocations in 4-6 weeks).
**Amends**: D19 (sole Anthropic call site → two call sites).
**See**: `ADR-032-project-local-skills-for-routine-task-workflows.md`.

---

## DEC-37 — SEC-first source hierarchy + compute-don't-pull

**Date**: 2026-05-15
**Decision**: Four-tier source hierarchy: **Tier 1A** SEC raw (companyfacts.json / submissions.json / companyconcept / frames endpoint / DEF 14A / SC 13D / Form 4 / 6-K MIC) → **Tier 1B** edgartools typed wrappers → **Tier 2** self-computed from SEC primitives → **Tier 3** API fallback (Polygon / yfinance / FMP). Each tier carries a trust weight (1.00 / 1.00 / 1.00 / 0.95-0.80) used by `compute_data_completeness`.

**Eight forbidden patterns** codified — most critical: no API pre-computed ratios (P/E, P/B, EV/EBITDA, beta), no forward-EPS substitution for negative TTM, no SBC add-backs, no yfinance industry/sector when SEC SIC is available.

**Concrete substitutions shipped**:
- Tier 1.1: industry/sector → SEC SIC primary (HIMS reclassification incident)
- Tier 1.2: P/E + P/B + EV/EBITDA → self-computed from SEC XBRL primitives (`valuation/sec_derived_ratios.py`)
- Tier 1.3: FPI detection → `Company.is_foreign` primary
- Tier 2.1-2.5: SEC frames endpoint + SIC-filtered peer comparison in F1/F3 + self-computed beta from PriceHistory vs SPY
- Phase 1 (2026-05-16): 20 per-field `_source` provenance columns + `tier_weight()` resolver + `compute_data_completeness` formula rewrite Σ(w·p)/N
- Phase 2.1 (2026-05-16): `exchange` → `Company.get_exchanges()` (Tier 1B)
- Phase 2.2 (2026-05-16): `ceo_total_pay` → DEF 14A SCT `proxy.peo_total_comp` (Tier 1A)
**See**: `ADR-033-sec-first-source-hierarchy-and-compute-dont-pull.md`, `API_FIELD_AUDIT.md`, `SEC_ENDPOINTS_INVENTORY.md`.

---

## DEC-38 — Skill versioning + lineage protocol

**Date**: 2026-05-16
**Decision**: Every skill carries explicit, machine-verifiable version lineage via semver + dated `changelog:` array. Cross-skill chronological index auto-generated at `.claude/skills/_lineage.md`. CI validator enforces three invariants: frontmatter version matches changelog head (§3.1), no duplicate versions (§3.2), date-monotonic entries (§3.3). CLI: `invest skill lineage [name] [--rebuild|--validate]`. Caught two real bugs at shipping (duplicate v1.0.1 in audit-completeness; missing changelog on external-signals).
**See**: `ADR-034-skill-versioning-and-lineage-protocol.md`.

---

## DEC-39 — Skill evaluation protocol (Anthropic four-dimension framing)

**Date**: 2026-05-16
**Decision**: Every skill is evaluated across four dimensions: **frontmatter_structure** (mandatory) / **script_execution** (mandatory) / **output_quality** (permissive — output_schema optional today) / **triggering_accuracy** (deferred — LLM-eval, corpus format in §3 reserved). Fifth dimension `composability_consistency` added by D30 (ADR-036). CI gate enforces mandatory dimensions. CLI: `invest skill eval [name] [--validate]`.
**See**: `ADR-035-skill-evaluation-protocol.md`.

---

## DEC-40 — Skill composability protocol + DAG validation

**Date**: 2026-05-16
**Decision**: Skills declare optional `composes:` block listing dependencies on (other skills + MCPs + Python libraries). Three relations between skills: **uses** (workflow invocation, hard dep) / **suggests** (recommended next step, soft dep) / **extends** (specialisation). Validation enforces refs resolve (§3.1), no self-loops (§3.2), no cycles (§3.3). PEP-440 constraint format check. Backfilled on all 3 skills: `dive-complete uses audit-completeness`; both `suggest external-signals`; all depend on `edgartools≥2.0`. CLI: `invest skill compose [name] [--validate]`. Closes Anthropic three-pillar (Versioning + Evaluation + Composability).
**See**: `ADR-036-skill-composability-protocol.md`.

---

## DEC-41 — PSA verdict-aware archetype gating + lattice budget bump

**Date**: 2026-05-17
**Decision**: `_select_archetype` (narrative.py) tags `post_spinoff` ONLY when PSA verdict is in the positive allowlist (`strong_psa_candidate / moderate_psa_candidate / weak_psa_candidate`). `not_a_spinoff_candidate` (PSA-3 self-disqualifies for mature issuers like LULU 158-month-old listing) and `data_gaps_block_verdict` (ambiguous) both fall through. Mental-model composer default `token_budget` raised 6000 → 8000 to unblock budget-starved conditional fires (Thorndike at 380 tokens couldn't fit alongside Group 0 always_load consuming 5530t). `RiskFactor.factor` `max_length` raised 300 → 500 (D22 hold-philosophy framing produces legitimate multi-clause monitoring checkpoints).
**Amends**: D20 (composer default budget) + D19 (RiskFactor schema).
**See**: `narrative.py:_select_archetype`, `mental_model_composer.py:select_models_for_dive`, `narrative_output.py:RiskFactor`.

---

## DEC-42 — Narrative contract reconciled with what shipped

**Date**: 2026-10-21
**Decision**: ADR-023 is amended, not rewritten. The shipped `bull/bear/risks/data_caveats` shape stays, and gains required `verdict`, `owner_operator_answer`, `moat_direction` and `triggers[]` fields. The §1.5 banned-language lint is implemented. Failed narratives persist as `guard_failed` behind an explicit "show anyway". Provider, model, caching and thinking settings are chosen from eval results rather than fixed in the ADR.
**Amends**: DEC-30.
**See**: `ADR-023-A1-narrative-contract-reconciliation.md`.

---

## DEC-43 — One verdict vocabulary; `initiate` retired

**Date**: 2026-10-21
**Decision**: Engine labels become `priority_watchlist` (≥ 7.0), `watchlist` (≥ 5.0), `monitor` (≥ 3.0), `exclude`, and `research_only` (coverage below floor). The first three map to the narrative verdict WATCHLIST WITH TRIGGERS, `exclude` to EXCLUDE WITH REASON, `research_only` to RESEARCH-ONLY. Thresholds are unchanged. Stored rows are mapped at read time and never rewritten.
**See**: `ADR-054-one-verdict-vocabulary.md`.

---

## DEC-44 — RAG and related LLM techniques rejected until a reopen condition is met

**Date**: 2026-10-21
**Decision**: RAG over filings or the lattice, LightRAG/GraphRAG, a vector database, LLM extraction into the data path, fine-tuning, and trading agents are not adopted. Each has a stated reopen condition backed by a measurement.
**See**: `ADR-055-rejected-llm-techniques.md`.

---

## DEC-45 — External signals verified in code before they are stored

**Date**: 2026-10-24
**Decision**: A deterministic verifier checks every `/external-signals` quote and value before persistence and sets a confidence ceiling that only lowers the model's band. Unverified signals cannot be persisted; source URLs and filing dates are checked before the paid call; the DEF 14A `0.5` placeholder is removed. ADR-057 is first in the AI-quality order, followed by ADR-048, ADR-044, the ADR-047 baseline and ADR-045+046.
**See**: `ADR-057-external-signals-verification.md`, `AI_QUALITY_PROPOSALS.md` §4.

---

## DEC-46 — Deep dives record their inputs; dives on superseded data are flagged, not deleted

**Date**: 2026-10-24
**Decision**: Each new deep dive records the parser version of the fundamentals it read, the 10-K accession it used, and the ScorecardView it scored (the JSON or its hash). A dive whose inputs have since been superseded, for example by a parser fix that re-read its filings, is flagged stale; it is never deleted. Narratives built on a flagged dive are excluded from use until re-run.
**Context**: The 52/53-week parser fix of 2026-10-24 (#24) re-read every dived ticker's filings and changed values and fiscal-year labels for some of them, and no stored dive recorded which data it was computed from: `SELECT COUNT(*) FROM deepdive_runs WHERE edgar_10k_accession IS NOT NULL` returned 0 of 217 on the author DB that day.
**See**: #25 (implementation); `PARSER_VERSION` in `data/edgar_companyfacts.py`; `DeepDiveRun` in `data/models/schema.py`.

---

## DEC-47 — A dive is stale when its inputs changed, not when the parser version did

**Date**: 2026-10-25
**Decision**: Each new deep dive records a SHA-256 digest of the fundamentals it read: the parser-written `Financial` values and the ratios derived from them (prices, FX, split and filing-date columns excluded; inputs outside `Financial`, such as insiders or analyst coverage, are not covered). Any write of fundamentals flags the ticker's dives whose digest no longer matches, whatever the cause: a parser or formula fix, a new filing (10-K or 10-Q) or a restatement. Same digest, same narrative. A dive with no recorded digest, which is every dive stored before this decision, counts as changed: its narrative and chat stay withheld until it is re-run. The same rule applies to chat as to narratives.
**Amends**: DEC-46 (which flagged on a parser re-read without comparing values).
**See**: `data/dive_staleness.py`; migration `0005_dive_inputs_digest`.

---

## DEC-48 — Orphaned and trailing-twelve-month annual rows deleted from the author DB

**Date**: 2026-10-26
**Decision**: The owner deleted 38 `financials` rows after a backup (`.backups/investment_intelligence-2026-10-26-pre-row-delete.db`, which still holds them). Two were orphans no current parser writes: ILMN "FY2026" (the year ending 2025-12-28, labelled a year late by the raw-month parser and now stored as FY2025) and MRVL FY2019 (an equity-only stub from parser v3). Thirty-six, in 31 undived companies, were annual rows ending off the company's year end with no revenue and no balance sheet: 10-Q trailing-twelve-month columns stored as fiscal years (e.g. AMZN 2025-04-01 to 2026-03-31), which #27 stops at the source. No dive's recorded inputs were affected: of the 33 companies (31 undived plus ILMN and MRVL), only ILMN and MRVL were ever dived (5 dives), and none of those dives has a recorded `inputs_sha256`, so all were already withheld under DEC-47.
**Context**: The 38 row ids and the SQL are in the PR (#31). The check, run with the backup attached as `old`: `SELECT COUNT(*) FROM deepdive_runs WHERE inputs_sha256 IS NOT NULL AND company_id IN (SELECT company_id FROM old.financials WHERE id IN (<the 38 ids>))` returned 0.
**See**: #24, #27, #31; `_derive_fiscal_period` in `data/edgar_companyfacts.py`.

---

## DEC-49 — Pre-IPO years stay data gaps; prospectuses are not read

**Date**: 2026-10-26
**Decision**: Years before a company's first 10-K (against Fiscal.ai across AAPL, NVDA, MSFT, UBER, LULU and HIMS: 6 field-gaps in 3 pre-IPO company-years, UBER FY2016-17 and HIMS FY2018) stay `data_gaps` entries. S-1/S-4 prospectus financials are not parsed: three company-years do not justify a new parser, and having a model read them would be LLM extraction into the data path, which DEC-44 rejects and coding rule 1 forbids (raw filing text in a prompt is SECURITY §3's concern too). "Recent IPO, insufficient history" is the correct output.
**See**: the Fiscal.ai comparison in #24's description; DEC-44, `ADR-055-rejected-llm-techniques.md`.

---

## DEC-50 — ADR-048 accepted: every LLM call is recorded, prices are copied with their source

**Date**: 2026-10-27
**Decision**: The owner accepted ADR-048. Every attempt at an allow-listed LLM call site writes one `llm_calls` row: tokens including cache tokens, latency, status and error class, guard status, cost and prompt version with a hash of the system prompt and schema; prompt text is never stored. Prices are rows copied from pydantic/genai-prices (MIT) at a named commit and date into `config/llm_prices.py`, not a dependency (SECURITY §5); a model with no row gets no cost rather than a guessed one, and the budgeted paths (chat, `/external-signals`) refuse it before the call. OpenTelemetry tracing libraries (OpenLLMetry, OpenInference) were considered and not adopted: they need a collector for three call sites; the table follows their GenAI field names instead.
**See**: `ADR-048-llm-observability-and-prompt-versioning.md`; the borrow-before-building comparison in the PR.

