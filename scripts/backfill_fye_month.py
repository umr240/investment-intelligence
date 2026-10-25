"""Correct Company.fiscal_year_end_month from each company's latest annual period.

Dry run by default: prints what would change. `--apply` writes only that
column, so take a backup first. See data/fye_month.py for the rule.

    uv run python scripts/backfill_fye_month.py            # report
    uv run python scripts/backfill_fye_month.py --apply    # write
"""

from __future__ import annotations

import sys
from collections import Counter

from sqlalchemy import select

from data.db import get_session
from data.fye_month import plan_fye_month_updates
from data.models.schema import Company


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    with get_session() as session:
        plan = plan_fye_month_updates(session)
        moves = Counter((old, new) for _t, old, new in plan)
        print(f"{len(plan)} companies would change month")
        for (old, new), n in moves.most_common(12):
            print(f"  {old} -> {new}: {n}")
        print("  e.g.", ", ".join(f"{t} {o}->{n}" for t, o, n in plan[:10]))
        if apply:
            new_month = {t: n for t, _o, n in plan}
            for co in session.execute(
                select(Company).where(Company.ticker.in_(new_month))
            ).scalars():
                co.fiscal_year_end_month = new_month[str(co.ticker)]
            print(f"applied to {len(new_month)} companies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
