# ADR-027 — Damodaran Intrinsic Value skill

**Status**: Accepted
**Date**: 2026-05-13
**Phase**: 5T
**Related**: ADR-021 (Peters-Taylor economic ROIC), ADR-023 (narrative personality), ADR-024 (mental-models library)
**Defers**: ADR-028 (Young-company target-margin DCF) — out of scope, see §Non-goals

## Context

Today the system answers three valuation-adjacent questions:

| Layer | Answers | How |
|---|---|---|
| Composite score (warehouse) | "Is the business high-quality?" | 4-ratio heuristic (ROIC + FCF margin + D/E + revenue growth) — see `screener/tasks/composite.py` |
| F7 Smart Beta | "Is the stock cheap vs its own history?" | EV/Revenue + P/B z-scores against the company's 7-yr history |
| ICA overlay (per-dive) | "Is GAAP ROIC understating economic ROIC?" | Peters-Taylor intangible capital adjustment |

What the system **does not** answer: **"What's it worth on a first-principles cash flow basis?"** — i.e., absolute intrinsic value derived from cash flows the business is expected to generate, discounted at the appropriate cost of capital, independent of where the market currently prices it.

This is the question the user asks most often when deciding sizing or timing. The composite score ranks; F7 detects relative-valuation extremes; neither produces a per-share intrinsic value or a margin-of-safety percentage.

### Why Damodaran specifically

Aswath Damodaran (NYU Stern) is the public canon for intrinsic-value methodology. His framework is preferred for this codebase because:

1. **Open methodology** — every input documented, every assumption stated. Morningstar / Yahoo "fair value" are closed black boxes.
2. **Free reference data** — he publishes industry betas, implied ERP, country risk premiums, sector tax rates quarterly at https://pages.stern.nyu.edu/~adamodar. We can vendor these as static snapshots.
3. **Discipline on inputs**:
   - Uses **implied ERP** (derived from current market dividend+buyback yield), not historical
   - Uses **fundamental growth** (`g = ROIC × reinvestment_rate`), not analyst forecasts
   - Uses **marginal tax rate** (statutory federal + state-weighted), not effective tax rate (which embeds one-time items)
   - Caps **terminal growth at the risk-free rate** (hard ceiling — no company can outgrow the economy forever)
4. **Story-to-numbers discipline** — every input has to be anchored to a stated narrative about the business. Aligns with ADR-023's narrative-personality spec.
5. **Rejects company-defined non-GAAP** — explicit teaching: "Stock-based compensation is not a non-cash expense." This aligns with ADR-021's Peters-Taylor-not-management-non-GAAP stance.

### Three categories of filers and how Damodaran handles each

The "GAAP-loss / non-GAAP-positive" problem (raised before ADR acceptance) split the universe into three tiers:

| Tier | Condition | Damodaran treatment |
|---|---|---|
| **A — GAAP-profitable** | EBIT > 0 historically | Standard DCF with GAAP NOPAT as starting point |
| **B — PT-rescued loss-maker** | GAAP EBIT < 0 BUT Peters-Taylor adjusted EBIT > 0 (R&D-heavy SaaS / biotech / semis) | DCF with **PT-adjusted NOPAT** (R&D capitalised, knowledge capital added to invested capital). Damodaran is explicit that R&D should be capitalised — Peters-Taylor is the same family of adjustment. |
| **C — True loss-maker** | Negative even after PT adjustment (pre-revenue, cyclical bottom, structural unprofitability) | Damodaran's young-company target-margin DCF: top-down revenue projection, target operating margin from mature peer, sales-to-capital reinvestment, survival probability multiplier. **Out of scope for ADR-027 — see ADR-028.** |

Portfolio coverage check (May 2026): 6 of 8 user-held tickers are Tier A or B (HIMS, NVDA, LULU, MRVL, INTA, PATH). 1 borderline (FIG — recent 2025 IPO). 1 likely Tier C (NBIS — Russian tech holding).

## Decision

Build a **deterministic Damodaran-style intrinsic value module** producing per-ticker intrinsic value, margin of safety, and a WACC × terminal-growth sensitivity matrix. The module is consumed by the dive layer (per-ticker output), the screener layer (warehouse column for filtering), and the narrative LLM (mental-model entry in the lattice). It is **lazy-load consistent** — no autorun beyond explicit user instruction (`invest dive`, `invest intrinsic`, or warehouse task on cron).

