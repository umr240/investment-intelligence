# ADR-055 — Retrieval-Augmented Generation and Other Rejected LLM Techniques

| Field | Detail |
|---|---|
| **Status** | **ACCEPTED 2026-10-21** — each technique rejected until its reopen condition is met. |
| **Phase** | AI architecture boundaries |
| **Upholds** | CLAUDE.md SECURITY §3 (filing text is data), CLAUDE.md coding rule 1 (deterministic data path), ADR-024 (lattice composition) |
| **Provenance** | Proposal review 2026-10-21 |

---

## 1. Context

Several current LLM techniques were proposed for this project. None is tied
to a measured problem in the 2026-10-21 audit. Recording the rejection, and
what would reopen each one, prevents re-litigating them without new evidence.

## 2. Decision — rejected for now, with reopen conditions

| Technique | Why rejected | Reopen if |
|---|---|---|
| **RAG over filings** (10-K/10-Q/8-K text) | Breaks the SECURITY §3 trust boundary: filing text is attacker-influenceable and never enters a prompt. The deterministic-parse-first design is a security property | A design keeps raw text out of the narrative prompt, e.g. retrieval only *locates* passages for deterministic parsers |
| **RAG over the mental-model lattice** | 114 files, already a graph (`related_models`), selected deterministically by `deepdive/mental_model_composer.py` under an 8,000-token budget. No measured retrieval failure | The composer measurably defers relevant models because of budget, and ADR-047 shows quality loss |
| **LightRAG / GraphRAG** | An LLM-built knowledge graph is non-deterministic, adds LLM call sites and an embedding dependency, and fixes nothing measured | Same as above, plus a call-site amendment (ADR-031 §4) |
| **Vector database** | No similarity-search need. "Companies like X" is a numeric nearest-neighbour query over factor scores (SQL or numpy), not embeddings | A text-similarity use case appears that structured fields cannot serve |
| **LLM extraction to fill data gaps** | Violates coding rule 1. The largest measured gap (26% of companies without revenue) was fixed deterministically with concept chains | Never for the canonical data path. ADR-031's isolated `external_signals` channel already exists for supplementary values |
| **Fine-tuning or distillation** | No eval set exists to show it worked, and provider-hosted models suffice | ADR-047 shows a stable gap that prompting and model choice cannot close |
| **Autonomous trading or execution agents** | Out of scope. Research-only posture; liability with no upside | Never within this project |

## 3. Inversion (mandatory)

*What if a rejection is wrong?* The reopen column defines the evidence that
would flip it, so this record is a gate, not a ban.

## 4. Alternatives considered

- **Adopt the techniques to broaden the stack:** rejected. A technique without a measured problem adds call sites, dependencies and attack surface, and cannot show an improvement.

## 5. Consequences

- Future proposals in this space start from a reopen condition and a measurement.

## 6. References

- CLAUDE.md "Security & privacy" §3 and "Critical coding rules" §1; ADR-024; ADR-031 §4
