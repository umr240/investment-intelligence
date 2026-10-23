# ADR-037 — F3 R&D-effectiveness disaggregation

**Status**: Draft
**Date**: 2026-05-18
**Phase**: TBD
**Related**: ADR-023 (narrative personality / lattice composer), ADR-024 (mental-models lattice), ADR-030 (maturity classifier), ADR-031 (data-gap register), ADR-033 (SEC-first, compute-don't-pull)
**Resolves**: Currently nothing — this ADR exists because the previous attempt to ship this feature was made WITHOUT one, became outcome-bias engineering, and was reverted. The goal of this document is to define what evidence and design would be required to ship a future R&D-effectiveness enhancement WITHOUT repeating that mistake.

## Context

### What F3 currently captures

`frameworks/f3_innovation.py` grades innovation on four signals:

| Signal | Range | Source | What it measures |
|---|---|---|---|
| GM trajectory | 0-4 pts | Annual `gross_margin` YoY | Operating-leverage signature |
| R&D intensity (sweet-spot band) | 0-3 pts | Annual `rd_intensity` | Quantity of R&D spend |
| Earnings surprise streak | 0-3 pts | yfinance `eps_surprise_pct` | PEAD proxy (revenue-surprise unavailable) |
| Patent disclosure | 0-1 pt | 10-K text regex | Absolute portfolio size (coarse) |

Composite is the additive sum, capped 0-10.

### The audit finding the prior conversation surfaced

A $1 of R&D spent stopping a competitor from eating your lunch is mechanically identical on the income statement to a $1 spent inventing a new category. Their forward return profiles are different:

| R&D type | What it buys | Forward return |
|---|---|---|
| Maintenance | Bug fixes, table-stakes feature parity, cloud re-platforming | Cost of capital, maybe less |
| Defensive innovation | Matching competitor advances | Above CoC if executed; margin-defending |
| Offensive innovation | Net-new category creation, capabilities competitors can't replicate quickly | Multi-bagger returns — Hirshleifer-Hsu-Li (2013) EMI alpha lives here |

F3 v3.0 grades R&D 15-35% intensity as "sweet spot" regardless of type. Two companies with identical R&D intensity and identical GM expansion can have completely different forward return signatures depending on whether the R&D dollars are maintenance, defensive, or offensive.

This is the actual problem statement. **Note what it is not**: it is not "SNOW scored 9.0 and that feels too high." Naming a thesis-driven anchor here would be the first sign that we are designing toward an outcome.

### The Red Queen mental model

From `mental_models/biology/red_queen.md` (or to be authored if not present). Lewis Carroll's Red Queen tells Alice: "It takes all the running you can do, to keep in the same place." Applied to capital allocation: in some R&D environments, you have to run as fast as you can just to stay competitive. That's maintenance + defensive. Offensive innovation is the only category that moves the company forward in real terms.

This model is the academic anchor. Hirshleifer-Hsu-Li (2013) Innovative Efficiency (EMI) operationalises it through patent-weighted-by-citations / R&D dollar — companies whose R&D produces high-impact patents that other firms cite are offensive innovators; companies whose patent stock is large but uncited are running the Red Queen treadmill.

### Six observable proxies

Companies don't break out R&D by type in 10-Ks (internal classifications would shift quarter-to-quarter). Observable proxies, ranked by data availability for this project:

| # | Proxy | Available today? | Strength |
|---|---|---|---|
| 1 | GM trajectory while R&D rising | Yes — `Financial.gross_margin` + `rd_intensity` | Strong — already half-computed |
| 2 | R&D intensity vs peer SIC-2 median | Yes — `data/sec_frames.py:get_percentile_rank` | Medium — already exposed as supplementary signal |
| 3 | Absolute R&D dollar trajectory | Yes — `Financial.rd_expense` raw value, multi-year | Medium — easy to compute, complements (2) |
| 4 | New product/category cadence | **No** — needs press-release feed / curated timeline; not in data model | Strong if available, requires Phase-3-scope data fetch |
| 5 | 10-K MD&A language ratio ("enhance/maintain" vs "explore/new/expand") | **Partial** — `data/edgar_text_parser.py` has the 10-K path; sentence-level classification not implemented | Medium — regex too coarse; embedding classification adds dependency |
| 6 | Patent citation quality (Hirshleifer-Hsu-Li EMI) | **No** — USPTO API key blocked (ADR-022 §SHELVED 2026-05-10); Google Patents BigQuery / Lens.org are the alternatives | The strongest signal academically; not implementable from current data plane |

**Critical constraint**: only proxies (1), (2), (3) are computable from data this project already pulls. Anything else requires new data plumbing.

### What ADR-023 reserves for the composer

> The lattice composer (`deepdive/mental_model_composer.py`) reads `mental_models/` at runtime and injects relevant model summaries + inversion forms into the narrative LLM user prompt. Qualitative threats — competitive dynamics, regulatory risk, narrative framing — live here, not in the deterministic framework scores.

Examples of what this means in practice:
- "Databricks is taking share in lakehouse" → composer territory (10-K language, earnings-call sentiment, qualitative threat models)
- "R&D intensity is 27% and GM expanded 240bps" → F3 deterministic territory
- "R&D intensity is 27% AND the company is fighting a Goliath" → composer territory; F3 should report the 27% / 240bps cleanly without conflating it with the qualitative threat

This ADR explicitly accepts that boundary: **F3 will not encode qualitative competitive-pressure inferences**. The composer reads F3's numeric output + qualitative signals separately and produces the synthesis.

## Decision

This ADR does NOT decide on an implementation. It decides on **the gate that any future R&D-effectiveness enhancement to F3 must pass before it ships**.

### The gate

A future F3 enhancement that disaggregates R&D effectiveness must:

1. **Be anchored to a named academic signal** — Hirshleifer-Hsu-Li EMI, Eberhart-Maxwell-Siddique R&D-increase abnormal returns, Chan-Lakonishok-Sougiannis intangibles work, or similar with citation. Not "the user said SNOW felt high."

2. **Use only deterministic data sources already in the warehouse** — Annual `Financial.rd_expense`, `Financial.gross_margin`, peer SIC percentile via `data/sec_frames.py`. New data sources (USPTO citations, 10-K MD&A language, product launch feeds) require their own ADR before F3 can read them.

3. **Distinguish informational vs scoring signal** — Two release tiers:
   - **Phase 1 (Informational)**: Compute the new disaggregation; surface in `signals` dict; **no scoring impact**. Dive renderer and composer can read it. The numeric F3 score is unchanged.
   - **Phase 2 (Scoring)**: Apply scoring impact (multiplier OR new sub-score) ONLY after Phase 1 has run for at least 4 weeks of warehouse data AND backtest passes (see §Validation).

4. **Have a written backtest** — Run the proposed Phase-2 scoring logic against the full warehouse universe (currently 3,154+ framework-scored tickers, ≈3,500 by Q3 2026). Backtest must demonstrate:
   - The signal fires on ≤ 25% of tickers (not a universal label)
   - The signal does NOT change the verdict for tickers in a hand-picked positive-conviction set (define before running — not after)
   - The signal does NOT change the verdict for tickers in a hand-picked negative-conviction set
   - False-positive rate (signal fires on a name where the qualitative thesis is positive) ≤ 10%

5. **Inversion mandatory** — Per ADR-024 and CLAUDE.md "Inversion is mandatory and primary". Inversion question for the enhancement itself: *"If we removed this signal tomorrow, which true-positive cases would we miss? Are those cases the lattice composer can catch via narrative signals (per ADR-023), or are they unreachable without it?"* If the answer is "the composer can catch them", the signal does not belong in F3.

6. **Pass the outcome-bias check** — For every name the proposer cites as motivation, ask: *"Would I have built this signal if the name in question had been scored the opposite way?"* If no, the signal is outcome-biased.

7. **Pass the Goodhart test** — Once shipped, the signal becomes a target. Anyone optimizing toward F3 will optimize toward this signal. Is the signal robust to that pressure, or will companies start gaming it (e.g., releasing useless product SKUs to inflate "new category cadence")?

### What this ADR does NOT decide

This ADR is not approving:
- A specific multiplier matrix (e.g., the reverted v2.0 `RD_EFFECTIVENESS_MATRIX`)
- A specific sigmoid calibration for GM strength
- A specific absolute-R&D scale threshold
- A specific deceleration gate on the surprise streak

All of those would be Phase 2 decisions requiring their own narrower ADR-037a / 037b / 037c following the validation discipline above.

## Architecture (if/when Phase 2 ships)

```
frameworks/
├── f3_innovation.py
│     score_f3() unchanged                  ← Phase 1: signals added, scoring untouched
│     _compute_rd_effectiveness() NEW       ← Phase 1: emits informational signals only
│                                           ← Phase 2: returns multiplier applied to score
└── ...
```

Phase 1 signal surface (informational only):

```python
signals["rd_effectiveness"] = {
    "method": "rd_trajectory_x_gm_trajectory",   # version stamp
    "rd_absolute_latest_usd": <float>,           # raw $
    "rd_absolute_trend_3yr": <"rising"|"stable"|"falling">,
    "rd_intensity_trend_3yr": <"rising"|"stable"|"falling">,
    "gm_strength_continuous": <float 0..1>,      # sigmoid-blended (kills binary cliff)
    "posture_inferred": <one of N labels>,       # e.g. "offensive_innovation"
    "peer_percentile": <float 0..100>,           # already exists
    "scoring_impact": "informational_only",      # Phase 1 flag
}
```

Phase 2 adds:

```python
signals["rd_effectiveness"]["scoring_impact"] = "multiplier_applied"
signals["rd_effectiveness"]["multiplier"] = <float 0.50..1.25>
signals["rd_effectiveness"]["raw_f3_score_before_multiplier"] = <float>
```

The deterministic scoring contract is preserved: same inputs → same output, audit trail visible.

## Constraints (per CLAUDE.md + ADR-023)

- **Deterministic** — All signals computed from XBRL / `Financial` rows / SEC peer frames. No LLM, no network. ADR-031 §4.1 two-permitted-Anthropic-call-sites rule untouched.
- **Lazy-load** — Computed only when F3 runs. No background task.
- **`data_gaps[]` first-class** — When trend signals can't be computed (e.g., <3 years of rd_expense history), emit a data gap; do not silently default.
- **No qualitative inference in F3** — Per ADR-023, competitive-pressure narratives belong in the composer reading `narrative_dumps/`, not in F3 scoring.
- **Inversion form mandatory** — The signal definition file (when authored) must include an `inversion_form` section per ADR-024 §1.6 lattice schema.
- **No outcome-bias** — Hand-picked validation sets must be defined BEFORE running the backtest, not after.
- **No scope creep** — F3 stays at ≤ 5 signal sub-scores (current 4 + at most 1 sub-score from this enhancement). If a 6th signal becomes "necessary", that triggers a new framework (F8), not F3 bloat.

## Alternatives considered

### Alt 1 — Do nothing; let the composer handle R&D quality inference

**Pros**: Respects ADR-023 fully. F3 stays minimal. Composer has access to GM trajectory + R&D intensity + peer percentile + narrative signals; can synthesise effectiveness inferences case-by-case.

**Cons**: Composer is one-shot per dive (subject to token budget, LLM variability, ADR-031 cost ceiling). A deterministic disaggregation surfaced once and persisted to `framework_scores` is available to every downstream consumer (screen-winners, watchlist filters, future ML rankers) without LLM cost.

**Verdict**: This is the default if Phase 2 fails its validation gates. Phase 1 (informational signals, no scoring impact) is the bridge — adds the deterministic disaggregation to the data plane so the composer has it, without committing to scoring impact.

### Alt 2 — New framework F8 instead of F3 enhancement

**Pros**: Avoids F3 bloat. F8 explicitly anchors on Hirshleifer-Hsu-Li with its own data requirements (USPTO citations).

**Cons**: USPTO data isn't available (per ADR-022). Without citations data, F8 would have the same observable proxies F3 already uses — pure name change, no architectural win. **Defer until USPTO data path is unblocked** (an alternative API such as Google Patents BigQuery or Lens.org). At that point, F8 becomes the right home.

**Verdict**: Right answer eventually; not now.

### Alt 3 — Multiplier on F3 final score (the reverted v2.0 approach)

**Pros**: Single number movement, easy to audit.

**Cons**:
- Hides the disaggregation behind a single scalar
- Multiplier × sum is the multiplicative form of double-counting when sub-signals are correlated (GM trajectory is in BOTH the gm_pts term AND the rd_effectiveness multiplier — Goodhart explosion risk)
- The reverted implementation was outcome-bias engineering (see §Why this ADR exists)

**Verdict**: Rejected as Phase 2 mechanism. If scoring impact is needed, a separate **additive sub-score** (capped, weighted explicitly) is preferred over a multiplier on the existing sum.

### Alt 4 — Replace existing rd_intensity sub-score with disaggregation sub-score

**Pros**: No new sub-score added; signal count stays at 4; disaggregation replaces the cruder quantity-only measure.

**Cons**: Discards an empirically validated signal (Chan-Lakonishok-Sougiannis 2001) for one with weaker empirical backing (the disaggregation matrix is mostly heuristic — Hirshleifer-Hsu-Li uses citations, not GM × trajectory).

**Verdict**: Plausible Phase 2 architecture if backtest favours it. Don't pre-commit.

## Consequences

### If ADR-037 is accepted (Phase 1 only)

**Code surface added (Phase 1)**:
- `frameworks/f3_innovation.py`: ~50 LOC for the disaggregation function + signal dict population
- Zero scoring impact; F3 numeric output unchanged
- Dive renderer + composer can read `signals["rd_effectiveness"]` to surface the posture qualitatively

**Warehouse impact**: None. `framework_scored_at` invalidation not required.

**Auditability**: The disaggregation is visible in dive `signals_json` and the dive renderer (when extended) without changing existing scores.

### If Phase 2 ships (only after Phase 1 + backtest validation)

**Code surface added (Phase 2)**:
- Either a multiplier (existing reverted approach, fixed for double-counting) OR an additive sub-score (max +/- 1.5 pts on the 0-10 scale, capped)
- Backtest results documented in `tests/test_frameworks/test_f3_rd_effectiveness_backtest.py`

**Warehouse impact**: Universe rescore (≈ 80 seconds based on prior framework_score runs)

**Calibration discipline**: Every threshold (sigmoid steepness, $2B scale floor, peer percentile threshold) must have a written rationale tying back to the academic anchor — not "this number made INTA look right."

## Risks

| Risk | Mitigation |
|---|---|
| Phase 1 ships, Phase 2 never happens — disaggregation becomes orphan code | Acceptable. Composer reads the signal; even without scoring impact, the data plane is richer. |
| Phase 2 calibration drifts toward outcome bias over time | Outcome-bias check is a contract test in CI: snapshot of the universe rescore at Phase 2 ship time becomes a regression baseline. Any future calibration tweak that moves the snapshot by >X% requires a new ADR. |
| Disaggregation overfits to current ~3,500-ticker universe; doesn't generalize | Backtest must hold out 20% of universe as a true test set, not just summary stats on training set. |
| New posture labels become target words analysts/management game | Posture labels are internal to F3 signals dict — not surfaced in CLI verdicts or watchlist UI. Composer can mention them; warehouse tier label remains the existing framework verdict ladder. |
| Goodhart on R&D dollar trajectory (companies inflate R&D classification to hit "rising absolute") | Cross-check: absolute R&D vs operating cash flow ratio. If R&D rises while OCF doesn't, capitalization games likely. Surface as data gap rather than scoring credit. |

## Validation plan

### Phase 1 acceptance

Phase 1 is informational. Validation = does the signal compute without errors on the universe AND does the signal correlate with prior intuitions on a small hand-picked validation set?

Hand-picked validation set (define BEFORE running):

| Ticker | Expected posture | Source of expectation |
|---|---|---|
| (TBD) | (TBD) | (TBD) |

The proposer of any future Phase 2 work must fill in this table BEFORE running any code. Tickers selected after seeing results are invalid.

### Phase 2 acceptance

Required before any scoring impact ships:

1. **Universe backtest report** in `narrative_dumps/f3_rd_effectiveness_backtest_<date>.md` containing:
   - Posture distribution across the full universe (e.g., "12% offensive_innovation, 47% maintenance, ...")
   - Verdict-shift distribution (how many tickers change verdict; by how much)
   - Top 20 verdict gainers + losers with their numeric breakdowns

2. **Hand-picked positive-conviction set**: at least 10 tickers the proposer holds (or would hold) on conviction independent of F3. The signal must NOT downgrade any of these. (If it does, the proposer either updates the conviction list with rationale or accepts the signal is miscalibrated.)

3. **Hand-picked negative-conviction set**: at least 10 tickers the proposer would avoid on conviction. The signal must NOT upgrade any of these.

4. **Outcome-bias check passed**: written answer to *"What would have to be true for SNOW to score higher under this signal, and would that be defensible from the data?"* (or whichever specific ticker motivates the change)

5. **Inversion answered**: written response to *"If this signal didn't exist, which true-positive cases would the system miss?"*

Only after all five pass does Phase 2 ship.

## Out of scope

- USPTO patent citation integration (Hirshleifer-Hsu-Li EMI signal at full strength) — separate ADR when USPTO data path unblocks
- 10-K MD&A language classification (sentence-level "enhance vs explore" ratio) — needs embedding-based classifier, separate ADR
- Hiring composition signals (research scientists vs application engineers via LinkedIn scraping) — out of project scope; introduces a third-party dependency
- New product/category cadence — requires curated press-release feed; out of scope until that data plane exists
- Changing the F3 weights / composite formula — F3 v3.0's gm_pts + rd_pts + streak_pts + patent_pts assembly is preserved
- R&D capitalisation-rate signal (IFRS filers disclose, US GAAP filers usually don't) — needs separate cross-jurisdiction handling, defer to ADR-025 IFRS work

## Why this ADR exists

On 2026-05-18, the assistant shipped F3 v2.0 (multiplier matrix), F3 v2.1 (sigmoid + absolute-trajectory disambiguator + scale override + label rename), and a surprise-streak revenue-deceleration gate **without** writing an ADR first. The work was outcome-bias engineering driven by case studies of INTA / SNOW / NVDA / KLIC. The owner identified the pattern and demanded a revert.

This ADR exists to make repeating that mistake difficult. Any future F3 enhancement must reference this document and pass its gates.

The reverted code lives in git history (commit prior to revert) for future reference; the current `frameworks/f3_innovation.py` is back to its pre-2026-05-18 state.

## References

- Hirshleifer, D., Hsu, P-H., Li, D. (2013). "Innovative Efficiency and Stock Returns." *Journal of Financial Economics* 107(3), 632-654.
- Chan, L., Lakonishok, J., Sougiannis, T. (2001). "The Stock Market Valuation of Research and Development Expenditures." *Journal of Finance* 56(6), 2431-2456.
- Eberhart, A., Maxwell, W., Siddique, A. (2004). "An Examination of Long-Term Abnormal Stock Returns and Operating Performance Following R&D Increases." *Journal of Finance* 59(2), 623-650.
- Peters, R., Taylor, L. (2017). "Intangible Capital and the Investment-q Relation." *Journal of Financial Economics* 123(2), 251-272. (Already referenced in ADR-021.)
- ADR-023 — Narrative personality spec (lattice composer boundary)
- ADR-024 — Mental models library and composition (inversion mandatory)
- ADR-030 — Maturity classifier and young-tier routing (sub-tier routing pattern)
- ADR-031 — Data gap register (two-permitted-Anthropic-call-sites rule)
- ADR-033 — SEC-first source hierarchy
