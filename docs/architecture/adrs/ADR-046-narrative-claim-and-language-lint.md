# ADR-046 — Claim-to-Evidence and Language Lint for Narratives

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | AI narrative layer |
| **Implements** | ADR-023 §1.5 (forbidden language), which was never built |
| **Extends** | ADR-045 (grounded generation) |
| **Resolves** | Qualitative overclaiming and prescriptive language, which the number guard cannot see |
| **Provenance** | Live narrative runs 2026-10-20; stored narratives |

---

## 1. Context

`narrative_guard.py` checks numbers, framework citations, risk grounding and
caveats. It does not check what the prose **claims**. Observed:

| Narrative | Claim | Evidence in the scorecard |
|---|---|---|
| CRWD (live) | "a durable platform moat" | F6 Platform Dominator 4.0/10, partial |
| CRWD (live) | "high-conviction innovation compounder" | Composite 5.58, watchlist |
| NVDA (live) | "warranting a sized, indefinite hold" | Prescriptive, with position sizing |
| NVDA (live) | "extreme winners require sized positions" | Position-sizing advice |
| 3 of 15 narratives | `compelling` ×2, `potentially` ×1 | Banned by ADR-023 §1.5 |

DEC-23 deliberately allows hold-*philosophy* language ("hold-forever
framing", "5-year reconsideration"). The lint has to tell that apart from a
hold *recommendation*.

## 2. Decision

### 2.1 A rules table, not a model

`deepdive/claim_rules.py` (new) holds deterministic rules. Each rule has an
ID, a pattern, a predicate over `citable_fields` (ADR-045), and a severity.

| Rule | Pattern (case-insensitive) | Permitted only if | Severity |
|---|---|---|---|
| L1 banned language | the ADR-023 §1.5 list | never | block |
| L2 prescriptive | `sized (hold\|position)`, `position siz`, `buy`/`sell`/`hold` used as a verdict or imperative, `initiate` | never | block |
| L3 sell-side tone | `high-conviction`, `conviction buy`, `undervalued`, `attractive valuation` | never | block |
| C1 moat strength | `durable\|wide\|widening\|strong` + `moat` | F6 ≥ 6.0 and feasible, or moat direction WIDENING | warn |
| C2 acceleration | `accelerat\w+` (growth, earnings) | F4 EPS acceleration ∈ {accelerating, strongly increasing} | warn |
| C3 extreme winner | `extreme winner` | BEW verdict strong or moderate | warn |
| C4 cheapness | `cheap`, `discount to`, `below intrinsic` | a valuation lens above the price | warn |

An allow-list carries DEC-23 phrasing (`hold-forever framing`,
`reconsideration window`) so L2 does not fire on it.

### 2.2 Wiring

- Rule hits become guard warnings carrying the rule ID.
- `block` hits go through ADR-045's single repair retry. If they still fail, the narrative persists as `guard_failed` (ADR-023-A1 row 5).

### 2.3 What this ADR does NOT decide

- An LLM judge for reasoning quality. That would be a third LLM call site and needs an amendment of the ADR-031 §4 call-site rule, so it is deferred to after ADR-047.

## 3. Inversion (mandatory)

- **Regex brittleness:** paraphrase slips through (false negatives), and quoting a banned phrase to negate it gets flagged (false positives). Mitigation: ADR-047 seeds known overclaims into the golden set and measures recall and precision per rule. A rule below 0.8 precision is demoted to `warn`.
- **Rule creep:** a list of 200 rules nobody maintains. Mitigation: a rule is added only with a real narrative example, kept in its test.

## 4. Alternatives considered

- **Prompt instructions only:** already present in ADR-023 §1.3; they failed on the live runs.
- **LLM-as-judge:** deferred (§2.3).

## 5. Consequences

- Closes the overclaiming gap partially and measurably.
- Small maintenance cost per rule.

## 6. References

- ADR-023 §1.5; DEC-23; `deepdive/narrative_guard.py`
