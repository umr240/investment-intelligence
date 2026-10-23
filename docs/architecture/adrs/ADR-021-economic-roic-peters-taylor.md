# ADR-021 — Economic ROIC adjustment: Peters-Taylor, not management non-GAAP

| Field | Detail |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-05-09 |
| **Provenance** | User intervention 2026-05-09: Claude was about to wire SBC + amortization-of-intangibles + restructuring as add-backs to compute "Non-GAAP ROIC" (Phase 2 proposal in the prior turn). User correctly pulled the brakes. |
| **Supersedes** | The "Phase 2 Non-GAAP ROIC pipeline" sketched at the end of the prior universe-query-script turn — explicitly rejected. |
| **Preserves** | ADR-017 (warehouse + task pattern); CLAUDE.md determinism rule; the existing F1–F7 framework score logic. |
| **Updates** | The parked (archived) direction for "tier-2/3 economic adjustment" in the screener — pivots from management non-GAAP to Peters-Taylor (2017 JFE). |

---

## 0. The mistake about to happen

In the prior turn Claude proposed a "Phase 2" pipeline:

> Add SBC + amortization_of_intangibles + restructuring_charges to `_CASHFLOW_CONCEPTS`/`_INCOME_CONCEPTS`, derive `Company.non_gaap_operating_income` and `Company.non_gaap_roic`, then add `--min-non-gaap-roic` to the screener.

That is **management non-GAAP ROIC**. The biggest add-back — SBC — is the most aggressive cosmetic in the SaaS playbook. Building it as a first-class warehouse column institutionalises bad methodology. User rejected it; this ADR records why and locks the alternative.

---

## 1. The three views of ROIC (correctly distinguished)

The framing "GAAP vs Non-GAAP" is a false binary. There are **three** distinct views and the screener architecture must not conflate them:

| View | Source | Authority | Treatment of reinvestment |
|---|---|---|---|
| **(1) GAAP ROIC** | SEC-mandated | Standardised, conservative, regulatory | Mechanically punishes R&D, SG&A reinvestment, SBC, acquisitions |
| **(2) Management non-GAAP ROIC** | Issuer earnings releases | Advocacy; varies by issuer; not auditable | Adds back what management says is "non-cash" or "one-time" — most commonly SBC |
| **(3) Economically-adjusted ROIC** | Peters & Taylor (2017) JFE ★★★, Eisfeldt-Papanikolaou (2013) JF ★★★ | Peer-reviewed academic finance | Capitalises R&D and 25% of SG&A as off-balance-sheet intangible assets, then re-derives ROIC against the augmented invested-capital base |

(2) and (3) both attempt to "rescue" intangible-heavy firms from GAAP optics. Only (3) survives an audit.

---

## 2. Why management non-GAAP fails — specifically the SBC add-back

Management's argument: "SBC is non-cash, so add it back."

Critic's response (correct):

| Point | Explanation |
|---|---|
| Share count grows | SBC-heavy SaaS dilutes 5–15%/yr |
| Future buybacks are real cash | Dilution that gets repurchased later is a deferred cash expense, not a non-cash one |
| "Non-cash" is a label, not exemption from economic dilution | Every share issued reduces the per-share economics of the existing shareholder |
| Recursive abuse | If SBC is "non-cash and excludable", every cash compensation can be replaced by stock and the line item disappears. The economic substance — paying employees — stays |

INTA is the textbook case (using actual figures from the existing dive output, not the loose numbers Claude fabricated):
- FY25 revenue: ~$504M
- SBC: ~$88M (~17% of revenue)
- Share count: up ~10% YoY largely from SBC + option exercises
- GAAP operating income: −$27.4M
- Management non-GAAP operating income: +$75.6M
- The +$103M swing is mostly the SBC add-back

If we'd built "non_gaap_roic" naively (just adding the swing to numerator), INTA would screen at a wildly inflated ROIC. The ~10%/yr dilution would be invisible. We'd be optimising for the wrong number.

---

## 3. Peters-Taylor is the academically defensible alternative — and we already have it

`overlays/ica.py` (Intangible Capital Adjustment) already implements the Peters-Taylor formula. From the file:

```python
# Knowledge capital perpetual inventory (R&D capitalised at 15%/yr decay)
KC_t = (1 - 0.15) × KC_{t-1} + R&D_t

# Organisational capital perpetual inventory (25% of SG&A at 20%/yr decay)
OC_t = (1 - 0.20) × OC_{t-1} + 0.25 × SG&A_t

# Adjusted invested capital includes the off-balance-sheet stack
Adj_NOPAT  = GAAP_NOPAT + R&D_t − 0.15 × KC_{t-1}
Adj_ROIC   = Adj_NOPAT / (Invested_Capital + KK_t + OC_t)
```

