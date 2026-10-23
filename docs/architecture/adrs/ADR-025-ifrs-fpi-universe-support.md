# ADR-025 — IFRS / FPI Universe Support

| Field | Detail |
|---|---|
| **Status** | **Accepted + implemented** (Phase 5W, status updated 2026-05-17). edgartools `Company.is_foreign` is the primary FPI detection signal (with 40-F/20-F filing-history fallback for redomiciliation cases like SHOP — verified). 6-K MIC parser shipped for Canadian-FPI beneficial ownership in `data/edgar_text_parser.py:parse_mic_ownership()`. IFRS taxonomy fundamentals fetch deferred — not yet blocking known target tickers. |
| **Date** | 2026-05-09 |
| **Provenance** | User intervention 2026-05-09: requested fundamentals fetch for SRAD (Sportradar Group AG, Swiss-domiciled, NASDAQ-listed). Empirical probe revealed SRAD reports XBRL exclusively in `ifrs-full` taxonomy in EUR. Our parser walks `us-gaap` only, returning zero rows. Decision: extend the SEC-XBRL data path to support IFRS taxonomy + foreign-currency conversion rather than build a parallel yfinance-driven fallback (which would violate ADR-022 §1.4 source-provenance discipline). |
| **Supersedes** | Nothing. |
| **Updates** | `data/edgar_companyfacts.py` (taxonomy walker); CLAUDE.md TECH STACK (data-source list); ADR-022 §1.4 (extends "single source" to include `ifrs-full`-tagged 20-F filings, still SEC-EDGAR-sourced). |
| **Preserves** | CLAUDE.md determinism rule; ADR-021 first-principles methodology; ADR-022 source-provenance requirements. The data path remains SEC-EDGAR-only and deterministic. |
| **Affects** | `data/edgar_companyfacts.py`, new `data/fx_rates.py` for currency conversion, `Financial` schema (adds `reporting_currency` + `original_value_native_currency` columns), screener filters for FPI inclusion. |

---

## 0. The reframe

Foreign Private Issuers (FPIs) like SRAD file 20-F annual reports with the SEC, but their XBRL is tagged in the `ifrs-full` taxonomy — different concept names, different units (typically EUR / GBP / CHF / JPY rather than USD). The data is real, public, free, and auditable; our parser just doesn't read it.

Three paths were considered (per the SRAD investigation 2026-05-09):

1. **Extend the SEC-XBRL parser** — proper fix; preserves ADR-022 source-provenance discipline; unlocks the entire 20-F universe (substantial — most European, many Asian, much of LatAm)
2. **yfinance fallback adapter for FPIs** — pragmatic; violates ADR-022 §1.4 by introducing methodology asymmetry at the row level
3. **Skip FPIs** — opportunity-cost answer; loses most of the non-US universe (European, Middle Eastern and Asian listings)

This ADR commits to **path 1**.

---

## 1. Decision

### 1.1 Taxonomy walker extension

`data/edgar_companyfacts.py:parse_companyfacts` currently reads `payload['facts']['us-gaap']` only. Extend to also read `payload['facts']['ifrs-full']` when present. The walker logic is unchanged; the input set expands.

### 1.2 Concept-mapping layer

Add `_IFRS_CONCEPTS` aliases parallel to `_INCOME_CONCEPTS` / `_BALANCE_CONCEPTS` / `_CASHFLOW_CONCEPTS`. Each `Financial` field gets an IFRS-tagged alias list. The walker tries us-gaap aliases first (most US issuers), falls back to ifrs-full aliases (FPIs). Per-row provenance: a single `Financial` row's field values must all come from the same taxonomy — no cross-taxonomy field mixing.

Initial mapping (extend per-issuer empirical needs):

