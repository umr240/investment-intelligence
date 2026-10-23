# ADR-050 — Narrative Feedback Capture

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | AI narrative layer — quality loop |
| **Feeds** | ADR-047 (golden set refresh) |
| **Provenance** | Audit 2026-10-21 |

---

## 1. Context

There is no way to mark a narrative or chat reply as wrong. Failures are seen
only when the user happens to read the guard box. The ADR-047 golden set
needs real failure cases, and today they exist only in this conversation's
notes.

## 2. Decision

- **UI:** a thumbs up/down on each narrative and chat reply, with a reason code: mis-cited number, overclaim, prescriptive language, missing verdict, factual error, other (with a free-text note).
- **Storage:** table `narrative_feedback` (new, additive migration). It records the run, model, `prompt_version` (ADR-048), the reason code and the note. Local only.
- **Export:** `invest narrative feedback export` (new) turns flagged cases into golden-set candidates: the frozen scorecard, the output and the reason. Each candidate is reviewed by the user before it is added to the set.
- **No automatic retuning.** Feedback never changes prompts or models by itself.

### 2.1 What this ADR does NOT decide

- Multi-user feedback. The tool is single-user (ADR-040 §0).

## 3. Inversion (mandatory)

- **Tiny volume from one user.** Accepted. The value is turning each noticed failure into a permanent test case, not statistics.
- **Feedback bias** towards dramatic failures. Mitigation: the golden set keeps its fixed strata (ADR-047 §2.1); feedback adds to them, it does not replace them.

## 4. Alternatives considered

- **Manual notes:** they are lost, as this audit shows.

## 5. Consequences

- The eval set grows from real failures.
- One small table and two UI controls.

## 6. References

- ADR-047, ADR-048
