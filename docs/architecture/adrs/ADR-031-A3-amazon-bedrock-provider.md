# ADR-031 Amendment A3: Amazon Bedrock as a third provider for the narrative

| Field | Detail |
|---|---|
| **Status** | **PROPOSED 2026-11-11, awaiting user sign-off.** Nothing implemented. |
| **Amends** | ADR-031 §4.1 (who the permitted call sites may call) |
| **Depends on** | ADR-031-A2 (in-code ceiling) and ADR-058 (AWS guardrails, deployed and drilled). Neither optional. |
| **Also touches** | CLAUDE.md SECURITY §1 (secrets in scope), §2 (egress), §5 (one optional dependency); ADR-048 (a provider value and a price row); `deep_dive_conversations.provider` (`data/models/schema.py:782`) is unchanged: chat does not use Bedrock (§4.1) |
| **Does not touch** | The allow-list (`tests/test_llm_call_sites.py:15`): no new module. `conversation.py` and `external_signals.py` stay off Bedrock. ADR-047: the eval's `--provider` stays `anthropic\|openai`. |
| **Eval Contract** | **UNMEASURED** (constitution VIII). Claims no quality result and runs no paid eval. |
| **Provenance** | Owner request 2026-11-11: add AWS, free-tier first, starting with Bedrock, at a monthly AWS spend as close to $0 as possible; recommendations accepted on review of need and cost. |

---

## 1. Why this is an amendment, and its conflict with DEC-42

ADR-031 §4.1 and A1 decide which modules may call an LLM, not which
providers they reach; OpenAI and Anthropic became the pair by
implementation (`config/settings.py:25-47`). A third provider changes where
prompts go and who bills, so it is an amendment here.

DEC-42 (`docs/architecture/DECISIONS.md:674`) chooses provider and model
from eval results. This provider is added for AWS experience, not because an
eval chose it, and its model differs from the Anthropic provider's. The owner
accepted that on 2026-11-11 with the work marked UNMEASURED and an exit test
(§6) instead of an eval.

## 2. Evidence (2026-11-11, `origin/main` at 2625ae2)

- **Dispatch falls through today.** `narrative.py:313-315` sends anything not
  OpenAI to Anthropic; `narrative.py:249-252` gives any preference other than
  the pinned `openai_only`/`anthropic_only` (`:244-247`) or `anthropic` the
  default OpenAI → Anthropic order, so a mistyped `NARRATIVE_PROVIDER` is
  silently ignored. `conversation.py:105,409-412` does the same. Fixed on its
  own first (§7), since it is a defect now.
- **The SDK ships the client.** `anthropic` 1.15.0 (`uv.lock`) exports
  `AnthropicBedrockMantle` (the Messages API on Bedrock). SigV4 signing
  imports `boto3`/`botocore` (`anthropic/lib/bedrock/_auth.py:10,45`); neither
  is installed.
- **Verified price.** pydantic/genai-prices `prices/providers/aws.yml`
  (commit e66fb87, `prices_checked: 2026-10-19`, from the AWS price list API,
  `AmazonBedrockFoundationModels`): `global.anthropic.claude-sonnet-5-5` at
  $2 / $10 per 1M input / output tokens, cache read $0.10;
  `global.anthropic.claude-sonnet-4-6` at $3 / $15.
- **Request shape.** The narrative sends structured output with no
  `thinking` or sampling parameters and `max_tokens=8192`
  (`narrative.py:494-510`), and treats a `refusal` stop as a provider failure
  (`narrative.py:522`). Chat forces a tool (`conversation.py:314`), which
  current models reject with a 400. That is why the narrative already moved
  to structured output (`narrative.py:503`, ADR-045).
- **Redaction.** `narrative.py:215` `_KEYISH` misses AWS key ids
  (`AKIA…`/`ASIA…`) and the account id in ARNs; the gate's scan matches
  `AKIA` only (`docs/release/e2e_gate.py:435`).

## 3. Options