| Field | us-gaap (existing) | ifrs-full (new) |
|---|---|---|
| revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues` | `Revenue`, `RevenueFromContractsWithCustomersExcludingAssessedTax` |
| cost_of_revenue | `CostOfRevenue` | `CostOfSales` |
| gross_profit | `GrossProfit` | `GrossProfit` (same name, different namespace) |
| operating_income | `OperatingIncomeLoss` | `ProfitLossFromOperatingActivities`, `OperatingProfit` |
| net_income | `NetIncomeLoss` | `ProfitLoss` |
| operating_cash_flow | `NetCashProvidedByUsedInOperatingActivities` | `CashFlowsFromUsedInOperatingActivities` |
| capex | `PaymentsToAcquirePropertyPlantAndEquipment` | `PurchaseOfPropertyPlantAndEquipment` |
| total_assets | `Assets` | `Assets` (same name, different namespace) |
| total_equity | `StockholdersEquity` | `Equity`, `EquityAttributableToOwnersOfParent` |
| long_term_debt | `LongTermDebt` + extensions (per ADR-024 history) | `NoncurrentBorrowings`, `LongTermBorrowings` |
| short_term_debt | (existing list) | `CurrentBorrowings`, `ShortTermBorrowings` |
| cash_and_equivalents | `CashAndCashEquivalentsAtCarryingValue` | `CashAndCashEquivalents` |
| rd_expense | `ResearchAndDevelopmentExpense` | `ResearchAndDevelopmentExpense` (same name) |
| sga_expense | `SellingGeneralAndAdministrativeExpense` | `GeneralAndAdministrativeExpense` + `SellingExpense` (often split in IFRS) |
| shares_outstanding | `CommonStockSharesOutstanding`, `WeightedAverageNumberOfSharesOutstandingBasic` | `NumberOfSharesIssued`, `WeightedAverageShares` |

The full mapping is iterative — start with the ~15 fields above; expand as empirical FPI coverage exposes gaps. Each new IFRS concept added to the alias list goes through ADR-024-style review (does it map cleanly? does it carry the same economic meaning?).

### 1.3 Currency normalisation

IFRS facts are tagged in the issuer's reporting currency (typically EUR / GBP / CHF / JPY for European issuers; CAD for Canadian; HKD / CNY for Asian). Two persistence requirements:

1. **`Financial.reporting_currency`** column added — explicit per-row provenance
2. **`Financial.{field}_native_currency`** is the raw XBRL value; **`Financial.{field}`** is the USD-converted value using FX rate at `period_end_date`

FX rate source: SEC EDGAR doesn't provide currency tables; use ECB historical reference rates (free, deterministic, published daily, no API key) for EUR-cross rates, with FRED as fallback for non-ECB currencies. Cache rates by date in a new `fx_rates` table to avoid repeated fetches.

Critical discipline: the *displayed* dive output uses USD-converted values for cross-company comparability, BUT the methodology disclosure panel (Stage 0c per ADR-022) declares the conversion explicitly when `reporting_currency != USD`. Source-of-record per row is preserved.

### 1.4 Schema migration

Alembic migration adds:

```sql
ALTER TABLE financial ADD COLUMN reporting_currency TEXT;          -- 'USD' / 'EUR' / 'GBP' / etc.
ALTER TABLE financial ADD COLUMN fx_rate_to_usd FLOAT;             -- rate applied at period_end_date
ALTER TABLE financial ADD COLUMN fx_rate_date DATE;                -- date the rate is from (period_end_date)

