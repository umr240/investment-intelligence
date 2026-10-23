# ADR-022 — Methodology Disclosure & Source Provenance

| Field | Detail |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-05-09 |
| **Provenance** | User intervention 2026-05-09: "we need to support non-GAAP metrics also but with a pinch of salt, always combining with the GAAP metrics". User flagged the Frankenstein-non-GAAP risk (cross-platform methodology mixing — FactSet vs Yahoo vs Fiscal.ai add back different things) and proposed a Stage 0c data-consistency checker. |
| **Supersedes** | Nothing (new ADR). |
| **Updates** | ADR-021 §4.1 — declares the enforcement mechanism for the "no management non-GAAP" rule (visible disclosure on every dive, not just code comments). |
| **Preserves** | CLAUDE.md determinism rule; ADR-021 Peters-Taylor selection; ADR-017 warehouse-task pattern. |

---

## 0. The reframe

Earlier ADRs decided **what** non-GAAP methodology we use (Peters-Taylor 2017 capitalisation; ADR-021). This ADR decides **how** we declare provenance so a reader can audit the dive without reading the ADR.

Charlie Munger's complaint about adjusted earnings was not that non-GAAP exists, but that:
1. Management controls what gets adjusted (conflict of interest)
2. Platforms mix methodologies (FactSet adjusts X, Yahoo adjusts Y)
3. "One-time" charges become structural (every Q has a "one-time" item)
4. SBC gets hidden in footnotes while EPS looks clean

The user's principle, codified here:
> **Never use non-GAAP in isolation. Always triangulate with GAAP + FCF + ROIC. If two sources give different non-GAAP for the same company, use the more conservative.**

---

## 1. Decision

### 1.1 Every metric carries a declared source

Every value used in a dive's framework scores or composite must be traceable to a declared source. The declared source has three components:

| Component | Today's value | Where declared |
|---|---|---|
| **Origin** | SEC EDGAR `companyfacts.json` for the issuer's 10-K | Stage 0c panel + ICA-5 `relevant_numbers.methodology` |
| **Accession number** | The single 10-K accession the row materialised from | `Financial.accession_number` (already persisted) |
| **Adjustments** | Peters-Taylor capitalisation only — no earnings add-backs | Stage 0c panel + ICA-5 `relevant_numbers.methodology.addbacks_excluded` |

### 1.2 Stage 0c — methodology disclosure panel

Every `invest dive` prints a Methodology panel **before** the framework scores table. The panel declares:

- Source ("SEC 10-K XBRL — same accession for both legs")
- GAAP ROIC formula
- Non-GAAP ROIC method (Peters-Taylor full / Eisfeldt-Papanikolaou OC-only when R&D isn't disclosed)
- ✓ What is capitalised: R&D → KC (15%/yr), 25% SG&A → OC (20%/yr)
- ✗ What is **not** added back: SBC, restructuring, acquisition costs, impairment, "one-time" items

The panel is mandatory output. Token cost ~50 per dive — cheap insurance against silent methodology drift.

### 1.3 ICA-5 self-audits provenance

The ICA-5 trigger condition string includes "Methodology-consistent: both legs from same SEC 10-K XBRL; no SBC/restructuring/acquisition add-backs (ADR-021 §4.1)". The `relevant_numbers.methodology` dict carries the structured equivalent for downstream consumers (LLM narrative, audit logs).

Future-state rule: **if any future code change makes the GAAP and non-GAAP legs come from different sources, the trigger MUST be updated to declare both sources, and the gap MUST be discarded if sources differ.** Cross-source ROIC differences are not the ICA signal — they're noise from methodology mismatch.

### 1.4 New external data sources require explicit Stage 0c integration

If a future PR adds FactSet, Yahoo Finance, Fiscal.ai, or any other non-SEC data source, the integration must:

1. Declare the source's methodology in code (which add-backs are included; how each metric is derived).
2. Persist the source on every value it produces (e.g., `Financial.source_factset` or a separate FactSet shadow table).
3. Update the Stage 0c panel to declare both/all sources.
4. Update ICA-5 (and any other triangulation triggers) to enforce same-source comparison.
5. **Never silently mix sources at the row level** — e.g. don't take revenue from SEC and operating income from FactSet for the same company-period.

The four-quadrant principle stands: GAAP + Non-GAAP + FCF + ROIC are the four lenses; if two of the four disagree materially across sources, the system must declare the divergence rather than picking a winner silently.

### 1.5 The conservative-source rule

When two sources disagree on a non-GAAP value, prefer the more conservative (lower for ROIC / margins; higher for debt / share count). Document the choice. This applies to non-GAAP only — GAAP is regulatory and should not require a "conservative" pick across sources (any divergence is a parser bug to fix).

---

## 2. What this ADR does NOT do

- Does **not** mandate FactSet (or any specific platform). The user explicitly noted: "im not saying we need to use FactSet". Reference-platform selection is deferred until a concrete need arises (e.g., institutional validation requirement).
- Does **not** add a triangulation alarm system (Munger-style "if 2 of 4 disagree, halt"). That would be a follow-on ADR if/when external data sources are integrated.
- Does **not** change ADR-021. The Peters-Taylor choice stands. This ADR is purely about the disclosure layer.

---

## 3. Anti-patterns this ADR forbids

| Pattern | Why forbidden |
|---|---|
| `Company.non_gaap_revenue = anthropic_completion(...)` | LLM derivation outside `deepdive/narrative.py` violates CLAUDE.md determinism rule |
| `total_debt = sec_value if sec_value else factset_value` (silent fallback) | Cross-source mixing without source-of-record persistence |
| ICA-5 firing on `roic_factset - roic_sec` gap | Same as 1.3 — different-source comparison is noise, not signal |
| "Adjusted EPS" or "non-GAAP net income" columns derived from management add-backs | ADR-021 §4.1 — these are management narrative, not economic adjustments |
| Stage 0c suppressed via `--quiet` or auto-disabled in batch flows | Disclosure must be unconditional; the user's audit trail is more valuable than the 50 tokens |

---

## 4. Implementation status (this PR)

- ✅ Stage 0c panel rendered at top of every `invest dive` (cli/main.py:_render_dive_outcome)
- ✅ ICA-5 trigger condition declares methodology consistency in plain text
- ✅ ICA-5 `relevant_numbers.methodology` dict carries structured provenance (sources, add-backs included/excluded, ADR reference)
- ✅ Peters-Taylor degraded mode (oc_only) declares its alternative anchor (Eisfeldt-Papanikolaou 2013) and surfaces R&D-missing in the panel
- 📋 Pending: machine-readable methodology block in `DeepDiveRun.framework_results_json._composite.methodology` (so audit log captures provenance; CLI panel is human-only today)
- 📋 Pending: `--show-methodology-detail` CLI flag for full per-metric source breakdown (overkill for now; the panel + ICA-5 dict cover the main needs)

---

## 5. Triangulation principle (codified)

The four lenses, in priority order:

| Lens | Source | Purpose | Red flag |
|---|---|---|---|
| **GAAP** | SEC 10-K XBRL | Baseline regulatory reality | Persistent losses + positive OCF = conservative accounting (good) |
| **Non-GAAP (PT)** | SEC 10-K XBRL via Peters-Taylor capitalisation | Economic reinvestment-aware ROIC | Adjustment list growing every year would be danger — ours doesn't grow because the formula is fixed (R&D + 25% SG&A, period) |
| **FCF** | SEC 10-K cash flow statement | Economic reality check | FCF < net income over 3yr = accrual inflation |
| **ROIC** | Computed consistently across the universe | Capital-allocation truth | Declining ROIC despite growing revenue = moat erosion |

Decision rule: if two of these four lenses disagree materially, the dive surfaces the divergence (e.g. ICA-5 fires on the GAAP↔Non-GAAP gap) rather than picking a winner. The user makes the call.

---

## 6. References

- ADR-021 — Economic ROIC adjustment: Peters-Taylor, not management non-GAAP
- ADR-017 — Screener as warehouse query (task pattern)
- CLAUDE.md §"AI layer boundary" — the deterministic data path that this ADR depends on
- Peters & Taylor (2017) JFE — capitalisation methodology
- Eisfeldt & Papanikolaou (2013) JF — organisation-capital fallback when R&D is undisclosed
- Munger (Berkshire annual letters, various) — the four-quadrant triangulation principle this ADR codifies
