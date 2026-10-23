# ADR-039 — Pluggable `FundamentalsSource` Port + SEDAR+ Adapter (Canadian issuers)

| Field | Detail |
|---|---|
| **Status** | **Accepted — Phase A + B implemented** (2026-06-06). Port + registry + resolver (`data/sources/`), SecEdgarSource wrap, YFinanceFundamentalsSource Tier-3 bridge, SedarPlusSource scaffold, `refresh_ticker` wired to `resolve_source`, schema migration `a8c9d0e1f2a3` (`companies.data_source_tier` + `financials.fx_rate_to_usd`), `watchlist add` auto-materialize, source-aware methodology panel. 19 port tests + full suite (147) green; `data/sources/` ruff + mypy-strict clean. **Validated live**: `invest dive VHI.TO --tier 2 --auto-overlays` runs F1/F2/F5 + ICA/PSA/**BEW** on yfinance Tier-3 data; F3/F4/F6/F7 degrade gracefully on ~4yr depth. Phase C (SEDAR+ Tier-1B iXBRL parser) remains deferred. |
| **Phase** | Data layer / source abstraction |
| **Supersedes** | ADR-038 §"Phase 1 design" (the `if cik else yfinance` branch in `refresh_ticker`) — replaces an inline conditional with a port/adapter seam. ADR-038's two-phase *commitment* and its honest Tier-3 caveat survive intact. |
| **Extends** | ADR-019 (plugin-source + per-task independence), ADR-022 (per-field `_source` provenance, Tier 1-4), ADR-025 (IFRS taxonomy + currency), ADR-033 (SEC-first hierarchy) |
| **Resolves** | TSX/TSX-V issuers (`.TO` / `.V`) currently fail at the Company-row level — no CIK, no fetcher path. Target: `invest dive VHI.TO` (VitalHub Corp) runs the framework engine on real Canadian fundamentals. |
| **Provenance** | User directive 2026-06-06: "Build a SEDAR+ adapter, similar to the SEC EDGAR architecture, a pluggable architecture following all the SOLID and software-engineering mental models." Scope chosen: **Phased** — port + yfinance-CA bridge now; SEDAR+ Tier-1B parser scaffolded + deferred. |

---

## 0. The non-negotiable shape (mirrors ADR-019 §0)

This ADR is only acceptable if its proposal:

1. **Adds a seam, does not rewrite EDGAR.** The existing `data/edgar_fetcher.py` path is wrapped, not reimplemented (Chesterton's Fence — `mental_models/engineering/chestertons_fence.md`). A US ticker's dive call-trace is byte-for-byte unchanged.
2. **Is closed for modification, open for extension** (Open/Closed). Adding SEDAR+ later touches *one new file* + *one registry line* — zero edits to `refresh_ticker`, frameworks, overlays, or the CLI.
3. **Inverts the dependency.** `refresh_ticker` depends on the `FundamentalsSource` *port* (an abstraction), never on a concrete fetcher. The pipeline does not know whether bytes came from SEC, SEDAR+, or yfinance (`boundaries_hexagonal` — `always_load: true`).
4. **Preserves provenance honesty.** Every `Financial.{field}_source` and `Company.data_source_tier` records the *real* origin. A Tier-3 yfinance dive of VitalHub must be visibly shallower than a Tier-1A SEC dive of NVDA — never silently equivalent.
5. **Fails into a `data_gap`, never a hallucination.** A source that can't answer returns gaps; it does not fabricate, and it does not resolve to the *wrong company* (the `VHI` → Valhi Inc collision that motivated this ADR).

If any of those is violated, scrap the proposal. This document keeps them.

---

## 1. Context

### 1.1 The triggering failure (verified 2026-06-06)

`invest dive VHI.TO` (VitalHub Corp — TSX healthcare-IT compounder, ~C$454M cap) cannot run. Empirical resolution probe:

| Ticker | EDGAR resolves to | Verdict |
|---|---|---|
| `VHI` | **VALHI INC /DE/** (CIK 59255) — US chemicals holding co. | ❌ silent **wrong-company** analysis |
| `VHI.TO` | `CompanyNotFoundError` | ❌ not an SEC filer |
| `VHIBF` (US OTC) | `CompanyNotFoundError` | ❌ not an SEC filer |
| name search `"VitalHub"` | 0 results | ❌ no SEC registration exists |

VitalHub files with **SEDAR+** (Canada), not the SEC. yfinance *does* hold the right company (`VHI.TO` → VITALHUB CORP, TOR, CAD, Healthcare / Health Information Services; price history 2021-09-23 → 2026-06-05). This is the exact gap ADR-038 named (its Table row 30 lists `VHI.TO`).

### 1.2 Why ADR-038's design is insufficient for this directive

ADR-038 (Draft, **unimplemented** — no `yfinance_fundamentals.py`, no `add_non_sec_ticker`, no `data_source_tier` column exist today) chose a pragmatic inline branch:

```python
# ADR-038 §Phase-1 design — the shape this ADR replaces
if company.cik and sec_companyfacts_available:
    ... existing SEC path ...
else:
    ... yfinance adapter ...
```

That conditional violates Open/Closed: every *new* source (SEDAR+, then ESEF, then Companies House — ADR-038's own Phase 2 roadmap) re-opens `refresh_ticker` and lengthens the `if/elif` ladder. With **three concrete sources now on the table (EDGAR, yfinance, SEDAR+)**, the `rule_of_three` (`mental_models/engineering/rule_of_three.md`) threshold for extracting an abstraction is met — the port earns its keep rather than being speculative (`yagni` respected: we abstract *because* the third case is real, not "in case").

### 1.3 What today's data layer looks like (the thing being refactored)

- `data/pipeline.py:refresh_ticker` imports `data.edgar_fetcher` **directly** and orchestrates EDGAR + Form 4 + yfinance snapshot + FMP + Polygon via one `asyncio.gather`. EDGAR is hard-wired.
- `fetch_edgar_fundamentals(...) -> EdgarFetchResult` where `EdgarFetchResult = {ticker, financials: list[EdgarFinancialRow], insider_transactions, gaps: list[str], latest_10k_accession}`. **This is the shape the port's return type mirrors** (`respect_the_contract`).
- `Company` has `cik`, `exchange`, `status`, and rich per-field `_source` columns (ADR-022). It has `currency` (default `"USD"`) + `currency_source`. **It does NOT have `reporting_currency` or `fx_rate_to_usd`** — ADR-038 §1.3/§"Currency handling" asserted these exist; **they do not.** This ADR corrects that claim and scopes the minimal FX columns it actually needs (§3.4).

### 1.4 The honest SEDAR+ reality

SEDAR+ (sedarplus.ca) has **no public REST API** (as of 2026). A Tier-1B parser = scrape the filing index → locate the iXBRL annual filing → parse iXBRL into `Financial` rows. ADR-038 estimated **4-6 weeks**, fragile to site changes. That fragility is why this ADR **scaffolds but does not build** SedarPlusSource now (per user's Phased scope). The yfinance-CA adapter is the bridge that makes VitalHub divable *today* at honest Tier-3 depth.

---

## 2. Decision

Introduce a **`FundamentalsSource` port** (Protocol) at the data boundary. Migrate EDGAR behind it unchanged. Add a yfinance-Canada adapter. Scaffold SEDAR+ behind the same port for a deferred Phase C. A resolver selects the source per ticker.

### 2.1 The port (Dependency Inversion + Interface Segregation)

```python
# data/sources/base.py  (NEW)
from typing import Protocol, runtime_checkable

@dataclass
class FundamentalsResult:
    """Unified result — superset-compatible with EdgarFetchResult so the
    existing _persist_financials / _persist_source_log path is untouched."""
    ticker: str
    financials: list[FinancialRow] = field(default_factory=list)
    insider_transactions: list[InsiderRow] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    source_tier: str = "sec_edgar"      # 'sec_edgar' | 'sedar_plus' | 'yfinance_only'
    reporting_currency: str = "USD"     # native filer currency, pre-FX
    metadata: dict = field(default_factory=dict)   # name/exchange/sector for Company row

@runtime_checkable
class FundamentalsSource(Protocol):
    name: str          # 'sec_edgar' | 'sedar_plus' | 'yfinance'
    tier: str          # ADR-022 source tier tag written to Financial.{field}_source

    def supports(self, ticker: str, company: Company | None) -> bool:
        """Cheap, no-I/O predicate: can this source serve this ticker?
        SEC: cik present. SEDAR+: .TO/.V suffix. yfinance: always (fallback)."""

    async def fetch(self, ticker: str, requirement: DataRequirement) -> FundamentalsResult:
        """Fetch + map to FinancialRow. Honours DataRequirement (annual_years
        etc.). Returns gaps, never raises on missing data (fail-soft per
        CLAUDE.md). Raises only on programmer error."""
```

**SOLID mapping (explicit, per user request):**

| Principle | How ADR-039 honours it |
|---|---|
| **S**ingle Responsibility | One adapter = one external system's wire format → `FinancialRow`. The pipeline orchestrates; adapters fetch; the reader serves frameworks. No adapter knows about scoring. |
| **O**pen/Closed | New source = new file in `data/sources/` + one `register()` line. `refresh_ticker` / frameworks / CLI never re-open. |
| **L**iskov | Every adapter is substitutable behind `FundamentalsSource` — same return contract (`FundamentalsResult`), same fail-soft semantics. A test double substitutes cleanly (`respect_the_contract`). |
| **I**nterface Segregation | The port is two methods (`supports`, `fetch`). Insider/proxy/10-K-text concerns are NOT forced onto sources that can't provide them — they surface as `gaps`, not unimplemented interface members. |
| **D**ependency Inversion | `refresh_ticker` depends on the `FundamentalsSource` abstraction + a `resolve_source()` factory; it imports no concrete fetcher. EDGAR becomes a detail, not the spine. |

Mental-model grounding: `boundaries_hexagonal` (the port IS the hexagon edge), `composition_over_inheritance` (registry of adapters, not a base-class hierarchy), `parse_dont_validate` (each adapter parses wire format → typed `FinancialRow` once, at the edge), `illegal_states_unrepresentable` (`source_tier` is an enum-constrained tag, not a free string downstream), `single_source_of_truth` (the resolver is the *one* place source-selection lives).

### 2.2 The adapters

```
data/sources/                              (NEW package)
├── base.py            — FundamentalsSource Protocol + FundamentalsResult + registry
├── sec_edgar.py       — SecEdgarSource: thin wrapper over fetch_edgar_fundamentals()
│                         (Chesterton's Fence — wrap, do NOT rewrite the EDGAR path)
├── yfinance_fund.py   — YFinanceFundamentalsSource: .financials/.balance_sheet/.cashflow
│                         → FinancialRow, Tier-3, ~4yr depth (ADR-038 Phase 1, now an adapter)
└── sedar_plus.py      — SedarPlusSource: SCAFFOLD. supports()=True for .TO/.V;
                          fetch() returns FundamentalsResult(gaps=["SEDAR+ parser not yet
                          implemented — ADR-039 Phase C"]). Tier-1B placeholder.
```

### 2.3 The resolver (Single Source of Truth for selection + precedence)

```python
# data/sources/base.py
def resolve_source(ticker: str, company: Company | None) -> FundamentalsSource:
    """Precedence — highest-fidelity available source wins:
       1. SEC EDGAR   — cik present AND companyfacts 200    (Tier-1A)
       2. SEDAR+      — .TO/.V suffix AND parser built       (Tier-1B)  [Phase C]
       3. yfinance    — fallback for any resolvable ticker   (Tier-3)
    Hard rule (ADR-038 §Risks slippery-slope): a cik-present + companyfacts-200
    ticker ALWAYS routes to SEC. yfinance is reachable ONLY when SEC 404s or
    cik is None. This is the anti-degradation guard."""
```

`refresh_ticker` change is minimal and one-concern (`one_concern_per_change`):

```python
# data/pipeline.py — BEFORE: `from data.edgar_fetcher import fetch_edgar_fundamentals`
#                    AFTER:
source = resolve_source(ticker, company)
result = await source.fetch(ticker, requirement)   # EDGAR / yfinance / SEDAR+ — pipeline is blind
_persist_financials(ticker, result.financials)      # unchanged
_persist_source_log(ticker, result.financials)      # unchanged (SEC accn; no-op for others)
```

### 2.4 What this ADR does NOT decide

- **No SEDAR+ scraper build now.** Scaffold only; Phase C is a separate go-ahead (4-6 wk).
- **No universe-screener integration.** Non-SEC tickers stay `status='watchlist'`, invisible to `screen-winners` (carried from ADR-038 §"NOT decide").
- **No bulk foreign ingestion.** Per-ticker `invest watchlist add VHI.TO` only.
- **No new framework math.** F1-F7 run unchanged on the resulting `FinancialRow`s; F7 (10yr z-scores) / insider / proxy / 10-K-text gracefully surface `InsufficientHistoryError` / `data_gaps` on Tier-3 sources (existing path, not new code).

---

## 3. Architecture & schema

### 3.1 Package layout (mirrors the `data/api/` precedent — `mirror_existing_patterns`)

```
data/
├── pipeline.py            — refresh_ticker(): depends on resolve_source() (DIP)
├── edgar_fetcher.py       — UNCHANGED (wrapped by sec_edgar.py)
├── sources/               — NEW port + adapters (this ADR)
│   ├── base.py · sec_edgar.py · yfinance_fund.py · sedar_plus.py
└── api/
    └── yfinance_client.py — UNCHANGED (snapshot/price; yfinance_fund.py is the fundamentals sibling)
```

### 3.2 Source-tier registry (ADR-022 tier integration)

| Source | `name` | ADR-022 tier | `Company.data_source_tier` | Built in |
|---|---|---|---|---|
| SecEdgarSource | `sec_edgar` | Tier-1A (SEC XBRL) | `sec_edgar` | Phase A (wrap) |
| SedarPlusSource | `sedar_plus` | Tier-1B (regulator iXBRL) | `sedar_plus` | Phase C (deferred) |
| YFinanceFundamentalsSource | `yfinance` | Tier-3 (third-party) | `yfinance_only` | Phase B |

### 3.3 Migration — additive only

```sql
-- carried from ADR-038; existing 10k+ rows default to sec_edgar
ALTER TABLE companies ADD COLUMN data_source_tier TEXT DEFAULT 'sec_edgar';
```

### 3.4 Currency — correcting ADR-038's false premise

Schema today has only `Financial.currency` (default `'USD'`) + `currency_source`. There is **no** `reporting_currency` / `fx_rate_to_usd`. Minimal honest scope:

```sql
ALTER TABLE financials ADD COLUMN fx_rate_to_usd REAL;     -- period-end FX, NULL if native USD
```

The yfinance adapter reads `Ticker.info.financialCurrency` → writes `Financial.currency` (e.g. `CAD` for `.TO`), cross-checks against the exchange suffix (`.TO`/`.V` ⇒ expect CAD; mismatch ⇒ `data_gap`, per `fail_fast`), and stores `fx_rate_to_usd` so downstream USD comparisons are explicit, not implicit. No ECB-table dependency is assumed (ADR-038 wrongly claimed one exists); Phase B uses yfinance's own FX or a single documented FX lookup — scoped in the Phase B impl note, not hand-waved.

---

## 4. Inversion (mandatory — CLAUDE.md §"Inversion is mandatory and primary")

| Forward | Inversion | Mitigation in this ADR |
|---|---|---|
| The port makes sources pluggable. | What if the abstraction is wrong and leaks? | Return type = existing `EdgarFetchResult` superset; if the port can't express EDGAR cleanly, it's wrong — caught in Phase A by re-running a US dive and diffing output byte-for-byte. |
| yfinance unblocks VitalHub today. | What false confidence does Tier-3 data create? | `data_source_tier` + Stage-0c methodology panel make shallowness loud; `data_completeness` scores it lower than SEC; F7/insider/proxy surface as explicit gaps. |
| Resolver picks the best source. | What's the worst mis-route? | The `VHI`→Valhi collision. Guard: SEC route requires *both* cik present *and* companyfacts-200; `.TO`/`.V` suffix never resolves through EDGAR. The wrong-company failure mode is the #1 test case (§6). |
| SEDAR+ scaffold is cheap. | Does a stub that returns gaps masquerade as "supported"? | `supports()=True` but `fetch()` returns an explicit gap string naming "ADR-039 Phase C" — a dive shows "no SEDAR+ data yet", never silent zeros. |

If the port cannot survive a US-dive byte-diff (forward inversion #1), it does not ship.

## 5. Alternatives considered

- **Alt 1 — Keep ADR-038's inline `if/else`.** Rejected: violates Open/Closed; the 4th source (ESEF) makes the ladder unmaintainable. Three real sources now justify the seam (`rule_of_three`).
- **Alt 2 — Build the SEDAR+ Tier-1B scraper now.** Rejected per user's Phased choice: 4-6 wk, fragile, and blocks VitalHub for weeks when a Tier-3 bridge ships today. SEDAR+ still ships — behind the same port, zero churn.
- **Alt 3 — FMP for Canadian fundamentals instead of yfinance.** Deferred: FMP free tier (250/day) fragile; yfinance free-at-scale. FMP can become a `FundamentalsSource` adapter later (proof the port pays off).
- **Alt 4 — abstraction-only, no Canadian data.** Rejected: leaves VitalHub blocked; the port without an adapter is `yagni` in the wrong direction (abstraction with no second concrete user to validate it).

## 6. Validation plan

Phase A (port + EDGAR wrap) ships iff:
1. **US-dive byte-diff** — `invest dive NVDA` / `INTA` / `AAPL` produce *identical* output pre/post refactor (Liskov proof; `test_behaviour_not_implementation`).
2. **Wrong-company guard** — a test asserts `resolve_source("VHI.TO", ...)` never returns `SecEdgarSource`, and `resolve_source("VHI", cik=59255)` resolving to Valhi is *flagged*, not silently dived (the motivating failure becomes a regression test — `test_failure_modes_not_happy_paths`).

Phase B (yfinance-CA) ships iff:
3. `invest watchlist add VHI.TO` materializes a Company row (CAD, Healthcare) + ≥3 annual `revenue` rows tagged `_source='yfinance'`, `data_source_tier='yfinance_only'`.
4. `invest dive VHI.TO` runs F1 + F3 + **BEW** (the overlay the user emphasised — feasible on price+cap+sector per ADR-038 §"What yfinance can deliver"); F7/ICA-needing-R&D surface as explicit gaps, no silent zeros.
5. Methodology panel states the Tier-3 caveat verbatim (ADR-038 §5 disclosure text, retargeted to SEDAR+/Canada).

## 7. Consequences

| File | LOC (est) | Purpose |
|---|---|---|
| `data/sources/base.py` | ~120 | Port + `FundamentalsResult` + registry + `resolve_source` |
| `data/sources/sec_edgar.py` | ~60 | Wrap `fetch_edgar_fundamentals` (no rewrite) |
| `data/sources/yfinance_fund.py` | ~230 | Tier-3 financials/balance/cashflow adapter + FX |
| `data/sources/sedar_plus.py` | ~40 | Scaffold (gap-returning stub) |
| `data/pipeline.py` (edit) | ~30 | Swap direct EDGAR import for `resolve_source` |
| `cli/main.py` (edit) | ~30 | `invest watchlist add VHI.TO` resolves via yfinance |
| `alembic/versions/*.py` | ~20 | `data_source_tier` + `fx_rate_to_usd` migration |
| `tests/test_sources/*` | ~200 | Port-contract + wrong-company-guard + yfinance-CA fixtures |

**Phase A+B total ≈ 760 LOC, ~1.5-2 days** + validation. Phase C (SEDAR+ scraper) ≈ 4-6 wk, separate go-ahead.

**Preserved:** F1-F7 code (zero change) · CLAUDE.md determinism (yfinance/SEDAR+ are deterministic, zero LLM) · ADR-031 two-Anthropic-call-sites rule · ADR-022 per-field provenance · lazy-load (sources fetch only on explicit `dive`/`watchlist add`).

## 8. References

- ADR-019 — plugin-source + per-task independence (precedent shape)
- ADR-022 — methodology disclosure & per-field source tiers (Tier 1A/1B/3)
- ADR-025 — IFRS taxonomy + currency (SEC-filing FPIs only)
- ADR-033 — SEC-first hierarchy (this ADR's resolver precedence enforces it)
- ADR-038 — non-SEC international issuer fundamentals (parent decision; this ADR replaces its inline-branch design with a port, corrects its currency-column claim, keeps its two-phase honesty)
- `mental_models/engineering/`: `boundaries_hexagonal`, `mirror_existing_patterns`, `respect_the_contract`, `composition_over_inheritance`, `single_source_of_truth`, `rule_of_three`, `yagni`, `chestertons_fence`, `parse_dont_validate`, `illegal_states_unrepresentable`, `fail_fast`, `one_concern_per_change`
- SEDAR+ (no public API as of 2026): https://www.sedarplus.ca

---

*ADR-039 | The Boardroom Lab | 2026-06-06*

*The architectural win is the port, not the parser. EDGAR was the spine; this ADR makes it one detail behind a `FundamentalsSource` boundary, so Canada (SEDAR+) — and later UK/EU/AU — drop in as adapters with zero churn to the framework engine. The yfinance-CA bridge makes VitalHub divable today at honestly-labelled Tier-3 depth; the proper SEDAR+ Tier-1B iXBRL parser ships later behind the same seam. The wrong-company collision (`VHI`→Valhi) that motivated this becomes a regression test, not a footnote.*
