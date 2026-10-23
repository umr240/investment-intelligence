# ADR-036 — Skill Composability Protocol

> Status: **Accepted**
> Date: 2026-05-16
> Supersedes: nothing (closes the three-pillar set after ADR-034 + ADR-035)
> Related: ADR-032 (project-local skills), ADR-034 (versioning + lineage), ADR-035 (evaluation protocol)
> Trigger: User 2026-05-16, citing Anthropic's "Don't Build Agents, Build Skills Instead" — completes the third pillar (Composability) after Versioning (ADR-034) + Evaluation (ADR-035) shipped earlier in the same session.

---

## 1. Decision

Every skill in `.claude/skills/` declares its dependencies — on other skills, on MCPs, and on Python libraries with version-sensitive APIs — via an optional `composes:` frontmatter block. The composition graph is parsed by `cli/skills/composability.py`, validated by CI, surfaced via `invest skill compose`, and gated by the fifth eval dimension (`COMPOSABILITY_CONSISTENCY` per ADR-035 §8).

Anthropic's "Branded Decks = Brand Style Skill + PowerPoint Skill; PowerPoint Skill = MCP + pandas" example maps directly to this schema. Our project-local instantiation (2026-05-16): `dive-complete` uses `audit-completeness` as workflow step 1, both depend on `edgartools>=2.0`, and `external-signals` depends on `anthropic>=0.28` (the permitted call site).

Anthropic three-pillar status — now complete:

| Pillar | ADR | Status |
|---|---|---|
| Versioning | ADR-034 | ✅ Shipped 2026-05-16 |
| Evaluation | ADR-035 | ✅ Shipped 2026-05-16 |
| Composability | ADR-036 (this) | ✅ Shipped 2026-05-16 |

---

## 2. The `composes:` schema

```yaml
composes:
  skills:                       # other .claude/skills/* this depends on
    - name: audit-completeness  # must match an existing skill filename
      relation: uses            # uses | suggests | extends
      constraint: ">=1.0"       # PEP-440 range; optional but recommended

  mcps:                         # external MCP servers this skill calls
    - name: filesystem
      capability: read_only     # informational; no runtime enforcement today

  libraries:                    # Python libs ONLY when version-sensitive
    - name: edgartools
      constraint: ">=2.0"
```

### 2.1 Relations (skill-to-skill only)

| Relation | Meaning |
|---|---|
| `uses` | The composing skill literally invokes the dependency as part of its workflow. Hard dependency. Breaking the dependent skill breaks this one. |
| `suggests` | The composing skill recommends invoking the dependency as a logical next step but doesn't run it. Soft dependency. |
| `extends` | The composing skill is a specialization / superset of the dependency. Used when forking a skill — e.g., `dive-complete-tier1` extends `dive-complete`. |

A `uses` relation should typically pair with a tight constraint (`>=1.0,<2.0`); a `suggests` relation can be looser.

### 2.2 What NOT to put in `libraries:`

Don't list every Python import. The `libraries:` array exists for **version-sensitive dependencies only**:

- Listed: `edgartools>=2.0` (skill calls `Company.is_foreign` introduced in 2.0)
- Listed: `anthropic>=0.28` (skill uses the message-creation API shape)
- NOT listed: `sqlalchemy`, `httpx`, `pydantic` — project-wide via pyproject.toml; no per-skill version sensitivity
- NOT listed: stdlib modules

The threshold is: *would this skill break on a different version of this library*. If yes, list. If no, don't add noise.

### 2.3 MCPs

`mcps:` entries are **informational today** — no runtime enforcement of MCP capability matching. They serve as documentation: "this skill uses the Atlassian MCP, with read_only capability." A future amendment may enforce capability matching when the runtime supports it.

---

## 3. Validation invariants

`cli/skills/composability.py:validate_composition()` enforces three rules:

### §3.1 Skill references resolve (ERROR)

```
every composes.skills[].name must match an existing skill file under
.claude/skills/
```

Catches: typos, deleted skills, skills that haven't been authored yet.

### §3.2 No self-loops (ERROR)

```
a skill cannot list itself in composes.skills[]
```

Catches: copy-paste errors during skill authoring.

### §3.3 No composition cycles (ERROR)

```
the skill-to-skill subgraph must be a DAG — no path from skill A back
to itself via composes.skills[] edges
```

DFS-based cycle detection. Catches: mutual `uses` declarations (A uses B AND B uses A) — almost always indicates the relationship should be `extends` or a refactor is needed.

Constraint format is validated at parse time (separately from §3.1-3.3) — malformed PEP-440 ranges produce error findings that block CI.

---

## 4. Fifth eval dimension

`cli/skills/evals.py:EvalDimension.COMPOSABILITY_CONSISTENCY` wraps `validate_composition()`:

| Status | When |
|---|---|
| PASS | `composes:` declared + all entries resolve cleanly |
| FAIL | One or more error findings from validate_composition |
| SKIP | No `composes:` block declared (optional today) |
| ERROR | Parser itself failed (unrecoverable — infra issue) |

Per ADR-035 §1, this dimension is **mandatory** in CI. A skill with malformed composition blocks the build. (Same gate-level as `FRONTMATTER_STRUCTURE` + `SCRIPT_EXECUTION`.)

### 4.1 Why mandatory from day one (unlike output_schema)

Composition has zero authoring friction — most skills won't declare anything (the SKIP path is free). When a skill DOES declare composition, the declaration must be correct, because a stale reference is exactly the kind of silent drift this protocol prevents.

