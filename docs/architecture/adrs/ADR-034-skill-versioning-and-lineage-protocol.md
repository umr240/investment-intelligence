# ADR-034 — Skill Versioning + Lineage Protocol

> Status: **Accepted**
> Date: 2026-05-16
> Supersedes: nothing (extends ADR-032)
> Related: ADR-032 (project-local skills), ADR-031 (data gap register)
> Trigger: User 2026-05-16, citing Anthropic's "Don't Build Agents, Build Skills Instead" talk — Evaluation / Versioning / Composability framing on how skills evolve.

---

## 1. Decision

Every skill in `.claude/skills/` carries an explicit, machine-verifiable version lineage. The lineage is:

1. **Recorded** in each skill's frontmatter `version:` + `changelog:` array (source of truth).
2. **Indexed** chronologically in `.claude/skills/_lineage.md` (auto-generated).
3. **Validated** by `cli/skills/lineage.py:validate_lineage()` (CI gate via `tests/test_skills/test_version_lineage.py`).
4. **Linked to runtime telemetry** through `skill_invocations.skill_version` (existing column; see ADR-032 §9.1.1).
5. **Inspectable** via `invest skill lineage [skill_name]` (CLI).

Anthropic's three pillars (Evaluation / Versioning / Composability) map to:

| Pillar | This ADR | Existing system |
|---|---|---|
| **Versioning** | §2 + §3 (semver, dated changelog, CI validator) | ADR-032 §9.1 already mandates `version:` bumps on shadow-mode exit |
| **Evaluation** | §4 graduation evidence | ADR-032 §9.1.2 shadow-mode discipline + `skill_invocations` telemetry |
| **Composability** | §5 (skill-references manifest, deferred) | Not yet built — skills reference other skills via prose today |

---

## 2. Version semantics

### 2.1 Semver discipline

```
MAJOR.MINOR.PATCH
```

| Bump | When |
|---|---|
| **PATCH** (1.0.0 → 1.0.1) | Bug fix, prompt tweak, frontmatter clarification, comment edit. Behavior contract unchanged. |
| **MINOR** (1.0.x → 1.1.0) | New optional argument, new postcondition, additive workflow step, **shadow-mode graduation** (§4). |
| **MAJOR** (1.y.z → 2.0.0) | Workflow rewrite, removed postcondition, breaking arg signature change, new `dangerous: true` requirement, new permitted Anthropic call site (which also needs an ADR amendment per CLAUDE.md). |

### 2.2 Suffixes

Two suffixes are recognised (per ADR-032 §9.1.2):

- `-SUSPENDED` — skill failed shadow-mode verification; `run_skill()` refuses to invoke until a human resolves
- `-DEPRECATED` — skill marked for retirement (rule-of-three inverse — not invoked ≥3 times in 4-6 weeks per ADR-032 §5). Removal grace = 30 days.

A skill in either state must still carry a valid semver prefix (`1.0.3-SUSPENDED`). The validator strips the suffix before comparison.

### 2.3 Same-day bumps

Multiple changes on the same calendar day get distinct semvers (`1.0.1` and `1.0.2` on `2026-05-15` is fine). Two entries with the same version on the same day are a §3.2 error — the validator catches them.

### 2.4 Changelog entry format

```yaml
changelog:
  - "1.0.0 (2026-05-15): initial."
  - "1.0.1 (2026-05-15): summary of what changed."
  - "1.1.0 (2026-05-29): shadow-mode graduation — 10/10 invocations clean."
```

Strict regex `^(?P<version>\d+\.\d+\.\d+(?:-[A-Z]+)?)\s*\(\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\)\s*:\s*(?P<summary>.+)$`. Anything else fails parsing as a §3 warning.

The summary should answer **what changed AND what it fixed** — bug-fix entries should reference the failure mode they close (e.g., `"fix AttributeError on framework_unfeasible_count — surfaced on PATH/LULU/MRVL"`). This turns the changelog into a debugging trail.

---

## 3. Validation invariants

`cli/skills/lineage.py:validate_lineage()` enforces:

### §3.1 Frontmatter–changelog consistency (ERROR)

```
frontmatter `version:` == latest entry's version in `changelog:`
```

If frontmatter says `version: 1.0.4` but the most-recent entry is `1.0.3 (date): foo` → ERROR. The version bump is real only when both halves move together.

### §3.2 No duplicate versions (ERROR)

```
within one skill, no two `changelog:` entries may share a version
```

`audit-completeness` 2026-05-15 had two entries both labelled `1.0.1` — the validator caught it; we renumbered the second to `1.0.2` and pushed downstream versions accordingly. This protocol formalises that fix.

### §3.3 Date monotonicity (ERROR)

```
entries sorted by version (which implies date-ordering when versions are
strictly increasing) must also be date-non-decreasing
```

Catches a version assigned a date earlier than its predecessor — a copy-paste error in practice.

### §3.4 Shadow-mode promotion clock (WARNING)

```
if `shadow_mode_until` is in the past, the skill must already have a
MINOR bump removing the date OR an extension entry
```

Warning, not error — sometimes you need a few extra days. But the warning must be resolved before the next session.

---

## 4. Graduation evidence (Evaluation pillar)

ADR-032 §9.1.2 sets the criteria for shadow-mode exit:

- ≥10 invocations recorded in `skill_invocations`
- 100% postcondition pass rate
- 0 unexplained anomalies
- Author has manually reviewed the 10 records

