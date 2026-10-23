# ADR-043 — Currency-Correct Cost of Capital + Market-Cap Normalisation

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. Evidence below is measured, not projected. |
| **Phase** | Valuation / data integrity |
| **Extends** | ADR-041 (jurisdiction routing + ESEF — the ADR that created this hole), ADR-027 (Damodaran DCF), ADR-042 (Greenwald ladder, shares the WACC), ADR-033 (source hierarchy) |
| **Resolves** | Three silent-wrong-answer defects that all trace to one root cause: ADR-041 admitted non-USD issuers into the system without propagating **currency** into the valuation layer. |
| **Provenance** | User cross-checked BONEX.ST against valueinvesting.io on 2026-08-17. Their WACC 6.3% vs our 8.87% forced the investigation. |

---

## 1. Context — what ADR-041 broke and did not notice

ADR-041 unlocked ~17 EU/EEA jurisdictions. Every one of them reports in a
non-USD currency. The valuation layer was written when every ticker was a US
SEC filer reporting USD, and it still assumes that. Three consequences,
all measured on BONEX.ST (Nasdaq Stockholm, reports SEK):

### 1.1 `companies.market_cap_usd` holds native currency

```
BONEX.ST   market_cap_usd = 14,564,058,112   currency = SEK
NVDA       market_cap_usd =  5,453,600,260,096   currency = USD
```

The column name asserts USD. The value is SEK. True USD cap is ≈ **1.53bn**
at ~9.5 SEK/USD — a **9.5× overstatement**.

This is the worst class of bug in this codebase: not a missing value that
surfaces as a `data_gap`, but a **present, plausible, wrong** value under a
name that guarantees it will be trusted. It silently disarms every
USD-denominated threshold, including the **$300m liquidity floor** (Universal
Disqualifier 5). A genuinely SEK 2.85bn Swedish micro-cap renders as
"$2.85B" and clears a floor it fails by a factor of three.

The UI compounds it by formatting with a `$` sign, but the wrongness is in
the **stored value**, not the template. Fixing the template alone would
leave the threshold broken and the display merely honest about a wrong number.

### 1.2 The risk-free rate has no currency branch

```
compute_wacc("BONEX.ST"):
  risk_free_rate            0.0463      ← US 10yr Treasury
  mature_market_erp         0.0428
  industry_beta_unlevered   0.99
  marginal_tax_rate         0.25
  country                   n/a
  wacc                      0.0887

cost_of_capital.py mentions 'SEK'              : False
cost_of_capital.py has a currency branch on rf : False
risk_free_rate.json "currency"                 : "USD"
```

