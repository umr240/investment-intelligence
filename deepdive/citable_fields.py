"""Stable citable field IDs over a ScorecardView (ADR-045 §2.1, §2.7 item 2).

The narrative cites a field by ID and code renders its value, so the model never
writes a number. IDs are names, never list positions: a framework signal is its
code plus the slug of its label (`F6.rule_of_40`). Deterministic; no LLM.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from deepdive.scorecard_view import ScorecardView

logger = logging.getLogger(__name__)

MAX_FIELDS = 80  # ADR-045 §2.1; the largest of 73 live views had 58 (2026-10-28)

# A field with no value gets no ID (§2.7 item 2). "withheld" is the golden set's
# public-copy marker (`deepdive/narrative_eval/export.py` WITHHELD).
_NO_VALUE = frozenset({"?", "None", "not_disclosed", ""})

_COMPANY_UNITS = {
    "market_cap_usd": ("usd", "Market cap"),
    "latest_revenue": ("usd", "Latest annual revenue"),
    "latest_net_income": ("usd", "Latest annual net income"),
    "latest_fiscal_year": ("year", "Latest fiscal year"),
    "pe_trailing": ("multiple", "Trailing P/E"),
    "pb_ratio": ("multiple", "P/B"),
    "ev_ebitda": ("multiple", "EV/EBITDA"),
    "beta": ("number", "Beta"),
    "ceo_equity_pct": ("pct", "CEO equity"),  # stored in percent (`cli/main.py` renders `{v}%`)
}

# Units of the numbers `overlays/detector.py` puts in `relevant_numbers`; the view
# stores them bare. `threshold` means a different thing per trigger.
_OVERLAY_UNITS = {
    "f5_roic": "fraction", "roic_threshold": "fraction", "rd_intensity": "fraction",
    "rd_threshold": "fraction", "return_12_1": "fraction", "pt_adjusted_roic": "fraction",
    "roic_gaap": "fraction",
    "gap_pp": "pp", "gap_threshold_pp": "pp",
    "gaap_net_income": "usd", "operating_cash_flow": "usd", "market_cap_usd": "usd",
    "ocf_to_loss_ratio": "multiple", "pb_ratio": "multiple", "pb_threshold": "multiple",
    "current_ev_revenue": "multiple",
    "f1_score": "score", "f3_score": "score", "f6_score": "score",
    "ev_revenue_z": "number", "gp_a": "number", "months_since_listing": "number",
    "piotroski": "number",
}  # fmt: skip
_THRESHOLD_UNITS = {"ICA-3": "multiple", "BEW-3": "fraction"}

# Unit of a key signal, read from its formatted value (`_extract_key_signals`).
_SIGNAL_UNITS = (
    (re.compile(r"^[+-]?\d[\d,.]*%"), "pct"),
    (re.compile(r"^[+-]?\d[\d,.]* bps/yr$"), "bps_per_year"),
    (re.compile(r"^\d+ qtrs$"), "quarters"),
    (re.compile(r"^\d+/\d+$"), "out_of"),
    (re.compile(r"^\d[\d,]* \("), "count"),
    (re.compile(r"^[+-]?\d[\d,]*\.?\d*$"), "number"),
    (re.compile(r"^(True|False)$"), "bool"),
)


class CitableField(BaseModel):
    """One citable value: `value` is what a `{id}` placeholder renders to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    unit: str
    label: str


def slug(label: str) -> str:
    """`% from 52w high` -> `pct_from_52w_high`."""
    return re.sub(r"[^a-z0-9]+", "_", label.lower().replace("%", " pct ")).strip("_")


def build_citable_fields(view: ScorecardView) -> dict[str, CitableField]:
    """Every citable value in the view, by ID. Unfeasible frameworks contribute none."""
    out: dict[str, CitableField] = {}

    def add(field_id: str, value: str, unit: str, label: str) -> None:
        if field_id in out:
            raise ValueError(f"{view.ticker}: two citable fields share the ID {field_id}")
        out[field_id] = CitableField(value=value, unit=unit, label=label)

    add("composite.score", render(view.composite.score, "score"), "score", "Composite score")
    feasible = [fw for fw in view.frameworks if not fw.is_unfeasible]
    for fw in feasible:
        add(f"{fw.code}.score", render(fw.score, "score"), "score", f"{fw.code} {fw.title} score")
    for fw in feasible:
        for label, value in fw.key_signals:
            if value in _NO_VALUE or value.startswith("withheld"):
                continue
            add(f"{fw.code}.{slug(label)}", value, _signal_unit(value), label)
    for attr, (unit, label) in _COMPANY_UNITS.items():
        v = getattr(view.company, attr)
        if v is not None:
            add(f"company.{attr}", render(v, unit), unit, label)
    for trigger in view.overlay_triggers:
        for key, v in trigger.relevant_numbers.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            unit = _overlay_unit(trigger.trigger_id, key)
            add(f"{trigger.trigger_id}.{key}", render(v, unit), unit,
                f"{trigger.trigger_id} {key.replace('_', ' ')}")  # fmt: skip
    if len(out) > MAX_FIELDS:
        logger.warning("%s: %d citable fields, keeping the first %d",
                       view.ticker, len(out), MAX_FIELDS)  # fmt: skip
        out = dict(list(out.items())[:MAX_FIELDS])
    return out


def render(v: Any, unit: str) -> str:
    """A bare number as prose shows it, with its unit."""
    x = float(v)
    if unit == "usd":
        sign, a = ("-" if x < 0 else ""), abs(x)
        for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
            if a >= scale:
                return f"{sign}${a / scale:.1f}{suffix}"
        return f"{sign}${a:,.0f}"
    if unit == "fraction":
        return f"{x * 100:.1f}%"
    if unit == "pct":
        return f"{x:g}%"
    if unit == "pp":
        return f"{x:g}pp"
    if unit == "multiple":
        return f"{x:.1f}x"
    if unit == "score":
        return f"{x:g}/10"
    if unit == "year":
        return str(int(x))
    return f"{x:g}"


def _signal_unit(value: str) -> str:
    return next((unit for pattern, unit in _SIGNAL_UNITS if pattern.match(value)), "label")


def _overlay_unit(trigger_id: str, key: str) -> str:
    if key == "threshold":
        return _THRESHOLD_UNITS.get(trigger_id, "number")
    return _OVERLAY_UNITS.get(key, "number")
