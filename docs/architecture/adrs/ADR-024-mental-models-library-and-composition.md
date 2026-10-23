# ADR-024 — Mental Models Library & Composition Pipeline

| Field | Detail |
|---|---|
| **Status** | **Accepted + Stages A-C complete** (status updated 2026-05-17). Stage A directory + extraction + schema (2026-05-09). Stage B composer wired into `narrative.py` (2026-05-10) — `select_models_for_dive(LatticeProfile)` injects context-appropriate subset. Stage C closed 2026-05-09 with 111 models across 16 populated domain directories. Token budget raised 6000→8000 (2026-05-17) after Thorndike budget-starvation incident. PSA verdict-aware archetype gating added 2026-05-17 (`narrative._select_archetype` reads `view.overlay_verdicts`). |
| **Date** | 2026-05-09 |
| **Provenance** | User direction 2026-05-09: scale §ANALYTICAL PERSONALITY toward a 100+ model latticework. Prior Claude session decomposed the question into knowledge-management (where models live), knowledge-composition (how they reach the LLM), and rejected the "LLM brain" framing as a category error. |
| **Supersedes** | Nothing. |
| **Updates** | CLAUDE.md §ANALYTICAL PERSONALITY (canonical source moves to `mental_models/`; CLAUDE.md retains stance + operationalisation table + pointer); ADR-023 §1.3 Block 2 (the lattice the narrative LLM reasons through is now a structured artifact, not embedded prose). |
| **Preserves** | CLAUDE.md determinism rule; ADR-021 / ADR-022 methodology; ADR-023 personality contract. |
| **Affects** | New `mental_models/` directory. No effect on data / framework / overlay code in this stage. |

---

## 0. The reframe

"Build a brain of our LLM" is the wrong framing — the LLM is rented compute, not memory. The actual problem is **knowledge composition**: given a growing latticework, deliver the right subset to the LLM at the right moment within token budget.

This ADR pins the structure of the latticework so it can grow toward 100+ models without bloating CLAUDE.md beyond its readability budget, and so the eventual `narrative.py` (Phase 6) has a stable artifact to compose against rather than parsing prose out of a freeform document.

Three failure modes this ADR is built to prevent:

1. **Inversion-form debt.** A model entered without its inversion is half-loaded. CLAUDE.md §"Inversion as primary tool" demands inversion at the framework layer; this ADR demands it at the model layer too. Every model has an `inversion_form` section. No exceptions.

2. **Knowledge bloat without removal.** Every addition gets celebrated; nothing ever gets retired. The library degrades into noise. Defence: every model has a removal criterion + annual review marker.

3. **Models without code teeth.** Decorative philosophy that doesn't change framework design, overlay logic, test coverage, or output vocabulary. Defence: `code_consequences` field is mandatory and must reference actual modules/functions.

---

## 1. Decision

### 1.1 Directory structure

```
mental_models/
├── README.md          ← schema + how-to-add-a-new-model + retirement criteria
├── _index.md          ← canonical listing, citation tier, slug, always_load flag
├── _gaps.md           ← first-class artifact: what's missing per domain
│
├── core/              ← always-loaded foundation
├── moat/              ← conditionally loaded if company has revenue
├── management/        ← conditionally loaded when DEF 14A / proxy data present
├── bias/              ← always-loaded guardrails
├── valuation/         ← stage / overlay conditional
├── lifecycle/         ← stage conditional (pre-discovery, platform, post-spinoff)
└── meta/              ← models about models (lollapalooza, man-with-hammer, etc.)
```

Stage A populates `core/`, `moat/`, `management/`, `bias/` from the existing CLAUDE.md §ANALYTICAL PERSONALITY content. `valuation/`, `lifecycle/`, `meta/` are created empty with a `.gitkeep` for future growth toward 100+.

### 1.2 File format — markdown with YAML frontmatter

Pure YAML scales poorly past ~30 models with substantive prose. Pure markdown loses queryability. The middle is markdown body + YAML frontmatter:

```markdown
---
slug: inversion
name: Inversion
school: munger
citation_tier: "★★★"
always_load: true
related_models:
  - failure_mode_analysis_engineering
  - pre_mortem_psychology
  - second_order_thinking
  - margin_of_safety
code_consequences:
  - Every framework has a corresponding disqualification check
  - Tests exercise failure modes, not just success paths
  - Each new feature must survive its own inversion before shipping
token_cost_estimate: 280
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Inversion

> *"Invert, always invert."* — Carl Jacobi (via Munger)

## Summary
[2-3 sentence prose summary]

## When to apply
- Bullet
- Bullet

## Inversion form
[Inverting the inversion principle itself — when does it fail?]

## Antipatterns
- Bullet

## Examples in this codebase
- file:function reference
```

