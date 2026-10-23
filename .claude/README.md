# `.claude/`

Claude Code configuration for this repository.

| Path | What |
|---|---|
| `skills/` | Project-local skills: checklists over existing CLI commands (ADR-032; frontmatter contract in `skills/README.md`) |
| `session-sweep.sh` | Session hooks: `start` (git orientation), `stop` (diff summary + ruff), `full` (ruff + mypy + pytest) |

Architecture lives in `docs/architecture/`: `DECISIONS.md` is the decision
log (entries are superseded by new entries, never edited in place) and
`adrs/` holds the ADRs.

Nothing here may contain secrets or personal data; see CLAUDE.md, Security & Privacy.
