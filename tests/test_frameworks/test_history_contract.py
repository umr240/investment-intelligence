"""A framework must not declare less history than it enforces.

The orchestrator's pre-flight gate reads DATA_REQUIREMENT.annual_years to decide
feasibility, and its auto-extend step fetches toward that same number. If the
score function enforces a higher floor, a company lands in the gap: pre-flight
says feasible, the framework raises at runtime, and the reason surfaces as
"recent IPO / insufficient annual history" regardless of listing age.

Checked by import, not by grep — a stale comment claiming a different floor
fools textual inspection (f7_smart_beta.py:47 did exactly that).
"""
from __future__ import annotations

import importlib

import pytest

FRAMEWORK_MODULES = {
    "F1": "frameworks.f1_pre_discovery",
    "F2": "frameworks.f2_momentum",
    "F3": "frameworks.f3_innovation",
    "F4": "frameworks.f4_stealth",
    "F5": "frameworks.f5_growth_quality",
    "F6": "frameworks.f6_platform",
    "F7": "frameworks.f7_smart_beta",
}


@pytest.mark.parametrize(("code", "module_path"), sorted(FRAMEWORK_MODULES.items()))
def test_declared_annual_years_covers_enforced_floor(code: str, module_path: str) -> None:
    mod = importlib.import_module(module_path)
    enforced = getattr(mod, "MIN_HISTORY_YEARS", None)
    if enforced is None:
        pytest.skip(f"{code} enforces no module-level annual floor")

    requirement = getattr(mod, "DATA_REQUIREMENT", None)
    assert requirement is not None, f"{code} enforces a floor but declares no DATA_REQUIREMENT"

    # The pre-flight gate reads min_annual_years when set, falling back to the
    # fetch target. That is the number that must cover the enforced floor.
    floor = requirement.min_annual_years or requirement.annual_years
    assert floor >= enforced, (
        f"{code} gates on {floor} annual years but enforces "
        f"MIN_HISTORY_YEARS={enforced}. Companies with {floor}-{enforced - 1} "
        f"years pass pre-flight and then raise InsufficientHistoryError."
    )
    assert requirement.annual_years >= floor, (
        f"{code} fetches {requirement.annual_years} annual years but gates on "
        f"{floor} — the fetch target must carry at least the floor, since the "
        f"coverage window spends a slot on fiscal years SEC cannot have yet."
    )


@pytest.mark.parametrize(("code", "module_path"), sorted(FRAMEWORK_MODULES.items()))
def test_declared_requirement_is_self_consistent(code: str, module_path: str) -> None:
    """Non-negative, and price history is declared whenever prices are read."""
    mod = importlib.import_module(module_path)
    requirement = getattr(mod, "DATA_REQUIREMENT", None)
    if requirement is None:
        pytest.skip(f"{code} declares no DATA_REQUIREMENT")

    assert requirement.annual_years >= 0
    assert requirement.quarterly_count >= 0
    assert requirement.price_history_years >= 0
