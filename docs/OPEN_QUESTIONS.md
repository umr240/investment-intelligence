# Open questions

Questions the code and the ADRs cannot answer. Work that depends on one stops
until the owner answers it; the answer then moves into an ADR, a DEC entry or
the code, and the row is deleted here.

| # | Question | Blocks | Raised (date, by) | Evidence (`file:line`) |
|---|---|---|---|---|
| 2 | Which companies does C1 (annual revenue present) exempt, and by what key? Of the 1,693 failing companies, 668 are blank-check shells (SIC 6770), 241 are banks, insurers and other financials (SIC 6000–6499), and about 140 are trusts or funds; only 5 have filings read by an older parser, so the backfill ADR-044 §2.5 expected to clear C1 re-reads only those 5. An SIC-based exemption (6770 at least) would replace the ticker list `C1_EXEMPT`. | C1 passing; the C1 threshold (§2.6 sets thresholds after the first backfill) | 2026-10-27, Claude | `data/contracts.py` `C1_EXEMPT`; query in PR for ADR-044 |
