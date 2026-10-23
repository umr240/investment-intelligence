# ADR-035 — Skill Evaluation Protocol

> Status: **Accepted**
> Date: 2026-05-16
> Supersedes: nothing (extends ADR-032 §10 + ADR-034)
> Related: ADR-032 (project-local skills), ADR-034 (versioning + lineage)
> Trigger: User 2026-05-16, citing Anthropic's "Don't Build Agents, Build Skills Instead" talk — completing the Evaluation pillar after Versioning shipped via ADR-034.

---

## 1. Decision

Every skill in `.claude/skills/` is evaluated across **four dimensions** drawn directly from Anthropic's "Exploring how Skills evolve" slide:

| Dimension | What it tests | Source of truth |
|---|---|---|
| **Triggering accuracy** | Does Claude invoke the right skill for a seeded user prompt? | LLM eval against a corpus (deferred — §3) |
| **Output quality** | Does the skill's output match the declared schema / postconditions? | `postconditions:` (mandatory) + `output_schema:` (optional today) |
| **Script execution** | Does the underlying implementation import + CLI surface resolve? | Python `importlib` + `invest <sub> --help` |
| **SKILL.md structure** | Frontmatter satisfies ADR-032 §2.1 + lineage invariants from ADR-034 §3 | `load_skill_frontmatter` + `validate_lineage` |

`cli/skills/evals.py:run_skill_evals(name)` returns a `SkillEvalReport` with one `EvalResult` per dimension. The CLI surface is `invest skill eval [name]`. CI runs `tests/test_skills/test_evals.py` which fails the build on any mandatory-dimension FAIL.

Anthropic's framing (Evaluation / Versioning / Composability):

| Pillar | ADR | Status |
|---|---|---|
| Versioning | ADR-034 | ✅ Shipped 2026-05-16 |
| Evaluation | ADR-035 (this) | ✅ Shipped 2026-05-16 (3 of 4 dimensions live) |
| Composability | ADR-036 (deferred) | 📋 Reserved hooks in ADR-034 §5 |

---

## 2. The four dimensions in detail

### 2.1 FRONTMATTER_STRUCTURE (deterministic, mandatory)

Aggregates two existing checks:

- **ADR-032 §2.1** — mandatory fields (`name`, `description`, `do_not_invoke_when` with ≥3 negative examples, `dangerous`, `shadow_mode_until`, `permitted_anthropic_calls`, `version`) — enforced by `load_skill_frontmatter()`.
- **ADR-034 §3** — version-lineage invariants (frontmatter version matches changelog head, no duplicate versions, date monotonicity) — enforced by `validate_lineage()`.

PASS when both checks succeed. FAIL when either raises or reports an error finding.

### 2.2 OUTPUT_QUALITY (deterministic, permissive today)

Two sub-checks:

1. **Postconditions declared** — `postconditions:` array is present + non-empty. **Mandatory** per ADR-032 §2.1.
2. **Output schema** — optional `output_schema:` field validates the actual runtime output shape against a Pydantic-or-JSONSchema spec.

Today: every skill has postconditions (FAIL if missing), but no skill declares `output_schema:`. The check returns SKIP with detail `"output_schema absent (ADR-035 §2.2 — optional today)"` until a future amendment makes the schema mandatory.

**Future tightening:** when `output_schema:` becomes mandatory, this dimension validates the most-recent `skill_invocations.render_output` row against the schema. Skills lacking a schema will FAIL.

### 2.3 SCRIPT_EXECUTION (deterministic, mandatory)

Two sub-checks:

1. **Implementation importable** — `frontmatter['implementation']` resolves to a real Python module that imports without raising.
2. **CLI surfaces resolve** — every `invest <subcommand>` mentioned in the skill body still produces a successful `--help`. This is identical to `tests/test_skills/test_signature_compatibility.py` (ADR-032 §10 #9, Vector 3 mitigation); duplicated here so a single `invest skill eval <name>` call surfaces it without pytest.

PASS when both hold. FAIL when impl import errors OR any body-referenced subcommand no longer exists.

### 2.4 TRIGGERING_ACCURACY (deferred)

Per Anthropic's slide ("8/10 cases correctly triggered"), this measures whether Claude picks the right skill given a user prompt. Implementation requires:

- A seeded corpus per skill — `should_trigger` prompts + `should_not_trigger` prompts
- A test harness that calls Claude with the corpus prompts and observes which skill the model selects
- Aggregate accuracy reporting (target ≥80% per Anthropic's example)

**Status:** the runner is not built. The check always returns SKIP with detail `"no triggering corpus declared (ADR-035 §3 — deferred)"` OR `"corpus exists … but runner not implemented"` if a corpus is present.

Corpus path convention: `.claude/skills/_evals/<skill>_triggering.yaml`. Schema (when implemented):

```yaml
should_trigger:
  - "audit completeness for SHOP"
  - "what's missing for HIMS"
  - "data gaps on INTA"
should_not_trigger:
  - "dive SHOP"                 # → should pick dive-complete
  - "what's SHOP's NRR?"        # → score-card answer, no skill needed
  - "screen for small caps"     # → unrelated workflow
```

See §3 for the runner roadmap.

---

## 3. Triggering-accuracy runner — roadmap (deferred)

The triggering-accuracy eval requires an LLM call site that this project's CLAUDE.md forbids outside `deepdive/narrative.py` and `deepdive/external_signals.py`. Two options for resolving this:

### Option A — Out-of-band runner

Build a standalone script `eval_skill_triggering.py` that:
1. Reads every skill's frontmatter + corpus
2. For each prompt in the corpus, calls Anthropic with a system prompt containing the inventory of skill descriptions
3. Parses Claude's response for skill invocation intent
4. Compares to the corpus's expected skill (or "none")
5. Reports accuracy per skill

This script lives OUTSIDE the deterministic data path (it's an eval tool, not production code). A dedicated permitted-call-site addition would be needed — likely `evals/triggering.py` per a future ADR.

### Option B — Use the Claude Code agent harness directly

The Claude Code session itself IS the LLM evaluator. A maintainer can:
1. Open a fresh Claude Code session with the corpus loaded
2. Ask each `should_trigger` prompt
3. Observe whether Claude invokes the expected skill via `Skill(...)` tool

Manually-driven, but no new call site required. The skill_invocations table already records which skill fired — making manual eval mechanically trivial.

**Recommendation:** start with Option B (manual eval on a monthly cadence) until Option A justifies the call-site addition.

### Corpus authoring guidance (when shipped)

Per Anthropic's example (8/10 = 80% target):

- **20 prompts per skill minimum**: 10 should-trigger + 10 should-not-trigger
- **Include adversarial cases**: prompts that mention the skill's keywords but shouldn't actually invoke it (e.g., "explain how audit-completeness works" should not run the skill — it's a question, not an invocation)
- **Source from real session transcripts**: every false-positive or false-negative trigger observed in production is added to the corpus

The corpus is versioned in `.claude/skills/_evals/`. Bumping a skill's prompt or `description:` triggers a re-eval against the corpus.

---

## 4. CI gate

`tests/test_skills/test_evals.py` runs on every PR. It enforces:

| Test | Asserts |
|---|---|
| `test_all_skills_pass_mandatory_evals` | Every skill PASSes FRONTMATTER_STRUCTURE + SCRIPT_EXECUTION. SKIP is acceptable for OUTPUT_QUALITY + TRIGGERING_ACCURACY. |
| `test_no_skill_eval_errors` | No dimension returns ERROR (infrastructure issue with the eval harness itself). |

A skill that introduces a FAIL on a mandatory dimension blocks the merge. The author either fixes the skill OR amends ADR-035 to demote the dimension from mandatory to permissive (with rationale).

---

## 5. Status as of 2026-05-16

| Skill | Version | Frontmatter | Script | Output | Triggering |
|---|---|---|---|---|---|
| audit-completeness | 1.0.4 | PASS | PASS | SKIP | SKIP |
| dive-complete | 1.0.1 | PASS | PASS | SKIP | SKIP |
| external-signals | 1.0.0 | PASS | PASS | SKIP | SKIP |

All three skills satisfy mandatory dimensions. None declare `output_schema:` yet — first declaration is part of the next eval-tightening pass.

---

## 6. CLI surfaces

| Command | Behavior |
|---|---|
| `invest skill eval` | Cross-skill summary table + per-skill detail blocks |
| `invest skill eval <name>` | One skill's four-dimension report |
| `invest skill eval --validate` | Exit 1 on any FAIL (mirrors the CI gate) |

---

## 7. Anti-patterns

Do NOT:

- **Demote a mandatory dimension silently.** Demoting FRONTMATTER_STRUCTURE or SCRIPT_EXECUTION from mandatory to permissive requires an ADR amendment with rationale.
- **Add `output_schema:` to a frontmatter without an accompanying skill body update.** The schema must reflect actual skill output, not aspiration.
- **Build the triggering-accuracy runner inside the deterministic data path.** Per CLAUDE.md, only `deepdive/narrative.py` and `deepdive/external_signals.py` are permitted Anthropic call sites — the eval runner needs its own ADR + call site, or remains manual (Option B).
- **Mark a check as PASS when it actually didn't run.** The four statuses (PASS/FAIL/SKIP/ERROR) are distinct: SKIP means "check is N/A or deferred"; PASS means "check ran and succeeded."

---

## 8. Forward-looking notes

- **Composability** (ADR-036, deferred) will introduce a fifth dimension: COMPOSABILITY_CONSISTENCY — does the `composes:` manifest validate against the dependency-skill versions present? When ADR-036 ships, ADR-035 §1 table expands.
- **Output schema mandatoriness** — promoting `output_schema:` from optional to mandatory is the natural next eval-tightening. Likely 6-month horizon, after at least one skill ships with a schema and proves the friction is manageable.
- **Eval results persisted** — today eval runs are stateless. A future amendment could persist `SkillEvalReport` to a new table for trend-over-time visibility (parallel to `skill_invocations`).

---

*Authored 2026-05-16 in the same session as ADR-034. Together they fulfil Anthropic's Versioning + Evaluation pillars; Composability remains for ADR-036.*
