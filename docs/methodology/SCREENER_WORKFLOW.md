<!--
Specification document. This is the specification of record for the screener's staged gate ladder.

Read it as the design intent the code was built against, not as a description
of current behaviour. Where the two diverge, the code and the decision log
(docs/architecture/DECISIONS.md) are authoritative, and the divergence is
annotated inline below.
-->

# SCREENER WORKFLOW v2.1 — LAZY-LOAD ARCHITECTURE
## Investment Intelligence Project — Parameterisable Multi-Framework System
### Version 2.1 — May 2026

---

> **Core design principle: Nothing runs without explicit user instruction at each gate.**
>
> Every stage is a hard stop. The system waits. No stage auto-advances. No deep dive fires because a screener ran. No overlay fires without a prompt and confirmation. Token cost is strictly proportional to what the user explicitly requests — nothing more.
>
> **Standard disclaimer:** Research purposes only. Not financial advice.

---

## SYSTEM ARCHITECTURE — FULL LAZY-LOAD MAP

```
USER PROMPT
    │
    ▼
GATE 0a ──► Elicit 4 screener parameters
    │        HARD STOP — wait for user response
    ▼
GATE 0b ──► Elicit framework mode (A / B / C / D)
    │        HARD STOP — wait for user response
    ▼
STAGE 1 ──► Run screener → ranked table only
    │        HARD STOP — "Want tier-1 on any of these?"
    ▼
GATE 1→2 ──► User selects ticker(s) for tier-1
    │         HARD STOP — wait for explicit ticker selection
    ▼
STAGE 2 ──► Tier-1 quick deep-dive on SELECTED tickers only
    │        OVERLAY LISTENER active (passive — no tokens unless triggered)
    │        HARD STOP — "Want full tier-2 on [ticker]?"
    ▼
GATE 2→3 ──► User selects single winner + confirms framework mode
    │         HARD STOP — wait for explicit confirmation
    ▼
STAGE 3 ──► Full deep-dive — CONFIRMED ticker, CONFIRMED frameworks only
             OVERLAY LISTENER active at each framework checkpoint
             HARD STOP at each overlay trigger — prompt before running
```

**What "lazy loaded" means in practice:**

| Component | When it runs | When it does NOT run |
|---|---|---|
| Screener (Stage 1) | User triggers with explicit params + mode | Never auto-runs |
| Tier-1 deep dive (Stage 2) | User explicitly names ticker(s) after Stage 1 | Never auto-runs after screener |
| Tier-2 deep dive (Stage 3) | User explicitly names winner + confirms mode | Never auto-runs after tier-1 |
| Individual frameworks | Only frameworks in user's chosen mode | All others silently skipped |
| Diagnostic overlays | Only when trigger condition fires AND user confirms | Never by default |
| Any re-run | Only when user explicitly requests | Never on cadence without prompt |

---

## STAGE 0A — PARAMETER ELICITATION

### Elicitation prompt (verbatim)

```
Before the screener runs, confirm four parameters:

1. Region:      [default: US-listed only — NYSE / NASDAQ / NYSE American]
2. Market cap:  [default: $50M – $10B]
3. Sector:      [default: any sector]
4. Exclusion:   [default: the configured exclusion policy; `none` excludes nothing]

Say "use defaults" to proceed as-is, or specify overrides.
```

**HARD STOP. Do not proceed until user responds.**

### Parameter options

| Parameter | Default | Alternatives |
|---|---|---|
| Region | US only | US + UK/Europe · US + Developed Asia · Global incl. EM |
| Market cap | $50M – $10B | Pre-discovery $50M–$1B · Small-cap $300M–$2B · Mid-cap $2B–$20B · Custom |
| Sector | Any | Tech only · Healthcare · Industrials/Cleantech · Consumer · Custom |
| Exclusion policy | `EXCLUSION_POLICY` (default `none`) | Any registered policy (`screener/policies/README.md`) |

---

## STAGE 0B — FRAMEWORK MODE SELECTION

### Elicitation prompt (verbatim)

```
Choose framework mode before scoring runs:

A) Tier-1 only    — F1, F2, F3 (★★★ top-journal peer-reviewed only)
B) Tier-1 + Tier-2 — F1 through F5 (full academic universe — default)
C) All 7           — includes F6 v2 (practitioner-heavy) + F7 (contested)
D) Custom          — specify your own subset and weights

Reply A / B / C / D, or specify subset (e.g. "F1, F3, F4 only, equal weight").
```

**HARD STOP. Do not proceed until user responds.**

