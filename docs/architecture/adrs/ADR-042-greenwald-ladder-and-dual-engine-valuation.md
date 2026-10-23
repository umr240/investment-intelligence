# ADR-042 — Greenwald Ladder + Dual-Engine Intrinsic Value

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Implemented and validated live (§5); this is the Tier-2 artifact CLAUDE.md requires you to ratify. |
| **Phase** | Valuation |
| **Extends** | ADR-027 (Damodaran forward DCF), ADR-029 (sibling outputs), ADR-030 (maturity routing), ADR-032 (project-local skills) |
| **Resolves** | The valuation stack had one framework and no front door. `valuation/damodaran/epv.py` was labelled "Greenwald EPV" but implements `NOPAT / WACC` — a no-growth anchor sharing Damodaran's own NOPAT, not Greenwald's method. The franchise test, which is the actual Greenwald payload, did not exist. |
| **Provenance** | User directive 2026-08-16: "the skill should cover each and everything … Greenwald's algorithm and calculation … Damodaran's … and also needs to consider caveats like young and mature company … core calculation … deterministic." |

---

## 1. Context

### 1.1 Two frameworks, two questions

Damodaran's forward FCFF DCF prices an explicit story: project growth, fade it,
add terminal value. Its growth input is an **assumption**.

Greenwald's method refuses to forecast. It computes what a competitor must
spend to reproduce the assets (AV), what current earnings are worth at zero
growth (EPV), and compares them. That comparison is a **moat test denominated
in currency** — and it is a *finding*, not an assumption.

They are not competing estimates of one quantity. Running both and reading the
disagreement is worth more than either alone.

### 1.2 What existed, honestly

`valuation/damodaran/epv.py` computes `NOPAT / WACC` inside the Damodaran
engine as an ADR-029 sibling. That is a legitimate no-growth anchor and it
stays. It is **not** Greenwald, which requires three adjustments it omits:

1. **Cycle-normalised margin** — current-year EBIT embeds cycle position.
2. **Growth capex added back** — at zero growth a firm spends only maintenance
   capex (≈ D&A). Charging total capex understates earning power for any
   growing company. This is the single largest omission.
3. **Asset reproduction value + the franchise test** — entirely absent.

### 1.3 Defects surfaced while building

Two silent-failure bugs in `_attach_sibling_outputs`, both from the same
anti-pattern (`except Exception: pass`):

- **Reverse DCF dead since 2026-05-14.** ADR-030 re-stamped `tier` with
  maturity sub-labels (`A_mature`, `B_young`, …) but the ADR-029 gate still
  matched `("A_gaap", "B_pt_rescued")`. The gate could only be true when
  maturity classification was absent — i.e. never. `reverse_implied_growth_rate`
  was None for every ticker for three months, invisible because None is a legal
  value and the exception handler swallowed everything.
- **`EPVResult.notes` computed then discarded** — including "EPV negative,
  narrative is the only anchor". A negative EPV surfaced as a bare number with
  no explanation.

Both violate CLAUDE.md §"No silent failures on missing data". Both fixed;
`tests/test_valuation/test_sibling_outputs.py` pins the gate and forbids the
swallow pattern returning.

---

## 2. Decision

### 2.1 New package `valuation/greenwald/` — three pillars

```
asset_value.py      Asset Reproduction Value
earnings_power.py   Cycle-normalised EPV with maintenance-capex adjustment
franchise.py        The EPV-vs-AV test
__init__.py         Orchestration + applicability gate + recent-regime EPV
```

**Asset reproduction value** — reproduction cost, not book:

| Leg | Treatment | Rationale |
|---|---|---|
| Working capital | At book, **excess cash excluded** | A competitor rebuilds the operating float, not the war chest |
| PP&E | Net book residual (`total_assets − current_assets − goodwill`) | **Weakest leg.** No canonical PP&E field; understates AV, so the franchise verdict is biased *toward* `franchise`. Always flagged |
| Goodwill | **Excluded** | A prior acquirer's price, not a competitor's build cost. Including it double-counts the franchise being measured |
| R&D | Capitalised, 6.67yr life | Reuses ADR-021's Peters-Taylor knowledge-capital convention so both engines share one intangible definition |
| SG&A | 25% × 3yr | Greenwald reproduces the customer base with 1–3yr of SG&A; the 25% share matches ADR-021 organisation capital |

