# AI Quality and Data Integrity — Proposed ADRs

**Audited:** 2026-10-21 · **Data:** author DB snapshot of 2026-10-19 · **Status:** ADR-023-A1, ADR-054 and ADR-055 accepted 2026-10-21; ADR-057 accepted 2026-10-24; the rest PROPOSED

This file is the entry point for review. It records what the audit measured,
which proposals it supports, and the order to take them in. Each decision
lives in its ADR; this file holds no decisions.

---

## 1. What the audit measured

### 1.1 Data layer

| Finding | Value |
|---|---|
| Companies with annual rows but no annual revenue | 1,694 of 6,518 (26%) |
| Companies with annual rows but no quarterly rows | 812 |
| Latest annual rows with a known split factor | 65 of 6,518 |
| SEC frames filers without revenue at Tier 4 | 68% before the fix, 33% after |
| Stored exclusion statuses that disagree with the current classifier | 125 (plus 2,565 never classified) |
| Companies below 0.5 data completeness | 5,444 of 10,148 |
| Recorded screener runs with a non-empty universe | 0 of 7 |
| Companies with price history | 88 |
| Financial rows with `filed_date` | 198,886 of 198,937 |

### 1.2 Narrative layer

| Finding | Value |
|---|---|
| Stored narratives that failed the guard | 8 of 13 (62%) |
| Live narratives that failed the guard (2026-10-20) | 2 of 2 |
| Dominant guard warning | claim value cited to the wrong field (7 of 9) |
| Narratives with an ADR-023 §1.4 verdict | 0 of 15 |
| Narratives with ADR-023 §1.5 banned phrases | 3 of 15 |
| Prescriptive language observed | "warranting a sized, indefinite hold" (NVDA, live) |
| Overclaim observed | "durable platform moat" with F6 = 4.0 (CRWD, live) |
| Tokens per narrative | ~12,000 in / ~3,300–4,000 out |
| Static (cacheable) part of the input | 1,242 tokens (system prompt) |
| Cost per narrative on the configured model (Sonnet 4.6) | ~$0.093; the UI says $0.03–0.05 (Haiku pricing) |
| Latency | narrative 68–81 s; chat reply 21–24 s |

### 1.3 Contract drift

ADR-023 is marked "Accepted + implemented". Its model choice, caching,
thinking, eight-section output, language lint and retry-then-reject rules
do not match the code. That is the subject of ADR-023-A1.

### 1.4 Already in place (not proposed again)

- Structured output on both providers: OpenAI JSON schema; Anthropic forced tool call.
- Token counts and guard status in each narrative's `audit` object.
- A deterministic skill-eval harness (ADR-035).
- A number-provenance guard (`deepdive/narrative_guard.py`).
- A deterministic, token-budgeted mental-model selector (`deepdive/mental_model_composer.py`).

## 2. Corrections to the source proposal list

| The list said | The audit found |
|---|---|
| Cache "the ~12k token static block" | Only 1,242 tokens are static. Caching saves at most ~10% of input, and nothing on Haiku 4.5 (4,096-token minimum) |
| "Your v3.0 doc cites Harvey-Liu-Zhu" | The citation is in `docs/methodology/SCREENER_WORKFLOW.md` |
| A backtest is the next quant step | Prices exist for 88 companies and the universe has no delisted filers. Data acquisition comes first |
| Langfuse for tracing | Sends prompts to a third party (SECURITY §2). A local table first |
| A debate-agent panel | Separate agent modules would be a third LLM call site; kept inside `narrative.py` and gated on evals |
| "Model cites, code renders" is new work | It completes ADR-023 §1.6, which was never built |
| A green "Initiate" button | Confirmed: the engine verdict `initiate` (composite ≥ 7.0) on 10 stored dives |

## 3. The ADRs

| ADR | Title | Depends on |
|---|---|---|
| ADR-023-A1 | Reconcile the narrative contract with what shipped — **accepted** | — |
| ADR-044 | Data contracts checked on every refresh | — |
| ADR-045 | Grounded generation: the model cites, code renders | ADR-054 |
| ADR-046 | Claim-to-evidence and language lint | ADR-045 |
| ADR-047 | Narrative eval harness | — (baseline); ADR-045/046 graders |
| ADR-048 | LLM observability and prompt versioning | — |
| ADR-049 | Narrative cost engineering | ADR-047, ADR-048 |
| ADR-050 | Narrative feedback capture | ADR-047 |
| ADR-051 | Read-only MCP server | — |
| ADR-052 | Multi-agent narrative panel (experiment) | ADR-045, ADR-047 |
| ADR-053 | Point-in-time backtest with multiple-testing control | price-data decision |
| ADR-054 | One verdict vocabulary; retire "initiate" — **accepted**, built in release Phase 6 | — |
| ADR-055 | RAG and other rejected LLM techniques — **accepted** | — |
| ADR-056 | Hosted read-only demo | public release, ADR-054 |
| ADR-057 | External signals: verify before storing (added 2026-10-24) | — |

## 4. Suggested order

Measure before changing, so every change has a before and an after.

On 2026-10-24 the user set the order: **ADR-057** (external-signals
verification, accepted that day), ADR-048, **ADR-044**, the ADR-047 baseline,
then ADR-045+046. ADR-044 goes before the baseline because a 52/53-week parser
bug found that day had dropped balance-sheet values and mislabelled fiscal
years (34 of 67 dived tickers had a year without total assets), so a baseline
on unchecked data would measure the data, not the narrative.

1. **ADR-044:** data contracts, then the backfill. Wrong data makes every later number wrong.
2. **ADR-048:** the `llm_calls` table, so cost and latency are recorded from the first eval run.
3. **ADR-047 (baseline):** run the golden set on today's narrative code. Expected to fail; that is the "before".
4. **ADR-023-A1 and ADR-054:** settle the contract and the verdict labels.
5. **ADR-045, then ADR-046:** grounded generation and the lint.
6. **ADR-047 (re-run):** the "after".
7. **ADR-049:** choose the model and cut cost, gated on step 6.
8. **ADR-050, ADR-051:** feedback loop and MCP surface.
9. **ADR-052:** only if step 6 leaves a gap worth an experiment.
10. **ADR-053:** after the price-data decision.
11. **ADR-056:** after the public release.

ADR-055 can be accepted at any time.

## 5. Decisions only the user can make

- ~~ADR-023-A1: options A or B per row.~~ Decided 2026-10-21: the recommended option on every row.
- ADR-044: the C1 exemption list and final thresholds after backfill.
- ADR-053: the source for delisted-company prices.
- ~~ADR-054: how `monitor` maps to the narrative verdict.~~ Decided 2026-10-21: WATCHLIST WITH TRIGGERS.
- ADR-056: static site or read-only API.
- ADR-051: registering the MCP server in an MCP client (Tier 2).
