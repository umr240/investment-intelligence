"""Deterministic graders G1–G7 and replay (ADR-047 §2.2, §2.3).

Grading reads a golden-set case and one stored model output; nothing here calls
a model. A grade is `pass`, `fail`, `not_measured` (the grader's input does not
exist yet) or `measured` (G6/G7 report a number, not a verdict).
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from config.llm_prices import cost_usd
from config.verdicts import narrative_verdict
from deepdive.narrative_eval.export import TEST, TRAIN, replay_mismatch
from deepdive.narrative_guard import _walk_path, validate
from deepdive.narrative_output import BearPoint, BullPoint, NarrativeOutput
from deepdive.scorecard_view import ScorecardView

PASS, FAIL, NOT_MEASURED, MEASURED = "pass", "fail", "not_measured", "measured"
VERDICT_GRADERS = ("G1", "G2", "G3", "G4", "G5")
CITATION_FLOOR = 1  # framework codes plus numeric claims per bull/bear point; set after baseline
# ADR-023-A1 row 2: the fields added to bull/bear/risks/data_caveats (ADR-045 builds them).
REQUIRED_FIELDS = ("verdict", "owner_operator_answer", "moat_direction", "triggers")
_PLACEHOLDER = re.compile(
    r"\{\{.*?\}\}|\{[\w.]+\}|\[\[|\]\]|\[[A-Z_]{3,}\]|<[A-Z_]{3,}>|(?i:\bTODO\b|\bTBD\b)"
)
GRADES_FILE = "grades.json"


class EvalOutput(BaseModel):
    """One live run's output for one case, as `invest narrative eval run` stores it."""

    case_id: str
    view_sha256: str  # the case's public view the model was given
    model: str
    prompt_version: int
    narrative: NarrativeOutput
    input_tokens: int  # uncached
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int
    lattice_deferred: list[str] = []  # models the composer dropped for budget (§2.7 item 4)


@dataclass(frozen=True)
class Grade:
    grader: str
    status: str
    detail: str = ""
    value: float | None = None


def _texts(out: NarrativeOutput) -> list[str]:
    b = out.body
    texts = [b.one_liner, *b.data_caveats]
    points: list[BullPoint | BearPoint] = [*b.bull, *b.bear]
    texts += [t for p in points for t in (p.headline, p.detail)]
    texts += [r.factor for r in b.risks]
    return texts


def grade(view: ScorecardView, out: EvalOutput) -> list[Grade]:
    body = out.narrative.body
    warnings = validate(body, view)
    g1 = Grade("G1", PASS) if not warnings else Grade("G1", FAIL, f"{len(warnings)}: {warnings[0]}")

    expected = narrative_verdict(view.composite.verdict)
    given = getattr(body, "verdict", None)
    if given is None:
        g2 = Grade("G2", FAIL, "no verdict field (ADR-045 adds it)")
    elif given != expected:
        g2 = Grade("G2", FAIL, f"{given!r}, expected {expected!r}")
    else:
        g2 = Grade("G2", PASS)

    view_dict = view.to_dict()
    problems = []
    sections: tuple[tuple[str, Sequence[BullPoint | BearPoint]], ...] = (
        ("bull", body.bull),
        ("bear", body.bear),
    )
    for section, points in sections:
        for i, p in enumerate(points):
            if len(p.framework_codes) + len(p.numeric_claims) < CITATION_FLOOR:
                problems.append(f"{section}[{i}] cites nothing")
            problems += [
                f"{section}[{i}] cites missing field {c.field_path!r}"
                for c in p.numeric_claims
                if _walk_path(view_dict, c.field_path) is None
            ]
    problems += [
        f"unrendered placeholder in {t[:40]!r}"
        for t in _texts(out.narrative)
        if _PLACEHOLDER.search(t)
    ]
    g3 = Grade("G3", FAIL, f"{len(problems)}: {problems[0]}") if problems else Grade("G3", PASS)

    g4 = Grade("G4", NOT_MEASURED, "claim lint not built (ADR-046)")

    missing = [f for f in REQUIRED_FIELDS if getattr(body, f, None) in (None, "", [])]
    g5 = Grade("G5", FAIL, f"missing {', '.join(missing)}") if missing else Grade("G5", PASS)

    cost = cost_usd(
        out.model,
        out.input_tokens,
        out.output_tokens,
        out.cache_read_tokens,
        out.cache_write_tokens,
    )
    tokens = (
        f"{out.input_tokens} in, {out.output_tokens} out, "
        f"{out.cache_read_tokens} cache read, {out.cache_write_tokens} cache write"
    )
    stored = out.narrative.cost_usd
    if cost is not None and stored is not None and abs(stored - cost) > 1e-6:
        tokens += f"; narrative recorded ${stored:.6f}"
    g6 = Grade("G6", MEASURED if cost is not None else NOT_MEASURED, tokens, cost)
    g7 = Grade("G7", MEASURED, "", float(out.latency_ms))
    return [g1, g2, g3, g4, g5, g6, g7]


