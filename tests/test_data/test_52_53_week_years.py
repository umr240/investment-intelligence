"""52/53-week fiscal years end within a week of a month end.

LULU's years end between Jan 28 and Feb 2, COST's between Aug 28 and Sep 3.
Reading the raw calendar month dropped balance-sheet values (LULU total assets
missing in 6 of 10 stored years, 7 of 14 on a full re-parse) and gave two
different years one label (COST FY2017 and FY2018 both held the year ending
2017-09-03). Dates from the author DB, 2026-10-24.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from data.edgar_companyfacts import (
    _derive_fiscal_period,
    fye_month_from_submissions,
    parse_companyfacts,
)


@pytest.mark.parametrize(
    ("end", "start", "fyem", "expected"),
    [
        # LULU: year ends late Jan or early Feb, nominal month January.
        ("2024-01-28", None, 1, (2024, "annual")),
        ("2025-02-02", None, 1, (2025, "annual")),
        ("2025-02-02", "2024-01-29", 1, (2025, "annual")),
        ("2024-05-05", None, 1, (2025, "Q1")),
        # COST: year ends late Aug or early Sep, nominal month August.
        ("2024-09-01", "2023-09-04", 8, (2024, "annual")),
        ("2025-08-31", "2024-09-02", 8, (2025, "annual")),
        ("2017-09-03", None, 8, (2017, "annual")),
        # ILMN: year ended in early January, nominal month December.
        ("2023-01-01", "2022-01-03", 12, (2022, "annual")),
        ("2023-12-31", "2023-01-02", 12, (2023, "annual")),
        # ADBE: year ends late Nov or early Dec, nominal month November.
        ("2016-12-02", "2015-11-28", 11, (2016, "annual")),
        ("2021-12-03", None, 11, (2021, "annual")),
        # Calendar and month-end filers are unchanged.
        ("2024-12-31", None, 12, (2024, "annual")),
        ("2024-03-31", None, 12, (2024, "Q1")),
        ("2026-01-31", "2025-02-01", 1, (2026, "annual")),
        # A mid-quarter date is still not a period boundary.
        ("2024-02-15", None, 12, None),
    ],
)
def test_period_derivation(
    end: str, start: str | None, fyem: int, expected: tuple[int, str] | None
) -> None:
    s = date.fromisoformat(start) if start else None
    assert _derive_fiscal_period(date.fromisoformat(end), s, fyem) == expected


@pytest.mark.parametrize(
    ("raw", "month"),
    [
        ("0201", 1),
        ("0131", 1),
        ("1231", 12),
        ("0103", 12),
        ("0901", 8),
        ("0831", 8),
        ("1003", 9),
        ("0630", 6),
        ("0107", 12),
        ("0108", 1),
        ("0207", 1),
        ("0208", 2),
        ("1200", None),
        ("1232", None),
        ("1302", None),
        ("", None),
        (None, None),
    ],
)
def test_fye_month_from_submissions(raw: str | None, month: int | None) -> None:
    assert fye_month_from_submissions(raw) == month


def _instant(val: float, end: str, accn: str, filed: str) -> dict[str, Any]:
    return {"end": end, "val": val, "accn": accn, "form": "10-K", "filed": filed}


def _flow(val: float, start: str, end: str, accn: str, filed: str) -> dict[str, Any]:
    return {"start": start, "end": end, "val": val, "accn": accn, "form": "10-K", "filed": filed}


def test_lulu_balance_sheet_kept_and_years_distinct() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _flow(9.6e9, "2023-01-30", "2024-01-28", "a-24", "2024-03-21"),
                            _flow(10.6e9, "2024-01-29", "2025-02-02", "a-25", "2025-03-27"),
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            _instant(7.1e9, "2024-01-28", "a-24", "2024-03-21"),
                            _instant(7.6e9, "2025-02-02", "a-25", "2025-03-27"),
                        ]
                    }
                },
            }
        }
    }
    rows = {
        r.fiscal_year: r
        for r in parse_companyfacts("LULU", payload, fiscal_year_end_month=1)
        if r.period == "annual"
    }
    assert sorted(rows) == [2024, 2025]
    assert rows[2024].total_assets == 7.1e9
    assert rows[2025].total_assets == 7.6e9


def test_cost_years_across_a_month_boundary_do_not_collide() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _flow(254e9, "2023-09-04", "2024-09-01", "c-24", "2024-10-09"),
                            _flow(275e9, "2024-09-02", "2025-08-31", "c-25", "2025-10-08"),
                        ]
                    }
                }
            }
        }
    }
    rows = {
        r.fiscal_year: r.revenue
        for r in parse_companyfacts("COST", payload, fiscal_year_end_month=8)
        if r.period == "annual"
    }
    assert rows == {2024: 254e9, 2025: 275e9}


def test_continuing_operations_cash_flow_is_a_fallback() -> None:
    # COST tagged FY2013-16 operating cash flow only as ...ContinuingOperations.
    cont = "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
    span = ("2015-08-31", "2016-08-28", "c-16", "2016-10-12")
    rows = [
        r
        for r in parse_companyfacts(
            "COST",
            {
                "facts": {
                    "us-gaap": {
                        "Revenues": {"units": {"USD": [_flow(118.7e9, *span)]}},
                        cont: {"units": {"USD": [_flow(3.3e9, *span)]}},
                    }
                }
            },
            fiscal_year_end_month=8,
        )
        if r.period == "annual"
    ]
    assert rows[0].operating_cash_flow == 3.3e9


def test_adoption_date_instant_is_not_a_prior_year_end() -> None:
    # ASC 842 balance "as of January 1, 2019" in a calendar filer's FY2019 10-K.
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [_flow(1.0e9, "2018-01-01", "2018-12-31", "k-18", "2019-02-20")]
                    }
                },
                "OperatingLeaseLiabilityNoncurrent": {
                    "units": {"USD": [_instant(4.0e8, "2019-01-01", "k-19", "2020-02-20")]}
                },
            }
        }
    }
    rows = [
        r
        for r in parse_companyfacts("X", payload, fiscal_year_end_month=12)
        if r.period == "annual"
    ]
    assert [r.fiscal_year for r in rows] == [2018]
    assert rows[0].total_debt is None


def test_acquisition_date_instant_does_not_replace_the_quarter_end() -> None:
    # KFS: a 10-K filed in 2021 carries an acquired business's 2019-03-01 balance.
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [_flow(1.3e7, "2019-01-01", "2019-03-31", "q-19", "2020-04-09")]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            _instant(4.05e8, "2019-03-31", "q-19", "2020-04-09"),
                            _instant(2.2e7, "2019-03-01", "k-20", "2021-03-29"),
                        ]
                    }
                },
            }
        }
    }
    rows = {
        (r.fiscal_year, r.period): r
        for r in parse_companyfacts("KFS", payload, fiscal_year_end_month=12)
    }
    assert rows[(2019, "Q1")].total_assets == 4.05e8


def test_the_period_end_gate_decides_for_instants_before_the_24th() -> None:
    lulu_ye = date(2025, 2, 2)
    assert _derive_fiscal_period(lulu_ye, None, 1, frozenset({lulu_ye})) == (2025, "annual")
    assert _derive_fiscal_period(lulu_ye, None, 1, frozenset()) is None
    # A month-end instant does not need a matching period (HIMS 2018-12-31 stubs).
    assert _derive_fiscal_period(date(2018, 12, 31), None, 12, frozenset()) == (2018, "annual")


def test_a_52_53_week_instant_with_no_matching_period_is_dropped() -> None:
    payload = {
        "facts": {
            "us-gaap": {
                "Assets": {"units": {"USD": [_instant(7.6e9, "2025-02-02", "a-25", "2025-03-27")]}}
            }
        }
    }
    assert parse_companyfacts("LULU", payload, fiscal_year_end_month=1) == []
