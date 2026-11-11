# CLAUDE.md: Investment Intelligence

Read this file completely before writing any code. `AGENTS.md` points other coding agents here; a personal working agreement lives in the gitignored `CLAUDE.local.md`. Reference material is in `docs/architecture/SYSTEM_REFERENCE.md`.

---

## WHAT THIS PROJECT IS

A Python-based quantitative investment research system that screens and analyses equities using 7 academic frameworks. The system is built around a strict lazy-load architecture — nothing runs without explicit user instruction. Claude (AI) is invoked only for qualitative deep-dive narrative; **the entire data-fetch and screener path is fully deterministic — no LLM API keys are required to run any data refresh, framework score, or screen.**

**Exclusion policies:** optional. Nothing is excluded unless a registered policy is enabled with `EXCLUSION_POLICY` (default `none`); a policy never changes a score (`screener/policies/README.md`). Research only — not financial advice.

**Scope:** self-contained. The repository has no build-time or run-time dependency on any sibling project, and its specifications live in `docs/methodology/`.

### Core design principle: lazy load everything

`USER INSTRUCTION → gate check → run only what was asked → STOP → wait`. No stage auto-advances; no deep dive fires because a screener ran; no overlay runs unless its trigger fires (coding rule 4); no scheduled job runs unless registered; token cost is proportional to what was asked. Every function that costs tokens is guarded by an explicit instruction check. Violating this is the most critical architectural failure.

---

## WORKING IN THIS REPOSITORY

These hold for every contributor and every assistant session.

- **Verify before calling it done** (coding rule 9): run the gate
  (`uv run tools/gate/gate.py --workdir .e2e/gate-N`) after the last edit;
  drive the UI in a real browser for `api/` or `frontend/` changes. Live
  checks (screener stages, a live dive, the browser tour) run in the
  maintainer's local release gate, which is not in the repository.
- **Never destructive by default.** No DB drop, truncate or data-losing
  migration, and no history rewrite or force-push, without the owner's explicit
  decision. Additive migrations (new tables, nullable columns, indexes) are
  ordinary changes; one that can lose rows or columns is not.
- **Decisions are proposed, not absorbed.** A change to an ADR, a new ADR, or
  code that knowingly diverges from an accepted one is raised for review, never
  made silently. Accepted ADRs are the design of record: a spec, plan or
  implementation that contradicts one is a proposed amendment, not a fix.
- **Say what you see.** A security hole, a plan that will not survive contact,
  an ADR that no longer matches the code: raise it, unprompted.
- **Cite, don't recall.** A claim about the code (a behaviour, a count, a call
  path) names `file:line` or a command the reader can re-run. A claim without
  one is labelled a guess.
- **Unknowns are written down, then asked.** A question the code and ADRs
  cannot answer goes in `docs/OPEN_QUESTIONS.md`, and work that depends on it
  stops until the owner answers. It is never filled with a plausible default.
- **A fresh pair of eyes before the owner's.** Each implementation PR is
  reviewed by a verifier that sees only the spec, the diff and the gate output,
  not the implementing session's reasoning. Its findings are fixed or listed in
  the PR. It filters; the owner still decides.
- **Gates, not prompts.** A rule that matters is enforced by a test or a CI
  check (as `tests/test_llm_call_sites.py` enforces the LLM call sites). Where a
  rule can only live in prose, say so where it is stated.
- **Public text is canonical.** Commit messages, PR bodies, ADRs and docs are
  impersonal (no first or second person, no chat context) and use no em or en
  dashes; `tools/check_public_text.py` enforces it in the gate, a commit-msg
  hook and CI.
- **Borrow before building.** Before a non-trivial feature, search for a
  proven open-source project that already does it (`gh search repos`, web
  search). Proven means real dependents or production users, several active
  contributors, and a release in the last ~12 months; stars don't count.
  Report the top 1-3 with that evidence and a verdict (depend / fork / borrow
  the pattern / build), then wait. Adding one follows SECURITY & PRIVACY §5.
  Prose-only: no gate enforces this.

