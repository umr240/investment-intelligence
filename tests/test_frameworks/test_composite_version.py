"""COMPOSITE_VERSION moves with the composite formula (ADR-047 §2.7).

Golden-set cases record the version that scored them; an unbumped formula edit
would let replay compare cases scored by different formulas.
"""

from __future__ import annotations

import hashlib
import inspect

import frameworks.composite as composite
from deepdive.orchestrator import _compute_overlay_composite_bonus
from frameworks.composite import COMPOSITE_VERSION

RECORDED = {1: "6ba2c5efcd9df07df37916c0354dbefe772cfa23031e7c9fd50ac4c2e410768a"}


def _formula_sha() -> str:
    source = inspect.getsource(composite) + inspect.getsource(_compute_overlay_composite_bonus)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_composite_formula_matches_its_version() -> None:
    assert RECORDED.get(COMPOSITE_VERSION) == _formula_sha(), (
        "frameworks/composite.py or the overlay bonus changed: if the formula changed, bump "
        "COMPOSITE_VERSION and COMPOSITE_SINCE and re-export the golden set; either way, "
        f"record {COMPOSITE_VERSION}: '{_formula_sha()}' here"
    )
