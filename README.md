# investment-intelligence

A command-line tool that reads a company's SEC filings and scores it against
seven frameworks drawn from published finance research — Piotroski's F-Score,
Sloan's accruals test, Novy-Marx gross profitability, Jegadeesh-Titman
momentum, and others. It reports what the numbers say, what it could not find
out, and what would have to be true for the conclusion to be wrong.

It will not tell you to buy anything. That is a design decision, not a
limitation, and the reasons are below.

**Research tooling, built for one operator. Not financial advice.**

---

## What problem this solves

Most stock screeners answer "which companies match these filters?" That question
is easy and not very useful — everyone with the same filters gets the same list.

The harder question is "what is actually true about this company, where does the
evidence run out, and what would change my mind?" Answering it means reading
primary sources, computing your own numbers, and being honest about gaps. That
is slow by hand. This automates the mechanical parts and refuses to paper over
the rest.

## The load-bearing decision

**A missing value is recorded as missing. It is never estimated, inferred, or
filled from a friendlier source.**

When a 10-K does not disclose net revenue retention, the output says
`NRR: not_disclosed`. It does not substitute an industry average or let a
language model guess. Every such absence becomes an explicit entry in a
`data_gaps` list that travels with the result.

This is the decision everything else hangs off. A flagged gap can be filled
later by a better data source. A plausible-but-wrong number silently corrupts
every score computed downstream, and you will never know it happened. One of
those failures is recoverable; the other is not.

The same reasoning keeps language models off the data path entirely:

```
SEC EDGAR XBRL      ─┐
10-K / 10-Q regex    ├─→  frameworks F1–F7  ─→  composite  ─→  verdict
DEF 14A HTML tables  │      (pure Python)         + overlays
yfinance snapshot   ─┘
```

Everything above is deterministic Python. Run it twice on the same filings and
you get the same answer. No API key is required for any of it.

An LLM is used in exactly one place — writing the prose narrative at the end —
and it is handed the already-computed numbers, never the raw filing text. Its
output is then validated claim by claim against the scorecard; any figure that
does not appear in the source data is flagged as a possible hallucination
before you ever read it.

## What the seven frameworks measure

Each produces a 0–10 score from published, citable signals.

| | Framework | Asks | Built from |
|---|---|---|---|
| **F1** | Pre-Discovery Alpha | Is quality improving before the market notices? | Piotroski (2000), Sloan (1996), Novy-Marx (2013), Lakonishok-Lee (2001) |
| **F2** | Momentum | Is price confirming, and has the market digested the last earnings? | Jegadeesh-Titman (1993), post-earnings drift |
| **F3** | Innovation Compounder | Are unit economics widening as it scales? | Gross-margin trajectory, R&D intensity |
| **F4** | Stealth Accumulation | Is informed money positioning quietly? | Short-interest decline, 13F flows, EPS acceleration |
| **F5** | Growth Quality | Is growth funded by the business, and is capital well allocated? | FCF margin, ROIC, Thorndike's capital-allocation traits |
| **F6** | Platform Dominator | Is there a structural moat, or just a good year? | Fahlenbrach (2009) founder premium, Patatoukas (2012) customer concentration |
| **F7** | Smart Beta Timing | Is it cheap against its own history? | Valuation z-scores |

**F7 is deliberately weighted at most 0.10** and always ships with a
disclaimer. Cheapness is contested ground academically, and it says nothing
about whether a business is good. Treating it as equal to the others would be
the single easiest way to make this tool wrong.

Three **overlays** sit on top and fire only when a specific anomaly is
detected — an intangible-heavy balance sheet distorting ROIC, a recent
spin-off, an extreme-winner pattern. They are capped so they can adjust a
verdict but never drive it.

## What a result looks like

```
$ uv run invest score-card NVDA

NVIDIA Corporation (NVDA)
Technology / Semiconductors & Related Devices   Cap $5434.77B   Stage established
CEO: Jensen Huang (Founder), 3.58% equity   IPO: 1999-04-29   Exchange: Nasdaq
P/E: 47.55   P/B: 36.30   EV/EBITDA: 42.87   Beta: 1.11

WATCHLIST   composite 7.00/10
weights: F1=0.11  F2=0.23  F3=0.06  F4=0.11  F5=0.34  F6=0.06  F7=0.10

  F1  Pre-Discovery Alpha    ███·······   3.0/10  fail
        · Piotroski: 4/9          · Asset growth band: top_decile
        · 90d open-market buyers: 0
  F2  Momentum               █████████·   9.0/10  strong_fit
        · 12-1 momentum: +22.8%   · % from 52w high: +2.3%
  F5  Growth Quality         ████████··   8.5/10  strong_fit
        · Revenue CAGR 3y: +100.0%   · FCF margin: +41.9%   · ROIC: +83.2%
  F6  Platform Dominator     ███████···   7.0/10  strong_fit
        · Rule of 40: 110.24      · NRR: not_disclosed
  F7  Smart Beta Timing      ··········   0.0/10  fail
        · EV/Rev band: very_expensive     (contested signal)
```

Read that as a disagreement, not a recommendation. The business scores well on
quality and momentum and badly on price and pre-discovery — it is thoroughly
discovered and expensive. Whether that is worth owning is a judgement the tool
deliberately leaves to you.

Note `NRR: not_disclosed` sitting in plain sight next to the scores. That is
the design working.

## Why there is no "buy"

The verdicts are `WATCHLIST WITH TRIGGERS`, `EXCLUDE WITH REASON`, and
`RESEARCH-ONLY`. There is no buy, no sell, no price target, by construction.

