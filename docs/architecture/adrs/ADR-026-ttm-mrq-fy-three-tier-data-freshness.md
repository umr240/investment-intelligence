# ADR-026 — TTM / MRQ / FY three-tier data freshness model

**Status**: Accepted
**Date**: 2026-05-11
**Supersedes**: parts of ADR-018 (which defaulted dive data to annual-only)
**Phase**: 5Q

## Context

A live cross-check on INTA (Phase 5P validation, May 2026) exposed
structural staleness in our framework outputs:

| Metric | Our system | Reality (per Q3 FY2026 earnings call) | Source of drift |
|---|---|---|---|
| Cloud NRR | 120% | **123%** | We pulled annual 10-K (FY25, Jun '25); reality is the 10-Q (Q3 FY26, Mar '26). |
| R&D intensity | 27.3% | **29.0%** | We computed against FY25 annual; LTM is fresher. |
| Revenue growth | 17.1% (FY25 YoY) | **13%** (Q3 FY26 YoY) | Latest quarterly run-rate is materially lower. |
| Cloud ARR | n/a (not extracted) | **$459M, +31% YoY** | The forward-looking SaaS metric isn't an XBRL fact — it's MD&A text we don't parse. |

The freshness gap is **6-11 months** for INTA-class tickers — anything
that filed an annual in mid-prior-year but has 1-3 quarters since.

Today's data path:

```
companyfacts.json  →  Financial rows  (quarterly + annual, BOTH persisted)
                                       ↓
framework code: `reader.annuals(last_n=N)` ← uses ANNUAL ONLY
                                       ↓
10-K text parser ← annual-only Item 1 / 1A / 7 / 8 extraction
```

The quarterly XBRL is already in our DB. The 10-Q TEXT is not. Framework
code does not aggregate quarters into LTM. The result: every signal we
compute from "current" data is actually 6-11 months stale.

## Decision

Adopt the **three-tier institutional model** (LTM + MRQ + FY) as the
data-freshness contract for framework scoring and dive output.
Framework code chooses the right tier per metric:

| Tier | Source | What it answers | Use for |
|---|---|---|---|
| **LTM** (Last Twelve Months) | Synthetic period: SUM of last 4 quarterly rows for flow items | "What's the current run-rate?" | Profitability ratios (ROIC, FCF margin, gross margin, operating margin), interest coverage |
| **MRQ** (Most Recent Quarter) | Latest quarterly Financial row | "What's the snapshot?" | Stock items (cash, debt, equity, IC, working capital) |
| **FY** (Most Recent Annual) | Latest annual Financial row, from 10-K | "What does the audited record say?" | Academic-framework anchors (Piotroski, Sloan, Peters-Taylor, Beneish) + multi-year trajectories + text-heavy disclosures |

LTM derived ratios combine TTM flows with MRQ stocks:
- LTM ROIC = (LTM NOPAT) / (MRQ IC)
- LTM FCF margin = (LTM FCF) / (LTM Revenue)
- LTM Debt/EBITDA = (MRQ Debt) / (LTM EBITDA)

10-Q text becomes a first-class source alongside 10-K text. For
disclosures that companies update quarterly (NRR, Cloud ARR, customer
concentration commentary, guidance changes), the regex parsers read
BOTH 10-K and latest 10-Q and take the freshest disclosure.

## Rationale

**Why three-tier, not full-TTM-everywhere**:

The frameworks we built (F1 Piotroski, F3 Hirshleifer-Hsu-Li, F5
combined ROIC + growth, F7 z-scores) were calibrated on annual data
in their source academic papers. Pushing them onto LTM would distort
the original signal:

- **Piotroski F-Score** — 9-point binary scoring, all on annual YoY
  changes (ROA up, OCF positive, ΔROA positive, etc.). LTM would
  produce a noisier, harder-to-interpret variant of an already-noisy
  signal.
- **Sloan accruals** — annual basis; quarterly working-capital noise
  destroys the signal.
- **Hirshleifer-Hsu-Li** — annual patent grants × R&D. Quarterly
  patent count not meaningful.
