---
slug: root_cause_over_symptom
name: Root Cause over Symptom (Five Whys)
school: ohno_toyota
citation_tier: "★★"
always_load: false
related_models:
  - failure_mode_analysis
  - fail_fast
  - chestertons_fence
  - pre_mortem_before_commit
code_consequences:
  - A bug fix that adds an alias / patches a value WITHOUT asking why the wrong value was produced treats the symptom, not the cause
  - Every silent-corruption incident should produce a why-chain logged in the ADR / commit, not just a patched value
  - The fix should, where possible, make the CLASS of failure impossible (fail-loud guard) rather than fixing the single instance
  - Disqualification checks (CGS top-decile, M-Score) are root-cause guards — each was added in response to a class of false-positive, not a single bad ticker
token_cost_estimate: 180
version: 1.0
added: 2026-06-07
last_reviewed: 2026-06-07
---

# Root Cause over Symptom (Five Whys)

> Taiichi Ohno (Toyota Production System): ask "why" repeatedly until you reach the cause that, if fixed, prevents the whole class of failure — not just the instance in front of you. Patching the symptom guarantees the symptom returns wearing a different mask.

## Summary

When a failure surfaces, the cheap fix addresses what you can see (the wrong value, the crashed row). The disciplined fix asks why that was possible, and why *that* was possible, until it reaches a cause whose removal closes the whole class. This is distinct from `failure_mode_analysis` (which enumerates *what could* fail, forward-looking, before the fact) — this model is *backward-looking root-cause* once a failure has already occurred. They pair: FMA designs the guards; Five Whys is invoked when a guard was missing and something slipped through.

## When to apply

- Every bug fix — am I fixing the value, or the reason the wrong value was producible?
- Every "add another alias / add another special case" patch — is the underlying parser contract wrong such that more aliases will keep being needed?
- Every incident post-mortem — has the why-chain reached a cause that closes the class, or stopped at the convenient symptom?
- Every recurring bug — recurrence is the tell that a prior fix stopped at the symptom

## When NOT to apply

- Trivial one-off failures with no class behind them (a genuine typo) — five-whys-ing it is theatre
- When the root cause is known and external (a vendor's API changed shape) — fix the boundary, don't ritualise the chain
- Beware the chain that terminates at "human error" or "should have been more careful" — that's a non-answer; push past it to the system change that makes the error structurally harder

## Inversion form

What does symptom-fixing cost? The same failure returns through a different door. The HIMS `total_debt` bug ($148M operating-lease alias vs $1.12B real debt) was fixed by adding aliases — symptom-level. The root cause was deeper: the parser found *an* alias and returned a partial value without flagging the discrepancy (`fail_fast` notes exactly this). Five-Whys terminates not at "add the missing alias" but at "the parser should raise when it finds a suspiciously partial match" — which closes every future alias-shortfall of that class, not just HIMS. Symptom fixes accumulate as a growing alias list that never stops growing; root-cause fixes make the list-growth unnecessary.

## Antipatterns

- "Added the missing alias, done" without asking why a partial match was silently acceptable
- Why-chains that stop at the first convenient answer (usually one or two whys deep)
- Terminating at "human/agent error" instead of the system change that prevents recurrence
- Fixing N instances of a class one at a time instead of installing one guard for the class

## Examples in this codebase

- The HIMS fix shipped the alias (symptom) but `fail_fast` records the deeper lesson (parser should flag the discrepancy) — that deeper lesson IS the root cause this model demands
- Disqualification checks (CGS top-decile asset growth, M-Score) — each closes a *class* of false-positive rather than blacklisting individual tickers; root-cause guards by construction
- ADR anti-pattern lists — each documents the class of failure a decision prevents, not just the one bad instance
- Counter-example to watch for: a future "just add another concept alias" parser patch that doesn't ask whether the alias-matching contract itself needs a fail-loud guard