Trigger conditions per `overlays/detector.py`:

- **ICA-1**: F5 ROIC fails AND R&D intensity ≥ 10%
- **ICA-2**: F5 ROIC fails AND sector ∈ {SaaS, biotech, semiconductors, deep-tech, pharma}
  *(Phase 5i correction: an earlier draft of this ADR added "software" and "technology" — that
  was unjustified silent drift, reverted to match `docs/methodology/DIAGNOSTIC_OVERLAYS.md`.
  Software is a superset of SaaS; "technology" is too broad. ICA-2 must stay precision-targeted.)*
- **ICA-3**: GAAP loss BUT OCF / |net income| > 2 (the "INTA shape")
- **ICA-4**: P/B > 4 AND GP/A in **top sector tercile** AND R&D intensity > 15%
  *(Phase 5i correction: prior ADR draft said "top 40%" — that loosened the spec without
  rationale; canonical is top tercile (~33%) per `DIAGNOSTIC_OVERLAYS_v1.md`. Code in
  `overlays/detector.py` currently approximates with `gp_a >= 0.20`; a true sector-percentile
  lookup is a TODO.)*

When the dive runs and an ICA trigger fires, the user is prompted (per CLAUDE.md "passive overlay detector" rule) to authorise running the overlay. The overlay returns adjusted NOPAT, knowledge capital, organisational capital, and the corrected ROIC.

**This is exactly the right adjustment**. Peer-reviewed, deterministic, no advocacy, no SBC laundering.

---

## 4. Decision

### 4.1 Reject — do NOT build management non-GAAP ROIC at the warehouse layer

| Rejected | Reason |
|---|---|
| `Company.non_gaap_operating_income` warehouse column | Institutionalises the SBC-add-back fallacy |
| `Company.non_gaap_roic` warehouse column | Same — would expose `--min-non-gaap-roic` flag that screens for management-flattered numbers |
| Adding `ShareBasedCompensation` as an Income/Cashflow concept *for the purpose of ROIC adjustment* | We may want SBC as a separate signal (dilution check) but **not** as a ROIC numerator add-back |

### 4.2 Accept — Peters-Taylor stays at the overlay (tier-2 dive) layer

| Accepted | Why |
|---|---|
| `overlays/ica.py` continues to be the canonical economic ROIC adjustment | Already peer-reviewed, already implemented |
| ICA detector triggers fire during dive flow | User-confirmation gates apply per CLAUDE.md |
| `framework_score` task at universe scale uses GAAP ROIC | Conservative; intangible-heavy candidates surface as low-ROIC + ICA-trigger combos in the dive layer |

### 4.3 Accept — multi-factor screener as a coarse pre-filter (NO conflation with non-GAAP)

The screener can keep a "growth-compounder" multi-factor filter as a **proxy** for "intangible-heavy reinvestment". It catches the same shape of company (high gross margin + healthy FCF + double-digit growth + low debt) without claiming to compute Non-GAAP ROIC.

**Crucially** the documentation must NOT call it "non-GAAP ROIC". It is a multi-factor quality screen anchored on:
- Gross margin (Novy-Marx 2013 JFE — gross profitability factor)
- FCF margin (cash-flow lie detector)
- Revenue growth (operating leverage proxy)
- Debt/equity (financial health)

**Tuning thresholds is allowed** but every tuning is a Goodhart hazard — the moment a threshold becomes the target it stops being a useful signal. Default thresholds (0.65 / 0.15 / 0.15 / 0.5) were calibrated against INTA — they correctly catch INTA and correctly reject NMAX/FIGS. PATH and DV missing is acceptable: their qualitative moats are weaker than INTA's.

### 4.4 IMPLEMENTED in Phase 5i (DEC-28) — Peters-Taylor integrated into composite scoring

After re-reading user audit feedback on 2026-05-09, the "deferred" framing
was wrong. Peters-Taylor adjusted ROIC IS the right adjustment AND it IS
deterministic AND its inputs (R&D + SG&A history) are already on
`Financial`. There's no reason to keep it as opt-in passive overlay. The
integration shipped in this turn:

- Migration `j1e2f3a4b5c6_pt_adjusted_roic.py`: adds
  `Company.pt_adjusted_roic` + `pt_adjusted_roic_fetched_at` + index.
