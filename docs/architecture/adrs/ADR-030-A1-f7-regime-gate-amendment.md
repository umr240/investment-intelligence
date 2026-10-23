# ADR-030 Amendment A1 — Extend Applicability Gating to F7 (and enforce its weight cap)

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Amends ADR-030 (Accepted, 2026-05-14). Nothing implemented. |
| **Amends** | ADR-030 — Maturity classifier and young-tier routing |
| **Also touches** | ADR-042 (`assess_epv_applicability` — the test being reused), ADR-029 (composite renormalisation) |
| **Provenance** | BONEX.ST cross-check, 2026-08-17. Pipeline scored F7 = **7.0 STRONG FIT**; a manual analysis of the same company scored 4.0 "expensive". Investigating the gap found the pipeline wrong for a reason ADR-030 already codified — in a different module. |

---

## 1. Why this is an amendment and not a new ADR

ADR-030 exists because of a single insight: **tier classification is a
current-state check, and a current-state check cannot tell you whether the
model applies.** It inserted a maturity classifier between tier determination
and the DCF engine, because `g = ROIC × reinvestment_rate` is meaningless for a
company whose ROIC is not yet at steady state.

F7 has the identical defect with a different formula, and ADR-030 did not reach
it. Filing this as ADR-044 would create two ADRs with overlapping authority
over "when does a model apply to this company", which is exactly the drift
CLAUDE.md's Tier-2 rule is meant to prevent. It belongs here.

## 2. Evidence

### 2.1 F7 scores a regime break that the same run detects elsewhere

`frameworks/f7_smart_beta.py` — verified, quoting the source:

```
It only asks "is this stock cheap relative to its own history?".

  1. EV/Revenue z-score       z = (current - mean(10yr)) / std(10yr)
  2. P/B z-score              same scale

MIN_HISTORY_YEARS = 5            # spec wants 10; <5 = unfeasible
```