This format is Obsidian-compatible from day one (when authoring eventually moves to a vault), GitHub-readable, and queryable with any YAML parser.

### 1.3 Mandatory frontmatter fields

A model file is **rejected** (does not ship) if any of these are missing:

| Field | Why mandatory |
|---|---|
| `slug` | Unique machine identifier; basis for `related_models` cross-references |
| `name` | Human-readable title |
| `school` | Discipline / origin (munger, helmer, thorndike, kahneman, taleb, etc.) — used for diversity metrics |
| `citation_tier` | `★★★` peer-reviewed alpha source / `★★` strong empirical / `★` heuristic / `◯` qualitative lens — mirrors QUICK_REFERENCE.md v3.0 discipline |
| `always_load` | Boolean — does this enter the prompt unconditionally, or is it conditionally selected? |
| `related_models` | List of slugs — the lattice IS a graph, this field IS the edges |
| `code_consequences` | List — what this model changes in framework / overlay / test / output design. Empty list = retire the model. |
| `token_cost_estimate` | Integer — composer needs this for budget enforcement |
| `version` | Semver — bumped on substantive content change |
| `added` | ISO date — when first introduced |
| `last_reviewed` | ISO date — auto-flagged for review at 12 months |

### 1.4 Mandatory body sections

- **Summary** — 2-3 sentences
- **When to apply** — bullets describing trigger conditions
- **Inversion form** — what failing this model looks like; what its mirror image is
- **Antipatterns** — failure modes, including academic-bloat warnings
- **Examples in this codebase** — file:function references where the model has code teeth

### 1.5 Selection rules (composer — Phase 6.1+, NOT this stage)

Future `deepdive/mental_model_composer.py` will compose context as:

1. All `always_load: true` models from `core/` + `bias/` (always)
2. All models from `moat/` if company has revenue
3. All models from `management/` if DEF 14A / proxy ownership data present
4. Stage-conditional from `lifecycle/` based on archetype
5. Overlay-conditional from `valuation/` if ICA / PSA / BEW fired
6. Token-budget enforcement: rank by relevance + `token_cost_estimate`, truncate at budget

This stage **does not build the composer**. The directory + schema is the contract the future composer will read.

### 1.6 Anti-bloat protections (mandatory now, even pre-composer)

Every model file must satisfy these BEFORE merging:

- `code_consequences` is non-empty, references real modules/functions
- `inversion_form` body section is non-empty
- `citation_tier` is one of `★★★ / ★★ / ★ / ◯` (no other values; no blank)
- `related_models` references at least 2 other models that exist (the lattice is a graph)
- `last_reviewed` matches `added` on creation; is updated on every substantive edit

Annual review process: any model with `last_reviewed` >12 months old gets surfaced in `_gaps.md` for retire-or-update decision. Munger's man-with-a-hammer applies recursively.

### 1.7 What this Stage A explicitly does NOT build

| Deferred | Reason | When to revisit |
|---|---|---|
| ~~`mental_model_composer.py`~~ | ~~Runtime consumer (`narrative.py`) doesn't exist~~ | ✅ Shipped Stage D (skeleton 2026-05-09, wired into `narrative.py` 2026-05-10) |
| Obsidian → YAML sync script | Premature; authoring is in repo for now | When user begins authoring in Obsidian regularly |
| Embedding-based semantic retrieval | Massively premature | If lattice exceeds ~60 models AND token budgets get tight |
| Graph visualisation tooling | Decorative | Probably never |
| Bidirectional `related_models` link validation | Nice-to-have | When references break in practice |
| Per-model regression tests | Need narrative.py to exist first | Phase 6.1+ |

The directory structure + schema + extracted prose IS the alpha. Runtime tooling is a follow-on.

---

## 2. CLAUDE.md impact

CLAUDE.md §ANALYTICAL PERSONALITY shrinks to: default stance (owner-operator), latticework principle (one paragraph), operationalisation table, pointer to `mental_models/_index.md`. The 30 individual model bullets / table rows previously embedded migrate to one-file-per-model under `mental_models/`. The prose is preserved, just relocated.

This keeps CLAUDE.md within its ~200-line orientation budget while letting the lattice grow without bound.

---

## 3. Anti-patterns this ADR forbids

