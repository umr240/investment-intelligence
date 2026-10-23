# ADR-056 — Hosted Read-Only Demo From a Sanitised Snapshot

| Field | Detail |
|---|---|
| **Status** | **PROPOSED — awaiting user sign-off.** Nothing implemented. |
| **Phase** | Public release |
| **Amends** | ADR-040 §0 item 4 (local-only; remote access "would need its own ADR with real auth") |
| **Depends on** | The public release, ADR-054 |
| **Provenance** | Proposal review 2026-10-21 |

---

## 1. Context

The repository is being prepared for public release. Readers cannot run
`localhost:5173`. A hosted demo crosses three standing rules:

- **ADR-040 §0 item 4:** the API binds to 127.0.0.1 with no auth.
- **SECURITY §7:** the database is local-only.
- **LLM spend:** a public endpoint that generates narratives lets strangers spend the author's API budget.

It also raises a data-licensing question. The README already flags Yahoo's
terms. Redistributing yfinance-sourced values on a public site may not be
permitted.

## 2. Decision

### 2.1 What the demo is

- Built from a sanitised snapshot by `invest export demo` (new). It is never the live database.
- **SEC-derived fields only**, unless the licence of another source is checked.
- **Pre-rendered** scorecards, valuations and narratives for a fixed showcase set of tickers.
- No portfolio or watchlist tables, and no exclusion-policy state, in the snapshot.

### 2.2 What it is not

- No write endpoints, no dives, no narrative or chat generation, no screener runs. Nothing a visitor does spends tokens or calls SEC.

### 2.3 Hosting (user decision)

- **(a)** A static site generated from the snapshot, with no server.
- **(b)** A read-only API serving the snapshot.

(a) has no attack surface and is the recommendation.

### 2.4 Labelling

Every page shows the "as of" date of the snapshot and the research-only
disclaimer.

## 3. Inversion (mandatory)

- **A stale snapshot is read as live advice.** Mitigation: the as-of stamp and disclaimer, and no verdict-as-action wording (ADR-054).
- **Licence breach.** Mitigation: SEC-only data by default.
- **Cost abuse.** Mitigation: no LLM endpoint exists.

## 4. Alternatives considered

- **Expose the local app with auth:** auth, hosting and spend controls for a single-user tool; rejected.
- **Video only:** the cheapest option, and compatible with this ADR as a complement.

## 5. Consequences

- Readers can see real output without installing anything.
- One export command and a static build.

## 6. References

- ADR-040 §0, CLAUDE.md "Security & privacy" §7, README (data-source terms)
