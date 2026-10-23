<!--
Specification document. This is the specification of record for the three diagnostic overlays (ICA / PSA / BEW) and their trigger conditions.

Read it as the design intent the code was built against, not as a description
of current behaviour. Where the two diverge, the code and the decision log
(docs/architecture/DECISIONS.md) are authoritative, and the divergence is
annotated inline below.
-->

# DIAGNOSTIC OVERLAYS — v1.0
## Investment Intelligence Project — Conditional Analytical Tools
### Version 1.0 — May 2026

---

> **Purpose:** Three lazy-loaded diagnostic overlays that fire only when specific anomaly conditions are detected during a deep-dive or screener run. These are NOT frameworks. They do not add to the composite score. They exist to interrogate specific misfires in the main 7-framework system — preventing false negatives caused by GAAP distortion, corporate structure discontinuity, or conventional-valuation bias.
>
> **Token discipline:** Overlays are never run by default. Zero token cost unless a trigger fires. Claude prompts the user before running any overlay — the user confirms before analysis begins.
>
> **Academic basis:** All three are anchored in ★★★ peer-reviewed work. See citation details below.

---

## TRIGGER ARCHITECTURE

```
DEEP-DIVE / SCREENER RUN
         │
         ▼
   ANOMALY DETECTOR  ────► No anomaly detected → proceed normally, zero overlay cost
         │
         ▼ (anomaly detected)
   PROMPT USER: "I've detected [condition]. Want me to run [overlay]?
                 It'll add ~[X] analysis steps. Y/N?"
         │
         ▼ (user confirms)
   RUN OVERLAY → output appended to relevant framework section
         │
         ▼
   REVISED VERDICT issued (if overlay changes the read)
```

**Rules:**
1. Never auto-run. Always prompt first.
2. One prompt per trigger, not per framework section.
3. If multiple triggers fire simultaneously, bundle into one prompt.
4. Overlay output appends to the most relevant existing framework section — it does not create a new section.
5. If user declines, log: *"[Overlay name] not run — user declined. Manual verification recommended."*

---

## OVERLAY 1 — INTANGIBLE CAPITAL ADJUSTMENT (ICA)

### Academic foundation

| Paper | Tier | Finding |
|---|---|---|
| Peters & Taylor (2017) "Intangible Capital and the Investment-q Relation" *Journal of Financial Economics* | ★★★ | Capitalising R&D (15%/yr depreciation) and SG&A organisational capital (20–30%) produces an intangible-adjusted q that dramatically outperforms standard Tobin's q |
| Eisfeldt & Papanikolaou (2013) "Organization Capital and the Cross-Section of Expected Returns" *Journal of Finance* | ★★★ | Firms with high organisational capital (SG&A-derived) earn ~5% annual premium; capital is non-transferable to shareholders → systematically underpriced |
| Lev & Sougiannis (1996) "The Capitalization, Amortization, and Value-Relevance of R&D" *Journal of Accounting & Economics* | ★★ | GAAP R&D expensing systematically understates book value and overstates ROIC deterioration in innovation-intensive firms |

### What it fixes

GAAP mandates immediate R&D expensing. This overstates economic losses, understates book equity, and makes ROIC appear negative or suppressed for companies that are actually compounding intellectual capital. F5's ROIC >15% threshold will mechanically fail most SaaS, biotech, and deep-tech companies not because the economics are bad — but because GAAP accounting makes them look bad.

### Trigger conditions (any one fires the prompt)

| ID | Condition | Where detected |
|---|---|---|
| ICA-1 | F5 ROIC fails (<15%) AND R&D intensity ≥10% of revenue | F5 scorecard |
| ICA-2 | F5 ROIC fails AND sector is: SaaS, biotech, semiconductors, deep-tech, pharma | F5 scorecard |
| ICA-3 | GAAP net loss reported AND OCF is strongly positive (OCF/GAAP loss ratio >2x) | F1 Sloan accruals check |
| ICA-4 | Standard P/B >4x AND GP/A is in top sector tercile AND R&D intensity >15% | F6 v2 / F1 GP/A check |
| ICA-5 | User says: "valuation looks off," "ROIC seems wrong," "book value doesn't make sense" | Any point |

### Prompt template