BONEX.ST result: EV/Rev z = **−0.757** ("cheap"), P/B z = **−0.406** ("below
average") → **7.0 / 10, STRONG FIT**, computed over **6** annual periods
(5 ESEF + 1 yfinance).

In the **same run**, ADR-042's `assess_epv_applicability` reports:

> `inflecting` — margin history crosses from loss to profit (−54.5% → +23.6%);
> the median is dominated by a pre-inflection regime

So one module in this engine knows the business regime broke and refuses to
average across it, while another averages across it and issues a STRONG FIT.
**Same engine, same dataset, two epistemic standards.** That inconsistency is
the finding; the score is only its symptom.

### 2.2 The z-scores measure arithmetic, not cheapness

For a company commercialising into scale:

- **EV/Revenue** compresses because the denominator grows. BONEX revenue went
  213 → 1,175 SEK m across the window.
- **P/B** compresses because retained earnings accumulate once the company
  turns profitable — equity grew 265 → 867 SEK m.

Both z-scores drift negative **regardless of what the share price does**. A
"cheap" reading here is a measurement of elapsed revenue, not of valuation. It
is a structurally guaranteed false positive for every post-inflection filer,
and BONEX is only where we noticed.

### 2.3 A citation–implementation mismatch the file half-admits

F7 is titled "Smart Beta Timing" and cites Arnott-Beck-Kalesnik, whose subject
is **factor** timing — is the value factor cheap relative to the value factor's
own history. What is implemented is **single-stock multiple** z-scoring, which
is a different signal with a thinner evidence base. The docstring is honest
about the behaviour ("relative to its own history") while the framework name and
citation are not, and the file already labels itself `CONTESTED ACADEMIC
GROUND`. This is the mismatch class the v3.0 audit removed from F5 and F6 and
did not finish in F7.

### 2.4 A separate, worse finding: renormalisation breaches F7's weight cap

F7's own docstring records the spec constraint:

> PROJECT_SPEC §F7 / CLAUDE.md require us to ALWAYS append F7_DISCLAIMER and to
> **weight F7 ≤ 0.10 in any composite score**.

On BONEX only F2, F5 and F7 were feasible. **Measured** by calling
`compute_composite_score({"F2":1.5,"F5":6.5,"F7":7.0}, mode="C",
stage="mid_cap")`:

```
composite = 5.1500   weights_renormalised = True
```

Solving `1.5·w₂ + 6.5·w₅ + 7.0·w₇ = 5.15` subject to `Σw = 1` gives exactly
**0.30 / 0.40 / 0.30**. So F7's effective weight is **0.30 — three times its
documented ≤ 0.10 ceiling.** Confirmed, not inferred.

This is not specific to F7 or to BONEX. **Any capped framework's cap is void
whenever renormalisation runs**, and renormalisation runs precisely when
frameworks are unfeasible — i.e. on the thinnest, least reliable names, where
caps matter most. The mechanism inverts the safeguard exactly when it is
needed.

### 2.5 The composite itself reconciles — there is no weighting bug

Worth stating because it was queried: persisted composite is **5.40**,
framework-weighted composite is **5.1500**, and the difference is **exactly
+0.25** — the PSA "moderate" auto-overlay bonus (ADR-021 §4.4 / CLAUDE.md
overlay-bonus table). The composite arithmetic is correct end to end.

The defect is not that the number is miscomputed. It is that **a correctly
computed number gives 30% of its weight to a framework the spec caps at 10%,
and 30% more to a framework whose inputs are broken (§5).**

## 3. Amendment to ADR-030

### 3.1 Generalise the principle (ADR-030 §Decision)

ADR-030 currently gates **the DCF engine** on maturity. Amend to:

> **Any framework or model whose inputs are averaged, z-scored, or regressed
> across a multi-year history MUST consult the applicability gate before
> scoring.** A detected regime break, or history shorter than the framework's
> own cited requirement, yields **UNFEASIBLE** — never a score.

### 3.2 One shared regime test

`assess_epv_applicability` (ADR-042) already implements the test and is already
validated against BONEX. Promote it out of `valuation/greenwald/` to a
shared location (e.g. `frameworks/base.py` or `valuation/regime.py`) and have
both consumers call it. Two copies of a regime test is how the two standards
in §2.1 reappear.

### 3.3 F7 routing table (new)

| Condition | F7 outcome |
|---|---|
| Regime break detected (`inflecting`) | **UNFEASIBLE** — "valuation history spans a regime break; z-scores measure the break, not cheapness" |
| Annual history < 10 (the cited requirement) | **UNFEASIBLE** — stop scoring at 5 and calling it thin |
| History ≥ 10 **and** regime-stable | Score as today, disclaimer unchanged |

`MIN_HISTORY_YEARS` rises from 5 to **10**, matching the spec the file already
cites. This will mark F7 unfeasible for most of the current universe. That is
the correct outcome: the alternative is a scored number the file itself calls
too noisy.

### 3.4 Weight cap must survive renormalisation (new invariant)

> A framework with a documented maximum weight retains that maximum **after**
> renormalisation. Excess released by a capped framework redistributes to the
> uncapped survivors. If capping leaves fewer than **two** uncapped feasible
> frameworks, the composite is **suppressed**, not renormalised.

The second clause matters for BONEX: with F7 unfeasible, the feasible set is
F2 (already suspect — see §5) and F5. One or two frameworks is not a composite,
and printing a single-decimal score over it implies a breadth of evidence that
does not exist.

### 3.5 Consequence for BONEX.ST

F7 7.0 → **UNFEASIBLE**. Feasible set collapses to F2 + F5. Under §3.4 the
composite is **suppressed**, and the honest output is: F5 = 6.5 (quality),
BEW 7/7 (extreme-winner candidate), no scoreable composite. That is the state
the name is actually in.

## 4. Inversion (mandatory)

| Forward | Inversion | Mitigation |
|---|---|---|
| Gating F7 removes a false positive. | Does gating hide a real signal? | F7 is a *cheapness* signal only; the docstring and CLAUDE.md both say it predicts neither moat nor quality. Losing it on thin history costs little. |
| Raising the floor to 10yr matches the spec. | Does F7 then ever run? | Rarely, on this universe. If F7 is almost never feasible, that is an argument about whether F7 belongs in the composite at all — surfaced, not resolved here. |
| Reusing the EPV gate stops the two standards diverging. | What if the gate is wrong? | Then it is wrong in one place for both consumers, which is strictly better than being right in one and absent in the other. It is pinned by tests (ADR-042) and externally corroborated (ADR-043 §1.5). |
| Enforcing the weight cap restores the safeguard. | Could suppressing the composite hide a usable read? | Per-framework scores and overlays still render. Only the single aggregate number is withheld — the number most likely to be quoted without its caveats. |

## 5. Out of scope (named, not fixed)

- **F2's sign convention.** BONEX rendered `% from 52w high: +29.8%` while
  trading ~29.9% *below* its high. The magnitude is right, the sign inverted.
  Real, smaller, separate.
- **F2's PEAD input.** Reported `mixed_recent_positive` against a guidance cut
  from >35% to 33–36% and a −7% share reaction. Likely reading an EPS-surprise
  flag and missing the guidance revision, which is the PEAD-relevant event.
- **F1/F4 mislabelled as jurisdictional unfeasibility.** Sweden's
  Finansinspektionen publishes a PDMR insider register and a net-short-position
  register; our gap text says "issuers file no SEC Form 4", which is true and
  reads as "unavailable". A connector gap dressed as a jurisdictional
  impossibility stops the search. Belongs with ADR-041's disclosure-side gap.
- **Whether F7 should exist.** §4 raises it; deciding it is not this
  amendment's business.

## 6. Validation plan

1. ~~Dump the actual composite weight vector.~~ **Done (§2.4):** renormalised
   weights are 0.30 / 0.40 / 0.30 for the F2+F5+F7 subset; F7 exceeds its cap
   3×. Note `mode="C"` and `mode="default"` produce identical output, and
   `stage` does move the result (`mid_cap` 5.1500 vs `established` 5.2100), so
   the stage classifier is load-bearing on the composite and worth its own
   verification pass.
2. Contract test: a synthetic filer with a loss→profit margin history and 6
   annual periods ⇒ F7 UNFEASIBLE with the regime reason.
3. Contract test: a 12-year regime-stable filer ⇒ F7 scores as today (proves
   the gate is not a blanket disable).
4. Invariant test: for any feasible subset, no framework's post-renormalisation
   weight exceeds its documented cap; < 2 uncapped survivors ⇒ composite is
   None.
5. Re-run NVDA and AAPL to confirm no regression on regime-stable US names.

## 7. Consequences

`frameworks/f7_smart_beta.py` (gate + floor 5→10) ·
`valuation/greenwald/__init__.py` → shared regime module ·
`deepdive/orchestrator.py` (cap enforcement + suppression) ·
`deepdive/scorecard_view.py` / `cli/main.py` / `frontend` (render a suppressed
composite as suppressed, not as 0.0) · tests per §6.

**Every persisted composite for a ticker with an unfeasible framework is
affected.** Composites will fall or vanish. Nothing about a company changes;
the number stops overstating its own evidential basis.

---

*ADR-030 Amendment A1 | The Boardroom Lab | 2026-08-17 | **PROPOSED — not ratified***

*ADR-030's insight was that a correct calculation on an inapplicable model is
more dangerous than no calculation, because it looks like an answer. That
insight was implemented for one engine and left unenforced everywhere else, so
the system ended up holding two standards at once and shipping the laxer one.
The weight-cap finding is the same shape one level up: a safeguard that
silently disables itself exactly when the data is thinnest.*
