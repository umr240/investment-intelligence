# ADR-032 — Project-Local Skills for Routine-Task Workflows

| Field | Detail |
|---|---|
| **Status** | **Accepted — Phased** (pattern decided; ≤3 starter skills authored in Phase 1, rest deferred) |
| **Date** | 2026-05-15 |
| **Provenance** | User intervention 2026-05-15 after the SHOP / INTA dive cycle: *"do we need an ADR for surfacing some of the routine tasks into skills instead?? or perhaps use /loop for good use?? I'm thinking in terms of token management, data integrity, latency, quality, accuracy, speed of execution. I don't see any skills … by skills I mean like claude.ai skills but here in the codebase to use skills??? instead of building agents, perhaps build the skills to build agents???????"* |
| **Related** | ADR-022 (Methodology disclosure), ADR-023 (Narrative personality), ADR-024 (Mental-models library), ADR-031 (Data Gap Register), CLAUDE.md §"AI layer boundary" |
| **Preserves** | CLAUDE.md determinism rule; ADR-031 §4.1 "Architectural moat is non-negotiable"; the canonical two-Anthropic-call-sites limit (`deepdive/narrative.py`, `deepdive/external_signals.py`). |
| **Does NOT decide** | Which specific routine tasks become skills beyond the three starter skills authored in Phase 1. Additional skills are authored on the rule-of-three trigger (§5). |

---

## 0. Why this ADR exists

Across the last two working sessions (2026-05-14, 2026-05-15) the same patterns repeated:

- User asks for X (deep-dive a ticker, audit data completeness, refetch insider transactions)
- Claude derives the workflow from CLAUDE.md + memory + tool listing, every session, from scratch
- The workflow takes 4-10 tool turns to execute, with variance in what guardrails get applied each time
- Some failures repeat (e.g., the FY2024 10-K/A amendment overwrite was discovered mid-flow this session, after I had run a non-`--force` refresh and tanked the composite from 6.32 → 4.12)
- Token consumption per session is significant — CLAUDE.md alone is ~9k tokens; framework + scorecard context reads add 30k+

This is not a bug in Claude; it is a **missing-abstraction problem** in the codebase. The routine tasks have no codified workflow — every session re-derives them, which means every session has variance.

The user's framing — *"build skills to build agents"* — is the right inversion. **Skills are deterministic, single-concern, testable.** Agents are non-deterministic and harder to reason about. Compose deterministic primitives into the non-deterministic orchestrator, not the other way around.

This ADR formalises the skill pattern, defines the contract, and ships a starter set. It does NOT mandate that every routine task become a skill — the rule-of-three antipattern from `mental_models/engineering/rule_of_three.md` governs new skill authoring: *use the workflow three times before extracting it.*

---

## 1. The decision

### 1.1 Adopt project-local skills as the canonical workflow-codification pattern

Skills live at `.claude/skills/{skill-name}.md`. Each skill is:

- **Markdown with YAML frontmatter** — the frontmatter is the contract; the body is the prompt/instructions
- **Invocable by name** — Claude calls `Skill(skill="dive-complete", args="SHOP")` rather than re-deriving the workflow
- **Single-concern** — one skill = one workflow. No god-skills.
- **Composable** — skills can call CLI subcommands and other skills; they can NOT call new Anthropic endpoints
- **Versioned in git** — skill files are checked in, change-tracked, code-reviewed like any other code

### 1.2 Adopt /loop and /schedule as the runtime invocation patterns

The Claude Code harness already provides `/loop` (within-session recurring invocation) and `/schedule` (cross-session cron). Skills are the unit those orchestrators run. The composition:

```
SKILL = "what to do, deterministically"  →  defined in .claude/skills/
LOOP/SCHEDULE = "when to run it"          →  harness orchestration
AGENT = "decide which skills, compose"    →  emerges naturally from skill-as-primitive
```

### 1.4 The regression-vector framing (user intervention 2026-05-15)

After the §1.1/1.2 pattern was drafted, the user raised: *"there won't be any regression with the current deep dive ticker analysis and code with the transition to skill? the goal is still 100% data completeness, data integrity, quality, accuracy, speed of execution"*. The answer must distinguish what is **architecturally guaranteed** from what is **skill-authoring-discipline**.

**Architecturally guaranteed — zero regression possible:**

| Layer | Why immune |
|---|---|
| F1-F7 framework code | Skill invokes `invest dive`, which invokes framework code, same as today. Bit-identical inputs → bit-identical outputs. |
| `data/pipeline.py` + companyfacts parser | Same indirection. Skill is a CLIENT, not a parallel implementation. |
| Database schema + persistence | DB writes go through the unchanged CLI pipeline. |
| Composite scoring formula | Pure deterministic function of persisted Financial/Company rows; skill doesn't touch the inputs. |
| Overlay logic (ICA/PSA/BEW/SIM) | Invoked by `invest dive --auto-overlays`, same as today. |
| `external_signals` isolation (ADR-031 moat) | Skill is a CLIENT of `deepdive/external_signals.py`, not a parallel extractor. |

**Three regression vectors that DO exist (skill-authoring-discipline, not architectural):**