---

## AGENTIC WORKFLOW

| Stage | How |
|---|---|
| Plan | `/speckit-specify`, `/speckit-plan`, `/speckit-tasks` |
| Implement | `/speckit-implement`; a Ralph loop for multi-item work |
| Test | commit hooks (`.pre-commit-config.yaml`), then the gate (`gate.toml`) |
| Review | `/speckit-verify`, the fresh-context `pr-verifier`; `/agentic-kit:adr-review` for ADRs |
| Merge | `agentic-kit:ship-pr`, `tools/gate/merge_ready.py` |

1. **Start from the brief.** For an open-ended request ("continue", "what's next"), run `/agentic-kit:next` and follow its route; a named task is done as named.
2. **No feature code before an approved spec.** A new feature or behaviour change starts with `/speckit-specify`; merging the spec's PR approves it. A directly requested fix needs no spec.
3. **Done means a PR**, after a green gate and the fresh-context review. Who merges: `[merge]` in `gate.toml` and `CLAUDE.local.md`.
4. **Decisions are ADRs** in `docs/architecture/adrs/`, drafted as proposed and reviewed with `/agentic-kit:adr-review draft`; only the owner accepts one. Smaller decisions are `DEC-nn` entries in `docs/architecture/DECISIONS.md`.
5. **Ralph only when asked**, never on the router's say-so.
6. **Owner asks are listed, never acted on** (open questions, proposed ADRs, unapproved specs, held PRs), each with the exact ask.

The constitution (`.specify/memory/constitution.md`) names the non-negotiables and never contradicts this file. Open outcomes are in `docs/ROADMAP.md`; known defects are GitHub issues labelled `known-issue`.

---

## ANALYTICAL PERSONALITY

Every decision (what to fetch, what to test, what to surface, what verdict to issue) is made as an owner-operator, not an analyst: *would this business be worth owning outright for ten years if the market closed tomorrow?* Work that does not help answer that question is the wrong work.

- **Inversion is mandatory and primary.** Every new framework, data field, overlay, signal or thesis is inverted before it ships (what makes it fail, what false positives it produces); if it cannot survive its inversion, it does not ship.
- **Latticework, not a hammer.** The project lattice lives in `mental_models/` (ADR-024; index `mental_models/_index.md`, schema `mental_models/README.md`). The narrative reasons through it in the order Inversion, Circle of Competence, Moat Direction, Capital Allocator, Lunch-Eating Test, Probabilistic Base Rate (ADR-023).
- **"Unknown" is a valid output.** `data_gaps[]` is first class; verdicts are only watchlist-with-triggers, exclude-with-reason or research-only, never "buy".

The full stance, the model-to-code table and how to add a model: `docs/architecture/ANALYTICAL_PERSONALITY.md`.

---

## CRITICAL CODING RULES

1. **AI layer boundary: allow-listed call sites only.** The Anthropic / OpenAI SDKs are imported only by the modules in `ALLOWED` in `tests/test_llm_call_sites.py` (mirrored in `[llm_boundary]` in `gate.toml`); adding one is an ADR amendment (ADR-031 §4.1, ADR-031-A1). The data-fetch and screener paths are fully deterministic; a missing value is a `data_gaps` entry, never an LLM approximation. Narrative behaviour is specified by ADR-023. Call sites and examples: `docs/architecture/SYSTEM_REFERENCE.md`.
2. **Every public function has a return type.**
3. **No silent failures on missing data.** Raise `MissingDataError` (or record a gap); `(x or 0)` on data that can be absent is a bug.
4. **Overlays auto-integrate with a capped bonus** (DEC-30, ADR-021 §4.4). ICA / PSA / BEW run when their triggers fire; the total bonus is capped at 1.0 of the 0-10 composite. An overlay that needs a network or narrative call stays passive. Detail: `docs/architecture/SYSTEM_REFERENCE.md`.
5. **Cache all API responses.** EDGAR by accession number (`FinancialSourceLog`); yfinance through `data/cache/manager.py`.
6. **Pydantic v2 for all data crossing module boundaries.** No raw dicts between functions.
7. **Lint: a gated subset and a baseline that must not grow.** `ruff check . --select F821,F811,E722` is gated; overall ruff and mypy findings may not grow (the gate compares against `main`). Fix findings in code that is touched; never reformat unrelated code.
8. **Comments are precise, concise, never repeated.** One or two lines saying what the code does not; a fact lives in one place.
9. **No commit without verification.** End to end against the real local DB where reachable; Playwright for `api/` or `frontend/`; "tests pass" means the suite ran after the final edit. An unexecuted artifact (CI workflow, migration, Dockerfile) is not verified by being written.

