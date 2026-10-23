---
name: intrinsic-value
description: |
  Full intrinsic-value workup for one ticker through BOTH deterministic
  frameworks: Damodaran forward FCFF DCF (ADR-027) and the Greenwald ladder —
  asset reproduction value → earnings power value → franchise test (ADR-042) —
  plus market-implied growth, applicability gates for young/inflecting/cyclical
  companies, and a cross-engine synthesis where the two disagree. Invoke when
  the user asks what a company is worth, for a DCF / intrinsic value / fair
  value / margin of safety / EPV / earnings power / franchise or moat-in-dollars
  question, whether a stock is cheap or expensive on fundamentals, or says
  "/intrinsic-value TICKER". Both core calculations are deterministic; the
  young/mature overlays are scenario-driven and require the user's stated story.
do_not_invoke_when:
  - The user wants the full framework dive (F1-F7 scores, overlays) — that is /dive-complete or `invest dive`.
  - The user wants qualitative narrative or a written thesis — that is `invest score-card TICKER --narrate`.
  - The user is asking about data coverage, gaps, or provenance — that is /audit-completeness.
  - The ticker has never been refreshed (no Company row) — run `invest data refresh TICKER` first; this skill does not fetch.
  - The user wants a price target or buy/sell call — the system does not produce those (ADR-023); say so instead.
arguments:
  - name: ticker
    type: ticker
    required: true
    description: Ticker as stored, e.g. NVDA, INTA, BONEX.ST.
  - name: scenario
    type: path
    required: false
    description: JSON file of ADR-028 ScenarioInputs. Required to VALUE a young-tier company.
  - name: years
    type: text
    required: false
    description: High-growth phase length in years (default 8).
preconditions:
  - A Company row exists for the ticker (else CompanyNotFoundError → tell the user to refresh).
  - At least one annual Financial row with revenue and total_equity is persisted.
  - The macro reference files under data/reference/damodaran/ are readable.
postconditions:
  - Both engines reported, or the reason each is unavailable given.
  - A reliability verdict of reliable | qualified | unreliable stated explicitly for the Damodaran headline.
  - The Greenwald applicability verdict (applicable | inflecting | not_applicable) stated explicitly.
  - The franchise verdict stated, or declared INDETERMINATE — never silently omitted.
  - Every data gap surfaced.
  - If tier ends in _young and no scenario was supplied, the forward IV is NOT quoted as a valuation.
side_effects:
  - Writes the Damodaran IV result to the warehouse and appends a JSONL run record (suppress with --no-persist).
  - Greenwald results are computed in-memory and not persisted.
  - Network - none. All inputs are already-persisted DB rows plus local reference JSON.
dangerous: false
token_budget_estimate:
  prompt: 2600
  completion: 1800
cost_estimate_usd: null
permitted_anthropic_calls:
  - none
related_adrs:
  - ADR-027
  - ADR-028
  - ADR-029
  - ADR-030
  - ADR-032
  - ADR-042
mental_models:
  - margin_of_safety
  - inversion
  - circle_of_competence
  - anchoring_bias
  - confidence_calibration
  - moat_direction
  - challenger_inversion_test
shadow_mode_until: 2026-08-30
version: 2.0.0
last_reviewed: 2026-08-16
changelog:
  - "1.0.0 (2026-08-16): initial. Wraps `invest iv` (new CLI surface). Authoring surfaced a live defect: the ADR-029 reverse-DCF gate still matched pre-ADR-030 tier labels ('A_gaap'/'B_pt_rescued'), so market-implied growth had been silently None for every classified ticker since 2026-05-14 — masked by a bare `except: pass`. Fixed in valuation/damodaran/intrinsic.py. Verified across NVDA, INTA, AAPL, BONEX.ST."
  - "2.0.0 (2026-08-16): MAJOR — adds the full Greenwald ladder (ADR-042, new valuation/greenwald/ package): asset reproduction value with goodwill excluded and R&D/SG&A capitalised, cycle-normalised earnings power with growth-capex added back, and the EPV-vs-AV franchise test. Adds the EPV applicability gate (the Greenwald analogue of ADR-030's maturity routing) plus a recent-regime EPV for inflecting filers. Adds cross-engine synthesis. Also fixed a second silent swallow: EPVResult.notes were computed then discarded. Breaking for consumers of the v1 single-engine output shape."
---

# /intrinsic-value TICKER

## What this does

Values one company through **two deterministic frameworks that answer different
questions**, then reads them against each other.

- **Damodaran (ADR-027)** — forward FCFF DCF. Projects growth, fades it, adds a
  terminal value. It *prices an explicit story*, and its growth input is an
  assumption, not a finding.
- **Greenwald (ADR-042)** — refuses to forecast. Computes what a competitor
  would spend to reproduce the assets (AV), what current earnings are worth at
  zero growth (EPV), and compares them. That comparison is **a moat test
  denominated in currency**.

