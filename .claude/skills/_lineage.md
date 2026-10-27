# Skill lineage — auto-generated, do not hand-edit

> Regenerated: 2026-10-27. Source: each skill's `changelog:` frontmatter array. Regenerate via `invest skill lineage --rebuild`.

Per ADR-034: this index is the chronological master view of every skill change. The frontmatter `changelog:` array on each individual skill remains the source of truth — this file is a derived index.

## All skills — chronological (newest first)

```
# Skill lineage — cross-skill chronological view
# Newest first. Format: DATE  SKILL  VERSION  SUMMARY
────────────────────────────────────────────────────────────────────────────────────────────────────
2026-10-27  external-signals         v1.2.0  postconditions follow ADR-057 — every stored value is verified in code before persistence (counts per outcome reported), replacing the 30-character quote rule; not_disclosed rows may carry value_text.
2026-08-16  intrinsic-value          v2.0.0  MAJOR — adds the full Greenwald ladder (ADR-042, new valuation/greenwald/ package): asset reproduction value with goodwill excluded and R&D/SG&A capitalised, cycle-normalised earnings power with growth-capex added back, and the EPV-vs-AV franchise test. Adds the EPV applicability gate (the Greenwald analogue of ADR-030's maturity routing) plus a recent-regime EPV for inflecting filers. Adds cross-engine synthesis. Also fixed a second silent swallow: EPVResult.notes were computed then discarded. Breaking for consumers of the v1 single-engine output shape.
2026-08-16  intrinsic-value          v1.0.0  initial. Wraps `invest iv` (new CLI surface). Authoring surfaced a live defect: the ADR-029 reverse-DCF gate still matched pre-ADR-030 tier labels ('A_gaap'/'B_pt_rescued'), so market-implied growth had been silently None for every classified ticker since 2026-05-14 — masked by a bare `except: pass`. Fixed in valuation/damodaran/intrinsic.py. Verified across NVDA, INTA, AAPL, BONEX.ST.
2026-05-17  dive-complete            v1.1.1  docs — clarified that this skill does not invoke the narrative LLM layer (deterministic-only per permitted_anthropic_calls: [none]). Narrative is a separate explicit step via `invest score-card TICKER --narrate`. Body note added; workflow unchanged.
2026-05-16  audit-completeness       v1.1.0  declare composes: per ADR-036 — suggests external-signals (category-A gap closure), depends on edgartools>=2.0 (Company.is_foreign API). Minor bump for additive metadata.
2026-05-16  dive-complete            v1.1.0  declare composes: per ADR-036 — uses audit-completeness workflow as step 1 (gap audit), suggests external-signals for category-A closure, depends on edgartools>=2.0. Minor bump for additive metadata.
2026-05-16  external-signals         v1.1.0  declare composes: per ADR-036 — depends on anthropic>=0.28 (the permitted call site) and edgartools>=2.0 (8-K fetching). Minor bump for additive metadata.
2026-05-15  audit-completeness       v1.0.4  Tier 1.3 — FPI detection now uses edgartools.Company.is_foreign as primary signal (one-call, fast) with 40-F/20-F filing-history check as fallback for ex-FPI redomiciliation pattern (SHOP). User-driven SEC-first principle.
2026-05-15  audit-completeness       v1.0.3  rd_intensity-missing classification refined for bundled_in_opex pattern (HIMS).
2026-05-15  audit-completeness       v1.0.2  fix R&D display — compute ratio (rd_expense / revenue) and render as percentage, not absolute.
2026-05-15  audit-completeness       v1.0.1  fix FPI detection (use submissions.json probe, not FinancialSourceLog). SHOP correctly classified as former-FPI; F1 90d-buyers + ceo_equity_pct upgraded to D.
2026-05-15  dive-complete            v1.0.1  fix AttributeError on framework_unfeasible_count — that column lives on Company, not DeepDiveRun. Now derived from per-framework score columns (f1_score..f7_score null = unfeasible). Surfaced when first invoked on PATH/LULU/MRVL.
2026-05-15  audit-completeness       v1.0.0  initial. Smoke test on SHOP surfaced 2 defects.
2026-05-15  dive-complete            v1.0.0  initial.
2026-05-15  external-signals         v1.0.0  initial — LLM-supplementary extraction of NRR/GRR/ARR/GMV/take-rate from 8-K EX-99.1. dangerous: true (token spend); strict isolation from F1-F7 (writes external_signals only).
```

## Per-skill version timelines