**Earnings power** — median margin (robust to one blowout year) applied to
current revenue; growth capex (`|capex| − D&A`, floored at 0) added back;
capitalised at WACC.

**Franchise test** — `EPV / AV`: ≥1.30 `franchise`, 0.80–1.30 `no_franchise`,
<0.80 `value_destruction`, missing legs → `indeterminate` (never "no moat").

### 2.2 The applicability gate — Greenwald's ADR-030

EPV assumes normal earning power is already visible in the history. That
assumption fails detectably for **inflecting** companies:

BONESUPPORT operating margins `[-54%, -38%, -20%, +2%, +19%, +24%]` have a
median of **−9%**. Naive EPV capitalises a loss the business no longer incurs
and returns `value_destruction` for a company whose last three years were
profitable. The arithmetic is right; the tool is misapplied — structurally
identical to ADR-030, where `g = ROIC × reinvestment` broke on young companies.

So `assess_epv_applicability` returns `applicable | inflecting |
not_applicable`, and on `inflecting` the engine additionally computes a
**recent-regime EPV** over the trailing consecutive profitable years. The
franchise test then runs on whichever EPV is defensible.

Effect on BONEX.ST: full-history EPV −$7.95/sh → recent-regime **+$34.49/sh**;
franchise verdict flips `value_destruction` → `franchise` at 1.30×.

This is **not** a forecast. It is the same deterministic math on the regime
that actually obtains. Forecasting remains confined to the ADR-028 scenario
path, which requires the user's stated story.

### 2.3 Shared WACC

Greenwald borrows the Damodaran engine's WACC. Discounting two ladders at
different rates would make their comparison meaningless — WACC is a property of
the company, not of the framework (`single_source_of_truth`). Fallback to 9.0%
is loud, never silent.

### 2.4 One skill, not two

The user asked whether this warrants `/damodaran-intrinsic-value` and
`/greenwald-intrinsic-value` separately. **No** — the cross-engine comparison is
the deliverable, and splitting would produce two half-answers plus a manual
reconciliation step. `/intrinsic-value` (v2.0.0) reports both ladders, both
applicability gates, and a synthesis table. `--no-greenwald` exists for the
rare single-engine case.

### 2.5 What this ADR does NOT decide

- **No persistence for Greenwald results.** In-memory only; revisit if the
  franchise ratio becomes a screener input.
- **No gross-PP&E sourcing.** Would materially improve AV; needs a new
  canonical field.
- **No macro-refresh automation.** `risk_free_rate.json` (95d) and
  `implied_erp.json` (137d) are stale as of 2026-08-16 and both engines inherit
  it. Separate concern, flagged not fixed.
- **No skill-discovery restructure** (§6).

---

## 3. Inversion (mandatory)

| Forward | Inversion | Mitigation |
|---|---|---|
| Two engines beat one. | Does a second number just create false confidence? | They are reported as a **disagreement matrix**, not averaged. The "usable DCF + no franchise" cell is explicitly labelled the dangerous one. |
| The franchise test measures a moat. | What if AV is simply wrong? | It is a floor — PP&E at net book, intangibles partial. Bias is toward `franchise`, stated in every run and pinned by a test. |
| Recent-regime EPV rescues inflecting filers. | Is this cherry-picking the good years? | It is, and that is why it is labelled an **upper reading**, requires ≥2 consecutive profitable years, and never replaces the full-history number — both are shown. |
| Applicability gates prevent misuse. | What if the gate itself misfires? | A consistently loss-making company is deliberately `applicable` — negative earning power is a genuine finding there, not a misapplication. Pinned by test. |
| Deterministic beats LLM judgement. | Does determinism imply correctness? | No. NVDA's forward IV is deterministic and structurally wrong. Hence the reliability verdict layer, which is the actual product. |

---

## 4. Alternatives considered

- **Alt 1 — extend `damodaran/epv.py` in place.** Rejected: Greenwald is a
  different framework with its own applicability rules, not a better formula.
  Fusing them would hide which assumptions belong to whom.
- **Alt 2 — two separate skills.** Rejected per §2.4.
- **Alt 3 — auto-generate young-company scenarios.** Rejected: manufactures a
  story and launders it as arithmetic. ADR-028's story discipline stands.
