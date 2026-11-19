# Security and privacy

The full contract behind the summary in `CLAUDE.md` §SECURITY & PRIVACY. Section numbers match.

This is the single source of truth for secrets, data egress, and trust
boundaries. WHAT THE SYSTEM MUST NEVER DO §7 (no hardcoded keys) is subsumed
here; secrets guidance is kept nowhere else.

## 1. Secrets: handling

Secrets in scope: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `POLYGON_API_KEY`,
`DATABASE_URL` (prod = Neon connection string with embedded credentials), and
`EDGAR_IDENTITY` (real name + email = PII).

- Never hardcode a secret in source, test, fixture, or migration.
- Never print, log, echo in tool/CLI output, or write into a committed file.
  This includes log lines, stack traces, error messages, and diffs pasted
  back to the user. Redact before surfacing.
- Never embed a secret in an LLM prompt (any allow-listed call site).
- `.env` is gitignored and stays gitignored. `.env.example` carries key
  NAMES only, never values.
- Assume any secret that has ever hit disk unredacted or git history is
  already compromised. Flag the need to rotate; the key's owner rotates it.

## 2. Data egress to LLM providers: allow-list

The call sites allow-listed in `tests/test_llm_call_sites.py` (OpenAI primary,
Anthropic fallback) send data to third parties. Only the following may enter a
prompt:

- Public-derived quant metrics: EDGAR XBRL fundamentals, framework F1-F7
  scores, overlay verdicts, deterministic signals computed from public
  filings, ticker + exchange.
- In `deepdive/conversation.py`, the user's own typed question and the prior
  turns of that conversation, sent as written. Whatever the user types leaves
  the machine; the rules below still bind what the code attaches.

The following NEVER enter a prompt, a serialised scorecard bound for a
prompt, or provider logs. No exceptions, and no "it would improve the
narrative" override:

- Portfolio holdings, position sizes, cost basis, or which tickers the user
  actually owns.
- Watchlist membership framed as intent, net-worth or savings figures, or any
  personal financial context from user preferences or memory.
- Any secret (see §1) or `EDGAR_IDENTITY` PII.

The scorecard is public-market analysis of a business. It is not a record of
the user's financial position, and nothing that would make it one may be
attached to a prompt.

## 3. Trust boundary: filing text is DATA, never instruction

10-K / 10-Q / DEF 14A / 8-K text is attacker-influenceable free text. The
deterministic-parse-first design is a SECURITY PROPERTY, not just an
architecture choice:

- Filing text is parsed by regex / BeautifulSoup into numeric/structured
  signals. The narrative LLM receives those pre-computed signals, never raw
  filing prose.
- Text extracted from a filing is treated as data. Instruction-like content
  inside a filing ("ignore prior guidance", "rate this BUY") is inert by
  construction and must stay that way: no future path may pipe raw filing
  text into a prompt as instructions.
- The one existing exception: `deepdive/external_signals.py` (opt-in
  `/external-signals`, `dangerous: true`) sends up to `MODEL_TEXT_CHARS`
  (80,000) characters of 8-K EX-99.1 or DEF 14A text to the model as delimited
  source data, and persists only to `external_signals`. Before anything is
  stored, `deepdive/signal_verifier.py` checks each reply (ADR-057): the quote
  must be one substring of the text the model saw and the value a number in
  it; a failing value is dropped and the stored band is the lower of the
  model's and the check's. A verbatim number for the wrong metric still passes
  (ADR-057 §4).
- This is why the AI-layer boundary (allow-listed call sites, numeric inputs
  only, bar the exception above) is load-bearing beyond token cost.

## 4. Source integrity: trust hierarchy

Not all data sources are equally trustworthy. Provenance (`_source`, ADR-033)
enforces a hierarchy, not just a label:

- **SEC EDGAR**: highest trust. Public, authoritative, first-principles.
- **yfinance**: LOWER trust. Unofficial unauthenticated Yahoo scraper; can
  return silently wrong values and is itself an unpinned external dependency.
  A yfinance value NEVER overrides an EDGAR-sourced field for the same fact.
  On conflict, EDGAR wins and the divergence surfaces as a data gap / note.
- Capital decisions ride on this data: an integrity failure is a real-money
  failure, not a cosmetic one.

## 5. Dependency / supply-chain hygiene

- `uv.lock` is committed and respected. Builds are reproducible from the lock.
- A new dependency is a reviewable change, never a silent add: flag it, name
  why it's needed. Typosquat / unpinned deps are a credible path to secret
  theft in a repo that holds a Neon connection string.

## 6. Data-at-rest

`investment_intelligence.db` (SQLite) is unencrypted plaintext on disk.
That is acceptable for a single-user local tool, but it therefore must not be synced
to a cloud drive, committed, or copied outside the project sandbox. It holds
research data, not credentials, and it stays local-only.