- **Peters-Taylor ICA overlay** — annual perpetual inventory for KC
  and OC. Quarterly cadence breaks the 15%/yr KC amortization math.

But for **current-state metrics**:

- The user dives a stock today; they want today's ROIC, not last
  June's ROIC.
- Industry standard (Bloomberg, FactSet, Refinitiv, Morningstar) is
  LTM for ratios, MRQ for balance sheet snapshots.
- Mauboussin's expectations-investing critique cuts both ways: stale
  inputs produce wrong expectations gaps.

The three-tier split lets each framework metric use the right tier
without imposing a single answer on all.

**Why 10-Q text matters distinctly from quarterly XBRL**:

XBRL captures financials. The narrative text in MD&A (Item 2 of 10-Q,
Item 7 of 10-K) is where companies disclose:

- Current NRR / GRR (typically quarterly refreshed)
- Cloud ARR / Total ARR (forward-looking SaaS KPI not in XBRL)
- Customer-concentration updates (qualitative; may shift between
  filings)
- Guidance changes (forward-looking)
- Operational color (sales motions, customer wins, expansion)

INTA explicitly disclosed Cloud NRR = 123% in Q3 FY26 MD&A. Our regex
never saw it because we only parse 10-K text. The fix is structural:
extend the parser fleet to 10-Q too.

## Consequences

### Positive

1. **Eliminates the 6-11 month freshness gap** for INTA-class tickers.
   ROIC, margins, growth rates all reflect the most recent quarterly
   filing.
2. **Cloud NRR / GRR refresh quarterly** — F6's retention signal
   reads from the freshest filing rather than waiting for the next
   annual.
