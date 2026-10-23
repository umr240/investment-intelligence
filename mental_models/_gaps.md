# Mental Models — Gaps & Candidates

> First-class artifact per ADR-024 §1.6. Tracks what's missing per domain so growth toward 100+ is honest about coverage breadth, not cosmetic count.

## Inventory: 114 models — initial target (100) + Stage C population (11) reached 2026-05-09; +3 engineering refinements (idempotency, tracer_bullets, root_cause_over_symptom) 2026-06-07. All 16 directories populated.

## Currently DENSE (well-populated)

- **Finance / capital allocation** — Munger lattice + Outsiders 8 traits + bias awareness (`core/`, `management/`, `bias/`)
- **Moat taxonomy** — Munger-Dorsey 5 + Helmer 7 + direction/TAM/lunch-eating refinements (`moat/`)
- **Behavioural bias** — 12 models (Munger 7 + Kahneman/Tversky/Cialdini 5) — `bias/`
- **Statistical thinking** — 5 models — `statistical/`
- **Engineering** — 34 models (6 reliability + 10 SE-foundational + 8 SE-practical + 3 SE-contested + 7 agent-discipline) — `engineering/`
- **Systems thinking** — 5 models — `systems/`
- **Biology / antifragility** — 5 models — `biology/`
- **Game theory** — 5 models — `game_theory/`
- **Physics** — 5 models — `physics/`
- **History / cycles** — 5 models — `history/`
- **Epistemology** — 4 models + `core/circle_of_competence` cross-link — `epistemology/`
- **Information theory** — 4 models — `information_theory/`

## Stage C — closed 2026-05-09

`valuation/` ✅, `lifecycle/` ✅, `meta/` ✅ — all populated. The 11 models from these directories are now in the lattice.

## Refinements within already-dense areas (candidates)

| Domain | Candidate | Why |
|---|---|---|
| Statistical | `volatility_drag` | Geometric vs arithmetic mean — directly relevant to compounding analysis |
| Statistical | `kelly_criterion_fractional` | Sub-Kelly sizing as practical default — deserves its own file separate from `kelly_criterion` |
| Statistical | `simpson_paradox` | Aggregated trends can reverse when disaggregated by group — relevant to multi-segment business analysis |
| Information theory | `bayesian_information_criterion` | Model selection under data constraint — relevant to framework weighting |
| Engineering | `chaos_engineering` | Deliberately injecting failures to verify resilience — direct map to test discipline |
| Game theory | `mechanism_design` | Engineering incentive structures — relevant to executive compensation analysis |

---

## Retired models

(Empty — no models retired yet. Annual review begins 2027-05.)

## Tracking notes

- Adding a model means **removing** the corresponding row above in the same PR. The gap list shrinks as the lattice grows.
- Quality bar applies: every candidate must satisfy ADR-024 §1.6 (mandatory `inversion_form`, non-empty `code_consequences`, ≥2 `related_models`, valid citation tier).
- All 16 directories are populated. Future growth is by selective refinement within dense areas + annual review-driven pruning, not by chasing breadth.
- The 111-model count is a snapshot. Quality dominates — annual review (begins 2027-05) will retire models that haven't earned their tokens.
