# Open questions

Questions the code and the ADRs cannot answer. Work that depends on one stops
until the owner answers it; the answer then moves into an ADR, a DEC entry or
the code, and the row is deleted here.

| # | Question | Blocks | Raised (date, by) | Evidence (`file:line`) |
|---|---|---|---|---|
| 1 | Where does the narrative eval **test** split live: `tests/fixtures/narrative_golden/test/` in this repo, or the private repo, so it cannot enter a future model's training data? | ADR-047 golden set; the `Read` deny rule in `.claude/settings.json` assumes `test/` | 2026-10-23, Claude | ADR-047 §2.1 places the set in `tests/fixtures/narrative_golden/` but does not say where the splits live |
