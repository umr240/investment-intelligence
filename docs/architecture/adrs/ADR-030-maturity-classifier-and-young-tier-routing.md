# ADR-030 — Maturity classifier and young-tier routing

**Status**: Accepted
**Date**: 2026-05-14
**Phase**: 5V
**Related**: ADR-027 (forward DCF), ADR-028 (young-company DCF), ADR-029 (universal sibling outputs)
**Resolves**: INTA-class misclassification surfaced by ADR-029 dashboard

## Context

The ADR-029 cross-ticker dashboard exposed a routing failure that was previously invisible:

```
INTA  | $24 price | EPV $5.54 | FwdIV $5.31 | Tier B_pt_rescued
```

Forward DCF and EPV agree at ~$5 for INTA. Both numbers are structurally wrong for INTA — bull case from the user's deep-dive is $45, base $30, bear $15. The math is correct given the inputs; the **inputs** are wrong, specifically the use of fundamental-DCF (`g = ROIC × reinvestment_rate`) for a still-scaling SaaS where current ROIC is structurally below what mature peers earn.

INTA passes ADR-027's Tier B check (EBIT + R&D > 0 → PT-rescue fires) but the resulting valuation is meaningless because:
- PT-adjusted ROIC ≈ 11% (modest, still-scaling)
- Reinvestment rate ≈ 70% (heavy growth investment)
- Fundamental g = 11% × 70% = 7.7% (sanity-capped)
- Result: $5 IV against $24 price

The same pattern fires on HIMS (just-turned-GAAP-profitable, ROIC ~10%, heavy Eucalyptus reinvest → $2.56 IV vs $29 price) and probably affects every mid-cap candidate whose ROIC is currently below mature-peer levels but trajectory is improving.

**Diagnosis**: Tier A/B classification (via `ADR-027 nopat.py`) is a *current-state* check (is EBIT positive? does R&D rescue it?). It does NOT check whether the company is operationally mature enough for fundamental DCF to apply. A maturity check is needed BEFORE delegating to the fundamental engine.

## Decision

Insert a **maturity classifier** between the tier determination (A/B/C from `nopat.py`) and the DCF engine. The classifier examines ROIC level + ROIC stability over the last 3 years and produces a sub-tier:

| Sub-tier | Condition | Routing |
|---|---|---|
| `A_mature` | Tier A AND ROIC ≥ floor AND ROIC stable (CoV < 0.4) | ADR-027 fundamental DCF (unchanged) |
| `A_young` | Tier A AND (ROIC < floor OR ROIC erratic) | ADR-028 scenario path if provided, else fundamental + warning flag |
| `B_mature` | Tier B AND PT-ROIC ≥ floor AND PT-ROIC stable | ADR-027 fundamental DCF on PT-adjusted NOPAT (unchanged) |
| `B_young` | Tier B AND (PT-ROIC < floor OR PT-ROIC erratic) | ADR-028 scenario path if provided, else fundamental + warning flag |
| `C_yc_resolved` | Tier C with scenario | Unchanged (ADR-028) |
| `C_insufficient` | Tier C without scenario | Unchanged data-gap |

### ROIC floor — sector-relative

Flat 12% is wrong across sectors. Damodaran's *Investment Valuation* Ch.12 criterion: **ROIC > Cost of Capital × 1.3** (the 30% buffer above WACC distinguishes "creating value" from "barely covering cost of capital"). This floats with WACC by sector:

| Sector profile | WACC | Floor = WACC × 1.3 |
|---|---|---|
| Mature consumer staples (low beta) | ~7% | ~9.1% |
| Asset-light SaaS | ~9% | ~11.7% |
| Healthcare info tech | ~9-10% | ~11.7-13% |
| Semiconductors | ~10-11% | ~13-14% |
| Pre-revenue biotech (high beta) | ~12-14% | ~15.6-18.2% |

A minimum absolute floor of 10% protects against degenerate cases (WACC near zero). Final rule: **`floor = max(0.10, wacc × 1.3)`**.

### Stability — coefficient of variation

