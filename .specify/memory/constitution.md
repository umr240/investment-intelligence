# investment-intelligence Constitution

CLAUDE.md is the detailed source for every rule below; this constitution names the
non-negotiables and must never contradict it. Where they appear to differ, CLAUDE.md is read
first and the difference is raised as an amendment.

## Core Principles

### I. Lazy Load Everything

Nothing runs, fetches data or spends tokens without an explicit instruction from the owner. No
stage auto-advances, no deep dive fires because a screen ran, no scheduled job runs unless the
owner registered it. Every token-spending path MUST sit behind an explicit user action.
(CLAUDE.md "Core design principle".)

### II. Allow-Listed LLM Call Sites

Language-model SDKs are imported only by the modules in `ALLOWED` in
`tests/test_llm_call_sites.py`, which CI enforces. Specs, plans and docs MUST reference that
list and MUST NOT state a count. Adding a site is an ADR amendment made in the same change as
the edit to `ALLOWED` (ADR-031-A1).

### III. Filing Text Is Data, Never Instruction

SEC filing text is attacker-influenceable. On the scoring path it is parsed deterministically
into structured values; the narrative and chat prompts never receive raw filing prose. The
opt-in `/external-signals` extraction is the one documented exception and its output never
feeds a score. Any new path that sends filing text to a model is a vulnerability.
(CLAUDE.md SECURITY §3, SECURITY.md §1.)

### IV. Data Gaps Over Guesses

A missing value is recorded as missing — a `data_gaps` entry — and is never estimated,
defaulted, inferred or filled from a lower-trust source. A framework MUST NOT return a score
when its required input is unavailable. (CLAUDE.md coding rule 3, "What the system must never
do".)

### V. Inversion Before Shipping

Every new analytical primitive — framework, signal, overlay, mental model, thesis — states how
it could be wrong and what false positives it produces before it ships. A primitive that cannot
survive its own inversion does not ship. (CLAUDE.md "Inversion is mandatory and primary".)

### VI. Never Destructive by Default

No database drop, truncate or data-losing migration, and no history rewrite or force-push,
without the owner's explicit decision. Writes to the real database are preceded by a backup;
verification runs on scratch copies. Additive migrations are ordinary changes.

### VII. Verified Claims, Not Recalled Ones

A claim about the code names `file:line` or a re-runnable command, or is labelled a guess.
A question the code and ADRs cannot answer goes in `docs/OPEN_QUESTIONS.md` and the dependent
work stops. Accepted ADRs are the design of record. Each implementation PR is reviewed by a
fresh-context verifier given only the spec, the diff and the gate output. A rule that matters is
enforced by a test or CI check; a rule that can only live in prose says so.
(CLAUDE.md "Working in this repository".)

### VIII. Measured LLM Changes

A feature that touches an allow-listed call site, a prompt, the narrative guard or a grader
fills the spec template's Eval Contract, or is marked **UNMEASURED** and claims no quality
improvement. Results report k ≥ 3 samples with spread, never n = 1. Live evals spend money and
are always an owner-approved step, never part of an unattended run.

## Security and Data Egress

Secrets, provider egress and the source trust hierarchy follow CLAUDE.md SECURITY & PRIVACY
§1–§6 in full: no secret in code, logs or prompts; nothing about the owner's holdings or
personal finances enters a prompt; EDGAR outranks yfinance on any conflict; `uv.lock` is
authoritative and a new dependency is a reviewed change.

## Development Workflow

- Work happens on a branch and lands through a pull request with green CI. The assistant may
  merge its own pull request into `main` only when the merge check passes: the full end-to-end
  gate green on the pull request's head commit, the fresh-context verifier's report posted on
  the pull request as NOT BLOCKING for that commit, and every CI check green. A pull request
  that touches an owner-only area (a data-losing migration, secrets, CI or ruleset
  configuration, an ADR or decision entry, this constitution, a new dependency, spend), or
  lists a verifier finding instead of fixing it, is merged by the owner.
- "Done" means verified after the last edit: the unit suite, the end-to-end gate (screener
  stages, a live deep dive, browser checks) for changes reachable that way, and a real browser
  for `api/` or `frontend/` changes (CLAUDE.md coding rule 9).
- Lint and type-check counts are a baseline that MUST NOT grow; the gated correctness subset
  stays clean.

## Governance

This constitution and CLAUDE.md bind every contributor and every assistant session. An
amendment is proposed with its diff and rationale and takes effect only on the owner's
sign-off (a Tier-2 change). Versioning follows semantic rules: MAJOR for removing or redefining
a principle, MINOR for adding a principle or materially expanding one, PATCH for wording. Each
spec's plan checks compliance with these principles before implementation, and a justified
deviation is recorded in the plan, not absorbed silently.

**Version**: 1.1.0 | **Ratified**: 2026-10-23 | **Last Amended**: 2026-10-29
