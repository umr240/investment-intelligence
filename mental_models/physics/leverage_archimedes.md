---
slug: leverage_archimedes
name: Leverage (Archimedes / Buffett)
school: archimedes_buffett
citation_tier: "★★"
always_load: false
related_models:
  - margin_of_safety
  - antifragility
  - commitment_devices
  - blast_radius
code_consequences:
  - F5 debt/EBITDA banding (healthy ≤2x, acceptable ≤4x) explicitly bounds leverage influence
  - Tier 1 Recession Stress Test (ICR ≥ 4.0x) — leverage that survives stress
  - Outsiders trait #6 distinguishes strategic episodic leverage (good use of Archimedean lever) from chronic crutch leverage (fragility)
  - HIMS dive flagged $1.12B convertible debt as concentrated leverage at presumed peak — wrong-direction Archimedean use
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Leverage (Archimedes / Buffett)

> *"Give me a lever long enough... and I'll move the world."* — Archimedes. Leverage amplifies. The question is what you're amplifying — and in which direction.

## Summary

Physics: a lever multiplies force. Finance: leverage multiplies return — and loss. Buffett's distinction: financial leverage (debt) is conventional and most-discussed; insurance float is leverage without due-date stress; reputation is leverage that compounds for free over decades. Operating leverage (high fixed cost, low variable cost) is leverage applied to revenue scaling.

## When to apply

- Capital-structure analysis — what kind of leverage is this, and in which direction does it amplify?
- DCF analysis — operating leverage (fixed/variable cost mix) determines the EBIT response to revenue changes
- Recession-stress analysis — leverage that strengthens under stress (insurance float) vs leverage that fragilises (callable debt)
- Outsiders trait #6 — episodic strategic leverage = good Archimedean use; chronic crutch = bad

## Inversion form

The "borrowed strength" trap: leverage that magnifies in good times also magnifies in bad. Most leverage looks great until it doesn't. Defence: leverage discipline = is the lever bidirectional, and is the system robust to amplification of losses?

## Antipatterns

- Issuing debt at peak rates / multiples (locking in expensive capital cost into a fragile period)
- Operating leverage amplifying revenue declines under recession-stress
- "Float" claimed without checking quality of underlying business (insurance float without underwriting discipline = leverage on losses)
- Confusing leverage with scale — they are different

## Examples in this codebase

- F5 debt/EBITDA banding — bounded leverage influence
- Tier 1 ICR ≥ 4.0x — operating earnings must cover interest under stress
- DCF DOL (degree of operating leverage) calculation — operating-leverage measure
- HIMS dive: total_debt $1.12B = leverage applied at presumed peak; failed Outsiders trait #6 (chronic, not episodic; misaligned with cyclical timing)
