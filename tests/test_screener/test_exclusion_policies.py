"""The exclusion-policy hook: `none` excludes nothing, names resolve or fail fast.

Release Phase 2. A stand-in policy, registered the way an add-on would be,
proves the hook wiring without depending on any real policy.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

import screener.policies as policies
from config.settings import Settings, settings
from data.models.schema import Company
from screener.gates import _gate_g1_policy
from screener.pipeline import _apply_exclusion_policy, _EnrichedTicker
from screener.policies import INCLUDED, PolicyVerdict, UnknownPolicyError, get_policy
from screener.query import ScreenerQuery, run_screener


def _ticker(symbol: str, sector: str, industry: str) -> _EnrichedTicker:
    return _EnrichedTicker(
        ticker=symbol,
        name=symbol,
        cik=None,
        exchange="NYSE",
        market_cap=5e9,
        sector=sector,
        industry=industry,
        country="US",
        currency="USD",
        analyst_count=3,
    )


SENSITIVE = [
    _ticker("JPM", "Financial Services", "Banks - Diversified"),
    _ticker("TAP", "Consumer Defensive", "Beverages - Brewers"),
    _ticker("LMT", "Industrials", "Aerospace & Defense"),
]


class _SectorPolicy:
    """Stand-in add-on: excludes one sector, everywhere the hook asks."""

    name = "no_utilities"

    def classify(self, sector: str | None, industry: str | None) -> PolicyVerdict:
        return PolicyVerdict(True, "utilities") if sector == "Utilities" else INCLUDED

    def not_excluded(self) -> ColumnElement[bool]:
        return Company.sector != "Utilities"

    def eligible(self) -> ColumnElement[bool]:
        return Company.sector != "Utilities"


def _install(monkeypatch: pytest.MonkeyPatch, *eps: Any) -> None:
    def fake_entry_points(group: str) -> list[Any]:
        assert group == policies.ENTRY_POINT_GROUP
        return list(eps)

    monkeypatch.setattr(policies, "entry_points", fake_entry_points)
    policies._add_ons.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_registry() -> Any:
    policies._add_ons.cache_clear()
    yield
    policies._add_ons.cache_clear()


@pytest.fixture
def add_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SimpleNamespace(name=_SectorPolicy.name, load=lambda: _SectorPolicy))


def test_default_policy_is_none() -> None:
    assert Settings.model_fields["exclusion_policy"].default == "none"


def test_none_keeps_every_company_at_tier3() -> None:
    survivors, excluded = _apply_exclusion_policy(SENSITIVE, get_policy("none"))
    assert ([t.ticker for t in survivors], excluded) == (["JPM", "TAP", "LMT"], [])


def test_tier3_records_the_policy_reason(add_on: None) -> None:
    utility = _ticker("DUK", "Utilities", "Utilities - Regulated Electric")
    policy = get_policy("no_utilities")
    survivors, excluded = _apply_exclusion_policy([*SENSITIVE, utility], policy)
    assert [t.ticker for t in survivors] == ["JPM", "TAP", "LMT"]
    assert [(t.ticker, reason) for t, reason in excluded] == [("DUK", "utilities")]


def test_g1_passes_under_none_even_without_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "exclusion_policy", "none")
    reader = SimpleNamespace(company_or_none=lambda: None, latest_annual_or_ttm=lambda: None)
    r = _gate_g1_policy(reader)  # type: ignore[arg-type]
    assert (r.gate_id, r.passed, r.reason) == ("G1_policy", True, "no exclusion policy active")


@pytest.fixture
def universe(session: Session) -> Session:
    rows = (("SOFT", "Technology"), ("DUK", "Utilities"), ("KO", "Consumer Defensive"))
    for ticker, sector in rows:
        session.add(
            Company(
                ticker=ticker,
                exchange="NYSE",
                name=ticker,
                status="screener_candidate",
                sector=sector,
                market_cap_usd=1e9,
                data_completeness=1.0,
            )
        )
    session.flush()
    return session


def _selected(session: Session, policy: str) -> set[str]:
    stmt = select(Company.ticker).where(get_policy(policy).not_excluded())
    return {str(t) for t in session.execute(stmt).scalars()}


def test_selectors_follow_the_policy(universe: Session, add_on: None) -> None:
    assert _selected(universe, "none") == {"SOFT", "DUK", "KO"}
    assert _selected(universe, "no_utilities") == {"SOFT", "KO"}


def test_warehouse_query_follows_the_policy(universe: Session, add_on: None) -> None:
    def tickers(policy: str) -> set[str]:
        rows = run_screener(universe, ScreenerQuery(policy=policy, top_n=10))
        return {str(c.ticker) for c in rows}

    assert tickers("none") == {"SOFT", "DUK", "KO"}
    assert tickers("no_utilities") == {"SOFT", "KO"}


def test_unknown_policy_fails_fast_with_the_registered_names() -> None:
    with pytest.raises(UnknownPolicyError, match=r"registered: .*\bnone\b"):
        get_policy("esg")


def test_add_on_policies_are_discovered_from_entry_points(add_on: None) -> None:
    assert get_policy("no_utilities").name == "no_utilities"


def test_an_add_on_cannot_replace_a_built_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SimpleNamespace(name="none", load=lambda: object))
    assert get_policy("none").name == "none"


def test_a_broken_add_on_does_not_break_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Any:
        raise ImportError("missing dependency")

    _install(monkeypatch, SimpleNamespace(name="broken", load=broken))
    assert get_policy("none").name == "none"
    assert "broken" in policies.registered()
    with pytest.raises(UnknownPolicyError, match="failed to load: missing dependency"):
        get_policy("broken")


def test_add_ons_are_scanned_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def counting(group: str) -> list[Any]:
        calls.append(group)
        return []

    monkeypatch.setattr(policies, "entry_points", counting)
    policies._add_ons.cache_clear()
    for _ in range(3):
        get_policy("none")
        policies.registered()
    assert len(calls) == 1


def test_g1_uses_the_runs_policy_not_the_configured_one(
    monkeypatch: pytest.MonkeyPatch,
    add_on: None,
) -> None:
    class _Strict(_SectorPolicy):
        def gate(self, reader: Any) -> PolicyVerdict:
            return PolicyVerdict(True, "strict")

    monkeypatch.setattr(settings, "exclusion_policy", "none")
    reader = SimpleNamespace(company_or_none=lambda: None, latest_annual_or_ttm=lambda: None)
    r = _gate_g1_policy(reader, _Strict())  # type: ignore[arg-type]
    assert (r.passed, r.reason) == (False, "strict")


def test_stage_a_rerun_uses_the_policy_recorded_on_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tier 3 and gate G1 must agree: Stage C gates under the recorded policy.
    import screener.policies as policies
    import screener.stages as stages
    from data.models.api_models import ScreenerParams

    names = {"recorded": "recorded", "alias": "recorded", "other": "other"}

    class _Named:
        def __init__(self, name: str) -> None:
            self.name = names[name]

    monkeypatch.setattr(
        stages, "_load_run_params", lambda _rid: ScreenerParams(exclusion_policy="recorded")
    )
    monkeypatch.setattr(policies, "get_policy", lambda name=None: _Named(name or "recorded"))
    assert stages._run_policy(1, None) == "recorded"
    assert stages._run_policy(1, "recorded") == "recorded"
    # An entry-point name that resolves to the recorded policy is the same policy.
    assert stages._run_policy(1, "alias") == "recorded"
    with pytest.raises(ValueError, match="created under exclusion policy 'recorded'"):
        stages._run_policy(1, "other")


def test_a_job_with_the_retired_ethics_filter_key_is_rejected() -> None:
    import asyncio

    from scheduler.jobs import _run_screener_stage

    job = {"screen_params": {"ethics_filter": "x"}, "mode": "B"}
    with pytest.raises(ValueError, match="retired key 'ethics_filter'"):
        asyncio.run(_run_screener_stage("screener-stage-A", job))
