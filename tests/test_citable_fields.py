"""Citable field IDs (ADR-045 §2.1, §2.7 item 2), over the golden set's real train views."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

import deepdive.citable_fields as cf
from deepdive.narrative_eval.export import WITHHELD
from deepdive.scorecard_view import OverlayTriggerView, ScorecardView

ROOT = Path(__file__).resolve().parents[1]
TRAIN = sorted((ROOT / "tests/fixtures/narrative_golden/train").glob("*.json"))


def _train(ticker: str) -> ScorecardView:
    path = ROOT / f"tests/fixtures/narrative_golden/train/{ticker}.json"
    return ScorecardView.from_dict(json.loads(path.read_text("utf-8"))["view"])


@pytest.mark.parametrize("path", TRAIN, ids=lambda p: p.stem)
def test_every_valued_field_gets_one_named_id(path: Path) -> None:
    view = ScorecardView.from_dict(json.loads(path.read_text("utf-8"))["view"])
    fields = view.citable_fields()
    assert 0 < len(fields) <= cf.MAX_FIELDS
    # Names, never list positions: no ID segment is a bare index.
    assert not [i for i in fields if any(s.isdigit() for s in i.split("."))]
    for fw in view.frameworks:
        ids = {i for i in fields if i.startswith(f"{fw.code}.")}
        if fw.is_unfeasible:
            assert ids == set()
            continue
        valued = [label for label, v in fw.key_signals
                  if v not in ("?", "None", "not_disclosed", WITHHELD)]  # fmt: skip
        assert ids == {f"{fw.code}.score"} | {f"{fw.code}.{cf.slug(x)}" for x in valued}


def test_crwd_cites_what_adr_045_found_miscited() -> None:
    f = _train("CRWD").citable_fields()
    # §1: FCF margin was cited to the ROIC path, Rule of 40 to the Fahlenbrach flag.
    assert (f["F5.fcf_margin"].value, f["F5.roic"].value) == ("+29.8%", "-11.6%")
    assert (f["F6.rule_of_40"].value, f["F6.fahlenbrach_signal"].value) == ("48.94", "False")
    assert f["F2.pct_from_52w_high"].unit == "pct"  # a window label is an ID, not prose
    assert f["company.latest_net_income"].value == "-$162.5M"
    assert (f["ICA-1.f5_roic"].value, f["ICA-3.threshold"].value) == ("-11.6%", "2.0x")
    assert f["BEW-3.threshold"].value == "50.0%"  # same key, another trigger's unit


def test_ids_do_not_move_when_lists_reorder() -> None:
    view = _train("CRWD")
    shuffled = copy.deepcopy(view)
    shuffled.frameworks.reverse()
    for fw in shuffled.frameworks:
        fw.key_signals.reverse()
    shuffled.overlay_triggers.reverse()
    assert shuffled.citable_fields() == view.citable_fields()


def test_withheld_and_missing_values_get_no_id() -> None:
    view = _train("AAPL")
    assert view.company.market_cap_usd is None
    ids = view.citable_fields()
    assert "company.market_cap_usd" not in ids
    assert "F4.short_int_current" not in ids  # withheld in the public copy
    assert "F6.nrr_net_revenue_retention" not in ids  # not_disclosed


@pytest.mark.parametrize(
    ("v", "unit", "text"),
    [
        (416161000000.0, "usd", "$416.2B"), (-162_500_000, "usd", "-$162.5M"),
        (950_000, "usd", "$950,000"), (0.333, "fraction", "33.3%"), (0.5, "pct", "0.5%"),
        (50.13, "pp", "50.13pp"), (9.9, "multiple", "9.9x"), (9.0, "score", "9/10"),
        (2025, "year", "2025"), (3.031, "number", "3.031"),
    ],
)  # fmt: skip
def test_render_states_the_unit(v: float, unit: str, text: str) -> None:
    assert cf.render(v, unit) == text


def test_every_number_the_detector_emits_has_a_unit() -> None:
    src = (ROOT / "overlays/detector.py").read_text("utf-8")
    blocks = re.findall(r"relevant_numbers=\{(.*?)\n\s*\}", src, re.S)
    keys = {k for b in blocks for k in re.findall(r'^\s*"([a-z0-9_]+)":', b, re.M)}
    assert len(blocks) >= 10 and "gap_pp" in keys  # the parse still finds the dicts
    descriptive = {
        "addbacks_excluded", "addbacks_included", "adr_reference", "direction",
        "f7_unfeasible_reason", "gp_a_strong", "ipo_date", "listing_type", "methodology",
        "non_gaap_method", "note", "ocf_positive", "same_source", "sector", "source_gaap",
        "source_non_gaap",
    }  # fmt: skip
    assert keys - descriptive - {"threshold"} == set(cf._OVERLAY_UNITS)
    with_threshold = set(re.findall(r'trigger_id="([A-Z]+-\d)"(?:(?!trigger_id=).)*?"threshold":',
                                    src, re.S))  # fmt: skip
    assert with_threshold == set(cf._THRESHOLD_UNITS), with_threshold


def test_the_cap_keeps_the_framework_fields_first() -> None:
    view = _train("AAPL")
    numbers = {f"n{i}": float(i) for i in range(cf.MAX_FIELDS)}
    view.overlay_triggers.append(OverlayTriggerView("ICA", "ICA-9", "", numbers, "F5"))
    fields = view.citable_fields()
    assert len(fields) == cf.MAX_FIELDS and "F6.rule_of_40" in fields
    assert "ICA-9.n79" not in fields


def test_a_repeated_id_is_an_error_not_an_overwrite() -> None:
    view = _train("AAPL")
    view.overlay_triggers.append(copy.deepcopy(view.overlay_triggers[0]))
    with pytest.raises(ValueError, match="share the ID"):
        view.citable_fields()
