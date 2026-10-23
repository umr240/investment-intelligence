---
slug: fail_fast
name: Fail Fast
school: erlang_armstrong
citation_tier: "★★★"
always_load: true
related_models:
  - illegal_states_unrepresentable
  - parse_dont_validate
  - circle_of_competence
  - failure_mode_analysis
code_consequences:
  - CLAUDE.md §"No silent failures on missing data" — already encoded; raise MissingDataError instead of (data or 0) defaults
  - data_gaps[] is a first-class output — failure to know is surfaced loudly, not papered over
  - InsufficientHistoryError raised when frameworks can't run, rather than fabricating thin-sample z-scores
  - Hooks / scheduler use loud failure: a single ticker failing surfaces in TaskFailure log; doesn't quietly drop the row
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Fail Fast

> *"Let it crash."* — Joe Armstrong, Erlang. Surface errors at the source, loudly. Defaults paper over data corruption that compounds across every downstream consumer.

## Summary

When a function receives input it can't handle, raise immediately rather than returning a placeholder, default, or silent zero. The earliest possible failure is the cheapest to debug; the latest is the most expensive (often surfaces as a wrong verdict the user acts on, not a stack trace).

## When to apply

- Every function boundary where input might be missing or invalid
- Every external-source fetch — distinguish "got value 0" from "got nothing"
- Every framework score — raise InsufficientHistoryError rather than returning a 0 score
- Every numerical derivation — a `None / None` should raise, not silently produce `nan`

## Inversion form

What does silent failure cost? Corruption that compounds. A single `(value or 0)` default at the parser layer becomes a fabricated 0 in a Financial row, becomes an artificially-low debt-to-equity, becomes a passing F5 score, becomes a high-conviction WATCHLIST verdict on a name with hidden leverage. Every silent-failure point is potential downstream verdict corruption. Loud failure breaks the build; silent failure breaks the analysis.

## Antipatterns

- `value = data.get('field', 0)` when missing-vs-zero matters analytically
- `try: ... except: pass` swallowing exceptions without logging
- Returning `None` from a function whose contract says it returns `float`
- "Best effort" data parsers that quietly skip bad rows without surfacing the count

## Examples in this codebase

- `frameworks/base.py:InsufficientHistoryError` — explicit fail-fast for thin-sample frameworks
- `data/reader.py:CompanyDataReader` returns explicit `None` for missing fields; never synthesised
- `data/edgar_companyfacts.py` distinguishes "concept missing" (fail) from "value is zero" (legitimate)
- The HIMS total_debt bug ($148M operating-lease vs $1.12B real debt) was a silent-failure: parser found an alias, returned a partial value, never raised. The fix added more aliases; the deeper lesson is the parser should have flagged the discrepancy
