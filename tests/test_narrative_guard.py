"""
Hallucination-guard unit tests.

The narrative_guard validator is the safety net catching LLM hallucinations
before they reach the user. These tests build synthetic narratives that
exercise each failure mode and assert the validator flags them.

We construct a fake ScorecardView (no DB / no LLM) so the test is hermetic.
"""
from __future__ import annotations

from datetime import date

from deepdive.narrative_guard import validate
from deepdive.narrative_output import (
    BearPoint,
    BullPoint,
    NarrativeBody,
    NumericClaim,
    RiskFactor,
)
from deepdive.scorecard_view import (
    CompanyHeader,
    CompositeView,
    FrameworkView,
    OverlayTriggerView,
    ScorecardView,
    StageView,
)


def _fixture_view() -> ScorecardView:
    """Synthetic scorecard view used by all tests in this module.

    Numbers chosen to be obviously distinct (not round) so accidental
    matches in whitelist generation don't mask real hallucinations.
    """
    return ScorecardView(
        ticker="TEST",
        run_date=date(2026, 5, 5),
        mode_used="C",
        company=CompanyHeader(
            ticker="TEST",
            name="Test Co",
            sector="Software",
            industry="Application Software",
            market_cap_usd=12_345_000_000.0,
            cik="0000000001",
            ipo_date=date(2014, 4, 11),
            exchange="NASDAQ",
            fiscal_year_end_month=12,
            ceo_name="Alice Example",
            ceo_equity_pct=2.31,
            ceo_equity_pct_state="disclosed_exact",
            is_founder_ceo=True,
            pe_trailing=37.4,
            pb_ratio=8.2,
            ev_ebitda=25.6,
            beta=1.18,
            latest_fiscal_year=2024,
            latest_period_end=date(2024, 12, 31),
            latest_revenue=1_872_300_000.0,
            latest_net_income=287_400_000.0,
        ),
        stage=StageView(stage="mid_cap", reasoning={}),
        composite=CompositeView(
            score=5.73,
            verdict="watchlist",
            mode_resolved="C",
            weights_used={"F1": 0.15, "F2": 0.20, "F3": 0.20, "F4": 0.10,
                          "F5": 0.15, "F6": 0.10, "F7": 0.10},
            weights_renormalised=False,
        ),
        frameworks=[
            FrameworkView(code="F1", title="Pre-Discovery Alpha", score=3.0,
                          max_score=10.0, verdict="fail", band="weak",
                          key_signals=[("Piotroski", "5/9")], data_gaps=[]),
            FrameworkView(code="F2", title="Momentum", score=4.5,
                          max_score=10.0, verdict="partial", band="moderate",
                          key_signals=[("12-1 momentum", "+18.7%")], data_gaps=[]),
            FrameworkView(code="F3", title="Innovation Compounder", score=6.2,
                          max_score=10.0, verdict="partial", band="moderate",
                          key_signals=[], data_gaps=[]),
            FrameworkView(code="F4", title="Stealth Accumulation", score=0.0,
                          max_score=10.0, verdict="unfeasible", band="unfeasible",
                          key_signals=[], data_gaps=[],
                          is_unfeasible=True,
                          unfeasible_reason="recent IPO"),
            FrameworkView(code="F5", title="Growth Quality", score=8.4,
                          max_score=10.0, verdict="strong_fit", band="strong",
                          key_signals=[("ROIC", "22.6%")], data_gaps=[]),
            FrameworkView(code="F6", title="Platform Dominator", score=5.1,
                          max_score=10.0, verdict="partial", band="moderate",
                          key_signals=[], data_gaps=[]),
            FrameworkView(code="F7", title="Smart Beta Timing", score=7.0,
                          max_score=10.0, verdict="strong_fit", band="strong",
                          key_signals=[], data_gaps=[],
                          notes="contested signal per PROJECT_SPEC §F7"),
        ],
        overlay_triggers=[
            OverlayTriggerView(
                overlay_type="BEW", trigger_id="BEW-2",
                condition="annualised idiosyncratic vol > 60%",
                relevant_numbers={"idio_vol": 0.683},
                framework_section="F2",
            ),
        ],
        fetch_data_gaps=["Form 4 transactions: not fetched (insider gate)"],
    )


