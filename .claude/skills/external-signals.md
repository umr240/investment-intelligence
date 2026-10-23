---
name: external-signals
description: |
  Extract supplementary operating metrics (NRR/GRR/MRR/ARR/GMV/take-rate)
  from a ticker's most recent 8-K EX-99.1 earnings press release via the
  permitted Anthropic call site (deepdive/external_signals.py). Invoke
  when the user explicitly authorizes LLM-supplementary extraction OR when
  /audit-completeness flagged category-A gaps the user wants to close.
  ALWAYS requires explicit confirmation before running (dangerous: true)
  because it spends Anthropic tokens (~$0.03/invocation per ADR-031 §3).
  Strictly isolated from F1-F7 framework scoring — results land in the
  external_signals table only, never in canonical Financial / Company fields.
do_not_invoke_when:
  - The user hasn't explicitly authorized LLM extraction (or hasn't asked
    about the specific signal targets — never proactively spend tokens)
  - The ticker's 8-K shows no EX-99.1 earnings press release (e.g., FPIs
    that file 6-K instead — use /mic-parse equivalent when it ships)
  - Monthly Anthropic spend would exceed $100 (ADR-031 §4.4 hard ceiling —
    refuse to invoke and surface the budget state)
  - The user is asking a question that the deterministic path can already
    answer (e.g., INTA NRR is already in Financial.nrr_pct via 10-K MD&A
    regex; check the deterministic field FIRST before paying for LLM
    extraction)
