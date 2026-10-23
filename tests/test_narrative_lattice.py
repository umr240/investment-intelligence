"""
Lattice → narrative wiring tests (ADR-024 Stage D continuation).

Verifies that:
  - LatticeProfile is correctly derived from a deterministic ScorecardView.
  - The composer's output is rendered into the user prompt.
  - The real lattice on disk loads without schema violations (smoke).

No LLM calls. No DB access. Hermetic against fixture-only views.
"""
from __future__ import annotations

from datetime import date

import pytest

from deepdive.mental_model_composer import (
    CompositionResult,
    MentalModel,
    load_lattice,
)
from deepdive.narrative import (
    _build_user_prompt,
    _extract_section,
    _format_lattice_block,
    _lattice_profile_from_view,
)
from deepdive.scorecard_view import (
    CompanyHeader,
    CompositeView,
    FrameworkView,
    OverlayTriggerView,
    ScorecardView,
    StageView,
)

# ── Fixture builders ──────────────────────────────────────────────────────


def _company(
    *,
    latest_revenue: float | None = 1_000_000_000.0,
    ceo_equity_pct_state: str | None = "disclosed_exact",
    ipo_date: date | None = date(2010, 1, 1),
    ipo_date_state: str | None = "disclosed_exact",
) -> CompanyHeader:
    return CompanyHeader(
        ticker="TEST",
        name="Test Co",
        sector="Software",
        industry="Application Software",
        market_cap_usd=10_000_000_000.0,
        cik="0000000001",
        ipo_date=ipo_date,
        ipo_date_state=ipo_date_state,
        exchange="NASDAQ",
        fiscal_year_end_month=12,
        ceo_name="Alice Example" if ceo_equity_pct_state else None,
        ceo_equity_pct=2.0 if ceo_equity_pct_state else None,
        ceo_equity_pct_state=ceo_equity_pct_state,
        is_founder_ceo=True if ceo_equity_pct_state else None,
        pe_trailing=30.0,
        pb_ratio=5.0,
        ev_ebitda=20.0,
        beta=1.1,
        latest_fiscal_year=2024,
        latest_period_end=date(2024, 12, 31),
        latest_revenue=latest_revenue,
        latest_net_income=200_000_000.0,
    )


def _framework(
    code: str, *, verdict: str = "partial", unfeasible: bool = False,
) -> FrameworkView:
    return FrameworkView(
        code=code,
        title=code,
        score=5.0,
        max_score=10.0,
        verdict="unfeasible" if unfeasible else verdict,
        band="moderate",
        key_signals=[],
        data_gaps=[],
        is_unfeasible=unfeasible,
        unfeasible_reason="recent IPO" if unfeasible else "",
    )


def _view(
    *,
    run_date: date = date(2026, 5, 5),
    company: CompanyHeader | None = None,
    frameworks: list[FrameworkView] | None = None,
    overlay_triggers: list[OverlayTriggerView] | None = None,
    overlay_verdicts: dict[str, str] | None = None,
) -> ScorecardView:
    return ScorecardView(
        ticker="TEST",
        run_date=run_date,
        mode_used="C",
        company=company or _company(),
        stage=StageView(stage="mid_cap", reasoning={}),
        composite=CompositeView(
            score=5.0, verdict="watchlist", mode_resolved="C",
            weights_used={}, weights_renormalised=False,
        ),
        frameworks=frameworks or [_framework(c) for c in
                                   ("F1", "F2", "F3", "F4", "F5", "F6", "F7")],
        overlay_triggers=overlay_triggers or [],
        fetch_data_gaps=[],
        overlay_verdicts=overlay_verdicts or {},
    )


# ── Profile derivation ────────────────────────────────────────────────────