This ADR codifies **how that evidence appears in the lineage**:

When a skill graduates, its new changelog entry MUST cite the evidence range:

```yaml
- "1.1.0 (2026-05-29): graduated from shadow-mode (skill_invocations rows 12–21, all postconditions PASS, no anomalies). shadow_mode_until → null."
```

This makes the evaluation gate visible in the lineage — anyone reading `_lineage.md` can trace WHY a skill moved from `1.0.x` to `1.1.0`.

If graduation criteria aren't met, the skill stays at `1.0.x` and `shadow_mode_until` is extended (with a changelog entry recording the extension reason).

---

## 5. Composability (deferred to ADR-036)

Anthropic's third pillar — skills composing other skills (Branded Decks = Brand Style Skill + PowerPoint Skill; PowerPoint Skill uses MCP + pandas) — is not in scope for this ADR. The hooks are reserved here:

Future skill frontmatter MAY include:

```yaml
composes:
  - skill: brand-style          # another local skill
    version_constraint: ">=1.0,<2.0"
  - mcp: filesystem             # external MCP
    capability: read_only
  - library: pandas
    version_constraint: ">=2.0"
```

A future ADR-036 will codify:
- How the runtime validates composability constraints before invocation
- How a composing skill's lineage entries reference dependent-skill versions
- How a breaking change in a dependency cascades to a `MAJOR` bump

Today, composition is prose-level (skills reference each other in their `description:` and workflow steps). The lineage system tracks per-skill versions correctly; composition tracking layers on top.

---

## 6. Operational surfaces

### 6.1 `invest skill lineage [skill_name]`

| Variant | Output |
|---|---|
| `invest skill lineage` | Cross-skill chronological timeline (newest first). The Anthropic-slide global timeline view. |
| `invest skill lineage <name>` | One skill's per-version timeline (oldest → newest), with the current frontmatter version marked ●. |
| `invest skill lineage --rebuild` | Regenerate `.claude/skills/_lineage.md` from current frontmatter. Idempotent. |
| `invest skill lineage --validate` | Run validator; exit 1 on any error finding (CI gate). |

### 6.2 `.claude/skills/_lineage.md`

Auto-generated, do not hand-edit. Body:

1. Cross-skill chronological view (newest first)
2. Per-skill version timelines
3. Validation findings at last regeneration

Regenerate after every changelog edit. CI catches drift via the test below.

### 6.3 `tests/test_skills/test_version_lineage.py`

Four tests:

| Test | Asserts |
|---|---|
| `test_all_skills_have_lineage` | `validate_lineage()` produces zero error findings (§3.1/§3.2/§3.3) |
| `test_each_skill_has_at_least_one_entry` | Every skill has ≥1 changelog entry (§3.1) |
| `test_frontmatter_version_matches_changelog_head` | §3.1 direct assertion |
| `test_lineage_index_is_regeneratable` | `rebuild_lineage_index()` runs cleanly + produces non-trivial output |

Run via `uv run pytest tests/test_skills/`.

---

## 7. Migration of existing skills (one-time fix)

When this ADR was authored (2026-05-16), the validator surfaced 2 errors:

1. `audit-completeness` had two changelog entries both labelled `v1.0.1` → renumbered:
   - `1.0.1` (FPI detection fix — was: 1.0.1)
   - `1.0.2` (R&D display ratio fix — was: 1.0.1)
   - `1.0.3` (rd_intensity classification — was: 1.0.2)
   - `1.0.4` (Tier 1.3 FPI detection via edgartools.is_foreign — was: 1.0.3)
   - Frontmatter `version: 1.0.3` → `1.0.4`

2. `external-signals` had no `changelog:` array → added the initial entry:
   - `1.0.0 (2026-05-15): initial — LLM-supplementary extraction of NRR/GRR/...`

Both fixes ship with this ADR. Post-fix: validator clean (0 errors, 0 warnings).

---

## 8. Anti-patterns

Do NOT:

- **Edit a changelog entry retroactively.** Wrong: changing the summary of `1.0.1` weeks after the fact. Right: ship a new `1.0.x+1` entry that corrects the prior summary.
- **Skip the changelog when bumping `version:`.** The frontmatter version IS the changelog head — if you don't have a new entry, you don't have a new version.
- **Reuse a version after a `-SUSPENDED` suffix.** When a suspended skill is fixed, it gets a fresh MINOR bump (`1.0.3-SUSPENDED` → `1.1.0`). The history of the suspension stays in the changelog.
- **Hand-edit `_lineage.md`.** It's regenerated; manual edits are blown away on next rebuild.
- **Use unstructured semver-equivalents like dates-as-versions.** `2026-05-15.1` is not a valid version. Stick to `X.Y.Z`.

---

## 9. Forward-looking notes

When the codebase grows beyond ~10 skills, the lineage index will get long. Two scaling options:

1. **Hierarchical lineage** — group skills by `category:` frontmatter field (e.g., "data-quality", "narrative", "screening"). `_lineage.md` becomes a per-category roll-up.
2. **Time-windowed view** — `invest skill lineage --since 2026-04-01` filters to recent changes.

Both are deferred until needed. Today's 3-skill inventory fits one screen.

---

*Authored 2026-05-16 in response to user citing Anthropic's "Exploring how Skills evolve" framing.*
