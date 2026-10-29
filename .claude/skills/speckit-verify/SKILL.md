---
name: "speckit-verify"
description: "Fresh-context review of an implemented feature by the pr-verifier agent; runs as the mandatory after_implement hook."
argument-hint: "Optional: PR number or branch, and the e2e gate log path"
compatibility: "Requires .claude/agents/pr-verifier.md"
metadata:
  author: "investment-intelligence"
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
session (no Anthropic API credit; never request `@claude` here).

1. Find the feature directory (`.specify/scripts/bash/check-prerequisites.sh --json`)
   and the branch (`git branch --show-current`). If the user input names a PR,
   branch or gate log, use those.
2. Run the e2e gate after the last edit if no log from after it exists
   (`docs/release/e2e_gate.py --workdir .e2e/<name>`, see memory
   e2e-gate-before-commit).
3. Spawn the `pr-verifier` agent. Pass only: the spec (the PR body, or the
   feature's `spec.md` if no PR exists yet), the branch for
   `git diff main...<branch>`, and the gate log path. Pass no reasoning,
   plan notes or task commentary from this session.
4. Post each report verbatim on the PR (`gh pr comment <N> --body-file
   <report>`). Fix each finding, re-run the tests and gate, and re-verify
   until the verdict is `NOT BLOCKING` on the head commit. A finding not fixed
   is listed in the PR body with the reason, and the owner merges that PR.
5. Report the verdict, what was fixed, and what is listed. Merging follows
   the constitution's Development Workflow rule.