| Option | Cost per narrative | Verdict |
|---|---|---|
| **(A) Mantle client, Claude Sonnet 5.5** | ~$0.05–0.07 | **Chosen.** Cheapest Claude that fits; no SDK pin; the client Anthropic recommends for new Bedrock code. |
| (B) Legacy InvokeModel client, Sonnet 4.6 (same model as Anthropic-direct) | ~$0.08–0.09 | Rejected: 1.5× the price, and `anthropic` 2.0 sends an API version Bedrock accepts only for Claude 4.7+ (§10), so it pins the SDK project-wide for an off-by-default provider. |
| (C) Bedrock Converse API through `boto3` | similar | Rejected: a second structured-output path to keep in step. |
| (D) Same as (A) with a Bedrock API key | same | Rejected: a long-lived secret in `.env`; AWS calls long-term keys "for exploration". |
| (E) Claude Platform on AWS | ~ Anthropic price | Rejected: an Anthropic API billed by AWS; exercises neither IAM nor Bedrock, which is the point. |
| (F) A multi-provider router (e.g. LiteLLM) | n/a | Rejected: replaces working SDK calls with a large dependency. Adoption evidence was not gathered; the rejection does not rest on it. |
| (G) No Bedrock; AWS experience elsewhere (ADR-056 hosting) | $0 | Not exclusive; stays open. |

The (A) range: per Anthropic's model-migration documentation, Sonnet 5.5's
tokenizer uses about 1×–1.35× the tokens of Sonnet 4.6's for the same text;
thinking tokens bill as output.

## 4. Decision

### 4.1 Narrative only

`NarrativeProvider.BEDROCK` joins the enum. `NARRATIVE_PROVIDER=bedrock`
means Bedrock, then the default OpenAI → Anthropic order; `bedrock_only`
means no fallback. The prompt is the same everywhere (SECURITY §2 unchanged),
and each provider is under its own A2 ceiling. Chat does not use Bedrock:
forced tool use would need a different request, not worth one for this. Chat
reads the same setting (`conversation.py:383-384`), so it treats `bedrock`
and `bedrock_only` as the default OpenAI → Anthropic order; `bedrock_only`
never leaves chat without a provider.

### 4.2 Model and request

