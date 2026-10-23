---
slug: signal_vs_noise
name: Signal vs Noise
school: shannon
citation_tier: "★★★"
always_load: true
related_models:
  - sample_size_law_of_small_numbers
  - regression_to_mean
  - probabilistic_thinking
  - first_principles
code_consequences:
  - F4 stealth framework explicitly distinguishes signal-rich indicators (Hong-Lim-Stein neglect, smart-money 13F deltas) from noise-heavy ones (analyst price targets, news sentiment)
  - F2 momentum signals weighted by window length — short-window signals are noise-dominated
  - F7 z-score thresholds calibrated against own-history noise level (z < -1.0 captures genuine signal vs reversion noise)
  - data_gaps[] discipline prevents noise-as-signal misinterpretation when inputs are missing
token_cost_estimate: 180
version: 1.0
added: 2026-05-09
last_reviewed: 2026-05-09
---

# Signal vs Noise

> Most observed variation is noise. The discipline is identifying what's signal — and weighting it accordingly.

## Summary

Claude Shannon's foundational distinction: in any communication channel, observed variation contains both genuine information (signal) and random fluctuation (noise). Translated to investment data: most short-window price moves are noise; most "indicator changes" are noise; the signal is the persistent pattern that survives noise filtering.

## When to apply

- Every framework input — is this metric signal-rich or noise-rich at the chosen frequency?
- Cross-period changes — does this change exceed noise level?
- Signal aggregation — combining noise-rich inputs produces aggregated noise, not aggregated signal
- "It's different this time" claims — usually noise; sometimes signal; statistical discipline tells which

## Inversion form

The "all signal" trap: treating every observed change as informative. Most quarter-to-quarter changes in fundamentals are noise; the multi-quarter trend is signal. Defence: filter at the frequency that matches the underlying business cycle.

## Antipatterns

- Single-quarter EPS movements treated as signal (mostly noise)
- Daily / weekly price moves treated as fundamental signal (almost entirely noise)
- "This indicator turned" without checking whether the change exceeds noise level
- Aggregating noisy indicators and calling the aggregate signal

## Examples in this codebase

- F2 momentum framework — multi-month windows filter shorter-window noise
- F7 z-scores require ≥5 years (cross-cycle history) so the z-score reflects regime-relevant signal, not single-cycle noise
- F4 academic anchors (Hong-Lim-Stein) calibrated against historical hit rates — empirically distinguishing signal from noise
- ADR-022 methodology discipline — signal/noise improves when source provenance is declared (mixed sources = noise)
