# ADR-041 — Jurisdiction Routing Table + ESEF Adapter (EU/EEA issuers)

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Code is implemented and validated live (see §6); this document is the Tier-2 artifact CLAUDE.md requires the user to ratify. Nothing here is settled until you say so. |
| **Phase** | Data layer / source abstraction |
| **Extends** | ADR-039 (the `FundamentalsSource` port — this ADR adds the 4th adapter and generalises the resolver), ADR-022 (per-field `_source` provenance), ADR-033 (SEC-first trust hierarchy), ADR-025 (IFRS taxonomy + currency) |
| **Resolves** | EU/EEA issuers (`.ST` `.HE` `.OL` `.CO` `.AS` `.PA` `.MI` `.MC` `.BR` `.VI` `.WA` `.LS` `.IC` `.AT`) were routed to the yfinance Tier-3 bridge despite filing mandatory machine-readable iXBRL with their national OAM. `BONEX.ST` was hand-analysed in chat while five years of audited XBRL sat in a public EU repository. |
| **Provenance** | User directive 2026-08-16: "check the architecture of the mechanism to fetch fundamentals … determine the country and region … it has to be architecturally sound, lazy loaded … add ESEF adapter." |

---

## 0. The non-negotiable shape (inherited from ADR-039 §0)

1. **Adds a row to a table, does not rewrite the resolver.** A US ticker's call trace is unchanged — verified by a live `invest dive NVDA` producing all 7 frameworks off `sec_edgar`.
2. **Open for extension.** Adding Korea = one `Jurisdiction` row + one adapter file. Adding a market that needs no new adapter = one row, zero code.
3. **Dependency inversion preserved.** `refresh_ticker` still depends only on the port.
4. **Provenance honesty at ROW granularity** — stricter than ADR-039, which tagged provenance per COMPANY. See §2.3.
5. **Fails into a `data_gap`, never a hallucination**, and never into the *wrong company*.

---

## 1. Context

### 1.1 What the old resolver could not express

`resolve_source` held two flat frozensets and an if-ladder:

```python
if suffix in _CANADIAN_SUFFIXES:  ...
if suffix in _FOREIGN_SUFFIXES:   return yfinance
return sec_edgar
```

`_FOREIGN_SUFFIXES` conflated two unrelated facts — "this is not a US ticker" and "we cannot get filing-grade data here". Those are different claims, and the moment a fourth source exists they must be separated. `.ST` and `.DE` sit in the same set, are governed by the same regulation, and have **opposite** reachability.

The set was also silently incomplete: `.KS`, `.SA`, `.JO`, `.IR` were absent, so a Korean ticker routed to **SEC EDGAR** and would have resolved against whatever US filer shared its symbol. That is the `VHI`→Valhi failure mode, latent for every unlisted suffix.

### 1.2 What ESEF actually is

Mandatory since FY2020 for EU/EEA-listed annual financial reports: inline XBRL against the IFRS taxonomy, filed with each member state's Officially Appointed Mechanism. XBRL International aggregates a large share at `filings.xbrl.org` and republishes each as an **xBRL-JSON (OIM) fact document** — free, no key, validation-scored.

### 1.3 Measured coverage — the premise that failed

Verified live 2026-08-16 against `filings.xbrl.org/api/filings?filter[country]=XX`:

| Country | Filings indexed | Newest `period_end` | Reachable |
|---|---:|---|---|
| DK | 2,126 | 2026-06-30 | ✅ |
| SE | 1,415 | 2024-12-31 | ✅ (≈1.5yr lag) |
| FR | 1,178 | current | ✅ |
| FI | 1,168 | 2026-01-31 | ✅ |
| NO | 958 | 2025-03-31 | ✅ |
| PL | 877 | 2024-03-31 | ✅ (lagging) |
| IT | 872 | 2026-01-31 | ✅ |
| BE | 709 | 2026-03-31 | ✅ |
| NL | 656 | 2026-03-31 | ✅ |
| AT | 601 | 2026-04-30 | ✅ |
| ES | 542 | 2025-01-31 | ✅ |
| GR / LU / PT / IS / HU | 128–266 | mixed | ✅ |
| **DE** | **0** | — | ❌ |
| **IE** | **0** | — | ❌ |