# ── Happy path ────────────────────────────────────────────────────────────


def test_clean_narrative_emits_no_warnings() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Composite verdict watchlist with strong growth-quality offset.",
        bull=[BullPoint(
            headline="Growth-quality fundamentals are robust",
            detail="ROIC 22.6% and the F5 framework rates strong_fit.",
            framework_codes=["F5"],
            numeric_claims=[
                NumericClaim(value="22.6%", field_path="frameworks.4.key_signals.0.1"),
                NumericClaim(value="8.4", field_path="frameworks.4.score"),
            ],
        )],
        bear=[BearPoint(
            headline="Pre-discovery signals weak",
            detail="F1 score is low, indicating limited insider/ accrual edge.",
            framework_codes=["F1"],
            numeric_claims=[
                NumericClaim(value="3.0", field_path="frameworks.0.score"),
            ],
        )],
        risks=[RiskFactor(
            factor="Idiosyncratic volatility flagged by extreme-winners overlay",
            severity="medium",
            grounded_in="BEW-2",
        )],
        data_caveats=["Form 4 transactions were not fetched."],
    )
    warnings = validate(body, view)
    assert warnings == [], f"unexpected warnings: {warnings}"


# ── Hallucinated number in prose ──────────────────────────────────────────


def test_unwhitelisted_number_in_headline_is_flagged() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Composite verdict watchlist.",
        bull=[BullPoint(
            headline="Revenue grew 999.9% year over year",  # 999.9 not in view
            detail="F5 looks strong.",
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="F1 weak",
            detail="Pre-discovery is weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 transactions were not fetched."],
    )
    warnings = validate(body, view)
    assert any("999.9" in w for w in warnings), warnings


def test_unwhitelisted_dollar_amount_in_detail_is_flagged() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Watchlist verdict.",
        bull=[BullPoint(
            headline="Strong growth quality",
            detail="The company posted $77.7B in revenue last quarter.",  # invented
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="Pre-discovery weak",
            detail="F1 is weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 not fetched."],
    )
    warnings = validate(body, view)
    assert any("77.7" in w for w in warnings), warnings


# ── Numeric claim with bogus field_path ───────────────────────────────────


def test_numeric_claim_bad_field_path_is_flagged() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Watchlist.",
        bull=[BullPoint(
            headline="ROIC strong",
            detail="ROIC is 22.6%.",
            framework_codes=["F5"],
            numeric_claims=[
                NumericClaim(value="22.6%", field_path="company.nonexistent_field"),
            ],
        )],
        bear=[BearPoint(
            headline="F1 weak",
            detail="Pre-discovery weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 not fetched."],
    )
    warnings = validate(body, view)
    assert any("does not exist" in w for w in warnings), warnings


# ── Citing an unfeasible framework ────────────────────────────────────────


def test_citing_unfeasible_framework_is_flagged() -> None:
    view = _fixture_view()  # F4 is unfeasible in the fixture
    body = NarrativeBody(
        one_liner="Watchlist.",
        bull=[BullPoint(
            headline="Stealth accumulation evident",
            detail="F4 indicates accumulation.",
            framework_codes=["F4"],  # citing unfeasible
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="F1 weak",
            detail="Pre-discovery weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 not fetched."],
    )
    warnings = validate(body, view)
    assert any("unfeasible" in w for w in warnings), warnings


# ── Citing a non-existent framework ───────────────────────────────────────


def test_unknown_framework_code_is_flagged() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Watchlist.",
        bull=[BullPoint(
            headline="F8 framework rules",
            detail="Per the F8 framework, this is a buy.",
            framework_codes=["F8"],  # F8 doesn't exist
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="F1 weak",
            detail="Weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 not fetched."],
    )
    warnings = validate(body, view)
    assert any("F8" in w for w in warnings), warnings


# ── Risk grounding ────────────────────────────────────────────────────────


def test_risk_with_unknown_grounding_is_flagged() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Watchlist.",
        bull=[BullPoint(
            headline="Solid",
            detail="F5 strong.",
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="Weak F1",
            detail="Pre-discovery weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[RiskFactor(
            factor="China tariff risk",
            severity="high",
            grounded_in="external_macro",  # not in view
        )],
        data_caveats=["Form 4 not fetched."],
    )
    warnings = validate(body, view)
    assert any("external_macro" in w for w in warnings), warnings


