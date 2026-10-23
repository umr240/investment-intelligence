# ADR-031 Amendment A1 — `deepdive/conversation.py` as a permitted LLM call site, and an enforced allow-list

| Field | Detail |
|---|---|
| **Status** | **Accepted** 2026-10-23 by the user. Amends ADR-031 (Accepted). |
| **Amends** | ADR-031 §4.1 — the permitted LLM call sites |
| **Also touches** | ADR-032 §1.5 (skills restate the rule), ADR-033 §4 item 7 and ADR-040 (context item 3), both of which assert there is no third site. Those ADRs stay unedited as historical record; this amendment governs. |
| **Provenance** | Release follow-up, 2026-10-23. Reconciling CLAUDE.md against the code found a third module importing provider SDKs, and found that the only automated check for the rule could not fail. |

---

## 1. Why this is an amendment

ADR-031 §4.1 set the call-site rule and DEC-36 (2026-05-15) restated it as
"two permitted call sites". Five days earlier, DEC-22 (2026-05-10) had shipped
`deepdive/conversation.py` — `invest chat` — which calls OpenAI and Anthropic.
The rule and the code diverged from then on. ADR-040 later said the API
"never calls Anthropic/OpenAI directly … not a third site", while
`api/app.py:330` (`POST /dive/{ticker}/chat`) routes to `conversation.py`.

The rule decides what may reach a provider, so a divergence from it is an
amendment to ADR-031, not a new ADR.

## 2. Evidence

- Provider imports in non-test code (2026-10-23):
  `deepdive/narrative.py:194,260-261`, `deepdive/external_signals.py:139,286`,
  `deepdive/conversation.py:229,282-283`. No others.
- **The local gate's boundary check was vacuous.** The maintainer's local
  release gate ran `git grep -E '^\s*(import|from) (anthropic|openai)\b'`. On macOS, git's
  ERE has no `\s` or `\b`; the pattern matched nothing and the check passed
  every run. POSIX classes (`[[:space:]]`) find all three modules.
- No CI check enforced the rule. It lived in prose in CLAUDE.md, CONTRIBUTING.md,
  SECURITY.md and the PR template, each stating a count.

## 3. Decision

1. **`deepdive/conversation.py` is a permitted LLM call site**, alongside
   `deepdive/narrative.py` and `deepdive/external_signals.py`.
2. **The allow-list is code.** `ALLOWED` in `tests/test_llm_call_sites.py` is
   the single source of truth. Documents point to it and never state a number,
   so a count cannot go stale again.
3. **Enforcement is a CI test.** It parses every non-test `.py` in the working
   tree and fails on any `import`/`from` of `anthropic` or `openai` (submodules
   included), or `importlib.import_module` / `__import__` with those literal
   names, outside `ALLOWED`. It also fails if an `ALLOWED` entry is missing or
   no longer imports a provider, so a stale entry cannot widen the list. It
   needs no database, so it runs in CI.
4. **Adding a site** means amending this ADR (or a successor) and editing
   `ALLOWED` in the same pull request.
5. The maintainer's local release gate (not in the repository) keeps a second,
   independent check (POSIX `git grep`), and
   now fails when an allow-listed site is *not* found, so a blind scan reads
   red instead of green.

## 4. What keeps `conversation.py` inside the boundary

Verified against the code on 2026-10-23:

- Grounded in the frozen `ScorecardView` of one `DeepDiveRun`
  (`conversation.py:18-19`); a re-dive starts a new conversation.
- Every reply carries `numeric_claims` whose `field_path` must resolve into the
  view (`validate_chat_turn`, `conversation.py:123`). Mismatches become
  `guard_warnings` on the persisted turn; validation is non-blocking
  (`conversation.py:360`).
- Every turn is appended to `deep_dive_conversations` (`data/models/schema.py:763`).
- The prompt holds the scorecard JSON, the last `HISTORY_WINDOW_TURNS` turns and
  the user's new message (`_build_user_message`, `conversation.py:186`). No raw
  filing text.
- Runs only when the user types a question: `invest chat` (`cli/main.py:987`) or
  the UI "Ask about this dive" box.

What is new relative to the other two sites: **the user's own typed text is
sent to the provider as written.** CLAUDE.md SECURITY §2 and SECURITY.md §3 now
say so.

## 5. Inversion (mandatory)

*What would make this amendment wrong?*

- **The test passes while a call escapes.** Static analysis misses dynamic
  imports with computed names, a vendored copy of an SDK, or raw HTTP to a
  provider endpoint. The test catches the forms used in this codebase; review
  remains the backstop for the rest.
- **The allow-list becomes a rubber stamp.** Editing one line of a test is
  easier than writing an ADR. The test's failure message names the ADR
  requirement, and the PR template checks it; neither prevents a careless edit.
- **Free text egress grows.** Chat is the first site that forwards user prose.
  If a later change attaches holdings or personal context to that prose, the
  SECURITY §2 deny-list is violated by the caller, not the call site, and this
  test will not see it.

## 6. Out of scope (named, not fixed)

- `POST /dive/{ticker}/chat` (`api/app.py:330`) has no session budget; the $2
  default with warn/halt exists only in the `invest chat` REPL
  (`cli/main.py:999`, DEC-22).
- Whether `external_signals.py` sends raw 8-K text to the provider, against
  SECURITY §3, is under review separately.

## 7. Consequences

- CLAUDE.md, CONTRIBUTING.md, SECURITY.md, the PR template, `cli/skills/__init__.py`,
  two skill files and the `conversation.py` docstring now reference the
  allow-list instead of a count.
- ADR-031, ADR-032, ADR-033 and ADR-040 keep their original wording; ADR-031's
  status line names this amendment.
