# ADR-044 — Data Contracts Checked on Every Refresh

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | Data integrity |
| **Extends** | ADR-022 (provenance), ADR-033 (source hierarchy), ADR-030-A2 (share basis) |
| **Resolves** | Silent data failures that corrupted scores for a large part of the universe without any alarm |
| **Provenance** | E2E testing and read-only DB measurement, 2026-10-19 → 2026-10-21 (author DB snapshot of 2026-10-19) |

---

## 1. Context — the failures were silent, not rare

Every defect below was found by hand during one e2e session. None raised an
error, a data gap, or a test failure.

| Defect | Measured scale | Effect |
|---|---|---|
| Revenue tagged only as `RevenueFromContractWithCustomerIncludingAssessedTax` was in no concept chain | 1,694 of 6,518 companies with annual rows have **no** annual revenue | CRWD composite 3.44 → 5.58 once read |
| Coverage gate ignored quarters | 812 companies have annual rows and zero quarterly rows | F1–F5 reported "unfeasible" on their dives |
| Tier 4 read only the `Revenues` frame | 68% of SEC frames filers had no revenue (33% after the fix) | Dropped as "revenue < $10M" |
| Split factor unknown | 65 of 6,518 latest annual rows carry `share_split_factor` | Per-share values off by the split ratio (CRWD ×4) |
| Mixed share bases inside a quarterly series | CRWD FY2026 Q2 = 999.6M shares between 248M and 251M neighbours | Distorts per-share quarterly signals |
| Exclusion-policy status vs the current classifier | 125 stored statuses disagree; 2,565 never classified | Screener membership depends on stale state |
| Warehouse completeness | 5,444 of 10,148 companies below 0.5 completeness; framework score on 4,418 | Most of the universe is not comparable |
| Screener runs | 7 of 7 recorded runs have `universe_count = 0` | No evidence the network screener completes |

Existing checks: `tests/test_data_layer_invariants.py` has four ticker-scoped
tests under `-m requires_data`. They skip in CI and measure nothing
universe-wide.

## 2. Decision

### 2.1 Named contracts with thresholds

A module `data/contracts.py` (new) defines each contract as an ID, a SQL
metric, a threshold and a severity (`block` or `warn`). Initial set, with
today's value:

| ID | Metric | Today | Proposed threshold | Severity |
|---|---|---|---|---|
| C1 | Annual rows with revenue, among companies with any annual row | 74.0% | ≥ 95%, excluding a documented exemption list (banks, insurers, IFRS filers) | block |
| C2 | Companies with annual rows but no quarterly rows | 812 | 0 among dived companies; reported for the rest | block (dived) |
| C3 | Latest annual row has a known split factor | 1.0% | 100% of dived companies | warn |
| C4 | Adjacent quarterly share counts differ by > 2× with no recorded split | not measured | 0 | warn |
| C5 | Stored exclusion status agrees with the classifier, or carries an explicit override record | 125 disagreements | 0 unexplained | block |
| C6 | Distribution of `data_completeness` | 54% < 0.5 | reported | warn |
| C7 | A completed screener run has `universe_count > 0` | 0 of 7 | every run | block |
| C8 | Tier-4 revenue-resolvable share of frames filers | 67% | reported | warn |

Thresholds are constants reviewed through this ADR, not tuned in code.

### 2.2 Where they run

- **Per ticker, after `refresh_ticker`:** C1–C4 for that ticker. DB-only, so no network and no tokens. A violation becomes a `data_gaps` entry, consistent with CLAUDE.md rule 3.
- **Universe-wide, on demand:** `invest data check` (new) runs all contracts and prints a table.
- **After screener stages:** C5, C7, C8.
- Results are persisted to a new table `data_contract_runs` (additive migration).

### 2.3 No new dependency in v1

`pandera` and Great Expectations were considered. Eight SQL metrics do not
justify a dependency (SECURITY §5). Revisit past ~30 contracts.

### 2.4 Backfill is a separate, explicit action

Contracts will fail on today's data until ~1,700 companies are refreshed with
the fixed parsers. That refresh is network-heavy. It runs only on an explicit
command (`invest data backfill --contract C1`, new), never automatically.

### 2.5 What this ADR does NOT decide

- Revenue concepts for banks, insurers and IFRS filers (the C1 exemption list starts empty and grows by review).
- Final thresholds; they are set after the first backfill.

## 3. Inversion (mandatory)

*How do contracts fail?*

- **Goodhart:** thresholds lowered until they pass. Mitigation: thresholds live in this ADR, and any change is an amendment.
- **Alarm fatigue:** too many `warn` results get ignored. Mitigation: few contracts, each with a named defect it would have caught (§1).
- **Contracts that test the code, not the data.** Mitigation: every contract is a query over persisted rows.

## 4. Alternatives considered

- **pandera or Great Expectations:** rejected for v1 (§2.3).
- **dbt tests:** wrong tool for an ORM-owned SQLite schema.
- **Status quo (hand discovery):** this ADR exists because of it.

## 5. Consequences

- Silent failures become visible numbers.
- Per-ticker refresh gains a few cheap queries.
- The first `invest data check` will fail several contracts. That is the point.

## 6. References

- `tests/test_data_layer_invariants.py`, `data/share_basis.py`, `screener/tier4_frames.py`
- `docs/architecture/AI_QUALITY_PROPOSALS.md` (measurements and audit)
