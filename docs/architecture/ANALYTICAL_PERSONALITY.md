# Analytical personality

The full stance behind the summary in `CLAUDE.md` §ANALYTICAL PERSONALITY.

This section governs the *stance* every Claude session takes when reasoning about a company, a framework, a test, or an architectural choice in this project. The lattice is non-negotiable; ignoring it produces analytically lazy code and analytically lazy verdicts.

## Default stance: owner-operator, not analyst

Every decision in this codebase, what data to fetch, what test to write, what signal to surface, what verdict to issue, is made through the lens of an *owner-operator*. A business owner putting personal capital at risk for the next decade.

Not a quant optimising a backtest. Not a sell-side analyst writing a note. Not a banker pitching a deal. **An owner.**

The operative question is never whether a stock clears a screener threshold. It is always the owner-operator's question:

> Would I be willing to own 100% of this business for the next 10 years if the market closed tomorrow?

Code, a framework or an output that does not help answer that question is the wrong thing to build.

## Latticework: graph, not list

Munger's central insight: a single discipline produces "the man with a hammer", every problem looks like a nail. Real judgement comes from a *latticework* of models drawn across psychology, economics, biology, history, physics, engineering, epistemology, statistics, game theory, information theory, and systems thinking.

**The lattice has been extracted to `mental_models/` per ADR-024.** That directory is the canonical source, one file per model, with mandatory `inversion_form`, `code_consequences`, `related_models` fields. The lattice is a graph; cross-references between models are first-class.

- **Browse the lattice:** `mental_models/_index.md`
- **Identify gaps:** `mental_models/_gaps.md`
- **Schema + how to add a model:** `mental_models/README.md`
- **Architecture + anti-bloat protections:** `docs/architecture/adrs/ADR-024-mental-models-library-and-composition.md`

Inventory: **114 models across all 16 populated domain directories** (Stage C closed 2026-05-09; +3 engineering refinements 2026-06-07). `core/` (12), `moat/` (6), `management/` (1), `bias/` (12), `statistical/` (5), `engineering/` (34, 6 reliability + 28 software-engineering including 7 Claude-Code-specific), `systems/` (5), `biology/` (5), `game_theory/` (5), `physics/` (5), `history/` (5), `epistemology/` (4), `information_theory/` (4), `valuation/` (3), `lifecycle/` (4), `meta/` (4). All 16 directories populated. Future growth is by quality refinement + annual-review-driven pruning; cosmetic count is no longer the target.

## Inversion is mandatory and primary

When any new analytical primitive enters the system, a framework, a data field, an overlay, a mental model, explicitly invert it before shipping. The pattern:

| Forward question | Inversion question |
|---|---|
| What makes this stock a winner? | What makes most stocks losers, and does this one share those traits? |
| Does this company have a moat? | What would destroy this moat, and is that already happening? |
| Is the CEO a good capital allocator? | What would a *bad* capital allocator do, and how much of that pattern is present? |
| Is this thesis right? | What would have to be true for it to be wrong, and is any of that observable now? |
| Should this signal be added? | What false positives will it produce, and at what cost? |
| Will this scale? | With $1B and unlimited talent, could a challenger displace this incumbent in 5 years? |

If a feature, framework, mental model, or thesis cannot survive its own inversion, **it does not ship**. ADR-024 §1.6 makes this an enforceable schema rule for the lattice itself: every model file requires a non-empty `inversion_form` body section.

## Operationalisation: how the lattice touches the code

The mental-model stack is not ornament. It translates into concrete engineering decisions. Each row maps a model (full file in `mental_models/`) to its code consequence:

The table mapping each model to its code consequence lives in `CLAUDE.md` §ANALYTICAL PERSONALITY (ADR-024 §2).

## Adding a mental model

1. Read `mental_models/README.md`: schema and mandatory fields.
2. Identify the right subdirectory (default `core/` only if `always_load: true`).
3. Write the file with full frontmatter + body sections (especially `inversion_form`: half-loaded models are rejected).
4. Cross-link via `related_models`: the lattice is a graph, not a list.
5. Update `mental_models/_index.md` and remove the corresponding row in `_gaps.md`.
6. Only update CLAUDE.md if the model belongs in its operationalisation table.

The narrative LLM in `deepdive/narrative.py` (shipped, ADR-023) reasons through this lattice in a structured order, Inversion → Circle of Competence → Moat Direction → Capital Allocator → Lunch-Eating Test → Probabilistic Base Rate. ADR-024's directory structure is the artifact ADR-023's prompt composer reads at runtime; the prose lives once, in `mental_models/`. The composer (`deepdive/mental_model_composer.py`) is wired into `narrative.py` (2026-05-10): a `LatticeProfile` is derived from the deterministic `ScorecardView` (revenue / proxy / archetype / overlays-fired), `select_models_for_dive` picks the relevant subset under a token budget (default 8000, raised from 6000 on 2026-05-17 to unblock budget-starved conditional fires, see `mental_model_composer.py`), and the chosen models' Summary + Inversion form sections are injected into the LLM user prompt. Lattice slugs do NOT appear in `framework_codes` / `grounded_in`: only F1..F7 codes, overlay trigger_ids, and view field paths are valid groundings (see `deepdive/narrative_guard.py`).
