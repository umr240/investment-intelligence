"""Golden-set export (ADR-047 §2.1, §2.7): which dives become cases, how they are stamped."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import deepdive.narrative_eval.export as export
from data.models.schema import Base, Company, DeepDiveRun, Financial
from deepdive.narrative_eval.export import CANARY, TEST, TRAIN, replay_mismatch, split_of
from deepdive.scorecard_view import (
    CompanyHeader,
    CompositeView,
    FrameworkView,
    OverlayTriggerView,
    ScorecardView,
    StageView,
)
from frameworks.composite import COMPOSITE_SINCE, COMPOSITE_VERSION


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def session() -> Iterator[Session]:
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr("data.db.get_session", session)
    # Bound at import: without this the frozen-view loader reads the real DB.
    monkeypatch.setattr("deepdive.scorecard_view.get_session", session)
    yield factory
    engine.dispose()


def _view(ticker: str = "ACME", **kw: Any) -> ScorecardView:
    listed = kw.pop("listed", 1)
    header: dict[str, Any] = {f: None for f in CompanyHeader.__dataclass_fields__}
    header.update(ticker=ticker, name=f"{ticker} Inc", market_cap_usd=kw.pop("cap", None))
    fw = FrameworkView(
        code="F2", title="Momentum", score=0.0, max_score=10.0, verdict="unfeasible",
        band="", key_signals=[], data_gaps=[], is_unfeasible=kw.pop("unfeasible", False),
        unfeasible_reason=f"recent IPO / insufficient annual history; listed {listed}yr",
    )  # fmt: skip
    return ScorecardView(
        ticker=ticker,
        run_date=kw.pop("run_date", date(2026, 10, 25)),
        mode_used="default",
        company=CompanyHeader(**header),
        stage=StageView(stage=kw.pop("stage", "mid_cap"), reasoning={}),
        composite=CompositeView(
            score=5.0,
            verdict=kw.pop("verdict", "monitor"),
            mode_resolved="B",
            weights_used={"F2": 1.0},
            weights_renormalised=False,
        ),  # fmt: skip
        frameworks=[fw],
        overlay_triggers=[],
        fetch_data_gaps=[],
        overlay_verdicts=kw.pop("overlays", {}),
    )


def _dive(s: Session, view: ScorecardView, *, inputs: bool = True, tamper: bool = False,
          when: datetime | None = None, currency: str = "USD") -> int:  # fmt: skip
    co = s.query(Company).filter_by(ticker=view.ticker).first()
    if co is None:
        co = Company(ticker=view.ticker, exchange="NASDAQ", name=view.company.name,
                     currency=currency)  # fmt: skip
        s.add(co)
        s.flush()
    body = view.to_llm_context()
    sha = hashlib.sha256(body.encode()).hexdigest()
    run = DeepDiveRun(
        company_id=co.id, ticker=view.ticker, mode="default",
        run_date=when or datetime(2026, 10, 25, 3, 50),
        scorecard_view_json=body + (" " if tamper else ""), scorecard_view_sha256=sha,
        inputs_sha256="i" * 64 if inputs else None,
    )  # fmt: skip
    s.add(run)
    s.flush()
    return int(run.id)


def _collect(db: sessionmaker[Session]) -> list[export.GoldenCase]:
    with db() as s:
        return export.collect_cases(s)


def test_split_is_stable_and_about_a_third() -> None:
    tickers = [f"T{i:03d}" for i in range(600)]
    first = [split_of(t) for t in tickers]
    assert first == [split_of(t) for t in tickers]
    assert 0.25 < first.count(TEST) / len(first) < 0.42


def test_collects_the_latest_intact_recorded_dive_per_company(db: sessionmaker[Session]) -> None:
    with db.begin() as s:  # commits on exit
        _dive(s, _view("ACME"))
        newest = _dive(s, _view("ACME", verdict="watchlist"))
        _dive(s, _view("NOINPUTS"), inputs=False)  # before DEC-47: withheld
        _dive(s, _view("TAMPERED"), tamper=True)  # frozen body no longer matches its hash
        old = datetime.combine(COMPOSITE_SINCE, datetime.min.time()).replace(day=1)
        _dive(s, _view("OLDFORMULA"), when=old)  # scored by an earlier composite version
    cases = _collect(db)
    assert [(c.ticker, c.run_id) for c in cases] == [("ACME", newest)]


def test_strata_come_from_the_view_and_the_company(db: sessionmaker[Session]) -> None:
    with db.begin() as s:  # commits on exit
        _dive(s, _view("BIG", stage="established", verdict="watchlist", cap=1e12))
        _dive(s, _view("IPO", stage="pre_profitability", unfeasible=True, verdict="exclude"))
        _dive(s, _view("OLDLISTING", unfeasible=True, listed=9))  # F7 short, not an IPO
        _dive(s, _view("SPIN", overlays={"PSA": "strong_spinoff_candidate",
                                         "BEW": "EXTREME_WINNER_CANDIDATE"}))  # fmt: skip
        _dive(s, _view("NOTSPIN", overlays={"PSA": "not_a_spinoff_candidate",
                                            "BEW": "moderate_winner_candidate"}))  # fmt: skip
        _dive(s, _view("CAD", verdict="research_only"), currency="CAD")
        split = _view("SPLIT")
        _dive(s, split)
        co = s.query(Company).filter_by(ticker="SPLIT").one()
        s.add(
            Financial(company_id=co.id, fiscal_year=2024, period="annual", share_split_factor=4.0)
        )
        s.add(
            Financial(company_id=co.id, fiscal_year=2025, period="annual", share_split_factor=1.0)
        )
    got = {c.ticker: c.strata for c in _collect(db)}
    assert got == {
        "BIG": ("established_compounder",),
        "IPO": ("pre_profitability", "recent_ipo_unfeasible", "exclude_path"),
        "SPIN": ("spinoff", "extreme_winner"),
        "NOTSPIN": (),
        "OLDLISTING": (),
        "CAD": ("research_only", "non_usd_filer"),
        "SPLIT": ("split_affected",),
    }


def test_fixture_is_stamped_and_only_test_cases_carry_the_canary(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with db.begin() as s:  # commits on exit
        for t in ("AAA", "BBB"):
            _dive(s, _view(t, cap=5e9))
    monkeypatch.setattr(export, "split_of", lambda t: TEST if t == "AAA" else TRAIN)
    by_ticker = {c.ticker: c.fixture() for c in _collect(db)}
    test, train = by_ticker["AAA"], by_ticker["BBB"]
    assert test["canary"] == CANARY and "canary" not in train
    assert test["schema_version"] == ScorecardView.schema_version
    assert test["composite_version"] == COMPOSITE_VERSION
    assert test["view"]["ticker"] == "AAA"
    assert replay_mismatch(test) is None and replay_mismatch(train) is None


def test_third_party_values_are_withheld_and_recorded(db: sessionmaker[Session]) -> None:
    with_short = _view("WITH", cap=5e9)
    with_short.frameworks[0].key_signals = [("12-1 momentum", "+34%")]
    with_short.frameworks.append(
        FrameworkView(
            code="F4",
            title="Stealth",
            score=4.0,
            max_score=10.0,
            verdict="partial",
            band="",
            key_signals=[("Short int (current)", "3.1%"), ("EPS acceleration", "yes")],
            data_gaps=[],
        )  # fmt: skip
    )
    # The shapes real views carry copies in (frameworks/composite.py, overlays/detector.py).
    with_short.stage.reasoning = {"market_cap_usd": 5e9, "net_income_positive": True}
    with_short.overlay_triggers = [
        OverlayTriggerView(
            overlay_type="ICA", trigger_id="ICA-4", condition="", framework_section="F5",
            relevant_numbers={"pb_ratio": 3.1, "current_ev_revenue": 7.2, "roic": 0.2},
        )
    ]  # fmt: skip
    with db.begin() as s:  # commits on exit
        frozen = _dive(s, with_short)
        _dive(s, _view("WITHOUT"))
    by_ticker = {c.ticker: c for c in _collect(db)}
    case = by_ticker["WITH"]
    assert sorted(case.withheld) == [
        "company.market_cap_usd",
        "frameworks.F4.Short int (current)",
        "overlay_triggers[0].relevant_numbers.current_ev_revenue",
        "overlay_triggers[0].relevant_numbers.pb_ratio",
        "stage.reasoning.market_cap_usd",
    ]
    assert by_ticker["WITHOUT"].withheld == ()
    fixture = case.fixture()
    view = fixture["view"]
    assert view["company"]["market_cap_usd"] is None
    assert view["stage"]["reasoning"] == {"market_cap_usd": None, "net_income_positive": True}
    assert view["overlay_triggers"][0]["relevant_numbers"] == {
        "pb_ratio": None, "current_ev_revenue": None, "roic": 0.2,
    }  # fmt: skip
    assert "5000000000" not in case.body
    assert view["frameworks"][1]["key_signals"] == [
        ["Short int (current)", export.WITHHELD],
        ["EPS acceleration", "yes"],
    ]
    assert view["frameworks"][0]["key_signals"] == [["12-1 momentum", "+34%"]]  # computed here
    with db() as s:
        stored = s.get(DeepDiveRun, frozen)
        assert stored is not None
        assert fixture["source_view_sha256"] == stored.scorecard_view_sha256
    assert fixture["view_sha256"] != fixture["source_view_sha256"]
    assert replay_mismatch(fixture) is None


def test_a_withheld_value_under_another_key_stops_the_export(db: sessionmaker[Session]) -> None:
    leaky = _view("LEAKY", cap=5e9)
    leaky.stage.reasoning = {"cap_used": 5e9}
    with db.begin() as s:  # commits on exit
        _dive(s, leaky)
    with pytest.raises(export.WithheldValueLeak, match="LEAKY"):
        _collect(db)


def test_a_withheld_value_copied_as_an_integer_also_stops_the_export(
    db: sessionmaker[Session],
) -> None:
    leaky = _view("INTCOPY", cap=5e9)
    leaky.stage.reasoning = {"cap_used": 5_000_000_000}
    with db.begin() as s:  # commits on exit
        _dive(s, leaky)
    with pytest.raises(export.WithheldValueLeak, match="INTCOPY"):
        _collect(db)


def test_a_withheld_value_ending_a_sentence_still_stops_the_export(
    db: sessionmaker[Session],
) -> None:
    leaky = _view("PERIOD", cap=5e9)
    leaky.stage.reasoning = {"note": "cap 5000000000."}
    with db.begin() as s:  # commits on exit
        _dive(s, leaky)
    with pytest.raises(export.WithheldValueLeak, match="PERIOD"):
        _collect(db)


def test_a_larger_number_containing_a_withheld_one_is_not_a_leak(
    db: sessionmaker[Session],
) -> None:
    view = _view("BIGGER", cap=5e9)
    view.stage.reasoning = {"revenue": 15e9, "assets": 50000000000}
    with db.begin() as s:  # commits on exit
        _dive(s, view)
    assert [c.ticker for c in _collect(db)] == ["BIGGER"]


def test_a_view_from_another_schema_version_is_not_exported(db: sessionmaker[Session]) -> None:
    old = _view("OLD")
    old.schema_version = "0.9"
    with db.begin() as s:  # commits on exit
        _dive(s, old)
        _dive(s, _view("CURRENT"))
    assert [c.ticker for c in _collect(db)] == ["CURRENT"]


def test_coverage_names_missing_strata(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with db.begin() as s:  # commits on exit
        _dive(s, _view("IPO", stage="pre_profitability"))
    monkeypatch.setattr(export, "split_of", lambda _t: TRAIN)
    cov = export.coverage(_collect(db))
    assert cov["pre_profitability"] == {TRAIN: 1, TEST: 0}
    assert cov["spinoff"] == {TRAIN: 0, TEST: 0}
    assert list(cov) == list(export.STRATA)


def test_replay_refuses_a_case_whose_versions_or_view_changed() -> None:
    body = _view().to_llm_context()
    fixture = {
        "schema_version": ScorecardView.schema_version,
        "composite_version": COMPOSITE_VERSION,
        "view_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "view": json.loads(body),
    }
    assert replay_mismatch(fixture) is None
    assert "schema" in str(replay_mismatch({**fixture, "schema_version": "0.9"}))
    assert "composite" in str(replay_mismatch({**fixture, "composite_version": 0}))
    edited = {**fixture, "view": {**fixture["view"], "mode_used": "A"}}
    assert "hash" in str(replay_mismatch(edited))
    broken = {**fixture, "view": {k: v for k, v in fixture["view"].items() if k != "stage"}}
    assert "no longer fits" in str(replay_mismatch(broken))


def test_write_cases_files_by_split(db: sessionmaker[Session], tmp_path: Path) -> None:
    with db.begin() as s:  # commits on exit
        _dive(s, _view("BRK/B"))
    (case,) = _collect(db)
    (path,) = export.write_cases([case], tmp_path)
    assert path == tmp_path / case.split / "BRK_B.json"
    assert json.loads(path.read_text())["case_id"] == "BRK/B"


def test_cli_reports_and_writes_only_when_asked(db: sessionmaker[Session], tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from cli.main import app

    with db.begin() as s:  # commits on exit
        _dive(s, _view("ACME", stage="pre_profitability", cap=5e9))
    runner = CliRunner()
    args = ["narrative", "eval", "export", "--out", str(tmp_path)]
    report = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert report.exit_code == 0, report.output
    assert "1 cases" in report.output and "spinoff" in report.output
    assert "1 third-party values withheld across 1 cases" in report.output
    assert not any(tmp_path.iterdir())
    wrote = runner.invoke(app, [*args, "--write"], env={"COLUMNS": "200"})
    assert wrote.exit_code == 0, wrote.output
    assert len(list(tmp_path.rglob("*.json"))) == 1
