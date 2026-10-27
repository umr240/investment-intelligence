# Contributing

Thanks for looking. A few things are worth knowing before you spend time on a
change, because some of this project's constraints are unusual and are load
bearing rather than stylistic.

## Setting up

```bash
uv sync                          # uv, not pip or poetry
cp .env.example .env             # set EDGAR_IDENTITY to your own name + email
uv run invest db-init            # create the schema
uv run pytest -q
```

`EDGAR_IDENTITY` is required for anything that touches SEC EDGAR. It must be
your own contact details: the SEC rate-limits per identity, so a shared default
would put every contributor on one budget. There is deliberately no fallback.

Nothing else needs a key. The data path, the frameworks and the screener are
all deterministic and run offline of any paid API.

## The rules that are not negotiable

**A missing value is recorded as missing.** Never substitute a default, an
industry average, an estimate, or a model's guess for a number that is not in
the filings. Add a `data_gaps` entry instead. This is the decision the whole
project rests on: a flagged gap can be filled later, a plausible wrong number
silently corrupts everything downstream and is never noticed.

```python
# wrong — invents a zero and quietly poisons the ratio
rd_intensity = (data.rd_expense or 0) / data.revenue

# right
if data.rd_expense is None:
    raise MissingDataError("rd_expense", endpoint, ticker)
```

**No model calls outside the allow-listed sites.** Only the modules in `ALLOWED`
in `tests/test_llm_call_sites.py` may call an LLM, and CI enforces it. The
data, framework, screener and overlay layers are deterministic, and must stay
that way — run them twice, get the same answer.

**Raw filing text does not reach a prompt.** Filings are untrusted input. They
get parsed into structured values; the model sees the values. The opt-in
`/external-signals` extraction is the one documented exception; a new path is a
vulnerability. See [SECURITY.md](SECURITY.md) for why this is a security
boundary.

**Every public function is annotated.** Including the return type.

A change that violates one of these will be declined even if it improves
output, so it is worth checking before you build.

## Before you open a pull request

```bash
uv run pytest -q                      # must pass
uv run pytest -m requires_data -q     # only if you have a populated database
uv run ruff check . --select F821,F811,E722   # must be clean — CI gates this
```

Two things about the checks:

- `ruff check .` and `mypy . --strict` overall are **not clean**: the baseline
  at release is 364 and 1086 findings. That is an honest backlog, not a
  standard to meet. Don't feel
  obliged to fix unrelated findings, and don't add new ones in code you touch.
- The correctness subset above **is** gated, because those rules catch errors
  that fail at runtime. One undefined name reached the main branch this way,
  and the non-gating lint reported it into a log nobody read.

Tests marked `requires_data` assert invariants over a populated database and
skip on an empty one. CI cannot run them, so a green CI has not checked them —
if your change touches the data layer, run them locally against real data.

Anything touching `api/` or `frontend/` should be checked in a real browser,
not only with `curl`:

```bash
uv run uvicorn api.app:app --reload --port 8000
cd frontend && npm run dev
uv run pytest -m browser -q           # needs: uv sync --group browser
```

Once a pull request is open, anyone with write access can ask for an automated
review by mentioning `@claude` in a comment or review, for example
`@claude please review this PR`. It runs `.github/workflows/claude-review.yml`
on the repository's `GITHUB_TOKEN` with `contents: read`, so it can read the code
and CI results and comment, but cannot push. Comments from people without write
access do not trigger it. A run uses Claude Sonnet 5.5 and is capped (30 turns,
20 minutes), so a large PR may get a partial review. Each run is billed to the
workflow's API key, so ask once the PR is ready, not after every fix. Its review
is a second opinion; a maintainer still decides.

## Adding a framework signal

Signals must be traceable to a published source. Each framework composes named,
citable academic work — Piotroski, Sloan, Novy-Marx, Jegadeesh-Titman,
Fahlenbrach, Patatoukas — and the threshold for adding to one is the same:
where is this from, and what does the paper actually claim?

Two questions get asked of any new signal, and it is faster to answer them up
front:

1. **What false positives does it produce, and at what cost?** Every signal is
   wrong sometimes. If you have not characterised how, it is not ready.
2. **What would have to be true for this to be a bad signal?** If the answer is
   "nothing", the signal has not been thought about hard enough.

New thresholds belong in `docs/methodology/`, which is the specification of
record, not only in the code.

## Commits and decisions

Commit messages here explain *why*, with enough context that someone reading
`git log` in a year understands the reasoning and not just the diff. Match the
existing style — look at a few before writing yours.

Architectural decisions are recorded in `docs/architecture/`: ADRs for designs,
and `DECISIONS.md` for the running log. If your change contradicts a recorded
decision, say so in the pull request. Changing one is a conversation, not a
silent edit — and the log is append-only for exactly that reason.

## Scope

This is a single-operator research tool, and it is not trying to become a
product, a service, or a platform. Changes that add hosting, accounts,
multi-tenancy, or a "buy" recommendation are out of scope by design. The
absence of a buy verdict in particular is a deliberate choice, explained in the
README.

Bug reports, correctness fixes, better extraction from filings, and new
academically-grounded signals are all welcome.
