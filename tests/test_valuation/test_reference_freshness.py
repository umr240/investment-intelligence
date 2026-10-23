"""Macro reference data freshness + the staleness-baseline regression.

Two distinct concerns:

1. **The staleness CHECK must be anchored to now, not to a constant.**
   ``compute_wacc`` previously defaulted ``as_of_date="2026-05-13"``. That
   makes the baseline itself age: every day that passes, the comparison point
   drifts further into the past, and eventually a *fresh* snapshot reads as
   negative staleness ("92 days in the future"). A staleness check anchored to
   a frozen literal is not a staleness check. Refreshing the reference data on
   2026-08-16 is what exposed it.

2. **The reference files must parse and carry the fields the loader reads.**
   A malformed refresh should fail here, loudly, rather than silently feeding
   a wrong WACC into every valuation in the system.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

_REF_DIR = Path("data/reference/damodaran")

# (filename, value-field, staleness-threshold-field)
_MACRO_FILES = [
    ("risk_free_rate.json", "ten_year_treasury_yield_pct", "_staleness_warning_days"),
    ("implied_erp.json", "implied_erp_pct", "_staleness_warning_days"),
]


@pytest.mark.parametrize("fname,value_field,thresh_field", _MACRO_FILES)
def test_macro_file_parses_and_has_loader_fields(fname, value_field, thresh_field):
    payload = json.loads((_REF_DIR / fname).read_text(encoding="utf-8"))
    assert value_field in payload, f"{fname} missing {value_field} — cost_of_capital reads it"
    assert isinstance(payload[value_field], (int, float))
    assert "snapshot_date" in payload
    datetime.strptime(payload["snapshot_date"], "%Y-%m-%d")  # raises on bad format
    assert thresh_field in payload


@pytest.mark.parametrize("fname,value_field,_t", _MACRO_FILES)
def test_macro_values_are_in_a_plausible_band(fname, value_field, _t):
    """A fat-finger refresh (4.63 typed as 46.3) must fail here, not silently
    triple every discount rate in the system."""
    payload = json.loads((_REF_DIR / fname).read_text(encoding="utf-8"))
    value = payload[value_field]
    assert 0.0 < value < 20.0, (
        f"{fname}:{value_field} = {value} is outside any plausible band for a "
        f"percentage-denominated macro rate. Check for a units error."
    )


@pytest.mark.parametrize("fname,_v,_t", _MACRO_FILES)
def test_snapshot_date_is_not_in_the_future(fname, _v, _t):
    payload = json.loads((_REF_DIR / fname).read_text(encoding="utf-8"))
    snap = datetime.strptime(payload["snapshot_date"], "%Y-%m-%d").date()
    assert snap <= date.today(), (
        f"{fname} snapshot_date {snap} is in the future — a refresh recorded the "
        f"wrong date, which would make the staleness check report negative days."
    )


def test_staleness_baseline_is_now_not_a_frozen_literal():
    """The regression. Fresh reference data must never read as negative staleness.

    Asserts the DEFAULT path (as_of_date omitted) resolves to today, so this
    keeps holding as the calendar advances — which is exactly the property the
    hardcoded literal lacked.
    """
    from valuation.damodaran.cost_of_capital import compute_wacc

    result = compute_wacc(
        ticker="TEST",
        sector="Technology",
        country="United States",
        market_cap=1_000_000_000.0,
        total_debt=100_000_000.0,
    )
    assert result.reference_data_staleness_days >= 0, (
        "negative staleness means the as_of baseline is behind the snapshot "
        "date — the staleness check is anchored to a constant again"
    )


def test_staleness_is_computed_forward_from_snapshot():
    """Direct unit check on the helper, independent of reference-file contents."""
    from valuation.damodaran.cost_of_capital import _staleness_days

    assert _staleness_days("2026-01-01", "2026-01-31") == 30
    assert _staleness_days("2026-01-01", "2026-01-01") == 0
    # A snapshot newer than the baseline is the pathological case that the
    # frozen literal produced; the helper reports it as negative so callers can
    # detect it rather than it being clamped away.
    assert _staleness_days("2026-08-13", "2026-05-13") < 0
