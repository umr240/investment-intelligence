# ADR-031 Amendment A2: a monthly LLM spend ceiling for every provider, enforced before each call

| Field | Detail |
|---|---|
| **Status** | **PROPOSED 2026-11-11, awaiting sign-off.** Nothing implemented. |
| **Amends** | ADR-031 §4.4 (the $100/month ceiling, written as guidance for the LLM-extraction option) and §8 ("Cost-ceiling enforcement ❌ NOT shipped") |
| **Related** | ADR-031-A3 (Bedrock provider: sets a Bedrock ceiling here before its first call); ADR-058 (the AWS-side stop) |
| **Eval Contract** | **UNMEASURED** (constitution VIII). Changes no prompt, guard or model; claims no quality effect. |
| **Provenance** | 2026-11-11. Separated from ADR-031-A3 because the ceiling stands whether or not a Bedrock provider is added. |

---

## 1. Why this is an amendment

ADR-031 §4.4 (ADR-031:405-412) says "$100/month hard ceiling enforced in
code. Exceed → abort + alert", as guidance for the extraction option. §8
records it as not shipped. Since then one call site gained a ceiling of its
own and two did not. This amendment puts one ceiling in front of every call
site and every provider.

## 2. Evidence (2026-11-11, `origin/main` at 2625ae2)

- **One choke point exists.** Every provider request is wrapped in
  `recorded_call` (`deepdive/llm_calls.py:91`): narrative
  (`deepdive/narrative.py:272`), chat (`deepdive/conversation.py:113`),
  external signals (`deepdive/external_signals.py:135`).
- **Spend is recorded per call:** `llm_calls.cost_usd` and `created_at`
  (`data/models/schema.py:853,855`). On the real DB: 279 rows, none with a
  NULL cost, $9.41 in total (OpenAI $0.23, Anthropic $9.18).
- **What is capped today.**
  - `/external-signals`: a $100 month-to-date ceiling over
    `skill_invocations.cost_usd`, by local-time month
    (`cli/skills/external_signals.py:35,62`; DEC-50).
  - `invest chat`: a per-session budget in the REPL (`cli/main.py:1038,1187`).
  - Narratives (CLI and UI) and `POST /dive/{ticker}/chat`
    (`api/app.py:364`): nothing.
- **Spend can go uncounted two ways.** A model with no price row records
  `cost_usd = None` (`config/llm_prices.py:62-73`); narrative does not refuse
  one (chat does, `conversation.py:396`; external signals does,
  `deepdive/external_signals.py:208,366`). And a failed row write is dropped by design
  ("Recording never fails a call", `deepdive/llm_calls.py:5-6,153-165`).

## 3. Options

| Option | Verdict |
|---|---|
| **(a) One check inside `recorded_call`** | **Chosen.** One place, covers every site and provider, reads a table that already exists. |
| (b) Provider-side limits in the Anthropic and OpenAI consoles | **Adopted as well, as the second line** for those providers: they count the real bill, which (a) cannot. Set in each provider console; whether each is a hard cap or an alert is not checked here. |
| (c) A copy of the skill's check at each call site | Rejected: three copies, and a new site can forget it. |
| (d) A budget proxy (e.g. LiteLLM) | Rejected on scope: a proxy process and a large dependency to replace a ~40-line check over an existing table. Adoption evidence not gathered. |

## 4. Decision

1. **Check before each request.** On entry, `recorded_call` sums this UTC
   calendar month's `cost_usd` from `llm_calls`, overall and for the call's
   provider. Every row counts, eval runs included, since they are real spend.
   If either has reached its ceiling it raises `SpendCeilingError` and sends
   nothing.
2. **Ceilings are settings.** `LLM_MONTHLY_CEILING_USD` (overall; default 100,
   ADR-031 §4.4's figure) and `LLM_PROVIDER_CEILINGS_USD` (per provider,
   e.g. `bedrock=1`; unset means only the overall ceiling).
3. **Nothing escapes the count.** The three rules below, with item 1's count,
   are one mechanism; each closes a way spend goes uncounted, so they ship
   together:
   - an unpriced model is refused before the request at every site,
     narrative included;
   - if the month's sum cannot be read, the call is refused;
   - if a call's row cannot be written, that process refuses further calls
     until restarted, with an error that says so. This reverses
     `llm_calls.py`'s "Recording never fails a call" for the next call, not
     for the one already made.
4. **Callers degrade, never crash a dive.** In the narrative fallback a
   provider over its own ceiling is skipped like an unconfigured one, with
   the reason in `fallback_reason`. A refused repair call keeps the first
   answer, as a failed repair does today (`narrative.py:170-171`). The
   overall ceiling ends the loop with the existing `NarrativeUnavailableError`.
   Chat and the UI return the error text. The skill's own $100 check stays as
   is: redundant, since it sums a subset of the same spend (local-time month
   there, UTC month here).
5. **Visible.** `invest llm stats` (`cli/main.py:4079`) gains month-to-date
   spend by provider against each ceiling. Zero tokens.
6. **Overshoot is bounded by the requests in flight** when a ceiling is
   reached: usually one, more if the UI's async chat and a scheduler process
   are both mid-call.

## 5. Inversion (mandatory)

- **It blocks a wanted dive.** The error names the setting to raise.
- **The sum is wrong.** It is computed from `config/llm_prices.py`, not the
  bill; stale prices under-count, and a timed-out request recorded as an
  error at $0 may still be billed (a guess). Check: once a month,
  `invest llm stats` is compared with each provider's invoice; option (b) is the
  backstop.
- **A long-running server goes quiet after a failed write.** Every call then
  fails with the restart message, in the UI as well as the CLI.
- **A call escapes `recorded_call`.** Check: a test walks each module in
  `ALLOWED` (`tests/test_llm_call_sites.py:15`) and fails on any provider SDK
  call (`messages.create`, `chat.completions.create`, …) that is not inside a
  `recorded_call` block. Per call, not per module.

## 6. Verification

Unit tests with no network: each ceiling, the UTC month boundary, an
unpriced narrative model, an unreadable sum, a failed write, the provider
skip and the refused repair. End to end against the real DB:
`invest llm stats` matches a hand-run `SELECT` over `llm_calls`.

## 7. Cost and dependencies

None. No new dependency, no AWS resource, no LLM call.

## 8. Consequences

- Easier: one number answers "what has this month cost".
- Harder: at the ceiling, narratives stop until the month turns.
- Forbidden: a provider SDK call outside `recorded_call`.
- Rollback: raise the setting; or revert the check, which leaves `llm_calls`
  untouched.
- ADR-031 §8's "Cost-ceiling enforcement" row is shipped once this lands, and
  ADR-031's status line names this amendment.
