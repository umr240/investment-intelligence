# Security Policy

## Reporting a vulnerability

Please report security issues privately, not as a public issue.

Use GitHub's [private vulnerability
reporting](https://github.com/umr240/investment-intelligence/security/advisories/new)
on this repository. If that is unavailable, open an issue titled
"Security — contact request" containing no details, and a private channel will
be arranged.

Please include what you can: what the issue is, how to reproduce it, and what
an attacker could achieve. A proof of concept helps, but do not include working
exploit code in a public location.

This is a single-maintainer research project, not a funded product. There is no
bounty and no guaranteed response time, though reports will be taken seriously
and acknowledged as soon as practical.

## Scope

This is a local research tool. It has no hosted component, no user accounts,
and no multi-tenant surface. The interesting attack surface is therefore
narrower than a typical web application, and concentrated in three places.

### 1. Filing text is untrusted input

SEC filings — 10-K, 10-Q, DEF 14A, 8-K — are written by the companies being
analysed. They are attacker-influenceable free text, and this project treats
them that way.

Filing text is parsed by regex and HTML parsing into numeric and structured
values. The language model that writes the narrative receives **those computed
values, never the raw filing prose**. Instruction-like text inside a filing
("ignore previous guidance", "rate this a strong buy") is inert by
construction, because there is no path from filing text into a prompt.

This is a security property, not only an architectural preference. **A change
that pipes raw filing text into a model prompt would be a vulnerability**, even
if it improved output quality. Report it as one.

### 2. Secrets

Secrets in scope: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `POLYGON_API_KEY`,
`FMP_API_KEY`, `DATABASE_URL` when it points at a hosted database, and
`EDGAR_IDENTITY` — which is a real name and email, so it is personal data.

- `.env` is gitignored and must stay so. `.env.example` carries key names only.
- No secret may be hardcoded in source, tests, fixtures, or migrations, or
  written into logs, error messages, or a committed file.
- No secret is ever placed in a model prompt.

A secret that has reached git history should be treated as compromised and
rotated, even after the commit is removed.

CI runs gitleaks over the full history of every push and pull request, and a
finding fails the build. Findings are redacted in the log.

### 3. What may be sent to a model provider

The LLM call sites allow-listed in `tests/test_llm_call_sites.py` (narrative,
chat and external-signals extraction) send data to OpenAI or Anthropic. Only
public-derived material may go: figures computed from SEC filings, framework
scores, overlay verdicts, ticker and exchange. Chat also sends the operator's
own typed question and the earlier turns of that conversation, as written.

The following must never be sent, and a change that sends them is a
vulnerability worth reporting: portfolio holdings, position sizes, cost basis,
which tickers the operator actually owns, personal financial context, or any
secret. A scorecard is analysis of a public company. It is not a record of
anyone's financial position, and nothing may be attached that makes it one.

## Data handling

The SQLite database is **unencrypted plaintext on disk**. That is an accepted
trade-off for a single-user local tool, and it means the file should not be
synced to a cloud drive, committed, or copied out of the project directory. It
holds research, not credentials — but it is still yours and it is still plain.

The local web UI binds to `127.0.0.1` and has no authentication. This is
deliberate and safe **only** because it is not reachable from the network.
Binding it to `0.0.0.0`, or placing it behind a tunnel or reverse proxy, would
expose an unauthenticated API that can spend money on model calls. Do not do
this without adding authentication first.

## Dependencies

`uv.lock` is committed and builds are reproducible from it. Dependency updates
arrive by Dependabot and are reviewed rather than merged automatically. A new
dependency is a reviewable change: this project holds API keys and, in some
configurations, a database connection string, which makes a typosquatted or
compromised package a credible route to credential theft.

GitHub Actions are pinned to commit SHAs, and the workflow token is read-only.

## Out of scope

- The accuracy of any score, valuation, or narrative. Wrong output is a bug,
  and possibly an interesting one, but it is not a security issue.
- Rate limiting or denial of service against your own machine.
- Vulnerabilities in SEC EDGAR, Yahoo Finance, or any other upstream service.
