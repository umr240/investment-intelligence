# Architecture decision records

Each ADR records one decision: the context, the options weighed, what was
chosen and why, and how it is verified. Smaller decisions live in
`../DECISIONS.md` as `DEC-nn` entries.

- **Numbering starts at ADR-016.** Earlier numbers were used before this
  repository existed and are not included here.
- **Amendments** keep the parent's number with a suffix: `ADR-023-A1` amends
  ADR-023. The parent ADR's status line names its amendments.
- **Status** is one of *Proposed* (written, awaiting sign-off), *Accepted*,
  *Superseded* (the status line names the successor) or *Draft*. A proposed
  ADR describes intent; the code may not do it yet.
- **Archived references.** Some ADRs cite probe scripts, plans or status
  snapshots that were retired when the repository was published. Those are
  marked *archived*; they survive in a private archive and are not needed to
  read the decision.

To add one, take the next free number, follow the shape of a recent ADR
(context, decision, alternatives, verification), and link it from any
`DEC-nn` entry or code comment that depends on it.

## Index

Generated from the ADR files; never edit it by hand:
`uv run --no-sync tools/gate/gate.py --write-adr-index`. The gate fails when it
is out of date.

<!-- adr-index:start -->
| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-016](ADR-016-screener-metadata-source.md) | Screener metadata source: FMP bulk screener replaces yfinance, SEC EDGAR for everything else | superseded | 2026-05-04 |
| [ADR-017](ADR-017-screener-as-warehouse-query.md) | Screener as warehouse query, not pipeline run | accepted |  |
| [ADR-018](ADR-018-dive-data-gap-task-fleet.md) | Dive-data gaps: per-gap deterministic task fleet | accepted |  |
| [ADR-019](ADR-019-polygon-as-plugin-source.md) | Polygon.io as a plugin source for price / momentum / technical tasks | accepted |  |
| [ADR-020](ADR-020-warden-pattern-for-mid-run-fallback.md) | Warden pattern for adaptive batched mid-run source fallback | accepted |  |
| [ADR-021](ADR-021-economic-roic-peters-taylor.md) | Economic ROIC adjustment: Peters-Taylor, not management non-GAAP | accepted |  |
| [ADR-022](ADR-022-methodology-disclosure-and-source-provenance.md) | Methodology Disclosure & Source Provenance | accepted |  |
| [ADR-023-A1](ADR-023-A1-narrative-contract-reconciliation.md) | Reconcile the Narrative Contract With What Shipped | accepted |  |
| [ADR-023](ADR-023-narrative-personality-spec.md) | Narrative Personality Spec for `deepdive/narrative.py` | accepted |  |
| [ADR-024](ADR-024-mental-models-library-and-composition.md) | Mental Models Library & Composition Pipeline | accepted |  |
| [ADR-025](ADR-025-ifrs-fpi-universe-support.md) | IFRS / FPI Universe Support | accepted |  |
| [ADR-026](ADR-026-ttm-mrq-fy-three-tier-data-freshness.md) | TTM / MRQ / FY three-tier data freshness model | accepted | 2026-05-11 |
| [ADR-027](ADR-027-damodaran-intrinsic-value-skill.md) | Damodaran Intrinsic Value skill | accepted | 2026-05-13 |
| [ADR-028](ADR-028-young-company-target-margin-dcf.md) | Young-Company Target-Margin DCF | accepted | 2026-05-13 |
| [ADR-029](ADR-029-sibling-outputs-epv-reverse-dcf.md) | Universal sibling outputs: EPV, Reverse DCF, Narrative Premium % | accepted | 2026-05-14 |
| [ADR-030-A1](ADR-030-A1-f7-regime-gate-amendment.md) | ADR-030 Amendment A1 — Extend Applicability Gating to F7 (and enforce its weight cap) | proposed |  |
| [ADR-030-A2](ADR-030-A2-f7-history-floor-vs-fetch-depth.md) | ADR-030 Amendment A2 — F7's history floor is unreachable at the default fetch depth | accepted | 2026-08-23 |
| [ADR-030](ADR-030-maturity-classifier-and-young-tier-routing.md) | Maturity classifier and young-tier routing | accepted | 2026-05-14 |
| [ADR-031-A1](ADR-031-A1-third-llm-call-site.md) | ADR-031 Amendment A1 — `deepdive/conversation.py` as a permitted LLM call site, and an enforced allow-list | accepted |  |
| [ADR-031](ADR-031-data-gap-register-and-supplementary-data-sources.md) | Data Gap Register & Supplementary Data Sources | accepted |  |
| [ADR-032](ADR-032-project-local-skills-for-routine-task-workflows.md) | Project-Local Skills for Routine-Task Workflows | accepted |  |
| [ADR-033](ADR-033-sec-first-source-hierarchy-and-compute-dont-pull.md) | SEC-First Source Hierarchy & Compute-Don't-Pull | accepted |  |
| [ADR-034](ADR-034-skill-versioning-and-lineage-protocol.md) | Skill Versioning + Lineage Protocol | accepted | 2026-05-16 |
| [ADR-035](ADR-035-skill-evaluation-protocol.md) | Skill Evaluation Protocol | accepted | 2026-05-16 |
| [ADR-036](ADR-036-skill-composability-protocol.md) | Skill Composability Protocol | accepted | 2026-05-16 |
| [ADR-037](ADR-037-f3-rd-effectiveness-disaggregation.md) | F3 R&D-effectiveness disaggregation | draft | 2026-05-18 |
| [ADR-038](ADR-038-non-sec-international-issuer-fundamentals.md) | Non-SEC International Issuer Fundamentals (Canadian + European + Australian + AIM) | draft | 2026-05-19 |
| [ADR-039](ADR-039-pluggable-fundamentals-source-port-and-sedar-adapter.md) | Pluggable `FundamentalsSource` Port + SEDAR+ Adapter (Canadian issuers) | accepted |  |
| [ADR-040](ADR-040-local-web-ui-fastapi-control-plane-and-frontend.md) | Local Web UI: FastAPI Control-Plane + Frontend Over the Existing CLI Engine | accepted |  |
| [ADR-041](ADR-041-jurisdiction-routing-and-esef-adapter.md) | Jurisdiction Routing Table + ESEF Adapter (EU/EEA issuers) | proposed |  |
| [ADR-042](ADR-042-greenwald-ladder-and-dual-engine-valuation.md) | Greenwald Ladder + Dual-Engine Intrinsic Value | proposed |  |
| [ADR-043](ADR-043-currency-correct-cost-of-capital.md) | Currency-Correct Cost of Capital + Market-Cap Normalisation | proposed |  |
| [ADR-044](ADR-044-data-contracts-on-refresh.md) | Data Contracts Checked on Every Refresh | accepted |  |
| [ADR-045](ADR-045-grounded-narrative-generation.md) | Grounded Narrative Generation: the Model Cites, Code Renders | accepted |  |
| [ADR-046](ADR-046-narrative-claim-and-language-lint.md) | Claim-to-Evidence and Language Lint for Narratives | proposed |  |
| [ADR-047](ADR-047-narrative-eval-harness.md) | Narrative Eval Harness: Golden Set, Deterministic Graders, Replay Gate | accepted |  |
| [ADR-048](ADR-048-llm-observability-and-prompt-versioning.md) | LLM Observability and Prompt Versioning (Local-First) | accepted |  |
| [ADR-049](ADR-049-narrative-cost-engineering.md) | Narrative Cost Engineering | proposed |  |
| [ADR-050](ADR-050-narrative-feedback-capture.md) | Narrative Feedback Capture | proposed |  |
| [ADR-051](ADR-051-read-only-mcp-server.md) | Read-Only MCP Server Over the Deterministic Engine | proposed |  |
| [ADR-052](ADR-052-multi-agent-narrative-panel.md) | Multi-Agent Narrative Panel (Experiment, Gated on Evals) | proposed |  |
| [ADR-053](ADR-053-point-in-time-backtest.md) | Point-in-Time Backtest With Multiple-Testing Control | proposed |  |
| [ADR-054](ADR-054-one-verdict-vocabulary.md) | One Verdict Vocabulary; Retire "Initiate" | accepted |  |
| [ADR-055](ADR-055-rejected-llm-techniques.md) | Retrieval-Augmented Generation and Other Rejected LLM Techniques | accepted |  |
| [ADR-056](ADR-056-hosted-read-only-demo.md) | Hosted Read-Only Demo From a Sanitised Snapshot | proposed |  |
| [ADR-057](ADR-057-external-signals-verification.md) | External Signals: Verify Before Storing | accepted |  |
<!-- adr-index:end -->
