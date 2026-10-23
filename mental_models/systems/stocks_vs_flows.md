---
slug: stocks_vs_flows
name: Stocks vs Flows
school: forrester_meadows
citation_tier: "★★"
always_load: true
related_models:
  - second_order_thinking
  - feedback_loops
  - compounding
  - moat_direction
code_consequences:
  - Peters-Taylor capitalisation (ADR-021) explicitly converts intangible *flows* (R&D expense, SG&A) into *stocks* (knowledge capital, organisation capital)
  - F1 / F5 frameworks separate level metrics (ROIC, GP/A — flows over stocks) from quality of the underlying stocks (total_assets, total_equity)
  - F6 vs F5 distinction: F5 measures current-year flows, F6 measures stock-quality (concentration, founder-CEO ownership)
  - DCF intrinsic value = stock derived from discounted projected flows
token_cost_estimate: 200
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Stocks vs Flows

> A great year is a flow. A great business is a stock. Don't confuse them.

## Summary

Systems-thinking distinction: stocks are accumulations (assets, capital, brand equity, customer base), flows are rates of change (revenue, cash flow, customer acquisition rate). One year's flows update the stock by a small percentage; the stock determines next year's flows. Confusing the two produces flow-extrapolation errors.

## When to apply

- Every "great year" — was it a flow event or did it materially change the stock?
- ROIC analysis — ROIC is a flow ratio; quality is the stock (durability of the moat producing the flow)
- DCF — intrinsic value is the stock derived from projected flows + terminal value
- Brand / customer-relationship analysis — these are stocks built by years of marketing flow

## Inversion form

The flow-extrapolation failure: extrapolating a great year's flows into a permanent stock change. HIMS' 2025 had outstanding flow performance (revenue +59%, NI flipped positive) but the underlying stock (asset base) ballooned +205% — the flow-to-stock ratio actually deteriorated.

## Antipatterns

- "Revenue grew 50% YoY" treated as moat evidence — moat is a stock; the growth is a flow
- DCF anchored on one year's free cash flow without sensitivity on the stock that produced it
- Customer-acquisition rate treated as recurring without examining the customer-base stock retention
- Treating one quarter's stock change as the new normal

## Examples in this codebase

- ADR-021 Peters-Taylor capitalisation — explicit stock construction from flow series (R&D, SG&A perpetual inventories)
- F1 ROIC = NI flow / IC stock — ratio captures the relationship; framework separates the two
- HIMS dive: F5=8.5 (flow strength: NI $128M, FCF positive) but F1=3.0 fail (stock concerns: dilution, asset growth)
- Tier 1 ROIC volatility filter measures the stock-level durability of the flow