| Vector | Description | Mitigation |
|---|---|---|
| **1. Wrong workflow in skill body** | Skill author hardcodes `--tier 2` when sometimes Tier 1 is needed; omits `--force` when a 10-K/A is present | §9.1 shadow-mode validation; §2.1 `preconditions` testable assertions |
| **2. Wrong skill invoked for user intent** | Claude invokes heavy `/dive-complete` when user only asked a cheap score-card query | §2.1 mandatory `do_not_invoke_when:` list (min 3 negative examples) |
| **3. Skill drift vs CLI signature** | CLI rename / flag-removal silently breaks the skill 6 months later | §10 #9 CI signature-compatibility check |

The deeper guarantee: **skills NEVER replace the CLI; they wrap it.** `invest dive SHOP --tier 2 --force --auto-overlays` and `/dive-complete SHOP` produce the same composite, the same DeepDiveRun row, the same persisted artifacts. The skill is a CHECKLIST over the CLI, not a re-implementation.

The judgment-in-edge-cases concern (e.g., "noticed FY2024 amendment overwrite mid-flow this session") is addressed by encoding the discovery as a postcondition delta check (see §3.1 `/dive-complete` postconditions).

### 1.5 Preserve all existing invariants

The skill layer is **additive only**:

- CLAUDE.md §"AI layer boundary" — unchanged. Only `deepdive/narrative.py` and `deepdive/external_signals.py` can call Anthropic. Skills that need LLM work invoke those modules; they do not open new call sites.
- ADR-031 §4.1 architectural moat — unchanged. Skills that touch supplementary data go through the `external_signals` channel; they do not write to canonical Financial / Company columns.
- ADR-022 methodology disclosure — unchanged. Skills that produce dive output cite source provenance via the same display layer (`_render_external_signals`, `_render_roic_summary`, etc.).
- ADR-024 mental-models library — unchanged. Skills can reference mental-model slugs but they do NOT replace lattice reasoning in `deepdive/narrative.py`.
- Determinism rule — skill bodies are textual instructions, not new code paths. The deterministic data path (EDGAR XBRL → DB → frameworks) is untouched.

---

## 2. The skill schema

### 2.1 Frontmatter contract

Every `.claude/skills/{name}.md` file MUST have this frontmatter:

```yaml
---
name: {slug-in-kebab-case}        # invoked as Skill(skill="<name>")
description: |
  {One paragraph. What it does, WHEN to invoke (the triggers), WHEN NOT to.}
do_not_invoke_when:                # MANDATORY — minimum 3 negative examples (Vector 2 mitigation, §1.4)
  - {one-line example of when NOT to invoke this skill}
  - {another}
  - {another}
arguments:
  - name: {positional or named}
    type: {ticker | path | text | enum:A,B,C}
    required: true | false
    description: {one-line}
preconditions:                     # MUST hold before skill runs
  - {testable assertion, e.g. "Company row exists for TICKER"}
postconditions:                    # MUST hold after skill runs (success path)
  - {testable assertion, e.g. "DeepDiveRun row created with composite_score not null"}
side_effects:                      # what changes outside the skill's return value
  - {DB write | filesystem write | network call | LLM token spend}
dangerous: false | true            # true → skill must request explicit user confirmation
token_budget_estimate:             # rough cap; if exceeded the skill should report and bail
  prompt: {tokens}
  completion: {tokens}
cost_estimate_usd: {dollars}       # per invocation; null if free
permitted_anthropic_calls:         # which call sites this skill is allowed to invoke
  - {none | narrative.py | external_signals.py}
related_adrs:
  - {ADR-XXX}
mental_models:                     # optional — slugs from mental_models/ this skill embodies
  - {slug}
shadow_mode_until:                 # date string OR null — see §9.1
  {YYYY-MM-DD or null when shadow period has been satisfied}
version: {semver, e.g. 1.0.0}
last_reviewed: {YYYY-MM-DD}
---
```

The `do_not_invoke_when:` list is non-negotiable. Vector 2 of the regression analysis (§1.4) is *"Claude invokes the wrong skill for the user's intent"* — for example, invoking `/dive-complete SHOP` (5-min, heavy) when the user only asked *"what's SHOP's NRR?"* (a one-second score-card query). Each negative example anchors the skill against an over-invocation pattern, exactly the same way `mental_models/core/inversion.md` requires every model to declare its inversion form.

The `shadow_mode_until:` field gates the skill into a verification-heavy mode (§9.1). It exists explicitly to prevent Vector 1 regressions during a skill's first 2 weeks.

### 2.2 Body structure

The body is markdown. It is read by Claude when the skill is invoked. Sections (in this order):

1. **What this does** (3-5 sentences, plain English)
2. **Workflow** (numbered steps — each step is one tool call or one decision)
3. **Pre-flight checks** (what to verify before running, with the exact tool calls)
4. **Failure modes** (what can go wrong, how to detect, what to surface to the user)
5. **Audit trail** (what gets persisted; where to find it later)
6. **Examples** (1-3 concrete invocations with expected output)

### 2.3 Naming convention

Skill names are lowercase, kebab-case, verb-first when imperative, noun-first when query-only:

- `dive-complete` (imperative — runs the dive)
- `audit-completeness` (imperative — runs the audit)
- `data-gap-register` (query-only — surfaces the register)