| Pattern | Why forbidden |
|---|---|
| Adding a model directly to CLAUDE.md instead of `mental_models/` | Bypasses schema enforcement; CLAUDE.md is no longer the canonical source |
| Model file with empty `code_consequences` | §1.6 — decorative philosophy without code teeth |
| Model file with no `inversion_form` body section | §1.6 — half-loaded model is no model |
| `related_models` with 0-1 entries | The lattice is a graph; isolated nodes contribute nothing to cross-domain reasoning |
| Bumping count toward "100 models" by splitting a single concept into trivially related sub-models | Munger's man-with-a-hammer applied recursively. Quality over count. |
| Citation tier `★★★` on a heuristic without peer-reviewed evidence | Mirrors QUICK_REFERENCE.md v3.0 audit discipline; Outsiders / Helmer are `◯` not `★★★` |

---

## 4. Implementation status

### Stage A (initial extraction)

- ✅ Directory structure created (`mental_models/{core,moat,management,bias,valuation,lifecycle,meta}`)
- ✅ README.md with schema + how-to-add documented
- ✅ `_gaps.md` with sparse domains + candidate models
- ✅ `_index.md` listing all extracted models
- ✅ Munger lattice → `core/` (12 models including owner-operator stance)
- ✅ Moat taxonomy → `moat/` (6 models)
- ✅ Outsiders 8 traits → `management/` (1 model)
- ✅ Bias awareness → `bias/` (7 Munger models initially)
- ✅ CLAUDE.md §ANALYTICAL PERSONALITY refactored to stance + table + pointer

### Stage B (sparse-domain population)

- ✅ `statistical/` populated (5 models: regression, base rates, survivorship, Bayesian, sample size)
- ✅ `engineering/` populated (5 models: FMA, redundancy, blast radius, defence-in-depth, Pareto)
- ✅ `systems/` populated (5 models: feedback loops, stocks/flows, leverage points, unintended consequences, ToC)
- ✅ `biology/` populated (5 models: antifragility, selection, ESS, hormesis, Red Queen)
- ✅ `game_theory/` populated (5 models: Nash, signalling, repeated games, commitment, PD)
- ✅ `physics/` populated (5 models: entropy, equilibrium, critical mass, leverage, phase transitions)
- ✅ `history/` populated (5 models: Dalio, wrong analog, base rates, Kondratieff, secular vs cyclical)
- ✅ `epistemology/` populated (4 models: calibration, intersubjective verification, falsifiability, unknown unknowns)
- ✅ `information_theory/` populated (4 models: signal/noise, Kelly, efficient-market filtration, channel capacity)
- ✅ `bias/` expanded (5 additional Kahneman/Cialdini/Taleb models — total 12)

**Total inventory after Stage B: 74 models**

### Stage B-extension (engineering domain)

- ✅ `engineering/` expanded with software-engineering principles (Tier ★★★ × 9, Tier ★★ × 7, Tier ◯ × 3)
- ✅ `engineering/` Claude-Code / agent-discipline sub-domain (7 models, all ★★★)
- ✅ Total `engineering/` = 31 (5 reliability + 26 SE/agent)
- ✅ Documented in user message 2026-05-09; honest tier discipline applied (DRY, premature-optimisation, Boy-Scout-rule explicitly tagged as ◯ contested)

**Total inventory after Stage B-extension: 100 models** — initial target reached.

### Stage C (closed 2026-05-09)

- ✅ `valuation/` populated (3 models: Peters-Taylor intangible capital ★★★, Eisfeldt-Papanikolaou organisation capital ★★★, Bessembinder extreme winners ★★★)
- ✅ `lifecycle/` populated (4 models: pre-discovery archetype ★★, platform-dominator archetype ★★, post-spinoff archetype ★★★, recent-IPO caution ★★)
- ✅ `meta/` populated (4 models: lollapalooza-alignment-detector ◯, man-with-hammer-warning ◯, taxonomy-of-uncertainty ★★★, model-retirement-criteria ★★)
- ✅ Placeholder `.gitkeep` files removed
- ✅ All 16 directories populated

**Total inventory after Stage C: 111 models** — all directories populated; future growth is refinement + pruning, not breadth.

### Stage D (composer skeleton + narrative wiring shipped 2026-05-09 / 2026-05-10)