### Mode reference

| Mode | Frameworks | Max score | Best for |
|---|---|---|---|
| A | F1, F2, F3 | 30 | Highest-confidence allocation decisions |
| B | F1–F5 | 50 | Default — full academic, excludes heuristic-heavy F6/F7 |
| C | F1–F7 | 70 | SaaS-heavy screens; macro timing context |
| D | User-specified | Variable | Custom thesis |

**Disclose mode used in every output header. No exceptions.**

---

## STAGE 1 — SCREENER EXECUTION

Runs only after both Stage 0a and 0b are confirmed. Produces a ranked table. Nothing else.

### Stage 1a — Hard gates (mode-agnostic, always apply)

Hard gates disqualify; soft gates move a ticker to the flagged tier, still
ranked (`screener/gates.py`, `docs/architecture/SCREENER_PIPELINE.md` §5).

1. **G1 Exclusion policy** (hard) — the active policy's rule; `none` passes everything
2. **G2 Market cap** (hard) — present, within the requested range
3. **G3 Analyst coverage** (soft) — at least one covering analyst
4. **G4 Asset growth** — decile 10 hard, decile 9 soft (Cooper-Gulen-Schill)
5. **G5 External financing** — severe issuance hard, mild soft
6. **G6 Piotroski subset ≥ 3** (soft)
7. **G7 Momentum decile ≥ 2** (soft)

### Stage 1b — Framework proxy scoring (mode-dependent)

Score only the frameworks in the user's chosen mode. Each framework 0–10.

#### F1 — Pre-Discovery Alpha (0–10) ★★★

| Signal | Source | Points |
|---|---|---|
| Piotroski simplified: ROA>0, OCF>0, low accruals, GM expanding | 10-K/10-Q XBRL | 0–2 |
| 3+ insider open-market buys in last 90 days | OpenInsider / Form 4 | 0–3 |
| ≤5 sell-side analysts | Yahoo Finance / TipRanks (use lowest) | 0–2 |
| GP/A in sector top 40% | Computed from 10-K | 0–2 |
| No material equity or debt raise in last 12 months | EDGAR S-1/S-3 | 0–1 |

#### F2 — Momentum + Mean Reversion (0–10) ★★★

| Signal | Source | Points |
|---|---|---|
| 6–12 month price momentum top decile | Yahoo Finance | 0–3 |
| Within 5–10% of 52-week high (George-Hwang) | Yahoo Finance | 0–2 |
| Valuation below 10yr median P/E or P/S | Macrotrends / Koyfin | 0–2 |
| 12-month momentum still positive | StockAnalysis | 0–2 |
| Market cap >$300M (liquidity floor) | Yahoo Finance | 0–1 |

#### F3 — Innovation Compounder (0–10) ★★★

| Signal | Source | Points |
|---|---|---|
| Gross margin expansion ≥200bps/year over 2 years | 10-K comparatives | 0–2 |
| R&D/Revenue 15–35% | 10-K | 0–2 |
| Patents granted / product launches / contract wins | USPTO + press releases | 0–2 |
| ≥2 consecutive quarterly revenue beats | Zacks / StockAnalysis | 0–2 |
| Rising forward estimates last 90 days | Refinitiv / Zacks | 0–2 |

#### F4 — Stealth Accumulation (0–10) ★★★/◯

| Signal | Source | Points |
|---|---|---|
| Short interest declining >8% → <5% over 2–3 quarters | FINRA bi-monthly | 0–2 |
| 13F institutional holder count +10% over 3 quarters | WhaleWisdom / Fintel | 0–2 |
| Sequential quarterly EPS acceleration | 10-Q comparatives | 0–2 |
| Revenue beat consensus 2+ quarters | StockAnalysis | 0–2 |
| Options put/call declining or O/S ratio low vs peers | CBOE / Market Chameleon | 0–2 |

#### F5 — Growth Quality + Capital Allocation (0–10) ★★/◯

| Signal | Source | Points |
|---|---|---|
| Revenue CAGR >10% (3yr) | 10-K | 0–1 |
| FCF margin >20% | 10-K cash flow | 0–2 |
| ROIC >15% or GP/A top 40% (★★★ proxy) | Computed | 0–2 |
| Debt/EBITDA <2.0x | 10-K | 0–1 |
| Buyback yield 2–5% | Cash flow statement | 0–1 |
| CEO tenure 5+ yrs OR founder-CEO >5% equity | DEF 14A | 0–3 |