```
⚡ ICA TRIGGER FIRED
Condition: [state which ICA-X fired and the specific numbers]

GAAP is likely distorting [TICKER]'s ROIC/book value because of R&D expensing.
Want me to run an Intangible Capital Adjustment?

I'll: (1) capitalise cumulative R&D at 15%/yr depreciation,
     (2) add 25% of cumulative SG&A as organisational capital,
     (3) recompute adjusted ROIC and P/B.

~3 additional analysis steps. Y/N?
```

### Analysis procedure (run only if user confirms)

**Step 1 — Build intangible asset stack**

```
R&D Capital (Knowledge Capital):
  Year t:   KK_t = (1 − 0.15) × KK_(t−1) + R&D_t
  Initialise: KK_0 = R&D_0 / (g + 0.15), where g = revenue CAGR

Organisational Capital:
  OC_t = (1 − 0.20) × OC_(t−1) + 0.25 × SG&A_t
  Initialise: OC_0 = 0.25 × SG&A_0 / (g + 0.20)

Total Intangible Asset Stack = KK_t + OC_t
```

**Step 2 — Adjust book equity and ROIC**

```
Adjusted Book Equity = Reported Book Equity + KK_t + OC_t

Adjusted NOPAT = Reported NOPAT + R&D_t − Amortisation of KK_t
               = Reported NOPAT + R&D_t − (0.15 × KK_(t−1))

Adjusted ROIC = Adjusted NOPAT / (Reported Invested Capital + KK_t + OC_t)

Adjusted P/B = Market Cap / Adjusted Book Equity
```

**Step 3 — Revised F5 verdict**

Compare adjusted ROIC to the 15% threshold. State:
- Original GAAP ROIC: X%
- Adjusted Economic ROIC: Y%
- Delta: Z percentage points
- F5 ROIC verdict revised: PASS / STILL FAIL / BORDERLINE

If adjusted ROIC passes: revise F5 score upward by 1–2 points (depending on magnitude of adjustment) and note the revision explicitly.

### Output format (append to F5 section)

```
── ICA OVERLAY ──────────────────────────────────────────────
Trigger: ICA-[X] — [condition]
Knowledge Capital (cumulative R&D, 15% decay):   $XM
Organisational Capital (25% SG&A, 20% decay):    $XM
Total Intangible Stack:                           $XM

GAAP ROIC:        −X%  (F5 FAIL)
Adjusted ROIC:    +X%  (F5 [PASS/FAIL/BORDERLINE])
Adjusted P/B:      X.Xx (vs reported X.Xx)

Revised F5 ROIC read: [revised verdict + 1-sentence rationale]
── END ICA ──────────────────────────────────────────────────
```

---

## OVERLAY 2 — POST-SPINOFF ALPHA (PSA)

### Academic foundation

| Paper | Tier | Finding |
|---|---|---|
| Cusatis, Miles & Woolridge (1993) "Restructuring Through Spinoffs" *Journal of Financial Economics* | ★★★ | Spinoffs outperform market by ~25–30% over 3 years post-separation; parents by ~12–15%. Mechanism: forced selling by index funds and mandated institutions creates structural mispricing. |
| Chemmanur & Yan (2004) "A Theory of Corporate Spin-offs" *Journal of Financial Economics* | ★★★ | Spinoffs are undervalued at separation due to information asymmetry — the carve-out entity has no standalone track record and analysts must rebuild coverage from scratch |
| Desai & Jain (1999) "Firm Performance and Focus: Long-Run Stock Market Performance Following Spinoffs" *Journal of Financial Economics* | ★★★ | Focus-increasing spinoffs (parent and spinoff in different industries) earn ~33% excess return over 3 years; focus-neutral spinoffs earn ~18% |

### What it fixes

The Piotroski F-Score requires two years of comparable financials. Post-spinoff companies have discontinuous prior-year numbers — carved out from a larger parent — so YoY comparatives are meaningless or actively misleading. F1 will mechanically penalise the spinoff on signals 3, 5, 6, 8, 9 (all YoY change signals) when the prior-year comparatives reflect the consolidated parent, not the standalone entity. Similarly, F7 has no valuation history to z-score. The standard frameworks produce false negatives on exactly the companies where structural mispricing is highest.

### Trigger conditions (any one fires the prompt)

| ID | Condition | Where detected |
|---|---|---|
| PSA-1 | IPO/listing date <36 months ago AND origin was demerger, spinoff, or corporate carve-out | Company snapshot |
| PSA-2 | Prior-year financials not comparable (different entity scope disclosed in 10-K) | F1 Piotroski execution |
| PSA-3 | F7 explicitly skipped due to insufficient valuation history (<36 months) | F7 section |
| PSA-4 | F1 scores unusually low (≤4/9) BUT OCF is positive and current-year GP/A is strong | F1 scorecard |
| PSA-5 | User notes: "limited history," "just listed," "spun out from," "demerger" | Any point |

