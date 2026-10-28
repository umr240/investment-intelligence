"""Narrative schema v2 (ADR-045 §2.2, §2.3): the model cites IDs, code renders the numbers.

Run against the golden set's real CRWD train view; no model is called.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config.verdicts import NARRATIVE_VERDICTS
from deepdive.narrative_guard import validate
from deepdive.narrative_output import (
    SCHEMA_V2,
    NarrativeBody,
    NarrativeBodyV2,
    NarrativeOutput,
    NarrativeProvider,
    NarrativeVerdict,
    narrative_json_schema_v2,
)
from deepdive.narrative_render import placeholders, render_body, render_text
from deepdive.scorecard_view import ScorecardView

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def crwd() -> ScorecardView:
    path = ROOT / "tests/fixtures/narrative_golden/train/CRWD.json"
    return ScorecardView.from_dict(json.loads(path.read_text("utf-8"))["view"])


def _point(headline: str, detail: str, codes: list[str], ids: list[str]) -> dict[str, Any]:
    return {"headline": headline, "detail": detail, "framework_codes": codes,
            "numeric_claims": [{"field_id": i} for i in ids]}  # fmt: skip


def _body(**over: Any) -> NarrativeBodyV2:
    """A clean v2 body for CRWD (composite watchlist)."""
    return NarrativeBodyV2.model_validate({
        "one_liner": "Fast growth at {F5.revenue_cagr_3y} with GAAP returns still negative.",
        "verdict": "WATCHLIST WITH TRIGGERS",
        "verdict_reason": "A composite of {composite.score} is a watchlist score.",
        "owner_operator_answer": "NOT_YET",
        "moat_direction": "UNKNOWN",
        "bull": [_point("Cash generation is strong",
                        "FCF margin is {F5.fcf_margin} and Rule of 40 is {F6.rule_of_40}.",
                        ["F5", "F6"], ["F5.fcf_margin", "F6.rule_of_40"])],
        "bear": [_point("Returns on capital are negative", "ROIC is {F5.roic}.", ["F5"],
                        ["F5.roic"])],
        "risks": [{"factor": "Losses persist: net income {company.latest_net_income}.",
                   "severity": "medium", "grounded_in": "company.latest_net_income"}],
        "triggers": [{"field_id": "F5.roic", "condition": "turns positive and stays above 10%"}],
        "data_caveats": ["Short interest is withheld from the public copy."],
        **over,
    })  # fmt: skip


# ── Schema ─────────────────────────────────────────────────────────────────


def test_the_verdict_enum_is_the_adr_054_vocabulary() -> None:
    assert {v.value for v in NarrativeVerdict} == set(NARRATIVE_VERDICTS.values())


def test_the_output_parses_its_body_by_schema_version() -> None:
    v2 = NarrativeOutput(ticker="CRWD", generated_at=datetime(2026, 10, 28),
                         provider=NarrativeProvider.OPENAI, model="m", schema_version=SCHEMA_V2,
                         body=_body())  # fmt: skip
    back = NarrativeOutput.model_validate_json(v2.model_dump_json())
    assert isinstance(back.body, NarrativeBodyV2) and back == v2
    v1 = json.loads(back.model_dump_json())
    v1.update(schema_version="1.0", body={"one_liner": "x", "bull": [], "bear": []})
    with pytest.raises(ValueError):  # a v1 body must have bull/bear points: parsed as v1
        NarrativeOutput.model_validate(v1)
    with pytest.raises(ValueError, match="does not match schema_version"):
        NarrativeOutput(ticker="CRWD", generated_at=datetime(2026, 10, 28),
                        provider=NarrativeProvider.OPENAI, model="m", body=_body())  # fmt: skip


def test_the_request_schema_names_this_views_ids_and_no_rejected_keyword(
    crwd: ScorecardView,
) -> None:
    ids = list(crwd.citable_fields())
    schema = narrative_json_schema_v2(ids)
    text = json.dumps(schema)
    for kw in ("minLength", "maxLength", "minimum", "maximum", "maxItems"):
        assert f'"{kw}"' not in text, kw
    for name in ("FieldCitation", "Trigger"):
        assert schema["$defs"][name]["properties"]["field_id"]["enum"] == ids
    assert schema["properties"]["bull"]["minItems"] == 1  # Anthropic accepts 0 or 1


# ── Rendering ──────────────────────────────────────────────────────────────


def test_render_fills_known_ids_and_leaves_unknown_ones(crwd: ScorecardView) -> None:
    fields = crwd.citable_fields()
    text = "ROIC {F5.roic}, gap {ICA-3.ocf_to_loss_ratio}, made up {F5.moat}."
    assert placeholders(text) == ["F5.roic", "ICA-3.ocf_to_loss_ratio", "F5.moat"]
    assert render_text(text, fields) == "ROIC -11.6%, gap 9.9x, made up {F5.moat}."
    rendered = render_body(_body(), fields)
    assert rendered.bull[0].detail == "FCF margin is +29.8% and Rule of 40 is 48.94."
    assert rendered.risks[0].factor == "Losses persist: net income -$162.5M."
    assert rendered.bull[0].numeric_claims[0].field_id == "F5.fcf_margin"  # IDs stay IDs


# ── Guard ──────────────────────────────────────────────────────────────────


def test_a_clean_v2_body_passes_the_guard(crwd: ScorecardView) -> None:
    assert crwd.composite.verdict == "watchlist"
    assert validate(_body(), crwd) == []


@pytest.mark.parametrize(
    ("over", "warning"),
    [
        ({"one_liner": "Margins at {F5.gross_margin}."}, "'{F5.gross_margin}' is not a citable"),
        ({"one_liner": "Margins at {{F5.roic}}."}, "unrendered placeholder or stray brace"),
        ({"verdict_reason": "Revenue tripled to $77.7B."}, "literal number '77.7b'"),
        ({"bull": [_point("h", "NRR is above 120%.", ["F6"], [])]}, "literal number '120%'"),
        ({"bull": [_point("h", "d", ["F6"], ["F6.nrr"])]}, "'F6.nrr' is not a citable field"),
        ({"bull": [_point("h", "d", ["F7"], [])]}, "'F7' is unfeasible"),
        ({"verdict": "EXCLUDE WITH REASON"}, "maps to 'WATCHLIST WITH TRIGGERS'"),
        ({"triggers": []}, "triggers: empty"),
        ({"risks": [{"factor": "Revenue fell 47% in 2024.", "severity": "high",
                     "grounded_in": "F5"}]}, "risks[0].factor: literal number '47%'"),
        ({"data_caveats": ["Short interest of 12.5% is withheld."]},
         "data_caveats[0]: literal number '12.5%'"),
        ({"triggers": [{"field_id": "F5.moat", "condition": "c"}]}, "triggers[0]: 'F5.moat'"),
        ({"risks": [{"factor": "f", "severity": "low", "grounded_in": "vibes"}]},
         "grounded_in='vibes'"),
        ({"data_caveats": []}, "caveats elided"),
    ],
)  # fmt: skip
def test_the_v2_guard_names_each_fault(
    crwd: ScorecardView, over: dict[str, Any], warning: str
) -> None:
    warnings = validate(_body(**over), crwd)
    assert any(warning in w for w in warnings), warnings


def test_only_a_trigger_condition_may_propose_a_threshold(crwd: ScorecardView) -> None:
    body = _body()
    assert body.triggers[0].condition == "turns positive and stays above 10%"
    assert validate(body, crwd) == []
    for verdict in ("EXCLUDE WITH REASON", "RESEARCH-ONLY"):  # every verdict names its triggers
        view = copy.deepcopy(crwd)
        view.composite.verdict = "exclude" if verdict.startswith("EXCLUDE") else "research_only"
        assert validate(_body(verdict=verdict), view) == []
        assert validate(_body(verdict=verdict, triggers=[]), view) == [
            "triggers: empty; name what would change the verdict"
        ]


def test_a_rendered_copy_must_be_the_body_with_its_text_filled_in(crwd: ScorecardView) -> None:
    body = _body()
    other = render_body(_body(moat_direction="WIDENING"), crwd.citable_fields())
    with pytest.raises(ValueError, match="rendered differs from body"):
        NarrativeOutput(ticker="CRWD", generated_at=datetime(2026, 10, 28),
                        provider=NarrativeProvider.OPENAI, model="m", schema_version=SCHEMA_V2,
                        body=body, rendered=other)  # fmt: skip


def test_the_cli_refuses_to_print_an_unrendered_v2_narrative(
    crwd: ScorecardView, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cli.main as cli
    import deepdive.narrative as narrative

    unrendered = _narrative(crwd, rendered=False)
    monkeypatch.setattr(narrative, "generate_narrative", lambda _v, provider_pref=None: unrendered)
    monkeypatch.setattr(narrative, "persist_narrative", lambda _n: True)
    with pytest.raises(ValueError, match="must be rendered"):
        cli._render_narrative(crwd, None)


def test_a_v1_body_still_gets_the_v1_guard(crwd: ScorecardView) -> None:
    v1 = NarrativeBody.model_validate({
        "one_liner": "x", "data_caveats": ["gaps"],
        "bull": [{"headline": "h", "detail": "d", "framework_codes": ["F5"],
                  "numeric_claims": [{"value": "-11.6%",
                                      "field_path": "frameworks.4.key_signals.2.1"}]}],
        "bear": [{"headline": "h", "detail": "d", "framework_codes": ["F5"]}],
    })  # fmt: skip
    assert validate(v1, crwd) == []


# ── Persistence and the API ────────────────────────────────────────────────


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    from data.models.schema import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)  # fmt: skip
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
    monkeypatch.setattr("data.dive_staleness.get_session", session)
    monkeypatch.setattr("data.dive_staleness.dive_withheld_reason", lambda _run: None)
    yield factory
    engine.dispose()


def _narrative(view: ScorecardView, *, rendered: bool = True) -> NarrativeOutput:
    body = _body()
    return NarrativeOutput(
        ticker="CRWD", generated_at=datetime(2026, 10, 28), provider=NarrativeProvider.OPENAI,
        model="gpt-4o-mini", schema_version=SCHEMA_V2, body=body,
        rendered=render_body(body, view.citable_fields()) if rendered else None,
    )  # fmt: skip


def test_a_v2_narrative_is_stored_rendered_with_its_template(
    db: sessionmaker[Session], crwd: ScorecardView, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from api.app import app
    from data.models.schema import Company, DeepDiveRun
    from deepdive.narrative import persist_narrative, shown_sections

    with pytest.raises(ValueError, match="must be rendered"):
        shown_sections(_narrative(crwd, rendered=False))
    with db() as s:
        co = Company(ticker="CRWD", name="CrowdStrike", exchange="NASDAQ")
        s.add(co)
        s.flush()
        s.add(DeepDiveRun(company_id=co.id, ticker="CRWD", mode="default"))
        s.commit()
    assert persist_narrative(_narrative(crwd))
    with db() as s:
        run = s.execute(select(DeepDiveRun)).scalars().one()
        bull, risk = json.loads(str(run.bull_narrative)), json.loads(str(run.risk_factors))
    assert bull[0]["detail"] == "FCF margin is +29.8% and Rule of 40 is 48.94."
    assert risk["_template"]["bull"][0]["detail"].endswith("{F6.rule_of_40}.")
    assert (risk["schema_version"], risk["verdict"]) == (SCHEMA_V2, "WATCHLIST WITH TRIGGERS")

    got = TestClient(app).get("/dive/CRWD/narrative").json()
    assert got["generated"] and got["verdict"] == "WATCHLIST WITH TRIGGERS"
    assert got["triggers"] == [{"field_id": "F5.roic",
                                "condition": "turns positive and stays above 10%"}]  # fmt: skip
    assert got["risks"][0]["factor"] == "Losses persist: net income -$162.5M."
    assert "_template" not in got and got["bull"][0]["numeric_claims"]


def test_a_v1_narrative_is_stored_as_before(db: sessionmaker[Session], crwd: ScorecardView) -> None:
    from data.models.schema import Company, DeepDiveRun
    from deepdive.narrative import persist_narrative

    with db() as s:
        co = Company(ticker="CRWD", name="CrowdStrike", exchange="NASDAQ")
        s.add(co)
        s.flush()
        s.add(DeepDiveRun(company_id=co.id, ticker="CRWD", mode="default"))
        s.commit()
    body = NarrativeBody.model_validate({
        "one_liner": "x", "bull": [{"headline": "h", "detail": "d"}],
        "bear": [{"headline": "h", "detail": "d"}],
    })  # fmt: skip
    persist_narrative(NarrativeOutput(ticker="CRWD", generated_at=datetime(2026, 10, 28),
                                      provider=NarrativeProvider.OPENAI, model="m",
                                      body=body))  # fmt: skip
    with db() as s:
        run = s.execute(select(DeepDiveRun)).scalars().one()
        risk = json.loads(str(run.risk_factors))
    stored = {"headline": "h", "detail": "d", "framework_codes": [], "numeric_claims": []}
    assert json.loads(str(run.bull_narrative)) == [stored]
    assert list(risk) == ["one_liner", "risks", "data_caveats", "_audit"]
