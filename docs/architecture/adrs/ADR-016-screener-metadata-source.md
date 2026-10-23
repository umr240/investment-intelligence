# ADR-016 — Screener metadata source: FMP bulk screener replaces yfinance, SEC EDGAR for everything else

**Status**: **Superseded by ADR-019 (Polygon-as-plugin) + ADR-033 (SEC-first hierarchy)**
**Date**: 2026-05-04
**Superseded**: 2026-05-17
**Decision-maker**: Umar
**Supersedes (in part)**: DEC-01 ("drop FMP from the lab")
**Related**: DEC-09 (SEC frames), DEC-10 (no auto-dive), DEC-15 (Tier 4 soft), ADR-019, ADR-033

> **Historical note (2026-05-17)**: This ADR proposed FMP bulk screener as
> the universe primary. The project converged on a different stack: SEC
> EDGAR as the canonical universe (ADR-033) + yfinance fallback + Polygon
> as an opt-in plugin for price/technicals only (ADR-019). FMP bulk
> screener is opt-in via `INVEST_USE_FMP_SCREENER=1` (Phase 5c-2). Kept for audit; do not implement the original proposal.

---

## Context

The screener's Tier 2 (cap + sector + IPO date filter on the universe) currently
calls yfinance `.info` once per ticker. On a ~10,000-ticker SEC US-listed
universe at semaphore=5, this triggers Yahoo's anti-abuse layer:

- "Invalid Crumb" 401s on a fraction of requests at moderate concurrency
- IP-level `YFRateLimitError: Too Many Requests` after sustained traffic
- Penalty box typically clears in 1–4 hours

Empirical evidence (this session, 2026-05-04):
- Full-universe Stage A (semaphore=5, 10,104 tickers): **1 survivor / 10,104**
- 26-ticker test list (post rate-limit, semaphore=1, retries=3): **0 / 26**
- Direct single-ticker probe: explicit `YFRateLimitError`

yfinance is unfit for universe-scale metadata enrichment. We need a different
source for cap + sector + industry + IPO date at the universe level.

The user has correctly observed:
1. yfinance shouldn't be used for the screener
2. SEC EDGAR should be relied on as the primary source
3. The main project (`next-nvidia-detector/microservices/shared/data_sources/fmp.py`)
   already has a 910-line `FMPClient` with rate-limit, retries, batching, caching

The question this ADR resolves: **what data source(s) should the screener use
for Tier 0–3 (universe enumeration + cap/sector/IPO filter + exclusion filter)?**

---

## Decision drivers

1. **Reliability** — must complete a screener run without rate-limiting or
   anti-abuse blocks
2. **Cost** — must fit within free tier of any external API; ideally zero
3. **Speed** — full screener (Tier 0–6) should complete in <30 min wall-clock
4. **Coverage** — must cover ~all US-listed common stock SEC filers
5. **Accuracy** — sector classification and market cap must be reliable;
   IPO date may be approximate
6. **Architectural consistency** — fits the existing 6-tier ladder, lazy-load
   discipline, and reusable components from main project

---

## What each tier of the screener actually needs

| Tier | Needs | Universe size | Per-ticker cost matters? |
|---|---|---|---|
| 0 | ticker, CIK, exchange | ~10,000 | NO (1 bulk call) |
| 1 | exchange (already have) | ~10,000 | NO (in-memory) |
| 2 | **market_cap, sector, industry, IPO_date** | ~5,000-10,000 | **YES** |
| 3 | sector, industry (already have) | ~1,500 | NO (in-memory) |
| 4 | revenue, assets, equity, debt, FCF, ROIC | universe-wide | NO (SEC frames bulk) |
| 5 | full per-ticker fundamentals | ~200-300 | YES but small N |
| 6 | composite + persist | ~50 | NO |

**Tier 2 is the bottleneck.** It's the only tier that needs per-ticker
metadata across the entire universe (5,000-10,000 tickers).

---

## Options analysed

### Option A — yfinance (status quo)