- **Alt 4 — report only the applicable engine.** Rejected: the disagreement is
  the most valuable output.

---

## 5. Validation (live, 2026-08-16)

| Ticker | Damodaran | Greenwald | Reading |
|---|---|---|---|
| NVDA | QUALIFIED · `A_mature` · IV 59.66 vs px 225 (g capped to WACC−50bps) | AV 8.27 · EPV 29.19 · **FRANCHISE 4.11×** | Both say the DCF understates |
| AAPL | **refuses** · `C_growth_invalid` (negative reinvestment) | AV 18.23 · EPV 73.85 · **FRANCHISE 3.49×** | Greenwald works where the DCF cannot |
| INTA | NOT USABLE · `B_young` | applicable · EPV −1.41 · `value_destruction` | Consistently loss-making; genuine finding |
| BONEX.ST | NOT USABLE · `A_young` · ESEF fundamentals | **inflecting** · full −7.95 → recent **+34.49** · **FRANCHISE 1.30×** | Gate working; ADR-041 + ADR-042 compose |

Gates: `ruff` clean on `valuation/greenwald/`; `mypy --strict` clean on the
three pure modules (the DB-loading orchestrator carries the same SQLAlchemy
`Column` pattern as the pre-existing `damodaran/loader.py`, which fails
identically — 61 pre-existing errors, not a regression). **218 passed, 2
skipped** (was 179). Skill CI green: frontmatter, lineage, mental-model slugs,
signature compatibility, mandatory evals.

---

## 6. Open — skill discovery (needs your decision)

`/intrinsic-value` is **not natively invocable** as a slash command. ADR-032
puts skills at `.claude/skills/*.md` (flat); Claude Code discovers skills at
`.claude/skills/<name>/SKILL.md`. Options:

1. **Leave as-is.** Claude reads the `.md` when asked — the current pattern for
   all four skills. Zero risk, no native `/intrinsic-value`.
2. **Restructure to `<name>/SKILL.md`.** Native discovery, but touches ADR-032
   §2.1 and five CI files that glob `.claude/skills/*.md`
   (`test_signature_compatibility`, `test_evals`, `test_version_lineage`,
   `test_mental_model_refs`, `_lineage` rebuild). This is ADR drift → your call.
3. **Dual-home.** Rejected — guarantees drift between two copies.

Recommendation: **(2)**, as its own change with an ADR-032 amendment, once
you've used the skill enough to want it bound to a keystroke.

## 7. Consequences

| File | LOC | Purpose |
|---|---:|---|
| `valuation/greenwald/asset_value.py` | ~200 | NEW — reproduction cost |
| `valuation/greenwald/earnings_power.py` | ~230 | NEW — normalised EPV |
| `valuation/greenwald/franchise.py` | ~165 | NEW — the franchise test |
| `valuation/greenwald/__init__.py` | ~320 | NEW — orchestration + applicability gate |
| `valuation/damodaran/intrinsic.py` | ~45 Δ | Reverse-DCF tier-family gate; EPV notes surfaced; two swallows removed |
| `cli/main.py` | ~230 Δ | `invest iv` — dual-engine output + reliability layer |
| `.claude/skills/intrinsic-value.md` | ~290 | NEW — skill v2.0.0 |
| `tests/test_valuation/test_greenwald.py` | ~215 | 26 tests |
| `tests/test_valuation/test_sibling_outputs.py` | ~95 | 13 tests pinning the ADR-030 regression |

**Known limits:** AV is a floor (net-book PP&E) · macro reference data stale ·
Greenwald results not persisted · recent-regime EPV is an upper reading ·
franchise thresholds (1.30 / 0.80) are Greenwald convention, not calibrated to
this universe.

---

*ADR-042 | The Boardroom Lab | 2026-08-16 | **PROPOSED — not ratified***

*The valuation stack could price a story but could not ask whether the story was
defensible. The franchise test is that question, and it is the one a DCF
structurally cannot answer: a forward model prices growth because g is an input,
so it will happily assign value to growth in a commodity business. Running both
ladders at one WACC and reading the disagreement is the product — not a second
opinion on the same number, but the only independent check on the first one's
central assumption.*