class TestLatticeProfileFromView:
    def test_revenue_flag_tracks_latest_revenue(self):
        with_rev = _view(company=_company(latest_revenue=500_000_000.0))
        without_rev = _view(company=_company(latest_revenue=None))
        zero_rev = _view(company=_company(latest_revenue=0.0))

        assert _lattice_profile_from_view(with_rev).has_revenue is True
        assert _lattice_profile_from_view(without_rev).has_revenue is False
        assert _lattice_profile_from_view(zero_rev).has_revenue is False

    def test_proxy_flag_tracks_ceo_equity_state_presence(self):
        with_proxy = _view(company=_company(ceo_equity_pct_state="disclosed_exact"))
        not_disclosed = _view(company=_company(ceo_equity_pct_state="not_disclosed"))
        no_proxy = _view(company=_company(ceo_equity_pct_state=None))

        # `not_disclosed` still means we ran the parser → has_proxy_data=True
        assert _lattice_profile_from_view(with_proxy).has_proxy_data is True
        assert _lattice_profile_from_view(not_disclosed).has_proxy_data is True
        assert _lattice_profile_from_view(no_proxy).has_proxy_data is False

    def test_overlays_fired_collected_from_triggers(self):
        triggers = [
            OverlayTriggerView(
                overlay_type="ICA", trigger_id="ICA-1",
                condition="", relevant_numbers={}, framework_section="F5",
            ),
            OverlayTriggerView(
                overlay_type="BEW", trigger_id="BEW-3",
                condition="", relevant_numbers={}, framework_section="F2",
            ),
        ]
        prof = _lattice_profile_from_view(_view(overlay_triggers=triggers))
        assert prof.overlays_fired == frozenset({"ICA", "BEW"})

    def test_archetype_post_spinoff_wins_priority(self):
        """PSA fires AND verdict confirms spinoff status → post_spinoff
        wins over recent_ipo + platform_dominator (the archetype priority
        rule). Verdict must be in the positive allowlist per the LULU
        2026-05-16 fix — not_a_spinoff_candidate alone is no longer
        sufficient to tag post_spinoff."""
        triggers = [
            OverlayTriggerView(
                overlay_type="PSA", trigger_id="PSA-1",
                condition="", relevant_numbers={}, framework_section="",
            ),
        ]
        # Even with a recent IPO and F6 strong, PSA wins — IF verdict confirms.
        view = _view(
            run_date=date(2026, 5, 5),
            company=_company(ipo_date=date(2025, 5, 5)),
            frameworks=[_framework("F1", verdict="strong_fit"),
                        _framework("F6", verdict="strong_fit"),
                        *(_framework(c) for c in ("F2", "F3", "F4", "F5", "F7"))],
            overlay_triggers=triggers,
            overlay_verdicts={"PSA": "strong_psa_candidate"},
        )
        assert _lattice_profile_from_view(view).archetype == "post_spinoff"

    def test_archetype_psa_self_disqualifies_falls_through(self):
        """PSA fires but verdict=not_a_spinoff_candidate (LULU 2026-05-16
        regression case) → DO NOT tag post_spinoff. Fall through to other
        archetype rules. With no recent IPO + no strong F6 / F1, expect None."""
        triggers = [
            OverlayTriggerView(
                overlay_type="PSA", trigger_id="PSA-3",
                condition="F7 unfeasible — recent IPO; spinoff/demerger PSA workflow may apply",
                relevant_numbers={}, framework_section="",
            ),
        ]
        view = _view(
            run_date=date(2026, 5, 5),
            company=_company(ipo_date=date(2013, 3, 5)),  # 158mo before run_date
            overlay_triggers=triggers,
            overlay_verdicts={"PSA": "not_a_spinoff_candidate"},
        )
        # Mature issuer past spinoff window AND past recent-IPO window AND
        # no strong F-framework verdict → no archetype.
        assert _lattice_profile_from_view(view).archetype is None

    def test_archetype_psa_ambiguous_verdict_falls_through(self):
        """PSA fires but verdict=data_gaps_block_verdict (insufficient data
        for the overlay's deeper analysis) → don't tag post_spinoff. The
        data-gaps verdict is ambiguous; positive allowlist requires explicit
        confirmation."""
        triggers = [
            OverlayTriggerView(
                overlay_type="PSA", trigger_id="PSA-3",
                condition="", relevant_numbers={}, framework_section="",
            ),
        ]
        view = _view(
            company=_company(ipo_date=date(2010, 1, 1)),
            overlay_triggers=triggers,
            overlay_verdicts={"PSA": "data_gaps_block_verdict"},
        )
        assert _lattice_profile_from_view(view).archetype is None

    def test_archetype_recent_ipo_when_within_two_years(self):
        view = _view(
            run_date=date(2026, 5, 5),
            company=_company(ipo_date=date(2025, 1, 1)),
        )
        assert _lattice_profile_from_view(view).archetype == "recent_ipo"

    def test_untrusted_listing_date_does_not_yield_recent_ipo(self):
        """ADR-018 state semantics apply at the read boundary, not just the write.

        657 companies carry a parser_uncertain ipo_date holding the earliest
        filing date in the fetched submissions window (KO -> 2018 against a 1919
        listing). Treating that as a listing date mislabels mature issuers as
        recent IPOs and pulls the wrong lattice into the narrative.
        """
        view = _view(
            run_date=date(2026, 5, 5),
            company=_company(
                ipo_date=date(2025, 1, 1), ipo_date_state="parser_uncertain"
            ),
        )
        assert _lattice_profile_from_view(view).archetype != "recent_ipo"

    def test_absent_listing_state_is_not_trusted(self):
        view = _view(
            run_date=date(2026, 5, 5),
            company=_company(ipo_date=date(2025, 1, 1), ipo_date_state=None),
        )
        assert _lattice_profile_from_view(view).archetype != "recent_ipo"

    def test_archetype_no_recent_ipo_after_two_years(self):
        view = _view(
            run_date=date(2026, 5, 5),
            company=_company(ipo_date=date(2010, 1, 1)),
        )
        # Falls through to framework-driven archetypes (none match here → None)
        assert _lattice_profile_from_view(view).archetype is None

    def test_archetype_platform_dominator_when_f6_strong(self):
        view = _view(
            company=_company(ipo_date=date(2010, 1, 1)),
            frameworks=[_framework("F6", verdict="strong_fit"),
                        *(_framework(c) for c in
                          ("F1", "F2", "F3", "F4", "F5", "F7"))],
        )
        assert _lattice_profile_from_view(view).archetype == "platform_dominator"

    def test_archetype_pre_discovery_when_f1_strong_and_no_other(self):
        view = _view(
            company=_company(ipo_date=date(2010, 1, 1)),
            frameworks=[_framework("F1", verdict="strong_fit"),
                        *(_framework(c) for c in
                          ("F2", "F3", "F4", "F5", "F6", "F7"))],
        )
        assert _lattice_profile_from_view(view).archetype == "pre_discovery"

    def test_archetype_platform_beats_pre_discovery_when_both_strong(self):
        view = _view(
            company=_company(ipo_date=date(2010, 1, 1)),
            frameworks=[_framework("F1", verdict="strong_fit"),
                        _framework("F6", verdict="strong_fit"),
                        *(_framework(c) for c in
                          ("F2", "F3", "F4", "F5", "F7"))],
        )
        assert _lattice_profile_from_view(view).archetype == "platform_dominator"

    def test_unfeasible_framework_does_not_drive_archetype(self):
        view = _view(
            company=_company(ipo_date=date(2010, 1, 1)),
            frameworks=[_framework("F6", verdict="strong_fit", unfeasible=True),
                        *(_framework(c) for c in
                          ("F1", "F2", "F3", "F4", "F5", "F7"))],
        )
        assert _lattice_profile_from_view(view).archetype is None


