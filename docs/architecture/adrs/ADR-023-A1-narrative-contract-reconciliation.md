# ADR-023-A1 — Reconcile the Narrative Contract With What Shipped

| Field | Detail |
|---|---|
| **Status** | **ACCEPTED 2026-10-21** — the recommended option on every row of §2. Not yet implemented; ADR-045 and ADR-046 carry the build. |
| **Phase** | AI narrative layer |
| **Amends** | ADR-023 (status "Accepted + implemented") |
| **Related** | ADR-045 (grounded generation), ADR-046 (claim and language lint), ADR-047 (eval harness), ADR-049 (cost), ADR-054 (verdict vocabulary) |
| **Provenance** | Code-vs-ADR audit and live narrative runs, 2026-10-19 → 2026-10-21 |

---

## 1. Context — ADR-023 and the code disagree

ADR-023 is marked "Accepted + implemented". Five of its binding sections do
not match `deepdive/narrative.py`, `deepdive/narrative_output.py` and
`deepdive/narrative_guard.py`:

| ADR-023 says | The code does |
|---|---|
| §1.2 Model `claude-opus-4-7`; does **not** fall back to another provider ("OpenAI NOT used") | OpenAI `gpt-4o-mini` primary, Anthropic fallback (`claude-sonnet-4-6` configured; `claude-haiku-4-5` used on 4 of 13 stored narratives). CLAUDE.md documents the code's behaviour, not the ADR's |
| §1.2 System prompt + personality block cached; hit-rate target ≥90% | No `cache_control` anywhere. Only the system prompt is static: 1,242 tokens of ~12,000 input (counted 2026-10-21) |
| §1.2 Extended thinking, 4K budget | Not enabled |
| §1.4 Eight mandatory sections, ending in a verdict | Different shape: `one_liner`, `bull[]`, `bear[]`, `risks[]`, `data_caveats[]`. No verdict field. 0 of 13 stored narratives carry a §1.4 verdict label |
| §1.5 Post-generation lint strips or rejects banned language | The guard has no language check. 3 of 15 narratives contain banned phrases (`compelling` ×2, `potentially` ×1) |
| §1.6 Failed lint → one retry with a stricter prompt → `NarrativeContractViolation` | Failed narratives are persisted with `status=guard_failed` and shown. 8 of 13 stored narratives (62%) and 2 of 2 live runs failed |

The drift matters because ADR-023 is what reviewers and contributors will
read as the contract. Today it describes a system that does not exist.

## 2. Decision

Decided 2026-10-21: the **Recommendation** column below, on every row.

| # | Topic | Option A — implement ADR-023 as written | Option B — amend ADR-023 to match the code | Recommendation (decided) |
|---|---|---|---|---|
| 1 | Provider | Anthropic only, Opus | Keep the provider order configurable; record the actual provider per call (ADR-048) | **B**, and pick the default model from ADR-047 results, not by assertion |
| 2 | Output structure | Eight prose sections | Keep `bull/bear/risks/data_caveats`, **add** the fields ADR-023 cares about most: `owner_operator_answer` (yes/no/not yet), `moat_direction` (WIDENING/FLAT/NARROWING/UNKNOWN), `triggers[]`, `verdict` | **B + additions** — the UI and stored data already use the shipped shape |
| 3 | Verdict | §1.4 labels | Same labels, as an enum field (ADR-045), mapped from the deterministic verdict (ADR-054) | Either; the field is required in both |
| 4 | Banned language | §1.5 lint | Same, implemented in ADR-046 | **A** (implement) |
| 5 | Failure handling | Retry once, then raise | Retry once, then persist with `guard_failed` **and** hide the narrative behind an explicit "show anyway" in the UI | **B** — a hidden failure is lost evidence for ADR-047 |
| 6 | Caching | ≥90% hit target | Cache the static prefix where it clears the model minimum; drop the 90% target (unattainable while 90% of input is per-ticker) | **B** (ADR-049) |
| 7 | Thinking | 4K budget | Decide per model from ADR-047 results; `budget_tokens` is deprecated or rejected on newer models | **B** |

### 2.1 What this amendment does NOT decide

- The grounding mechanism (ADR-045), the claim rules (ADR-046), or eval thresholds (ADR-047).
- Any change to the two permitted LLM call sites.

## 3. Inversion (mandatory)

*What would make this amendment wrong?* If the eight-section structure is what
actually produces owner-operator reasoning, then option B keeps a weaker format
for convenience. Test: ADR-047 can score both shapes on the same golden
scorecards. If the eight-section form wins on the claim-linter and guard
metrics, row 2 flips to A.

## 4. Alternatives considered

- **Leave ADR-023 as is.** Rejected: an ADR marked implemented that is not is worse than no ADR.
- **Rewrite ADR-023 in place.** Rejected: the project's convention is amendment files (ADR-030-A1, ADR-030-A2), which preserve the original reasoning.

## 5. Consequences

- ADR-023's status line now reads "Accepted; amended by ADR-023-A1" (done 2026-10-21).
- ADR-045 and ADR-046 become the implementation of the parts kept under option A.
- CLAUDE.md's narrative paragraph is updated to cite the amendment during release Phase 6 (the CLAUDE.md split).

## 6. References

- ADR-023 §1.2, §1.4, §1.5, §1.6; `docs/architecture/AI_QUALITY_PROPOSALS.md` for the measurements.
