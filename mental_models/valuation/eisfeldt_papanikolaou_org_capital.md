---
slug: eisfeldt_papanikolaou_org_capital
name: Eisfeldt-Papanikolaou Organisation Capital
school: eisfeldt_papanikolaou
citation_tier: "★★★"
always_load: false
related_models:
  - intangible_capital_peters_taylor
  - first_principles
  - moat_direction
  - selection_pressure
code_consequences:
  - Operational as the OC-only fallback in `screener/tasks/fundamentals.py:compute_pt_adjusted_full` when R&D is undisclosed
  - Stage 0c methodology panel declares "Non-GAAP ROIC: Eisfeldt-Papanikolaou OC-only (R&D not disclosed)" when the degraded mode applies
  - HIMS case (no XBRL R&D tag) triggers this model rather than failing the methodology entirely
  - Cross-references Peters-Taylor — these are co-anchors of the broader intangible-capital literature
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Eisfeldt-Papanikolaou Organisation Capital

> Eisfeldt & Papanikolaou (2013 JF ★★★): capitalise SG&A as organisational capital — distinct from R&D-derived knowledge capital. Useful when R&D doesn't exist as a separate line.

## Summary

Companion paper to Peters-Taylor (2017). Where Peters-Taylor focuses on capitalising R&D + 25% of SG&A, Eisfeldt-Papanikolaou's earlier work establishes that organisational capital (the durable economic value of internal processes, customer relationships, brand, accumulated coordination capacity) is partially captured by SG&A perpetual-inventory accounting. Particularly relevant for marketing-led or relationship-led businesses where R&D is minimal.

## When to apply

- Every business that doesn't tag R&D as a separate XBRL fact (HIMS-style consumer telehealth, marketing-led DTC)
- Every analysis where SG&A intensity is high but R&D is low — OC is the dominant intangible component
- As fallback when Peters-Taylor's full mode is unavailable due to data gaps
- Cross-checking Peters-Taylor — when both apply, the OC component should match between modes

## Inversion form

What does ignoring OC cost? Treating SG&A purely as operating expense when a meaningful fraction is capital-like investment in customer relationships and brand. For marketing-led businesses (HIMS at 39% marketing intensity), this is the dominant intangible capital — ignoring it produces ROIC that looks better than reality (numerator unchanged, denominator missing the marketing-built brand asset).

## Antipatterns

- Treating SG&A as 100% expense regardless of capitalisable fraction (the 25% rule is the academic anchor)
- Using OC-only when R&D IS disclosed (Peters-Taylor full mode is more complete)
- Capitalising SG&A but not declaring the methodology (ADR-022 violation)
- Ignoring direction of OC accumulation across periods

## Examples in this codebase

- `screener/tasks/fundamentals.py:compute_pt_adjusted_full` — degraded `mode='oc_only'` path explicitly invokes this anchor
- HIMS dive: ROIC GAAP 18.63% → OC-only 4.57% (Δ -14.06pp downward) — capitalising marketing-built OC reveals true economic ROIC well below GAAP appearance
- Stage 0c panel declares "OC-only — R&D not disclosed" when the degraded path applies, with Eisfeldt-Papanikolaou citation
