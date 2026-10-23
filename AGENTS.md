# AGENTS.md

For coding agents working in this repository (Codex, Cursor, Copilot, Claude
Code and others).

The rules live in [CLAUDE.md](CLAUDE.md). Read it in full before changing
anything; this file adds no rules of its own, so the two cannot drift.

Sections agents most often need:

- **Core design principle — lazy load everything**: nothing runs, fetches or
  spends tokens without an explicit instruction.
- **Critical coding rules**: LLM calls only at the sites allow-listed in
  `tests/test_llm_call_sites.py`; missing data is a `data_gaps` entry, never a
  guess.
- **Security & privacy**: secrets, what may reach a model provider, and why
  filing text is data, never instruction.
- **What the system must never do.**

Design decisions are in `docs/architecture/` (ADRs and `DECISIONS.md`);
methodology specs are in `docs/methodology/`. `CLAUDE.local.md` is a personal,
untracked file and binds no one else.