@dataclass
class Replay:
    """Cases and stored outputs that can no longer be graded as-is, and the grades of the rest."""

    drift: list[str]
    grades: dict[
        tuple[str, int], dict[str, list[Grade]]
    ]  # (model, prompt_version) -> case -> grades
    splits: dict[str, str]  # case_id -> train | test


def load_cases(golden: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    cases, drift = {}, []
    for split in (TRAIN, TEST):
        for path in sorted((golden / split).glob("*.json")):
            case = json.loads(path.read_text("utf-8"))
            why = replay_mismatch(case)
            if why:
                drift.append(f"{split}/{path.name}: {why}")
            cases[case["case_id"]] = case
    return cases, drift


def replay(golden: Path) -> Replay:
    """Re-grade every stored output against its case (ADR-047 §2.3 replay mode)."""
    cases, drift = load_cases(golden)
    grades: dict[tuple[str, int], dict[str, list[Grade]]] = defaultdict(dict)
    for path in sorted((golden / "outputs").glob("*/*/*.json")):
        if path.name == GRADES_FILE:
            continue
        out = EvalOutput.model_validate_json(path.read_text("utf-8"))
        case = cases.get(out.case_id)
        key = (out.model, out.prompt_version)
        if (path.parent.parent.name, path.parent.name) != (out.model, f"v{out.prompt_version}"):
            drift.append(f"{path}: says {out.model} v{out.prompt_version}")
        elif out.case_id in grades[key]:
            drift.append(f"{path}: a second output for {out.case_id}")
        elif case is None:
            drift.append(f"{path}: no case {out.case_id!r}")
        elif case["view_sha256"] != out.view_sha256:
            drift.append(f"{path}: graded a different view of {out.case_id}")
        else:
            view = ScorecardView.from_dict(case["view"])
            grades[(out.model, out.prompt_version)][out.case_id] = grade(view, out)
    for path in sorted((golden / "outputs").glob(f"*/*/{GRADES_FILE}")):
        model, version = path.parent.parent.name, path.parent.name.removeprefix("v")
        if not version.isdigit() or (model, int(version)) not in grades:
            drift.append(f"{path}: no outputs left to grade")
    return Replay(drift, dict(grades), {c: case["split"] for c, case in cases.items()})


def grades_path(golden: Path, model: str, prompt_version: int) -> Path:
    return golden / "outputs" / model / f"v{prompt_version}" / GRADES_FILE


def serialise(by_case: dict[str, list[Grade]]) -> dict[str, list[dict[str, Any]]]:
    return {case: [asdict(g) for g in gs] for case, gs in sorted(by_case.items())}


def summary(by_case: dict[str, list[Grade]], splits: dict[str, str], split: str) -> dict[str, Any]:
    """Pass rates per grader, cost per narrative and latency percentiles for one split."""
    rows = [gs for case, gs in by_case.items() if splits.get(case) == split]
    out: dict[str, Any] = {"cases": len(rows)}
    for grader in VERDICT_GRADERS:
        graded = [g for gs in rows for g in gs if g.grader == grader and g.status in (PASS, FAIL)]
        out[grader] = sum(g.status == PASS for g in graded) / len(graded) if graded else None
    costs = [g.value for gs in rows for g in gs if g.grader == "G6" and g.value is not None]
    latency = sorted(g.value for gs in rows for g in gs if g.grader == "G7" and g.value is not None)
    out["cost_per_narrative"] = statistics.fmean(costs) if costs else None
    out["latency_p50_ms"] = statistics.median(latency) if latency else None
    # Nearest rank: the smallest value with at least 95% of the latencies at or below it.
    out["latency_p95_ms"] = latency[math.ceil(0.95 * len(latency)) - 1] if latency else None
    return out