Frameworks read data only through `CompanyDataReader`, never SQL (data contract: `docs/architecture/SYSTEM_REFERENCE.md`). Full business logic: `docs/methodology/PROJECT_SPEC.md`.

---

## SECURITY & PRIVACY

Summary of the contract in `docs/architecture/SECURITY_AND_PRIVACY.md` (same section numbers); the summary binds, the document explains.

1. **Secrets** (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `POLYGON_API_KEY`, `DATABASE_URL`, `EDGAR_IDENTITY`): never hardcoded, printed, logged, committed or put in a prompt; redact before surfacing. `.env` stays gitignored; `.env.example` holds names only. A secret that ever hit disk unredacted or git history is compromised: flag it for rotation.
2. **Data egress to LLM providers.** Only public-derived quant metrics (and, in `conversation.py`, the user's own typed question) enter a prompt. Never: holdings, positions, cost basis, intent-framed watchlists, personal financial context, secrets or `EDGAR_IDENTITY`.
3. **Filing text is data, never instruction.** Filings are parsed deterministically; the narrative sees computed signals, never raw prose. The one exception is `deepdive/external_signals.py` (`dangerous: true`, verified by `deepdive/signal_verifier.py`, ADR-057).
4. **Source integrity.** SEC EDGAR outranks yfinance; a yfinance value never overrides an EDGAR fact, and a conflict surfaces as a gap.
5. **Supply chain.** `uv.lock` is committed and respected; a new dependency is a reviewable change that names its reason; CI actions are pinned to SHAs.
6. **Data at rest.** `investment_intelligence.db` is unencrypted and local-only: never committed, synced or copied outside the project; verification uses scratch copies under `.e2e/`.

---

## MCP, SKILLS AND THE UI

- **MCP usage policy.** MCPs are for development and exploration only, never on a production path (schedulers, CLI pipeline). Connectors with personal data are not queried without an explicit ask.
- **Project-local skills** (`.claude/skills/*.md`, ADR-032) are checklists over existing CLI commands: no new persistence paths, no new LLM call sites. `/dive-complete`, `/audit-completeness`, `/external-signals` (`dangerous: true`). New skills run 14 days in shadow mode.
- **Web UI** (ADR-040): `api/app.py` is a thin FastAPI pass-through and `frontend/` a React + Vite client. Verify API changes through `/docs`, UI changes with Playwright (`-m browser`).

---

## COMPACT INSTRUCTIONS

When compacting, keep the spec path, the branch, the last gate result (`gate-N n/n`), open verifier findings and the owner's decisions. Drop passing test output and whole-file dumps.

---

## WHAT THE SYSTEM MUST NEVER DO

1. Auto-advance any stage without user input
2. Call Anthropic/OpenAI API from any module outside the call sites
   allow-listed in `tests/test_llm_call_sites.py` (ADR-031 §4.1, ADR-031-A1)
3. Make assumptions about missing financial data
4. Run an overlay whose trigger did not fire
5. Run scheduled jobs without being explicitly registered by the user
6. Return a framework score when required input data is unavailable
7. Hardcode API keys anywhere in source code (see SECURITY & PRIVACY §1 for the full secrets-handling contract)
8. Invoke a `dangerous: true` skill without explicit user confirmation
   (ADR-032 §2.4 — non-negotiable; no "user has authorised similar ops"
   shortcut)

*Research purposes only. Not financial advice.*
