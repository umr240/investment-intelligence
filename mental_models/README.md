# Mental Models Library

> Canonical lattice for the Investment Intelligence System. Every analytical decision — what data to fetch, what test to write, what signal to surface, what verdict to issue — is reasoned through this lattice. See **ADR-024** for the architecture decision.

## What this directory is

A graph of mental models, one file per model, each with structured frontmatter and prose body. The graph (not any single model) is the analytical instrument. The eventual narrative LLM in `deepdive/narrative.py` (Phase 6) composes context by selecting subsets of this directory based on company profile, framework results, and overlay state.

CLAUDE.md §ANALYTICAL PERSONALITY holds the *stance* (owner-operator, lattice-first reasoning, mandatory inversion). This directory holds the *content* of the lattice itself.

## Directory layout

| Subdirectory | Loaded when | Examples |
|---|---|---|
| `core/` | **Always** — foundation of every dive | inversion, owner-operator stance, margin of safety, compounding |
| `moat/` | Company has revenue (i.e. real business to evaluate) | Munger-Dorsey 5 sources, Helmer 7 Powers, moat direction |
| `management/` | DEF 14A / proxy ownership data present | Thorndike Outsiders 8 traits, founder-CEO premium |
| `bias/` | **Always** — guardrails against systemic misjudgement | confirmation, anchoring, recency, motivated reasoning |
| `valuation/` | Overlay-conditional (ICA / PSA / BEW fired) | Peters-Taylor intangible capital, Bessembinder extreme winners |
| `lifecycle/` | Stage-conditional based on framework archetype | pre-discovery, platform dominator, post-spinoff |
| `meta/` | Models *about* models | lollapalooza alignment, man-with-hammer warning |

## File schema

Every model file is markdown with YAML frontmatter. Mandatory fields enforced by ADR-024 §1.3:

```markdown
---
slug: <unique_machine_id>            # snake_case, basis for related_models cross-refs
name: <Human Title>
school: <discipline>                 # munger, helmer, thorndike, kahneman, taleb, etc.
citation_tier: "★★★ | ★★ | ★ | ◯"   # see Citation Tiers below
always_load: true | false            # unconditional vs selectable
related_models:                      # ≥2 entries; the lattice is a graph
  - <slug>
  - <slug>
code_consequences:                   # non-empty; what this changes in framework/overlay/test design
  - "<consequence>"
token_cost_estimate: <int>           # composer needs this for budget enforcement
version: 1.0
added: YYYY-MM-DD
last_reviewed: YYYY-MM-DD
---

# <Name>

> Optional epigraph / quote.

## Summary
2-3 sentences. The model in the smallest possible form.

## When to apply
- Bullets describing trigger conditions

## Inversion form
What does failing this model look like? What is its mirror image?
This section is **mandatory** — a model without an inversion form is half-loaded.

## Antipatterns
- Failure modes
- Bloat warnings

## Examples in this codebase
- `path/to/file.py:function_name` — concrete code teeth
```

## Citation tiers

Mirror of `QUICK_REFERENCE.md v3.0` discipline. Be honest about epistemic status — overstating tier is worse than admitting `◯`.

| Tier | Meaning | Example |
|---|---|---|
| `★★★` | Peer-reviewed academic alpha source | Piotroski (2000), Patatoukas (2012), Peters-Taylor (2017) |
| `★★` | Strong empirical or industry-validated | Kahneman biases, Helmer 7 Powers in practice |
| `★` | Heuristic with practitioner consensus | Rule of 40, NRR ≥ 110% |
| `◯` | Qualitative lens, not return-prediction evidence | Thorndike Outsiders 8 traits, Munger lattice principles |

The Munger lattice itself is `◯` — these are reasoning tools, not alpha citations. Don't grade-inflate.

## How to add a new model

1. **Pick the right subdirectory.** Default to `core/` only if `always_load: true`. Otherwise place by domain.
2. **Write the file.** Use the schema above. Every mandatory field, every mandatory body section.
3. **Fill `inversion_form` first, before the summary.** ADR-024 §1.6 — half-loaded models are rejected.
4. **Fill `code_consequences`.** If empty after honest effort, the model isn't ready — add it to `_gaps.md` as a candidate instead. A model with no code teeth is a quote, not a model.
5. **Cross-link.** `related_models` needs ≥2 entries that *exist*. Update those models' `related_models` to point back if appropriate (the lattice is a directed graph but symmetric edges are common).
6. **Update `_index.md`.** Add the new entry. (When tooling exists, this will be auto-generated.)
7. **Update `_gaps.md`.** Remove what's now filled.

## How to retire a model

Annual review process per ADR-024 §1.6. Any model with `last_reviewed` more than 12 months old is a candidate for:

- **Update** — refresh `last_reviewed`, add new examples, sharpen the inversion form
- **Retire** — delete the file, log retirement in `_gaps.md` under "Retired models"
- **Demote** — drop `always_load` from `true` to `false` if the model has narrowed in applicability

A model that has not changed any framework / overlay / test / output decision in 12 months is failing its `code_consequences` claim and should be reviewed for retirement.

## Anti-bloat reminders

Quality over count. Munger's man-with-a-hammer applies recursively to mental-model libraries.

- Don't split a single concept into trivially related sub-models to inflate count
- Don't elevate every quote to a model
- Don't grade-inflate citation tiers
- Don't leave `related_models` empty (the graph IS the value)
- Don't paste the same model into both `core/` and `bias/` (canonical location only; cross-link instead)

The aspirational target of 100+ models is a function of *coverage breadth* (psychology, economics, biology, physics, engineering, history, epistemology, game theory, statistics, information theory, systems thinking — see `_gaps.md`), not of cosmetic count.
