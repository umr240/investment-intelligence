## What this changes, and why

<!-- The why matters more than the what; the diff already shows the what. -->

## Checks

- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check . --select F821,F811,E722` is clean (CI gates this)
- [ ] `uv run pytest -m requires_data -q` — if this touches the data layer
      (CI cannot run these; they need a populated database)
- [ ] Verified in a browser — if this touches `api/` or `frontend/`

## The non-negotiables

- [ ] No missing value is filled with a default, estimate, or guess — gaps are
      recorded as `data_gaps` entries
- [ ] No LLM call outside `deepdive/narrative.py` / `deepdive/external_signals.py`
- [ ] No raw filing text reaches a model prompt
- [ ] Public functions are annotated, return types included

## Decisions

<!-- Does this contradict anything in docs/architecture/? Say so here.
     Changing a recorded decision is a conversation, not a silent edit. -->

## New signal?

<!-- If this adds or changes a scoring signal:
     - Published source (author, year, what the paper claims)
     - What false positives it produces, and at what cost
     - Thresholds added to docs/methodology/ -->
