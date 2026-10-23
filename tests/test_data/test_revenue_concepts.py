"""Revenue tagged only as RevenueFromContractWithCustomerIncludingAssessedTax.

CRWD, VLO and ODFL use this concept alone; it was in no revenue chain, so their
annual revenue was NULL (1,694 of 6,518 companies in the author DB had no
annual revenue at all, 2026-10-19).
"""
from __future__ import annotations

from typing import Any

from data.edgar_companyfacts import parse_companyfacts

INC = "RevenueFromContractWithCustomerIncludingAssessedTax"
EXC = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _fact(val: float, start: str = "2025-02-01", end: str = "2026-01-31") -> dict[str, Any]:
    return {"start": start, "end": end, "val": val, "accn": "0001-26-1",
            "form": "10-K", "fp": "FY", "fy": 2026, "filed": "2026-03-10"}


def _payload(**concepts: float) -> dict[str, Any]:
    return {"facts": {"us-gaap": {
        name: {"units": {"USD": [_fact(v)]}} for name, v in concepts.items()
    }}}


def _annual_revenue(payload: dict[str, Any]) -> float | None:
    rows = [r for r in parse_companyfacts("X", payload, fiscal_year_end_month=1)
            if r.period == "annual"]
    assert len(rows) == 1
    return rows[0].revenue


def test_including_assessed_tax_alone_is_read() -> None:
    assert _annual_revenue(_payload(**{INC: 4.8e9, "NetIncomeLoss": -1e8})) == 4.8e9


def test_earlier_concepts_still_win() -> None:
    assert _annual_revenue(_payload(**{EXC: 4.5e9, INC: 4.8e9})) == 4.5e9
    assert _annual_revenue(_payload(**{"Revenues": 4.4e9, INC: 4.8e9})) == 4.4e9