3. **Cloud ARR + Total ARR enter the framework data layer** as
   first-class signals (5Q-5). For SaaS-heavy holdings (PATH, MRVL,
   NVDA's data center segment, etc.) this is the institutional-grade
   forward-looking metric.
4. **Backward-compatible** at the schema level — quarterly Financial
   rows already exist; we just compute new aggregations.
5. **Source-explicit** — dive output labels each metric with its
   source tier ("ROIC -9.4% (LTM Q3 FY26)" not "ROIC -9.4%"). Removes
   the ambiguity that hid the INTA staleness for so long.

### Negative

1. **Per-period source bookkeeping** — every CLI render now needs to
   know which tier each metric came from. Adds rendering complexity.
2. **Backfill question for existing DeepDiveRun rows** — historical
   dives stored annual-derived ratios. Old rows stay as-is (audit
   trail); new dives use the new tiers. The dive `scorecard_json`
   contract has a `_source_tier` per metric field added; old rows
   that lack it are displayed as "FY (legacy)".
3. **Test maintenance** — fixtures need quarterly Financial rows
   alongside the annuals they already contain. Existing tests stay
   green (annual-only is still a valid tier; frameworks that need it
   keep using it).
4. **10-Q text fetch cost** — one additional SEC EDGAR roundtrip per
   dive when 10-Q text is requested. ~50KB payload; rate-limit
   compatible. Cached at the accession-number level like 10-K.
5. **Edge case: recent IPOs with <4 quarters** — `reader.ttm()`
   returns partial-period LTM when fewer than 4 quarters available;
   marked with a `partial: True` flag so consumers can skip it for
   ratios that require a clean year.

### Rejected alternatives

**A. Full TTM/MRQ across all frameworks** — Push every framework
onto LTM regardless of academic source. Rejected because the
calibration of F1 Piotroski, F3 patent-citation, F7 z-scores all
assume annual cadence. Pushing them onto LTM would produce variants
of the original signals with no academic validation.

**B. Quarterly-only mode** — Drop annual data entirely; use quarterly
or LTM everywhere. Rejected because multi-year trajectories
(revenue CAGR, ROIC consistency, BEW extreme-winner cohort tracking)
require annual cadence for noise reduction.

**C. Status quo** — Keep annual default; document the freshness gap
in the methodology box. Rejected because the gap is structural, not
informational. Users running dives in May 2026 against June 2025 data
without explicit labelling will make wrong reads — and discovering
this requires the kind of cross-check the user did with INTA, which
shouldn't be a precondition for trustworthy output.

**D. LLM-driven extraction over earnings transcripts** — Use the
narrative layer to extract fresh ARR, NRR, etc. directly from
quarterly earnings transcripts. Rejected for the same reason as the
broader web-search shelf in the SIM discussion: introduces drift
across model versions, breaks the audit-trail invariant. Transcripts
also aren't SEC-filed and don't have accession-number-level
reproducibility.

## Implementation plan (Phase 5Q)

### Layer 1 — TTM/MRQ infrastructure + 10-Q text

- **5Q-2** `CompanyDataReader.ttm()` + `.mrq()` — synthetic period
  builders. ~3 hours.
- **5Q-3** `fetch_latest_10q_filing()` + `_read_tenq_sections()`
  mirroring 10-K patterns. ~2 hours.
- **5Q-6** F5 (Growth Quality) switches ROIC / FCF margin / Debt-EBITDA
  to LTM; revenue CAGR stays on annuals. ~1 hour.

### Layer 3 — 10-Q-aware text extraction

- **5Q-4** Retention regex (5k-7) extended: pulls from 10-K + latest
  10-Q, returns freshest disclosure. ~1 hour.
- **5Q-5** New `parse_arr_metrics()` for Cloud ARR + Total ARR +
  growth-rate extraction. Schema migration adds
  `Financial.cloud_arr_usd`, `total_arr_usd`,
  `arr_growth_yoy_pct`. ~2 hours.
- Per-metric source labels in dive output: "ROIC -9.4% (LTM Q3 FY26)"
  ~30 min (light version of full Layer 2).

### Validation

- **5Q-7** Re-dive INTA, verify: Cloud NRR = 123% (not stale 120%);
  R&D intensity = 29% LTM (not 27.3% FY25); Cloud ARR $459M
  surfaces. Pytest 49+ passing. ~1 hour.

**Estimated total**: ~10-12 hours focused work.

## What this ADR does NOT do

- **No quarterly framework SCORING** — F1, F3, F5, F7 still emit per-
  annual scores. Only the *current-state inputs* shift to LTM.
- **No full source-tagging infrastructure** (full Layer 2 from the
  prior plan). Per-metric labels in CLI rendering only — no end-to-end
  source provenance in `scorecard_json` keyed per claim.
- **No streaming / real-time data** — quarterly SEC filings come ~45
  days after quarter-end. That's the freshness ceiling.
- **No analyst estimates / forward consensus** — those are a separate
  data domain (sell-side analyst inputs); out of scope for ADR-026.
- **No transcript ingestion** — earnings call transcripts (the source
  the user pasted for the INTA check) are not SEC-filed, not
  accession-number-reproducible, and feed the LLM-second-opinion path
  (`invest chat`), not the deterministic data layer.

## Migration

Schema additions (5Q-5):

```
Financial.cloud_arr_usd          Float
Financial.total_arr_usd          Float
Financial.arr_growth_yoy_pct     Float
Financial.arr_extraction_state   Text   ('disclosed_exact'|'parser_uncertain'|'not_disclosed')
Financial.arr_fetched_at         DateTime
```

Migration `q8e9f0a1b2c3` (next in sequence).

No backfill of existing DeepDiveRun rows — they stay as-is per the
"audit trail preserved" rule from DEC-34/DEC-35. Re-diving any ticker after
this lands populates the new fields automatically.

## References

- ADR-018: dive-data-gap task fleet (which defaulted to annual-only;
  this partially supersedes)
- ADR-021: Peters-Taylor ROIC adjustment (its KC/OC perpetual
  inventory stays annual; not affected by this change)
- ADR-022: methodology disclosure (extends naturally to per-tier
  labels in output)
- DEC-34: yearly checkpoint warning detector (will pick up LTM-vs-annual
  drift as a new signal automatically — no code change needed)
- DEC-35: portfolio reassessment scheduler (same)
- The Mauboussin "Expectations Investing" framework — TTM is the
  institutional default precisely because expectations gaps must be
  measured against current operating reality, not last year's audited
  reality.
