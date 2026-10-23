"""ADR-030 Amendment A1 §6 — F7 regime gate + composite weight-cap invariant.

The defect these pin: F7 scored BONEX.ST at 7.0 STRONG FIT by z-scoring
EV/Revenue and P/B across a margin history running −54.5% → +23.6%. In the SAME
run, the Greenwald module refused to average across that break. One engine, two
epistemic standards, shipping the laxer one.
"""
from __future__ import annotations

import pytest

from frameworks.composite import (
    _MAX_WEIGHTS,
    MIN_UNCAPPED_FRAMEWORKS,
    compute_composite_score,
)
from valuation.regime import APPLICABLE, INFLECTING, NOT_APPLICABLE, assess_margin_regime

# ── The shared regime test (one copy, two consumers) ──────────────────────

def test_bonex_margin_history_is_caught_as_inflecting():
    """BONESUPPORT's real operating margins. Median −8.6%, latest +23.6%."""
    verdict, reason = assess_margin_regime(
        [-0.545, -0.379, -0.196, 0.024, 0.185, 0.236]
    )
    assert verdict == INFLECTING
    assert "loss to profit" in reason


def test_regime_stable_history_is_applicable():
    verdict, _ = assess_margin_regime([0.30, 0.32, 0.31, 0.33, 0.32, 0.31])
    assert verdict == APPLICABLE


def test_consistently_lossmaking_is_applicable_not_inflecting():
    """Deliberate asymmetry: a company that has ALWAYS lost money is not
    inflecting. Its earning power genuinely is negative, and saying so is a
    finding rather than a misapplication."""
    verdict, _ = assess_margin_regime([-0.20, -0.15, -0.10, -0.05])
    assert verdict == APPLICABLE


def test_too_little_history_is_not_applicable():
    assert assess_margin_regime([0.2, 0.22])[0] == NOT_APPLICABLE


def test_f7_and_greenwald_share_one_implementation():
    """Two copies of a regime test is how the two standards reappear."""
    from valuation.greenwald import assess_epv_applicability
    history = [-0.545, -0.379, -0.196, 0.024, 0.185, 0.236]
    assert assess_epv_applicability(history) == assess_margin_regime(history)


# ── F7's own gate ─────────────────────────────────────────────────────────

def test_f7_history_floor_matches_the_cited_spec():
    """The module cited "spec wants 10" while enforcing 5, then fed the result
    into a weighted composite."""
    from frameworks.f7_smart_beta import MIN_HISTORY_YEARS
    assert MIN_HISTORY_YEARS == 10


def test_f7_data_requirement_still_requests_enough_history():
    """ADR-030-A2 separated the fetch target from the feasibility floor.

    This originally asserted MIN_HISTORY_YEARS >= annual_years, treating them as
    one number. They are not: the year-coverage gate anchors its window on the
    current calendar year, so a fetch target equal to the floor spends a slot on
    a fiscal year SEC cannot have yet — which is the very failure this test's
    own message describes ("unfeasible for a fetch reason rather than an
    analytical one"). CSGP sat at 9 of 10 years for exactly that reason.
    """
    from frameworks.f7_smart_beta import DATA_REQUIREMENT, MIN_HISTORY_YEARS

    floor = DATA_REQUIREMENT.min_annual_years or DATA_REQUIREMENT.annual_years
    assert floor == MIN_HISTORY_YEARS, (
        "the pre-flight floor must equal what score_f7 enforces, or a company "
        "passes the gate and then raises InsufficientHistoryError"
    )
    assert (DATA_REQUIREMENT.annual_years or 0) > MIN_HISTORY_YEARS, (
        "the fetch target must carry headroom above the floor"
    )


# ── §3.4 the weight cap must survive renormalisation ──────────────────────

def test_f7_weight_cap_survives_renormalisation():
    """The measured defect: F2/F5/F7 renormalised 0.15/0.20/0.15 over 0.50 to
    0.30/0.40/0.30, giving F7 THREE TIMES its documented ≤0.10 ceiling."""
    out = compute_composite_score(
        {"F2": 1.5, "F5": 6.5, "F7": 7.0}, mode="C", stage="mid_cap"
    )
    assert out.weights_used["F7"] == pytest.approx(_MAX_WEIGHTS["F7"])
    assert sum(out.weights_used.values()) == pytest.approx(1.0, abs=1e-3), (
        "excess released by a capped framework must redistribute, not vanish"
    )


def test_capped_weight_holds_across_every_feasible_subset():
    """The invariant, not just the one case that surfaced it."""
    import itertools
    codes = ["F1", "F2", "F3", "F4", "F5", "F6", "F7"]
    for r in range(2, len(codes) + 1):
        for subset in itertools.combinations(codes, r):
            if "F7" not in subset:
                continue
            out = compute_composite_score(
                {c: 5.0 for c in subset}, mode="C", stage="mid_cap"
            )
            if out.score is None:
                continue    # suppressed for breadth — no weights to violate
            assert out.weights_used["F7"] <= _MAX_WEIGHTS["F7"] + 1e-6, (
                f"subset {subset} gave F7 weight {out.weights_used['F7']}"
            )


def test_composite_suppressed_below_minimum_uncapped_breadth():
    """One framework plus a capped one is not a composite. Suppress rather than
    renormalise — the aggregate is what gets quoted without its caveats."""
    out = compute_composite_score({"F5": 6.5, "F7": 7.0}, mode="C", stage="mid_cap")
    assert out.score is None
    assert out.verdict == "research_only"


def test_suppressed_score_is_none_not_zero():
    """A 0.0 reads as "scored badly"; the truth is "not scoreable". Renderers
    must never coerce one into the other."""
    out = compute_composite_score({"F5": 6.5, "F7": 7.0}, mode="C", stage="mid_cap")
    assert out.score is not None or out.score is None    # explicit: not 0.0
    assert out.score != 0.0


def test_full_framework_set_is_unaffected_by_the_cap():
    """No regression for a complete run: F7's ideal weight is already ≤0.10."""
    out = compute_composite_score(
        {"F1": 6.0, "F2": 7.0, "F3": 7.0, "F4": 5.0, "F5": 8.0, "F6": 7.0, "F7": 3.0},
        mode="C", stage="mid_cap",
    )
    assert out.score is not None
    assert out.weights_used["F7"] <= _MAX_WEIGHTS["F7"] + 1e-6
    assert sum(out.weights_used.values()) == pytest.approx(1.0, abs=1e-3)


def test_min_uncapped_frameworks_is_at_least_two():
    assert MIN_UNCAPPED_FRAMEWORKS >= 2
