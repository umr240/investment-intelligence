---
name: dive-complete
description: |
  Run the canonical deep-dive workflow for a single ticker with completeness
  guarantees. Invoke when the user says "deep dive TICKER", "full dive on
  TICKER", "dive TICKER with completeness", or asks for a comprehensive
  research output on a specific equity. Wraps `invest data gaps` + `invest
  dive --tier 2 --force --auto-overlays` + scorecard rendering, with
  pre-flight checks for 10-K/A amendments and post-condition delta-anomaly
  detection (the FY2024 overwrite regression observed 2026-05-15 cannot
  recur silently — the postcondition surfaces it).
do_not_invoke_when:
  - "The user asks a cheap-query question like what's TICKER's NRR — answer from existing score-card or external_signals (no fresh dive needed)"
  - "The most recent DeepDiveRun for this ticker is less than 30 minutes old AND the user hasn't asked for a refresh — re-use the existing scorecard"
  - "The ticker has no Company row yet — run invest db-init / verify universe membership first; do not auto-create"
arguments:
  - name: ticker
    type: ticker
    required: true
    description: Stock ticker (uppercase, e.g. SHOP)
  - name: tier
    type: enum:1,2
    required: false
    description: Default 2 (full). Use 1 only when the user explicitly asks for the cheap pre-dive.
preconditions:
  - "Company row exists for TICKER (verify via select 1 from companies where ticker=:t)"
  - "CIK populated on the Company row (XBRL fetch requires it)"
  - "If latest filing is 10-K/A within last 30 days, MUST use --force (else parser restatement-resolution may null out prior-period rows; see ADR-031 sec 1.2 category C parser bug)"
postconditions:
  - "A new DeepDiveRun row created with composite_score IS NOT NULL"
  - "data_completeness == 1.0 OR data_gaps_json populated with explicit gap entries"
  - "All 7 framework rows present in framework_results_json (unfeasible frameworks listed with reason, not silently dropped)"
  - "If a prior DeepDiveRun exists for TICKER within last 24h and |delta-composite| > 1.0, SURFACE as [SHADOW-MODE ANOMALY] to user with hypothesis text"
side_effects:
  - DB writes: Financial / Company / DeepDiveRun / FrameworkScore / FinancialSourceLog
  - SEC EDGAR rate-limit budget consumed (~5-10 requests per dive when
    coverage is full; 30+ on cold cache)
  - No LLM token spend (deterministic path only)
dangerous: false
token_budget_estimate:
  prompt: 3000
  completion: 1500
cost_estimate_usd: 0.0
permitted_anthropic_calls:
  - none
related_adrs:
  - ADR-021
  - ADR-022
  - ADR-031
mental_models:
  - owner_operator_stance
  - margin_of_safety
  - inversion
shadow_mode_until: 2026-05-29
version: 1.1.1
last_reviewed: 2026-05-17
implementation: cli/skills/dive_complete.py
composes:
  skills:
    - name: audit-completeness
      relation: uses
      constraint: ">=1.0"
    - name: external-signals
      relation: suggests
      constraint: ">=1.0"
  libraries:
    - name: edgartools
      constraint: ">=2.0"
changelog:
  - "1.0.0 (2026-05-15): initial."
  - "1.0.1 (2026-05-15): fix AttributeError on framework_unfeasible_count — that column lives on Company, not DeepDiveRun. Now derived from per-framework score columns (f1_score..f7_score null = unfeasible). Surfaced when first invoked on PATH/LULU/MRVL."
  - "1.1.0 (2026-05-16): declare composes: per ADR-036 — uses audit-completeness workflow as step 1 (gap audit), suggests external-signals for category-A closure, depends on edgartools>=2.0. Minor bump for additive metadata."
  - "1.1.1 (2026-05-17): docs — clarified that this skill does not invoke the narrative LLM layer (deterministic-only per permitted_anthropic_calls: [none]). Narrative is a separate explicit step via `invest score-card TICKER --narrate`. Body note added; workflow unchanged."
---

## What this does

Runs the full canonical Tier-2 deep-dive workflow for one ticker. The workflow is the exact sequence the manual orchestration converged on across 4 dive cycles in the 2026-05-15 session:

1. Audit data gaps (read-only, ~10s)
2. Force-refresh fundamentals from EDGAR (handles 10-K/A amendments correctly)
3. Run all 7 frameworks + auto-overlays (ICA/PSA trigger-gated, BEW mandatory, SIM tech-only)
4. Render scorecard with provenance (deterministic + external_signals if present)
5. Verify postconditions; flag anomalies; persist invocation telemetry

The skill is the **checklist over the CLI**. The CLI itself is the canonical implementation; this skill is the wrapper that prevents variance.

## Workflow

```
1. Pre-flight: verify Company row exists + has CIK populated
2. Pre-flight: check most-recent filing — if 10-K/A within 30 days, log warning
3. Run: invest data gaps TICKER             # capture current gap list
4. Run: invest dive TICKER --tier 2 --force --auto-overlays
5. Run: invest score-card TICKER            # render full scorecard (deterministic only)
6. Post-flight: query DeepDiveRun for the just-created row
7. Post-flight: compute Δcomposite vs prior run (if any within 24h)
8. Post-flight: write skill_invocations row with all metrics
9. If anomaly fired: prepend [SHADOW-MODE ANOMALY] banner to response
```

**Note on narrative**: this skill does NOT invoke the LLM narrative layer
(score-card with the narrate flag). Per frontmatter `permitted_anthropic_calls:
[none]`, this skill is deterministic-only. Narrative generation is a separate,
explicit, paid step the user requests (~$0.04-0.05/call, two permitted call
sites per ADR-031 §4.1 + ADR-032 §1.5). After a successful dive-complete,
the user may follow up with the narrate flag on score-card to populate the
`bull_narrative` / `bear_narrative` / `risk_factors` JSON columns on the
just-created DeepDiveRun row. The `invest export deepdive` subcommand
renders both the deterministic scorecard and any persisted narrative as
clean markdown — see `exports/` directory for examples.

