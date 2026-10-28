"""The committed golden set replays (ADR-047 §2.3 replay gate, §2.7 item 1).

CI calls no model: it re-checks every committed case and re-grades every stored
output. A schema, composite, guard or grader change that alters either fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

from deepdive.narrative_eval.export import CANARY, TEST, TRAIN
from deepdive.narrative_eval.graders import grades_path, replay, serialise

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "narrative_golden"
MIN_CASES = 30  # ADR-047 §2.1: 30-50 cases


def test_the_golden_set_is_committed_and_large_enough() -> None:
    cases = [p for split in (TRAIN, TEST) for p in (GOLDEN / split).glob("*.json")]
    assert len(cases) >= MIN_CASES, f"{len(cases)} cases under {GOLDEN}; run the export (S2)"


def test_every_case_and_output_still_replays() -> None:
    assert replay(GOLDEN).drift == []


def test_only_test_cases_carry_the_canary() -> None:
    for split in (TRAIN, TEST):
        for path in (GOLDEN / split).glob("*.json"):
            has = json.loads(path.read_text("utf-8")).get("canary") == CANARY
            assert has == (split == TEST), path.name


def test_stored_outputs_regrade_to_their_recorded_grades() -> None:
    result = replay(GOLDEN)
    for (model, version), by_case in result.grades.items():
        path = grades_path(GOLDEN, model, version)
        assert path.exists(), f"no {path}: run `invest narrative eval replay --record`"
        assert json.loads(path.read_text("utf-8")) == serialise(by_case), (
            f"grades changed for {model} v{version}: re-baseline with --record if intended"
        )