Skills MUST NOT shadow existing CLI subcommand names. The CLI namespace is canonical; skill names are typically `verb-noun-modifier` to distinguish.

### 2.4 The `dangerous: true` discipline

Any skill that:
- Deletes DB rows (e.g., `refetch-form4` — wipes 153 rows then refills)
- Force-overwrites cached state (e.g., `--force` refreshes that ignore the year-coverage gate)
- Spends Anthropic tokens above ADR-031's $1/invocation soft ceiling
- Pushes / commits to remote infrastructure

MUST set `dangerous: true` in frontmatter. Claude is then required to:
1. Surface what the skill will do BEFORE invoking it (one-line description from the frontmatter)
2. Ask the user for explicit confirmation
3. Log the user's authorisation in the skill's audit trail

---

## 3. The starter-skill catalogue (Phase 1 — author now)

These three skills are authored in Phase 1 because the work to derive each has been executed 3+ times across the last two sessions (rule-of-three satisfied).

### 3.1 `/dive-complete TICKER`

Wraps the full deep-dive cycle that this session executed for SHOP at least 4 times.

| Aspect | Value |
|---|---|
| Triggers | "deep dive TICKER", "full dive on TICKER", "dive TICKER with completeness" |
| Workflow | (1) Run `invest data gaps TICKER`; (2) Run `invest dive TICKER --tier 2 --force --auto-overlays`; (3) Render scorecard with provenance |
| Preconditions | Company row exists; if 10-K/A filed in last 30 days → log warning (the FY2024-overwrite reason for `--force`) |
| Postconditions | DeepDiveRun row created; `data_completeness=1.0` or gaps explicitly logged |
| Side effects | DB writes; no LLM calls; ~SEC EDGAR rate-limit budget |
| Dangerous | false |
| Token budget | ~3k prompt, ~1k completion |
| Cost | $0 (deterministic) |
| Permitted Anthropic | none |

### 3.2 `/audit-completeness TICKER`

Wraps the gap-classification analysis I wrote ad-hoc in this session.

| Aspect | Value |
|---|---|
| Triggers | "audit gaps for TICKER", "what's missing for TICKER", "data completeness check" |
| Workflow | (1) Query Company-level field coverage; (2) Query Financial-row-level coverage; (3) Cross-reference each gap with ADR-031 §1.2 register; (4) Classify each missing field by root cause A-E; (5) Render table |
| Preconditions | Company row exists; ≥1 Financial row |
| Postconditions | Returns structured gap inventory with classifications |
| Side effects | Read-only; no writes |
| Dangerous | false |
| Token budget | ~2k prompt, ~1.5k completion |
| Cost | $0 |
| Permitted Anthropic | none |

### 3.3 `/external-signals TICKER`

Wraps the `deepdive/external_signals.py` extractor with the ADR-031 §4.4 cost-ceiling guard.

| Aspect | Value |
|---|---|
| Triggers | "extract external signals for TICKER", "fetch NRR/ARR for TICKER via LLM" |
| Workflow | (1) Check current monthly Anthropic spend (DB query); (2) If under $100/mo: fetch 8-K EX-99.1 → `extract_signals_via_llm` → persist; (3) Render External Signals panel |
| Preconditions | Company row exists; CIK populated; user has acknowledged the LLM-spend implication |
| Postconditions | ExternalSignalRecord rows persisted with full audit trail (per ADR-031 §4.3 criteria) |
| Side effects | DB writes; **Anthropic token spend** (~$0.03/invocation) |
| Dangerous | true (token spend) |
| Token budget | ~5-9k prompt, ~500 completion (per `external_signals.py` measurements) |
| Cost | ~$0.03 per invocation |
| Permitted Anthropic | external_signals.py |

---

## 4. Deferred skills (Phase 2+ — author on rule-of-three trigger)

Skills NOT authored now but pre-identified as future candidates. They are listed for inventory only — none ship until the workflow has been executed 3+ times.

| Skill (proposed) | Wraps | Promotion trigger |
|---|---|---|
| `/refetch-form4` | The Form-4 destructive refetch with issuer filter | After the 3rd ticker we discover has corrupt insider data |
| `/mic-parse` | Canadian Management Information Circular ownership extraction | After 3 Canadian-FPI dives need CEO equity |
| `/screen-and-watchlist-audit` | Diff screener top-N against watchlist; propose changes | After 3 quarterly screener reviews |
| `/data-quality-report` | Universe-level gap stats (the ADR-031 §1.2 evidence script) | After we revisit ADR-031 evidence 3 times |
| `/narrative-with-grounding` | Run `deepdive/narrative.py` + verify all citations resolve to scorecard fields or external_signals rows | After 3 narrative-validation cycles |
| `/cost-budget-status` | Show MTD Anthropic spend across narrative + external_signals + chat | After we hit the $100/mo ceiling once and have to investigate |

Each row is a hypothesis until we have rule-of-three evidence.

---

## 5. The rule-of-three discipline for new skills

A new skill is authored only when:

1. The workflow has been executed **3 or more times** across sessions (not within a single session — drift between sessions is the signal)
2. Each prior execution had **variance** in tool sequence or guardrail application (i.e., the codification pays off)
3. The workflow can be expressed as a deterministic recipe — branching is OK, but the branches must be explicit decisions, not vibes

This guard exists because **every skill is a maintenance liability**:

- When the underlying CLI subcommand changes signature, the skill needs to update
- When a new framework is added, skills that include "render full scorecard" need to know
- When ADR-031's gap register grows, skills that classify gaps need to update §1.2 reference

Past projects (cross-referenced in the user's lattice notes) accumulated dead skills faster than live ones once the rule-of-three discipline was dropped. We will not repeat that.

---

## 6. Composition with /loop and /schedule

### 6.1 /loop — within-session recurring invocation

Use case: an active working session where Claude is babysitting some recurring task. Example: earnings-day monitoring.

```
/loop 1h /dive-complete SHOP   # refresh SHOP scorecard hourly during the user's session
```

The /loop harness pauses Claude until the next interval, then re-invokes the skill. Cache stays warm if interval < 5 min; cold otherwise (per ADR-031 §3.2 token-cost analysis).

Use cases that warrant /loop:
- Pre-earnings monitoring of a single ticker
- Polling a slow-running data refresh until complete
- Watching `invest scheduler status` for the warehouse job to finish

Use cases that DON'T warrant /loop:
- "Refresh once a week" — that's /schedule, not /loop
- "Re-derive a scorecard every 5 seconds" — that's a polling antipattern
- Anything that runs faster than the cache-TTL of the underlying expensive op

### 6.2 /schedule — cross-session cron

Use case: persistent recurring work that runs whether or not the user is in session. Example: nightly screener refresh.

```
/schedule "0 6 * * MON" /screen-and-watchlist-audit
/schedule "0 0 1 */3 *" /external-signals-universe-refresh
```

The /schedule harness owns the cron daemon; the skill is the unit of work; the agent that runs is a fresh Claude instance with no prior context — which is exactly why the skill abstraction matters (no shared session state to rely on).

Use cases that warrant /schedule:
- Monday-morning watchlist refresh
- Quarterly external-signals universe refresh
- Daily data-completeness audit on the active portfolio

Use cases that DON'T warrant /schedule:
- Anything that costs >$10/invocation (manual-approval gate instead)
- Anything that depends on user-context (the cron Claude doesn't have it)
- Anything that's not idempotent (retries will compound errors)

### 6.3 Skills-to-build-agents composition

This is the heart of the user's framing. The pattern:

```
AGENT: nightly-portfolio-audit
  ↓
  invokes /audit-completeness PORTFOLIO_TICKERS (skill)
  ↓
  for each ticker with critical gaps:
    invokes /external-signals TICKER (skill, dangerous: true → cost-gated)
  ↓
  invokes /dive-complete TICKER (skill)
  ↓
  invokes /narrative-with-grounding TICKER (skill)
  ↓
  summarises findings; persists to DeepDiveRun + emails / Slacks user
```

The agent is the **decision layer** ("which tickers, in what order, with what cost ceiling"). Each skill is **deterministic and unit-testable**. When the agent fails, the failure mode is debuggable because each skill's pre/post-conditions are explicit.

Critically: the agent itself is NOT a skill. Agents are non-deterministic; skills are deterministic. We never compose agent-into-agent or skill-into-agent-into-skill. The hierarchy is one level deep: agent → skills. This keeps reasoning tractable.

---

## 7. Token / latency / quality analysis

### 7.1 Token cost — this session, post-hoc

The work executed in the 2026-05-15 session, naive Claude-orchestration (no skills):

| Workflow | Tool calls | Approx prompt tokens consumed | Wall-clock time |
|---|---|---|---|
| First SHOP dive | ~12 | ~40k (CLAUDE.md reads + scorecard reads + tool listings + ad-hoc Python) | ~25 min |
| SHOP gap audit + classification | ~9 | ~30k | ~20 min |
| Form-4 refetch (with issuer-filter design) | ~14 | ~50k | ~35 min |
| External-signals extractor design + build | ~22 | ~80k | ~60 min |
| Surfacing external signals in display | ~10 | ~35k | ~25 min |
| ADR-031 authoring | ~7 | ~25k | ~20 min |
| **Session total** | **~80** | **~260k+** | **~3.5 hours** |

If the first 3 workflows had been skills:

| Workflow | Tool calls (with skill) | Approx tokens (with skill) | Wall-clock |
|---|---|---|---|
| `/dive-complete SHOP` | 1 invoke + ~3 tools inside the skill | ~12k | ~5 min |
| `/audit-completeness SHOP` | 1 invoke + ~2 tools | ~8k | ~3 min |
| `/refetch-form4 SHOP` | 1 invoke + ~3 tools (with confirmation prompt) | ~10k | ~6 min |
| **Subtotal with skills** | ~14 | ~30k | ~14 min |
| **Saved** | **~80%** | **~80k tokens** | **~65 min** |

These savings compound across sessions because the skill is loaded on demand, not in every CLAUDE.md preamble.

### 7.2 Quality / variance

Concrete variance observed this session (would have been prevented by skills):

| Failure | Skill that would have caught it |
|---|---|
| First SHOP dive used `--force` (correct). Second dive omitted `--force`, hit 10-K/A overwrite bug → composite tanked. | `/dive-complete` always uses `--force` when a 10-K/A is in last 30 days |
| Initial Klaviyo Form-4 misattribution went undetected for one full session | `/refetch-form4` includes the issuer-filter validation step |
| Initial assumption that NRR could be extracted from 10-K MD&A for SHOP (wasted parser effort) | `/audit-completeness` classifies SHOP NRR as category A (issuer non-disclosure) up front |
| LLM extraction used wrong model ID first try (`claude-opus-4-5-20250929`, doesn't exist) | `/external-signals` skill body hardcodes the validated model ID |
| `data gaps SHOP` queried `Company.nrr_pct` (no such column) instead of `Financial.nrr_pct` | `/audit-completeness` skill body has the correct query path |

Each of these is a non-trivial failure that cost real time. Each would be a one-line skill-body decision.

### 7.3 Latency

Two latency wins from skills:

1. **Cognitive latency** — Claude doesn't re-derive the workflow. The skill's "Workflow" section is the recipe. Decisions Claude has to make per session drop from ~10 to ~1 (which skill to invoke).
2. **Tool-call latency** — Skill bodies can call multiple tools in a single response (parallelism encouraged). Today I make 8 sequential turns; a skill makes 8 parallel tool calls in one turn.

### 7.4 Accuracy

Skills enforce post-conditions. Example: `/dive-complete` post-condition is *"DeepDiveRun row created with composite_score not null"*. If the post-condition fails, the skill SURFACES it to the user instead of falsely reporting success — which is what happened to me twice this session (I declared work complete and then had to discover regressions next turn).

---

## 8. Architectural integrity — what skills must NOT do

(All of these are non-negotiable; violating any breaks the moat from ADR-031.)

1. **No new Anthropic call sites.** Skills that need LLM work invoke `deepdive/narrative.py` or `deepdive/external_signals.py`. Adding a third call site requires a new ADR.
2. **No new persistence paths.** Skills that touch supplementary data go through `external_signals` (ADR-031 §4.1 channel) or canonical CLI subcommands. They do not write to Financial / Company directly.
3. **No silent fallback.** When a skill encounters a missing precondition, it surfaces the gap; it does NOT fabricate a fallback value. Same discipline as `data_gaps[]` (CLAUDE.md determinism rule).
4. **No model-drift hiding.** Skills hardcode the validated model ID per ADR-031 §4.4 ("Default model: Sonnet 4.6"). When that changes, the skill's `version` bumps and `last_reviewed` updates.
5. **No retroactive composite-score changes.** A skill that introduces new data MUST NOT modify any historical FrameworkScore or DeepDiveRun composite. New data appends as a new run; old runs are immutable.
6. **No bypass of the `dangerous: true` confirmation.** If frontmatter says dangerous, Claude MUST ask for confirmation. No "user has already authorised this kind of operation in this session" shortcut.

---

## 9. Phased implementation plan

### Phase 1 — Pattern + 3 starter skills (this PR / next)

1. Create `.claude/skills/` directory
2. Write the schema reference at `.claude/skills/README.md`
3. Author the 3 starter skills:
   - `.claude/skills/dive-complete.md`
   - `.claude/skills/audit-completeness.md`
   - `.claude/skills/external-signals.md`
4. Update CLAUDE.md to reference the skill pattern (one sentence pointer to this ADR + the skills/ directory)
5. Smoke-test each skill in a fresh session to verify Claude finds and invokes correctly
6. **Author skill telemetry log** (§9.1.3 — required before shadow-mode is operational)

### 9.1 Shadow-mode validation (Vector 1 mitigation)

Every new skill enters **shadow mode** for the first **14 calendar days** after authoring. The `shadow_mode_until: YYYY-MM-DD` field in the frontmatter sets the explicit expiry date.

**What shadow mode does:**

When a skill is invoked while `shadow_mode_until` is in the future, the skill body MUST include an additional verification step immediately after the main workflow:

1. **Capture** — record the skill's output artifacts (composite_score, verdict, data_completeness, gap classifications, persisted row IDs) into a `skill_invocations` log entry
2. **Verify postconditions deterministically** — each postcondition is asserted via an explicit tool call (NOT a "looks right to me" judgment). Each pass/fail recorded.
3. **Delta-check against prior canonical output** — if a prior DeepDiveRun / scorecard / `external_signals` row exists for the same target, compute the diff. Material divergence (e.g., composite_score moves >1.0 between adjacent runs of the same skill within 24h) flags as anomaly.
4. **Surface anomalies loudly** — if any postcondition fails OR any delta-check flags, the skill's response to the user prepends: `[SHADOW-MODE ANOMALY] {skill_name} v{version}: {what diverged}` and includes a one-line root-cause hypothesis.

**Exit criteria from shadow mode:**

A skill exits shadow mode when **all** of these hold:
- ≥10 invocations recorded in `skill_invocations`
- 100% postcondition pass rate
- 0 delta-check anomalies (or all flagged anomalies traced to genuine source-data change, not skill bug — recorded with a `false_positive: true` annotation)
- Skill author has manually reviewed the 10 invocation records

When the criteria are met, the skill's `shadow_mode_until:` is set to `null` and `version` bumps minor (1.0.0 → 1.1.0 or higher).

**If the criteria fail:**
- Any postcondition failure OR unexplained anomaly → skill is suspended (frontmatter `version` gets a `-SUSPENDED` suffix; Claude refuses to invoke until human resolves)
- Author RC-analyses the failure, amends the skill, resets the 14-day clock, re-enters shadow mode

**Cost of shadow mode:** ~2× the deterministic work for the 14-day window (each invocation also runs verification). For `/dive-complete` and `/audit-completeness` this is zero LLM cost; for `/external-signals` it adds the same ~$0.03 per invocation a second time IF the verification re-runs the LLM call. To avoid that, `/external-signals` verifies by re-reading the persisted ExternalSignalRecord row and verifying the audit trail integrity (URL responds, accession parses, source_quote ≥30 chars), NOT by re-calling Anthropic.

### 9.1.1 The `skill_invocations` table

```python
class SkillInvocation(Base):
    __tablename__ = "skill_invocations"
    id = Column(Integer, primary_key=True)
    skill_name = Column(Text, nullable=False, index=True)
    skill_version = Column(Text, nullable=False)
    invoked_at = Column(DateTime, server_default=func.now())
    args_json = Column(Text)                       # serialised invocation args
    success = Column(Boolean, nullable=False)
    duration_seconds = Column(Float)
    tool_calls_count = Column(Integer)
    tokens_prompt = Column(Integer)
    tokens_completion = Column(Integer)
    cost_usd = Column(Float)
    postconditions_json = Column(Text)             # [{name, pass: bool, observed, expected}]
    shadow_mode_active = Column(Boolean, nullable=False, default=False)
    anomalies_json = Column(Text)                  # delta-check results, null if none
    false_positive_annotation = Column(Text)       # set by author after RC if needed
```

Added in a separate small alembic migration as part of Phase 1.

### 9.1.2 Concrete example — `/dive-complete` shadow-mode verification

For the SHOP case from this session:
- Invocation: `/dive-complete SHOP`
- Workflow executes, produces composite_score=6.32, verdict=WATCHLIST
- Verification step queries the DeepDiveRun row that was just written, confirms `composite_score IS NOT NULL`, `f1_score`, `f5_score`, etc. all present (10 deterministic asserts)
- Delta check: most recent prior DeepDiveRun for SHOP was at 6.32 composite. Δ = 0.0. No anomaly.
- Records `skill_invocations` row with `shadow_mode_active=true`, all postconditions pass
- Returns to user with the standard dive output (no anomaly banner)

If instead the FY2024-amendment bug had triggered (composite dropped 6.32 → 4.12):
- Delta check fires: |Δ| = 2.20 > 1.0 anomaly threshold
- Response prepends `[SHADOW-MODE ANOMALY] dive-complete v1.0.0: composite dropped 2.20 from prior run within 24h. Hypothesis: amendment 10-K/A may have overwritten FY2024 income-statement; investigate before relying on output.`
- skill_invocations row records `anomalies_json={delta: 2.20, prior_run_id: ..., this_run_id: ...}`
- The author (next morning) reviews, confirms the amendment bug, suspends the skill, RC-fixes it, resumes

### 9.1.3 What shadow mode is NOT

- It is NOT a parallel manual execution. The skill IS the workflow; there's no separate "manual run" to diff against. Verification is against deterministic postconditions and historical persisted artifacts.
- It is NOT a token-doubling penalty. For `/dive-complete` and `/audit-completeness`, verification is read-only DB queries.
- It is NOT permanent. The 14-day clock is a soft expiry; the skill graduates once 10 clean invocations are logged.

### Phase 2 — Hook integration (next sprint after Phase 1)

1. Decide /loop integration points (likely: pre-earnings monitoring, watchlist refresh)
2. Decide /schedule integration points (likely: Monday watchlist audit, quarterly external-signals refresh)
3. Author the cost-budget-status skill (needed before any /schedule rollout to enforce ADR-031 §4.4 ceiling)
4. Build skill telemetry — log invocations to a `skill_invocations` table so we can measure actual use

### Phase 3 — Rule-of-three evaluation (4-6 weeks after Phase 1)

1. Review skill_invocations table — which workflows have been executed 3+ times outside the existing 3 skills?
2. For each rule-of-three trigger, evaluate whether a skill should be authored (workflow stable? variance observed?)
3. Author 0-3 additional skills per evaluation cycle
4. Retire any Phase 1 skill that has been invoked <3 times in 4-6 weeks (the inverse of rule-of-three — dead skills are removed)

### Phase 4 — Agent composition (after Phase 3 has 6+ stable skills)

1. Identify recurring multi-skill workflows
2. Define the first agent (likely: `nightly-portfolio-audit`)
3. Constrain agents to one-level composition (agent → skills; never agent → agent)

---

## 10. Acceptance criteria for any new skill

Any future PR adding a `.claude/skills/{name}.md` file MUST satisfy:

1. **Frontmatter contract complete** — all fields from §2.1 present and validated
2. **Rule-of-three documented** — frontmatter `description` or body must reference the ≥3 prior executions that justify authoring
3. **Preconditions / postconditions testable** — each is a concrete assertion that can be verified by a tool call
4. **Token budget realistic** — measured against actual past executions, not estimated
5. **Permitted Anthropic calls explicit** — never `*`, never "any"; either `none`, `narrative.py`, or `external_signals.py`
6. **Coordination with related ADRs** — at minimum ADR-022 and ADR-031; others as applicable
7. **`dangerous: true` audit** — if the skill writes/deletes/spends, it's dangerous; no exceptions
8. **Idempotency declared** — body must state whether re-invocation is safe (most skills should be idempotent; non-idempotent skills must justify)
9. **CI signature-compatibility check** (Vector 3 mitigation) — a `pytest` test (`tests/test_skills/test_signature_compatibility.py`) loads each skill, regex-extracts every `invest …` invocation from the body, runs `invest <subcommand> --help` to verify the subcommand exists, and parses each `--flag` referenced in the skill against the help output to verify the flag exists. CI fails if any skill references a CLI surface that no longer exists. This is what prevents the "CLI rename silently breaks the skill 6 months later" failure mode.

```python
# tests/test_skills/test_signature_compatibility.py — sketch
import re
import subprocess
from pathlib import Path

INVEST_INVOCATION = re.compile(r'invest\s+([a-z\-]+)(?:\s+([^\n`]+))?')