arguments:
  - name: ticker
    type: ticker
    required: true
    description: Stock ticker (uppercase)
  - name: period_end
    type: text
    required: false
    description: ISO date of the period the extraction targets (default = latest 8-K's report date)
preconditions:
  - User has explicitly confirmed authorization to spend ~$0.03 Anthropic tokens
  - Company row exists with CIK populated
  - At least one 8-K filing exists on the issuer's CIK feed in the last 90 days
  - Current month-to-date Anthropic spend (sum of cost_usd in skill_invocations
    + external_signals rows attributed to this month) is below $100 / month
  - The deterministic Financial.nrr_pct / Financial.arr_state fields have been
    checked FIRST — if they're disclosed_exact, the user must explicitly opt
    into a triangulation run rather than a fresh extraction
postconditions:
  - "1-N ExternalSignalRecord rows persisted with extraction_method=llm_anthropic"
  - "Every persisted row has signal_name, extraction_confidence in {high, medium, low, not_disclosed}, source_url (resolves), source_quote (verbatim from source >=30 chars OR empty for not_disclosed), source_accession, extracted_model, extracted_at"
  - "For confidence != not_disclosed rows: source_quote length >=30 chars (verbatim requirement from external_signals.py system prompt)"
  - "For confidence = not_disclosed rows: signal_value_numeric IS NULL AND signal_value_text IS NULL (no fabrication)"
  - "skill_invocations row written with cost_usd populated (actual measured cost, not estimate)"
side_effects:
  - "Anthropic token spend (~$0.022-$0.034 per invocation per ADR-031 sec 3.1 measurements; budget gate applies)"
  - "DB writes: 1-7 ExternalSignalRecord rows depending on signal targets"
  - "SEC EDGAR rate-limit budget consumed (one 8-K fetch)"
  - "No writes to Financial / Company canonical tables (strict isolation per ADR-031 sec 4.1)"
dangerous: true
token_budget_estimate:
  prompt: 7000
  completion: 500
cost_estimate_usd: 0.028
permitted_anthropic_calls:
  - external_signals.py
related_adrs:
  - ADR-031
  - ADR-022
  - ADR-023
mental_models:
  - margin_of_safety
  - first_principles
  - inversion
shadow_mode_until: 2026-05-29
version: 1.1.0
last_reviewed: 2026-05-16
implementation: cli/skills/external_signals.py
composes:
  libraries:
    - name: anthropic
      constraint: ">=0.28"
    - name: edgartools
      constraint: ">=2.0"
changelog:
  - "1.0.0 (2026-05-15): initial — LLM-supplementary extraction of NRR/GRR/ARR/GMV/take-rate from 8-K EX-99.1. dangerous: true (token spend); strict isolation from F1-F7 (writes external_signals only)."
  - "1.1.0 (2026-05-16): declare composes: per ADR-036 — depends on anthropic>=0.28 (the permitted call site) and edgartools>=2.0 (8-K fetching). Minor bump for additive metadata."
---

## What this does

Runs the LLM-extraction prototype (`deepdive/external_signals.py`) for one ticker, persisting results to the isolated `external_signals` channel. Surfaces them in the dive display via the existing `_render_external_signals` panel. **F1-F7 framework scoring is unaffected** — the architectural moat from ADR-031 §4.1 is preserved.

This is the second permitted Anthropic call site (after `deepdive/narrative.py`). No third site exists or will be added without an ADR amendment.

The skill exists because the manual workflow was executed 3+ times in the 2026-05-15 session (SHOP twice, INTA once) and every invocation followed an identical structure with identical guards. Rule-of-three satisfied.

## Workflow

```
1. Pre-flight: confirm dangerous-skill authorization received from user
2. Pre-flight: check month-to-date Anthropic spend (skill_invocations + external_signals)
3. Pre-flight: verify Company + CIK + 8-K EX-99.1 available
4. Pre-flight: check Financial.nrr_pct / arr_state — if disclosed_exact, ask user
   whether to proceed with triangulation
5. Run: fetch_latest_earnings_8k_text(ticker, cik) → (text, accession, url, label)
6. Run: extract_signals_via_llm(...)  ← THE Anthropic call
7. Run: persist_extraction(result)
8. Render: External Signals panel (already wired in cli/main.py:_render_external_signals)
9. Post-flight: verify every persisted row has its mandatory audit-trail fields
10. Post-flight: write skill_invocations row with actual measured cost
```

## Pre-flight checks

```python
# Check 1: dangerous-skill confirmation
# (Claude MUST surface the cost estimate and signal targets BEFORE running.
# Example confirmation prompt:
#   "About to spend ~$0.03 Anthropic tokens to extract NRR/GRR/MRR/ARR/GMV/
#   merchant_count/take_rate for {TICKER} from its Q{N} {YYYY} 8-K
#   press release. Proceed? (y/n)"
# Only proceed on explicit y/yes.)

# Check 2: month-to-date spend ceiling ($100/mo per ADR-031 §4.4)
from data.db import SessionLocal
from data.models.schema import SkillInvocation
from sqlalchemy import select, func
from datetime import datetime, date
month_start = date.today().replace(day=1)
with SessionLocal() as s:
    mtd = s.execute(
        select(func.coalesce(func.sum(SkillInvocation.cost_usd), 0.0))
        .where(SkillInvocation.invoked_at >= month_start)
    ).scalar()
assert mtd < 100.0, f"MTD Anthropic spend ${mtd:.2f} ≥ $100 ceiling (ADR-031 §4.4). Refuse."

# Check 3: Company exists with CIK
from data.models.schema import Company
with SessionLocal() as s:
    c = s.execute(select(Company).where(Company.ticker == TICKER.upper())).scalar_one_or_none()
    assert c is not None, f"No Company row for {TICKER}."
    assert c.cik, f"{TICKER} has no CIK — cannot fetch 8-K."

# Check 4: deterministic field already populated?
from data.models.schema import Financial
from sqlalchemy import desc
with SessionLocal() as s:
    latest = s.execute(
        select(Financial)
        .where(Financial.company_id == c.id, Financial.period == "annual")
        .order_by(desc(Financial.fiscal_year))
        .limit(1)
    ).scalar_one_or_none()
    if latest and latest.nrr_pct is not None and (latest.retention_state or "") == "disclosed_exact":
        # Surface to user — let them choose triangulation vs skip
        print(f"NOTE: {TICKER} already has Financial.nrr_pct = {latest.nrr_pct}% from "
              f"deterministic 10-K MD&A regex (retention_state=disclosed_exact). LLM "
              f"extraction would triangulate (verify) rather than discover. "
              f"Proceed for triangulation? (y/n)")
```

## Main workflow

```python
from datetime import date
from deepdive.external_signals import (
    fetch_latest_earnings_8k_text,
    extract_signals_via_llm,
    persist_extraction,
)

# Step 5: deterministic fetch
fetched = fetch_latest_earnings_8k_text(TICKER, CIK)
assert fetched is not None, f"No 8-K EX-99.1 found for {TICKER}"
text, accn, url, label = fetched

# Step 6: LLM extraction
# Period end defaults to last calendar-quarter end; override via skill arg
period_end = period_end_arg or _infer_quarter_end_from_filing_date(accn)
result = extract_signals_via_llm(
    ticker=TICKER, source_text=text, source_url=url,
    source_accession=accn, source_label=label, period_end=period_end,
)

# Step 7: persist (idempotent — upserts on company_id+signal_name+as_of_date)
n_persisted = persist_extraction(result)
assert n_persisted >= 1, f"Extraction returned 0 rows — investigate before retry"
```

## Failure modes

| Failure | Detection | Surface to user |
|---|---|---|
| User declines confirmation | Pre-flight check 1 | Abort cleanly; no Anthropic call; no telemetry written |
| MTD spend ≥ $100 | Pre-flight check 2 | "Anthropic budget ceiling reached this month (MTD: $X.XX). Refusing extraction. See ADR-031 §4.4 for the policy." |
| No 8-K found | Step 5 returns None | "No 8-K earnings press release found for {TICKER} in last 90 days. FPI? Use /mic-parse equivalent when it ships." |
| Anthropic API error | exception from step 6 | Catch, log to telemetry with `success=False, error_message=...`, surface to user. Do NOT retry automatically (avoid silent cost amplification). |
| LLM returned non-verbatim quote | Postcondition check (quote not in source_text) | Anomaly fires; record row but flag confidence as `low` and surface to user |
| Source URL doesn't resolve | Spot-check the persisted url with HEAD request | Anomaly fires; row is suspect for audit |
| Token spend exceeds budget estimate by >2× | After-call measurement | `[SHADOW-MODE ANOMALY] external-signals v1.0.0: actual spend $X exceeded estimate $0.028 by Nx. Investigate prompt size before next run.` |

## Shadow-mode verification (until 2026-05-29)

While `shadow_mode_until` is in the future:

1. After persistence (step 7), for each persisted row with `confidence != not_disclosed`:
   - Re-fetch the source URL (HEAD request to confirm 200) — verifies the audit trail integrity
   - Search the source text for `source_quote.substring(0, 50)` — confirm verbatim match
   - If either fails → row marked suspect; anomaly fires
2. Compare extracted values against the deterministic field where applicable (e.g., `Financial.nrr_pct` for INTA case):
   - If both present and Δ > 5pp → `[SHADOW-MODE ANOMALY]` triangulation mismatch
3. Record postcondition pass rate and anomalies in `skill_invocations`

Importantly: shadow mode does NOT re-call Anthropic to verify. The verification is deterministic (URL resolves, quote matches source) and adds zero LLM cost. This is why §9.1.3 of ADR-032 explicitly says shadow mode is not a token-doubling penalty for this skill.

## Audit trail

- `external_signals` row: the canonical extraction record (source_url, source_quote, extraction_confidence, extracted_model, extracted_at)
- `skill_invocations` row: telemetry (args, duration, actual cost, postconditions, anomalies)
- The dive/score-card display surfaces `external_signals` rows in the yellow "External Signals (LLM-extracted)" panel — see `cli/main.py:_render_external_signals`

To inspect:
```sql
SELECT signal_name, signal_value_numeric, extraction_confidence, source_quote
FROM external_signals
WHERE company_id = (SELECT id FROM companies WHERE ticker = 'TICKER')
ORDER BY extraction_confidence DESC, signal_name;
```

## Examples

### Example 1 — fresh extraction, user authorizes

```
User: extract external signals for SHOP
Claude: This will spend ~$0.028 Anthropic tokens on Sonnet 4.6 to extract
        NRR/GRR/MRR/ARR/GMV/merchant_count/take_rate from SHOP's most recent
        Q1 2026 8-K earnings press release. Result will land in the
        external_signals table (isolated from F1-F7 scoring). Proceed?
User: yes

Claude: [invokes skill]
  Pre-flight: MTD spend $0.06 / $100 ceiling. Company SHOP, CIK 1594805.
  Deterministic Financial.nrr_pct = None (not_disclosed). Proceeding.
  Fetching 2026-05-05 8-K EX-99.1 (14,738 chars)...
  Anthropic call: 5,133 prompt + 446 completion = $0.0221.
  Persisted 7 ExternalSignalRecord rows:
    GMV   $100.74B  high
    MRR   $212.0M   high
    NRR   —         not_disclosed
    GRR   —         not_disclosed
    ARR   —         not_disclosed
    merchant_count  —  not_disclosed
    take_rate       —  not_disclosed
  Postconditions: 7/7 pass (verbatim quotes verified, URL resolves).
  [External Signals panel renders inline]
```

### Example 2 — budget ceiling hit

```
User: extract external signals for SHOP
Claude: [pre-flight]
  MTD Anthropic spend: $102.34 → exceeds $100 ceiling (ADR-031 §4.4).
  Refusing extraction. To proceed, either wait until next month or amend
  the ceiling via ADR-031 amendment (not unilateral).
```

### Example 3 — triangulation against deterministic field

```
User: extract external signals for INTA --triangulate
Claude: [pre-flight]
  Financial.nrr_pct = 123.0% (disclosed_exact via 10-K MD&A regex).
  Triangulation mode: will compare LLM extraction against this deterministic value.

  [main workflow]
  LLM extracted: nrr_pct = 123.0% (high confidence)
  Quote: "Trailing twelve months' cloud net revenue retention rate as of
   March 31, 2026 was 123%"
  Triangulation: Δ = 0.0pp → AGREE. Both channels independently extract 123%.

  Postconditions: 7/7 pass. Triangulation: clean.
```
