---
name: "speckit-verify"
description: "Fresh-context review of an implemented feature by the pr-verifier agent; runs as the mandatory after_implement hook."
argument-hint: "Optional: PR number or branch, and the gate log path"
compatibility: "Requires the agentic-kit plugin (pr-verifier agent)"
metadata:
  author: "agentic-kit"
  source: ".specify/extensions.yml hooks.after_implement"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

## Outline

CLAUDE.md "A fresh pair of eyes before the owner's", run in this Claude Code
session.

1. Find the feature directory (`.specify/scripts/bash/check-prerequisites.sh --json`)
   and the branch (`git branch --show-current`). If the user input names a PR,
   branch or gate log, use those.
2. Run the gate after the last edit if no log from after it exists:
   `uv run tools/gate/gate.py --workdir .e2e/<name>` (the `agentic-kit:e2e-gate`
   skill).
3. Spawn the `agentic-kit:pr-verifier` agent (subagent type). Pass only: the
   feature's `spec.md` path, the branch for `git diff <main>...<branch>`, and
   the gate log path. Never the PR body. Pass no
   reasoning, plan notes or task commentary from this session.
4. Fix each finding, re-run the gate, and re-verify until the verdict is
   `NOT BLOCKING`. A finding not fixed is listed in the PR body with the
   reason. Its tag decides who merges (agentic-kit ADR 004): a tag in `gate.toml`
   `[merge] merge_on` may merge on `merge_ready` YES; any other tag, a missing
   tag or a disputed one goes to the owner.
5. Report the verdict, what was fixed, and what is listed.
