# ADR-047 — Narrative Eval Harness: Golden Set, Deterministic Graders, Replay Gate

| Field | Detail |
|---|---|
| **Status** | **ACCEPTED 2026-10-28** (DEC-52), with the additions in §2.7. |
| **Phase** | AI narrative layer — quality measurement |
| **Extends** | ADR-035 (skill evaluation), ADR-023 §1.8 (test coverage) |
| **Measures** | ADR-023-A1, ADR-045, ADR-046, ADR-049 |
| **Resolves** | Narrative quality is never measured; model and prompt changes are unverifiable |
| **Provenance** | Audit 2026-10-21 |

---

## 1. Context

- **No measurement.** 13 stored narratives, 62% guard-failed. Two models used (Haiku 4.5 on 4, Sonnet 4.6 on 9), never compared. 2 of 2 live runs failed the guard.
- **Existing evals cover other things.** ADR-035 evaluates *skills*, and its only LLM dimension (triggering accuracy) is deferred. `tests/test_narrative_lattice.py` and `tests/test_narrative_guard.py` use canned inputs with no model call. They test the plumbing, not the output.
- **No regression signal.** Nothing in CI would notice if a prompt edit doubled the failure rate.

## 2. Decision

### 2.1 Golden set

- 30–50 frozen `ScorecardView` JSON files exported from the author DB into `tests/fixtures/narrative_golden/` (new).
- Public-derived fields only (SECURITY §2): no portfolio, no watchlist membership, no secrets.
- Strata: established compounder, pre-profitability, recent IPO with unfeasible frameworks, EXCLUDE path, data-poor RESEARCH-ONLY, non-USD filer, spinoff, extreme winner, split-affected (CRWD).
- Seeded failure cases for ADR-046 recall: outputs with known overclaims.
- Split into train and test sets. Prompt work iterates on train only; the test score is the headline number.
- Raw third-party values are withheld from the public files (owner, 2026-10-28): the Yahoo header figures (market cap, P/E, P/B, EV/EBITDA, beta) and F4's short interest. Each case records what was withheld and the hash of the frozen view it came from; the model is evaluated on the public view.
- Both splits live in this public repo (owner, 2026-10-28). Contamination is the cost: a future model may train on the test cases. Mitigations: every test-split file carries a canary string (the BIG-bench pattern), so a crawler that honours it skips the file and a model that reproduces it shows contamination; the test split is refreshed each quarter with dives dated after the candidate models' training cutoffs; the `Read` deny rule in `.claude/settings.json` keeps assistant sessions out of `test/`.

### 2.2 Graders — deterministic, no LLM

| Grader | Pass condition |
|---|---|
| G1 guard | zero guard warnings |
| G2 verdict | present, and equal to the mapped deterministic verdict (ADR-054) |
| G3 citations | every `field_id` resolves; no unrendered placeholder; citations per point ≥ floor |
| G4 claims | zero ADR-046 `block` hits; `warn` hits counted |
| G5 structure | required fields present (ADR-023-A1 row 2) |
| G6 cost | input, output and cache tokens × versioned price table (ADR-048) |
| G7 latency | p50 and p95 per model |

### 2.3 Two modes

- **Live (spends tokens, user-triggered):** `invest narrative eval run --provider <anthropic|openai> --model <id> [--split test|train|all]` (new; the provider is named because the narrative path is provider-specific, amended 2026-10-28 at S5). It prints the estimated cost and requires confirmation, the same discipline as `dangerous: true` skills (ADR-032 §2.4). Outputs are stored under `tests/fixtures/narrative_golden/outputs/<model>/<prompt_version>/`.
- **Replay (zero tokens, CI gate):** CI re-grades stored outputs. A grader change, schema change or guard change that breaks stored outputs fails the build. CI never calls an LLM: lazy-load principle, cost, and no secrets in CI.

### 2.4 Comparison report

Per model × prompt version: pass rates G1–G5, cost per narrative, p50/p95
latency, plus a quality-versus-cost Pareto plot.

Candidate set: `claude-sonnet-4-6` (configured today), `claude-sonnet-5`,
`claude-haiku-4-5`, and the configured OpenAI default.

Estimated cost per 40-case live run, from measured tokens (~12k in, ~3.8k
out) at Anthropic list prices (verify at implementation):

| Model | Per narrative | Per run |
|---|---|---|
| Sonnet 4.6 | ~$0.093 | ~$3.70 |
| Sonnet 5 | ~$0.062 | ~$2.50 |
| Haiku 4.5 | ~$0.031 | ~$1.25 |

### 2.5 Gate

Proposed after a baseline run, not before:

- G1 ≥ 90% on the test split.
- G2 = 100%.
- G4 `block` hits = 0.

The first run on today's code is the baseline. It is expected to fail.

### 2.6 What this ADR does NOT decide

- An LLM judge. A judge is a new call site, so it needs an amendment to ADR-031-A1 (and an entry in `tests/test_llm_call_sites.py`), and a judge must itself be validated against human labels first.

### 2.7 Additions at acceptance (owner, 2026-10-28)

1. **Versioned fixtures.** Each frozen view records the scorecard schema version, the composite formula version and its own SHA-256. Replay fails on a mismatch, so unifying the composite or changing when BEW runs (ARCHITECTURE_AUDIT.md) forces a re-export instead of comparing different inputs.
2. **Live runs from the CLI only.** No API route starts an eval. The run prints its cost from `config/llm_prices.py` and asks for confirmation; a model without a price row is refused (ADR-048).
3. **Eval calls are marked in `llm_calls`,** so `invest llm stats` and ADR-048's cost figures keep evaluation spend apart from real use.
4. **Composer deferrals are recorded per case:** the lattice models `deepdive/mental_model_composer.py` dropped for budget. That is the measurement ADR-055 names before RAG over the lattice can reopen.

## 3. Inversion (mandatory)

- **Overfitting 40 cases (Goodhart).** Mitigations: the train/test split, quarterly refresh of the set with real failures (ADR-050), and the test score as the headline.
- **Deterministic graders miss bad reasoning that is well-formed.** Acknowledged; this is the case for a validated judge later.
- **Frozen scorecards drift from the live schema.** Mitigation: a schema-version check fails the replay when the view shape changes.

## 4. Alternatives considered

- **LLM-as-judge first:** rejected (§2.6).
- **Hosted eval platforms:** new dependency, and scorecards leave the machine (SECURITY §2 egress). Exporting results later stays possible.
- **Eval libraries (searched 2026-10-28):** Inspect (UK AISI; proven, 40 required packages) is the one to depend on if an LLM judge arrives (§2.6). pydantic-evals (cases, evaluators, comparable reports) is the closest fit; its shape is borrowed, not the package, which brings pydantic-ai and OpenTelemetry for seven deterministic graders. promptfoo is a Node toolchain; deepeval requires a telemetry client (`posthog`); openai/evals is inactive.
- **Live LLM calls in CI:** rejected (§2.3).

## 5. Consequences

- Every narrative change gets a before/after number.
- Live runs cost single-digit dollars, within the ADR-031 §3 budget envelope.

## 6. References

- ADR-035, ADR-023 §1.8, `tests/test_narrative_guard.py`
