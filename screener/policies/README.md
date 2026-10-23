# Exclusion policies

Every company that clears the data and quality gates is scored the same way.
An **exclusion policy** is an optional rule that leaves some companies out of
the screen, for example to follow an investment mandate. A policy never changes
a framework score, and every exclusion is recorded with its reason.

The active policy is set by `EXCLUSION_POLICY` in `.env`. The default is `none`,
which excludes nothing. An unknown name fails at first use and lists the
registered policies.

## Where a policy acts

| Stage | Method | Effect |
|---|---|---|
| Tier 3, before fundamentals are fetched | `classify(sector, industry)` | Excluded tickers are persisted as `archived`, with the reason |
| Tier 5, gate G1 | `gate(reader)` | An exclusion is a hard gate failure (`G1_policy`) |
| Warehouse tasks | `not_excluded()` | SQL predicate; excluded companies are not refreshed |
| Warehouse query | `eligible()` | SQL predicate; only confirmed-eligible companies are listed |
| Classification task | `classification_task()` | Optional warehouse task (`exclusion_classify`) that classifies new companies |

`screener/policies/base.py` defines the full `ExclusionPolicy` protocol, and
`none.py` is the smallest complete example.

## Writing and registering a policy

Ship the policy in its own package and register a zero-argument factory under
the `investment_intelligence.exclusion_policies` entry-point group:

```toml
# pyproject.toml of your package
[project.entry-points."investment_intelligence.exclusion_policies"]
mandate = "my_policies.mandate:MandatePolicy"
```

Install it into the same environment (for example `uv pip install -e ../my-policies`),
then set `EXCLUSION_POLICY=mandate`. A policy cannot replace a built-in name.

## Storing verdicts

A policy that keeps a status per company stores it in the `exclusion_verdicts`
table, one row per (company, policy), through `screener/policies/verdicts.py`:
`set_status()` to record a verdict (it works before the company row is
flushed), `status_of()` to read one, and `has_status()` / `lacks_status()` to
build the `eligible()` and `not_excluded()` predicates. A company with no row
has not been classified by that policy.

## Rules a policy must follow

- **Deterministic.** No network calls and no LLM calls (CLAUDE.md, coding rule 1).
- **Explain every exclusion.** `PolicyVerdict.reason` is shown to the user.
- **Fail closed in the gate.** Missing inputs are an exclusion with a reason, never a pass.
- **Never touch scores.** A policy filters companies; it does not change how they score.