Each of the last 3 years' ROIC must (a) be above the floor and (b) have a coefficient of variation `CoV = stddev / |mean|` below 0.4.

- ROIC sequence [22%, 25%, 24%]: mean=23.7%, stddev=1.5%, CoV=0.06 → stable
- ROIC sequence [15%, 30%, 8%]: mean=17.7%, stddev=11.0%, CoV=0.62 → erratic
- ROIC sequence [10%, 11%, 9%]: mean=10%, stddev=1.0%, CoV=0.10 → stable but low (floor check fails)

Both gates must pass. Either failure → young classification.

When fewer than 3 years of ROIC history exist (recent IPO, recent profitability inflection like HIMS), default to `young` — there isn't enough data to certify stability.

### Per-sub-tier routing

**Mature (A_mature, B_mature)**: Forward DCF as today. The fundamental engine is appropriate.

**Young (A_young, B_young) with scenario**: Delegate to `compute_young_iv` (ADR-028) — same path Tier C uses. The scenario explicitly states the maturity trajectory (target margin, revenue endpoint) the fundamental engine couldn't infer.

**Young (A_young, B_young) without scenario**: Run fundamental DCF anyway BUT tag the result with `data_gaps` entry: *"Maturity classifier flagged this filer as YOUNG (ROIC < WACC×1.3 OR erratic). Forward DCF using fundamental growth (ROIC × reinvestment_rate) may structurally understate valuation. Consider providing a young-company scenario for a target-margin DCF (ADR-028)."*

The user gets a number but it's labeled as tentative. This preserves backward compatibility — Phase 1 callers that don't bind scenarios still get something — while making the misclassification visible.

## Architecture

```
valuation/damodaran/
├── maturity.py            (NEW — maturity classifier)
│     classify_maturity(roic_history, wacc) -> MaturityClassification
├── intrinsic.py           (modified — maturity gate before tier routing)
├── nopat.py               (unchanged — A/B/C still derived from EBIT + R&D)
└── ...
```

`IVResult.tier` field domain expands from `{A_gaap, B_pt_rescued, C_yc_resolved, C_insufficient}` to `{A_mature, A_young, B_mature, B_young, C_yc_resolved, C_insufficient}`. The classifier output is also exposed:

```python
class IVResult:
    ...
    maturity_classification: MaturityClassification | None = None
    # Includes: is_mature, roic_floor, roic_history, roic_mean, roic_stddev,
    # roic_cov, floor_pass, stability_pass, notes
```

### Tier label compatibility

The old tier values (`A_gaap`, `B_pt_rescued`) are still recognized by downstream consumers (warehouse columns, screener filters) but the new values are produced. A small mapping table in `data/models/` or a migration adds the new labels.

For the warehouse `Company.intrinsic_value_tier` column: no schema migration needed — it's already `Text`. Just new possible values.

## Constraints (per CLAUDE.md)

- **Deterministic** — classifier is pure math (no LLM, no network)
- **Lazy-load** — fires only as part of an IV computation, never standalone
- **`data_gaps[]` first-class** — young classification without scenario emits explicit gap
- **Inversion mandatory** — for young-classified tickers, an auto-generated inversion question is added: *"Is the maturity classifier right that this filer isn't mature? What evidence would you need to see — 3 years of ROIC stability above floor — and is that defensible from current trajectory?"*

## Alternatives considered

- **Reclassify INTA as Tier C directly** — rejected. INTA structurally IS Tier B by Damodaran's R&D-capitalization criterion (EBIT + R&D > 0). The issue isn't tier assignment; it's that Tier B's *valuation path* (fundamental DCF) doesn't apply. The fix is sub-tier routing, not reclassification.

- **Flat ROIC threshold (12% or 15%)** — rejected. Sector beta varies WACC by 200-500bps, and a flat threshold misclassifies asset-light SaaS (high WACC, but mature at 15-25% ROIC) vs heavy industrials (lower WACC, mature at 8-12%). Sector-relative threshold via WACC×1.3 is Damodaran's published approach.

