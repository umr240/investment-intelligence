---
slug: parse_dont_validate
name: Parse, Don't Validate
school: alexis_king
citation_tier: "★★★"
always_load: true
related_models:
  - illegal_states_unrepresentable
  - fail_fast
  - boundaries_hexagonal
  - first_principles
code_consequences:
  - EDGAR text parser converts untrusted HTML/text → typed Pydantic models at the boundary; downstream code receives trusted typed values
  - data/api/yfinance_client.py wraps yfinance's loose dicts into typed snapshot models
  - Frameworks consume `CompanyDataReader` (typed) not raw SQL or raw JSON
  - companyfacts.json → EdgarFinancialRow → Financial row — three parsing transitions, each producing trusted typed output
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Parse, Don't Validate

> Alexis King: at the boundary, convert untrusted input into a trusted typed value. After that, *trust the type*. Don't repeatedly revalidate.

## Summary

Validation is "is this string a valid email?" — produces a yes/no but leaves the string still typed as `str`, requiring future code to remember to validate again. Parsing is "produce an `Email` value if possible, else fail" — produces a richer type that downstream code can trust by construction. The discipline is converting at boundaries; trusting after.

## When to apply

- Every external-data ingestion point — convert to typed model immediately
- Every API response — parse to a Pydantic model; don't pass `dict` around
- Every user input — convert to a constrained type at the CLI parser
- Every database read — `CompanyDataReader` returns typed objects; downstream code doesn't reparse

## Inversion form

What does "validate-then-pass-as-string" cost? Repeated revalidation, type-uncertainty everywhere, eventual `if isinstance(x, dict): if 'field' in x: if isinstance(x['field'], str): if x['field'].startswith('USD'): ...` chains. Every consumer reinvents the validation, often inconsistently. Bug surface multiplies.

## Antipatterns

- Passing raw API response dicts deep into business logic
- "I'll validate it where it's used" — guarantees inconsistent validation
- Type hints that say `dict` rather than a Pydantic model
- Validation functions that return `bool` rather than the parsed typed value

## Examples in this codebase

- `data/edgar_companyfacts.py:parse_companyfacts` returns typed `EdgarFinancialRow` objects, not dicts
- `data/edgar_text_parser.py` returns typed `CustomerSignals` / `ProxySignals` from regex'd 10-K text
- `data/api/yfinance_client.py` wraps yfinance's loose responses in typed Pydantic snapshot models
- `frameworks/base.py:FrameworkResult` is the typed return of every framework — no consumer needs to reparse
