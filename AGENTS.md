# AGENTS.md

For coding agents working in this repository (Codex, Cursor, Copilot, Claude
Code and others).

The rules live in [CLAUDE.md](CLAUDE.md). Read it in full before changing
anything; this file adds no rules of its own, so the two cannot drift.

Sections agents most often need:

- **Core design principle — lazy load everything**: nothing runs, fetches or
  spends tokens without an explicit instruction.
- **Working in this repository**: verify before done, never destructive,
  decisions are proposed, cite `file:line`, unknowns go in
  `docs/OPEN_QUESTIONS.md`.
- **Agentic workflow**: Spec Kit specs, the Ralph task file
  `docs/loop/TASKS.md`, the gate (`uv run tools/gate/gate.py --workdir
  .e2e/gate-N`, configured by `gate.toml`) and the fresh-context verifier.
- **Critical coding rules**: LLM calls only at the sites allow-listed in
  `tests/test_llm_call_sites.py`; missing data is a `data_gaps` entry, never a
  guess.
- **Security & privacy**: secrets, what may reach a model provider, and why
  filing text is data, never instruction.
- **What the system must never do.**

Decisions are ADRs in `docs/architecture/adrs/` (indexed in its README) and
`DEC-nn` entries in `docs/architecture/DECISIONS.md`; methodology specs are in
`docs/methodology/`. `CLAUDE.local.md` is a personal, untracked file and binds
no one else.