We discount **SEK** cash flows at a **USD** risk-free rate. Damodaran is
explicit and unambiguous that the risk-free rate must be denominated in the
currency of the cash flows — this is not a refinement, it is the first
consistency check in his framework. Swedish 10yr government yield is ~2.5–3.0%
(valueinvesting.io's range), so we overstate `rf` by **~170–210bps** and every
discounted value for every ESEF ticker inherits it.

Note the uncomfortable ordering: the 2026-08-16 reference refresh made
`risk_free_rate.json` *accurate* while leaving it *single-currency*. Accuracy
without applicability. The file even declares `"currency": "USD"` — the
information needed to catch this was sitting in the payload, unread.

### 1.3 Country is never resolved, so tax and CRP fall back to defaults

`country` came out `n/a`, therefore:

- `marginal_tax_rate` = **0.25** default, not Sweden's **20.6%**
- `country_risk_premium` = **0.0** by *default*, not because Sweden was
  identified as Aaa/CRP-0.0

The second is right by accident. A Turkish or Brazilian issuer would receive
CRP 0.0 on the same code path — a **silent under-statement of risk** for
exactly the markets where country risk matters.

The galling part: `country_erp.json`, refreshed on 2026-08-16, contains
`Sweden: {country_risk_premium_pct: 0.0, corporate_tax_rate_pct: 20.6}`, and
`jurisdiction_for("BONEX.ST").country` returns `"SE"`. **Both the data and the
resolver exist and neither is wired to the WACC.**

### 1.4 Adjacent, same root: industry beta mapped by sector alone

`industry_beta_unlevered = 0.99` = Damodaran's "Heathcare Information and
Technology". BONESUPPORT makes bone-graft substitute — `Company.industry` is
"Medical Instruments & Supplies", which maps to **"Healthcare Products"
(0.83)**. `_SECTOR_TO_DAMODARAN_INDUSTRY` keys on `sector` only, so every
healthcare name in the universe gets the healthcare-IT beta.

Included here because it pushes WACC the same direction as §1.2–1.3 and
because fixing WACC while leaving beta mis-mapped would produce a number that
is *differently* wrong.

### 1.5 Combined effect, and the external check

| | Ours | valueinvesting.io |
|---|---|---|
| Risk-free | 4.63% (USD) | 2.5–3.0% (SEK govt) |
| Beta | 0.99 (healthcare IT) | 0.55–0.61 (adjusted) |
| Tax | 25% | 20.35% |
| **WACC** | **8.87%** | **6.3%** |

Three errors, all one direction, ~257bps of WACC. On a
terminal-value-dominated DCF that is not a rounding difference.

**A caution against reading the EPV agreement as validation.** Our Greenwald
recent-regime EPV (35.06 SEK) sits 1.2% from theirs (35.47 SEK). That is a
coincidence of offsetting errors, not corroboration: our normalised earnings
are ~172 SEK m against their 117, discounted at 8.87% against their 6.3%. The
two differences very nearly cancel. **Fixing WACC will move our EPV away from
theirs**, and that is expected. Anyone who cites the current agreement as
evidence the engine is calibrated has been misled by an artefact.

What the cross-check *does* validate is ADR-042's applicability gate: their
EPV lands near our **recent-regime** figure and nowhere near our full-history
figure (−8.22 SEK). An independent implementation, normalising differently,
landed in the regime the gate selects.

---

## 2. Decision

Treat **currency as a first-class attribute of every monetary value and every
rate**, resolved from the jurisdiction registry that already knows it.

### 2.1 Market cap — store both, name both honestly

```sql
ALTER TABLE companies ADD COLUMN market_cap_native REAL;      -- as reported
ALTER TABLE companies ADD COLUMN market_cap_currency TEXT;    -- ISO-4217
-- market_cap_usd RETAINED, redefined to mean what its name says:
--   market_cap_usd = market_cap_native × fx_rate_to_usd
```

`Financial.fx_rate_to_usd` already exists (ADR-039 migration) and is populated
for BONEX.ST (0.10504). The conversion input is present; only the write path
is missing.

Backfill is a **data correction**, not a destructive migration: it rewrites
`market_cap_usd` only for rows where `currency != 'USD'`, and those values are
currently wrong by construction. USD rows are untouched. Per CLAUDE.md the
additive columns are Claude Code's job; **the backfill UPDATE is surfaced for
sign-off** because it rewrites existing rows.

Thresholds (liquidity floor, market-cap banding, stage classification) must
read `market_cap_usd` and **fail closed** — if `fx_rate_to_usd` is NULL for a
non-USD filer, the threshold emits a `data_gap` and the disqualifier does not
silently pass.

### 2.2 Risk-free rate — one file, many currencies

`risk_free_rate.json` becomes a map:

```json
{
  "rates_by_currency": {
    "USD": {"pct": 4.63, "snapshot_date": "2026-08-13", "series": "FRED DGS10"},
    "SEK": {"pct": 2.  , "snapshot_date": "...",        "series": "..."},
    "EUR": {"pct":  ... },
    "..." : {}
  }
}
```

Sourcing, in preference order, extended in `scripts/refresh_damodaran_reference.py`:

1. **FRED OECD long-term government bond yields** (`IRLTLT01*M156N` family)
   — one series per country, same public CSV endpoint already in use.
2. **Damodaran's own fallback** where no reliable sovereign bond exists:
   `rf_currency = rf_USD + (expected inflation differential)`.

The exact FRED series IDs are **not asserted here**; the refresh script must
resolve and validate them, and **fail loudly** on a 404 rather than falling
back to USD. A silent fallback to USD would recreate this bug with a
provenance trail that says it was fixed.

`compute_wacc` gains a `reporting_currency` parameter, defaulted from
`Company.currency`. **No currency → refuse, do not default to USD.**

### 2.3 Country resolution — wire the registry that already exists

```python
jur = jurisdiction_for(ticker)          # already returns country="SE"
country_name = ISO2_TO_DAMODARAN[jur.country]   # "SE" -> "Sweden"
```

Then `marginal_tax_rate` and `country_risk_premium` come from
`country_erp.json` lookups keyed on that name. An **unmapped country is a
`data_gap`, never a default of 0.0** — that is the specific failure that makes
§1.3 dangerous for emerging markets.

### 2.4 Industry beta — key on industry, fall back to sector

Add an `INDUSTRY_TO_DAMODARAN` map consulted before the sector map, so
"Medical Instruments & Supplies" → "Healthcare Products". Sector remains the
fallback, and the resolved Damodaran row plus its `mapping` confidence
(exact / renamed / approximate, per ADR-042's refresh script) is recorded on
the WACC result so a reader can audit which beta was used and how confident
the correspondence is.

### 2.5 Guardrails — the tests that would have caught all of this

`tests/test_valuation/test_currency_integrity.py`:

1. For every persisted company: `currency != 'USD'` ⇒ `market_cap_usd !=
   market_cap_native` (i.e. a conversion actually happened).
2. `compute_wacc` on a non-USD filer uses a risk-free rate whose declared
   currency equals the filer's reporting currency.
3. A ticker whose country cannot be resolved produces a `data_gap` and does
   **not** silently receive `CRP = 0.0` or a default tax rate.
4. `market_cap_usd` for a known non-USD ticker is within a sane band of
   `native × fx` (guards the direction of the multiplication — dividing by
   0.105 instead of multiplying is the obvious next bug).

### 2.6 What this ADR does NOT decide

- **No FX time series.** One current rate per currency, as today. Historical
  FX for period-accurate conversion is a separate concern and `yagni` until a
  cross-currency comparison actually needs it.
- **No change to the reporting currency of outputs.** Per-share values stay in
  the filer's currency (BONEX in SEK). Only USD *thresholds* convert. Mixing
  presentation currencies is a worse failure than this one.
- **No re-derivation of Damodaran's ERP per currency.** The implied ERP stays
  the US/mature-market premium plus CRP, which is his own construction.

---

## 3. Inversion (mandatory)

| Forward | Inversion | Mitigation |
|---|---|---|
| Currency-correct rf fixes the discount rate. | What if the per-currency rate is missing or stale? | Refuse and gap. Never fall back to USD — that is precisely the current bug wearing a fix's clothes. |
| Converting market cap fixes the thresholds. | What if the conversion runs the wrong way? | 9.5× vs 0.105× is a 90× error and visually obvious; test #4 pins the direction with a band assertion. |
| Resolving country fixes tax + CRP. | What if the ISO2→Damodaran name map is incomplete? | Unmapped ⇒ `data_gap`, not default. An incomplete map degrades to "we don't know", which is a valid system answer. |
| Fixing WACC improves every valuation. | What breaks downstream? | Every persisted IV changes, and our EPV moves AWAY from valueinvesting.io's. §1.5 states why that is correct rather than a regression. |
| These are all currency bugs. | Is currency really the root cause, or is it "US-only assumptions" more broadly? | Broader. Form 4 / short-interest gaps (ADR-041) are the same family. This ADR fixes the monetary subset; the disclosure subset is separate and named as out of scope. |

---

## 4. Alternatives considered

- **Alt 1 — fix the `$` label only.** Rejected: the stored value is wrong, so
  the threshold stays broken and the display becomes honestly wrong.
- **Alt 2 — convert everything to USD at ingestion.** Rejected: destroys the
  filing-grade native figures ADR-041 worked to obtain, and per-share values
  in a currency the filer never reported are harder to audit against the
  annual report.
- **Alt 3 — one global WACC per jurisdiction.** Rejected: discards
  company-specific beta and leverage, which is most of what WACC is for.
- **Alt 4 — defer until more non-USD names are in the universe.** Rejected:
  the bug is silent, so waiting means accumulating wrong persisted valuations
  that nobody flags. Silent-wrong is exactly the class that should not wait.

---

## 5. Consequences

| File | Change |
|---|---|
| `alembic/versions/*` | `market_cap_native`, `market_cap_currency` (additive) + backfill (sign-off) |
| `data/reference/damodaran/risk_free_rate.json` | multi-currency shape |
| `scripts/refresh_damodaran_reference.py` | fetch per-currency sovereign yields; fail loudly |
| `valuation/damodaran/cost_of_capital.py` | `reporting_currency` param; country resolution; industry-first beta |
| `data/pipeline.py` | write native + converted market cap |
| `screener/gates.py` (thresholds) | read USD, fail closed on missing FX |
| `tests/test_valuation/test_currency_integrity.py` | the four assertions in §2.5 |

**Expected effect:** every non-USD ticker's WACC falls (BONEX ~8.87% → ~6.5%),
so intrinsic values rise and franchise ratios move. **All persisted non-USD
valuations should be treated as void until recomputed.** US tickers are
unaffected — a property worth asserting in the test suite rather than assuming.

**Known limits after this ADR:** single current FX rate (no historical
conversion) · ERP remains US-derived + CRP · the disclosure-side US
assumptions (Form 4, short interest) remain open.

## 6. References

- ADR-041 §"Known limits" — this is the hole that section did not anticipate
- ADR-042 §2.3 — Greenwald shares this WACC, so it inherits every fix here
- `data/reference/damodaran/INDEX.md` 2026-08-16 refresh log — the accuracy-without-applicability precedent
- valueinvesting.io BONEX.ST WACC / EPV / DCF pages, retrieved 2026-08-17
- `mental_models/`: `first_principles`, `single_source_of_truth`, `fail_fast`, `illegal_states_unrepresentable`

---

*ADR-043 | The Boardroom Lab | 2026-08-17 | **PROPOSED — not ratified***

*The common thread is not "currency" but a category error: a value that is
present, plausible and wrong is more dangerous than one that is absent. This
codebase is unusually disciplined about missing data — `data_gaps[]` is a
first-class output, frameworks refuse rather than default. It had no equivalent
discipline for values that arrive in the wrong units, because until ADR-041
every value arrived in the same units. The fix is to make units as
unrepresentable-when-wrong as missingness already is.*
