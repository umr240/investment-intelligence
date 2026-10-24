"""Flag deep dives stored before their filings were re-read by a newer parser (DEC-46).

A refresh flags them itself once this code is in place; this script covers
only dives stored before it (no recorded parser version), once the ticker's
filing log carries a version. Safe to re-run: already-flagged dives and dives
stored since are skipped. It writes only `deepdive_runs.stale_reason` / `stale_at`, and
deletes nothing.

    uv run python scripts/flag_stale_dives.py            # every ticker with a dive
    uv run python scripts/flag_stale_dives.py LULU COST  # just these
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from data.db import get_session
from data.dive_staleness import flag_dives_read_by_older_parser
from data.models.schema import DeepDiveRun


def main(tickers: list[str]) -> int:
    if not tickers:
        with get_session() as session:
            tickers = sorted(session.execute(select(DeepDiveRun.ticker).distinct()).scalars())
    total = 0
    for ticker in tickers:
        n = flag_dives_read_by_older_parser(ticker.upper())
        if n:
            print(f"{ticker.upper()}: {n} dive(s) flagged stale")
        total += n
    print(f"{total} dive(s) flagged across {len(tickers)} ticker(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