### Tiered handling (the question-before-ADR-acceptance)

1. **Tier A**: standard Damodaran DCF using GAAP NOPAT.
2. **Tier B**: same DCF, with PT-adjusted NOPAT as starting point. Output banner says: *"GAAP-loss filer rescued by Peters-Taylor R&D capitalisation. IV depends on R&D becoming productive — see inversion form."*
3. **Tier C**: **no IV computed.** Output is a structured `data_gap` entry: `"Damodaran IV requires positive economic NOPAT (GAAP or PT-adjusted); ${ticker} negative on both. Young-company target-margin DCF is out of scope for ADR-027 — see ADR-028 if shipped."`

Tier C tickers get a clean **"insufficient inputs"** signal, not a forced number. The fundamental Damodaran teaching applies: it is better to admit you cannot value something than to fabricate a value.

### Architecture (4 layers)

```
1. valuation/damodaran/                    ← Pure deterministic Python
   ├── __init__.py
   ├── cost_of_capital.py                  ← CAPM, WACC, country adjustments
   ├── growth.py                           ← fundamental growth = ROIC × reinvestment_rate
   ├── reinvestment.py                     ← (capex + ΔWC − D&A) / EBIT(1−t)
   ├── nopat.py                            ← Tier A (GAAP) vs Tier B (PT-adjusted) selection
   ├── fcff.py                             ← FCFF projection over high-growth period
   ├── terminal.py                         ← Gordon growth, capped at Rf
   ├── sensitivity.py                      ← WACC × g matrix (5×5 default)
   └── intrinsic.py                        ← Public API: intrinsic_value(ticker) -> IVResult

2. data/reference/damodaran/               ← Snapshot of his quarterly tables
   ├── implied_erp_<YYYYQN>.json           ← Updated monthly (his Jan/Apr/Jul/Oct major + monthly minor)
   ├── industry_betas_<YYYYQN>.json
   ├── country_erp_<YYYYQN>.json
   ├── tax_rates_<YYYYQN>.json
   ├── risk_free_rate.json                 ← Snapshot of 10yr Treasury yield (weekly refresh)
   └── INDEX.md                            ← Provenance log: which file, source URL, snapshot date

3. Warehouse integration                   ← Scale-friendly screener filter
   ├── Migration: 2 new Company columns
   │     intrinsic_value_per_share         (Float)
   │     margin_of_safety_pct              (Float — derived: (IV − price)/IV)
   ├── screener/tasks/intrinsic_value.py   ← New FilterTask, 30d refresh
   └── invest screen --min-margin-of-safety <pct> filter

4. Mental-model + narrative                ← LLM hook (per ADR-024)
   └── mental_models/valuation/damodaran_intrinsic_value.md
       ├── auto_load_when: scorecard contains non-null intrinsic_value_per_share
       ├── related_models: [moat/moat_direction, core/margin_of_safety, valuation/multiples]
       ├── inversion_form: mandatory body section
       └── code_consequences: links to valuation/damodaran/intrinsic.py
```

### IVResult dataclass (the contract)

```python
@dataclass(frozen=True)
class IVResult:
    ticker: str
    tier: Literal["A_gaap", "B_pt_rescued", "C_insufficient"]
    intrinsic_value_per_share: float | None        # None when tier == C_insufficient
    current_price: float
    margin_of_safety_pct: float | None             # None when tier == C
    # Inputs (provenance-tracked)
    nopat_source: Literal["gaap", "pt_adjusted"]   # which EBIT used
    risk_free_rate: float
    erp_implied: float
    industry: str
    industry_beta_unlevered: float
    beta_relevered: float
    wacc: float
    growth_rate_high: float                         # fundamental: ROIC × reinvestment
    growth_period_years: int                        # 5-10, story-anchored
    terminal_growth: float                          # ≤ risk_free_rate
    reinvestment_rate: float
    # Projections
    fcff_projections: list[float]                   # year 1 .. N
    terminal_value: float
    # Diagnostics
    terminal_value_pct_of_total: float              # how much of IV is in TV
    sensitivity_matrix: list[list[float]]           # 5×5 WACC × g grid of IV/share
    # Provenance
    reference_data_snapshot_date: date              # the Damodaran file date used
    reference_data_staleness_days: int              # auto-flagged if >100
    data_gaps: list[str]                            # any missing inputs
    inversion_questions: list[str]                  # populated by mental-model composer for narrative
```