CREATE TABLE fx_rates (
    id INTEGER PRIMARY KEY,
    base_currency TEXT NOT NULL,
    rate_date DATE NOT NULL,
    rate_to_usd FLOAT NOT NULL,
    source TEXT NOT NULL,                                          -- 'ECB' / 'FRED' / 'fallback'
    fetched_at DATETIME NOT NULL,
    UNIQUE (base_currency, rate_date)
);
```

Existing `Financial` rows get `reporting_currency='USD'`, `fx_rate_to_usd=1.0` via backfill in the migration.

### 1.5 Submissions probe + form-set

`data/edgar_companyfacts.py:probe_recent_filings` already accepts forms `{'10-K', '10-K/A', '20-F', '20-F/A', '40-F'}`. Verify this is consistent with the parser's `_FUNDAMENTAL_FORMS` set; widen if needed. 40-F is Canadian and often us-gaap-tagged (some Canadian FPIs use IFRS though); 20-F is the IFRS-typical case.

### 1.6 Stage 0c methodology disclosure update

When `reporting_currency != USD`, the methodology panel (per ADR-022) prepends:

```
Source: SEC 20-F XBRL (companyfacts.json) — ifrs-full taxonomy
Reporting currency: EUR (converted to USD at €1 = $1.0843, ECB ref rate 2025-12-31)
```

This makes the methodology asymmetry visible to the reader. ICA-5 and other GAAP↔non-GAAP gap triggers continue to require *same-source* comparison — both legs from the same accession; conversion to USD doesn't change source provenance.

### 1.7 Per-issuer parsing flag

Add `Company.taxonomy: TEXT` column ('us-gaap' / 'ifrs-full' / 'mixed') populated at first parse. Speeds up the year-coverage gate (skips us-gaap probe entirely for known IFRS issuers). Mixed-taxonomy issuers (rare but exist — some Canadian FPIs co-file in both) fall through both walkers.

---

## 2. What this ADR does NOT do

- Does **not** add yfinance as a fundamentals source for FPIs. yfinance remains a price / ownership / snapshot source only (ADR-022 §1.4 stands).
- Does **not** add live FX. Conversion happens at `period_end_date` only; we don't continuously re-mark to current FX. The dive output is the company's economic state at fiscal year-end, expressed in USD via the FY-end rate.
- Does **not** support every world taxonomy. `ifrs-full` covers most non-US listings; obscure jurisdictional taxonomies (e.g. Japanese GAAP `jpcrp` extensions) are deferred to a later ADR if encountered.
- Does **not** change framework score logic. F1-F7 read from `Financial.{field}` (the USD-converted value); they don't need to know the row originated from IFRS.

---

## 3. Anti-patterns this ADR forbids

| Pattern | Why forbidden |
|---|---|
| Mixing us-gaap and ifrs-full values in a single `Financial` row's fields | Per-row provenance requirement; analytically incoherent |
| Using yfinance values to fill IFRS fields when SEC IFRS values exist | ADR-022 §1.4 — methodology asymmetry at the row level |
| Skipping currency conversion ("EUR is close to USD") | Numerical noise compounds across multi-year analyses; conversion is mechanical and cheap |
| Pulling FX rates without caching | Rate-limits fragile sources; deterministic dates → cache hits forever |
| Treating FX-converted values as identical to USD-native values for all purposes | The methodology panel must declare the conversion; ICA-5 / cross-period analyses use the conversion consistently but disclose it |
| Building a separate "FPI dive command" | The dive flow is universal; FPIs are routed through the same orchestrator with the additional currency-disclosure layer |

---

## 4. Implementation status

### Stage A (this ADR — spec only)

- ✅ ADR written
- ✅ SRAD investigation documented (catalyst for the decision)
- 📋 Alembic migration for `Financial.reporting_currency` + related columns
- 📋 `_IFRS_CONCEPTS` mapping in `data/edgar_companyfacts.py`
- 📋 `data/fx_rates.py` ECB / FRED fetcher + cache
- 📋 Stage 0c panel update for currency declaration
- 📋 Test coverage: SRAD as the canonical FPI test ticker; one Canadian (40-F) FPI as cross-jurisdiction case
- 📋 `Company.taxonomy` column + classifier

### Stage B (deferred — encountered-only)

- 📋 Other taxonomies (Japanese `jpcrp`, etc.) — add when needed
- 📋 Multi-currency reporting issuers (some Korean / Chinese filers report in both KRW and USD via XBRL extensions)
- 📋 Constant-currency framework signals — would let F1-F7 distinguish FX-driven changes from operational changes; orthogonal to this ADR

---

## 5. References

- ADR-021 — Economic ROIC adjustment (first-principles methodology this extension preserves)
- ADR-022 — Methodology disclosure (extended here to declare currency conversion + IFRS taxonomy)
- ADR-024 — Mental models library (the candidate `valuation/intangible_capital_peters_taylor.md` already needs to be IFRS-aware once IFRS coverage exists; this ADR unblocks that)
- IFRS Foundation Taxonomy — `ifrs-full` concept reference
- ECB historical reference rates — `https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/`
- SEC EDGAR companyfacts API documentation — taxonomy field returns whichever the issuer used
