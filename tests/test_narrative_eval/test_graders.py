"""Graders G1–G7 and replay (ADR-047 §2.2, §2.3). No model is called."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import deepdive.narrative_eval.graders as graders
from deepdive.narrative_eval.export import CANARY, TEST, TRAIN
from deepdive.narrative_eval.graders import (
    FAIL,
    MEASURED,
    NOT_MEASURED,
    PASS,
    EvalOutput,
    grade,
    replay,
    summary,
)
from deepdive.narrative_output import (
    BearPoint,
    BullPoint,
    NarrativeBody,
    NarrativeOutput,
    NarrativeProvider,
    NumericClaim,
)
from deepdive.scorecard_view import ScorecardView
from frameworks.composite import COMPOSITE_VERSION
from tests.test_narrative_eval.test_export import _view


class _BodyWithContract(NarrativeBody):
    """The ADR-023-A1 fields ADR-045 will add, to show G2 and G5 passing."""

    verdict: str | None = None
    owner_operator_answer: str | None = None
    moat_direction: str | None = None
    triggers: list[str] = []


def _body(*, claim_path: str = "composite.score", codes: list[str] | None = None,
          detail: str = "Composite is 5.0.", cls: type[NarrativeBody] = NarrativeBody,
          **extra: Any) -> NarrativeBody:  # fmt: skip
    claim = NumericClaim(value="5.0", field_path=claim_path)
    point: dict[str, Any] = {"headline": "Steady", "detail": detail, "numeric_claims": [claim]}
    return cls(
        one_liner="A steady business.",
        bull=[BullPoint(**point, framework_codes=["F2"] if codes is None else codes)],
        bear=[
            BearPoint(headline="Thin data", detail="Few frameworks ran.", framework_codes=["F2"])
        ],
        **extra,
    )


def _out(body: NarrativeBody, view: ScorecardView, *, cost: float | None = 0.004,
         latency: int = 2500, model: str = "claude-sonnet-4-6") -> EvalOutput:  # fmt: skip
    narrative = NarrativeOutput(
        ticker=view.ticker, generated_at=datetime(2026, 10, 28),
        provider=NarrativeProvider.ANTHROPIC, model=model, body=body,
    )  # fmt: skip
    sha = hashlib.sha256(view.to_llm_context().encode()).hexdigest()
    return EvalOutput(
        case_id=view.ticker, view_sha256=sha, model=model, prompt_version=1, narrative=narrative,
        input_tokens=12_000, output_tokens=3_800, latency_ms=latency, cost_usd=cost,
    )  # fmt: skip


def _by_id(grades: list[graders.Grade]) -> dict[str, graders.Grade]:
    return {g.grader: g for g in grades}


def test_todays_narrative_shape_passes_g1_g3_and_fails_g2_g5_by_construction() -> None:
    view = _view(verdict="watchlist")
    got = _by_id(grade(view, _out(_body(), view)))
    assert [got[g].status for g in ("G1", "G2", "G3", "G4", "G5")] == [
        PASS, FAIL, PASS, NOT_MEASURED, FAIL,
    ]  # fmt: skip
    assert "ADR-045" in got["G2"].detail and "ADR-046" in got["G4"].detail
    assert got["G5"].detail == "missing verdict, owner_operator_answer, moat_direction, triggers"
    assert (got["G6"].status, got["G6"].value) == (MEASURED, 0.004)
    assert (got["G7"].status, got["G7"].value) == (MEASURED, 2500.0)


def test_g1_runs_the_current_guard() -> None:
    view = _view()
    g1 = _by_id(grade(view, _out(_body(claim_path="composite.nonexistent"), view)))["G1"]
    assert g1.status == FAIL and "does not exist in view" in g1.detail


def test_g2_compares_with_the_mapped_deterministic_verdict() -> None:
    view = _view(verdict="monitor")  # ADR-054: monitor -> WATCHLIST WITH TRIGGERS
    ok = _body(cls=_BodyWithContract, verdict="WATCHLIST WITH TRIGGERS")
    wrong = _body(cls=_BodyWithContract, verdict="EXCLUDE WITH REASON")
    assert _by_id(grade(view, _out(ok, view)))["G2"].status == PASS
    g2 = _by_id(grade(view, _out(wrong, view)))["G2"]
    assert g2.status == FAIL and "WATCHLIST WITH TRIGGERS" in g2.detail


@pytest.mark.parametrize(
    ("kwargs", "problem"),
    [
        ({"codes": [], "claim_path": ""}, "cites missing field"),
        ({"detail": "Revenue grew {{revenue_growth}}."}, "unrendered placeholder"),
        ({"detail": "Margin TBD."}, "unrendered placeholder"),
    ],
)
def test_g3_fails_on_missing_or_unrendered_citations(kwargs: dict[str, Any], problem: str) -> None:
    view = _view()
    g3 = _by_id(grade(view, _out(_body(**kwargs), view)))["G3"]
    assert g3.status == FAIL and problem in g3.detail


def test_g3_needs_a_citation_per_point() -> None:
    view = _view()
    body = _body()
    body.bull[0].framework_codes, body.bull[0].numeric_claims = [], []
    g3 = _by_id(grade(view, _out(body, view)))["G3"]
    assert g3.status == FAIL and "bull[0] cites nothing" in g3.detail


def test_g5_passes_once_the_contract_fields_are_filled() -> None:
    view = _view()
    full = _body(
        cls=_BodyWithContract, verdict="WATCHLIST WITH TRIGGERS",
        owner_operator_answer="not yet", moat_direction="FLAT", triggers=["FCF > 0"],
    )  # fmt: skip
    assert _by_id(grade(view, _out(full, view)))["G5"].status == PASS


def test_g6_is_not_measured_for_an_unpriced_model() -> None:
    view = _view()
    assert _by_id(grade(view, _out(_body(), view, cost=None)))["G6"].status == NOT_MEASURED


# ── Replay ─────────────────────────────────────────────────────────────────


def _case(view: ScorecardView, split: str) -> dict[str, Any]:
    body = view.to_llm_context()
    case = {
        "case_id": view.ticker, "split": split, "schema_version": view.schema_version,
        "composite_version": COMPOSITE_VERSION, "view": json.loads(body),
        "view_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }  # fmt: skip
    return {"canary": CANARY, **case} if split == TEST else case


def _golden(tmp: Path, *outputs: EvalOutput, cases: list[tuple[ScorecardView, str]]) -> Path:
    for view, split in cases:
        (tmp / split).mkdir(parents=True, exist_ok=True)
        (tmp / split / f"{view.ticker}.json").write_text(json.dumps(_case(view, split)))
    for out in outputs:
        d = tmp / "outputs" / out.model / f"v{out.prompt_version}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{out.case_id}.json").write_text(out.model_dump_json())
    return tmp


def test_replay_grades_each_output_against_its_case(tmp_path: Path) -> None:
    a, b = _view("AAA"), _view("BBB", verdict="exclude")
    golden = _golden(tmp_path, _out(_body(), a), _out(_body(), b), cases=[(a, TEST), (b, TRAIN)])
    result = replay(golden)
    assert result.drift == []
    by_case = result.grades[("claude-sonnet-4-6", 1)]
    assert set(by_case) == {"AAA", "BBB"}
    s = summary(by_case, result.splits, TEST)
    assert (s["cases"], s["G1"], s["G2"], s["G4"]) == (1, 1.0, 0.0, None)
    assert (s["cost_per_narrative"], s["latency_p50_ms"]) == (0.004, 2500.0)


def test_replay_reports_drift(tmp_path: Path) -> None:
    a, orphan = _view("AAA"), _view("GONE")
    stale = _out(_body(), a).model_copy(update={"view_sha256": "0" * 64})
    golden = _golden(tmp_path, stale, _out(_body(), orphan), cases=[(a, TRAIN)])
    case = json.loads((golden / TRAIN / "AAA.json").read_text())
    case["composite_version"] = COMPOSITE_VERSION + 1
    (golden / TRAIN / "AAA.json").write_text(json.dumps(case))
    drift = replay(golden).drift
    assert any("composite" in d for d in drift)
    assert any("different view of AAA" in d for d in drift)
    assert any("no case 'GONE'" in d for d in drift)


def test_cli_replay_records_then_holds_grades(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from cli.main import app

    a = _view("AAA")
    golden = _golden(tmp_path, _out(_body(), a), cases=[(a, TEST)])
    args = ["narrative", "eval", "replay", "--golden", str(golden)]
    runner = CliRunner()
    assert runner.invoke(app, args, env={"COLUMNS": "200"}).exit_code == 1  # nothing recorded yet
    recorded = runner.invoke(app, [*args, "--record"], env={"COLUMNS": "200"})
    assert recorded.exit_code == 0, recorded.output
    assert "claude-sonnet-4-6, prompt v1" in recorded.output
    assert runner.invoke(app, args, env={"COLUMNS": "200"}).exit_code == 0
    path = graders.grades_path(golden, "claude-sonnet-4-6", 1)
    grades = json.loads(path.read_text())
    grades["AAA"][0]["status"] = FAIL  # as if a guard change flipped G1
    path.write_text(json.dumps(grades))
    changed = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert changed.exit_code == 1 and "grades differ" in changed.output
