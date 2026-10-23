# ADR-028 — Young-Company Target-Margin DCF

**Status**: Accepted
**Date**: 2026-05-13
**Phase**: 5U
**Related**: ADR-027 (Damodaran fundamental DCF — handles Tier A + B)
**Resolves**: Tier C gap in ADR-027 (loss-makers where R&D-capitalization rescue still fails)

## Context

ADR-027 ships a Damodaran-strict fundamental DCF that explicitly **refuses to value Tier C** tickers — companies whose economic EBIT remains negative even after R&D capitalization. The framework returns `IVResult.tier = 'C_insufficient'` with a data-gap note pointing to a future ADR-028.

That gap is now binding. Concrete cases from the May 2026 universe:

| Ticker | FY25 Rev | FY25 EBIT | EBIT + R&D | ADR-027 Tier |
|---|---|---|---|---|
| **TEM** | $1,272M (+83% YoY) | −$253M | −$80M | C_insufficient |
| FIG | TBD (2025 IPO) | negative | negative | C_insufficient |
| NBIS | complex | negative | negative | C_insufficient |
| Many pre-revenue biotechs | <$50M | deeply negative | deeply negative | C_insufficient |

For these, the user's actual question — *"what is this worth on first-principles cash flows it might generate"* — requires a different framework. Damodaran himself documents this in *Valuing Young, Start-Up and Growth Companies* (SSRN 2009) + *Investment Valuation* Ch.23.

**The user-facing impact**: TEM's full-dive surfaces:
- 7/4 frameworks fail (loss-makers structurally fail academic gates)
- BEW says "moderate winner candidate"
- F4 says "institutional accumulation while shorts elevated" (smart-money setup)
- Damodaran refuses to compute IV
- All 4 cross-source truthfulness checks pass — our data is correct

But the **valuation question is unanswered**. The market is paying $46.95/share (~$8.43B mkt cap). Is that priced for a $5B-revenue mature-margin business that hasn't arrived yet, or fantasy? Without a number for IV, the user has no anchor.

## Damodaran's young-company DCF framework

Substitute the four ADR-027 inputs that break for loss-makers:

| ADR-027 input | ADR-028 substitute |
|---|---|
| `g = ROIC × reinvestment_rate` (fundamental) | **Top-down revenue projection** (TAM × market share) |
| Reinvestment from `(capex + ΔWC − D&A) / NOPAT` | **Reinvestment from sales-to-capital ratio** — for each $1 of new revenue, X cents of capital |
| NOPAT = EBIT × (1 − t) | **Target operating margin** from a mature peer, interpolated from current to target over `years_to_target_margin` |
| (Cap value at face) | **Multiply by survival probability** — P(business reaches steady state) |

The mathematical structure becomes:

```
For each year t = 1..N:
  revenue_t = revenue_{t-1} × (1 + g_t)          # g decays from g_high to g_terminal
  op_margin_t = interpolate(current_margin → target_margin, t)
  EBIT_t = revenue_t × op_margin_t
  NOPAT_t = EBIT_t × (1 − marginal_tax_rate)     # tax kicks in only when EBIT > 0
  reinvestment_t = (revenue_t − revenue_{t-1}) / sales_to_capital_ratio
  FCFF_t = NOPAT_t − reinvestment_t

Terminal value = FCFF_{N+1} / (WACC − g_terminal)
DCF_total = Σ FCFF_t / (1+WACC)^t + TV / (1+WACC)^N

Expected_IV = P(survival) × DCF_total + (1 − P(survival)) × liquidation_value
Per_share_IV = (Expected_IV − net_debt) / shares_outstanding
```

The **discipline shift**: every input is now an **explicit assumption** rather than a derived ratio. This is the cost of valuing loss-makers — there's no "fundamental anchor" to derive from, only stated business hypotheses.

## Decision

Build a **scenario-driven Damodaran young-company DCF** as the Tier C resolution path.

### Architecture

```
valuation/damodaran/young_company.py
├── ScenarioInputs           dataclass — user-stated story assumptions
├── PeerBenchmark            dataclass — mature peer target metrics
├── YoungCompanyResult       dataclass — full output including survival-weighted IV
├── load_peer_benchmark()    by industry → expected target margin + sales-to-capital
├── derive_survival_prob()   from cash runway + burn rate trajectory
├── interpolate_margin()     current → target over N years (linear or S-curve)
└── compute_young_iv()       PUBLIC API — assembles everything

data/reference/damodaran/young_company_peers.json
   industry → {mature_peer_ticker, target_op_margin, sales_to_capital, notes}

valuation/damodaran/scenarios.py   (optional Phase 2)
   Predefined story archetypes: ai-platform-aggressive, biotech-platform,
   ev-disruptor, fintech-scale-up, etc.

scripts/young_company_dive.py     (demo + validation)
   Run on TEM, FIG, NBIS — output sensitivity table per scenario
```

### Scenario inputs (the "story")

A `ScenarioInputs` dataclass forces the user to state assumptions explicitly:

```python
@dataclass(frozen=True)
class ScenarioInputs:
    # Revenue trajectory (top-down)
    revenue_year_1: float                # current revenue (from Financial)
    revenue_year_N: float                # target revenue at end of horizon (TAM × share)
    high_growth_years: int               # typical 5-10
    growth_decay: Literal["linear", "scurve"]   # how growth slows

    # Margin trajectory (mature peer benchmark)
    current_op_margin: float             # may be negative
    target_op_margin: float              # from mature peer
    years_to_target_margin: int          # ≤ high_growth_years

    # Capital efficiency
    sales_to_capital_ratio: float        # from industry table; user override allowed

    # Survival probability
    survival_probability: float | None   # None → derived from cash runway + burn

    # Standard DCF
    high_growth_years: int               # default 8
    growth_rate_terminal: float | None   # None → use risk-free rate cap

    # Peer attribution
    peer_ticker: str                     # for narrative
    peer_op_margin: float                # the peer's actual margin
    notes: str                           # story justification
```

The intent: **the user MUST state the story**. The calc refuses to run on defaults — too easy to fabricate. The CLI surfaces a `--scenario <archetype>` flag that loads a pre-built scenario, but even then the archetype is named and version-tracked.

### Peer benchmark library

`data/reference/damodaran/young_company_peers.json`:

```json
{
  "Healthcare Information Tech": {
    "mature_peer_ticker": "VEEV",
    "mature_peer_name": "Veeva Systems",
    "target_op_margin": 0.25,
    "sales_to_capital_ratio": 2.5,
    "notes": "Veeva is the canonical mature health-IT cloud platform. 25% steady-state op margin reflects scale economics; sales-to-capital of 2.5 reflects capital-light SaaS."
  },
  "Software (Internet)": { "...": "..." }
}
```

Vendored, version-controlled, refreshed alongside the existing Damodaran reference data.

### Survival probability derivation

When `ScenarioInputs.survival_probability is None`, the calc derives:

```
runway_years = cash_position / abs(annual_op_cash_burn)
burn_trajectory = (current_burn / prior_burn) − 1   # negative = improving

if runway_years > 4 AND burn_trajectory < 0:
    P(survival) = 0.90    # well-funded with improving fundamentals
elif runway_years > 2:
    P(survival) = 0.75    # adequate runway
elif runway_years > 1:
    P(survival) = 0.60    # tight — dilution likely
else:
    P(survival) = 0.40    # high-risk, near-term financing needed
```

These are Damodaran's textbook ranges. The derived probability surfaces in `data_gaps[]` so the user can override per ticker if their narrative diverges.

### Output: YoungCompanyResult

```python
@dataclass(frozen=True)
class YoungCompanyResult:
    ticker: str
    tier: str                            # always "C_yc_resolved" when this runs

    # Scenario provenance
    scenario_name: str                   # e.g. "tem-ai-platform-aggressive"
    peer_ticker: str
    target_margin: float
    sales_to_capital_ratio: float

    # Survival
    survival_probability: float
    survival_probability_source: str     # "derived" | "user_override"
    cash_runway_years: float

    # DCF construction
    revenue_projections: list[float]     # year 1..N
    op_margin_projections: list[float]   # year 1..N (interpolated)
    nopat_projections: list[float]
    reinvestment_projections: list[float]
    fcff_projections: list[float]

    # Aggregate value
    enterprise_value_pre_survival: float
    enterprise_value_post_survival: float    # × P(survival)
    net_debt: float
    equity_value: float
    intrinsic_value_per_share: float
    current_price: float
    margin_of_safety_pct: float

    # Sensitivity (5×5 over target_margin × growth)
    sensitivity_matrix: list[list[float]]
    iv_per_share_p25: float              # P25 = conservative lower bound
    iv_per_share_median: float
    iv_per_share_p75: float

    # Reuse from Phase A
    wacc: float

    # Diagnostics
    data_gaps: list[str]
    inversion_questions: list[str]
```

### Inversion questions (mandatory per ADR-024)

For every young-company calc, three baseline questions are auto-populated:

1. "What revenue trajectory and target operating margin would have to be true for IV to be 30% below the base case?"
2. "What if the survival probability is 50% (worst-case dilution scenario) instead of the derived value?"
3. "Is the chosen mature peer (`<peer_ticker>`) actually a fair benchmark? What if the long-run margin is closer to the *median* health-IT peer rather than VEEV's top-decile?"

### Integration with ADR-027

When ADR-027 returns Tier C, the dive flow can optionally invoke ADR-028:

```python
# In compute_intrinsic_value:
if nopat_res.tier == Tier.C_INSUFFICIENT:
    if inputs.young_company_scenario is not None:
        return _delegate_to_young_company(inputs)
    else:
        return _tier_c_data_gap_result(inputs)        # unchanged from ADR-027
```

The `IntrinsicValueInputs` gains an optional `young_company_scenario: ScenarioInputs | None` field. When provided AND tier resolves to C, the young-company DCF runs instead of emitting a Tier-C data-gap.