A number that looks like a recommendation invites you to stop thinking. The
useful output of research is not a verdict but a set of conditions — what you
believe, and what would falsify it. So every deep dive ends by inverting its
own conclusion:

> **What must be true for this to be wrong?**
> · What WACC and growth combination would make intrinsic value 30% lower?
> · Terminal value is 68% of total IV. If terminal growth were 0, what is it worth?
> · What would have to be true about the moat to sustain 10.5% growth for 8 years?

Risk factors are framed as monitoring checkpoints over a multi-year hold, not
stop-loss triggers.

### Exclusion policies

Every company that clears the data and quality gates is scored the same
way. Nothing is excluded for non-financial reasons. Investors who need to
leave out certain industries or companies, for example to follow an
investment mandate or their own values, can register an optional
**exclusion policy**. A policy is off unless it is enabled, never changes
a framework score, and records every exclusion with its reason. See
[`screener/policies/README.md`](screener/policies/README.md).

## Getting started

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/umr240/investment-intelligence.git
cd investment-intelligence
uv sync
cp .env.example .env          # then edit it — see below
uv run invest db-init         # creates the database; safe to re-run
uv run invest --help
```

`EDGAR_IDENTITY` must be your own name and email. The SEC's fair-use policy
requires a User-Agent identifying the requester, and rate-limits per identity —
so there is deliberately no default, and commands that reach EDGAR will stop
and tell you to set it.

```bash
uv run invest dive NVDA                  # all feasible frameworks
uv run invest dive NVDA --frameworks F1  # just one
uv run invest score-card NVDA            # the deterministic scorecard
uv run invest iv NVDA                    # intrinsic value, two independent methods
uv run invest score-card NVDA --narrate  # adds the LLM narrative (needs a key)
```

Everything except `--narrate` runs without any API key.

There is also a local web UI — a FastAPI control plane and a React client, both
bound to localhost by design:

```bash
uv run uvicorn api.app:app --reload --port 8000    # API, docs at /docs
cd frontend && npm install && npm run dev          # UI on :5173
```

On Windows, clone somewhere shallow. A few documentation filenames are long
enough that a deeply nested parent directory pushes them past the 260-character
path limit. `git config --global core.longpaths true` fixes the checkout, but
not the run: native extensions in `.venv` (lxml, pyarrow) fail to load past
MAX_PATH whatever git and the registry are set to, because Windows resolves DLL
paths the old way regardless. Shallow is the fix; longpaths is not a substitute.

## How it is organised

| Directory | Holds |
|---|---|
| `data/` | EDGAR fetch and XBRL parsing, deterministic filing-text extraction, typed yfinance client |
| `frameworks/` | The seven scorers, one file each |
| `overlays/` | The three anomaly overlays, capped so they never dominate |
| `valuation/` | Damodaran DCF and Greenwald asset-value ladders, EPV, reverse DCF |
| `screener/` | Tiered gate ladder over the stored universe |
| `deepdive/` | Orchestration, scorecard assembly, narrative generation and its output guard |
| `mental_models/` | 114 reasoning models the narrative layer draws on, each with a mandatory inversion |
| `docs/methodology/` | The specifications of record — every threshold and trigger condition |
| `docs/architecture/` | Architecture decision records, and the decision log |

## Honest status

| Area | State |
|---|---|
| Frameworks, overlays, valuation ladders | working |
| Screener over the full SEC US universe | working |
| Deep dives, scorecards, narrative layer | working |
| Local web UI | working |
| Test suite | 419 passing, plus 11 browser tests (`-m browser`) |
| `ruff` / `mypy --strict` | **not clean** — 364 / 1086, an honest backlog. Reported by CI but not gating; the correctness subset (`F821`, `F811`, `E722`) is gating and is clean. |
| Filing-text extraction | **weak.** Attempted on a small fraction of the universe, largely untested, and a failed extraction is currently indistinguishable from a genuine non-disclosure. |
| Retrieval over filing text | not built |

That filing-text row is the most important line in this table. It is the next
piece of work, and it will be measured before it is fixed: a labelled
ground-truth corpus first, so any improvement is provable rather than asserted.
A tool whose whole premise is honesty about gaps has to be honest about its own.

## Data sources and their terms

- **SEC EDGAR** — public, authoritative, no key. Requires a User-Agent
  identifying you, and rate-limits per identity. Treated as the highest-trust
  source; where anything disagrees with EDGAR, EDGAR wins.
- **yfinance** — an unofficial scraper of Yahoo Finance, not a supported API. It
  can return silently wrong values, so it never overrides an EDGAR-sourced
  figure. Review Yahoo's terms before relying on it.
- **Financial Modeling Prep** — optional, one bulk call per screener run for
  metadata only. Never used for per-ticker fundamentals.

Filing text is treated as untrusted input throughout. It is parsed into
structured values by regex and HTML parsing; instruction-like text inside a
filing cannot reach a language model as an instruction, because raw filing prose
never enters a prompt.

## Notes

- The SQLite database is unencrypted and local by design. It is gitignored and
  should not be synced to a cloud drive or copied out of the project.
- `uv.lock` is authoritative; builds are reproducible from it.
- `CLAUDE.md` carries the project specification for AI-assisted work and the security policy.
- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, the non-negotiable rules, and
  what is asked of a new scoring signal.
- [SECURITY.md](SECURITY.md) — reporting, and why filing text is treated as
  untrusted input.

## Licence

MIT — see [LICENSE](LICENSE).

---

*Research purposes only. Nothing here is financial advice, a recommendation, or
a solicitation. The author is not a licensed investment adviser. Past
performance does not guarantee future results, and models are simplifications
that will be wrong in ways their authors did not anticipate. Do your own
research and consider speaking to a qualified professional before investing.*
