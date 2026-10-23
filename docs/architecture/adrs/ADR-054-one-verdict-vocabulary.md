# ADR-054 — One Verdict Vocabulary; Retire "Initiate"

| Field | Detail |
|---|---|
| **Status** | **ACCEPTED 2026-10-21.** `monitor` maps to WATCHLIST WITH TRIGGERS. To be built in release Phase 6. |
| **Phase** | Scoring presentation |
| **Aligns** | CLAUDE.md ("never offers a buy verdict"), ADR-023 §1.4, ADR-023-A1 |
| **Unblocks** | ADR-045 (verdict field mapping) |
| **Provenance** | Audit 2026-10-21 |

---

## 1. Context

There are three verdict vocabularies:

| Where | Labels |
|---|---|
| Deterministic engine (`config/constants.py`, `deepdive/scorecard.py`) | `initiate` (composite ≥ 7.0), `watchlist` (≥ 5.0), `monitor` (≥ 3.0), `exclude`, plus `insufficient_breadth` when framework-weight coverage is below the floor |
| ADR-023 §1.4 (narrative) | `WATCHLIST WITH TRIGGERS`, `EXCLUDE WITH REASON`, `RESEARCH-ONLY` |
| CLAUDE.md bias rule | "only watchlist with triggers or exclude with reason" |

Stored dives: initiate 10, watchlist 102, monitor 73, exclude 30,
insufficient breadth 1.

The CLI colours `initiate` green, and the UI has an "Initiate" filter.
"Initiate" reads as "initiate a position": a buy signal under another name,
in a project that says it never gives one.

## 2. Decision

### 2.1 Canonical labels

Thresholds stay unchanged; only the labels change.

| Composite / condition | Engine label | Narrative label (ADR-023) |
|---|---|---|
| ≥ 7.0 | `priority_watchlist` | WATCHLIST WITH TRIGGERS |
| ≥ 5.0 | `watchlist` | WATCHLIST WITH TRIGGERS |
| ≥ 3.0 | `monitor` | WATCHLIST WITH TRIGGERS (decided 2026-10-21) |
| < 3.0 | `exclude` | EXCLUDE WITH REASON |
| coverage below floor | `research_only` (was `insufficient_breadth`) | RESEARCH-ONLY |

### 2.2 Stored rows are mapped at read time

Old values (`initiate`, `insufficient_breadth`) are mapped when read. No row
is rewritten, so this needs no destructive migration. New runs write the new
labels.

### 2.3 UI and CLI

- The "Initiate" filter and the green colouring are removed. Labels use neutral colours.
- The composite score stays visible: it is a ranking, not an action.

### 2.4 What this ADR does NOT decide

- Threshold recalibration. That needs ADR-053 evidence.

## 3. Inversion (mandatory)

*Does renaming hide that a ranked list still gets read as a buy list?*
Partly. A label is still less loaded than an action verb, and the
research-only banner stays. The full answer is ADR-053's out-of-sample
evidence about what a high composite means.

## 4. Alternatives considered

- **Keep "initiate":** contradicts CLAUDE.md and ADR-023.
- **Collapse to two labels:** loses the monitor band, which the checkpoint logic uses (`deepdive/checkpoint.py`).

## 5. Consequences

- One vocabulary from engine to narrative.
- ADR-045's verdict field becomes a pure mapping.
- Tests that assert verdict strings are updated.

## 6. References

- `config/constants.py` (`VERDICT_*`), `deepdive/checkpoint.py`, `frontend/src/components/OverviewPanel.tsx`