`BEDROCK_NARRATIVE_MODEL` (Sonnet 5.5's Bedrock id, OPEN_QUESTIONS #7) in
`AWS_REGION`, through `AnthropicBedrockMantle`. `output_config.effort` is a
setting, `BEDROCK_NARRATIVE_EFFORT`, default `low`, because Sonnet 5.5 thinks
by default and thinking bills as output; `effort` is sent on the Bedrock
path only. `max_tokens` stays 8192. No SDK pin.

### 4.3 Credentials

`BEDROCK_AWS_PROFILE` names the profile; the client is built with it
explicitly, and the provider is unavailable when it is unset, never falling
back to boto3's default chain. That profile assumes `BedrockInvoker`
(ADR-058) from an `aws login` session, so nothing long-lived sits on disk and
the ADR-058 deny applies. `boto3` is an optional extra
(`uv sync --extra bedrock`), like `postgres` (`pyproject.toml:57`); it may
need its `crt` extra for `aws login` refresh (checked at implementation).
`boto3` is the AWS SDK for Python, maintained by AWS: latest tag 1.44.0,
last commit 2026-11-10, 100+ contributors (checked 2026-11-11 with `gh api`;
dependents not counted).

`_KEYISH` and the gate's scan learn `ASIA…` ids, session tokens and the
account id; ARNs in error text are redacted. SECURITY §1 lists them.

### 4.4 Price row

Copied from genai-prices `aws.yml` as ADR-048 §2.1 requires
(`config/llm_prices.py:3-7`), from the row whose match covers the configured
id: `global.` is $2 / $10, `regional.` is $2.20 / $11. Keyed by the full
configured id. A bare `claude-sonnet-5-5` is refused as a Bedrock id, so it
can never share a row with a later Anthropic-direct Sonnet 5.5.

### 4.5 Data

Model invocation logging stays off (it would copy prompts into CloudWatch or
S3). Whether Bedrock stores prompts or trains on them under the account's
terms is OPEN_QUESTIONS #13.

### 4.6 Gate

`tests/test_llm_call_sites.py` also fails on a `boto3`/`botocore` client for
`bedrock-runtime` or `bedrock-mantle` outside `ALLOWED`. A unit test fails if
the Bedrock client is built without the configured profile.

## 5. Cost

| Item | Cost |
|---|---|
| Per narrative | ~$0.05–0.07 (§3) |
| On the Free plan | $0 by AWS rule, if Claude is open there (OPEN_QUESTIONS #8) |
| Smoke test (§7) | ≤ $0.10, once |
| **Monthly cap** | **$1.00** in code (`LLM_PROVIDER_CEILINGS_USD=bedrock=1`) and in AWS (ADR-058): ~15 narratives |
| Eval | none (UNMEASURED) |

## 6. Exit test

Bedrock is removed (enum value, client, price row, extra) if either holds,
smoke-test rows excluded:

- **Unused:** `llm_calls` shows Bedrock narratives for fewer than 10 distinct
  dives within 60 days of merge.
- **Poor:** more than half of the first 10 Bedrock narratives are
  guard-failed, or more than 2 of them end on `max_tokens`.

## 7. Delivery

1. A standalone fix: exhaustive provider dispatch, unknown values rejected
   (no ADR; a defect today).
2. A2 merged; ADR-058 deployed by the owner and drilled (the CLI drill; the
   Mantle namespace is OPEN_QUESTIONS #12).
3. One PR: enum value, client, settings, price row, redaction, gate and
   profile tests; the second ADR-058 drill (§2.5) through this client, with
   the deny attached, returning `AccessDenied`; then one live narrative on
   Bedrock (≤ $0.10; owner approves the spend).

## 8. Inversion (mandatory)

- **A surprise bill.** Bounded by the Free plan while on it, by A2 within the
  requests in flight, and by ADR-058 within hours if its deny reaches the
  Mantle endpoint (OPEN_QUESTIONS #12; the second drill shows it). Not
  shipped on the Paid plan until OPEN_QUESTIONS #11 is answered.
- **Thinking eats the output budget.** A `max_tokens` stop is billed and
  falls back to OpenAI, so the narrative is paid twice. `effort=low` makes it
  rarer; §6 counts it.
- **Quality drops on a different model.** UNMEASURED: no claim is made, the
  narrative guard still runs, and guard-failed narratives are marked as
  today. §6 removes Bedrock if the guard fails most of its first 10.
- **The app runs as the owner.** §4.3 refuses without the dedicated profile,
  and a test checks it.
- **The gate passes while a call escapes.** Raw HTTPS with hand-built SigV4
  is not an import; review is the backstop (A1 §5).

## 9. Consequences

- A third narrative provider behind one setting, off by default, $1/month.
- One optional dependency (`boto3`).
- Chat ignores Bedrock settings and keeps the default order.
- Forbidden while this stands: Bedrock for chat or external signals; model
  invocation logging; building the Bedrock client from the default
  credential chain.
- Rollback: unset the provider; remove per §6.
- ADR-031's status line names this amendment once accepted.

## 10. Sources (checked 2026-11-11)

- pydantic/genai-prices `prices/providers/aws.yml` at e66fb87: https://github.com/pydantic/genai-prices
- Anthropic API version 2026-10-21 migration: https://platform.claude.com/docs/en/api/migration-2026-10-21.md
- Claude on Amazon Bedrock (legacy models): https://platform.claude.com/docs/en/build-with-claude/claude-on-amazon-bedrock-legacy
- AWS SDK login credentials provider (`aws login`): https://docs.aws.amazon.com/sdkref/latest/guide/feature-login-credentials.html
- Bedrock API keys: https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html
- AWS Free Tier FAQ: https://aws.amazon.com/free/free-tier-faqs/
