# Open questions

Questions the code and the ADRs cannot answer. Work that depends on one stops
until the owner answers it; the answer then moves into an ADR, a DEC entry or
the code, and the row is deleted here.

| # | Question | Blocks | Raised (date, by) | Evidence (`file:line`) |
|---|---|---|---|---|
| 1 | Where does the narrative eval **test** split live: `tests/fixtures/narrative_golden/test/` in this repo, or the private repo, so it cannot enter a future model's training data? | ADR-047 golden set; the `Read` deny rule in `.claude/settings.json` assumes `test/` | 2026-10-23, Claude | ADR-047 §2.1 places the set in `tests/fixtures/narrative_golden/` but does not say where the splits live |
| 2 | Which companies does C1 (annual revenue present) exempt, and by what key? Of the 1,693 failing companies, 668 are blank-check shells (SIC 6770), 241 are banks, insurers and other financials (SIC 6000–6499), and about 140 are trusts or funds; only 5 have filings read by an older parser, so the backfill ADR-044 §2.5 expected to clear C1 re-reads only those 5. An SIC-based exemption (6770 at least) would replace the ticker list `C1_EXEMPT`. | C1 passing; the C1 threshold (§2.6 sets thresholds after the first backfill) | 2026-10-27, Claude | `data/contracts.py` `C1_EXEMPT`; query in PR for ADR-044 |