- ✅ `deepdive/mental_model_composer.py` skeleton: Pydantic-typed `MentalModel`, `LatticeProfile`, `CompositionResult`; `load_lattice()` (imperative shell) + `select_models_for_dive()` (pure functional core); priority-grouped budget enforcement (core/+bias/ first, conditionals second, other always_load third)
- ✅ Selection rules per §1.5 implemented and verified across 5 profiles (INTA-style, post-spinoff, ICA-only, BEW-only, minimal)
- ✅ Loader hardening: dict-collapse shim handles YAML's hostile-to-prose colon interpretation (`{X: Y}` → `"X: Y"`) at the boundary per `parse_dont_validate`; true schema violations still fail-fast
- ✅ Data-file fixes: 3 files with outright YAML parse errors (boy_scout_rule_caveat, premature_optimisation_caveat, model_retirement_criteria) corrected — now valid YAML
- ✅ **Composer → `narrative.py` wiring (2026-05-10)**: `_lattice_profile_from_view` derives `LatticeProfile` from a `ScorecardView` (revenue, proxy data, archetype priority `post_spinoff > recent_ipo > platform_dominator > pre_discovery`, overlays-fired); `_build_lattice_block` composes + formats the selected models' Summary + Inversion form into the user prompt. System prompt updated with rule 9 referencing the ADR-023 §1.3 Block 2 reasoning order (Inversion → CoC → Moat Direction → Capital Allocator → Lunch-Eating → Probabilistic). Lattice loaded once per process via lazy module-level cache; load failures degrade gracefully (`Lattice: (unavailable)`) so a bad model file never blocks dive narrative. Lattice slugs explicitly excluded from `framework_codes` / `grounded_in` so the guard validator stays accurate. Tests in `tests/test_narrative_lattice.py` (18 cases): profile derivation across all archetype paths, section extraction, lattice-block formatting, end-to-end user-prompt integration with both real on-disk lattice and a forced-failure path.
- ✅ **Graph-integrity validator (2026-05-10)**: `validate_lattice()` in `deepdive/mental_model_composer.py` returns a Pydantic `ValidationReport` with two layers — **errors** (CI-blocking dangling references; every `related_models` slug must resolve to an existing model) and **warnings** (asymmetric edges A→B without B→A; informational only — the lattice is a directed graph by design). Baseline at landing: 0 errors, 315 asymmetries (out of 443 total edges). Asymmetry monitored via `ASYMMETRY_BUDGET = 350` in `tests/test_lattice_integrity.py` so unintentional graph degradation surfaces but reciprocity is not enforced. Two pre-existing dangling references (`founder_ceo_premium_fahlenbrach`, planned-but-never-authored slug, referenced from `core/incentive_structures.md` and `management/thorndike_outsiders_eight_traits.md`) repointed to the existing `lifecycle/platform_dominator_archetype.md` (the actual home of the Fahlenbrach founder-CEO premium discussion). Tests: 10 cases — 2 real-lattice CI guards + 8 synthetic-lattice unit tests covering reciprocal triangles, dangling refs, asymmetry warnings, no-double-counting (a dangling ref is not also reported as an asymmetry), and deterministic ordering of errors/warnings.
- 📋 Per-model regression tests asserting each model's contribution to specific narrative outputs (deferred — needs canned-LLM-response fixtures; current 18 cases cover wiring, not output-quality regression)
- 📋 Auto-generated `_index.md` from frontmatter (now feasible; deferred to follow-up)
- 📋 CLI inspection command `invest lattice show TICKER` (deferred — narrative.py is now wired so this is debugging convenience, not a blocker)
- 📋 Refinements within dense areas (volatility drag, fractional Kelly, Simpson's paradox, BIC, chaos engineering, mechanism design — see `_gaps.md` candidates)

### Stage E (deferred — user opt-in)

- 📋 Obsidian → YAML/markdown sync script
- 📋 Embedding-based semantic retrieval (only if 60+ models AND token-budget pressure forces it — currently 111 models is fine for selective rule-based composition)

### Annual review cadence

- First annual review: 2027-05 (one year after Stage A initial population)
- Process: every model with `last_reviewed` >12 months → flagged in `_index.md` for retire-or-update decision
- Retired models logged in `_gaps.md` "Retired models" section with rationale

---

## 5. References

- CLAUDE.md §ANALYTICAL PERSONALITY — pre-Stage-A canonical source (now retained as stance summary; full lattice migrated)
- ADR-023 — narrative personality spec (the runtime consumer of this lattice)
- ADR-022 — methodology disclosure (the source-provenance discipline this ADR mirrors)
- QUICK_REFERENCE.md v3.0 audit — citation-tier discipline this ADR adopts (`★★★ / ★★ / ★ / ◯`)
- Munger, *Poor Charlie's Almanack* — origin of the latticework concept
- Donella Meadows, *Thinking in Systems* — feedback loops, leverage points (candidate `lifecycle/` and `meta/` additions per `_gaps.md`)
- Taleb, *Antifragile* — antifragility, convexity (candidate biology/engineering additions per `_gaps.md`)
