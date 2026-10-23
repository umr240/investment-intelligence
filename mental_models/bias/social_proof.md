---
slug: social_proof
name: Social Proof
school: cialdini
citation_tier: "★★"
always_load: true
related_models:
  - authority_bias
  - confirmation_bias
  - liking_loving_tendency
  - efficient_market_filtration
code_consequences:
  - F4 stealth framework rewards LOW analyst coverage (Hong-Lim-Stein neglect premium) — explicitly inverts social-proof bias
  - F4 13F institutional ownership signal interpreted carefully — accumulation BEFORE consensus is signal; herd-following accumulation is noise
  - F7 contestedness flagged because cheapness consensus often reflects social proof rather than analytical edge
  - Cross-framework decision matrix flags single-framework strong_fit when the framework reflects current market consensus
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Social Proof

> When uncertain, people look to others' actions. In markets, this produces herding. The discipline is recognising when "everyone agrees" is a signal vs noise.

## Summary

Robert Cialdini's term for the influence of others' behaviour on our own decision-making, especially under uncertainty. In market contexts: when many investors hold the same view, individual investors anchor on the consensus rather than independently verifying. Often this is rational (consensus reflects aggregate information); sometimes it produces costly herding.

## When to apply

- Every "consensus" reference — is the consensus reflecting analytical signal or social proof?
- Institutional-ownership analysis — accumulation before consensus is signal; piling-in after consensus is herding
- Sector "everyone is buying" patterns — late-stage social-proof cascades produce poor entries
- Cross-checking analyst recommendations — high-coverage names with consensus buy ratings face social-proof contamination

## Inversion form

The "always contrarian" trap: assuming consensus is always wrong. Often consensus is right. Defence: contrarian-by-default is as bad as consensus-by-default. The discipline is independent verification — does the analysis support the consensus, or am I just inheriting it?

## Antipatterns

- "Everyone is bullish" treated as evidence (positive or negative) without independent analysis
- High-coverage names anchored on consensus targets
- Treating institutional ownership levels as binary ("smart money likes / doesn't like")
- Ignoring that consensus can be both right and over-priced

## Examples in this codebase

- F4 Hong-Lim-Stein neglect premium explicitly rewards low-coverage names — inversion of social proof
- F7 contestedness flag — cheapness signals can reflect social-proof discount rather than fundamental opportunity
- Composite scoring is independent of consensus — even if every analyst rates a name "buy", composite reflects framework outputs only
- ADR-022 source-provenance discipline anchors analysis to primary data, not aggregated consensus