```
# audit-completeness  (current: v1.1.0)
  shadow_mode_until: 2026-05-29
  last_reviewed:     2026-05-16

  Version timeline (oldest → newest):
  ──────────────────────────────────────────────────────────────────────
  ○ 2026-05-15  v1.0.0
        initial. Smoke test on SHOP surfaced 2 defects.
  ○ 2026-05-15  v1.0.1
        fix FPI detection (use submissions.json probe, not FinancialSourceLog). SHOP correctly classified as former-FPI; F1 90d-buyers + ceo_equity_pct upgraded to D.
  ○ 2026-05-15  v1.0.2
        fix R&D display — compute ratio (rd_expense / revenue) and render as percentage, not absolute.
  ○ 2026-05-15  v1.0.3
        rd_intensity-missing classification refined for bundled_in_opex pattern (HIMS).
  ○ 2026-05-15  v1.0.4
        Tier 1.3 — FPI detection now uses edgartools.Company.is_foreign as primary signal (one-call, fast) with 40-F/20-F filing-history check as fallback for ex-FPI redomiciliation pattern (SHOP). User-driven SEC-first principle.
  ● 2026-05-16  v1.1.0
        declare composes: per ADR-036 — suggests external-signals (category-A gap closure), depends on edgartools>=2.0 (Company.is_foreign API). Minor bump for additive metadata.

```

```
# dive-complete  (current: v1.1.1)
  shadow_mode_until: 2026-05-29
  last_reviewed:     2026-05-17

  Version timeline (oldest → newest):
  ──────────────────────────────────────────────────────────────────────
  ○ 2026-05-15  v1.0.0
        initial.
  ○ 2026-05-15  v1.0.1
        fix AttributeError on framework_unfeasible_count — that column lives on Company, not DeepDiveRun. Now derived from per-framework score columns (f1_score..f7_score null = unfeasible). Surfaced when first invoked on PATH/LULU/MRVL.
  ○ 2026-05-16  v1.1.0
        declare composes: per ADR-036 — uses audit-completeness workflow as step 1 (gap audit), suggests external-signals for category-A closure, depends on edgartools>=2.0. Minor bump for additive metadata.
  ● 2026-05-17  v1.1.1
        docs — clarified that this skill does not invoke the narrative LLM layer (deterministic-only per permitted_anthropic_calls: [none]). Narrative is a separate explicit step via `invest score-card TICKER --narrate`. Body note added; workflow unchanged.

```

```
# external-signals  (current: v1.2.0)
  shadow_mode_until: 2026-05-29
  last_reviewed:     2026-05-16

  Version timeline (oldest → newest):
  ──────────────────────────────────────────────────────────────────────
  ○ 2026-05-15  v1.0.0
        initial — LLM-supplementary extraction of NRR/GRR/ARR/GMV/take-rate from 8-K EX-99.1. dangerous: true (token spend); strict isolation from F1-F7 (writes external_signals only).
  ○ 2026-05-16  v1.1.0
        declare composes: per ADR-036 — depends on anthropic>=0.28 (the permitted call site) and edgartools>=2.0 (8-K fetching). Minor bump for additive metadata.
  ● 2026-10-27  v1.2.0
        postconditions follow ADR-057 — every stored value is verified in code before persistence (counts per outcome reported), replacing the 30-character quote rule; not_disclosed rows may carry value_text.

```

```
# intrinsic-value  (current: v2.0.0)
  shadow_mode_until: 2026-08-30
  last_reviewed:     2026-08-16

  Version timeline (oldest → newest):
  ──────────────────────────────────────────────────────────────────────
  ○ 2026-08-16  v1.0.0
        initial. Wraps `invest iv` (new CLI surface). Authoring surfaced a live defect: the ADR-029 reverse-DCF gate still matched pre-ADR-030 tier labels ('A_gaap'/'B_pt_rescued'), so market-implied growth had been silently None for every classified ticker since 2026-05-14 — masked by a bare `except: pass`. Fixed in valuation/damodaran/intrinsic.py. Verified across NVDA, INTA, AAPL, BONEX.ST.
  ● 2026-08-16  v2.0.0
        MAJOR — adds the full Greenwald ladder (ADR-042, new valuation/greenwald/ package): asset reproduction value with goodwill excluded and R&D/SG&A capitalised, cycle-normalised earnings power with growth-capex added back, and the EPV-vs-AV franchise test. Adds the EPV applicability gate (the Greenwald analogue of ADR-030's maturity routing) plus a recent-regime EPV for inflecting filers. Adds cross-engine synthesis. Also fixed a second silent swallow: EPVResult.notes were computed then discarded. Breaking for consumers of the v1 single-engine output shape.

```

## Validation findings at last regeneration

0 error(s), 4 warning(s).

### Warnings

- **audit-completeness** — §3.4: shadow_mode_until=2026-05-29 is in the past — graduate to non-shadow + bump minor OR extend the window with rationale.
- **dive-complete** — §3.4: shadow_mode_until=2026-05-29 is in the past — graduate to non-shadow + bump minor OR extend the window with rationale.
- **external-signals** — §3.4: shadow_mode_until=2026-05-29 is in the past — graduate to non-shadow + bump minor OR extend the window with rationale.
- **intrinsic-value** — §3.4: shadow_mode_until=2026-08-30 is in the past — graduate to non-shadow + bump minor OR extend the window with rationale.