### Trigger points

| Trigger | Mechanism | Cost |
|---|---|---|
| `invest dive TICKER` | Auto-computed as part of scorecard build; rendered as new "Intrinsic Value (Damodaran)" panel | ~50ms per ticker (deterministic math) |
| `invest intrinsic TICKER` | New standalone CLI for ad-hoc one-shot calc | Same |
| `invest screen --min-margin-of-safety 0.20` | Reads pre-computed `Company.margin_of_safety_pct` from warehouse | Sub-second SQL |
| Warehouse task `intrinsic_value` | 30-day refresh, runs on the policy-eligible $100M+ universe (~2K tickers); ~2 min total compute time | Bulk pre-compute |
| Narrative LLM (`deepdive/narrative.py`) | Lattice composer auto-loads the Damodaran mental model when `scorecard.intrinsic_value_per_share is not None`. Inversion question is mandatory. | No extra tokens — model body is already in lattice |

## Resolutions to open decisions raised in planning

1. **Reference data refresh**: vendor static JSON. Damodaran updates monthly (implied ERP) and quarterly (betas, ERPs, tax rates). We snapshot from his Stern page and store under `data/reference/damodaran/`. The `IVResult.reference_data_staleness_days` auto-flags files older than 100 days; in-flight uses the most-recent file with a warning in `data_gaps`. Rationale: deterministic per CLAUDE.md, no live-HTTP dependency for a calc that must be reproducible.

2. **Risk-free rate**: static weekly snapshot in `data/reference/damodaran/risk_free_rate.json` with `last_updated` field. Auto-flag if >7 days stale. No live FRED API. Rationale: same as #1; the marginal precision from intra-week 10yr-Treasury moves is not worth the live-HTTP dependency.

3. **Warehouse pre-compute scope**: policy-eligible $100M+ (~2K-2.2K tickers). Rationale: matches the user's effective screening universe today; smaller filers get on-demand dive-level calc; full-universe pre-compute is wasted bandwidth.

4. **Story-discipline UX**: the **deterministic calc emits IV without requiring user-stated story** — per CLAUDE.md the data path cannot block on user input. The **LLM narrative layer** is where story-to-numbers discipline applies (mental-model composer pulls the Damodaran model with mandatory inversion form into the prompt). The CLI `invest intrinsic --story "<text>"` flag is available for users who want to attach a stated assumption to the persisted record, but it is optional and does not gate the calc.

5. **Naming**: `valuation/damodaran/`. Rationale: most semantically clear; leaves room for `valuation/multiples/` (relative valuation), `valuation/asset/` (sum-of-the-parts), etc. as future siblings. **Not** `frameworks/F8_damodaran/` because Damodaran IV is a *tool used by* frameworks (F5 fair-value cross-check, F7 z-score sanity), not a peer framework. **Not** `intrinsic/` because that's too narrow — the same package will hold relative-valuation cross-checks later.

## Constraints (per CLAUDE.md)

- **Deterministic** — no LLM in the calc path; AI layer reads outputs only.
- **Lazy-load** — only runs on user instruction (`invest dive`, `invest intrinsic`, or the scheduled warehouse task).
- **`data_gaps[]` first-class** — every missing input (reinvestment rate unknown, industry beta absent, etc.) surfaces in the output; never hallucinated.
- **Inversion mandatory** — every IV ships with at least three inversion questions: "what assumption would have to be wrong for IV to be off by 30%?", "what destroys the moat that justifies this growth rate?", "what would a bad capital allocator do here?". Populated by the mental-model composer per ADR-024.
- **Methodology disclosure** — every IV output includes a provenance block: which Damodaran reference snapshot, which NOPAT source (Tier A/B), which growth-rate derivation. Per ADR-022.

## Alternatives considered

