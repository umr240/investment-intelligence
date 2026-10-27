# ADR-048 — LLM Observability and Prompt Versioning (Local-First)

| Field | Detail |
|---|---|
| **Status** | **ACCEPTED 2026-10-27** (DEC-50). |
| **Phase** | AI narrative layer — operations |
| **Extends** | ADR-031 §3 (token budget), ADR-047 (evals need versioned prompts) |
| **Resolves** | LLM cost, latency, failures and prompt changes are invisible |
| **Provenance** | Audit 2026-10-21 |

---

## 1. Context

Today each narrative stores an `audit` object inside its JSON:

- provider, model, prompt tokens, completion tokens;
- `fallback_used`, status, guard warnings, timestamp.

Missing:

- **latency**, **cost**, **prompt version or hash**, request ID, cache tokens;
- a record per *attempt*.

Consequences seen in this audit:

- **Wasted requests went unnoticed.** With the current `.env` (provider `openai`, rejected key), every narrative first makes a failed OpenAI request. That shows up only as a boolean inside one JSON blob.
- **The UI's cost label is wrong.** It says "~$0.03–0.05". That matches Haiku 4.5 pricing, but the configured model is Sonnet 4.6, at about $0.09 per narrative.
- **No prompt history.** Nobody can say which prompt produced which stored narrative.

## 2. Decision

### 2.1 One table for every LLM call

`llm_calls` (new, additive migration) gets one row per attempt from every
call site allow-listed in `tests/test_llm_call_sites.py` (three today):

| Column group | Columns |
|---|---|
| Identity | `call_site` (narrative, chat, external_signals), `ticker`, `run_id`, `attempt` |
| Model | `provider`, `model`, `prompt_version`, `prompt_sha256` (system prompt + output schema) |
| Usage | input, output, cache-write and cache-read tokens |
| Outcome | `latency_ms`, `status`, `error_class`, `guard_status`, `warning_count` |
| Cost | `cost_usd`, computed from a dated price table in `config/`: rows copied from pydantic/genai-prices (MIT) with its commit and date, not a dependency (owner, 2026-10-27) |
| Trace | provider request ID, `created_at` |

Field names follow the OpenTelemetry GenAI semantic conventions, so an
exporter can be added later without renaming anything.

### 2.2 Prompt versioning

- `PROMPT_VERSION` is a constant in each call-site module (`deepdive/narrative.py`, `conversation.py`, `external_signals.py`), bumped by hand on any prompt or schema change.
- The SHA catches unbumped edits: a hash change without a version bump fails a unit test.

### 2.3 Surfaces

- `invest llm stats` (new): cost, latency and failure rate by model and prompt version.
- The UI cost label reads from the price table × measured tokens, not a hard-coded string.

### 2.4 Privacy

- Prompt text is **not** stored by default, only its hash.
- A debug flag can write full prompts to the gitignored `narrative_dumps/`.
- Secrets never enter the table (SECURITY §1).

### 2.5 What this ADR does NOT decide

- Hosted tracing (§4).

## 3. Inversion (mandatory)

- **Logs nobody reads.** Mitigation: ADR-047 reads this table for cost and latency, and the UI reads it for the cost label.
- **Price table drifts from real prices.** Mitigation: entries are dated, and a test asserts every configured model has a price entry.

## 4. Alternatives considered

- **Langfuse Cloud or another hosted tracer:** rejected for v1. It sends scorecard prompts to a third party, a new egress path under SECURITY §2. A self-hosted instance is new infrastructure for a single-user tool.
- **Logging to files only:** not queryable.

## 5. Consequences

- Cost per narrative, failure rate and per-prompt-version quality become queryable.
- One extra insert per LLM call.

## 6. References

- `deepdive/narrative.py` (`audit` dict), ADR-031 §3