- **Industry-median ROIC lookup** — considered. Cleaner economically but requires a vendored sector-median table that needs annual refresh. WACC×1.3 is approximate but adequate and self-updating per the WACC reference data we already maintain.

- **3-year CoV vs 5-year** — chose 3 because (a) it's the minimum where CoV is statistically meaningful, (b) it accommodates recent IPOs like INTA without forcing 5-year history requirements that would route everyone to young.

- **CoV threshold 0.3 vs 0.4 vs 0.5** — 0.4 lets [22%, 25%, 24%] pass cleanly (CoV=0.06), catches [15%, 30%, 8%] (CoV=0.62). 0.3 would be too aggressive (catches normal cyclicality); 0.5 too lax (lets erratic ROIC through).

## Consequences

**Code surface added**:
- `valuation/damodaran/maturity.py` (~120 LOC)
- ~30 LOC integration in `compute_intrinsic_value`
- 1 new field on `IVResult` (`maturity_classification: MaturityClassification | None`)

**Schema changes**: none. Warehouse `intrinsic_value_tier` already accepts new values.

**Behavioral changes**:
- INTA at $24: will route to `B_young`. If no scenario, fundamental DCF runs with warning flag. With scenario, ADR-028 path → meaningful IV.
- HIMS at $29: likely `A_young` (FY25 was first profitable year — no 3-yr ROIC history above floor). Same routing as INTA.
- LULU at $126: `A_mature` (mature retailer, stable ROIC). Unchanged.
- COST at $999: `A_mature`. Unchanged.
- NVDA at $211: probably `A_young` (ROIC has exploded recently — high mean, high CoV). Worth verifying empirically.

**Diagnostic value added**:
- The new sub-tier labels in the dashboard directly answer the previous Claude's audit question ("why is INTA on B_pt_rescued?")
- Tickers that are *young by classification but the user hasn't supplied a scenario* are now visible as a class — scenario-library prioritization can target these explicitly.

## Risks

| Risk | Mitigation |
|---|---|
| WACC × 1.3 floor is approximate; doesn't perfectly track sector reality | Document explicitly; allow ticker-specific override via future `roic_floor_override` parameter |
| 3-year history requirement excludes very recent IPOs from being classified mature | By design — recent IPOs SHOULD route to young until 3-year track record exists |
| CoV calculation can spike on a single bad year | The pre-test "each year above floor" gates this — if year 2 is below floor, classification fails regardless of CoV |
| Existing warehouse rows have old tier labels (`A_gaap`, `B_pt_rescued`) | Backward compat: old labels still parseable. Forward: bulk recompute writes new labels per the upcoming refresh cycle. |

## Validation plan

Re-run portfolio post-implementation. Expected reclassifications:

| Ticker | Before | After (predicted) | Reason |
|---|---|---|---|
| LULU | A_gaap | A_mature | stable ROIC >> floor |
| COST | A_gaap | A_mature | stable ROIC >> floor |
| NVDA | A_gaap | A_young (probable) | erratic ROIC (high CoV from recent ramp) |
| INTA | B_pt_rescued | **B_young** | PT-ROIC ~11% below floor 11.7% |
| HIMS | A_gaap | **A_young** | <3yr ROIC history above floor |
| TEM | C_insufficient → C_yc_resolved | unchanged | already on scenario path |
| FIG | C_insufficient | unchanged | no scenario |

If the predictions hold: the routing audit is data-driven not vibes-based.

## Out of scope

- Sector-median ROIC table for floor lookup (vs WACC×1.3 approximation) — future enhancement when accuracy on edge cases matters
- ROIC trend test (improving vs stable vs degrading) — separately useful but not in v1
- Multi-tier scenarios per ticker (bull/base/bear classified separately) — ADR-028 amendment work

## References

- Damodaran, A. *Investment Valuation*, 3rd ed., Ch. 12 ("Estimating Growth") — ROIC vs cost of capital as maturity criterion
- ADR-027 — fundamental DCF (Tier A/B)
- ADR-028 — young-company DCF (Tier C, now also `*_young`)
- ADR-029 — universal sibling outputs (the dashboard that surfaced this routing failure)
