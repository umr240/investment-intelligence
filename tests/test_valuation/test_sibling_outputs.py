"""ADR-029 sibling outputs — reverse-DCF tier gate regression.

Pins the defect found on 2026-08-16: ADR-030 (2026-05-14) re-stamped
``IVResult.tier`` with maturity sub-labels (``A_mature`` / ``A_young`` /
``B_mature`` / ``B_young`` / ``A_cyclical`` / ``B_cyclical``), but the
reverse-DCF gate in ``_attach_sibling_outputs`` still matched the pre-ADR-030
labels ``("A_gaap", "B_pt_rescued")``.

Consequence: for every ticker that received a maturity classification — i.e.
every ticker — the gate was False, ``reverse_solve_growth`` was never called,
and ``reverse_implied_growth_rate`` stayed None. It was invisible for three
months because (a) None is a legal value for that field, and (b) the enclosing
block swallowed all exceptions with a bare ``except: pass``.

These tests assert the GATE, not the arithmetic — the arithmetic lives in
test_intrinsic.py. A future tier rename must fail here loudly.
"""
from __future__ import annotations

import pytest

# The gate is a pure predicate over the tier string; test it directly so the
# test needs no DB, no network and no macro reference files.
TIER_LABELS_THAT_MUST_SOLVE = [
    "A_gaap",         # pre-ADR-030 (still valid when maturity is None)
    "B_pt_rescued",   # pre-ADR-030
    "A_mature",       # ADR-030
    "A_young",
    "B_mature",
    "B_young",
    "A_cyclical",
    "B_cyclical",
]

TIER_LABELS_THAT_MUST_NOT_SOLVE = [
    "C_insufficient",    # no positive NOPAT base
    "C_growth_invalid",  # no growth lever
    "C_yc_resolved",     # scenario path owns its own projection
]


def _gate(tier: str) -> bool:
    """Mirror of the production predicate in intrinsic._attach_sibling_outputs."""
    return str(tier).split("_", 1)[0] in ("A", "B")


@pytest.mark.parametrize("tier", TIER_LABELS_THAT_MUST_SOLVE)
def test_reverse_dcf_gate_accepts_every_ab_tier_label(tier: str) -> None:
    assert _gate(tier) is True, (
        f"tier {tier!r} must reach the reverse-DCF solver. If a tier rename "
        f"broke this, market-implied growth silently becomes None for every "
        f"ticker — the exact ADR-030 regression this test exists to catch."
    )


@pytest.mark.parametrize("tier", TIER_LABELS_THAT_MUST_NOT_SOLVE)
def test_reverse_dcf_gate_rejects_c_tiers(tier: str) -> None:
    assert _gate(tier) is False


def test_production_gate_matches_this_mirror() -> None:
    """Guard against the mirror drifting from the implementation.

    Reads the real source line so a change to the production predicate that
    is not reflected here fails rather than silently passing a stale mirror.
    """
    from pathlib import Path
    src = Path("valuation/damodaran/intrinsic.py").read_text(encoding="utf-8")
    assert 'tier_family_ok = str(primary.tier).split("_", 1)[0] in ("A", "B")' in src, (
        "reverse-DCF tier gate changed in intrinsic.py — update the mirror in "
        "this test and re-verify every label above."
    )


def test_no_bare_except_pass_around_reverse_dcf() -> None:
    """CLAUDE.md: no silent failures. A failed solve must become a data gap.

    The original defect was doubly hidden by `except Exception: pass`. If that
    pattern returns anywhere in the sibling-output block, the next regression
    will be just as invisible as this one was.
    """
    from pathlib import Path
    src = Path("valuation/damodaran/intrinsic.py").read_text(encoding="utf-8")
    start = src.index("def _attach_sibling_outputs")
    block = src[start:start + 6000]
    import re
    # Any `except ...:` whose entire body is a bare `pass` — whitespace-agnostic,
    # so reformatting cannot quietly reintroduce the swallow.
    assert not re.search(r"except\s+Exception[^\n]*:\s*(#[^\n]*)?\n\s*pass\b", block)
    assert "reverse DCF unsolved" in block, (
        "a failed reverse-DCF solve must append a data gap naming the failure"
    )