### Prompt template

```
⚡ PSA TRIGGER FIRED
Condition: [state which PSA-X fired]

[TICKER] appears to be a post-[spinoff/demerger/carve-out] entity.
Standard Piotroski and valuation history may be producing false negatives
because prior-year comparatives reflect the consolidated parent, not this
standalone business.

Want me to run a Post-Spinoff Alpha overlay?

I'll: (1) adjust Piotroski for transition-year distortions,
     (2) assess structural mispricing conditions (forced-seller overhang),
     (3) apply Desai-Jain focus test (same/different industry as parent).

~4 additional analysis steps. Y/N?
```

### Analysis procedure (run only if user confirms)

**Step 1 — Transition-year Piotroski adjustment**

Re-run F-Score with adjusted rules:
- Signals 3, 8, 9 (YoY change signals): replace prior-year comparatives with **industry median** for the sector, not the consolidated parent's financials. Flag each adjustment explicitly.
- Signals 5, 6 (leverage/liquidity YoY): replace prior year with **IPO/listing day balance sheet** (first standalone period) rather than the distorted consolidated prior.
- State: "Adjusted F-Score: X/9 (vs unadjusted X/9). Adjustment rationale: [brief explanation]."

**Step 2 — Structural mispricing assessment (4 binary checks)**

| Check | Question | Pass condition |
|---|---|---|
| PSA-A | Was parent in a different sector/index than the spinoff? | Yes → forced selling likely |
| PSA-B | Is spinoff too small for parent's institutional mandate? | Yes (if >2 size deciles smaller) → forced selling likely |
| PSA-C | Analyst coverage initiated within 12 months? | <3 analysts → information asymmetry intact |
| PSA-D | Has the spinoff been ejected from/never included in a major index? | Yes → mechanical tracker selling likely |

Score: X/4 structural mispricing conditions met. Each ✅ = one additional positive signal.

**Step 3 — Desai-Jain focus test**

- Same SIC 2-digit code (parent and spinoff): **focus-neutral** → ~18% excess return documented
- Different SIC 2-digit code: **focus-increasing** → ~33% excess return documented
- State: "[TICKER] is a [focus-neutral/focus-increasing] spinoff. Desai-Jain baseline: ~[X]% 3-year excess return documented."

### Output format (append to F1 section)

```
── PSA OVERLAY ──────────────────────────────────────────────
Trigger: PSA-[X] — [condition]
Listing date: [date] | Parent: [name] | Type: [spinoff/demerger/carve-out]
Time since separation: [X] months

Piotroski (adjusted for transition year):
  Original: X/9  →  Adjusted: X/9
  Signals revised: [list which signals, brief rationale]

Structural mispricing: X/4 conditions met
  [✅/❌] PSA-A: Forced selling (sector mismatch)
  [✅/❌] PSA-B: Forced selling (size mandate)
  [✅/❌] PSA-C: Information asymmetry (<3 analysts)
  [✅/❌] PSA-D: Index ejection / tracker selling

Focus test: [Focus-increasing / Focus-neutral]
Desai-Jain baseline: ~[X]% 3-year documented excess return

Revised F1 read: [revised verdict + 1-sentence rationale]
── END PSA ──────────────────────────────────────────────────
```

---

## OVERLAY 3 — BESSEMBINDER EXTREME WINNERS (BEW)

### Academic foundation

| Paper | Tier | Finding |
|---|---|---|
| Bessembinder (2018) "Do Stocks Outperform Treasury Bills?" *Journal of Financial Economics* | ★★★ | 4% of US-listed stocks (1926–2016) account for all net wealth creation above T-bills. Top 50 stocks = ~40% of total wealth. The other 96% collectively matched or underperformed T-bills. |
| Bessembinder, Chen, Choi & Wei (2019) "Do Global Stocks Outperform US Treasury Bills?" *Journal of Financial Economics* | ★★★ | 1.3% of global stocks account for all net wealth creation above bills. Pattern holds across 42 countries. |
| Bessembinder (2021) "Wealth Creation in the US Public Markets 1926 to 2019" *Financial Analysts Journal* | ★★ | Extreme winner characteristics: smaller at time of acquisition, higher idiosyncratic volatility, positive return skewness, growth industries, NOT conventionally cheap. |

