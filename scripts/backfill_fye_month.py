"""Correct Company.fiscal_year_end_month, confirmed against SEC.

Candidates are companies whose latest year-long annual row implies a month
other than the stored one (data/fye_month.py, no network). Each candidate's
month is then read from SEC submissions.json and written only when SEC states
one that differs from the stored value. Dry run by default; `--apply` writes
only that column, so take a backup first.

    uv run python scripts/backfill_fye_month.py            # report
    uv run python scripts/backfill_fye_month.py --apply    # write
"""

from __future__ import annotations

import sys
import time

from sqlalchemy import select

from config.settings import require_edgar_identity
from data.db import get_session
from data.edgar_companyfacts import fetch_filer_metadata
from data.fye_month import confirmed_month, plan_fye_month_updates
from data.models.schema import Company


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    identity = require_edgar_identity()
    with get_session() as session:
        plan = plan_fye_month_updates(session)
        ciks = {
            str(c.ticker): c.cik
            for c in session.execute(
                select(Company).where(Company.ticker.in_([t for t, _o, _d in plan]))
            ).scalars()
        }
        writes: dict[str, tuple[int | None, int]] = {}
        sec_agrees: list[str] = []  # SEC states the stored month: the stored rows were wrong
        unconfirmed: list[str] = []  # no SEC month (none stated, or the fetch failed)
        for ticker, stored, _derived in plan:
            cik = ciks.get(ticker)
            meta = fetch_filer_metadata(int(cik), identity) if cik else None
            sec = (meta or {}).get("fiscal_year_end_month")
            target = confirmed_month(stored, sec)
            if target is not None:
                writes[ticker] = (stored, target)
            elif sec is None:
                unconfirmed.append(ticker)
            else:
                sec_agrees.append(ticker)
            time.sleep(0.12)  # SEC fair access: ~8 requests a second
        print(
            f"{len(plan)} candidates: {len(writes)} to write (SEC month differs from stored), "
            f"{len(sec_agrees)} left (SEC confirms stored), {len(unconfirmed)} left (no SEC month)"
        )
        # One line per write, old -> new: the undo list for this column.
        for ticker, (stored, target) in sorted(writes.items()):
            print(f"  write {ticker} {stored} -> {target}")
        print("  SEC confirms stored:", " ".join(sorted(sec_agrees)))
        print("  no SEC month:", " ".join(sorted(unconfirmed)))
        if apply:
            for co in session.execute(select(Company).where(Company.ticker.in_(writes))).scalars():
                co.fiscal_year_end_month = writes[str(co.ticker)][1]
            print(f"applied to {len(writes)} companies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
