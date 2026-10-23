# ADR-045 — Grounded Narrative Generation: the Model Cites, Code Renders

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | AI narrative layer |
| **Extends** | ADR-023 §1.6 (anti-hallucination contract), ADR-023-A1 |
| **Depends on** | ADR-054 (verdict vocabulary) for the verdict mapping |
| **Resolves** | Mis-citation, the dominant cause of guard failures |
| **Provenance** | Stored narratives and live runs, 2026-10-19 → 2026-10-21 |

---

## 1. Context

ADR-023 §1.6 aims to make hallucination "systemically impossible, not just
culturally discouraged". The current design only detects it:

- `NumericClaim.value` is a string the model writes. `field_path` points into the view **by list position**, e.g. `frameworks.4.key_signals.2.1`. The model has to count list indices.
- Numbers in `headline` and `detail` prose are free text, checked against a whitelist after the fact.

Measured result:

| Sample | Guard failed | Warning kinds |
|---|---|---|
| 13 stored narratives | 8 (62%) | 7 claim-vs-view mismatches, 2 unknown numbers |
| 2 live runs (2026-10-20) | 2 | CRWD: FCF margin +29.8% cited to the ROIC path (−11.6%); Rule of 40 (48.94) cited to the Fahlenbrach flag; NRR "above 120%" (not in the scorecard). NVDA: two "52-week"/"90-day" false positives |

The numbers the model wrote were mostly right. It pointed at the wrong
field. Index-based paths make that easy.

Also: `_call_anthropic` forces `tool_choice: {"type": "tool"}`. Newer models
(Claude Opus 5.5, Claude Fable 5.1) reject forced tool choice with a 400, so
the current call shape blocks the model comparison in ADR-047.

## 2. Decision

### 2.1 Stable citable field IDs

`ScorecardView` exports a `citable_fields` map: a stable ID →
`(value, unit, label)`. Examples: `F5.roic`, `F5.fcf_margin`,
`F6.rule_of_40`, `price.pct_from_52w_high`, `insider.open_market_buyers_90d`.
IDs are names, never list positions. The map is built deterministically from
the view, with a cap of about 80 entries per company. Unfeasible frameworks
contribute no IDs.

### 2.2 The model never writes a number

- `NumericClaim` becomes `{field_id}`, an enum generated per request from `citable_fields`. The `value` field is removed.
- Prose cites values with placeholders, e.g. `{F5.roic}`. Code renders each placeholder from the view, with units, before persisting.
- A literal number in prose stays a guard error, as today. The difference is that the model now has a legal way to say every number.
- Window labels such as "52-week" and "90-day" become field IDs, so they stop producing false positives.

### 2.3 Verdict and owner-operator fields

Per ADR-023-A1 row 2:

- `verdict`: enum `WATCHLIST_WITH_TRIGGERS | EXCLUDE_WITH_REASON | RESEARCH_ONLY`, plus `verdict_reason`.
- It must equal the mapping of the deterministic verdict (ADR-054). The model explains the verdict; it does not choose it.
- `triggers[]`: each trigger names a `field_id` and a condition.
- `owner_operator_answer` and `moat_direction`: enums.

### 2.4 Transport

- **Anthropic:** a tool with `strict: true` and `tool_choice: auto`, plus an instruction naming the tool, or `output_config.format`. Both work on models that reject forced tool choice.
- **OpenAI:** `json_schema` with `strict`.
- Both stay inside `deepdive/narrative.py`. No new call site.

### 2.5 One bounded repair

If the guard still fails, call once more with the warnings appended. The
retry belongs to the same user request, is recorded in the audit (ADR-048),
and is capped at one.

### 2.6 What this ADR does NOT decide

- Qualitative claim checks (ADR-046).
- The pass-rate target (ADR-047).

## 3. Inversion (mandatory)

- **Enum too large:** schema tokens grow with the field list. Mitigation: the ~80-ID cap, with only feasible frameworks included.
- **The model avoids numbers to stay safe.** Mitigation: ADR-047 tracks citations per point and sets a floor.
- **Rendering failure leaks raw `{F5.roic}` text.** Mitigation: an unrendered placeholder is a guard error, and the narrative is not shown as clean.
- **Verdict field duplicates the engine verdict.** That is intended: the narrative must agree with the deterministic verdict, and a mismatch is a guard error.

## 4. Alternatives considered

- **Keep free text plus the guard (status quo):** 62% failure rate.
- **Auto-correct values after generation:** hides errors instead of preventing them.
- **More prompt instructions:** ADR-023 §1.3 already requires citation, and it is not enough.

## 5. Consequences

- Mis-citation becomes unrepresentable.
- The `narrative_json` schema version is bumped. Old narratives stay readable, and the UI renders both versions.
- Model migration becomes possible without the forced-tool-choice 400.

## 6. References

- `deepdive/narrative_output.py` (`NumericClaim`), `deepdive/narrative_guard.py`, `deepdive/scorecard_view.py`
- ADR-023 §1.4, §1.6