### What it fixes

Your 7 frameworks are calibrated to find **1–3 standard deviation mispricings** and target 20–100% returns. Bessembinder shows that this approach — by construction — systematically excludes the 4% of stocks that generate the multi-bagger (10x–100x) outcomes you're targeting. Those stocks rarely look cheap by F7 metrics, often have negative GAAP ROIC (ICA issue), and frequently fail momentum screens (F2) because they experience prolonged periods of apparent overvaluation before their compounding becomes undeniable.

The BEW overlay doesn't replace the frameworks. It asks a separate question: *"Does this stock have the structural characteristics of an extreme winner, even if it looks expensive by conventional metrics?"*

### Trigger conditions (any one fires the prompt)

| ID | Condition | Where detected |
|---|---|---|
| BEW-1 | F3 (Innovation) ≥7 AND F6 (Platform) ≥7 BUT F7 z-score is expensive (>0) or stock is at/near 52-week high | Cross-framework anomaly |
| BEW-2 | Strong F1 + F3 but stock screens as "expensive" on EV/Revenue, P/S, or P/B relative to sector median | F7 / valuation check |
| BEW-3 | Stock has compounded >50% in 12 months AND user is asking whether to add or hold at current price | F2 momentum section |
| BEW-4 | User explicitly asks: "could this be a multi-bagger," "is this worth paying up for," "am I too late" | Any point |
| BEW-5 | Company is in top-decile idiosyncratic volatility AND top-tercile R&D intensity AND market cap <$2B | F3 / screener output |

### Prompt template

```
⚡ BEW TRIGGER FIRED
Condition: [state which BEW-X fired]

[TICKER] may look expensive by conventional metrics but could exhibit
characteristics of a Bessembinder extreme winner — the 4% of stocks
that historically account for all net market wealth creation.

Want me to run a Bessembinder Extreme Winners check?

I'll: (1) score [TICKER] against documented extreme-winner characteristics,
     (2) assess portfolio construction implications (concentration, hold period),
     (3) give an honest verdict on whether paying up is academically defensible.

~3 additional analysis steps. Y/N?
```

### Analysis procedure (run only if user confirms)

**Step 1 — Extreme winner characteristics score (7 binary checks)**

From Bessembinder (2018, 2021):

| Check | Characteristic | Threshold | Read |
|---|---|---|---|
| BEW-A | Smaller at time of acquisition | Market cap <$2B at analysis date | ✅/❌ |
| BEW-B | High idiosyncratic volatility | Annualised idiosyncratic vol >30% (residual from market beta) | ✅/❌ |
| BEW-C | Positive return skewness | Return distribution positively skewed (prior 3yr monthly returns) | ✅/❌ |
| BEW-D | Growth industry | Sector: technology, healthcare, consumer discretionary, industrials (tech sub-sector) | ✅/❌ |
| BEW-E | Not conventionally cheap | EV/Revenue > sector median at analysis date | ✅/❌ |
| BEW-F | Long runway (TAM >> current revenue) | TAM / Current Revenue ratio >20x | ✅/❌ |
| BEW-G | Innovation-compounding visible | F3 score ≥7 OR gross margin expanding ≥200bps/yr | ✅/❌ |

Score: X/7. Bessembinder characteristics present.

**Interpretation:**
- 6–7/7: Strong extreme-winner profile. Conventional valuation metrics are likely misleading — the Bessembinder framework suggests the market is repricing future compounding, not overvaluing current fundamentals.
- 4–5/7: Partial profile. Paying up is defensible only if F3 + F6 are both strong.
- 0–3/7: Conventional valuation frameworks remain appropriate. BEW does not support paying a premium.

**Step 2 — Portfolio construction implication**

