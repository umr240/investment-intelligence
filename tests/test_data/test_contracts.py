"""Data contracts (ADR-044): each contract's failing units, thresholds, recording and CLI."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import data.contracts as contracts
from data.contracts import ALL, BY_ID, DIVED, ContractResult, evaluate
from data.models.schema import (
    Base,
    Company,
    DataContractRun,
    DeepDiveRun,
    ExclusionVerdict,
    Financial,
    ScreenerRun,
    ScreenerStage,
)
from screener.policies import verdicts


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
    yield factory
    engine.dispose()


@pytest.fixture
def s(db: sessionmaker[Session]) -> Iterator[Session]:
    with db() as session:
        yield session


def _co(s: Session, ticker: str, **kw: Any) -> Company:
    c = Company(ticker=ticker, exchange="NASDAQ", name=f"{ticker} Inc", **kw)
    s.add(c)
    s.flush()
    return c


def _fin(s: Session, c: Company, fy: int, period: str = "annual", **kw: Any) -> None:
    s.add(Financial(company_id=c.id, fiscal_year=fy, period=period, **kw))
    s.flush()


def _dive(s: Session, c: Company) -> None:
    s.add(DeepDiveRun(company_id=c.id, ticker=c.ticker, mode="A"))
    s.flush()


def _run(s: Session, cid: str, scope: str = ALL) -> ContractResult:
    return evaluate(s, BY_ID[cid], scope)


# ── C1–C4: company contracts ───────────────────────────────────────────────


def test_c1_counts_companies_with_annual_rows_and_no_revenue(
    s: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, bad, exempt = _co(s, "OK"), _co(s, "BAD"), _co(s, "EXEMPT")
    _co(s, "NOROWS")
    _fin(s, ok, 2024, revenue=None)
    _fin(s, ok, 2025, revenue=10.0)
    _fin(s, bad, 2025, revenue=None)
    _fin(s, bad, 2025, "Q1", revenue=3.0)  # quarterly revenue does not satisfy C1
    _fin(s, exempt, 2025)
    monkeypatch.setattr(contracts, "C1_EXEMPT", frozenset({"EXEMPT"}))
    r = _run(s, "C1")
    assert (r.failing, r.total, r.keys) == (1, 2, ["BAD"])


def test_c1_allows_five_percent(s: Session) -> None:
    for i in range(20):
        _fin(s, _co(s, f"T{i:02d}"), 2025, revenue=None if i == 0 else 1.0)
    assert _run(s, "C1").passed is True  # 1 of 20 = 5%
    _fin(s, _co(s, "T20"), 2025, revenue=None)
    assert _run(s, "C1").passed is False  # 2 of 21


def test_c2_blocks_on_dived_and_reports_the_rest(s: Session) -> None:
    dived, other, fine = _co(s, "DIVED"), _co(s, "OTHER"), _co(s, "FINE")
    for c in (dived, other, fine):
        _fin(s, c, 2025)
    _fin(s, fine, 2025, "Q1")
    _dive(s, dived)
    _dive(s, fine)
    d, a = _run(s, "C2", DIVED), _run(s, "C2", ALL)
    assert (d.keys, d.total, d.passed) == (["DIVED"], 2, False)
    assert (sorted(a.keys), a.total, a.passed) == (["DIVED", "OTHER"], 3, None)


def test_c3_reads_only_the_latest_annual_row(s: Session) -> None:
    known, unknown = _co(s, "KNOWN"), _co(s, "UNKNOWN")
    _fin(s, known, 2024, share_split_factor=None)
    _fin(s, known, 2025, share_split_factor=1.0)
    _fin(s, known, 2026, "Q1", share_split_factor=None)  # a later quarter is not the latest annual
    _fin(s, unknown, 2024, share_split_factor=1.0)
    _fin(s, unknown, 2025, share_split_factor=None)
    for c in (known, unknown):
        _dive(s, c)
    r = _run(s, "C3", DIVED)
    assert (r.keys, r.total) == (["UNKNOWN"], 2)


def _quarters(s: Session, c: Company, shares: list[float], factors: list[float | None]) -> None:
    for i, (n, k) in enumerate(zip(shares, factors, strict=True)):
        end = date(2024 + i // 4, 3 * (i % 4) + 1, 28)
        _fin(s, c, 2024 + i // 4, f"Q{i % 4 + 1}", shares_outstanding=n,
             share_split_factor=k, period_end_date=end)  # fmt: skip


def test_c4_flags_a_jump_with_no_recorded_split(s: Session) -> None:
    mixed, split, steady = _co(s, "MIXED"), _co(s, "SPLIT"), _co(s, "STEADY")
    _quarters(s, mixed, [250.0, 1000.0, 251.0], [None, None, None])  # NVDA-style basis mix
    _quarters(s, split, [250.0, 1000.0], [4.0, 1.0])  # the factor records the split
    _quarters(s, steady, [250.0, 400.0, 260.0], [None, None, None])  # under 2x
    _co(s, "ONEQ")
    r = _run(s, "C4")
    assert (r.keys, r.total) == (["MIXED"], 3)


def test_c4_takes_quarters_in_period_order(s: Session) -> None:
    c = _co(s, "ORDER")
    # By period end 100, 150, 220: no jump. In insertion order 220 -> 100 would be one.
    _fin(s, c, 2024, "Q3", shares_outstanding=220.0, period_end_date=date(2024, 9, 30))
    _fin(s, c, 2024, "Q1", shares_outstanding=100.0, period_end_date=date(2024, 3, 31))
    _fin(s, c, 2024, "Q2", shares_outstanding=150.0, period_end_date=date(2024, 6, 30))
    assert _run(s, "C4").failing == 0


# ── C5: exclusion verdicts ─────────────────────────────────────────────────


class _Policy:
    name = "p"

    def classify(self, sector: str | None, industry: str | None) -> Any:
        from screener.policies.base import INCLUDED, PolicyVerdict

        return PolicyVerdict(True, "banking") if industry == "Banks" else INCLUDED

    def not_excluded(self) -> Any:
        return verdicts.lacks_status("p", "fail")

    def eligible(self) -> Any:
        return verdicts.has_status("p", "pass")


def test_c5_compares_stored_verdicts_with_the_classifier(
    s: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("screener.policies.get_policy", lambda name=None: _Policy())
    rows = [
        ("AGREE_FAIL", "Banks", "fail", None),
        ("AGREE_PASS", "Software", "pass", None),
        ("STALE_FAIL", "Software", "fail", None),
        ("STALE_PASS", "Banks", "pass", None),
        ("OVERRIDDEN", "Banks", "pass", contracts.OVERRIDE_SOURCE),
        ("UNVERIFIED", "Banks", "unverified", None),
    ]
    for ticker, industry, status, source in rows:
        c = _co(s, ticker, industry=industry)
        s.add(ExclusionVerdict(company_id=c.id, policy="p", status=status, source=source))
    _co(s, "NEVER", industry="Banks")
    s.flush()
    r = _run(s, "C5")
    assert (sorted(r.keys), r.total) == (["STALE_FAIL", "STALE_PASS"], 5)
    assert r.note == "policy p; 2 never classified"


def test_c5_has_no_units_under_the_none_policy(s: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from screener.policies.none import NonePolicy

    monkeypatch.setattr("screener.policies.get_policy", lambda name=None: NonePolicy())
    _co(s, "ANY", industry="Banks")
    r = _run(s, "C5")
    assert (r.failing, r.total, r.passed) == (0, 0, True)


# ── C6–C8 ──────────────────────────────────────────────────────────────────


def test_c6_counts_low_and_missing_completeness(s: Session) -> None:
    _co(s, "LOW", data_completeness=0.49)
    _co(s, "EDGE", data_completeness=0.5)
    _co(s, "NONE")
    r = _run(s, "C6")
    assert (sorted(r.keys), r.total, r.passed) == (["LOW", "NONE"], 3, None)


def _screener_run(s: Session, universe: int | None, *stages: tuple[str, str]) -> int:
    run = ScreenerRun(universe_count=universe)
    s.add(run)
    s.flush()
    for stage, status in stages:
        s.add(ScreenerStage(screener_run_id=run.id, stage=stage, status=status))
    s.flush()
    return int(run.id)


def test_c7_counts_only_finished_runs(s: Session) -> None:
    good = _screener_run(s, 900, ("A", "completed"), ("B", "completed"), ("C", "completed"))
    empty = _screener_run(s, 0, ("A", "completed"), ("B", "completed"), ("C", "completed"))
    failed = _screener_run(s, 0, ("A", "failed"))
    _screener_run(s, 0, ("A", "completed"))  # between stages: not finished
    _screener_run(s, 0, ("A", "completed"), ("B", "running"))
    legacy = _screener_run(s, None)  # single-shot, no stages
    r = _run(s, "C7")
    assert r.total == 4 and good not in {int(k.split()[1]) for k in r.keys}
    assert sorted(r.keys) == sorted(f"run {i}" for i in (empty, failed, legacy))


def test_c8_reads_the_latest_completed_stage_b(s: Session) -> None:
    assert _run(s, "C8").total == 0
    run = _screener_run(s, 0)
    for when, filers, revenue in ((datetime(2026, 1, 1), 10, 1), (datetime(2026, 2, 1), 100, 67)):
        funnel = {"T4_frames_filers": filers, "T4_frames_revenue": revenue}
        s.add(ScreenerStage(
            screener_run_id=run, stage="B", status="completed", completed_at=when,
            state_json=json.dumps({"gate_funnel": funnel}),
        ))  # fmt: skip
        run = _screener_run(s, 0)
    r = _run(s, "C8")
    assert (r.failing, r.total, r.keys, r.passed) == (33, 100, [], None)


# ── Recording, per-ticker gaps, the screener hook ──────────────────────────


def test_record_keeps_twenty_sorted_keys(contract_rows: list[dict[str, Any]]) -> None:
    keys = [f"T{i:02d}" for i in range(30, 0, -1)]
    contracts.record([ContractResult(BY_ID["C1"], ALL, 30, 100, keys, 0.05)], "check")
    (row,) = contract_rows
    assert json.loads(row["sample_json"]) == sorted(keys)[:20]
    assert (row["failing"], row["total"], row["passed"]) == (30, 100, False)


def test_check_ticker_turns_violations_into_gaps(
    s: Session, contract_rows: list[dict[str, Any]]
) -> None:
    c = _co(s, "GAPPY")
    _fin(s, c, 2025, revenue=None)
    s.commit()
    gaps = contracts.check_ticker("GAPPY")
    assert gaps == [
        "GAPPY: data contract C1 (block) not met: annual revenue present",
        "GAPPY: data contract C2 (block) not met: quarterly rows present",
        "GAPPY: data contract C3 (warn) not met: latest annual split factor known",
    ]
    assert [(r["contract_id"], r["scope"], r["trigger"]) for r in contract_rows] == [
        (cid, "GAPPY", "refresh") for cid in ("C1", "C2", "C3", "C4")
    ]


def test_screener_hook_never_raises(
    db: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("db gone")

    monkeypatch.setattr(contracts, "evaluate_all", boom)
    contracts.check_after_screener_stage()
    assert "screener data contracts not checked: RuntimeError" in caplog.text


def test_screener_hook_records_c5_c7_c8(
    db: sessionmaker[Session], contract_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("screener.policies.get_policy", lambda name=None: _Policy())
    contracts.check_after_screener_stage()
    assert [(r["contract_id"], r["trigger"]) for r in contract_rows] == [
        ("C5", "screener"),
        ("C7", "screener"),
        ("C8", "screener"),
    ]


def test_rows_fit_the_table(s: Session, contract_rows: list[dict[str, Any]]) -> None:
    contracts.record([ContractResult(BY_ID["C6"], ALL, 1, 2, ["X"], None, "n")], "check")
    s.add_all(DataContractRun(**row) for row in contract_rows)
    s.flush()
    (row,) = s.query(DataContractRun).all()
    rec: Any = row  # Column-style model: mypy types its attributes as Column[...]
    assert (rec.contract_id, rec.passed, rec.threshold, rec.note) == ("C6", None, None, "n")


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli(*args: str) -> Any:
    from typer.testing import CliRunner

    from cli.main import app

    return CliRunner().invoke(app, ["data", *args], env={"COLUMNS": "200"})


def test_data_check_exits_1_on_a_failing_block_contract(
    s: Session, contract_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("screener.policies.get_policy", lambda name=None: _Policy())
    c = _co(s, "WARNONLY")
    _fin(s, c, 2025, revenue=1.0)
    _fin(s, c, 2025, "Q1")
    s.commit()
    ok = _cli("check")
    assert ok.exit_code == 0, ok.output
    assert len(contract_rows) == 9  # C2 has two scopes
    _fin(s, _co(s, "NOREV"), 2025, revenue=None)
    s.commit()
    bad = _cli("check", "--contract", "c1")
    assert bad.exit_code == 1 and "NOREV" in bad.output and "FAIL" in bad.output


def test_data_check_rejects_unknown_and_non_ticker_contracts(db: sessionmaker[Session]) -> None:
    assert _cli("check", "--contract", "C9").exit_code == 2
    assert _cli("check", "--ticker", "X", "--contract", "C7").exit_code == 2


def test_backfill_covers_company_contracts_only(db: sessionmaker[Session]) -> None:
    out = _cli("backfill", "--contract", "C5")
    assert out.exit_code == 2 and "C1-C4" in out.output
    assert _cli("backfill", "--contract", "C1,C2").exit_code == 2
    assert _cli("backfill", "--contract", ",").exit_code == 2


def test_backfill_refreshes_failing_tickers_after_confirmation(
    s: Session, contract_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    for t in ("AAA", "BBB", "CCC"):
        _fin(s, _co(s, t), 2025, revenue=None)
    s.commit()
    refreshed: list[str] = []

    async def fake_refresh(ticker: str, **_kw: Any) -> list[str]:
        refreshed.append(ticker)
        return []

    monkeypatch.setattr("data.pipeline.refresh_ticker", fake_refresh)
    declined = _cli("backfill", "--contract", "C1", "--limit", "2")  # no input: declines
    assert declined.exit_code == 1 and refreshed == []
    done = _cli("backfill", "--contract", "C1", "--limit", "2", "--yes")
    assert done.exit_code == 0, done.output
    assert refreshed == ["AAA", "BBB"]
    assert [(r["contract_id"], r["trigger"]) for r in contract_rows] == [("C1", "backfill")]


def test_screener_stages_check_contracts_when_they_finish(
    s: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import data.db
    import screener.stages as stages

    calls: list[str] = []
    # stages binds get_session at import: without this the helpers write to the real DB.
    monkeypatch.setattr(stages, "get_session", data.db.get_session)
    monkeypatch.setattr(stages, "check_after_screener_stage", lambda: calls.append("checked"))
    run = _screener_run(s, 0, ("A", "running"), ("B", "running"))
    a, b = s.query(ScreenerStage).filter_by(screener_run_id=run).order_by(ScreenerStage.stage)
    s.commit()
    stages._complete_stage(int(a.id), output_count=1, state="{}")
    stages._fail_stage(int(b.id), "frames missing")
    assert calls == ["checked", "checked"]
    s.expire_all()
    assert [st.status for st in (a, b)] == ["completed", "failed"]  # written here, not elsewhere


def test_stage_b_records_the_frames_counts_c8_reads(
    s: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from types import SimpleNamespace

    import data.db
    import data.edgar_frames as edgar_frames
    import screener.stages as stages
    import screener.tier4_frames as tier4
    from screener.tier4_frames import Tier4Snapshot

    monkeypatch.setattr(stages, "get_session", data.db.get_session)
    monkeypatch.setattr(stages, "check_after_screener_stage", lambda: None)
    run = _screener_run(s, 0)
    state = {"tier3_survivors": [{"ticker": "NVDA", "cik": 1}], "gate_funnel": {"T3_x": 1}}
    s.add(ScreenerStage(screener_run_id=run, stage="A", status="completed",
                        state_json=json.dumps(state)))  # fmt: skip
    s.commit()

    async def frames(*_a: Any, **_k: Any) -> dict[int, Any]:
        return {}

    snaps = {1: Tier4Snapshot(cik=1, revenue=5e9), 2: Tier4Snapshot(cik=2), 3: Tier4Snapshot(cik=3)}
    monkeypatch.setattr(edgar_frames, "build_frames_universe_async", frames)
    monkeypatch.setattr(tier4, "build_tier4_snapshots", lambda _f: snaps)
    picked = [SimpleNamespace(ticker="NVDA", flags=[])]
    monkeypatch.setattr(tier4, "evaluate_tier4", lambda _survivors, _s: picked)
    monkeypatch.setattr(tier4, "rank_and_truncate", lambda results, _n: (results, [], []))
    asyncio.run(stages.run_stage_b(run))
    r = _run(s, "C8")
    assert (r.failing, r.total) == (2, 3)


def test_refresh_ticker_returns_contract_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    import data.api.yfinance_client as yf
    import data.pipeline as pipeline
    import data.sources as sources
    import data.sources.jurisdiction as jurisdiction
    from frameworks.base import DataRequirement

    async def fetch(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(gaps=[], financials=[])

    empty = SimpleNamespace(gaps=[])
    monkeypatch.setattr(sources, "resolve_source", lambda *_a: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(jurisdiction, "jurisdiction_for", lambda _t: SimpleNamespace(regime="none"))
    monkeypatch.setattr(yf, "fetch_yfinance_snapshot", lambda *_a: empty)
    for name in ("_ensure_company_row", "_apply_adr018_reconciliation",
                 "_compute_buyback_yields", "_record_share_split_basis",
                 "_fetch_fmp_profile_safe", "_fetch_polygon_safe"):  # fmt: skip
        monkeypatch.setattr(pipeline, name, lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_persist_yfinance_snapshot", lambda *_a: [])
    monkeypatch.setattr(contracts, "check_ticker", lambda t: [f"{t}: contract gap"])
    gaps = asyncio.run(pipeline.refresh_ticker("ZZZ", requirement=DataRequirement()))
    assert gaps == ["ZZZ: contract gap"]
