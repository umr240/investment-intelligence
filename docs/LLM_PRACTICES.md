# LLM practices

How this project calls models. Read it before touching an LLM call site, a
prompt or a retrieval path. The gate enforces only the allow-listed call sites
(`[llm_boundary]` in `gate.toml`). Everything else here is prose-only, so the
reviewer checks it.

These are defaults. A recorded decision can override one rule: add a line under
that rule naming the decision and what it changes, for example "Overridden by
ADR-NNN: prompts live in two places, the server and the eval harness". Override
only the rule the decision covers. Add lines rather than deleting rules, so kit
updates merge cleanly. Overriding a Security rule, or a rule about real or
personal data, needs an ADR the owner has accepted, not only a log entry.

## Security

Mapped to the [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/).

| Risk | Rule |
|---|---|
| LLM01 Prompt injection | Untrusted text reaches a prompt only as delimited data. Delimiters reduce this risk and do not remove it, so the limits below still apply |
| LLM02 Sensitive information | Only cleared data enters a prompt. Logs carry ids and lengths, never prompt or response text |
| LLM05 Improper output handling | Model output is untrusted input. Validate it against a schema, and never pass it straight into SQL, a shell, HTML, a file path or a URL |
| LLM06 Excessive agency | Each tool gets the least access its job needs. A destructive or irreversible action needs a person's confirmation, whatever the model asks for |
| LLM10 Unbounded consumption | Every call sets `max_tokens`. Every job or user action has a limit on calls and a spend ceiling, and a loop has a maximum number of steps |

## Coding

- A schema-validated result is the only thing the rest of the code sees. A
  failed validation is an explicit error or fallback, never a guess.
- Prompts live in one place, carry a version and are reviewed like code.
- Model ids are configuration, not literals scattered through the code.
- Retries have a limit and back off. A retry repeats the spend, so it counts
  towards the ceiling.
- Agents hold their state in your own storage, so a run can stop and resume
  ([12-factor-agents](https://github.com/humanlayer/12-factor-agents), factors 5
  and 12).

## Testing and evals

- **Gate checks spend nothing by default.** They use recorded responses or a fake
  model. A check that calls a real model needs the owner's approval, because it
  costs money on every run. To run those on a schedule, see `require_live` in
  `gate.toml`.
- **Eval sets hold no real personal data.** Use synthetic or cleared examples,
  since eval files are committed and their text is sent to the model.
- **Databases other than SQLite get a throwaway server.** The gate's scratch copies
  only cover files, so for Postgres start a container for the run, and point the
  checks at it:

  ```toml
  [[variant]]
  name = "default"
  env = { DATABASE_URL = "postgresql://postgres@127.0.0.1:55432/postgres" }
  setup = "docker rm -f gate-pg; docker run -d --rm --name gate-pg -e POSTGRES_HOST_AUTH_METHOD=trust -p 127.0.0.1:55432:5432 postgres:17 || exit 1; for i in $(seq 60); do docker exec gate-pg pg_isready -q -h 127.0.0.1 && exit 0; sleep 1; done; docker rm -f gate-pg; exit 1"
  teardown = "docker stop gate-pg"
  ```

  Give each checkout its own container name and port if gates run at the same time.
  Never point a gate check at a database holding real data.

## Cost

- **Keep the stable part first.** Prompt caching matches an exact prefix in the
  order tools, system, messages, and a change invalidates everything after it. So
  put instructions and reference text first, and timestamps, ids and the user's
  message last ([prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
- **Measure it.** Record `cache_read_input_tokens` and
  `cache_creation_input_tokens` with each eval baseline. If both are 0, the prompt
  was not cached, usually because it is below the minimum length.
- **Use the cheapest model that passes the eval,** decided by measurement, not by
  assumption.
- **Send less.** Trim history and tool output before they reach the model.

## Retrieval

Take the first step that meets the need, and measure before moving to the next.

1. **Under about 200,000 tokens of knowledge: no retrieval.** Send it all in a
   cached prefix.
2. **Larger, with precise lookups:** keyword search (BM25), or an agent searching
   with `grep`.
3. **Larger, with meaning-based questions:** hybrid search, combining embeddings
   and BM25, then rerank. On Anthropic's benchmark, contextual embeddings with BM25
   and reranking cut retrieval failures by 67%. Your data will differ
   ([contextual retrieval](https://www.anthropic.com/news/contextual-retrieval)).
4. **Heavier systems,** such as graph-based retrieval, only when an eval shows the
   simpler step failing.

Add a retrieval eval before changing this: a set of questions with the passages
they should find. Text from retrieved documents is untrusted (LLM01), and each
user's index is kept apart (LLM08).