#### F6 v2 — Platform Dominator (0–10) ★★/◯ — Mode C only

Academic anchors (60% of score):

| Signal | Source | Points |
|---|---|---|
| Founder-CEO >5% equity (Fahlenbrach) | DEF 14A | 0–2 |
| Customer concentration mature >3yr (Patatoukas) | 10-K | 0–2 |
| GP/A sector top 40% (Novy-Marx) | Computed | 0–2 |

Practitioner confirmations ◯ (40% of score — flagged heuristic):

| Signal | Source | Points |
|---|---|---|
| Recurring revenue >70% or NRR >110% | 10-K MD&A / IR | 0–1 |
| Rule of 40 ≥35 | Computed | 0–1 |
| GRR >90% or net churn low | 10-K / IR | 0–1 |
| Network effects / switching costs / regulatory lock-in | Business model analysis | 0–1 |

#### F7 — Smart Beta Timing (0–10) ★★/◯ — Mode C only; contested

| Signal | Source | Points |
|---|---|---|
| Sector EV/Rev z-score <−1.0 vs 20yr history | Bloomberg / Macrotrends | 0–3 |
| P/B z-score <−1.0 vs 20yr history | Macrotrends | 0–2 |
| Peer-relative valuation in cheapest quartile | StockAnalysis | 0–2 |
| Mean-reversion setup vs broader market | Computed | 0–3 |

**Always append to F7 output:** *"F7 rests on contested academic ground — Arnott (pro-timing) vs Asness/AQR (anti-timing). Score weighted at 0.10 maximum."*

### Stage 1c — Qualifier thresholds

| Mode | Max | Deep-dive tier | Watch | Bench |
|---|---|---|---|---|
| A (max 30) | 30 | ≥20 | 16–19 | <16 |
| B (max 50) | 50 | ≥33 | 27–32 | <27 |
| C (max 70) | 70 | ≥47 | 38–46 | <38 |
| D (custom) | Variable | ≥65% | 50–64% | <50% |

### Stage 1 output format

1. **Header** — mode used, parameters, date, data quality caveats
2. **Universe funnel** — count at each gate
3. **Ranked table** — all names above bench threshold, sorted descending by total score
4. **Tier segregation** — Clean tier (all gates passed) vs Flagged tier (⚠ gate trip)
5. **Non-obvious pattern observation** — 1–2 sentences on what the top 5 share

### Stage 1 stop prompt

```
[N] names cleared the deep-dive threshold.

Want tier-1 analysis on any of these?
Default shortlist: top 5 from clean tier.

Name the tickers you want, or say "top 5" to use the default.
Say "done" to stop here.
```

**HARD STOP. Nothing proceeds until user responds.**

---

## STAGE 2 — TIER-1 QUICK DEEP-DIVE

Runs **only on the tickers the user explicitly named.** Never auto-runs on the full shortlist.

### Framework selection for tier-1 (by archetype)

| Candidate archetype | Mode A | Mode B/C |
|---|---|---|
| Pre-discovery / small-cap quality | F1 + F2 | F1 + F2 |
| Innovation-stage, R&D-heavy | F3 + F2 | F3 + F2 |
| Mature compounder, FCF positive | F1 + F2 | F5 + F2 |
| Platform / SaaS | F1 + F2 | F5 + F6 v2 (if Mode C) |

Mode A always restricts tier-1 to F1, F2, F3 regardless of archetype.

### Overlay listener — passive, no token cost

During tier-1 execution the overlay detector runs silently. If a trigger condition fires:

```
⚡ [OVERLAY NAME] TRIGGER FIRED
Condition: [specific trigger ID and numbers]

[1-sentence explanation of what's potentially distorted]

Run the overlay? ~[X] additional analysis steps. Y/N?
```

**HARD STOP on overlay prompt. Proceed with tier-1 output regardless of overlay decision.**

### Tier-1 output per ticker

1. Company snapshot (ticker, cap, exchange, IPO, sector, strategic state)
2. Framework 1 scorecard (varies by archetype — see above)
3. Framework 2 scorecard (F2 momentum signals + 52-week-high overlay)
4. Composite tier-1 verdict: **Strong fit / Partial / Fail**

### Cross-ticker comparison table

Single table across all tier-1 tickers: Revenue CAGR, FCF margin, R&D %, ROIC/GP/A, Debt/EBITDA, 12m return, % below 52wk high, EV/S vs median, tier-1 scores.

### Stage 2 stop prompt