- **Morningstar / Yahoo fair value**: closed methodology, third-party black box. Rejected per first-principles requirement.
- **Simple multiples-based valuation (P/E, EV/EBITDA against peer median)**: already in F7 z-scores. Doesn't answer "what's it worth on first-principles cash flows."
- **Tier 2 ContrarianDCF from the parent project's `unified-backend/`**: exists for the React/EdTech frontend but uses analyst-consensus growth forecasts (not fundamental growth) and lives in a separate codebase outside `investment-intelligence`'s lazy-load architecture. Porting it would also import its analyst-forecast dependency. Rejected — building Damodaran-style fresh is cleaner and methodologically more rigorous.
- **Reverse-DCF (Mauboussin "what's priced in")**: complementary, not competing. Could be a future ADR-029. Solves the inverse problem: given the current price, what growth rate is implied? Useful but doesn't replace forward DCF.
- **Skip ADR-027, just expose Peters-Taylor ROIC as the "intrinsic" measure**: half-measure. ROIC is a *quality* signal, not a *value* signal. A 30% ROIC business can still be overvalued if the market is pricing 40%.

## Consequences

**Code surface added**:
- `valuation/damodaran/` package (~8 files, ~600-800 LOC including tests)
- `data/reference/damodaran/` (5-6 JSON snapshots, ~100KB total)
- `screener/tasks/intrinsic_value.py` (~150 LOC)
- New CLI command in `cli/main.py` (`invest intrinsic`)
- 1 new mental model file in `mental_models/valuation/`

**Schema changes**:
- Migration `u<id>_intrinsic_value_columns.py`: 2 new `Company` columns (`intrinsic_value_per_share`, `margin_of_safety_pct`)

**Behavioral changes**:
- Dive output gains an "Intrinsic Value (Damodaran)" panel
- Screener gains `--min-margin-of-safety <pct>` filter
- Narrative LLM auto-loads the Damodaran model when IV is non-null in scorecard
- Warehouse task list grows by one entry

**Maintenance discipline**:
- Quarterly Damodaran reference-data refresh becomes a checklist item (Jan/Apr/Jul/Oct first week)
- Weekly risk-free-rate refresh becomes a checklist item
- The auto-staleness flag in `IVResult.reference_data_staleness_days` triggers a warning at 100 days but does not block

**Cost impact**:
- Deterministic calc: ~50ms per ticker → ~2 min for the $100M+ bulk pre-compute
- Zero LLM tokens for the calc itself
- Narrative LLM cost unchanged (mental model is pulled into existing prompt, not a separate call)

## Risks

| Risk | Mitigation |
|---|---|
| Reinvestment rate noisy on recent IPOs (FIG-class) and M&A-heavy filers | Surface as `data_gaps[]`, do not extrapolate. If reinvestment_rate uncomputable, IV is not produced for that ticker. |
| Terminal value typically 60-80% of total IV → highly sensitive to inputs | **Sensitivity matrix is mandatory output, not optional.** Every IV ships with the 5×5 WACC × terminal-g grid. The narrative must explicitly call out terminal-value share of total IV. |
| Damodaran reference snapshots drift between quarterly updates | `reference_data_staleness_days` auto-flag; weekly Rf refresh; the calc keeps working with stale data but the warning is loud. |
| "Story" component is qualitative — LLM consumes it but can't compute it; risk of becoming a narrative crutch where IV is rationalised after the fact | **Inversion form is mandatory** per ADR-024 §1.6 — the mental-model file includes three inversion questions, the narrative prompt forces the LLM to answer all three. |
| Tier B (PT-rescued) tickers produce IV that's heavily dependent on whether R&D is genuinely productive | Tier B output carries an explicit banner: "GAAP-loss filer rescued by Peters-Taylor R&D capitalisation. IV depends on R&D becoming productive — see inversion form." |
| Sensitivity matrix may suggest false precision (an IV range of $30-$80 is fundamentally different from a point estimate of $50) | The dive renderer presents IV as a **range with bands** (P5 / median / P95 of the sensitivity grid), not a single number. Margin of safety uses the lower P25 bound, not the median. |

## Non-goals (deferred)

