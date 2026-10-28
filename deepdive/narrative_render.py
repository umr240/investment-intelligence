"""Fill a v2 narrative's `{field_id}` placeholders from the view (ADR-045 §2.2).

Deterministic; no LLM. An unknown ID stays as written, so the guard reports it
and the text never shows a number the view does not hold.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from deepdive.citable_fields import CitableField
from deepdive.narrative_output import NarrativeBodyV2

PLACEHOLDER = re.compile(r"\{([A-Za-z0-9][\w.-]*)\}")


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER.findall(text)


def render_text(text: str, fields: dict[str, CitableField]) -> str:
    return PLACEHOLDER.sub(lambda m: fields[m[1]].value if m[1] in fields else m[0], text)


def prose(body: NarrativeBodyV2) -> Iterator[tuple[str, str]]:
    """(path, text) for every free-text field the model wrote."""
    yield "one_liner", body.one_liner
    yield "verdict_reason", body.verdict_reason
    for section, points in (("bull", body.bull), ("bear", body.bear)):
        for i, p in enumerate(points):
            yield f"{section}[{i}].headline", p.headline
            yield f"{section}[{i}].detail", p.detail
    for i, r in enumerate(body.risks):
        yield f"risks[{i}].factor", r.factor
    for i, t in enumerate(body.triggers):
        yield f"triggers[{i}].condition", t.condition
    for i, c in enumerate(body.data_caveats):
        yield f"data_caveats[{i}]", c


def render_body(body: NarrativeBodyV2, fields: dict[str, CitableField]) -> NarrativeBodyV2:
    """The body with every known placeholder replaced by its rendered value."""

    def r(text: str) -> str:
        return render_text(text, fields)

    return body.model_copy(
        update={
            "one_liner": r(body.one_liner),
            "verdict_reason": r(body.verdict_reason),
            "bull": [p.model_copy(update={"headline": r(p.headline), "detail": r(p.detail)})
                     for p in body.bull],
            "bear": [p.model_copy(update={"headline": r(p.headline), "detail": r(p.detail)})
                     for p in body.bear],
            "risks": [x.model_copy(update={"factor": r(x.factor)}) for x in body.risks],
            "triggers": [t.model_copy(update={"condition": r(t.condition)}) for t in body.triggers],
            "data_caveats": [r(c) for c in body.data_caveats],
        }
    )  # fmt: skip