Neither is "the" intrinsic value. Where they agree you have confirmation; where
they disagree, **the disagreement is the finding** — and the most common
disagreement is a healthy-looking DCF on a business with no franchise, where a
forward model prices growth that competitive economics will not permit.

Both core calculations are fully deterministic — no LLM, no network. The
young/inflecting overlays are scenario-driven and require the user's stated
story (§Young and inflecting companies).

## Workflow

1. **Run both engines.**
   ```
   invest iv TICKER [--years N] [--scenario FILE] [--no-greenwald] [--no-gaps]
   ```
2. **Read the Damodaran reliability banner first** — green `reliable`, yellow
   `qualified`, red `NOT USABLE AS A VALUATION`. Everything downstream is
   conditioned on it.
3. **Report the Damodaran three lenses**: forward DCF, the anchor EPV sibling,
   and market-implied growth.
4. **Report the Greenwald ladder in order** — AV, then EPV, then price. The
   order is the discipline: each rung is more speculative than the last.
5. **State the Greenwald applicability verdict.** If `inflecting`, use the
   recent-regime EPV and say why the full-history number is misleading.
6. **State the franchise verdict** and what it implies for growth:
   - `franchise` → growth is worth paying for; now invert and name the barrier.
   - `no_franchise` → **growth is worth approximately zero**; distrust a high DCF.
   - `value_destruction` → retained earnings destroy value.
   - `indeterminate` → say UNEVAL. Never report missing data as "no moat".
7. **Give the cross-engine synthesis** — the four configurations in §Reading
   the two engines together.
8. **Surface every data gap**, especially macro staleness and the PP&E
   approximation.
9. **Close with the inversion questions.** They are part of the deliverable.

## Pre-flight checks

```
invest iv TICKER --no-persist       # CompanyNotFoundError → refresh first
```
This skill never fetches. If the ticker is absent, run `invest data refresh
TICKER` and retry — that keeps it lazy-load compliant.

## Reading the Damodaran tier

| Tier | Meaning | Headline IV usable? |
|---|---|---|
| `A_mature` | GAAP EBIT positive, ROIC mature + stable | Yes, subject to the growth-cap check |
| `B_mature` | Rescued by capitalising R&D (Peters-Taylor), otherwise mature | Yes, same caveat |
| `A_young` / `B_young` | ROIC below mature-peer level or unstable | **No** — needs an ADR-028 scenario |
| `A_cyclical` / `B_cyclical` | Cyclical; normalised margins applied | Yes, with the cycle caveat |
| `C_yc_resolved` | Tier C rescued by a supplied scenario | Yes — it is the scenario's number |
| `C_insufficient` | Negative EBIT even after R&D add-back | Engine emits nothing |
| `C_growth_invalid` | Reinvestment ≤ 0 → no growth lever | Engine emits nothing — **correct** |

`C_growth_invalid` is not a bug. AAPL lands there because multi-year
reinvestment is negative, so `g = ROIC × RR` has no meaning. **Greenwald still
works on those names** — which is precisely why both engines run.

## Reading the Greenwald applicability gate

| Verdict | Meaning | What to do |
|---|---|---|
| `applicable` | Margin history is regime-stable | Use the full-history EPV |
| `inflecting` | Crossed loss→profit, or latest margin > 2× median | Use the **recent-regime EPV**; full-history EPV capitalises a regime that no longer exists |
| `not_applicable` | < 3 years of margin history | No EPV. Say so |

The inflecting case is the Greenwald analogue of ADR-030. BONESUPPORT's margins
`[-54%, -38%, -20%, +2%, +19%, +24%]` have a **median of −9%**, so a naive EPV
returns "value destruction" for a company whose last three years were
profitable. Full-history EPV −$7.95/sh; recent-regime EPV **+$34.49/sh**; the
franchise verdict flips from `value_destruction` to `franchise` at 1.30×. The
arithmetic was never wrong — the tool was misapplied.

## Reading the two engines together

| Damodaran | Franchise | What it means |
|---|---|---|
| usable | `franchise` | The only configuration where a DCF growth assumption is independently supported. Strongest case. |
| not usable | `franchise` | Greenwald ladder is the defensible anchor. Growth has value; this model cannot size it. |
| usable | `no_franchise` | **The dangerous one.** The DCF prices growth that competitive economics says is worth ~zero. Weight the EPV floor, not the DCF. |
| any | `indeterminate` | The DCF is unanchored — nothing independent confirms its growth. |

## Young and inflecting companies (ADR-028 story discipline)

The young path is **deliberately manual**. `ScenarioInputs` requires a
`scenario_name` and raises on anonymous defaults, because a young-company
valuation *is* a stated business hypothesis. Auto-generating one would
manufacture a story and launder it as arithmetic.

