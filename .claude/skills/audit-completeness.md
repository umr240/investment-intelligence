---
name: audit-completeness
description: |
  Audit data completeness for a single ticker, classifying every gap by
  ADR-031 root-cause category (A-E). Invoke when the user asks "what's
  missing for TICKER", "data completeness for TICKER", "why is F6 partial
  for TICKER", or when planning whether to authorize an /external-signals
  extraction. Read-only — touches no DB writes, makes no network calls.
  Returns a structured inventory of present vs missing fields grouped by
  category, with per-row pointers to ADR-031 §1.2.
do_not_invoke_when:
  - The user wants a fresh dive — use /dive-complete which runs gap audit
    as a side-effect of step 1
  - The ticker is unknown to the universe — surface that fact and refuse
    rather than producing an empty audit
  - The user is asking about cross-universe gap distribution (use the
    /data-quality-report skill when it ships in Phase 3+; today the
    ADR-031 §1.2 register is the canonical source)
arguments:
  - name: ticker
    type: ticker
    required: true
    description: Stock ticker (uppercase, e.g. SHOP)
preconditions:
  - Company row exists for TICKER
  - At least one Financial row exists for TICKER (else the audit has no
    Financial-level coverage to report)
postconditions:
  - Returns a structured inventory: {fields_present, fields_missing_by_category}
  - Every missing field classified A/B/C/D/E per ADR-031 §1.1
  - Output cites ADR-031 §1.2 row for each missing field (link in skill output)
side_effects:
  - None (read-only)
  - Writes one telemetry row to `skill_invocations` (operational ledger only)
dangerous: false
token_budget_estimate:
  prompt: 2000
  completion: 1500
cost_estimate_usd: 0.0
permitted_anthropic_calls:
  - none
related_adrs:
  - ADR-031
  - ADR-022
mental_models:
  - margin_of_safety
  - first_principles
shadow_mode_until: 2026-05-29
version: 1.1.0
last_reviewed: 2026-05-16
implementation: cli/skills/audit_completeness.py
composes:
  skills:
    - name: external-signals
      relation: suggests
      constraint: ">=1.0"
  libraries:
    - name: edgartools
      constraint: ">=2.0"
changelog:
  - "1.0.0 (2026-05-15): initial. Smoke test on SHOP surfaced 2 defects."
  - "1.0.1 (2026-05-15): fix FPI detection (use submissions.json probe, not FinancialSourceLog). SHOP correctly classified as former-FPI; F1 90d-buyers + ceo_equity_pct upgraded to D."
  - "1.0.2 (2026-05-15): fix R&D display — compute ratio (rd_expense / revenue) and render as percentage, not absolute."
  - "1.0.3 (2026-05-15): rd_intensity-missing classification refined for bundled_in_opex pattern (HIMS)."
  - "1.0.4 (2026-05-15): Tier 1.3 — FPI detection now uses edgartools.Company.is_foreign as primary signal (one-call, fast) with 40-F/20-F filing-history check as fallback for ex-FPI redomiciliation pattern (SHOP). User-driven SEC-first principle."
  - "1.1.0 (2026-05-16): declare composes: per ADR-036 — suggests external-signals (category-A gap closure), depends on edgartools>=2.0 (Company.is_foreign API). Minor bump for additive metadata."
---

## What this does

Inventories the data completeness state for one ticker against the canonical gap register (ADR-031 §1.2). Every Company-level and Financial-level field the system tries to populate is queried; each missing field is classified by the root-cause taxonomy (A = issuer non-disclosure, B = source-policy exclusion, C = parser miss, D = FPI structural, E = insufficient history).

Output is a structured table the user can scan to decide:
- Which gaps are closeable by engineering (C)
- Which gaps need supplementary sources like LLM extraction (A) — sets up `/external-signals` invocation
- Which gaps are time-curable (E)
- Which gaps are structural and need a different solution entirely (B, D)