def test_each_skill_invest_invocations_are_valid():
    for skill_path in Path(".claude/skills").glob("*.md"):
        if skill_path.name == "README.md":
            continue
        body = skill_path.read_text()
        for match in INVEST_INVOCATION.finditer(body):
            subcommand, args_line = match.group(1), match.group(2) or ""
            # Verify subcommand exists
            help_text = subprocess.check_output(
                ["uv", "run", "invest", subcommand, "--help"], text=True
            )
            # Verify each --flag referenced exists in help
            for flag_match in re.finditer(r'--[a-z-]+', args_line):
                flag = flag_match.group(0)
                assert flag in help_text, (
                    f"{skill_path.name}: invest {subcommand} no longer supports {flag}"
                )
```

---

## 11. Open questions

1. **Where does skill telemetry live?** A `skill_invocations` table (analogous to `dive_history`) is the cleanest answer but adds schema. Alternative: skills append to a flat JSONL log. Decision deferred to Phase 2.
2. **Should skill bodies be allowed to invoke other skills?** The naive answer is no (avoid recursion / cycles). But composition primitives like *"after dive, run completeness audit"* are pervasive. Decision: skills MAY invoke at most one other skill, and only via the Skill tool (no implicit composition). Cycles forbidden by convention.
3. **How do skills interact with the `Agent` tool's worktree isolation?** Some skills (refetch-form4) make destructive changes that should arguably go through a worktree first. Decision deferred — for Phase 1, skills run in-place; worktree integration is a Phase 3+ refinement.
4. **What's the policy on community-contributed skills?** A future contributor might want to add a skill specific to their workflow that doesn't generalise. Decision: skills MUST follow §10 acceptance criteria; non-generalising skills go in `.claude/skills/personal/` (gitignored) rather than `.claude/skills/` (versioned).
5. **Should skills also live in `.claude/agents/`?** No — the Agent tool's subagent_type catalogue is the harness's own thing. Project-local agents (if ever) get their own ADR.
6. **Do skills replace any existing CLI subcommand?** No. CLI subcommands are the canonical surface for users. Skills are the canonical surface for Claude. Both exist; the skill is a workflow over CLI commands.

---

## 12. Coordination with related ADRs

- **ADR-022 (Methodology disclosure)** — every skill that produces user-facing output MUST surface source provenance the same way as canonical dive output. No skill can launder data through display rendering.
- **ADR-023 (Narrative personality)** — `/narrative-with-grounding` (Phase 2+ skill) must respect ADR-023's reasoning-order constraint and grounding requirement. Skills do NOT bypass the narrative-LLM's discipline.
- **ADR-024 (Mental-models library)** — skills MAY declare which mental-model slugs they embody in `frontmatter.mental_models[]`. This is informational, not enforceable — but helps maintainers reason about why the skill exists.
- **ADR-031 (Data Gap Register)** — any skill that touches the supplementary-data channel MUST conform to §4.3 acceptance criteria. The starter `/external-signals` skill is the canonical example.
- **CLAUDE.md §"AI layer boundary"** — the two-Anthropic-call-sites rule is preserved verbatim. Skills are NOT a loophole.

---

## 13. Non-goals

- This ADR does NOT replace any framework, overlay, or pipeline behaviour
- This ADR does NOT mandate that every workflow becomes a skill (rule-of-three is the gate)
- This ADR does NOT prescribe a specific agent runtime; agents are deferred to Phase 4
- This ADR does NOT change CLI subcommand signatures
- This ADR does NOT introduce a third permitted Anthropic call site
- This ADR does NOT decide /loop / /schedule UI conventions — those are harness-level
- This ADR does NOT define the personal-skills mechanism in detail — that's a Phase 3+ open question

---

## 14. Implementation status (2026-05-15)

| Component | Status |
|---|---|
| `.claude/skills/` directory | ❌ NOT yet created — Phase 1 |
| `.claude/skills/README.md` (schema reference) | ❌ Phase 1 |
| `dive-complete.md` skill | ❌ Phase 1 |
| `audit-completeness.md` skill | ❌ Phase 1 |
| `external-signals.md` skill | ❌ Phase 1 |
| CLAUDE.md update (pointer to ADR-032 + skills/) | ❌ Phase 1 |
| `skill_invocations` table + alembic migration (§9.1.1) | ❌ Phase 1 (was Phase 2 — moved earlier to support shadow-mode) |
| `tests/test_skills/test_signature_compatibility.py` (§10 #9) | ❌ Phase 1 (CI gate before first commit) |
| Shadow-mode verification logic in each starter skill (§9.1) | ❌ Phase 1 (lives in skill bodies) |
| /loop integration | ❌ Phase 2 |
| /schedule integration | ❌ Phase 2 |
| Agent composition (Phase 4 — far future) | ❌ Phase 4 |
| ADR-032 itself | ✅ This document (amended 2026-05-15 with §1.4, §9.1, §10 #9 per user intervention) |

---

## 15. Summary in one sentence

**Skills codify the routine workflows that today re-derive themselves every session, paying ~80% in tokens, ~80% in latency, and unbounded variance in quality; we adopt the project-local skill pattern with strict invariants (no new LLM call sites, no new persistence paths, rule-of-three for new skill authoring, `dangerous: true` confirmation discipline), ship 3 starter skills, and defer everything else to rule-of-three-gated phased rollout.**

---

## 16. Subsequent amendments / extensions (added 2026-05-17)

After ADR-032 shipped, three follow-on ADRs extended the skill substrate to close Anthropic's "Don't Build Agents, Build Skills Instead" three-pillar (Evaluation / Versioning / Composability). Reading order: ADR-032 (this) → ADR-034 → ADR-035 → ADR-036.

| ADR | Pillar | What it adds | Extends section |
|---|---|---|---|
| **ADR-034** Skill versioning + lineage protocol | **Versioning** | Semver discipline + dated `changelog:` array + cross-skill chronological index (`.claude/skills/_lineage.md`) + CI validator (`tests/test_skills/test_version_lineage.py`) + CLI (`invest skill lineage [name] [--rebuild|--validate]`). Three invariants: §3.1 frontmatter version matches changelog head, §3.2 no duplicate versions, §3.3 date-monotonic entries. | Extends §9.1 (telemetry) + §10 (acceptance criteria) |
| **ADR-035** Skill evaluation protocol | **Evaluation** | Four eval dimensions: `frontmatter_structure` (mandatory) + `script_execution` (mandatory) + `output_quality` (permissive) + `triggering_accuracy` (deferred — LLM eval). Fifth dimension added by ADR-036 (`composability_consistency`, mandatory). CI gate (`tests/test_skills/test_evals.py`) + CLI (`invest skill eval [name] [--validate]`). | Extends §10 #9 (CI signature compatibility) |
| **ADR-036** Skill composability protocol | **Composability** | Optional `composes:` frontmatter block (skills + mcps + libraries) + three relations (`uses` / `suggests` / `extends`) + DAG validation (refs resolve, no self-loops, no cycles) + PEP-440 constraint format. CI test (`tests/test_skills/test_composability.py`) + CLI (`invest skill compose [name] [--validate]`). | New section — does not modify ADR-032 §2.1 frontmatter contract directly; the `composes:` field is additive optional |

### Test suite at ADR-036 ship (2026-05-16)

| Test file | Tests | Purpose | Source |
|---|---|---|---|
| `test_signature_compatibility.py` | 6 (some skipped per-skill) | CLI-surface stability (Vector 3 mitigation) | ADR-032 §10 #9 |
| `test_version_lineage.py` | 4 | Version-lineage invariants §3.1-3.3 | ADR-034 §3 |
| `test_evals.py` | 2 | Mandatory eval dimensions | ADR-035 §4 |
| `test_composability.py` | 3 | Composition graph validity | ADR-036 §3 |
| `test_mental_model_refs.py` | 3 | Documentary lattice refs (typo-catch, WARN-only) | — |
| **Total** | **18 tests** (16 pass + 2 skip) | All green at 2026-05-17 | — |

### Skill state at ADR-036 ship

- `audit-completeness` → v1.1.0 (was 1.0.4 pre-composability backfill)
- `dive-complete` → v1.1.0 (was 1.0.1)
- `external-signals` → v1.1.0 (was 1.0.0)

All three skills satisfy mandatory eval dimensions (frontmatter_structure, script_execution, composability_consistency).

### Linkage to telemetry

The `skill_invocations` table from §9.1.1 now carries `skill_version` populated from frontmatter at invocation time. This enables historical analysis: "did v1.0.4 of audit-completeness have a higher anomaly rate than v1.1.0?" — answerable via SQL without joining external state. ADR-034 §4 specifies that shadow-mode graduation entries cite the `skill_invocations` row range as evidence.

---

*Skills are deterministic; agents are not. Compose deterministic primitives into the orchestrator, not the other way around. The architectural moat — deterministic data canonical, LLM supplementary with provenance — remains intact at every level of composition.*
