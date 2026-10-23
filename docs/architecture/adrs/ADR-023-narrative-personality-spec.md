# ADR-023 — Narrative Personality Spec for `deepdive/narrative.py`

| Field | Detail |
|---|---|
| **Status** | **Accepted; amended by ADR-023-A1 (2026-10-21).** Several sections below were never implemented (model, caching, thinking, §1.4 structure, §1.5 lint, §1.6 reject-on-failure); the amendment records what stands. Original status: Accepted + implemented (2026-05-17). `deepdive/narrative.py` shipped ~629 LOC + `narrative_guard.py` structured-output validator + DEC-23 hold-philosophy block (§10). Production-validated on LULU + BFLY narratives. `RiskFactor.factor` max_length raised 300→500 (2026-05-17) to accommodate DEC-23 multi-clause monitoring checkpoints. |
| **Date** | 2026-05-09 |
| **Provenance** | User intervention 2026-05-09: requested explicit codification of the ANALYTICAL PERSONALITY (CLAUDE.md §ANALYTICAL PERSONALITY) as a binding contract on the future `deepdive/narrative.py` LLM call site, rather than leaving the personality embedded only in human-readable docs that future authors might paraphrase or drift from. |
| **Supersedes** | Nothing. |
| **Updates** | CLAUDE.md §"AI layer boundary" (declares the *behavioural* contract for the sole permitted LLM call site, not just its location); ADR-021 / ADR-022 (the personality must enforce both methodology rules). |
| **Preserves** | CLAUDE.md determinism rule; ADR-022 source-provenance requirements; ADR-021 anti-management-non-GAAP rule. |
| **Affects** | `deepdive/narrative.py` (Phase 6 — currently planned, not implemented). No effect on existing data / framework / overlay code. |

---

## 0. The reframe

The data path is deterministic by design — every framework score, every overlay computation, every PT ROIC capitalisation is rule-based and auditable. Phase 6 introduces an LLM solely for **qualitative narrative synthesis** of the already-computed quantitative scorecard. That LLM is the only soft surface in the system. The personality with which it speaks is therefore a *system-design decision*, not a stylistic afterthought — sloppy narrative voice undermines an otherwise rigorous pipeline.

Three failure modes this ADR is built to prevent:

1. **Sell-side drift.** LLMs trained on financial corpora default to "buy/hold/sell with target price $X" prose. That voice is incompatible with owner-operator decision-making and is explicitly forbidden by CLAUDE.md §"Bias awareness".

2. **Confidence laundering.** LLMs naturally smooth over data gaps, paraphrase uncertainty, and write fluent prose around weak evidence. Every smoothed-over `data_gap` becomes a silent hallucination at the verdict layer.

3. **Lattice amnesia.** Without explicit prompt-level enforcement, the LLM picks one or two mental models (usually moat + valuation) and ignores the rest. Inversion in particular is almost never produced unprompted — it must be *demanded* in the output structure.

This ADR locks the personality at the prompt-contract layer so future authors of `narrative.py` cannot accidentally produce sell-side prose with a Munger veneer.

---

## 1. Decision

### 1.1 Constraint contract

The narrative call is a pure function:

```
narrative(scorecard: ScorecardJSON, ticker: str) -> NarrativeMarkdown
```

- **Input**: the structured scorecard already produced by `deepdive/scorecard.py` (deterministic). Includes framework scores, signals, ROIC views, PT methodology, ICA/PSA/BEW results, data_gaps, fetch_gaps. **No raw 10-K text, no analyst transcripts, no third-party narrative.**
- **Output**: markdown matching the structure in §1.4. No JSON, no auxiliary objects.
- **Side effects**: none. Persists nothing. Caller logs the (input_hash, output_hash, model_id, prompt_version) for audit.

The LLM never produces a number that isn't already in the scorecard. The function contract enforces this — see §1.6 anti-hallucination rule.

### 1.2 Model & caching

