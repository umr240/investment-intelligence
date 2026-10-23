---
slug: failure_pareto
name: Failure Pareto (80/20 Failure Modes)
school: reliability_engineering
citation_tier: "★★"
always_load: true
related_models:
  - failure_mode_analysis
  - opportunity_cost
  - margin_of_safety
  - circle_of_competence
code_consequences:
  - Tests prioritise the failure modes that matter most — not all failure modes get equal investment
  - Disqualification checks per framework focus on top-impact modes (CGS top-decile, M-Score > -2.22, Beneish indicators)
  - data_gaps[] surface missing data — the 20% of missing inputs causing 80% of analytical confusion
  - F4 stealth signals concentrate on fraud / accounting-quality red flags — high-impact failure modes
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Failure Pareto (80/20 Failure Modes)

> 80% of failures come from 20% of failure modes. Cover those thoroughly; accept residual risk on the tail.

## Summary

Pareto applied to failure-mode analysis. A small subset of failure modes accounts for most observed failures. Engineering effort focused on covering the high-impact modes produces dramatically better outcomes than uniform coverage of all enumerated modes.

## When to apply

- Test prioritisation — failure-mode tests for top-impact modes get cycle-time investment; tail modes get smoke tests
- Bug-fix triage — fix what fails for many users / high-impact analyses first
- Framework design — which 2-3 disqualification checks catch most bad theses?
- Investment risk — which 2-3 failure modes account for most realised losses (fraud, leverage cycles, secular decline)?

## Inversion form

The under-coverage failure: declaring "this is the 20% that matters" without empirical evidence and ignoring tail risks that are actually material. Defence: the Pareto split must be calibrated against observed failure data, not assumed.

## Antipatterns

- Uniform test coverage across all enumerated modes (resources mis-allocated)
- "We've thought of everything" without ranking by impact
- Skipping tail-risk analysis because "low probability" — Pareto says low probability is fine if low impact too; tail combines low probability with high impact
- Equating investment-relevant failure modes (fraud, secular decline, leverage cycle) with operational failure modes (integration bug, parser edge case)

## Examples in this codebase

- F1 / F4 disqualification checks focus on accounting-fraud red flags (Beneish M-Score, CGS top-decile asset growth) — high-impact modes empirically
- Test allocation in `tests/test_frameworks/` should weight failure-mode tests heavier than happy-path
- ADR-022 source-provenance discipline focuses on methodology mismatch — empirically the highest-impact analytical failure mode in cross-platform comparison
- HIMS dive: total_debt bug ($148M vs $1.12B) was the single highest-impact data error among the 5 fixes — addressing it first matched Pareto priority