By contrast, `output_schema:` (ADR-035 §2.2) is permissive because authoring a schema is non-trivial and the cost-of-friction is high. Composition is just metadata.

---

## 5. CLI surface

| Command | Behavior |
|---|---|
| `invest skill compose` | Cross-skill dependency graph (every edge on one line) |
| `invest skill compose <name>` | One skill's tree view (Anthropic-slide style) |
| `invest skill compose --validate` | Exit 1 on any error finding (mirrors CI gate) |

Sample output:

```
# Skill composition graph (all edges)

  audit-completeness --[suggests]--> external-signals (>=1.0)
  audit-completeness --[lib]--> edgartools (>=2.0)
  dive-complete --[uses]--> audit-completeness (>=1.0)
  dive-complete --[suggests]--> external-signals (>=1.0)
  dive-complete --[lib]--> edgartools (>=2.0)
  external-signals --[lib]--> anthropic (>=0.28)
  external-signals --[lib]--> edgartools (>=2.0)
```

---

## 6. Version cascading

Per ADR-034 §2.1 semver discipline, here's how a dependency change cascades into a composing skill's version:

| Change in dependency | Composing skill's version bump |
|---|---|
| Dependency PATCH (1.0.0 → 1.0.1) | None — composition unaffected |
| Dependency MINOR (1.0.x → 1.1.0) | Composing skill MAY bump PATCH if it adopts new optional behavior; otherwise None |
| Dependency MAJOR (1.y.z → 2.0.0) | Composing skill MUST review + likely bump MINOR (if compatible) or MAJOR (if it consumed a removed API) |
| Dependency added to `composes:` | The composing skill MUST bump MINOR (additive metadata) — exactly what the three backfilled skills did on 2026-05-16 (all bumped 1.0.x → 1.1.0) |
| Dependency removed from `composes:` | Composing skill MUST bump MINOR (declarative dependency surface shrunk) |
| Dependency's `constraint:` tightens (e.g., `>=1.0` → `>=1.0,<2.0`) | Composing skill MUST bump PATCH or MINOR depending on whether the tightening reflects new behavior |
| Dependency's `relation:` changes (e.g., `suggests` → `uses`) | Composing skill MUST bump MINOR — relation change is a real shift in workflow coupling |

The validator does NOT enforce these — they're conventions. ADR-034 §3 catches the version<->changelog inconsistency that would result from forgetting a bump.

---

## 7. Status as of 2026-05-16

The backfill bumped all three skills 1.0.x → 1.1.0 with explicit composition declarations:

| Skill | v | Composes |
|---|---|---|
| `audit-completeness` | 1.1.0 | suggests `external-signals (>=1.0)`; lib `edgartools (>=2.0)` |
| `dive-complete` | 1.1.0 | uses `audit-completeness (>=1.0)`; suggests `external-signals (>=1.0)`; lib `edgartools (>=2.0)` |
| `external-signals` | 1.1.0 | lib `anthropic (>=0.28)`; lib `edgartools (>=2.0)` |

All three PASS `COMPOSABILITY_CONSISTENCY`. The full graph has no cycles and one `uses` edge (`dive-complete → audit-completeness`).

---

## 8. Anti-patterns

Do NOT:

- **Stuff every Python import into `libraries:`.** Only list version-sensitive deps. Routine imports are pyproject.toml's job.
- **Use `uses` when you mean `suggests`.** `uses` means "I literally invoke this skill in my workflow." If the user might invoke the other skill as a follow-up but you don't run it, that's `suggests`.
- **Declare circular `uses` to model bidirectional cooperation.** Composition is a DAG. If two skills genuinely cooperate symmetrically, extract the shared logic into a third skill that both `use`.
- **Skip the version bump when adding `composes:`.** Per §6, declaring composition for the first time is a MINOR bump (additive metadata change). The three backfilled skills bumped 1.0.x → 1.1.0 to demonstrate.
- **Mix `composes:` semantics with `related_adrs:`.** The latter records architectural rationale (ADR links); the former records concrete runtime dependencies. They serve different audit purposes.

---

## 9. Forward-looking notes

When the inventory grows beyond ~10 skills, three extensions become attractive:

1. **Visual graph rendering** — emit Graphviz or Mermaid syntax from `render_dependency_graph()`. Useful for onboarding diagrams.
2. **Transitive constraint propagation** — if A uses B and B uses C, validate that A's constraint on C (via B) is satisfied. Today the graph is one-hop only.
3. **MCP capability runtime enforcement** — when the runtime supports MCP-capability checks, the `mcps[].capability` field gets teeth. Today it's documentation.

All three are deferred. The current implementation is the MVP that ships the third Anthropic pillar.

---

## 10. CI integration summary

After ADR-036 ships, the `tests/test_skills/` suite has 13 passing tests across four files:

| File | Tests | Pillar |
|---|---|---|
| `test_signature_compatibility.py` | 6 (some skipped per-skill) | Foundation (ADR-032 §10 #9) |
| `test_version_lineage.py` | 4 | Versioning (ADR-034) |
| `test_evals.py` | 2 | Evaluation (ADR-035 + composability now mandatory per ADR-036 §4) |
| `test_composability.py` | 3 | Composability (this ADR) |

Run via `uv run pytest tests/test_skills/`. All must pass before merge.

---

*Authored 2026-05-16. Together ADRs 034 + 035 + 036 codify the full three-pillar skill discipline Anthropic outlined in "Don't Build Agents, Build Skills Instead."*