# ── Section extraction ────────────────────────────────────────────────────


class TestExtractSection:
    def test_extracts_prose_under_heading(self):
        body = (
            "# Title\n\n"
            "## Summary\n\nFoo bar baz.\n\n"
            "## Inversion form\n\nQux.\n"
        )
        assert _extract_section(body, "Summary") == "Foo bar baz."
        assert _extract_section(body, "Inversion form") == "Qux."

    def test_missing_section_returns_empty(self):
        body = "## Summary\n\nFoo.\n"
        assert _extract_section(body, "Inversion form") == ""

    def test_case_insensitive(self):
        body = "## Summary\n\nFoo.\n"
        assert _extract_section(body, "summary") == "Foo."


# ── Lattice block formatting ──────────────────────────────────────────────


def _fake_model(slug: str, domain: str, *, body: str = "") -> MentalModel:
    return MentalModel(
        slug=slug,
        name=slug.replace("_", " ").title(),
        school="test",
        citation_tier="★★",
        always_load=True,
        related_models=["a", "b"],
        code_consequences=["does a thing"],
        token_cost_estimate=200,
        version=1.0,
        added=date(2026, 1, 1),
        last_reviewed=date(2026, 1, 1),
        domain=domain,
        body=body or "## Summary\n\nA model summary.\n\n## Inversion form\n\nA failure mode.\n",
        file_path=f"{domain}/{slug}.md",
    )