```
Tier-1 complete. Strongest fit: [TICKER] — [1-sentence rationale].

Want the full tier-2 deep-dive on [TICKER]?
Alternatives: [TICKER2], [TICKER3].

Say "go [TICKER]" or redirect. Say "done" to stop here.
```

**HARD STOP. Nothing proceeds until user responds.**

---

## STAGE 3 — TIER-2 FULL DEEP-DIVE

Runs only on the **single ticker the user explicitly confirmed.** Uses only the **frameworks in the user's confirmed mode.**

### Stage 3a — Mode re-confirmation

```
Tier-2 deep-dive for [TICKER].

You used Mode [X] at the screener. Same mode for tier-2, or different?

Reply "same" or specify new mode (A / B / C / D / custom subset).
```

**HARD STOP. Do not proceed until confirmed.**

### Stage 3b — Framework execution

Execute each framework in the confirmed mode, in order (F1 → F2 → F3 → ...). After each framework:

- Check the combined trigger decision table (see DIAGNOSTIC_OVERLAYS_v1.md)
- If a trigger fires → overlay prompt → HARD STOP → continue regardless of user decision
- If no trigger → proceed silently to next framework

**Framework scorecards:**

Each framework executed in full per the specifications in QUICK_REFERENCE_v3.md. No shortcuts, no skips within a chosen framework.

| Framework | Sections required |
|---|---|
| F1 | Piotroski 9-signal table · insider cluster check · analyst coverage · Sloan accruals · GP/A · external financing flag · asset growth decile |
| F2 | 6mo + 12mo return · PEAD pattern · 52-week-high overlay · EV/S vs since-IPO median · entry/hold/exit verdict |
| F3 | GM expansion trajectory · R&D intensity · EMI (if patent data available) · revenue surprise streak · estimate revision trend |
| F4 | Short interest trajectory · 13F holder count with conviction filter · earnings acceleration · options O/S ratio |
| F5 | 6-criterion scorecard · CEO track record narrative · ICA overlay trigger check |
| F6 v2 | Academic anchors first (Fahlenbrach + Patatoukas + GP/A) → then practitioner heuristics clearly flagged ◯ |
| F7 | Z-scores with Arnott vs Asness disclaimer · skip explicitly if <36 months history with PSA trigger check |

### Stage 3c — Universal disqualification check

Run all 7 regardless of mode:

| Check | Criterion |
|---|---|
| ❌ | Heavy external financing — top 2 deciles equity issuance (Bradshaw-Richardson-Sloan ★★) |
| ❌ | Asset growth top 2 deciles (Cooper-Gulen-Schill ★★★) |
| ❌ | Negative gross profitability at scale (Novy-Marx ★★★) |
| ❌ | Zero insider ownership (Lakonishok-Lee caveat ★★★) |
| ❌ | Market cap <$300M — F2 liquidity floor |
| ❌ | Material weakness in ICFR |
| ❌ | Negative gross margin — terminal exclusion |

### Stage 3d — Composite score

Compute weighted composite using mode's stage weights (per QUICK_REFERENCE_v3.md).

| Threshold | Verdict |
|---|---|
| ≥7.0 | Initiate |
| 5.0–6.9 | Watchlist — specify entry triggers |
| 3.0–4.9 | Monitor |
| <3.0 | Exclude |

Always append: *"Mode [X] verdict. Mode [Y] sensitivity: [estimated direction of change if different mode applied]."*

### Stage 3e — Required sections

1. Extended company snapshot
2. Mode disclosure header
3. Framework scorecards (F1 → Fn per mode)
4. Overlay outputs (appended inline to relevant framework sections — only if run)
5. Universal disqualification check
6. Composite score table
7. Bull case / Bear case / Risk matrix
8. Entry triggers + stop-loss indicators
9. Data transparency log (SEC accession numbers, explicit data gaps, price as-of date)
10. Exclusion-policy status, with the reason, when a policy is active

---

## DIAGNOSTIC OVERLAYS — INTEGRATION SUMMARY

Full specifications in DIAGNOSTIC_OVERLAYS_v1.md. Summary for workflow reference:

| Overlay | Fires after | Key trigger | Token cost |
|---|---|---|---|
| ICA (Intangible Capital Adjustment) | F5 ROIC check | ROIC <15% + R&D ≥10% or innovation sector | ~600–900 |
| PSA (Post-Spinoff Alpha) | F1 Piotroski | Demerger/spinoff <36 months OR distorted comparatives | ~700–1,000 |
| BEW (Bessembinder Extreme Winners) | F3+F6 cross-check or F7 | Strong innovation + expensive by conventional metrics | ~500–800 |

