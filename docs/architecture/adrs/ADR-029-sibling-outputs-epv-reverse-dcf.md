# ADR-029 — Universal sibling outputs: EPV, Reverse DCF, Narrative Premium %

**Status**: Accepted
**Date**: 2026-05-14
**Phase**: 5V
**Related**: ADR-027 (forward DCF — Tier A/B), ADR-028 (young-company DCF — Tier C)
**Precedes**: ADR-030 (maturity classifier — depends on this for systematic audit)

## Context

The forward DCF (ADR-027) returns a single point estimate per ticker. Real-world critique surfaced three structural shortcomings:

1. **No floor anchor.** ADR-027 already includes growth (`g = ROIC × reinvestment_rate`). It is not "the floor" of valuation — it's the fundamental-growth case. The actual floor is **Earnings Power Value (Greenwald)** — current NOPAT capitalized as a perpetuity at WACC, with zero growth and zero reinvestment. Without an EPV anchor, we can't tell whether the market is paying *below the no-growth case* (LULU at $125 vs $160 EPV — strongest possible buy signal) or *above it* (HIMS at $29 vs $5 EPV — pure narrative trade).

2. **No market-implied case.** For stocks like NVDA where forward DCF gives $61 but the market pays $211, the forward number is sterile by itself. The more useful framing is "the market is implying X% revenue CAGR and Y% terminal margin — is that defensible?" — Mauboussin's reverse-DCF / *Expectations Investing* framework. Without reverse-DCF, every Tier A/B output is missing the diagnostic that explains the gap.

3. **No portable cross-ticker premium metric.** Raw margin-of-safety percentages don't normalize across price levels. **Narrative premium % = (price − forward_IV) / price** gives a 0-100% scale that's directly comparable across tickers. NVDA at 71% narrative, HIMS at 91% narrative, LULU at <0% narrative — that's a league table you can rank a portfolio by.

These three are not competing valuations. They are **sibling outputs** that ride alongside the primary IV regardless of which tier produced it. Per the user's framing: *forward DCF gives the fundamental floor; reverse DCF tells you what the market is paying for; the gap is the narrative premium*. All three must be visible, always.

## Decision

Build three additional outputs that fire on every IV computation, regardless of tier:

| Output | What it answers | Method |
|---|---|---|
| **EPV** (no-growth floor) | What is this worth if it never grows again? | Current NOPAT × (1/WACC) — Greenwald perpetuity |
| **Reverse DCF** | What growth assumption is the market pricing in? | Bisection over growth rate until DCF = market cap |
| **Narrative premium %** | What fraction of price is narrative vs fundamentals? | `(price − forward_IV) / price`, also against EPV |

All three are universal sibling outputs — not new tiers. They populate fields on the existing `IVResult` dataclass. The primary IV result remains the headline; the siblings are the diagnostic.

### EPV (Earnings Power Value)

Greenwald's framework. EPV = normalized NOPAT × (1/WACC) as a perpetuity. No growth, no reinvestment, no terminal-growth assumption. Math is equivalent to running ADR-027's engine with `growth_rate_high=0, reinvestment_rate=0, terminal_growth=0`. The DCF reduces to a Gordon perpetuity.

Per-tier handling:

| Tier | NOPAT source | Behavior |
|---|---|---|
| A_gaap | EBIT × (1 − tax) | Standard EPV |
| B_pt_rescued | PT-adjusted EBIT × (1 − tax) | EPV with R&D capitalization (consistent with Tier B claim) |
| C_yc_resolved | Current EBIT × (1 − tax), likely negative | EPV reported but flagged as "negative floor — narrative is the only anchor" |
| C_insufficient | Same as C_yc_resolved | Same handling |

When EPV is negative (current NOPAT < 0), the value is informative — it tells you the market is paying *only for the story*, with zero fundamental anchor. Surface this prominently in `data_gaps`.

### Reverse DCF

Given a current price and shares outstanding, solve for the growth rate that makes the forward DCF equal to market capitalization. Bisection over `growth_rate_high` in [-5%, +40%]. All other inputs held at their fundamental-DCF values (WACC, reinvestment rate, terminal growth, etc.).