## Pre-flight checks

```python
# Check 1: Company row exists
from data.db import SessionLocal
from data.models.schema import Company
from sqlalchemy import select
with SessionLocal() as s:
    c = s.execute(select(Company).where(Company.ticker == TICKER.upper())).scalar_one_or_none()
    assert c is not None, f"No Company row for {TICKER}. Add to universe before diving."
    assert c.cik, f"{TICKER} has no CIK — EDGAR XBRL fetch will fail."

# Check 2: 10-K/A amendment in last 30 days
from data.models.schema import FinancialSourceLog
from sqlalchemy import desc
from datetime import date, timedelta
recent = s.execute(
    select(FinancialSourceLog)
    .where(FinancialSourceLog.ticker == TICKER.upper())
    .where(FinancialSourceLog.form_type == "10-K/A")
    .where(FinancialSourceLog.fetched_at >= date.today() - timedelta(days=30))
).first()
if recent:
    print(f"WARNING: {TICKER} has a 10-K/A amendment in last 30 days. "
          f"--force is REQUIRED to prevent prior-period overwrite (see ADR-031 §1.2 "
          f"category C). The skill body already uses --force; this is informational.")
```

## Failure modes

| Failure | Detection | Surface to user |
|---|---|---|
| `invest dive` returns non-zero exit | Captured stderr from Bash tool | "Dive command failed for TICKER. stderr: …" — do NOT claim success |
| DeepDiveRun row not created | Post-flight SELECT returns None | "Dive completed but no DeepDiveRun row persisted — investigate persistence path" |
| `composite_score IS NULL` | Post-flight check on the new row | "Dive produced a row but composite_score is null — frameworks may all be unfeasible. Check `framework_unfeasible_count`." |
| Composite delta >1.0 vs prior 24h | Comparison in step 7 | `[SHADOW-MODE ANOMALY] dive-complete v1.0.0: composite changed by Δ within 24h. Hypothesis: {amendment / parser regression / source-data change}. Investigate before relying on output.` |
| 7 frameworks not all accounted for | Inspect `framework_results_json` | "Only N of 7 frameworks ran for TICKER. Missing: {names}. Reason persisted." |
| `data_completeness < 1.0` AND no `data_gaps_json` | Both checks | "Completeness below 1.0 but no gaps logged — this is a system inconsistency, not a skill failure." |

## Shadow-mode verification (until 2026-05-29)

While `shadow_mode_until` is in the future, every invocation MUST:

1. After step 8 (writing telemetry), query `skill_invocations` for the last 10 invocations of `dive-complete`
2. Compute postcondition pass rate across those 10
3. Compute anomaly rate across those 10
4. If pass rate < 100% OR unexplained anomaly rate > 0% → write `[SHADOW-MODE STATUS]` to user response with stats
5. When 10 consecutive clean invocations recorded: prompt the maintainer (mention in skill output) that `shadow_mode_until` should be set to `null` and version bumped to 1.1.0

## Audit trail

- `DeepDiveRun` row: the canonical artifact (composite, verdict, framework_results_json, data_gaps_json)
- `FrameworkScore` row: per-framework persisted score
- `Company.composite_score` + `Company.composite_score_fetched_at`: warehouse view
- `skill_invocations` row: this skill's telemetry (args, duration, postconditions, anomalies)

To inspect:
```
invest score-card TICKER                                    # the rendered output
sqlite3 investment_intelligence.db                          # the underlying rows
  > SELECT * FROM deepdive_runs WHERE ticker = 'TICKER' ORDER BY run_date DESC LIMIT 1;
  > SELECT * FROM skill_invocations WHERE args_json LIKE '%TICKER%' ORDER BY invoked_at DESC LIMIT 5;
```

## Examples

### Example 1 — happy path (no amendments, no anomaly)

```
User: dive-complete SHOP
Claude: [invokes skill]
  Pre-flight: Company SHOP exists, CIK 1594805. No 10-K/A in last 30 days.
  Running: invest data gaps SHOP — 3 gaps (F4 options, F5 buyback yield, F1 no Form-4 — FPI).
  Running: invest dive SHOP --tier 2 --force --auto-overlays
  Running: invest score-card SHOP
  Post-flight: DeepDiveRun #N created, composite_score=6.32, verdict=WATCHLIST.
  Δcomposite vs prior run: 0.00 (within tolerance).
  Postconditions: 6/6 pass.
  [scorecard renders]
```

### Example 2 — anomaly fires

```
User: dive-complete SHOP
Claude: [invokes skill]
  ...
  Post-flight: DeepDiveRun #N+1 created, composite_score=4.12, verdict=WATCHLIST.
  Δcomposite vs prior run #N (composite_score=6.32): -2.20 → ANOMALY.

  [SHADOW-MODE ANOMALY] dive-complete v1.0.0: composite dropped 2.20
  from prior run within 24h. Hypothesis: most recent 10-K/A amendment
  may have overwritten prior-period income statement (ADR-031 §1.2
  category C parser bug). Verify FY2024 row has rev/ni populated
  before relying on this output.

  [scorecard renders]
```

### Example 3 — precondition fails

```
User: dive-complete WXYZ
Claude: [invokes skill]
  Pre-flight FAILED: No Company row for WXYZ. Add to universe before diving.
  Skill aborts; no DeepDiveRun created; no telemetry written (precondition failure
  is logged separately as a refusal, not an invocation).
```
