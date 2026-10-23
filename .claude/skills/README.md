# `.claude/skills/` — Project-Local Skills

> Skills codify the routine workflows that today re-derive themselves every session, paying ~80% in tokens, ~80% in latency, and unbounded variance in quality.

This directory contains project-local skills per **[ADR-032](../../docs/architecture/adrs/ADR-032-project-local-skills-for-routine-task-workflows.md)**. Each `.md` file (except this README) is a single skill: a deterministic, single-concern workflow that Claude can invoke by name via the `Skill` tool.

---

## How skills are invoked

When you (the user) say *"run audit-completeness on SHOP"* or simply *"/audit-completeness SHOP"*, Claude calls:

```
Skill(skill="audit-completeness", args="SHOP")
```

Claude reads the skill body, executes its workflow, and reports the result. The skill body is treated as **binding instructions** — the postconditions and pre-flight checks are mandatory, not advisory.

---

## File layout

```
.claude/skills/
  README.md                      ← this file (schema reference)
  dive-complete.md               ← /dive-complete TICKER
  audit-completeness.md          ← /audit-completeness TICKER
  external-signals.md            ← /external-signals TICKER (dangerous: true)
  …
  personal/                      ← gitignored — non-generalising per-user skills
```

The `personal/` subdirectory exists for one-off workflows that don't generalise to the project. It is gitignored. Skills there are loaded by your local Claude but never shared.

---

## Frontmatter contract (mandatory)

Every skill file MUST start with this YAML block. Fields are non-negotiable; see ADR-032 §2.1 for the full rationale.

```yaml
---
name: {slug-in-kebab-case}
description: |
  {One paragraph. What it does, WHEN to invoke (the triggers).}
do_not_invoke_when:                # min 3 negative examples (ADR-032 §1.4 Vector 2 mitigation)
  - {when NOT to invoke}
  - {when NOT to invoke}
  - {when NOT to invoke}
arguments:
  - name: {arg}
    type: {ticker | path | text | enum:A,B,C}
    required: true | false
    description: {one-line}
preconditions:                     # testable assertions, MUST hold before workflow runs
  - {assertion}
postconditions:                    # testable assertions, MUST hold after workflow succeeds
  - {assertion}
side_effects:                      # DB writes / filesystem / network / LLM tokens
  - {what changes}
dangerous: false | true            # true → MUST request explicit user confirmation before running
token_budget_estimate:
  prompt: {tokens}
  completion: {tokens}
cost_estimate_usd: {dollars}       # per invocation, null if free
permitted_anthropic_calls:         # exactly one of these — never wildcard
  - {none | narrative.py | external_signals.py}
related_adrs:
  - {ADR-XXX}
mental_models:                     # optional — slugs from mental_models/
  - {slug}
shadow_mode_until: {YYYY-MM-DD}    # date string OR null; gates shadow-mode verification (§9.1)
version: 1.0.0
last_reviewed: {YYYY-MM-DD}
---
```

---

## Body structure

After the frontmatter, the body follows this order (deviations require ADR amendment):

1. **What this does** (3-5 sentences, plain English)
2. **Workflow** (numbered steps; each is one tool call or one decision)
3. **Pre-flight checks** (exact tool calls that verify preconditions)
4. **Failure modes** (what can go wrong; how to detect; what to surface to the user)
5. **Shadow-mode verification** (§9.1 — required while `shadow_mode_until` is in the future)
6. **Audit trail** (what gets persisted; how to find it later)
7. **Examples** (1-3 concrete invocations with expected output)

---

## Naming conventions