This skill captures the ad-hoc Python the 2026-05-15 session ran 3+ times. Rule-of-three satisfied.

## Workflow

```
1. Pre-flight: verify Company row + ≥1 Financial row
2. Query Company-level fields (ceo_equity_pct, beta, pe_trailing, pb_ratio, etc.)
3. Query latest-annual Financial row fields (nrr_pct, grr_pct, customer_concentration_pct,
   share_based_compensation, rd_expense, goodwill)
4. Query external_signals rows for the ticker (note: this channel is read-only here)
5. Classify each missing field per ADR-031 §1.1 (A-E categories)
6. Render category-grouped table
7. Write skill_invocations row
```

## Pre-flight checks

```python
from data.db import SessionLocal
from data.models.schema import Company, Financial
from sqlalchemy import select, func

with SessionLocal() as s:
    c = s.execute(select(Company).where(Company.ticker == TICKER.upper())).scalar_one_or_none()
    assert c is not None, f"No Company row for {TICKER}. Add to universe before auditing."
    fin_count = s.execute(
        select(func.count(Financial.id)).where(Financial.company_id == c.id)
    ).scalar()
    assert fin_count >= 1, f"{TICKER} has no Financial rows — refresh fundamentals first."
```

## Field-level audit (the canonical list)

For each row: query the persisted location, classify by root cause if missing.

### Company-level fields

| Field | If null → category | ADR-031 cite |
|---|---|---|
| `Company.ceo_equity_pct` (state=disclosed_exact) | D for Canadian FPIs; C otherwise | §1.2 F5 row "ceo_equity_pct" |
| `Company.is_founder_ceo` | C — parser conservative | §1.2 F5 row "is_founder_ceo" |
| `Company.beta` | C — yfinance gap; recomputable from PriceHistory | §1.2 Company-level meta |
| `Company.pe_trailing`, `pb_ratio` | C — yfinance gap | §1.2 Company-level meta |
| `Company.roic`, `pt_adjusted_roic` | C — parser miss on OperatingIncomeLoss + IC components | §1.2 F5 row "roic" / "pt_adjusted_roic" |
| `Company.shares_float` | C — yfinance + 13F partial | §1.2 Company-level meta |

### Financial-row fields (latest annual)

| Field | If null → category | ADR-031 cite |
|---|---|---|
| `Financial.nrr_pct` (or retention_state='not_disclosed') | **A** — issuer non-disclosure for most | §1.2 F6 row "nrr_pct" |
| `Financial.grr_pct` | **A** — almost no issuer discloses GRR | §1.2 F6 row "grr_pct" |
| `Financial.customer_concentration_pct` | A for low-concentration issuers; C if above-threshold-undetected | §1.2 F6 row |
| `Financial.arr_state` | A/C — rare XBRL tagging | §1.2 F6 row "arr_state" |
| `Financial.share_based_compensation` | C — parser concept list (fixed 2026-05-15 for SHOP) | §1.2 F5 indirect (no SBC add-back per ADR-021) |
| `Financial.rd_expense` | C — some filers bundle in opex; `rd_disclosure_state='bundled_in_opex'` partial fix | §1.2 F3 row "rd_intensity" |
| `Financial.goodwill` | C — non-acquirer = true zero; serial-acquirer parser miss otherwise | not directly in §1.2; informational |

### Out-of-table fields (computed at dive time)

| Field | If missing → category | Notes |
|---|---|---|
| F4 options put/call ratio | **B** — paid data only per PROJECT_SPEC §F4 | §1.2 F4 row "options_put_call_ratio" |
| F4 13F institutional delta | C — `change_in_shares` null for 100% of rows (yfinance snapshot) | §1.2 F4 row "13f_institutional_delta" |
| BEW TAM estimate | **A** — TAM not in any SEC filing | §1.2 Overlays row "BEW.tam_estimate" |
| BEW sector median EV/Rev | C — never warehoused; in-scope sector aggregation | §1.2 Overlays row "BEW.sector_median_ev_revenue" |
| F1 90d open-market buyers | D for FPIs (Section 16 exempt); otherwise true 0 vs missing | §1.2 F1 row "open_market_buyers_90d" |