**The originating brief claimed this build "unlocks Germany, the Nordics and the rest of the EU in one build." Germany is not unlocked.** The Bundesanzeiger does not syndicate to the index. `AG1.DE` (AUTO1 Group SE, LEI `391200S2LPXG5ZD5G304`) is a mandatory ESEF filer with **zero** indexed filings. The UK is separately out of scope — it left the ESEF regime and uses Companies House.

Honest headline: **this unlocks the Nordics + France/Italy/Benelux/Iberia/Austria/Poland — roughly 11,900 indexed filings across 17 countries — and does not unlock Germany, Ireland or the UK.**

That correction matters for prioritisation. Of the three markets named as where the informational edge lives (UK, Canada, Nordics), this build reaches exactly one.

---

## 2. Decision

### 2.1 Jurisdiction registry — routing becomes data (`data/sources/jurisdiction.py`)

```python
@dataclass(frozen=True)
class Jurisdiction:
    suffix: str; mic: str; country: str; region: str; currency: str
    regime: str                    # what the issuer MUST file (de jure)
    source_chain: tuple[str, ...]  # adapters, HIGHEST FIDELITY FIRST (de facto)
    venue: str; note: str
```

**`regime` and `source_chain` are deliberately separate fields.** Germany's regime is `esef`; its chain is `(yfinance,)`. Collapsing those two into one flag is what produces "it should work" bug reports and a guaranteed-empty round trip on every German dive. The `.DE` row carries a note recording the measurement and the flip condition.

`resolve_source` becomes a walk: take the first chain entry that is registered, `available`, and `supports()` the ticker. yfinance terminates every chain, so resolution can never fail. Unknown suffixes resolve to the US row, preserving `BRK.B` → SEC exactly.

### 2.2 ESEF adapter (`data/sources/esef.py`, `esef_concepts.py`)

Resolution chain, all lazy — no I/O in `supports()`, nothing fetched until a dive or `watchlist add` asks:

```
ticker → Jurisdiction → legal name (Company.name, else yfinance)
       → LEI via GLEIF (country-scoped)  → cached on companies.lei
       → filing index (filings.xbrl.org) → xBRL-JSON facts
       → EdgarFinancialRow per fiscal year
```

Four engineering problems that are not obvious until you touch real filings:

**(a) Concept heterogeneity.** There is no single revenue tag. Measured: BONESUPPORT uses `RevenueFromSaleOfGoods`, Kempower `Revenue`, ASML `RevenueFromContractsWithCustomers`. `esef_concepts.CONCEPT_MAP` holds ordered synonyms per canonical field — the same shape as `yfinance_fund._val`'s label candidates. Company-specific **extension** concepts (`BON:…`) are deliberately never interpreted.

**(b) Additive vs synonym fields.** Capex splits across PP&E / intangibles / other. First-match-wins undercounts BONESUPPORT FY2024 by 74% (1.53m vs 5.84m). `SUM_CONCEPT_MAP` sums components.

**(c) OIM period encoding.** Instants are the *next day* (the 2024-12-31 balance sheet is tagged `2025-01-01T00:00:00`); durations are half-open. Both resolve as `end − 1 day`. Interim durations in the same document are excluded by a 330–400 day window.

**(d) Comparative columns are tagged less completely than current-year columns.** Merging filings at *year* granularity silently dropped `ifrs-full:Assets` for every prior period. Merging **per concept**, newest-filing-wins, recovers full balance sheets back to FY2020.

Segment/member-dimensioned facts are refused outright — a revenue-by-geography fact read as consolidated revenue is a wrong-number bug, not a missing-number bug.

### 2.3 Per-ROW provenance — the change from ADR-039

**ESEF is an ANNUAL regime.** EU interim reports are not iXBRL-tagged, so an ESEF-only ticker persists zero quarterly rows and every framework declaring `quarterly_count` goes UNEVAL. Filing-grade annuals no framework can consume are not a win.

So the adapter returns a **hybrid**: ESEF owns the annual periods it covers; yfinance supplements quarterly rows and any annual year beyond the index. Each `Financial` row keeps its own `source` (`esef` | `yfinance`), so fidelity is inspectable per number rather than per company. ESEF rows are never overwritten by yfinance for the same year (ADR-033 hierarchy).

This is the concrete form of "screening fidelity is not thesis fidelity": a normalised quarterly is fine for momentum; a thesis number comes off the filing.

### 2.4 Wrong-company guard