| Concern | Decision |
|---|---|
| Model | `claude-opus-4-7` for the narrative output. Sonnet is acceptable as a cheaper fallback for batch screener narratives; Opus is required for dive-level narrative where reasoning depth matters. |
| Prompt caching | System prompt + the personality block are stable across calls — both go in the cached prefix. Per-ticker scorecard goes after the cache breakpoint. Cache hit rate target: ≥90% across a screener batch run. |
| Extended thinking | Enabled with a 4K thinking budget. The lattice + inversion-first ordering produces materially better output when the model can think before drafting. |
| ANTHROPIC_API_KEY missing | `narrative()` raises `NarrativeUnavailableError`. Caller must catch and emit a "narrative skipped — no API key" placeholder. Does NOT fall back to a different LLM provider (CLAUDE.md "OpenAI / FMP / Alpha Vantage NOT used"). |

### 1.3 System prompt skeleton (binding spec)

The system prompt has four blocks, in this order. Wording can be polished at implementation time but the *content* of each block is non-negotiable.

```
[BLOCK 1 — STANCE]
You are an owner-operator. Every paragraph you write is read by someone
deciding whether to put personal capital at risk for the next decade.
Write as someone who would buy 100% of this business if the market
closed tomorrow — or refuse to. There is no third state called "trade".

You are NOT a sell-side analyst. You are NOT a quant optimising a
backtest. You are NOT a banker pitching a deal. You do not produce
target prices. You do not say "buy" or "sell". The only verdicts
permitted are: WATCHLIST WITH TRIGGERS / EXCLUDE WITH REASON /
RESEARCH-ONLY (insufficient data or inversion fails).

[BLOCK 2 — LATTICE]
Reason through Charlie Munger's latticework, in this order:
  1. INVERSION (mandatory FIRST, before any synthesis): "what makes
     most stocks losers, and does this one share those traits?"
  2. CIRCLE OF COMPETENCE: state explicitly what is understood and
     what is not. "Unknown" is a first-class output.
  3. MOAT DIRECTION (Helmer 7 Powers): name the specific Power if
     present, and answer "is the moat WIDENING, FLAT, or NARROWING?"
     Direction beats width.
  4. CAPITAL ALLOCATOR (Thorndike 8 traits): score the management
     team trait-by-trait. Cite specific signals from the scorecard.
  5. LUNCH-EATING TEST: would a $1B-funded, top-talent challenger
     displace this company in 5 years? Answer concretely.
  6. PROBABILISTIC: state the base rate for this profile and the
     conditional probability given the divergent signals.

[BLOCK 3 — DATA DISCIPLINE]
Every number you cite must appear verbatim in the scorecard JSON
provided in the user message. If you reference a metric not in the
scorecard, you have failed the contract. If the scorecard contains
a `data_gaps` array, every gap appears verbatim in your "Data gaps"
section — you do not paraphrase, summarise, or reduce. The gap is
the signal.

The methodology block (ADR-022) tells you the source provenance for
every metric. If GAAP and non-GAAP ROIC come from the same source
(SEC 10-K XBRL — they always do today), say so. If a future
scorecard declares mixed sources, surface that as the headline
warning, not a footnote.

[BLOCK 4 — VOICE]
Plain. Direct. Owner-operator vocabulary. No hedging adverbs
("potentially", "arguably", "perhaps"). No filler ("it is worth
noting", "it should be considered"). No sell-side phrases
("compelling opportunity", "attractive entry point", "structural
tailwinds"). State the case, name the inversion, declare the
verdict in the constrained vocabulary, list the gaps. Done.
```

### 1.4 Mandatory output structure

Every narrative output has these sections, in this order, with these names. Missing a section is a contract violation.