- Lowercase, kebab-case
- Verb-first when imperative (`dive-complete`, `audit-completeness`, `refetch-form4`)
- Noun-first when query-only (`data-gap-register`, `cost-budget-status`)
- **MUST NOT shadow CLI subcommand names.** `dive` is taken (it's `invest dive`); use `dive-complete` for the skill.

---

## The rule of three (§5 in ADR-032)

**A new skill is authored only when the workflow has been executed 3 or more times across sessions, with observed variance.**

This guard prevents accumulation of dead skills. Codify what you've already verified by repetition, not what you imagine will repeat.

Inversely: a skill not invoked ≥3 times in 4-6 weeks is retired (frontmatter `version` gets a `-DEPRECATED` suffix; eventually deleted).

---

## Shadow-mode (§9.1 in ADR-032)

**Every new skill spends its first 14 days in shadow mode.** During that window, the skill body MUST include a verification step that:

1. Captures the skill's output (composite_score, persisted row IDs, etc.) into the `skill_invocations` table
2. Asserts every postcondition deterministically
3. Delta-checks against any prior canonical artifact for the same target
4. Loudly surfaces anomalies (prefixed `[SHADOW-MODE ANOMALY]`) to the user

A skill exits shadow mode when **all** hold:
- ≥10 invocations recorded
- 100% postcondition pass rate
- 0 unexplained delta anomalies
- Author has manually reviewed the 10 records

When met: `shadow_mode_until: null` and `version` bumps minor.

When failed: skill suspended (`version` gets `-SUSPENDED` suffix); RC analysis; clock resets.

---

## What skills MUST NOT do

(All non-negotiable per ADR-032 §8 and CLAUDE.md §"AI layer boundary":)

1. **No new Anthropic call sites.** Only `deepdive/narrative.py` and `deepdive/external_signals.py` are permitted. Skills that need LLM work invoke those modules.
2. **No new persistence paths.** Writes go through canonical CLI subcommands or the `external_signals` channel.
3. **No silent fallback.** When a precondition fails, surface the gap; do not fabricate.
4. **No model-drift hiding.** Hardcode validated model IDs; bump `version` when changing.
5. **No retroactive composite-score changes.** New data appends as new runs; old runs are immutable.
6. **No `dangerous: true` bypass.** Confirmation discipline is non-negotiable.
7. **No phantom `mental_models:` references** — every slug must resolve to a real `mental_models/<domain>/<slug>.md` file. Caught by `tests/test_skills/test_mental_model_refs.py` (WARN-only — linkage is documentary). The lattice runtime touch-point is `deepdive/mental_model_composer.py` selecting models per ScorecardView at narrative time, NOT skills declaring static lists.
8. **No phantom `composes:` references** — every `composes.skills[].name` must resolve to a real skill file; constraint strings must parse as PEP-440 ranges; no self-loops or cycles. Caught by `tests/test_skills/test_composability.py` (ERROR severity — blocks CI). See ADR-036 §3.
9. **No version-lineage drift** — frontmatter `version` MUST match the latest `changelog:` entry; no duplicate versions; date-monotonic. Caught by `tests/test_skills/test_version_lineage.py`. See ADR-034 §3.

---

## Audit + CI

Every invocation logs a `skill_invocations` row (ADR-032 §9.1.1) carrying `skill_name`, `skill_version`, args, postcondition pass/fail array, anomalies, cost, and duration.

**Five CI test files (16 tests total)** — all pass at 2026-05-17:

| Test file | Tests | Enforces | ADR |
|---|---|---|---|
| `test_signature_compatibility.py` | 6 (some skipped per-skill) | CLI-surface stability (Vector 3 mitigation) | ADR-032 §10 #9 |
| `test_version_lineage.py` | 4 | Frontmatter `version` matches `changelog` head + no duplicate versions + date-monotonic | ADR-034 §3 |
| `test_evals.py` | 2 | Mandatory eval dimensions: frontmatter_structure + script_execution + composability_consistency | ADR-035 §4 |
| `test_composability.py` | 3 | `composes:` refs resolve, no self-loops, no cycles | ADR-036 §3 |
| `test_mental_model_refs.py` | 3 | Lattice slug typo-catch in `mental_models:` field (WARN-only — documentary linkage) | ADR-024 |

The `Skill_check` task in the warehouse (future Phase 2) audits skill staleness — skills unused for 60+ days surface for retirement review.

---

## Adding a new skill

1. Confirm rule-of-three (have you done this workflow ≥3 times with variance?)
2. Draft the frontmatter — every field mandatory
3. Write the body following the 7-section structure above
4. Set `shadow_mode_until` = today + 14 days
5. Run `uv run pytest tests/test_skills/test_signature_compatibility.py` — must pass
6. Invoke the skill in a fresh session — verify it runs end-to-end
7. Commit with a reference to the rule-of-three evidence (e.g., `feat(skills): add /foo (3 invocations in sessions A/B/C)`)

---

## Current skill inventory

| Skill | Version | Status | Shadow expires | Composes | Notes |
|---|---|---|---|---|---|
| `dive-complete` | **1.1.0** | active | 2026-05-29 | `uses` audit-completeness; `suggests` external-signals; lib edgartools≥2.0 | Wraps the full Tier-2 dive cycle |
| `audit-completeness` | **1.1.0** (was 1.0.4 pre-composes backfill) | active | 2026-05-29 | `suggests` external-signals; lib edgartools≥2.0 | Gap classification per ADR-031 §1.2 |
| `external-signals` | **1.1.0** | active | 2026-05-29 | lib anthropic≥0.28; lib edgartools≥2.0 | `dangerous: true` — LLM extraction with cost ceiling |

Live inventory + version history available via `invest skill lineage` (ADR-034) and `.claude/skills/_lineage.md` (auto-generated).

Deferred (rule-of-three not yet satisfied): `refetch-form4`, `mic-parse`, `screen-and-watchlist-audit`, `data-quality-report`, `narrative-with-grounding`, `cost-budget-status`. See ADR-032 §4.

---

## CLI subcommands

| Command | Purpose | ADR |
|---|---|---|
| `invest skill list` | List all skills + shadow-mode status | ADR-032 |
| `invest skill status <name>` | Shadow-mode status + recent invocations | ADR-032 |
| `invest skill run <name> [ticker]` | Execute a skill (requires `--confirm` for `dangerous: true`) | ADR-032 |
| `invest skill lineage [name] [--rebuild|--validate]` | Per-skill or cross-skill chronological version timeline | **ADR-034** |
| `invest skill eval [name] [--validate]` | Five-dimension evaluation report | **ADR-035** |
| `invest skill compose [name] [--validate]` | Tree view of skill's `composes:` dependencies (skills + MCPs + libraries) | **ADR-036** |
