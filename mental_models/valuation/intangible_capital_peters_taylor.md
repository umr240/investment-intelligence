---
slug: intangible_capital_peters_taylor
name: Intangible Capital (Peters-Taylor)
school: peters_taylor
citation_tier: "★★★"
always_load: false
related_models:
  - eisfeldt_papanikolaou_org_capital
  - first_principles
  - moat_direction
  - second_order_thinking
code_consequences:
  - Operational in `overlays/ica.py:run_ica` and `screener/tasks/fundamentals.py:compute_pt_adjusted_full`
  - ADR-021 selects this methodology over management non-GAAP add-backs (no SBC, no restructuring add-backs)
  - ICA-5 trigger fires when |Peters-Taylor non-GAAP ROIC − GAAP ROIC| ≥ 3pp
  - Stage 0c methodology disclosure declares this model on every dive (ADR-022)
  - Degraded mode: Eisfeldt-Papanikolaou OC-only when R&D undisclosed (HIMS case)
token_cost_estimate: 240
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Intangible Capital (Peters-Taylor)

> Peters & Taylor (2017 JFE ★★★): capitalise R&D + 25% of SG&A as off-balance-sheet intangible assets. Adjusts the ROIC denominator for capital that GAAP expenses immediately.

## Summary

GAAP expenses R&D and SG&A immediately, despite both creating durable economic capital (knowledge capital, organisational capital). For intangible-heavy businesses (SaaS, biotech, semiconductors), this systematically distorts ROIC — denominator omits the largest economic asset. Peters-Taylor reconstructs the intangible asset stack via perpetual-inventory accounting and produces an economic ROIC that includes it.

## When to apply

- Every R&D-intensive business — GAAP under-states capital efficiency
- Every SaaS / consumer-internet name with high SG&A intensity (organisational capital component)
- Cross-period analysis — direction of the GAAP↔Peters-Taylor gap is itself signal
- Dive narrative — must declare which methodology applies (Stage 0c per ADR-022)

## Inversion form

What does NOT apply Peters-Taylor cost? GAAP-only ROIC over-states capital efficiency for asset-heavy traditional businesses (where book invested capital is mostly economically real) AND under-states it for intangible-heavy modern businesses. The directional asymmetry across business types invalidates cross-company comparisons unless the methodology is consistent. Peters-Taylor restores comparability.

## Antipatterns

- Adding back SBC, restructuring, acquisition costs (that's management non-GAAP — ADR-021 §0 explicitly rejects)
- Applying Peters-Taylor without declaring it (mixing GAAP and non-GAAP without disclosure)
- Treating capitalised R&D as cash (it's an accounting adjustment, not a flow change)
- Comparing Peters-Taylor ROIC of one company to GAAP ROIC of another (apples to oranges)

## Examples in this codebase

- `screener/tasks/fundamentals.py:compute_pt_adjusted_full` — perpetual-inventory implementation; KC at 15%/yr depreciation, OC at 20%/yr
- ADR-021 — methodology decision (Peters-Taylor over management non-GAAP)
- INTA dive: GAAP ROIC -3.36% → Peters-Taylor 5.31% (+8.67pp upward); model captures the capital reinvestment story
- HIMS dive: degrades to Eisfeldt-Papanikolaou OC-only because HIMS doesn't tag R&D in XBRL
- AMBA dive: GAAP -12.47% → Peters-Taylor +2.00% (+14.47pp upward); even after capitalisation, ROIC is still well below 15% target — the adjustment magnitude is large but the absolute level is not investable
