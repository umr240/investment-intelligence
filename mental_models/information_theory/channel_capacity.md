---
slug: channel_capacity
name: Channel Capacity
school: shannon
citation_tier: "★★★"
always_load: false
related_models:
  - signal_vs_noise
  - opportunity_cost
  - circle_of_competence
  - failure_pareto
code_consequences:
  - ADR-024 §1.3 mandates token_cost_estimate per mental model — composer must respect channel capacity (LLM context window)
  - ADR-023 §1.7 narrative output target ~600-1000 tokens — over-writing dilutes signal
  - Stage 0c methodology disclosure budget ~50 tokens — mandatory but channel-efficient
  - data_gaps[] discipline minimises noise in the channel (no inferred values polluting the output)
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Channel Capacity

> Every channel has finite capacity. The question is what to put in it. Pollute the channel with noise and signal arrives degraded.

## Summary

Shannon's channel-capacity theorem: every information channel can carry at most a fixed amount of information per unit time. Excess content is dropped, distorted, or arrives noisy. Translated to the LLM-narrative system: the context window is a channel; the system prompt + scorecard + mental-models are the content; over-loading degrades reasoning quality.

## When to apply

- ADR-023 prompt design — prompt + scorecard + lattice context must fit within budget while preserving signal
- ADR-024 mental-model composition — token_cost_estimate per model enables principled budget allocation
- Narrative output length — long output dilutes the signal-to-noise ratio at the human-reader level
- Cross-framework synthesis — combining too many signals saturates the analyst's own channel

## Inversion form

The under-utilisation failure: leaving channel capacity unused when it could carry signal. Defence: not every dive needs to use the full channel; matching content to need is the discipline. Sparse channels are fine; saturated channels are degraded.

## Antipatterns

- Loading every mental model into every dive (saturated channel, degraded reasoning)
- Long verbose narratives (analyst's reading channel saturates)
- Including all data_gaps even when many are irrelevant (signal lost in noise)
- Treating token budget as constraint to maximise rather than to respect

## Examples in this codebase

- ADR-024 §1.5 selection rules — composer chooses subset of lattice based on relevance, respecting channel capacity
- ADR-023 §1.7 — narrative output target 600-1000 tokens; lint warns on excess length
- Mental-model `always_load` flag separates universal context from conditional context (channel allocation)
- F1-F7 produce structured signals that compress fluent prose into typed outputs — channel-efficient by construction