GLEIF's `filter[entity.legalName]` is a **leading-substring** match, not fuzzy, and exchange names disagree with registered names in both directions (`"Bonesupport Holding AB (publ)"` → 0 hits; `"Dometic Group AB (publ)"` → 1). So the adapter walks progressively shorter name variants and stops at the first that returns anything — then requires an **unambiguous** winner: exact normalised-name match, or exactly one ACTIVE in-country entity. Anything else returns a gap and **zero rows**.

An unscoped GLEIF query returned a German rowing club and an Indian individual. Country-scoping and the ambiguity refusal are load-bearing, not defensive decoration.

### 2.5 Derived share counts

ESEF Phase-1 frequently omits share counts (BONESUPPORT tags EPS but no share count). F7 discards any annual row lacking `shares_outstanding`, so ESEF alone left F7 UNEVAL. Weighted-average shares are recovered as `ProfitLoss / BasicEPS` — both filing-grade, the identity is definitional (ADR-033 "compute, don't pull"). Verified: 133,754,000 / 2.04 = 65,565,686 against ~65.5m actual. Tagged counts always win; sign-mismatched inputs derive nothing.

### 2.6 SEC-artifact gating

Form 4, 10-K text and DEF 14A do not exist for non-SEC filers. These were gated only by `DataRequirement`, so a Swedish refresh fired six EDGAR calls to log six `Company not found` warnings. Now gated on `jurisdiction.regime == sec_xbrl`, and the resulting gap says *"Nasdaq Stockholm issuers file no SEC Form 4"* rather than *"no Form 4 found"* — a regime absence, not a search miss.

### 2.7 What this ADR does NOT decide

- **No German/Irish national-OAM adapter.** Needs a Bundesanzeiger-specific build; out of scope.
- **No Companies House (UK) adapter.** `SRC_COMPANIES_HOUSE` is reserved in the UK chain so it upgrades with zero edits when built. **Recommended next**, on the edge argument.
- **No LLM PDF extraction** for Canada/Australia. That is a separate ADR and would be the first non-deterministic path in the data layer — it needs its own scrutiny under the two-call-sites rule.
- **No universe-screener integration.** Non-SEC tickers stay `status='watchlist'`.
- **No framework math changes.** F1–F7 unchanged.

---

## 3. Schema

```sql
ALTER TABLE companies ADD COLUMN lei TEXT;   -- b7d1e4c93f10, additive, nullable
```

Identity cache: resolved once via GLEIF, then every later refresh is a two-hop fetch. NULL for US issuers, which join on CIK.

---

## 4. Inversion (mandatory)

| Forward | Inversion | Mitigation |
|---|---|---|
| Jurisdiction routing generalises the resolver. | What if the table is wrong or incomplete? | Unknown suffix → US/SEC (unchanged behaviour); tests assert no duplicate suffixes and that every chain terminates at yfinance. |
| ESEF gives filing-grade EU data. | What if it gives *stale* filing-grade data and that reads as current? | Index lag is measured per country, surfaced as a gap naming the boundary year, and the missing year is explicitly labelled Tier-3 when supplemented. |
| Filing-grade beats yfinance. | Where is filing-grade actually *worse*? | Recency. Sweden lags ~1.5yr. Hence the hybrid — refusing yfinance entirely would have made BONEX's FY2025 invisible. |
| GLEIF resolves ticker→entity. | What is the worst mis-resolution? | Wrong company with plausible numbers. Guard: country scope + ACTIVE + unambiguous, else zero rows. Three tests pin this. |
| Deriving shares from EPS unlocks F7. | Is this fabrication? | No — both inputs are tagged facts and the identity is definitional. But it is *weighted-average*, not period-end; documented at the call site and in the panel. |
| More markets reachable = more edge. | Does breadth without depth create false confidence? | F1/F3/F4/F6 remain UNEVAL on EU tickers (no Form 4, no short interest, ≤5 quarters). The dive prints exactly which and why. UNEVAL, never 0. |

---

## 5. Alternatives considered

- **Alt 1 — keep the flat suffix sets, add `.ST` etc. to a new ESEF set.** Rejected: a third frozenset restates the same conflation and cannot express DE (right regime, no reachability).
- **Alt 2 — build a per-country OAM adapter set.** Rejected for now: ~17 parsers for what one index API already aggregates. Revisit for DE specifically.
- **Alt 3 — ESEF only, no yfinance supplementation.** Rejected: zero quarterly rows ⇒ F1–F6 all UNEVAL. Filing-grade data nothing can consume.
- **Alt 4 — treat ESEF as a full replacement for yfinance on EU tickers.** Rejected: index lag would hide the most recent fiscal year.