- `screener/tasks/fundamentals.py:_compute_pt_adjusted_roic`: mirrors
  `overlays/ica.py:run_ica` math at warehouse-rollup time. Same KC + OC
  perpetual-inventory formula. No SBC add-back.
- `screener/tasks/composite.py:compute_composite` accepts
  `pt_adjusted_roic=` and uses
  `economic_roic = max(roic, pt_adjusted_roic)` only when PT exceeds
  GAAP by ≥3 percentage points (the "materially exceeds" gate). Below
  that threshold, GAAP is preferred for conservatism.
- `deepdive/orchestrator.py`: ICA auto-runs when ICA-* triggers fire;
  result lands in `DeepDiveRun.overlays_results_json` and
  `FrameworkScore.overlay_ica_run = True`.
- `cli/main.py:_prompt_and_run_overlays`: skips ICA confirmation
  (deterministic, already persisted); PSA/BEW remain user-gated.
- The universe query script (archived): new `--min-pt-adjusted-roic` flag.

CLAUDE.md §4 ("Overlay detector is always passive") refined: split into
"deterministic overlays auto-integrate" vs "interpretive overlays stay
passive". ICA is the only deterministic one today. See DEC-28.

### 4.5 What was NOT shipped (still deferred)

- F5 score logic itself still uses GAAP ROIC. The composite layer above
  it picks the better of GAAP/PT, but F5's internal score didn't change.
  This is intentional — F5 is per-framework methodology; mixing GAAP
  and PT inside one framework score muddies the metric. The composite
  layer is the right home for the swap.
- True sector-percentile lookup for ICA-4's "top tercile" GP/A check.
  Code still uses the absolute approximation `gp_a >= 0.20`. TODO.
- Backfilling `Company.pt_adjusted_roic` across the existing 4,263
  Tier-2/3-ready warehouse rows requires re-running
  `invest task run fundamentals` (the rollup is now extended; cached
  companyfacts means no SEC re-fetch, ~15 min wall clock). This is a
  manual step the user runs when ready.

### 4.5 Reverted in this turn

