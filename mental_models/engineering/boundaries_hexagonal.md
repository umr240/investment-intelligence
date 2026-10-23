---
slug: boundaries_hexagonal
name: Boundaries / Hexagonal Architecture
school: cockburn
citation_tier: "★★★"
always_load: true
related_models:
  - functional_core_imperative_shell
  - parse_dont_validate
  - single_source_of_truth
  - illegal_states_unrepresentable
code_consequences:
  - Frameworks NEVER touch SQL or import schema directly — always go through CompanyDataReader (CLAUDE.md §"Data contract")
  - data/edgar_companyfacts.py owns the SEC boundary; frameworks consume only the resulting typed Financial rows
  - data/api/yfinance_client.py wraps yfinance; consumers see typed snapshots, not raw yfinance objects
  - CLI in cli/main.py owns user-input boundary; orchestrator receives typed Pydantic args, not argv
token_cost_estimate: 220
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Boundaries / Hexagonal Architecture

> Alistair Cockburn: domain logic isolated from I/O. Pure functions inside, side effects at the edges. The "hexagon" is whatever shape the core has — what matters is the boundary.

## Summary

The most testable, maintainable architecture concentrates side effects (I/O, network, time, randomness, database) at well-defined edges and keeps the inside pure. Domain logic that doesn't know whether its inputs came from EDGAR, yfinance, or a test fixture is logic you can refactor freely without breaking integration with external sources.

## When to apply

- Every framework — does it talk to the database directly, or does it consume a typed reader?
- Every overlay — does it fetch its own data, or does the orchestrator pass it pre-fetched?
- Every CLI command — does it embed business logic, or does it parse args and delegate?
- Every test — does it need network / DB to test the logic, or is the logic pure given typed input?

## Inversion form

What does mixed I/O + logic cost? Untestable code, fragile to source changes, requires fixtures + DB + network for trivial logic tests. A change to EDGAR's response shape cascades into business logic that imported the response shape. The architectural smell: "I can't test this without a real database."

## Antipatterns

- Functions that take a SQL session and a business-logic concern in the same call
- Frameworks that import `data.api.yfinance_client` directly (couples logic to the wire format)
- Tests that mock at the wrong layer — mocking SQL when the framework should never have called SQL in the first place
- "Just this one HTTP call inside the framework, for performance"

## Examples in this codebase

- `frameworks/*.py` consume `CompanyDataReader` only — boundary enforced; SQL stays in `data/`
- `data/edgar_companyfacts.py:parse_companyfacts` is pure given input payload — testable without network
- `data/edgar_text_parser.py` regex over text — pure, no I/O inside
- `overlays/ica.py:run_ica` consumes `reader`; produces typed result; does no I/O
- Counter-example to watch for: `_persist_dive_results` in orchestrator owns DB writes — appropriately at the boundary, not inside framework logic