**How**: per-ticker `yf.Ticker(t).info` × N
**API calls**: ~10,000 yfinance per screener run
**Cost**: $0
**Speed**: 30+ min at semaphore=1; 5 min at semaphore=5 (but blocked)
**Reliability**: ❌ Yahoo's anti-abuse rate-limits us before completion
**Coverage**: All US-listed common stock
**Verdict**: Proven unfit at universe scale (this session's empirical results)

### Option B — SEC EDGAR only

**Sources available**:
- `company_tickers_exchange.json` — ticker, CIK, name, exchange (already used at Tier 0). NO cap, NO sector beyond exchange.
- `submissions/CIK{cik}.json` — entityName, sicCode, sicDescription, exchanges, formerNames, ~1MB per CIK or 50KB if `include_filings=false`. ~10,000 calls per universe walk. SIC code → sector mapping is doable.
- `frames.json` — universe-wide per-concept (used in Tier 4). Has `CommonStockSharesOutstanding` per CIK. NO current price, so NO current market cap.
- `companyfacts.json` per ticker — full fundamentals, but per-ticker (~10,000 × 5MB = 50GB on cold cache; absurd at universe scale).

**The fatal gap**: SEC has NO current market price. Without price × shares = no market cap. We can compute book equity from frames, but that's not market cap.

**API calls**: ~10,000 SEC submissions calls (~1.5 hours at SEC's 10 req/sec)
**Cost**: $0
**Speed**: ~1.5 hours just for sector lookup; market cap missing entirely
**Reliability**: ✅ SEC has no anti-abuse for fair-use compliant traffic
**Coverage**: All SEC filers (~all US-listed)
**Verdict**: Works for sector/SIC code but **cannot deliver market cap without an additional price source**. Slow at universe scale (~1.5h).

### Option C — FMP free tier, only at Tier 2 (single bulk call)

**How**: One call to FMP's stock-screener endpoint:
```
GET /api/v3/stock-screener?marketCapMoreThan=500000000&marketCapLowerThan=5000000000&isActivelyTrading=true
```
Returns a JSON array. Each element has: `symbol, companyName, marketCap, price, beta, volume, exchange, exchangeShortName, country, sector, industry, isActivelyTrading`.

**Critical**: this is **server-side filtered**. We send the cap range, FMP returns only matching tickers. No per-ticker round-trips needed.

**API calls per screener run**:
- 1 FMP call (the bulk screener) — replaces ~10,000 yfinance calls
- Tier 4 already uses ~30 SEC frames calls
- Tier 5 uses ~200 SEC companyfacts calls
- Total external: 1 FMP + 230 SEC

**FMP free tier**: 250 calls/day. We use **1 per screener run**. Even at 24 runs/day we're at <10% of quota. Quarterly screening = 4 runs/year.

**IPO date**: NOT in the bulk screener response. Three sub-options:
- C1: Skip IPO filter at the screener; defer to dive review
- C2: One additional call per surviving ticker via `/v3/profile/{ticker}` (~600 calls — busts free tier)
- C3: Pull IPO date from SEC submissions endpoint per surviving ticker (~600 SEC calls, free)

C3 wins. SEC submissions has `firstFiled` date which is a reliable IPO-equivalent for most issuers (10-K filing within ~120 days of IPO). 600 SEC calls at 10 req/sec = ~60 seconds.

**Speed**: ~1 sec FMP + ~60 sec SEC IPO probe + ~3 sec frames + ~10 sec companyfacts = **~75 sec for the universe-narrowing phases**
**Reliability**: ✅ FMP free tier is stable; no anti-abuse for bulk calls
**Coverage**: FMP covers all US-listed common stock + ADRs + OTC (matches our scope)
**Verdict**: Optimal cost/speed/reliability for Tier 2.

### Option D — FMP for everything (drop SEC frames + companyfacts)

**How**: per-ticker FMP for fundamentals + bulk screener for metadata
**API calls**: 1 + ~600 profile + ~200 fundamentals = ~800 FMP/run
**Cost**: 800/250 → busts free tier; needs paid ($19-79/mo)
**Verdict**: Loses the SEC-bulk advantage. Worse than C.

### Option E — Hybrid: FMP at Tier 2 + SEC for everything else (RECOMMENDED)

**How**:
- Tier 0: SEC `company_tickers_exchange.json` (1 call) — gives ticker → CIK map
- Tier 1: in-memory exchange filter (0 calls)
- Tier 2: **FMP bulk screener** (1 call) — gives cap + sector + industry + initial filtering
- Tier 2.5: SEC `submissions/CIK{cik}.json` (per surviving ticker, ~600 calls) — IPO date proxy via `firstFiled`
- Tier 3: in-memory exclusion filter (0 calls)
- Tier 4: SEC frames (30 calls)
- Tier 5: SEC companyfacts (~200 calls)
- Tier 6: persist (0 calls)

**Total per run**: 1 FMP + ~830 SEC = ~831 external calls
**Cost**: $0 (1/250 FMP, SEC unlimited within fair-use)
**Speed**: ~5 min wall-clock (mostly SEC sequential calls at 10 req/sec)
**Reliability**: ✅ Both sources are stable at this volume
**Coverage**: Matches universe (FMP + SEC filers ≈ same set)

**Why this wins**:
- 1 FMP call replaces 10,000 yfinance calls (architectural unlock)
- SEC remains the source of truth for fundamentals (no LLM, no FMP fundamentals quality concerns)
- The FMP screener is the ONLY place the lab uses FMP — clean attack surface
- Reuses main project's 910-line FMPClient (rate-limit, retries, caching already battle-tested)

---

## Cost / efficiency / speed / performance / data optimization comparison

### API call budget per quarterly screener run

| Tier | A (yfinance) | B (SEC only) | E (FMP+SEC, recommended) |
|---|---|---|---|
| 0 universe | 1 SEC | 1 SEC | 1 SEC |
| 1 exchange filter | 0 | 0 | 0 |
| 2 cap/sector | **~10,000 yf** | ~10,000 SEC submissions | **1 FMP** |
| 2.5 IPO date | (in yf .info) | (in submissions) | ~600 SEC submissions |
| 3 exclusion | 0 | 0 | 0 |
| 4 frames | 30 SEC | 30 SEC | 30 SEC |
| 5 companyfacts | ~200 SEC | ~200 SEC | ~200 SEC |
| **Total** | 10,000 yf + 230 SEC | 10,230 SEC | 1 FMP + 830 SEC |
| **Wall-clock** | 30+ min (rate-limited) | ~1.5h | **~5 min** |

### Cost analysis (per year, quarterly screening = 4 runs)

| Approach | Annual cost | Free tier impact | Notes |
|---|---|---|---|
| A (yfinance) | $0 | n/a | Doesn't actually work at scale |
| B (SEC only) | $0 | n/a | Slow; missing market cap |
| E (FMP+SEC) | $0 | 4 of 250 daily quota | <2% of free tier; bulletproof |

### Daily quota math (FMP free tier = 250/day)

Even if user runs the full screener pipeline **5 times per day** with the
recommended approach: 5 FMP calls / 250 = 2% of quota. The rest of the budget
is available for `invest data refresh` ad-hoc work or experimentation.

### Performance / speed

For a typical quarterly screener run:

| Metric | A (yfinance) | E (FMP+SEC, recommended) |
|---|---|---|
| Tier 0 (universe) | 1s | 1s |
| Tier 2 (cap/sector) | 5-30 min (blocked) | 1s (1 FMP call) |
| Tier 2.5 (IPO) | (free with .info) | 60s (600 SEC calls) |
| Tier 4 (frames) | 3s | 3s |
| Tier 5 (companyfacts) | 10s | 10s |
| **Total** | 5-30 min (often fails) | **~80s** |

Wall-clock improvement: **~22× faster** when E succeeds vs A's best-case.
Reliability improvement: **infinite** since A often fails entirely.

### Data quality

| Field | yfinance | FMP screener | SEC |
|---|---|---|---|
| Market cap | live, sometimes stale | live, daily refresh | n/a (no price) |
| Sector | varies (Yahoo's taxonomy) | GICS-aligned | SIC code (older taxonomy) |
| Industry | varies | GICS-aligned | SIC description |
| IPO date | `firstTradeDateEpochUtc` (sometimes wrong) | not in screener; in profile | `firstFiled` (10-K date — close) |
| Country | yes | yes | yes |
| Active/Listed | inferred | `isActivelyTrading` flag | requires recent filing |

FMP's GICS-aligned sector/industry mapping is BETTER than Yahoo's ad-hoc taxonomy for sector/industry rule-matching. SEC's SIC code is older (1987) and less granular than GICS.

### Data optimization opportunities

1. **Cache the FMP screener response 24h** — the universe doesn't change much daily. One real fetch per day max.
2. **Cache the SEC submissions per CIK 7 days** — IPO date never changes; entity metadata rarely changes.
3. **Hit FMP screener only when cap/sector/industry params change** — for the same params within 24h, replay the cached response.

These optimizations bring sustained operation closer to **zero external calls** for repeat screens with identical params.

---

## Existing main-project FMP client — can we reuse?

**Yes.** Located at `microservices/shared/data_sources/fmp.py` (910 lines).

**Reusable components**:
- `FMPClient.__init__` — rate-limit-aware (250/day default, configurable)
- `_rate_limit()` — sliding-window throttle
- `fetch()` with `max_retries`, `retry_wait_429=60s`, exponential backoff
- `fetch_company_profile()` — for individual ticker IPO date if SEC fails
- Connection pooling (`_create_session`)
- Cache integration via Redis (optional; we'd swap for our SQLite cache)

**Reuse path**:
- Lab's `data/api/` adds `fmp_client.py` that imports the main project's `FMPClient`
- Or: copy the relevant methods into the lab if cross-project import is awkward
- Either way, do NOT rewrite — the rate-limit/retry/backoff logic is non-trivial and the main project's version is battle-tested

**Single endpoint we actually need for the screener**: `/v3/stock-screener?...`

**FMPClient methods we'd use**:
- The bulk screener call (need to verify which method maps; may need to add `fetch_screener()` if it doesn't exist)
- `fetch_company_profile()` only as IPO date fallback (rarely triggered if SEC submissions provides `firstFiled`)

---

## Decision

**Adopt Option E**: FMP bulk screener at Tier 2 + SEC submissions for IPO date + SEC frames at Tier 4 + SEC companyfacts at Tier 5. **Drop yfinance from the screener path entirely.**

**Keep yfinance for the dive path** where it's appropriate:
- Per-ticker holders (`institutional_holders`, `mutualfund_holders`)
- Per-ticker insider trades (Form 4 supplementary)
- Per-ticker price history (`.history()` for momentum)
- Analyst counts, recommendations

These dive-time uses are individual ticker fetches with low concurrency, NOT
universe-scale. yfinance handles those fine and they're free.

This decision **partially reverses DEC-01** (drop FMP from the lab). The
reversal is justified because:
- DEC-01 was correct for **per-ticker workflows** where 250/day is too few
- The screener uses **1 FMP call per run** (bulk screener endpoint), NOT per-ticker
- SEC remains the source of truth for fundamentals; FMP is used ONLY for the bulk metadata replacement at Tier 2

---

## Consequences

### Positive

1. **Screener actually works at universe scale** — empirically blocked today; reliable after E
2. **22× faster** than A's best case, infinite reliability improvement
3. **Single point of FMP dependency** — only Tier 2 metadata. Easy to monitor, rate-limit, and replace if FMP changes terms.
4. **Reuses main-project battle-tested rate-limit logic** — no rewrites
5. **GICS-aligned sector/industry** is better data for sector/industry rules than yfinance's ad-hoc taxonomy
6. **FMP free tier safely covers** quarterly + ad-hoc screening (max ~24 runs/day before approaching quota)
7. **SEC remains the source of truth** for fundamentals (preserves DEC-01's spirit even while reversing it for screener metadata)

### Negative

1. **One additional API key** — `FMP_API_KEY` is back in `.env`. Documented in CLAUDE.md.
2. **Reverses part of DEC-01** — the audit trail must show DEC-01 + this ADR as the
   complete story; future contributors will see "FMP dropped, then re-added for screener Tier 2 only"
3. **One additional dependency** — main project's FMPClient (or a slim copy)
4. **FMP free tier change risk** — if FMP changes free tier policy, we'd need to handle it. Mitigated by the fact that we use 1 call per run; even a 100-call/month tier would suffice.

### Neutral

1. **yfinance remains in the codebase** — used by the dive path (`refresh_ticker(requirement=...)` for holders, prices, analyst). Just not at universe scale.
2. **Existing screener Tier 2 code** (`_fetch_metadata_bulk`, `fetch_yfinance_metadata_only`) gets replaced. No regression — feature was broken anyway.

---

## Implementation plan (post-decision approval)

### Phase 3.1 — Wire FMP screener into Tier 2 (1 day)

**Files**:
- `data/api/fmp_client.py` (new) — minimal client; either imports main project's `FMPClient` or vendors the rate-limit/retry helpers
- `data/api/fmp_client.py:fetch_screener_universe(cap_min, cap_max, sector, exchange, country) -> list[FMPScreenerEntry]` — single bulk call
- `screener/stages.py:run_stage_a` — replace `_fetch_metadata_bulk` (yfinance) with `fetch_screener_universe` (FMP)
- `screener/pipeline.py:_EnrichedTicker` — populated from FMP response, not yfinance
- `data/api/yfinance_client.py:fetch_yfinance_metadata_only` — keep but mark internal/legacy
- `config/settings.py` — re-add `fmp_api_key` field with comment "screener Tier 2 metadata only"

### Phase 3.2 — IPO date via SEC submissions (0.5 day)

**Files**:
- `data/edgar_submissions.py` (new) — `fetch_submissions(cik) -> SubmissionsMeta` returning `{first_filed_date, sic_code, sic_description, ...}`. Cached 7 days.
- `screener/stages.py:run_stage_a` — after FMP cap/sector filter, hit SEC submissions per surviving ticker for IPO date. Apply `--ipo-after` filter using `first_filed_date` (within ~120 days of actual IPO for most issuers; flag the approximation in logs).

### Phase 3.3 — Drop yfinance from screener path (0.5 day)

**Files**:
- `screener/pipeline.py` — remove `_fetch_metadata_bulk` use from Tier 2
- `data/api/yfinance_client.py:fetch_yfinance_metadata_only` — keep for now (used elsewhere?) but don't call from screener
- Update CLAUDE.md FRAMEWORK-AWARE LAZY LOAD section

### Phase 3.4 — Tests + docs (0.5 day)

- Synthetic fixture for FMP screener response → `_EnrichedTicker` translation
- Update DATA_LAYER.md §10 with the new Tier 2 source
- Append **DEC-16** to `docs/architecture/DECISIONS.md` referencing this ADR
- Update the lab and screener plans (since archived)

**Total**: ~2.5 days

### Acceptance criteria

- `invest screen-stage A --cap-min 500M --cap-max 5B --ipo-after 2016-05-04`
  completes in <90 seconds wall-clock and returns 200-700 survivors
- The exclusion filter drops the sectors its rules name
- All tests pass; AST clean
- DECISIONS.md and CLAUDE.md updated
- One real screener run confirmed end-to-end (the test we couldn't complete with yfinance)

---

## Open questions for implementation

1. **FMPClient location** — copy into lab vs. import from `next-nvidia-detector/microservices/shared/data_sources/fmp.py`?
   Recommendation: vendor a minimal copy (~150 lines) into `data/api/fmp_client.py`. Cross-project imports are fragile across the lab/main split. The main project's full 910-line client is overkill for our 1 endpoint.

2. **IPO date approximation** — `firstFiled` from SEC submissions is the date of the company's first SEC filing, NOT necessarily the IPO date. For S-1s (IPO registration) it's a few months before IPO; for already-public companies that became SEC filers later (rare), it's the listing date. Acceptable for "IPO'd in past 10 years" filter where we just need approximate cohort.

3. **Cache TTL for FMP screener** — recommend 24h. Universe doesn't change much intra-day. Different cap/sector params = different cache key.

4. **Failure modes** — if FMP is down, fall back to SEC + yfinance combo (same as Option A but rate-limited)? Or hard-fail the screener? Recommend: hard-fail with clear error. The screener is a deliberate user action; better to surface the dependency than silently degrade.

5. **Cost ceiling alarm** — should we add a config alarm if FMP daily count nears 200? Yes — `FMPClient.get_statistics()` already tracks this. Surface it via `invest data cache-stats` or similar.

---

## References

- DEC-01 (drop FMP from lab) — partially superseded
- DEC-09 (DECISIONS.md — SEC frames at Tier 4)
- Empirical results from session 2026-05-04 (Stage A on full universe)
- Main project FMP client: `next-nvidia-detector/microservices/shared/data_sources/fmp.py`
- FMP API docs: https://site.financialmodelingprep.com/developer/docs#stock-screener
- SEC EDGAR fair-use: https://www.sec.gov/os/accessing-edgar-data