- The universe query script (archived) — the `--mode growth-compounder` and `--min-gross-margin` additions from the prior turn are reverted. Script is back to the strict-AND-only filter shape. (Reasoning: the tuning conversation needs to settle before the multi-factor mode is wired; the user's verdict was to keep it but the methodology audit should land first.)

---

## 5. Honest acknowledgements (Claude's errors in the prior turn)

| Error | Correction |
|---|---|
| Conflated "Non-GAAP" (management) with the broader concept of economic adjustment | These are distinct categories — see §1 |
| Proposed adding SBC as an operating-income add-back | SBC is real economic cost via dilution; only amortization-of-intangibles and one-time restructuring are defensible (and even those need audit per issuer). The mention of "phase 2" institutionalising this was wrong |
| Used "$245M revenue" for INTA in a back-of-envelope ROIC adjustment | Actual FY25 revenue ~$504M per existing dive output. Bad arithmetic |
| Estimated "Non-GAAP ROIC ~17%+" for INTA | Even with management non-GAAP NOPAT of ~$60M and IC of ~$600–800M post-acquisition, the figure is ~7.5–10%, not 17%+. Order-of-magnitude error from missing the IC denominator |
| Implied PATH/DV deserve to be "rescued" by a tuned threshold | Goodhart's Law: tuning thresholds to catch borderlines defeats the design intent. PATH (12.7% growth, mature decel + agentic-AI risk) and DV (4% ROIC, ad-tech under structural pressure) have weaker moats than INTA. Missing them is plausibly correct, not a bug |
| Did not flag that `overlays/ica.py` already implements Peters-Taylor | Should have surfaced the existing solution before proposing a new one |

---

## 6. The actually-correct recommendation chain

1. **Conservative GAAP screen at warehouse scale**: `Company.roic` from `FundamentalsTask`. Default screen.
2. **Coarse multi-factor "quality-or-growth" pre-filter** (proxy, not non-GAAP): keep it as an opt-in mode in the screener, with thresholds anchored to peer-reviewed factor research (Novy-Marx GP/A; Sloan accruals; Piotroski) — NOT to "what makes INTA pass".
3. **Peters-Taylor at dive time** via `overlays/ica.py`: when a candidate's GAAP ROIC looks suspect (R&D-heavy, intangible-heavy, persistent OCF / loss combo), the dive's ICA detector fires and the user authorises the Peters-Taylor adjustment per CLAUDE.md's passive-overlay rule.
4. **Peters-Taylor at warehouse scale** (deferred): only build `Company.pt_adjusted_roic` when there's evidence the dive-time path is too narrow.

---

## 7. Latticework cross-checks

| Mental model | Application |
|---|---|
| **Map vs territory** | GAAP, management non-GAAP, and Peters-Taylor are three different maps. None is the territory. Multi-map approach reduces single-source bias |
| **Chesterton's Fence** | GAAP forces SBC to be expensed because it is real economic cost via dilution. Stripping it out at the warehouse level tears down a fence the regulators built deliberately |
| **Goodhart's Law** | Tuning a screener threshold to catch borderlines (PATH/DV) defeats the screener's selection logic. The threshold becomes the target |
| **Cash flow as lie detector** | A company can manipulate adjusted EBITDA, operating income, and "non-GAAP" ROIC much more easily than sustained free cash flow. Dive-layer FCF analysis catches what the screener can't |

---

## 8. What stays in the codebase post-ADR (updated 2026-05-09 Phase 5i)

| Component | Status |
|---|---|
| `screener/tasks/fundamentals.py` writing `Company.roic` (GAAP) | Unchanged |
| `screener/tasks/fundamentals.py:_compute_pt_adjusted_roic` (PT) | **NEW Phase 5i** — same math as `overlays/ica.py`, runs at warehouse rollup |
| `Company.pt_adjusted_roic` warehouse column | **NEW Phase 5i** — migration `j1e2f3a4b5c6` |
| `Company.composite_score` formula | **UPDATED Phase 5i** — uses `max(roic, pt_adjusted_roic)` when PT exceeds GAAP by ≥3pp |
| `framework_score` task at universe scale | Unchanged (still uses GAAP via F1-F7 internals) |
| `overlays/ica.py` (Peters-Taylor) | Unchanged — still canonical for dive-time economic ROIC |
| `overlays/detector.py` ICA-1/2/3/4 triggers | Comments aligned to "top sector tercile" not "top-40%"; INNOVATION_SECTORS reverted to 5 |
| `deepdive/orchestrator.py` ICA invocation | **UPDATED Phase 5i** — auto-runs ICA when triggers fire (no user prompt) |
| `cli/main.py:_prompt_and_run_overlays` | **UPDATED Phase 5i** — skips ICA (auto-integrated); PSA/BEW user-gated |
| Universe query script (archived) `--min-pt-adjusted-roic` | **NEW Phase 5i** |
| CLAUDE.md §4 "Overlay detector is always passive" rule | **REFINED Phase 5i** — split deterministic vs interpretive; ICA auto-integrates |
| Future `--mode growth-compounder` flag | NOT shipped; if added later must be documented as multi-factor proxy, NOT Non-GAAP ROIC |
| Future `Company.non_gaap_*` columns | **Rejected** per §4.1; do not build |
| Future sector-percentile lookup for ICA-4 GP/A | TODO — currently `gp_a >= 0.20` approximation |
| Future F5 internal use of PT-adjusted ROIC | Deferred per §4.5 — composite layer is the right home, not per-framework internals |

---

## 9. References

- Peters, R. H., & Taylor, L. A. (2017). *Intangible Capital and the Investment-q Relation*. Journal of Financial Economics 123 (2): 251–272. ★★★
- Eisfeldt, A. L., & Papanikolaou, D. (2013). *Organization Capital and the Cross-Section of Expected Returns*. Journal of Finance 68 (4): 1365–1406. ★★★
- Novy-Marx, R. (2013). *The Other Side of Value: The Gross Profitability Premium*. Journal of Financial Economics 108 (1): 1–28. ★★★ — for the multi-factor proxy's GP/A anchor
- Sloan, R. G. (1996). *Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?*. The Accounting Review 71 (3): 289–315. ★★★ — for the OCF/net_income accruals quality bar
- Piotroski, J. D. (2000). *Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers from the Pool of High Book-to-Market Value Firms*. Journal of Accounting Research 38 (Suppl.): 1–41. ★★★ — F1's underlying rigour
- CLAUDE.md "Overlay detector is always passive" — non-negotiable user-confirmation gate before any overlay runs
- ADR-017 — warehouse + task pattern (preserved)
- Existing implementation: `overlays/ica.py`, `overlays/detector.py`, `frameworks/f5_growth_quality.py`

---

*ADR-021 | The Boardroom Lab | 2026-05-09*

*The right map is the academically defensible one. Management non-GAAP is advocacy with a leaf blower; Peters-Taylor is research. Build the latter, refuse the former.*