- **Tier C — Young-company target-margin DCF**: Damodaran's approach for genuinely loss-making, pre-revenue, or distressed companies. Requires TAM × market-share projection, mature-peer mapping, sales-to-capital reinvestment, and survival probability. Significantly more complex; sees `ADR-028: Young-Company Target-Margin DCF` (to be written if and when a Tier-C ticker becomes a priority).
- **Reverse-DCF (Mauboussin)**: "what's priced in" given current price. Complementary to forward DCF; potential `ADR-029` future work.
- **Sum-of-the-parts valuation**: for conglomerates (BRK, GE-style); separate ADR if/when needed.
- **Real-options valuation**: for optionality-heavy businesses (early biotechs, miners pre-development); separate ADR.
- **Dividend Discount Model**: covered as a degenerate case of FCFE; not a separate path.

## Phased implementation (1-2 days work; each phase independently testable)

**Phase A — Reference data + cost of capital** (~3 hrs)
- Vendor Damodaran's current implied ERP, industry betas, country ERPs, tax rates as JSON in `data/reference/damodaran/`
- `valuation/damodaran/cost_of_capital.py`: CAPM cost of equity, after-tax cost of debt, WACC
- Tests: NVDA / COST / HIMS WACC against Damodaran's published company-level values (cross-check < 50bps deviation)

**Phase B — FCFF + terminal** (~4 hrs)
- `nopat.py`: Tier A vs Tier B selection (uses `Company.pt_adjusted_roic` to detect Tier B candidates)
- `reinvestment.py`: capex + ∆WC − D&A from existing Financial rows
- `growth.py`: fundamental growth = ROIC × reinvestment rate (with sanity caps: g ≤ 25% in high-growth phase)
- `fcff.py`: NOPAT − reinvestment, projected over high-growth period (5-10 yr; 8 default, story-adjustable)
- `terminal.py`: Gordon growth, hard ceiling at risk-free rate
- `intrinsic.py`: assemble everything, return `IVResult`

**Phase C — Sensitivity + tests** (~2 hrs)
- 5×5 grid: WACC ± 100bps × terminal_g ± 50bps
- IV is the median of the grid; MoS uses the P25 (conservative lower bound)
- Tests for known-cheap (COST, INTA after Peters-Taylor rescue), known-expensive (NVDA at current multiples), distressed (HIMS pre-GLP-1 if historical data permits), Tier C gating (verify a known unprofitable-even-after-PT filer triggers Tier C and emits the correct data_gap)

**Phase D — Warehouse + screener** (~3 hrs)
- Alembic migration: 2 new Company columns
- `screener/tasks/intrinsic_value.py`: FilterTask with 30d refresh, scoped to policy-eligible $100M+
- Screener flag `--min-margin-of-safety <pct>`
- Bulk run on the policy-eligible $100M+ universe (one-shot to seed the warehouse)

**Phase E — Dive + narrative lattice** (~3 hrs)
- `deepdive/scorecard_view.py` renders IV panel with range bands + sensitivity matrix
- `mental_models/valuation/damodaran_intrinsic_value.md` with mandatory inversion form, three baseline inversion questions
- Lattice composer auto-loads when `scorecard.intrinsic_value_per_share is not None`
- Narrative LLM grounding extends per ADR-023 §1.8 to validate IV claims against the structured result

**Phase F — CLI + docs** (~1 hr)
- `invest intrinsic TICKER [--story <text>] [--years <n>] [--terminal-g <rate>]` standalone command
- Update `CLAUDE.md` framework section (add `valuation/damodaran/` to the project structure tree)
- Update `mental_models/_index.md` and `_gaps.md`

Total: ~16 hours of implementation. Each phase is independently testable and shippable — recommend shipping A+B+C as one PR (the standalone calc), D as a second PR (warehouse), E+F as a third PR (dive + CLI).

## References

- Damodaran, A. *Investment Valuation: Tools and Techniques for Determining the Value of Any Asset*, 3rd ed. (2012)
- Damodaran, A. *Valuing Young, Start-Up and Growth Companies: Estimation Issues and Valuation Challenges*. SSRN (2009)
- Damodaran data site: https://pages.stern.nyu.edu/~adamodar
- Peters, R. & Taylor, L. "Intangible Capital and the Investment-Q Relation." *Journal of Financial Economics* (2017) — already referenced by ADR-021
- ADR-021 — Economic ROIC adjustment (Peters-Taylor not management non-GAAP)
- ADR-023 — Narrative personality spec (where story-to-numbers discipline lives)
- ADR-024 — Mental-models library and composition (where the Damodaran skill auto-loads from)
