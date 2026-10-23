# ADR-049 — Narrative Cost Engineering

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | AI narrative layer — cost |
| **Amends** | ADR-023 §1.2 (caching target), through ADR-023-A1 row 6 |
| **Depends on** | ADR-047 (quality gate), ADR-048 (measured tokens) |
| **Provenance** | Token counts and live runs, 2026-10-20 → 2026-10-21 |

---

## 1. Context (measured)

| Fact | Value |
|---|---|
| Input tokens per narrative | ~12,000 (11,956 and 12,338 on two live runs) |
| Output tokens per narrative | ~3,300–4,000 |
| Static system prompt | 1,242 tokens (counted with `count_tokens`) |
| Per-ticker part (view + lattice block) | ~10,700 tokens; changes every call |
| Configured model | `claude-sonnet-4-6`: ~$0.093 per narrative |
| UI label | "~$0.03–0.05", which matches Haiku 4.5 (~$0.031), not the configured model |
| Failed attempt per call | `.env` lists OpenAI first with a rejected key |

List prices per million tokens (input / output; verify at implementation):

| Model | Price |
|---|---|
| Sonnet 4.6 | $3 / $15 |
| Sonnet 5 | $2 / $10 |
| Haiku 4.5 | $1 / $5 |

ADR-023 §1.2's caching target (≥90% hit rate) assumed most of the input was
static. Only about 10% is.

## 2. Decision — levers in order of measured value

1. **Remove the failed attempt.** At startup, a provider whose key is missing or rejected drops out of the provider order. Free, immediate.
2. **Choose the model with ADR-047.** Sonnet 5 costs ~33% less than Sonnet 4.6 per token; Haiku 4.5 costs ~67% less. Adopt the cheapest model that passes the ADR-047 gate.
3. **Cache the static prefix where it can cache.** The 1,242-token system prompt clears the 1,024-token minimum on Sonnet 4.6 and Sonnet 5. It silently will **not** cache on Haiku 4.5 (4,096-token minimum). The saving is at most ~10% of input cost. Larger savings need the always-loaded lattice models moved into a stable shared prefix, which is a measured follow-up, not an assumption.
4. **Batches only on explicit bulk requests.** The Message Batches API costs 50% of normal and is asynchronous. It is allowed only behind an explicit command over a named ticker list (`invest narrative batch --tickers …`, new), with a cost preview and confirmation. Never on a schedule the user did not register; this keeps the lazy-load principle.
5. **Honest UI estimate.** The cost label comes from ADR-048's price table × measured tokens.

Report cost per 1,000 narratives before and after each lever, from
`llm_calls` (ADR-048).

### 2.1 What this ADR does NOT decide

- Which model wins. That is ADR-047's output.

## 3. Inversion (mandatory)

- **A cheaper model degrades quality silently.** Mitigation: no model change without the ADR-047 gate.
- **The cache is invalidated silently**, for example by a timestamp in the prompt. Mitigation: alert when `cache_read_input_tokens` in `llm_calls` reads zero across repeated calls.
- **Batch pricing encourages bulk spend.** Mitigation: explicit command, preview, confirmation, and the ADR-031 §3 budget.

## 4. Alternatives considered

- **Cache "the 12k block":** not possible. Only ~1.2k is static.
- **Cut output length:** reduces cost, but risks dropping required sections; measure with ADR-047 first.

## 5. Consequences

- The largest saving comes from model choice and removing failed attempts, not from caching.

## 6. References

- ADR-023 §1.2, ADR-031 §3, `deepdive/narrative.py` (`_SYSTEM_PROMPT`, `_build_user_prompt`)