class TestFormatLatticeBlock:
    def test_empty_composition_returns_stub(self):
        comp = CompositionResult(
            selected=[], deferred=[], total_tokens=0, budget=6000,
        )
        out = _format_lattice_block(comp)
        assert "minimal-data dive" in out

    def test_groups_by_domain_and_includes_summary_inversion(self):
        comp = CompositionResult(
            selected=[
                _fake_model("alpha", "core"),
                _fake_model("beta", "bias"),
                _fake_model("gamma", "core"),
            ],
            deferred=[],
            total_tokens=600,
            budget=6000,
        )
        out = _format_lattice_block(comp)

        assert "Lattice — 3 models composed" in out
        assert "600/6000 tokens" in out
        assert "### bias/" in out
        assert "### core/" in out
        # Domain headers sorted alphabetically: bias before core
        assert out.index("### bias/") < out.index("### core/")
        # Each model emits Summary + Inversion lines
        assert "Summary: A model summary." in out
        assert "Inversion: A failure mode." in out


# ── User prompt integration ───────────────────────────────────────────────


class TestUserPromptIntegration:
    """End-to-end: `_build_user_prompt` should embed both lattice + scorecard JSON."""

    def test_user_prompt_contains_lattice_and_scorecard(self):
        view = _view()
        prompt = _build_user_prompt(view)

        # Header / framing
        assert "Generate a narrative for TEST" in prompt
        # Lattice block actually got composed (real lattice on disk loads)
        assert "Lattice —" in prompt
        # Scorecard JSON envelope intact
        assert "ScorecardView JSON" in prompt
        assert '"ticker": "TEST"' in prompt

    def test_user_prompt_handles_lattice_load_failure_gracefully(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        # Force the lazy loader to raise so we exercise the fallback.
        import deepdive.narrative as narrative_mod

        def _boom() -> dict[str, MentalModel]:
            raise RuntimeError("disk on fire")

        # Reset any cached lattice and patch the loader
        monkeypatch.setattr(narrative_mod, "_LATTICE_CACHE", None)
        monkeypatch.setattr(narrative_mod, "load_lattice", _boom)

        prompt = _build_user_prompt(_view())
        assert "Lattice: (unavailable)" in prompt
        # Scorecard JSON still present — narrative call should still proceed
        assert "ScorecardView JSON" in prompt


# ── Real-lattice smoke test ───────────────────────────────────────────────


class TestRealLatticeLoads:
    """The on-disk lattice must satisfy ADR-024 §1.3/§1.6 schema. If this
    test breaks, a model file regressed — fix the file, not this test.
    """

    def test_load_lattice_produces_models_with_required_sections(self):
        lattice = load_lattice()
        assert len(lattice) >= 100  # ADR-024 Stage C: 111 models
        # Spot-check: inversion is foundational and must be loadable
        assert "inversion" in lattice
        assert lattice["inversion"].always_load is True
        # Body of every model should have Summary + Inversion form sections
        sample = list(lattice.values())[:5]
        for m in sample:
            assert _extract_section(m.body, "Summary"), (
                f"{m.file_path}: missing Summary section"
            )
            assert _extract_section(m.body, "Inversion form"), (
                f"{m.file_path}: missing Inversion form section"
            )