## Constraints (per CLAUDE.md)

- **Deterministic** — the math is pure; the *scenario* is user-stated, never LLM-generated
- **Lazy-load** — only fires when user provides a scenario OR explicitly opts in via `--young-company` CLI flag
- **`data_gaps[]` first-class** — peer mapping fallback, survival probability override, every assumption surfaced
- **Inversion mandatory** — three baseline inversion questions on every output
- **Story-discipline** — the calc REFUSES to default. Either user provides full scenario or CLI loads a named archetype from a versioned library.

## Alternatives considered

- **Black-Scholes real options** for early-stage drug/tech — Damodaran teaches this for pre-revenue biotech. Out of scope; revisit if pre-revenue ticker becomes a priority.
- **Reverse-DCF (Mauboussin "what's priced in")** — what growth assumptions justify the current price? Complementary, not competing — could be ADR-029.
- **Multiples-based valuation** — peer P/E or EV/Revenue × forward estimates. Already in F7. Not first-principles.
- **Just leave Tier C as data_gap** — defensible but means ~10-20% of the screened universe gets no IV. Specifically excludes the highest-narrative-premium opportunities (TEM, FIG, NBIS).

## Consequences

**Code surface added**:
- `valuation/damodaran/young_company.py` (~400 LOC)
- `valuation/damodaran/scenarios.py` (predefined archetypes, ~150 LOC)
- `data/reference/damodaran/young_company_peers.json` (~10-15 industry mappings)
- `tests/test_valuation/test_young_company.py` (~250 LOC, ~15 tests)
- `scripts/young_company_dive.py` (demo runner)

**Schema changes**: none required initially. Existing `Company.intrinsic_value_per_share` + `Company.intrinsic_value_tier` columns hold the young-company result with `tier='C_yc_resolved'`. Optional future enhancement: add `Company.intrinsic_value_scenario` (Text) for scenario attribution.

**Behavioral changes**:
- `compute_intrinsic_value()` accepts optional `young_company_scenario` parameter
- New CLI: `invest intrinsic TICKER --scenario <name>` to invoke young-company path
- Tier C tickers get a real IV when a scenario is provided

**Maintenance discipline**:
- Peer benchmark JSON refresh — annually with Damodaran's industry data update
- Scenario library — track which archetypes are in use, retire stale ones

## Risks

| Risk | Mitigation |
|---|---|
| Scenario assumptions can be aggressive/optimistic — promotional valuation | **Inversion questions mandatory.** Sensitivity matrix forces a range, not a point. P25 is reported alongside median. |
| Survival probability is the most fragile input — small changes flip the verdict | Derivation is transparent (runway × burn trajectory). User override surfaces in `data_gaps[]`. |
| Mature peer mapping is judgment — wrong peer → wrong target margin | Peer attribution is explicit in output. Multiple-peer mode is a future enhancement. |
| Linear margin interpolation may overstate near-term profitability | S-curve interpolation is supported via `growth_decay='scurve'`. Both available; user picks. |
| Sales-to-capital ratio noisy across industries | Default per industry from Damodaran's published table; user override per scenario. |

## Phased implementation (the work to ship today)

**Phase A — Core calc** (~2 hrs)
- `valuation/damodaran/young_company.py`: `ScenarioInputs`, `YoungCompanyResult`, `compute_young_iv()`
- Revenue/margin trajectory interpolation
- Reuses Phase A WACC machinery
- Sensitivity grid over target_margin × growth

**Phase B — Reference data + survival** (~1 hr)
- `data/reference/damodaran/young_company_peers.json` (10+ industries)
- `derive_survival_prob()` function
- `load_peer_benchmark()` function

**Phase C — Tests + integration** (~1 hr)
- `tests/test_valuation/test_young_company.py`
- Wire into `compute_intrinsic_value()` so Tier C with scenario invokes this path
- Update `IntrinsicValueInputs` to include optional `young_company_scenario`

**Phase D — TEM demonstration** (~30 min)
- Build TEM scenario: ai-platform-aggressive
- Run end-to-end
- Sensitivity table output

**Out of scope** (defer to follow-up ADRs):
- Predefined scenario library beyond TEM
- CLI flag wiring (`invest intrinsic --scenario`)
- Dive integration (the LLM narrative grounding against young-company outputs)
- Reverse-DCF / Mauboussin "what's priced in" (potential ADR-029)
- Multi-peer benchmarking

## References

- Damodaran, A. *Valuing Young, Start-Up and Growth Companies: Estimation Issues and Valuation Challenges*. SSRN (2009)
- Damodaran, A. *Investment Valuation*, Ch.23 ("Valuing Young or Start-Up Firms")
- ADR-027 — Damodaran fundamental DCF (Tier A + B)
- ADR-023 — Narrative personality spec (story → numbers discipline at the LLM layer)
- ADR-024 — Mental-models library (inversion form mandatory)
