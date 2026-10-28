"""COMPOSITE_VERSION moves with the composite formula (ADR-047 §2.7).

Golden-set cases record the version that scored them; an unbumped formula edit
would let replay compare cases scored by different formulas. The formula is
`frameworks/composite.py`, the config constants it imports, and the overlay
bonus: its constants, its function and how it is applied.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json

import config.constants
import deepdive.orchestrator as orchestrator
import frameworks.composite as composite
from frameworks.composite import COMPOSITE_VERSION

RECORDED = {1: "70dcd62fac29b2115c199ebe45b89019659a4272b78ba9c2b97a78a5804764be"}
_BONUS_CONSTANTS = (
    "ICA_BONUS_PER_VERDICT_BAND", "ICA_MAX_BONUS", "PSA_BONUS_STRONG", "PSA_BONUS_MODERATE",
    "BEW_BONUS_EXTREME", "BEW_BONUS_MODERATE", "TOTAL_OVERLAY_BONUS_CAP", "_VERDICT_RANK",
)  # fmt: skip


def _imported_constants() -> list[str]:
    tree = ast.parse(inspect.getsource(composite))
    return sorted(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "config.constants"
        for alias in node.names
    )


def _formula_sha() -> str:
    values = {
        **{n: getattr(config.constants, n) for n in _imported_constants()},
        **{n: getattr(orchestrator, n) for n in _BONUS_CONSTANTS},
    }
    source = "\n".join(
        [
            inspect.getsource(composite),
            inspect.getsource(orchestrator._compute_overlay_composite_bonus),
            inspect.getsource(orchestrator._apply_overlay_bonus),
            json.dumps(values, sort_keys=True, default=str),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_composite_formula_matches_its_version() -> None:
    assert RECORDED.get(COMPOSITE_VERSION) == _formula_sha(), (
        "the composite formula changed (frameworks/composite.py, its config constants, or the "
        "overlay bonus): if scores can differ, bump COMPOSITE_VERSION and COMPOSITE_SINCE and "
        f"re-export the golden set; either way, record {COMPOSITE_VERSION}: '{_formula_sha()}'"
    )


def test_the_pin_covers_the_weights_and_the_bonus() -> None:
    assert {"WEIGHTS_B", "WEIGHTS_C", "VERDICT_WATCHLIST"} <= set(_imported_constants())
    assert "PSA_BONUS_STRONG" in _BONUS_CONSTANTS
