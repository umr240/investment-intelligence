# Investment Intelligence: Ralph loop state

Read first every iteration. Do the NEXT unchecked, unblocked item; update this
file last. A step that needs the owner (merge, password, decision, spend) is
marked `[U]`: write the exact ask under it, then move on. Output
`<promise>ALL UNBLOCKED TASKS DONE</promise>` only when every item is `[x]` or `[U]`.

Rules: CLAUDE.md + CLAUDE.local.md. Each implementation item ships through
`agentic-kit:ship-pr` and is merged by the loop when `merge_ready.py` says YES;
an item whose merge the owner must make is marked `[U]`. An item is ticked only after
the gate passes after the last edit and the `agentic-kit:pr-verifier` agent returns NOT
BLOCKING on its branch (pass it the spec path or item id, the branch and the gate log only; fix
or list its findings; re-run the gate). Never write real data: scratch copies
under `.e2e/`. Never print secrets. Prefer gate checks to new unit tests.

Gate: `uv run tools/gate/gate.py --workdir .e2e/gate-N --scope "<areas this loop may touch>"`

Each ticked item records, on the lines under it: DONE date, branch and commit,
gate run and result (`gate-N n/n`), verifier verdict, and anything not fixed.

No open items. Work with a spec runs from that spec's `tasks.md`.