---

## 6. Validation (all executed live, 2026-08-16)

| # | Check | Result |
|---|---|---|
| 1 | US dive unchanged (Liskov) | `invest dive NVDA` → 7/7 frameworks, `sec_edgar` panel, `Tier sec_edgar dive plan` ✅ |
| 2 | Routing table | 18 tickers across 8 countries route as specified; `AG1.DE`→yfinance, `BONEX.ST`→esef ✅ |
| 3 | Wrong-company guard | `VHI.TO` never reaches SEC; ambiguous GLEIF returns zero rows ✅ |
| 4 | Cross-country extraction | SE / FI / NO / NL / IT, 3 currencies, 3 revenue concepts ✅ |
| 5 | Filing-grade correctness | BONEX FY2024 revenue `898,727,000 SEK`, capex `5,840,000`, FCF `59,920,000` — capex/FCF match yfinance exactly; **operating income `166,147,000` where yfinance said `147,713,000` / `174,918,000`** ✅ |
| 6 | Resolves prior data gaps | BONEX FY2023 income tax `−229,273,000` — confirms the deferred-tax-asset hypothesis that was unverifiable from normalised sources ✅ |
| 7 | End-to-end persistence | `data refresh BONEX.ST` → 5 esef annual + 1 yfinance annual + 5 yfinance quarterly, `lei` cached, `data_source_tier='esef'` ✅ |
| 8 | Framework engine | `dive BONEX.ST` → F2/F5/F7 run (composite 5.40); F1/F3/F4/F6 UNEVAL with jurisdiction-accurate reasons ✅ |
| 9 | Gates | ruff + mypy --strict clean on `data/sources/`; **178 passed, 2 skipped** (was 147) ✅ |

---

## 7. Consequences

| File | LOC | Purpose |
|---|---:|---|
| `data/sources/jurisdiction.py` | ~270 | NEW — routing registry (36 venues) |
| `data/sources/esef.py` | ~490 | NEW — ESEF adapter |
| `data/sources/esef_concepts.py` | ~145 | NEW — IFRS concept map (data) |
| `data/sources/base.py` | ~50 Δ | Chain-walking resolver, fidelity rank, derived suffix sets |
| `data/pipeline.py` | ~35 Δ | SEC-artifact gating, LEI cache, currency-source hierarchy |
| `cli/main.py` | ~30 Δ | ESEF methodology panel |
| `alembic/versions/b7d1e4c93f10` | ~25 | `companies.lei` |
| `tests/test_sources/` | ~300 | 31 new tests |

**Known limits, stated plainly:** Germany/Ireland unreachable · UK needs Companies House · Sweden lags ~1.5yr · quarterlies are Tier-3 everywhere in the EU · F1/F4 structurally UNEVAL for EU issuers (no Form 4, no short-interest feed) · notes are block-tagged so customer concentration and proxy signals remain gaps.

**Recommended next**, in edge order rather than coverage order: **Companies House (UK)** — it is one of the three named edge markets, the API is free and structured, and `PINE.L` / `JDG.L` are already waiting on it.

## 8. References

- ADR-039 — the port this extends · ADR-033 — SEC-first hierarchy · ADR-022 — provenance tiers · ADR-025 — IFRS taxonomy
- `mental_models/engineering/`: `single_source_of_truth`, `boundaries_hexagonal`, `parse_dont_validate`, `illegal_states_unrepresentable`, `mirror_existing_patterns`, `chestertons_fence`, `rule_of_three`, `fail_fast`
- ESEF index: https://filings.xbrl.org/api/filings · GLEIF: https://api.gleif.org/api/v1/lei-records

---

*ADR-041 | The Boardroom Lab | 2026-08-16 | **PROPOSED — not ratified***

*The win is the routing table, not the parser. Routing knowledge moved out of an if-ladder into one greppable dataset where `regime` (what an issuer must file) and `source_chain` (what we can actually read) are separate columns — which is the only reason the German case is representable at all. The ESEF adapter is then just the first row that needed a new adapter. The correction to the brief stands on its own: this build does not unlock Germany, and the market where the edge was argued to be strongest — the UK — needs a different adapter entirely.*
