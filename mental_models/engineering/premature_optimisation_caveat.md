---
slug: premature_optimisation_caveat
name: '"Premature Optimisation Is the Root of All Evil" — With Caveats'
school: knuth
citation_tier: "◯"
always_load: false
related_models:
  - yagni
  - rule_of_three
  - margin_of_safety
  - boundaries_hexagonal
code_consequences:
  - Performance choices that ARE structural (lazy loading per CLAUDE.md, accession-level caching, year-coverage gate) are deliberate up-front design — not "premature"
  - Micro-optimisations (comprehension vs loop, list vs generator) deferred until profiling shows they matter
  - Composite scoring uses simple stage weights, not pre-optimised vectorised matrix math — sufficient at the universe scale we operate at
  - Profile-then-optimise discipline: when a screener pass takes too long, profile first, identify the actual bottleneck, then optimise narrowly
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# "Premature Optimisation Is the Root of All Evil" — With Caveats

> Knuth's actual quote was specific to *small, local optimisations* — not architectural decisions. Frequently weaponised against legitimate up-front design. The full quote: "We should forget about small efficiencies, say about 97% of the time: premature optimization is the root of all evil. Yet we should not pass up our opportunities in that critical 3%."

## Summary

The aphorism is widely truncated to "premature optimisation is bad" and used to dismiss any performance consideration in design. The full Knuth quote is more nuanced: he was specifically warning against *micro-optimisation of small bits of code* without profiling — not against thinking about architectural performance. Architectural decisions (caching strategy, lazy loading, data structure choice) are upstream of the "premature optimisation" warning.

## When to apply

- Micro-optimisations (comprehension vs loop, list vs generator, dict vs ordered dict) — defer until profiling shows it matters
- Compiler-level tricks before measuring — defer
- "Performance" abstractions that complicate code before evidence of bottleneck — defer
- BUT: structural performance (caching, indexing, lazy evaluation, batched I/O) is design, not optimisation

## Inversion form

What does the over-application of "no premature optimisation" cost? Architectural decisions made without considering performance produce systems that hit walls at the wrong scale. Knuth wasn't saying "ignore performance"; he was saying "don't micro-optimise locals without measuring." The misuse is treating any performance thought as forbidden, which produces designs that fall over at production scale.

## Antipatterns

- Truncating the quote to "premature optimisation is the root of all evil" and using it to dismiss performance discussion
- Architectural choices that ignore Big-O at the design layer (treating "I'll profile later" as license to write quadratic algorithms over millions of rows)
- Performance theatre: micro-optimising a function that's never the bottleneck
- Conversely: complex caching layers added before the source proves slow

## Examples in this codebase

- Lazy-load architecture (CLAUDE.md core principle) — *structural* performance design, not premature
- Year-coverage gate in `data/pipeline.py` — avoids redundant SEC fetches; structural, not micro
- Accession-level cache in `FinancialSourceLog` — structural, addresses a known SEC rate-limit + bandwidth concern
- Counter-example to watch for: any "let me make this faster" without first profiling and identifying the actual bottleneck. Composite scoring at universe scale (hundreds of tickers) is fast enough; vectorising it would be premature
