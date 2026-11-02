"""
Composite-score and company-stage classification.

Per PROJECT_SPEC §4.4, the composite score is mode-dependent AND stage-
dependent:

  Mode A (F1+F2+F3): equal-weight average. No stage.
  Mode B (F1-F5):    stage-weighted (pre_profitability / mid_cap / established).
  Mode C (F1-F7):    stage-weighted; F7 carries ≤0.10 weight (contested).

Stage classification heuristic:
  - pre_profitability: latest annual net_income < 0
  - established:       market_cap >= $50B AND last 3 annuals all profitable
  - mid_cap:           everything else

Verdict thresholds (PROJECT_SPEC §4.4):
  priority_watchlist: composite >= 7.0
  watchlist: 5.0 <= composite < 7.0
  monitor:   3.0 <= composite < 5.0
  exclude:   composite < 3.0

Labels never name an action (ADR-054): there is no buy verdict.

When a framework is unfeasible (e.g. F7 on a recent IPO), its score is
absent. We renormalise the remaining weights so the missing score doesn't
drag the composite to zero — present-frameworks-only weighting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from config.constants import (
    MIN_FRAMEWORK_WEIGHT_COVERAGE,
    VERDICT_PRIORITY_WATCHLIST,
    VERDICT_WATCHLIST,
    VERDICT_MONITOR,
    WEIGHTS_B,
    WEIGHTS_C,
)

# Bump both on any change to this module's formula or the overlay bonus
# (deepdive/orchestrator.py): golden-set cases from older dives stop replaying (ADR-047 §2.7).
COMPOSITE_VERSION = 1
COMPOSITE_SINCE = date(2026, 10, 23)  # first dive date scored by this version


# ── Stage classification ──────────────────────────────────────────────────

ESTABLISHED_MARKET_CAP_USD: float = 50_000_000_000   # $50B threshold


@dataclass(frozen=True)
class StageClassification:
    """Output of classify_company_stage().

    `stage` is one of 'pre_profitability' | 'mid_cap' | 'established'.
    `reasoning` carries the inputs the classification used so the
    framework_scores.scorecard_json can audit later.
    """
    stage: str
    reasoning: dict[str, Any]


def classify_company_stage(reader: Any) -> StageClassification:
    """Classify a company into one of three stages from its persisted data.

    Determinism: this function NEVER calls APIs. It reads only what
    `CompanyDataReader` exposes from the SQLite warehouse.
    """
    annuals = reader.annuals(last_n=3)
    company = reader.company_or_none()

    if not annuals:
        return StageClassification(
            stage="mid_cap",
            reasoning={"fallback": "no annual financials persisted"},
        )

    latest = annuals[0]
    market_cap = company.market_cap_usd if company is not None else None

    # pre_profitability: GAAP-loss-making in the latest annual
    if latest.net_income is not None and latest.net_income < 0:
        return StageClassification(
            stage="pre_profitability",
            reasoning={
                "latest_net_income": latest.net_income,
                "latest_fy": latest.fiscal_year,
                "market_cap_usd": market_cap,
            },
        )

    # established: $50B+ market cap AND 3 consecutive profitable annuals
    profitable_3yr = (
        len(annuals) >= 3
        and all(
            a.net_income is not None and a.net_income > 0
            for a in annuals[:3]
        )
    )
    if (
        market_cap is not None
        and market_cap >= ESTABLISHED_MARKET_CAP_USD
        and profitable_3yr
    ):
        return StageClassification(
            stage="established",
            reasoning={
                "market_cap_usd": market_cap,
                "established_threshold": ESTABLISHED_MARKET_CAP_USD,
                "profitable_3yr": True,
                "n_profitable_annuals": sum(
                    1 for a in annuals if a.net_income and a.net_income > 0
                ),
            },
        )

    # mid_cap: profitable but not yet "established"
    return StageClassification(
        stage="mid_cap",
        reasoning={
            "market_cap_usd": market_cap,
            "established_threshold": ESTABLISHED_MARKET_CAP_USD,
            "profitable_3yr": profitable_3yr,
            "latest_net_income": latest.net_income,
        },
    )


# ── Composite scoring ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompositeOutput:
    """Output of compute_composite_score()."""
    # ADR-030 A1 §3.4: None when the composite is SUPPRESSED for insufficient
    # breadth (fewer than MIN_UNCAPPED_FRAMEWORKS uncapped frameworks feasible).
    # Renderers must show "suppressed", never coerce None to 0.0 — a 0.0 reads
    # as "scored badly" when the truth is "not scoreable".
    score: float | None                   # 0-10, or None when suppressed
    verdict: str                          # priority_watchlist | watchlist | monitor
                                          #   | exclude | research_only
    weights_used: dict[str, float]        # the actual {'F1': 0.30, ...} that fired
    weights_renormalised: bool            # True iff missing scores forced renorm
    mode_resolved: str                    # 'A' | 'B' | 'C' (after default→inference)
    stage_resolved: str                   # echoed for traceability
    framework_weight_coverage: float = 1.0  # pre-renorm sum of present weights (0..1)
    verdict_capped_by_data: bool = False    # True when coverage floor downgraded the verdict


# ── ADR-030 Amendment A1 §3.4 — caps that survive renormalisation ─────────
# PROJECT_SPEC §F7 / CLAUDE.md: "weight F7 ≤ 0.10 in any composite score".
# That ceiling was silently void whenever renormalisation ran. Measured on
# BONEX.ST (only F2/F5/F7 feasible): renormalising 0.15/0.20/0.15 over 0.50
# gave 0.30/0.40/0.30 — F7 at THREE TIMES its documented maximum.
#
# The inversion is what makes it serious: renormalisation runs precisely when
# frameworks are unfeasible, i.e. on the thinnest, least reliable names, where
# a cap on a contested signal matters most. The safeguard disabled itself
# exactly when it was needed.
_MAX_WEIGHTS: dict[str, float] = {
    "F7": 0.10,     # contested academic ground; cheapness only, not quality
}

# Below this many UNCAPPED frameworks, the composite is suppressed (None).
MIN_UNCAPPED_FRAMEWORKS = 2


def _renormalise_with_caps(
    present_weighted: dict[str, float],
    weight_sum: float,
) -> dict[str, float]:
    """Renormalise to 1.0 while honouring per-framework maximums.

    Excess released by a capped framework redistributes pro-rata across the
    UNCAPPED survivors, so the vector still sums to 1.0. Iterates because
    redistribution can push a second framework over its own cap.
    """
    normed = {k: w / weight_sum for k, w in present_weighted.items()}

    for _ in range(len(normed) + 1):
        over = {k: _MAX_WEIGHTS[k] for k in normed
                if k in _MAX_WEIGHTS and normed[k] > _MAX_WEIGHTS[k] + 1e-9}
        if not over:
            break
        freed = sum(normed[k] - cap for k, cap in over.items())
        normed.update(over)
        free_keys = [k for k in normed if k not in over]
        free_total = sum(normed[k] for k in free_keys)
        if not free_keys or free_total <= 0:
            break   # nothing to absorb it; leave capped and short of 1.0
        for k in free_keys:
            normed[k] += freed * (normed[k] / free_total)

    return {k: round(v, 4) for k, v in normed.items()}


def compute_composite_score(
    scores: dict[str, float | None],
    *,
    mode: str,
    stage: str,
) -> CompositeOutput:
    """Apply mode + stage weights to per-framework scores.

    `scores` example: {'F1': 6.83, 'F2': 9.0, 'F3': 7.0, 'F4': 3.5,
                       'F5': 9.0, 'F6': 3.0, 'F7': 0.0}
    A framework with score=None is treated as ABSENT — weight renormalised.

    `mode`:
      'A' | 'a'         → F1+F2+F3 equal-weight (1/3 each)
      'B' | 'b'         → WEIGHTS_B[stage]
      'C' | 'c'         → WEIGHTS_C[stage]
      'default'/other   → inferred: WEIGHTS_C if F6/F7 present else
                                    WEIGHTS_B if F4/F5 present else
                                    Mode A
    """
    mode_norm = (mode or "default").upper()
    mode_resolved = _resolve_mode(mode_norm, scores)

    # Build the ideal weight vector for this mode + stage
    if mode_resolved == "A":
        ideal = {"F1": 1.0 / 3, "F2": 1.0 / 3, "F3": 1.0 / 3}
    elif mode_resolved == "B":
        stage_weights = WEIGHTS_B.get(stage, WEIGHTS_B["mid_cap"])
        ideal = {k.upper(): v for k, v in stage_weights.items()}
    else:    # 'C'
        stage_weights = WEIGHTS_C.get(stage, WEIGHTS_C["mid_cap"])
        ideal = {k.upper(): v for k, v in stage_weights.items()}

    # Filter to frameworks that have a real score; renormalise the rest
    present_weighted: dict[str, float] = {}
    weight_sum = 0.0
    for fkey, weight in ideal.items():
        score = scores.get(fkey)
        if score is None:
            continue
        present_weighted[fkey] = weight
        weight_sum += weight

    if weight_sum == 0.0:
        return CompositeOutput(
            score=0.0,
            verdict="exclude",
            weights_used={},
            weights_renormalised=False,
            mode_resolved=mode_resolved,
            stage_resolved=stage,
        )

    renormalised = weight_sum < 0.999
    final_weights = _renormalise_with_caps(present_weighted, weight_sum)

    # ADR-030 A1 §3.4 — with capped frameworks removed from the driving set,
    # a "composite" of fewer than two uncapped survivors is one framework
    # wearing an aggregate's clothing. Suppress rather than renormalise: the
    # single number is the one most likely to be quoted without its caveats.
    uncapped_present = [k for k in final_weights if k not in _MAX_WEIGHTS]
    if len(uncapped_present) < MIN_UNCAPPED_FRAMEWORKS:
        return CompositeOutput(
            score=None,
            verdict="research_only",
            weights_used=final_weights,
            weights_renormalised=renormalised,
            mode_resolved=mode_resolved,
            stage_resolved=stage,
        )

    weighted_sum = sum(scores[fkey] * w for fkey, w in final_weights.items())
    score = round(min(max(weighted_sum, 0.0), 10.0), 2)

    if score >= VERDICT_PRIORITY_WATCHLIST:
        verdict = "priority_watchlist"
    elif score >= VERDICT_WATCHLIST:
        verdict = "watchlist"
    elif score >= VERDICT_MONITOR:
        verdict = "monitor"
    else:
        verdict = "exclude"

    # Data-coverage floor: when too little of the framework weight is
    # present, a single thin signal can produce a misleadingly high score.
    # Cap the verdict at "monitor" so callers don't promote shell-company
    # tickers to watchlist on default-baseline scores.
    verdict_capped = False
    capped_bands = ("priority_watchlist", "watchlist")
    if weight_sum < MIN_FRAMEWORK_WEIGHT_COVERAGE and verdict in capped_bands:
        verdict = "monitor"
        verdict_capped = True

    return CompositeOutput(
        score=score,
        verdict=verdict,
        weights_used=final_weights,
        weights_renormalised=renormalised,
        mode_resolved=mode_resolved,
        stage_resolved=stage,
        framework_weight_coverage=round(weight_sum, 4),
        verdict_capped_by_data=verdict_capped,
    )


def _resolve_mode(mode_norm: str, scores: dict[str, float | None]) -> str:
    """Convert an explicit mode letter or 'DEFAULT' into a resolved A/B/C.

    'default' picks the most expressive mode that matches what actually
    scored: Mode C if any F6/F7 is present, Mode B if F4/F5 present,
    else Mode A.
    """
    if mode_norm in ("A", "B", "C"):
        return mode_norm
    has_67 = scores.get("F6") is not None or scores.get("F7") is not None
    has_45 = scores.get("F4") is not None or scores.get("F5") is not None
    if has_67:
        return "C"
    if has_45:
        return "B"
    return "A"
