# ADR-052 — Multi-Agent Narrative Panel (Experiment, Gated on Evals)

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off. Blocked until ADR-047 ships.** |
| **Phase** | AI narrative layer — experiment |
| **Depends on** | ADR-045 (field-ID citations), ADR-047 (eval harness) |
| **Constraint** | The LLM call-site allow-list in `tests/test_llm_call_sites.py` (ADR-031 §4, ADR-031-A1, ADR-032 §1.5) |
| **Provenance** | Proposal review 2026-10-21 |

---

## 1. Context

The proposal: archetype agents (bull, bear, and value-investor personas)
argue over the same frozen scorecard, and a judge writes the narrative,
citing fields.

The evidence is mixed. Du et al. (2023) report gains from multi-agent debate
on reasoning and factuality tasks. Later evaluations report that much of the
gain can be matched by single-model baselines given the same compute
(sampling several drafts and selecting one).

A panel multiplies the cost per narrative: N agents plus a judge.

## 2. Decision

### 2.1 Run it as an experiment, not a feature

- `strategy="panel"` is an alternative generation strategy **inside** `deepdive/narrative.py`. That keeps it within an existing call site. Placing agents in new modules would make new call sites and require amending ADR-031 §4.
- The judge emits the ADR-045 schema: field IDs only, and a verdict mapped from the deterministic engine.

### 2.2 Compare against three arms on the ADR-047 golden set

| Arm | Description |
|---|---|
| A | Single call (current) |
| B | Compute-matched: k independent samples + deterministic selection (best ADR-047 grade) |
| C | Panel |

### 2.3 Adoption rule

Adopt C only if it beats **B**, not just A, on:

- guard pass rate (G1);
- claim-linter `block` hits (G4);

at an acceptable cost per narrative. Otherwise, record the result and close this ADR as rejected.

### 2.4 What this ADR does NOT decide

- Persona prompts. Personas that produce sell-side tone fail ADR-046 anyway.

## 3. Inversion (mandatory)

- **Theatre:** more calls that look sophisticated and measure the same. Mitigation: arm B.
- **Cost multiplication:** N+1 calls per narrative. Mitigation: ADR-048 cost tracking and the adoption rule.
- **Persona drift into recommendations.** Mitigation: ADR-046 L2/L3 rules apply to every agent's output.

## 4. Alternatives considered

- **Ship the panel without evals:** rejected. Nothing could show it helps.

## 5. Consequences

- Either a measured improvement or a documented negative result. Both are useful.

## 6. References

- Du, Y., Li, S., Torralba, A., Tenenbaum, J. B., Mordatch, I. (2023). *Improving Factuality and Reasoning in Language Models through Multiagent Debate.* arXiv:2305.14325.
- ADR-031 §4, ADR-045, ADR-047
