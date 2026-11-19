## What this changes, and why

<!-- The why matters more than the what; the diff already shows the what. -->

## Verification

- [ ] Gate run after the last edit: `uv run tools/gate/gate.py --workdir .e2e/gate-N` → n/n
- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check . --select F821,F811,E722` is clean (CI gates this)
- [ ] `uv run pytest -m requires_data -q` — if this touches the data layer
      (CI cannot run these; they need a populated database)
- [ ] Verified in a browser — if this touches `api/` or `frontend/`
- [ ] `pr-verifier` verdict: NOT BLOCKING (findings fixed, or listed below with the reason)

## The non-negotiables

- [ ] No missing value is filled with a default, estimate, or guess — gaps are
      recorded as `data_gaps` entries
- [ ] No LLM call outside the sites allow-listed in `tests/test_llm_call_sites.py`
- [ ] No new path sends raw filing text to a model prompt (`/external-signals` is the one documented exception)
- [ ] Public functions are annotated, return types included
- [ ] No new dependency without naming it and why
- [ ] No secret, machine path or local data file added

## Decisions

<!-- Does this contradict anything in docs/architecture/? Say so here.
     Changing a recorded decision is a conversation, not a silent edit. -->

## Inversion

<!-- How could this change be wrong while every check passes? -->

## New signal?

<!-- If this adds or changes a scoring signal:
     - Published source (author, year, what the paper claims)
     - What false positives it produces, and at what cost
     - Thresholds added to docs/methodology/ -->

## Verifier findings not fixed

<!-- finding: reason -->