| # | Section | Required content |
|---|---|---|
| 1 | **Owner-operator answer** | One sentence. Would you own 100% for 10 years? Yes / No / Not yet — pick one. |
| 2 | **Inversion** | One paragraph. The specific failure modes for this profile, and how many of them this company shares. |
| 3 | **Moat direction** | Specific Helmer Power named (or "no Power identified"). One word for direction: WIDENING / FLAT / NARROWING. The PT-ROIC trajectory across periods is the primary evidence. |
| 4 | **Capital allocator** | Outsiders trait count out of 8, with the named gaps. References to specific scorecard signals (CEO equity %, dilution YoY, debt issuance timing). |
| 5 | **Lunch-eating test** | Two-three sentences. Would a $1B-funded challenger displace this in 5 years? What specifically prevents it (or doesn't). |
| 6 | **Triggers to watch** (only if §1 = "Not yet") | Bulleted list of *observable* future events that would change the verdict. Each trigger references a specific scorecard field. |
| 7 | **Data gaps** | The `data_gaps` array from the scorecard, verbatim. Do not summarise. Do not omit. |
| 8 | **Verdict** | One of: `WATCHLIST WITH TRIGGERS` / `EXCLUDE WITH REASON: <reason>` / `RESEARCH-ONLY: <reason>`. Nothing else. |

### 1.5 Forbidden language

Hard-banned in output. The implementation should include a post-generation lint that strips or rejects responses containing any of these:

- `buy`, `sell`, `hold` (as verdicts)
- `target price`, `price target`, `fair value $X`, `intrinsic value $X` (verdict-shaping numerical claims)
- `compelling`, `attractive entry`, `structural tailwind`, `secular growth story`, `disruptive`, `category-defining`
- `it should be noted`, `it is worth considering`, `arguably`, `potentially`, `perhaps`
- Any phrase ending in "headed into earnings" or "ahead of the print"
- Any sentence that names a multi-bagger return target without naming the inversion that would prevent it

### 1.6 Anti-hallucination contract

Two enforcement layers:

1. **Prompt-level**: §1.3 Block 3 requires every numeric claim to map to the scorecard. Caller passes the scorecard inline; LLM is told "your only source is the JSON you were given."
2. **Post-generation lint**: a deterministic check that every monetary value, percentage, and ratio in the output appears in the scorecard JSON within ±0.5% rounding tolerance. Output failing the lint is rejected and the call retries once with a stricter system prompt; second failure raises `NarrativeContractViolation`.

The lint cost is trivial relative to the model call. The point is to make hallucination *systemically impossible*, not just culturally discouraged.

### 1.7 Token budget envelope

| Component | Target |
|---|---|
| System prompt (cached) | ~1.5K tokens |
| Scorecard input | ~3-5K tokens |
| Extended thinking | ≤4K tokens |
| Markdown output | ~600-1000 tokens (covers all 8 sections without bloat) |

A narrative call that produces >2000 output tokens is over-writing. The lint should warn (not reject) on excess output length.

### 1.8 Test coverage requirement

Before `narrative.py` ships, three test categories must pass:

1. **Contract tests** — feed canned scorecards covering each verdict path (clean WATCHLIST, EXCLUDE on inversion failure, RESEARCH-ONLY on data gaps). Assert all 8 mandatory sections present, verdict in the constrained vocabulary, no forbidden phrases.
2. **Anti-hallucination tests** — feed a scorecard with NO debt-related metrics; confirm the output never mentions debt levels. Feed a scorecard with `data_gaps: ["X is missing"]`; confirm the gap appears verbatim in §7.
3. **Personality tests** — feed an obvious-buy and an obvious-exclude scorecard. Confirm the obvious-exclude output explicitly inverts and names the failure modes; confirm the obvious-buy output still produces inversion + lunch-eating test (lattice can never be skipped just because the verdict is positive).

Tests use `respx` to mock the Anthropic SDK call and feed deterministic responses for the anti-hallucination + contract tests. Personality tests can use `pytest.mark.live` and call the real model when explicitly opted in.

---

## 2. What this ADR does NOT do

- Does **not** implement `narrative.py`. That's Phase 6. This ADR pins the spec so the eventual implementation cannot drift from CLAUDE.md §ANALYTICAL PERSONALITY.
- Does **not** introduce a second LLM call site. The "AI layer boundary" rule (CLAUDE.md) stands — `narrative.py` remains the sole permitted Anthropic SDK consumer.
- Does **not** change the data path. Frameworks, overlays, screener, scheduler all stay deterministic.
- Does **not** add multi-provider fallback. ANTHROPIC_API_KEY missing → narrative skipped, full stop. No OpenAI, no Mistral, no Cohere.

---

## 3. Anti-patterns this ADR forbids

| Anti-pattern | Why forbidden |
|---|---|
| LLM call from any module other than `deepdive/narrative.py` | CLAUDE.md AI-layer-boundary rule + ADR-022 source provenance |
| Narrative output containing a target price | §1.5 + Outsiders-CEO bias toward FCF/share, not target-price sell-side prose |
| Narrative output omitting the inversion section | §1.4 — the inversion IS the personality. Without it, the output is sell-side prose with Munger ornament |
| Paraphrasing or summarising `data_gaps` | §1.4 §7 — the gap is the signal; smoothing it over is hallucination by reduction |
| LLM call that doesn't use prompt caching | §1.2 token cost discipline; uncached calls violate the screener-batch economics |
| "BUY" / "SELL" / "HOLD" verdicts | §1.5 — owner-operator lens has no third state called "trade" |
| Adjusting numerical claims to fit narrative tone | §1.6 — every number must round-trip to the scorecard within ±0.5% |
| Using extended thinking to "explore" before drafting in a non-deterministic order | §1.3 Block 2 — inversion is mandatory first; thinking that synthesises before inverting violates the order rule |
| Multi-call narrative (call once for moat, once for valuation, etc.) | One call per dive. Lattice is meant to be reasoned through holistically, not compartmentalised |

---

## 4. Implementation checklist (for Phase 6 PR)

When `narrative.py` ships, the PR must include:

- [ ] System prompt with all four blocks from §1.3, version-tagged (e.g. `PROMPT_VERSION = "narrative-v1"`)
- [ ] Pydantic v2 model for `ScorecardJSON` input (matches what `deepdive/scorecard.py` already produces)
- [ ] Post-generation lint with deterministic numeric round-trip check (§1.6)
- [ ] Forbidden-phrase regex set (§1.5) loaded from a `_FORBIDDEN.txt` resource so updates don't require code changes
- [ ] Three test categories from §1.8
- [ ] CLI flag `invest dive TICKER --narrative` enabling the call (default OFF — opt-in, per CLAUDE.md lazy-load principle)
- [ ] Persistence: narrative output written to `DeepDiveRun.narrative_md` + `narrative_prompt_version` columns; Alembic migration
- [ ] Audit log: `(ticker, run_id, prompt_version, model_id, input_hash, output_hash, lint_failures)` to a `narrative_audit_log` table
- [ ] Documentation update in CLAUDE.md §"AI layer boundary" — link to this ADR

---

## 5. Open questions (deferred until implementation)

- Should narrative be generated for every dive automatically, or only on demand? **Default: opt-in** (lazy-load principle). Revisit if narrative cost ends up trivial relative to dive value.
- Should narrative output be diffed across periodic re-runs to surface "what changed"? Useful for the eventual Boardroom feature but out of scope here.
- Multi-ticker comparison narratives ("rank these 5 by inversion-survival") — separate function, separate ADR. Don't try to make `narrative()` do this.
- Confidence calibration via self-evaluation prompt (LLM rates its own output 1-10 on lattice coverage) — appealing, but adds another call and another failure mode. Defer.

---

## 6. References

- CLAUDE.md §ANALYTICAL PERSONALITY — source of truth for the lattice; this ADR is its enforcement layer
- CLAUDE.md §"AI layer boundary" — the location constraint this ADR's behavioural contract sits inside
- ADR-021 — economic ROIC adjustment methodology that the narrative must respect
- ADR-022 — methodology disclosure & source provenance that the narrative must surface
- Munger, *Poor Charlie's Almanack* — latticework + Standard Causes of Human Misjudgement
- Thorndike, *The Outsiders* — the 8 capital-allocator traits §1.3 Block 2 cites (epistemic note per CLAUDE.md: qualitative lens, not return-prediction evidence)
- Helmer, *7 Powers* — the moat taxonomy §1.4 §3 cites
- Anthropic prompt caching docs — engineering guidance for §1.2 cache discipline
