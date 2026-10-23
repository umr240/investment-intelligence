# ADR-051 — Read-Only MCP Server Over the Deterministic Engine

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | Integration surface |
| **Extends** | ADR-040 (local control plane), CLAUDE.md MCP usage policy |
| **Provenance** | Proposal review 2026-10-21 |

---

## 1. Context

The engine is reachable through the CLI and the local FastAPI control plane.
An MCP client (Claude Desktop, Claude Code, other assistants) cannot query
it. CLAUDE.md's MCP policy covers *consuming* MCP servers during
development; nothing covers *exposing* one.

The trust-boundary rule still applies to any MCP client, because the client
is an LLM:

- **SECURITY §3:** filing text never enters a prompt.
- **SECURITY §2:** portfolio and watchlist data never enter a prompt.

## 2. Decision

### 2.1 Tools (v1, read-only)

| Tool | Wraps | Notes |
|---|---|---|
| `screen_warehouse` | `screener.query.run_screener` | Query parameters only; row cap |
| `get_scorecard` | the persisted `ScorecardView` | Latest stored dive; no refresh |
| `get_valuation` | the valuation service, `persist=false` | DB-only |
| `explain_score` | framework result + key signals | One framework per call |
| `list_data_gaps` | stored gaps for a ticker | |

Not in v1: anything that fetches from the network, spends LLM tokens or
writes (no `run_deep_dive`, no narrative). A later write tool would carry the
`dangerous: true` confirmation discipline (ADR-032 §2.4).

### 2.2 Shape

- `mcp_server/` (new): stdio transport, local only.
- It calls the same service functions as `api/app.py`. No business logic in the server (ADR-040 §0 item 1).
- Responses contain deterministic, public-derived fields only. No raw filing text, no portfolio or watchlist tables.

### 2.3 Dependency and configuration

- **New dependency:** the official MCP Python SDK. Flagged under SECURITY §5; pinned in `uv.lock`.
- **Registering the server** in a user's MCP client is a Tier-2 user action (CLAUDE.md).
- CLAUDE.md's MCP policy gains one paragraph on the exposed server.

### 2.4 What this ADR does NOT decide

- A remote (HTTP) transport. That would need auth (ADR-040 §0 item 4).

## 3. Inversion (mandatory)

- **An LLM client loops on tools.** Mitigations: read-only tools, row caps, no network, no token spend.
- **Company names are attacker-influenced text** (they come from filings). Accepted: names are short, and no instruction-bearing free text is returned.
- **Data looks like advice to the client's model.** Mitigation: every response carries the research-only disclaimer field.

## 4. Alternatives considered

- **Point MCP clients at the FastAPI docs:** clients cannot call it without a wrapper.
- **Expose write tools in v1:** rejected (§2.1).

## 5. Consequences

- Any MCP client can ask about screens and scorecards without leaving the trust boundary.
- One new dependency.

## 6. References

- ADR-040 §0, CLAUDE.md "MCP usage policy" and "Security & privacy"