Implementation:

```python
def reverse_solve_growth(target_equity_value: float, ...) -> float:
    """Bisection: find growth_rate_high such that forward DCF equals target."""
    lo, hi = -0.05, 0.40
    for _ in range(40):  # 40 iterations of bisection = sub-bp precision
        mid = (lo + hi) / 2
        iv = _quick_forward_iv(growth=mid, ...)
        if iv > target_equity_value:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2
```

Output: `reverse_implied_growth_rate` plus feasibility flag (`plausible` if 0-15%, `aggressive` if 15-25%, `extreme` if >25% — Damodaran's published caps).

For Tier C, the reverse-DCF question is "what revenue_year_N makes scenario IV = market cap?" — a different equation with different unknowns. Phase A ships reverse-DCF for Tier A/B only; Tier C reverse-DCF deferred to a follow-up.

### Narrative premium %

```
narrative_premium_pct = (price − forward_IV) / price
```

Range:
- `< 0`: market trading below fundamental IV (LULU-class — undervalued)
- `0-30%`: modest narrative premium (reasonable for growth-stage)
- `30-70%`: substantial narrative premium (NVDA-class)
- `> 70%`: pure narrative trade (HIMS-class at $29 vs $2.56 IV)

Also computed against EPV: `narrative_premium_vs_epv_pct = (price − EPV) / price`. The difference between the two narrative premiums tells you how much of the premium is "fundamental growth being priced in" vs "pure narrative beyond fundamentals."

## Architecture

```
valuation/damodaran/
├── intrinsic.py          (existing — modified to populate sibling fields)
├── cost_of_capital.py    (existing)
├── ...
├── epv.py                (NEW — Greenwald earnings power value)
├── reverse_dcf.py        (NEW — bisection solver for market-implied growth)
└── (existing modules)
```

`IVResult` gains five fields:
```python
# ADR-029 sibling outputs — universal across all tiers
epv_per_share: float | None                 # Greenwald no-growth floor
mos_vs_epv: float | None                    # (EPV − price) / price
reverse_implied_growth_rate: float | None   # market-implied g_high
reverse_implied_growth_feasibility: str | None  # 'plausible' | 'aggressive' | 'extreme'
narrative_premium_pct: float | None         # (price − forward_IV) / price
narrative_premium_vs_epv_pct: float | None  # (price − EPV) / price
```

All fields are `None` for unresolvable cases (e.g., negative NOPAT → EPV negative; no current_price → narrative premium uncomputable).

## Per-tier behavior summary

| Tier | EPV | Reverse DCF | Narrative Premium |
|---|---|---|---|
| A_gaap | ✓ (GAAP NOPAT / WACC) | ✓ (bisection over g) | ✓ (vs forward IV) + EPV variant |
| B_pt_rescued | ✓ (PT NOPAT / WACC) | ✓ (bisection over g) | ✓ + EPV variant |
| C_yc_resolved | ⚠ likely negative (current NOPAT < 0) | Deferred (different equation; Tier-C reverse-DCF is ADR-029 v2) | ✓ vs scenario IV |
| C_insufficient | ⚠ likely negative | N/A | N/A (no IV anchor) |

For Tier C tickers with positive scenario IV, narrative premium uses the scenario IV as the anchor — equivalent to "how much is the market paying above the user's story?"

## Constraints (per CLAUDE.md)

- **Deterministic** — both EPV and reverse-DCF are pure math, no LLM, no network
- **Lazy-load** — sibling outputs only compute when the primary IV path runs (no extra trigger)
- **`data_gaps[]` first-class** — negative EPV, infeasible reverse-DCF (no bracketing solution), missing price all surface as gaps
- **Inversion mandatory** — when narrative premium is high, an auto-generated inversion question is added: "what would have to be true about growth / margin / TAM for this premium to be defensible?"

## Alternatives considered

- **Skip EPV, keep ADR-027 as the floor anchor** — rejected. ADR-027 isn't the floor; it's already a growth case. Without true EPV, the cross-method dashboard is missing the most conservative anchor.
- **Reverse-DCF as a separate Tier D path** — rejected. Tiering implies mutual exclusivity; reverse-DCF is a sibling diagnostic that should fire on every Tier A/B run alongside forward IV. The user's "universal sibling outputs" framing is correct.
- **Solve for terminal margin in reverse-DCF instead of growth** — also valid, but growth is the more single-knob input. Multi-variate reverse-DCF (growth + margin + length) is mathematically correct but harder to interpret. Single-knob solving is the right v1.

## Consequences

**Code surface added**:
- `valuation/damodaran/epv.py` (~120 LOC)
- `valuation/damodaran/reverse_dcf.py` (~150 LOC)
- 6 new fields on `IVResult` (already optional, no schema migration)
- ~50 LOC in `compute_intrinsic_value` to populate the sibling fields
- ~10 lines per-tier in `IVResult` ↔ `compute_*` conversions

**Schema changes**: none. All new fields are optional on existing `IVResult` dataclass.

**Behavioral changes**:
- Every `IVResult` now carries 6 additional fields (EPV, MoS-vs-EPV, reverse-implied-growth, feasibility, narrative-premium, narrative-premium-vs-EPV)
- Existing callers see them as `None` if they don't consume them — backwards compatible
- New cross-ticker dashboard view becomes possible (see §Validation below)

**Diagnostic capability added**:
- "Paying below floor" signal (price < EPV) — strongest fundamental buy
- "Fundamental destroying value" signal (ADR-027 IV < EPV) — diagnostic that current reinvestment is sub-EPV (HIMS-like)
- "Market implies X% growth — is that plausible?" — every Tier A/B run

## Risks

| Risk | Mitigation |
|---|---|
| EPV is negative for Tier C tickers and confuses users | Surface explicitly: "EPV negative — narrative is the only anchor." UI shows as `n/a` with flag. |
| Reverse-DCF bisection fails to converge for extreme market premiums | Bracket clamps at [-5%, +40%]. If price implies >40% growth, return `extreme` flag, do NOT extrapolate beyond bracket. |
| Reverse-DCF solver runs on every call, adds latency | Bisection converges in ~40 iterations × ~1ms per iteration = ~40ms. Acceptable. |
| Narrative premium is misread as "the market is wrong" | Output description should frame as "narrative premium is X% — that's the gap between fundamental and price, not necessarily an error." |

## Validation plan

Cross-ticker dashboard on portfolio + extras, post-implementation. Expected pattern:

```
Ticker | Price | EPV   | Fwd IV | Reverse-g | Narr.% | EPV.Narr.%
LULU   | $125  | $160  | $210   | ~negative | -68%   | -28%       (rare: paying below EPV)
COST   | $999  | ?     | $346   | ~12%      | ~65%   | ?
NVDA   | $211  | ?     | $61    | ~35%      | 71%    | ?           (high narrative; market implies 35% CAGR)
HIMS   | $29   | $5    | $2.56  | ~50%      | 91%    | 83%
INTA   | $22   | $9    | $5     | ~28%      | 76%    | 59%
TEM    | $47   | <$0   | n/a    | n/a (C)   | ?      | n/a
```

If LULU shows market < EPV: high-confidence buy diagnostic confirmed.
If HIMS shows >85% narrative premium: confirms "narrative trade, not fundamental trade."
If NVDA reverse-implied growth is >30%: that's the conversation worth having.

## Out of scope (deferred)

- Reverse-DCF for Tier C tickers (different equation; needs scenario context)
- Multi-variate reverse-DCF (solve for `(growth, margin, length)` jointly)
- Reverse-DCF that solves for terminal margin instead of growth (single-knob is the v1)
- Probability-weighted narrative-premium across multiple scenarios (ADR-028 work)

## References

- Greenwald, B. *Value Investing: From Graham to Buffett and Beyond*. Wiley (2001) — EPV framework
- Mauboussin, M. & Rappaport, A. *Expectations Investing*. Harvard Business Review Press (2001/2021) — reverse-DCF
- Damodaran, A. *Investment Valuation*, Ch. 18 ("Earnings Multiples") — implicit-growth solving
- ADR-027 — forward DCF (Tier A/B fundamental)
- ADR-028 — young-company DCF (Tier C scenario)
