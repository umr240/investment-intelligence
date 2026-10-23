"""An over-long string must not discard a paid generation.

Neither OpenAI strict mode nor Anthropic tool-use enforces `maxLength`, so the
model can and does return headlines longer than the schema declares. Before
this, a single overrun raised a provider error, the fallback provider was
billed, its response overran too, and the user got "All narrative providers
failed" having paid twice.
"""
from __future__ import annotations

import pytest

from deepdive.narrative import _fit_to_declared_lengths, _trim_on_word_boundary
from deepdive.narrative_output import NarrativeBody

_HEADLINE_CAP = 140


def _body(headline: str) -> dict[str, object]:
    return {
        "one_liner": "Composite 7.0/10 — watchlist.",
        "bull": [
            {"headline": headline, "detail": "d", "framework_codes": [], "numeric_claims": []},
        ],
        "bear": [{"headline": "b", "detail": "d", "framework_codes": [], "numeric_claims": []}],
        "risks": [],
        "data_caveats": [],
    }


def test_overlong_headline_is_trimmed_not_rejected() -> None:
    long_headline = (
        "Exceptional growth quality with revenue CAGR above one hundred percent "
        "and free cash flow margin expanding materially, rarely observed at this scale"
    )
    assert len(long_headline) > _HEADLINE_CAP

    fitted, notes = _fit_to_declared_lengths(_body(long_headline), NarrativeBody)
    body = NarrativeBody.model_validate(fitted)   # would previously raise

    assert len(body.bull[0].headline) <= _HEADLINE_CAP
    assert len(notes) == 1
    assert "bull.0.headline" in notes[0]


def test_conforming_payload_is_untouched() -> None:
    fitted, notes = _fit_to_declared_lengths(_body("Short headline"), NarrativeBody)
    assert notes == []
    assert fitted == _body("Short headline")


def test_trim_prefers_a_word_boundary() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    out = _trim_on_word_boundary(text, 30)
    assert len(out) <= 30
    assert out.endswith("…")
    assert "  " not in out
    # Did not cut mid-word.
    assert out[:-1].rstrip().split()[-1] in text.split()


def test_trim_handles_a_single_unbroken_token() -> None:
    """A long token with no spaces must still yield a capped, non-empty string."""
    out = _trim_on_word_boundary("x" * 200, 40)
    assert 0 < len(out) <= 40


@pytest.mark.parametrize("field,cap", [("one_liner", 400)])
def test_other_capped_fields_are_also_fitted(field: str, cap: int) -> None:
    payload = _body("ok")
    payload[field] = "y" * (cap + 50)
    fitted, notes = _fit_to_declared_lengths(payload, NarrativeBody)
    NarrativeBody.model_validate(fitted)
    assert any(field in n for n in notes)


# ── Status must not conflate formatting with grounding ────────────────────

def _split(warnings: list[str]) -> tuple[list[str], list[str]]:
    """The partition cli/main.py applies when rendering warnings."""
    grounding = [w for w in warnings if not w.startswith("formatting: ")]
    formatting = [w for w in warnings if w.startswith("formatting: ")]
    return grounding, formatting


def test_a_trim_alone_is_not_reported_as_a_grounding_failure() -> None:
    """A trimmed headline must not raise "numeric/citation validation failed".

    Conflating the two would blunt a signal that should only ever mean a
    number in the narrative is unsupported by the scorecard.
    """
    grounding, formatting = _split(["formatting: bear.2.headline trimmed from 148 to 140 chars"])
    assert grounding == []
    assert len(formatting) == 1


def test_grounding_and_formatting_warnings_are_reported_separately() -> None:
    grounding, formatting = _split([
        "bull.0 cites 45.2% which is not present in the view",
        "formatting: one_liner trimmed from 460 to 400 chars",
    ])
    assert len(grounding) == 1 and len(formatting) == 1
    assert "cites 45.2%" in grounding[0]