### Per-FPI-status adjustment

If the ticker's `Company.exchange` indicates a former Foreign Private Issuer (e.g., NMS but with 40-F history), upgrade these classifications:
- `ceo_equity_pct` null → **D** (MIC parser exists but needs pipeline integration)
- `open_market_buyers_90d` = 0 → **D** (Section 16 exempt, not a true zero)

The presence of any 40-F or 20-F in the most-recent 5 SEC filings is the signal.

## Failure modes

| Failure | Detection | Surface to user |
|---|---|---|
| Universe miss | Precondition fail | "No Company row for {TICKER}; cannot audit." |
| No Financial rows | Precondition fail | "{TICKER} has no fundamentals fetched. Run /dive-complete first." |
| Classification ambiguity | When parser status is null AND no XBRL signal AND no MD&A text mention | Report `category=uncertain` with sub-cause hypothesis; do not force-classify |

## Shadow-mode verification (until 2026-05-29)

While `shadow_mode_until` is in the future:
1. After producing the audit output, also fetch the comparable output from a manual python query (ad-hoc, like the 2026-05-15 session ran) and compare counts
2. If category counts differ → `[SHADOW-MODE ANOMALY] audit-completeness v1.0.0: {field} classified as {X} by skill but {Y} by reference query`
3. Record in `skill_invocations.anomalies_json`

This is read-only verification — no double-write risk. Cost is one extra DB scan per invocation; negligible.

## Audit trail

- `skill_invocations` row records: args (ticker), classification counts per category, anomaly_count
- Output is NOT persisted to a separate table — re-running is the canonical refresh path (the audit is a stateless function of the DB state at query time)

## Examples

### Example 1 — SHOP (former FPI)

```
User: audit-completeness SHOP
Claude: [invokes skill]

Data Completeness Audit — SHOP (Shopify Inc., NMS, former FPI)

Present: 14 / 22 canonical fields

By root-cause category:
  A (issuer non-disclosure):   4 fields — F6 nrr_pct, F6 grr_pct, F6 customer_concentration, BEW tam
  B (source-policy exclusion): 1 field  — F4 options put/call ratio
  C (parser miss):             0 fields — all fixable engineering closed for SHOP
  D (FPI structural):          2 fields — F1 90d Form-4 buyers (Section 16 exempt pre-2026),
                                          F5 ceo_equity_pct (DEF 14A absent; MIC parser available)
  E (insufficient history):    1 field  — F7 will mature in 12mo (SHOP has 7yr; needs 5+)

Recommended next actions:
  - Closeable now via /external-signals SHOP: nrr_pct (LLM may extract from press
    release; SHOP Q1 2026 confirmed not_disclosed via that channel)
  - Closeable now via the MIC parser already built: ceo_equity_pct (NOT yet pipeline-
    integrated — see ADR-032 §4 deferred skills)
  - Cannot close: F4 options (paid feed only); BEW tam (out-of-filing)

Postconditions: 8/8 pass.
Anomalies: none.
```

### Example 2 — INTA (US domestic SaaS)

```
User: audit-completeness INTA

Data Completeness Audit — INTA (Intapp, NMS)

Present: 18 / 22 canonical fields

By root-cause category:
  A: 2 fields — F6 grr_pct, BEW tam
  B: 1 field — F4 options
  C: 0 fields
  D: 0 fields (US domestic)
  E: 1 field — F7 z-score history (5yr threshold, INTA has 4yr post-IPO)

Notably present:
  - Financial.nrr_pct = 123.0% (disclosed_exact via 10-K MD&A regex) — F6 reads this
  - external_signals.nrr_pct = 123.0% (high confidence, Q1 2026 press release)
    → triangulated signal; both channels agree

Postconditions: 8/8 pass.
Anomalies: none.
```
