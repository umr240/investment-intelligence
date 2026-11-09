# Investment-intelligence

A command-line tool that reads a company's SEC filings and scores it against
seven frameworks from published finance research, including Piotroski's
F-Score, Sloan's accruals test, Novy-Marx gross profitability and
Jegadeesh-Titman momentum. It reports what the numbers say, what it could not
find out, and what would have to be true for the conclusion to be wrong.

It will not tell you to buy anything. That is deliberate, and
[Why there is no "buy"](#why-there-is-no-buy) explains the reasoning.

**Research tooling built for one operator. It is not financial advice.**

## What problem this solves

Most stock screeners answer "which companies match these filters?" That
question is easy and not very useful, because everyone with the same filters
gets the same list.

A harder question is what is actually true about a company, where the evidence
runs out, and what would change your mind. Answering it means reading primary
sources, computing your own numbers and being honest about gaps, which is slow
by hand. This tool automates the mechanical parts and refuses to paper over the
rest.

## Missing data stays missing

A missing value is recorded as missing. It is never estimated, inferred, or
filled from a friendlier source.

When a 10-K does not disclose net revenue retention, the output says
`NRR: not_disclosed` instead of substituting an industry average or letting a
language model guess. Every such absence becomes an explicit entry in a
`data_gaps` list that travels with the result.

Most of the rest of the design follows from this. A flagged gap can be filled
later by a better data source. A plausible-but-wrong number silently corrupts
every score computed downstream, and nothing tells you it happened.

The same reasoning keeps language models off the data path entirely:

```
SEC EDGAR XBRL      ─┐
10-K / 10-Q regex    ├─→  frameworks F1–F7  ─→  composite  ─→  verdict
DEF 14A HTML tables  │      (pure Python)         + overlays
yfinance snapshot   ─┘
```

Everything in that pipeline is deterministic Python. Run it twice on the same
filings and you get the same answer. None of it needs an API key.

Language models are called only from the modules allow-listed in
`tests/test_llm_call_sites.py`, and CI enforces that list. The prose narrative
and the follow-up chat receive the already-computed numbers, never raw filing
text. Their output is checked claim by claim against the scorecard, and any
figure that does not appear in the source data is flagged as a possible
hallucination before you read it.

One opt-in path does send filing text to a model: the `/external-signals`
extraction of metrics such as net revenue retention from earnings releases and
proxy statements. It asks for confirmation before running, stores its results
apart from every framework score, and requires each value to come with a quote
from the source. Before anything is stored, code checks that the quote appears
in the text the model saw and that the value is a number in it, and drops any
value that fails.

## What the seven frameworks measure

Each framework produces a score from 0 to 10 from published, citable signals.

| | Framework | Asks | Built from |
|---|---|---|---|
| F1 | Pre-Discovery Alpha | Is quality improving before the market notices? | Piotroski (2000), Sloan (1996), Novy-Marx (2013), Lakonishok-Lee (2001) |
| F2 | Momentum | Is price confirming, and has the market digested the last earnings? | Jegadeesh-Titman (1993), post-earnings drift |
| F3 | Innovation Compounder | Are unit economics widening as it scales? | Gross-margin trajectory, R&D intensity |
| F4 | Stealth Accumulation | Is informed money positioning quietly? | Short-interest decline, 13F flows, EPS acceleration |
| F5 | Growth Quality | Is growth funded by the business, and is capital well allocated? | FCF margin, ROIC, Thorndike's capital-allocation traits |
| F6 | Platform Dominator | Is there a structural moat, or just a good year? | Fahlenbrach (2009) founder premium, Patatoukas (2012) customer concentration |
| F7 | Smart Beta Timing | Is it cheap against its own history? | Valuation z-scores |

F7's weight is capped at 0.10, and its score always ships with a disclaimer.
The academic evidence on cheapness is contested, and a low multiple says
nothing about whether the business is any good. Weighting it equally with the
others would be the easiest way to make this tool wrong.

Three overlays sit on top and fire only when they detect a specific anomaly: an
intangible-heavy balance sheet distorting ROIC, a recent spin-off, or an
extreme-winner pattern. They are capped so they can adjust a verdict but never
drive it.

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

The frameworks disagree here. The business scores well on quality and momentum
and badly on price and pre-discovery, because it is thoroughly discovered and
expensive. Whether that is worth owning is a judgement the tool leaves to you.

`NRR: not_disclosed` sits in the output beside the scores, with no estimate in
its place.

## Why there is no "buy"

The verdicts are `WATCHLIST WITH TRIGGERS`, `EXCLUDE WITH REASON`, and
`RESEARCH-ONLY`. By construction there is no buy, no sell and no price target.

A number that looks like a recommendation invites you to stop thinking. Research
is more useful when it ends in conditions: what you believe, and what would
falsify it. So every deep dive ends by inverting its own conclusion:

> **What must be true for this to be wrong?**
> · What WACC and growth combination would make intrinsic value 30% lower?
> · Terminal value is 68% of total IV. If terminal growth were 0, what is it worth?
> · What would have to be true about the moat to sustain 10.5% growth for 8 years?

Risk factors are framed as monitoring checkpoints over a multi-year hold, not as
stop-loss triggers.

### Exclusion policies

Every company that clears the data and quality gates is scored the same way,
and none is excluded for non-financial reasons. Investors who need to leave out
certain industries or companies, for example to follow an investment mandate or
their own values, can register an optional exclusion policy. A policy is off
until enabled, never changes a framework score, and records every exclusion
with its reason. See [`screener/policies/README.md`](screener/policies/README.md).

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
requires a User-Agent that identifies the requester and rate-limits per
identity, so there is deliberately no default. Commands that reach EDGAR will
stop and tell you to set it.

```bash
uv run invest dive NVDA                  # all feasible frameworks
uv run invest dive NVDA --frameworks F1  # just one
uv run invest score-card NVDA            # the deterministic scorecard
uv run invest iv NVDA                    # intrinsic value, two independent methods
uv run invest score-card NVDA --narrate  # adds the LLM narrative (needs a key)
```

Everything except `--narrate` runs without an API key.

There is also a local web UI, made up of a FastAPI control plane and a React
client. Both are bound to localhost by design.

```bash
uv run uvicorn api.app:app --reload --port 8000    # API, docs at /docs
cd frontend && npm install && npm run dev          # UI on :5173
```

On Windows, clone into a short path near the drive root. A few documentation
filenames are long enough that a deeply nested parent directory pushes them
past the 260-character path limit. `git config --global core.longpaths true`
fixes the checkout but not the run: native extensions in `.venv` (lxml,
pyarrow) still fail to load past MAX_PATH, whatever git and the registry are
set to, because Windows resolves DLL paths the old way.

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
| `docs/methodology/` | The specifications of record, with every threshold and trigger condition |
| `docs/architecture/` | Architecture decision records and the decision log |

## Status

| Area | State |
|---|---|
| Frameworks, overlays, valuation ladders | Working |
| Screener over the full SEC US universe | Working |
| Deep dives, scorecards, narrative layer | Working |
| Local web UI | Working |
| Test suite | Passing in CI on Linux, Windows and macOS, plus 11 browser tests run locally (`-m browser`) |
| `ruff` / `mypy --strict` | Not clean: 364 / 1086 outstanding. CI reports them without failing the build. The correctness subset (`F821`, `F811`, `E722`) does fail the build, and it is clean. |
| Filing-text extraction | Weak. It has run on a small fraction of the universe and is largely untested, and a failed extraction currently looks the same as a genuine non-disclosure. |
| Retrieval over filing text | Not built |

Filing-text extraction matters most on this list. While a failed extraction
reads the same as a real gap, the `not_disclosed` guarantee above is weaker than
it looks. It is the next piece of work, and it will be measured before it is
fixed: a labelled ground-truth corpus comes first, so any improvement can be
shown rather than claimed.

## Data sources and their terms

- SEC EDGAR: public, authoritative, no key. It requires a User-Agent
  identifying you and rate-limits per identity. This is the highest-trust
  source, and where anything disagrees with EDGAR, EDGAR wins.
- yfinance: an unofficial scraper of Yahoo Finance, not a supported API. It can
  return silently wrong values, so it never overrides an EDGAR-sourced figure.
  Review Yahoo's terms before relying on it.
- Financial Modeling Prep: optional, and used for one bulk metadata call per
  screener run. It is never used for per-ticker fundamentals.

Filing text is treated as untrusted input throughout. On the scoring path,
regex and HTML parsing turn it into structured values, so raw filing prose never
reaches the narrative or chat prompts. The opt-in `/external-signals`
extraction is the one exception: it sends earnings-release and proxy text to a
model, marked as source data, and its output never feeds a score.

## Notes

- The SQLite database is unencrypted and local by design. It is gitignored and
  should not be synced to a cloud drive or copied out of the project.
- `uv.lock` is authoritative; builds are reproducible from it.
- `CLAUDE.md` holds the project specification for AI-assisted work and the
  security policy.
- [CONTRIBUTING.md](CONTRIBUTING.md): setup, the non-negotiable rules, and what
  is asked of a new scoring signal.
- [SECURITY.md](SECURITY.md): reporting, and why filing text is treated as
  untrusted input.

## Licence

MIT. See [LICENSE](LICENSE).

---

*Research purposes only. Nothing here is financial advice, a recommendation, or
a solicitation. The author is not a licensed investment adviser. Past
performance does not guarantee future results, and models are simplifications
that will be wrong in ways their authors did not anticipate. Do your own
research and consider speaking to a qualified professional before investing.*
