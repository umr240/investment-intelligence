"""Shared regime-break test (ADR-030 Amendment A1).

ADR-030's insight, generalised: **any model whose inputs are averaged,
z-scored, or regressed across a multi-year history must first ask whether that
history describes one business or two.**

ADR-030 implemented that for the DCF engine (`g = ROIC × reinvestment` is
meaningless before steady state). ADR-042 implemented it again, independently,
for Greenwald EPV (a median margin spanning a loss→profit transition
capitalises a regime that no longer exists). F7 implemented it not at all, and
z-scored across BONEX.ST's −54.5% → +23.6% margin history to a STRONG FIT.

Two copies of a regime test is how a system ends up holding two epistemic
standards and shipping the laxer one. This module is the single copy.

Deterministic. No LLM, no network, no DB.
"""
from __future__ import annotations

from statistics import median

APPLICABLE = "applicable"
INFLECTING = "inflecting"
NOT_APPLICABLE = "not_applicable"

# A latest margin more than this multiple of the median means operating leverage
# is still arriving, so the median understates steady state.
_MARGIN_DOUBLING_FACTOR = 2.0
_MIN_HISTORY = 3


def assess_margin_regime(
    margins: list[float | None],
    *,
    min_history: int = _MIN_HISTORY,
) -> tuple[str, str]:
    """Is a multi-year average over these margins meaningful? → (verdict, reason).

    Verdicts:
      ``applicable``     — regime-stable; averaging/z-scoring is meaningful.
      ``inflecting``     — the window spans a regime change, so any statistic
                           computed over it describes the change, not the
                           business.
      ``not_applicable`` — too little history to judge either way.

    Note the deliberate asymmetry: a **consistently loss-making** company is
    ``applicable``. Its earning power genuinely is negative and that is a
    finding, not a misapplication. Only a *transition* invalidates the average.
    """
    valid = [m for m in margins if m is not None]
    if len(valid) < min_history:
        return NOT_APPLICABLE, (
            f"only {len(valid)}yr of margin history — needs {min_history}+ to "
            f"judge whether the window spans one regime"
        )

    latest = valid[-1]
    has_losses = any(m < 0 for m in valid)
    has_profits = any(m >= 0 for m in valid)

    # Sign regime change: was loss-making, is now durably profitable.
    if has_losses and has_profits and latest > 0 and all(m > 0 for m in valid[-2:]):
        return INFLECTING, (
            f"margin history crosses from loss to profit "
            f"({min(valid):.1%} → {latest:.1%}); statistics over this window are "
            f"dominated by a pre-inflection regime the business has left"
        )

    med = median(valid)
    if latest > 0 and med > 0 and latest > med * _MARGIN_DOUBLING_FACTOR:
        return INFLECTING, (
            f"latest margin {latest:.1%} is more than "
            f"{_MARGIN_DOUBLING_FACTOR:g}x the median {med:.1%} — operating "
            f"leverage is still arriving, so the median understates steady state"
        )

    return APPLICABLE, (
        f"margin history is regime-stable (median {med:.1%}, latest {latest:.1%})"
    )
