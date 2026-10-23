---
slug: boring_technology
name: Boring Technology
school: dan_mckinley
citation_tier: "★★"
always_load: true
related_models:
  - yagni
  - opportunity_cost
  - failure_pareto
  - margin_of_safety
code_consequences:
  - Stack choices documented in CLAUDE.md TECH STACK — uv, SQLAlchemy 2.0, Pydantic v2, pytest, ruff, mypy. All maximally boring.
  - FMP / Alpha Vantage / OpenAI explicitly NOT used — innovation budget preserved for differentiated investment-research problems
  - SQLite-first, PostgreSQL-later — boring database; deferred to prod-only
  - APScheduler chosen over Celery / Airflow for scheduler — lighter, boring, sufficient for the problem
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Boring Technology

> Dan McKinley: each new dependency carries an innovation budget. Spend it on differentiated problems. Boring tools for everything else.

## Summary

Most engineering choices should be the most boring option that solves the problem. Boring = well-documented, well-trodden, predictable failure modes, large community, won't be abandoned. The "innovation budget" is real but limited — spend it where the problem is genuinely novel, not on infrastructure choices.

## When to apply

- Every dependency addition — is this the most boring option that does the job?
- Every architectural choice — does the cutting-edge framework solve a problem we have, or one we're imagining?
- Every "let's try the new thing" — what's the cost if it stops being maintained?
- Every "this is too boring, let me modernise" — does the modernisation buy something the team needs?

## Inversion form

What does novelty-driven choice cost? Maintenance burden, fragile deployments, recruiting friction (newer tools = smaller talent pool), abandonment risk. The async-framework-of-the-week chosen for "performance" reasons usually doesn't deliver, often becomes unmaintained, and always raises the floor of what new contributors must learn.

## Antipatterns

- Adopting the latest framework before it has 3+ years of production track record
- Choosing technology to be impressive rather than to solve the problem
- Chasing performance benchmarks before measuring actual production load
- "We need event sourcing" before having a use case that demands it

## Examples in this codebase

- `uv` (boring, fast, simple) over poetry (also fine, slower)
- SQLAlchemy 2.0 + Alembic (industry-standard) over hand-rolled ORM
- Pydantic v2 (boring, well-supported) over custom validation classes
- pytest + respx (boring, well-known) over novel testing frameworks
- APScheduler (boring) over Celery+Redis+broker for the scheduler — sufficient for single-user scale
- Counter-example to watch for: when adding ML / NLP later (Phase 6+), boring-technology suggests starting with scikit-learn / FinBERT before reaching for the latest research paper
