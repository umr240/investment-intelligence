---
name: "speckit-handoff"
description: "After tasks are generated, ask whether to implement them now or hand them to an unattended Ralph loop; runs as the optional after_tasks hook."
compatibility: "Spec Kit after_tasks hook (agentic-kit ADR 005)"
metadata:
  author: "agentic-kit"
  source: ".specify/extensions.yml hooks.after_tasks"
user-invocable: true
disable-model-invocation: false
---

## Outline

Ask the owner, with the task count from `tasks.md`:

- **Implement now** in this session with `/speckit-implement`, or
- **Run unattended** with `/agentic-kit:ralph-tasks <spec dir>`, which drives
  this spec's `tasks.md` directly; the owner starts the loop.

Never start the loop without the owner's answer (CLAUDE.md, "Ralph only when asked").