def test_risk_grounded_in_overlay_trigger_passes() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Watchlist.",
        bull=[BullPoint(
            headline="Solid",
            detail="F5 strong.",
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="Weak F1",
            detail="Pre-discovery weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[RiskFactor(
            factor="High idiosyncratic volatility — extreme-winners regime risk",
            severity="medium",
            grounded_in="BEW-2",
        )],
        data_caveats=["Form 4 not fetched."],
    )
    warnings = validate(body, view)
    grounding_warnings = [w for w in warnings if w.startswith("risks[")]
    assert grounding_warnings == [], grounding_warnings


# ── Caveat fidelity ───────────────────────────────────────────────────────


def test_missing_caveats_when_view_has_gaps_is_flagged() -> None:
    view = _fixture_view()  # has fetch_data_gaps
    body = NarrativeBody(
        one_liner="Watchlist.",
        bull=[BullPoint(
            headline="Solid",
            detail="F5 strong.",
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="Weak F1",
            detail="Pre-discovery weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=[],  # missing despite gaps in view
    )
    warnings = validate(body, view)
    assert any("data_caveats" in w for w in warnings), warnings


def test_sec_form_names_are_not_read_as_numbers() -> None:
    # A live CRWD narrative was guard_failed on "Monitor DEF 14A filings" (2026-10-19).
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Composite verdict watchlist.",
        bull=[BullPoint(
            headline="F5 strong",
            detail="Track 13F holder counts and any 10b5-1 plans.",
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="F1 weak",
            detail="Monitor DEF 14A filings for changes in founder ownership.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 transactions were not fetched."],
    )
    assert not [w for w in validate(body, view) if "whitelist" in w]


def test_fabricated_number_beside_a_form_name_is_still_flagged() -> None:
    view = _fixture_view()
    body = NarrativeBody(
        one_liner="Composite verdict watchlist.",
        bull=[BullPoint(
            headline="F5 strong",
            detail="The DEF 14A shows $77.7B of buybacks.",
            framework_codes=["F5"],
            numeric_claims=[],
        )],
        bear=[BearPoint(
            headline="F1 weak",
            detail="Pre-discovery is weak.",
            framework_codes=["F1"],
            numeric_claims=[],
        )],
        risks=[],
        data_caveats=["Form 4 transactions were not fetched."],
    )
    assert any("77.7" in w for w in validate(body, view))


def test_comma_grouped_decimals_with_units_parse_whole() -> None:
    # "$1,612.3M" was read as 1612 and flagged against a correct 1.612e9.
    from deepdive.narrative_guard import _value_matches

    assert _value_matches("$1,612.3M", 1612349000.0)


def test_period_labels_are_not_numeric_claims() -> None:
    from deepdive.narrative_guard import _extract_tokens_and_floats

    assert _extract_tokens_and_floats("trading above its 52-week high") == []
    assert [t for t, _, _ in _extract_tokens_and_floats("up 52% this year")] == ["52%"]


def test_provider_errors_are_scrubbed_of_key_fragments() -> None:
    # OpenAI's 401 echoes a masked key; the text is logged and persisted.
    from deepdive.narrative import _redact

    out = _redact("Incorrect API key provided: key_aMWq********4qiw. Retry.")
    assert "aMWq" not in out and "4qiw" not in out