```json
{
  "scenario_name": "inta-saas-scale-base",
  "revenue_year_N": 900000000,
  "high_growth_years": 8,
  "target_op_margin": 0.22,
  "years_to_target_margin": 8,
  "sales_to_capital_ratio": 2.0,
  "notes": "Base case: holds share in permitting software; margin converges to mature vertical-SaaS peer."
}
```
```
invest iv INTA --scenario inta_base.json
```

**Ask the user for these inputs. Do not choose them yourself.**

## The lattice this runs on

| Model | How it binds here |
|---|---|
| `margin_of_safety` | Report the gap to the EPV floor, not just to the DCF. The floor is the number that survives the growth model being wrong. |
| `inversion` | Every run closes with what must be true for the valuation to be wrong. A `franchise` verdict obliges naming the barrier AND what removes it. |
| `circle_of_competence` | `indeterminate` and `UNEVAL` are valid answers. Missing data is never reported as a finding. |
| `anchoring_bias` | Never lead with a single number. A structurally-wrong IV anchors harder than no IV — this is why the reliability banner precedes every figure. |
| `confidence_calibration` | Three verdicts, not a binary. "Qualified" exists because most real cases are neither clean nor useless. |
| `moat_direction` | The franchise ratio is a moat measured in currency; direction over time matters more than the level. |
| `challenger_inversion_test` | The franchise test IS this model formalised: could a challenger spending AV earn EPV? If yes, there is no moat. |

## Failure modes

| # | Symptom | Detection | What to surface |
|---|---|---|---|
| 1 | Model invents scenario inputs to "get a number" | Any `target_op_margin` / `revenue_year_N` not supplied by the user | **Never do this.** State that the valuation needs the user's story; list the required fields. |
| 2 | Headline IV quoted despite `unreliable` verdict | Red banner but the IV appears as a valuation in your answer | Report EPV and the franchise verdict instead. |
| 3 | Full-history EPV quoted for an inflecting filer | Applicability says `inflecting` | Use the recent-regime EPV; explain that the median covers a dead regime. |
| 4 | `indeterminate` franchise reported as "no moat" | Franchise verdict is `indeterminate` | It means UNEVAL. Absence of data is not absence of moat. |
| 5 | Market-implied growth read as a point estimate | `feasibility: extreme` or the saturation warning | The solve hit the model's `WACC − 50bps` ceiling. It means "more growth than this model can express". |
| 6 | Asset value treated as precise | Always | PP&E is a net-book residual, so AV is a **floor** and the franchise ratio is biased toward `franchise`. Say so. |
| 7 | Stale macro silently accepted | Gaps mention `risk_free_rate.json` / `implied_erp.json` | Say how stale. Both engines share that WACC. |
| 8 | Non-US ticker valued without noting fidelity | `fundamentals source` is `esef` or `yfinance_only` | Name the source tier (ADR-041). ESEF annuals are filing-grade; yfinance rows are not. |

## Shadow-mode verification (until 2026-08-30)

Record per invocation in `skill_invocations`: ticker, Damodaran tier, reliability
verdict, Greenwald applicability, franchise verdict, whether a scenario was
supplied, and whether the answer respected both gates. Graduation requires ≥3
invocations with **zero** instances of failure modes 1–4.

## Audit trail

- Warehouse: the Damodaran IV row (unless `--no-persist`).
- JSONL: `log_iv_run` records tier, scenario name, young-company fields
  (`valuation/damodaran/instrumentation.py`). Read with `read_iv_runs(ticker)`.
- Greenwald results are **not** persisted — recompute via `invest iv TICKER`.

## Examples

**Franchise + capped DCF — NVDA**
```
/intrinsic-value NVDA
→ Damodaran: QUALIFIED · A_mature · IV 59.66 vs price 225 (g capped to WACC−50bps)
→ Greenwald: AV 8.27 · EPV 29.19 · FRANCHISE 4.11x
→ Both engines say the DCF understates. The franchise is real and large; the
  forward model cannot size growth this far above WACC. Do not quote $59.66.
```

**Damodaran refuses, Greenwald works — AAPL**
```
/intrinsic-value AAPL
→ Damodaran: C_growth_invalid · no IV (negative multi-year reinvestment)
→ Greenwald: AV 18.23 · EPV 73.85 · FRANCHISE 3.49x
→ The forward model does not apply; the franchise test still does.
```

**Inflecting — BONEX.ST (ESEF fundamentals)**
```
/intrinsic-value BONEX.ST
→ Damodaran: NOT USABLE · A_young (needs a scenario)
→ Greenwald: applicability INFLECTING
   full-history EPV −7.95  ·  recent-regime EPV +34.49  ·  FRANCHISE 1.30x
→ +85% of price sits above earnings power — that is what is being paid for
  growth and franchise durability.
```