**Overlay rules:**
- Never auto-run. Always prompt.
- Bundle multiple triggers into one prompt.
- Overlay output appends to relevant framework section — no new section created.
- Composite score is NOT recalculated. Overlay verdict noted qualitatively.
- If user declines: log *"[Overlay] not run — user declined. Manual verification recommended."*

---

## TOKEN COST PROFILE

| Stage | Runs when | Approx. token cost |
|---|---|---|
| Stage 0a + 0b elicitation | Every session | ~100–200 |
| Stage 1 screener | User confirms params + mode | ~1,500–3,000 |
| Stage 2 tier-1 (per ticker) | User names ticker | ~800–1,500 per ticker |
| Stage 3 tier-2 (Mode A) | User confirms winner | ~4,000–6,000 |
| Stage 3 tier-2 (Mode B) | User confirms winner | ~6,000–9,000 |
| Stage 3 tier-2 (Mode C) | User confirms winner | ~8,000–12,000 |
| ICA overlay | User confirms trigger | ~600–900 |
| PSA overlay | User confirms trigger | ~700–1,000 |
| BEW overlay | User confirms trigger | ~500–800 |
| **Full session, Mode C, all overlays** | Every gate confirmed | **~15,000–20,000** |
| **Full session, Mode A, no overlays** | Every gate confirmed | **~6,000–10,000** |

---

## RE-RUN CADENCE

Screener re-runs are **never automatic.** User must explicitly trigger them.

| Suggested trigger | Action |
|---|---|
| Mid-May 2026 (post Q1 filings) | User triggers full re-run |
| Mid-August 2026 (post Q2 filings) | User triggers full re-run |
| Mid-November 2026 (post Q3 filings) | User triggers full re-run |
| Mid-March 2027 (post Q4/10-K) | User triggers annual re-run |
| Mid-quarter | User triggers short-interest + 13F refresh only (no re-scoring) |
| Ad-hoc | User-identified catalyst, sector rotation, macro regime shift |

---

## KNOWN LIMITATIONS

1. **$50M–$1B band** — OpenInsider, WhaleWisdom, analyst counts, short interest data degrade. Scores carry ±1pt uncertainty per framework.
2. **Piotroski (F1) needs 2yr comparable financials** — recent IPOs cannot be cleanly scored. PSA overlay corrects for spinoff-specific distortions.
3. **Exclusion verdicts are rule outputs, not certifications** — a policy reports what its rules matched.
4. **F6 v2 academic anchors translate imperfectly to non-SaaS** — substitute recurring-revenue %, installed-base lock-in, or regulatory spec-in for NRR/GRR.
5. **F2 (Momentum) requires 1+ year price history** — recent IPOs cannot be cleanly scored on 12-month momentum.
6. **F7 requires 10–20yr history** — skip explicitly for recent companies. PSA trigger likely fires simultaneously.
7. **Multiple-testing problem** — combining signals raises significance bar. Per Harvey-Liu-Zhu (2016), t >3.0 needed under multiple testing.
8. **Bessembinder (BEW) is retrospective** — the 7-point characteristic checklist is an operationalisation of descriptive findings, not a prospective formula with academically validated thresholds.
9. **McLean-Pontiff decay applies to all frameworks** — realistic net alpha is 2–5% over a decade-plus horizon. 15%+ claims are not supportable.
10. **Mode A is statistically purest but narrowest** — may miss true positives that Mode B/C catch.

---

## STANDARD DISCLAIMERS

- Research purposes only. Not investment advice.
- All signals academic-peer-reviewed or practitioner-validated; tier marker (★★★/★★/★/◯) shown for each.
- Realistic net alpha is 2–5% over decade-plus horizons after McLean-Pontiff decay.

---

## VERSION HISTORY

| Version | Date | Changes |
|---|---|---|
| 1.0 | April 2026 | Initial parameterisable workflow. Three-stage structure. Old framework numbering. |
| 2.0 | May 2026 | Framework numbering updated to v3 merit order. Stage 0b mode selection added. Citation tier markers. Replication crisis disclosed. |
| **2.1** | **May 2026** | **Lazy-load architecture made the explicit central design principle. Hard stops formalised at every gate. Token cost profile added. Diagnostic overlays integrated inline. Stage 3 framework execution table added. Re-run cadence made user-triggered only.** |

---

*Workflow designed so token cost is strictly proportional to what the user explicitly requests. Nothing auto-advances. Not financial advice.*