State explicitly (from Bessembinder's findings):
- Holding period required: extreme winners typically take **5–15 years** to deliver their full return. Exit at 2–3x likely truncates the distribution.
- Position sizing: Bessembinder's result implies **concentration is necessary**. A 2% position in a 10x stock contributes 0.2% to portfolio returns. A 10% position contributes 1.9%.
- Diversification cost: holding 20 mediocre value stocks mathematically outperforms holding 3–4 extreme winners *only if* you correctly identify the 20 mediocre stocks. If 1–2 of your holdings are in the 4% extreme-winner cohort, concentration dominates.

**Step 3 — Honest verdict**

State one of three verdicts:

> **EXTREME WINNER CANDIDATE (X/7):** Paying above sector median multiples is academically defensible given the Bessembinder characteristic profile. The relevant risk is not overpaying — it's underweighting or exiting too early. Monitor: F3 innovation flywheel and TAM realisation progress, not near-term P/E.

> **PARTIAL PROFILE (X/7):** Conventional valuation discipline applies. BEW does not provide cover for paying a significant premium. F7 valuation z-score remains the appropriate anchor.

> **CONVENTIONAL VALUATION APPLIES (X/7):** Stock does not exhibit Bessembinder characteristics. Standard framework verdicts stand.

### Output format (append to the framework section where the trigger fired)

```
── BEW OVERLAY ──────────────────────────────────────────────
Trigger: BEW-[X] — [condition]
Bessembinder characteristics: X/7

  [✅/❌] BEW-A: Small at acquisition (<$2B)
  [✅/❌] BEW-B: High idiosyncratic volatility (>30%)
  [✅/❌] BEW-C: Positive return skewness
  [✅/❌] BEW-D: Growth industry
  [✅/❌] BEW-E: Not conventionally cheap (above sector median)
  [✅/❌] BEW-F: Long runway (TAM/Revenue >20x)
  [✅/❌] BEW-G: Innovation compounding visible (F3 ≥7)

Portfolio implication:
  Required hold period:  5–15 years (truncating at 2–3x likely suboptimal)
  Position sizing note:  [state concentration implication for this specific score]

Verdict: [EXTREME WINNER CANDIDATE / PARTIAL PROFILE / CONVENTIONAL VALUATION APPLIES]
[1–2 sentence rationale]
── END BEW ──────────────────────────────────────────────────
```

---

## COMBINED TRIGGER DECISION TABLE

For quick reference during a deep-dive — check this table after completing each framework:

| After completing... | Check for trigger | Overlay prompted |
|---|---|---|
| F1 Piotroski | PSA-1, PSA-2, PSA-4 | PSA |
| F5 ROIC criterion | ICA-1, ICA-2, ICA-3 | ICA |
| F1 GP/A + F6 v2 P/B | ICA-4 | ICA |
| F7 (or F7 skip) | PSA-3, BEW-1, BEW-2 | PSA and/or BEW |
| F2 momentum | BEW-3 | BEW |
| F3 + F6 cross-check | BEW-1, BEW-5 | BEW |
| User language anywhere | ICA-5, PSA-5, BEW-4 | As triggered |

**Multiple triggers:** If ICA and PSA both fire (e.g., a post-spinoff SaaS with negative GAAP ROIC), bundle into one prompt: *"Two overlays triggered for [TICKER]: ICA and PSA. Run both? ~6 additional analysis steps. Y/N?"*

---

## TOKEN COST ESTIMATES

| Overlay | Steps | Approx. token cost |
|---|---|---|
| ICA only | 3 steps | ~600–900 tokens |
| PSA only | 4 steps | ~700–1,000 tokens |
| BEW only | 3 steps | ~500–800 tokens |
| ICA + PSA | 7 steps | ~1,200–1,700 tokens |
| All three | 10 steps | ~1,800–2,500 tokens |
| None triggered | 0 steps | 0 tokens |

Baseline deep-dive without overlays: ~8,000–12,000 tokens.
Maximum overlay addition: ~20% overhead.

---

## INTEGRATION WITH QUICK_REFERENCE.md v3.0

These overlays sit **outside** the 7-framework composite score. They do not change framework weights. They amend individual framework verdicts where GAAP distortion, corporate structure, or valuation convention produce demonstrable false negatives.

When a revised verdict is issued, the composite score table in the deep-dive appends:

```
| Overlay adjustments applied | ICA → F5 ROIC revised | BEW → valuation premium defensible |
```

The composite score number itself is not recalculated (no scoring weight assigned to overlays). The revised framework verdict is noted qualitatively.

---

## VERSION HISTORY

| Version | Date | Changes |
|---|---|---|
| 1.0 | May 2026 | Initial release. Three overlays: ICA (Peters-Taylor), PSA (Cusatis-Desai-Jain), BEW (Bessembinder). Lazy-load trigger architecture. Token cost estimates. |

---

*Research purposes only. Not financial advice. Overlays are diagnostic tools, not scoring frameworks. All underlying papers are peer-reviewed ★★★ or ★★.*
