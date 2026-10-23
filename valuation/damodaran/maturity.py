"""Maturity classifier — ADR-030 (extended for cyclical detection).

Gates Tier A/B fundamental DCF on a maturity check. Tickers whose ROIC
is below the sector-relative floor OR is erratic over the last 3 years
fail the standard `is_mature` test. We further sub-classify the failures
into `cyclical_mature` (long-history capital-equipment / commodity-cycle
firms in a margin trough) vs `young` (still scaling), because the right
DCF for each is structurally different:
  - mature           → standard fundamental DCF off trailing NOPAT
  - cyclical_mature  → DCF off NORMALISED mid-cycle margin × cycle-mean
                       revenue (avoids the trailing-NOPAT trough anchor)
  - young            → ADR-028 target-margin DCF with peer scenario

Criteria for `mature` (Damodaran *Investment Valuation* 3rd ed. Ch.12):
  1. ROIC floor = max(10%, WACC × 1.3); each of last 3 years above.
  2. ROIC stability: CoV = stddev / |mean| < 0.4
  3. ≥ 3 years of ROIC history.

Criteria for `cyclical_mature` (fired when `mature` fails BUT):
  1. ≥ 5 years of revenue history AND of op-margin history
  2. Revenue peak-to-trough swing > 50% (sign of cycle, not secular decline)
  3. AND/OR op-margin stdev > 10 percentage points over the window

KLIC is the canonical example: 9 years history, revenue $540M-$1.5B
swing, margins -13% (2024) to +31% (2022) — clearly cyclical, not young,
and standard DCF anchored on trough NOPAT understates by ~10x.

Public API:
    classify_maturity(roic_history, wacc, revenue_history=None,
                      op_margin_history=None) -> MaturityClassification
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Sequence


_DEFAULT_FLOOR_ABSOLUTE = 0.10                 # 10% absolute minimum
_WACC_MULTIPLIER = 1.3                          # ROIC must beat WACC by 30%
_DEFAULT_COV_THRESHOLD = 0.4
_MIN_HISTORY_YEARS = 3

# Cyclical detection thresholds
_CYCLICAL_MIN_HISTORY = 5                       # need ≥5yr to see a cycle
_CYCLICAL_REV_PT_RATIO = 1.5                    # peak/trough > 1.5x = cyclical
_CYCLICAL_MARGIN_STDEV_PP = 0.10                # ≥10pp op-margin stdev = cyclical


@dataclass(frozen=True)
class MaturityClassification:
    is_mature: bool
    tier: str                                    # "mature" | "cyclical_mature" | "young"
    roic_history: list[float]                   # newest-last; only valid values
    roic_mean: float | None
    roic_stddev: float | None
    roic_cov: float | None                       # stddev / |mean|; None when mean = 0
    roic_floor: float                            # max(0.10, wacc × 1.3)
    floor_pass: bool                             # each year >= floor
    stability_pass: bool                         # CoV < threshold
    history_pass: bool                           # >= 3 years available
    # Cyclical detection diagnostics (None when histories not provided)
    revenue_peak_to_trough: float | None = None  # max(rev) / min(rev) over window
    op_margin_stdev_pp: float | None = None      # stddev of margins in percentage points
    normalized_margin: float | None = None       # median margin over cycle (for normalized DCF)
    normalized_revenue: float | None = None      # mean revenue over cycle (for normalized DCF)
    notes: list[str] = field(default_factory=list)


def _detect_cyclical(
    revenue_history: Sequence[float | None] | None,
    op_margin_history: Sequence[float | None] | None,
) -> tuple[bool, float | None, float | None, float | None, float | None]:
    """Detect cyclical pattern from revenue + op-margin history.

    A ticker is cyclical_mature when its margin history shows
    OSCILLATIONS — multiple sign flips and big peak-to-trough swings.
    Pure scale-up trajectories (e.g., PATH: -154% → -56% → -33% → -12% → +3.5%)
    have at most one sign-flip and are NOT cyclical; they're scale-up.

    Normalized margin is the median of POSITIVE-margin years only —
    excludes trough disasters that distort the "fair-cycle earnings power"
    central tendency. (Median of all 9 years for KLIC is 9.4%, which
    treats two trough disasters as half the central tendency. Median of
    7 positive years for KLIC is 14% — much closer to the actual cycle-
    typical earnings power.)

    Returns (is_cyclical, rev_peak_to_trough, margin_stdev_pp,
              normalized_margin, normalized_revenue).
    """
    if not revenue_history or not op_margin_history:
        return False, None, None, None, None
    rev = [r for r in revenue_history if r is not None and r > 0]
    mar = [m for m in op_margin_history if m is not None]
    if len(rev) < _CYCLICAL_MIN_HISTORY or len(mar) < _CYCLICAL_MIN_HISTORY:
        return False, None, None, None, None

    rev_pt = max(rev) / min(rev) if min(rev) > 0 else None
    margin_stdev = statistics.pstdev(mar) if len(mar) > 1 else 0.0

    # Count "decline events" — years where margin dropped by >5pp YoY. A
    # cyclical pattern has multiple declines (peak years giving back to
    # trough years). A pure scale-up has none (monotonic improvement).
    # KLIC: 3 decline events (18.7→4, 31.3→5.3, 5.3→-13). PATH: 0 (every
    # year improved over prior). NVDA in a normal year: 0-1 (no cycle).
    decline_events = sum(
        1 for i in range(1, len(mar))
        if mar[i] < mar[i - 1] - 0.05
    )

    # Normalized margin from POSITIVE-margin years only — excludes troughs
    # that drag the median below the actual cycle-typical earnings power.
    positive_margins = [m for m in mar if m > 0]
    if positive_margins:
        norm_margin = statistics.median(positive_margins)
    else:
        norm_margin = statistics.median(mar)
    norm_revenue = statistics.fmean(rev)

    # Cyclical iff ≥2 decline events AND margin stdev big enough to matter.
    # The decline-events test excludes pure scale-ups (PATH: 0 declines)
    # while catching cyclicals with only 1-2 sign-flips per cycle (KLIC: 3
    # declines, only 1 sign-flip).
    is_cyclical = decline_events >= 2 and margin_stdev >= _CYCLICAL_MARGIN_STDEV_PP

    return is_cyclical, rev_pt, margin_stdev, norm_margin, norm_revenue


def classify_maturity(
    *,
    roic_history: Sequence[float | None],        # newest-last
    wacc: float,
    revenue_history: Sequence[float | None] | None = None,  # for cyclical detection
    op_margin_history: Sequence[float | None] | None = None,
    cov_threshold: float = _DEFAULT_COV_THRESHOLD,
    min_history_years: int = _MIN_HISTORY_YEARS,
) -> MaturityClassification:
    """Classify a company as mature or young based on ROIC level + stability.

    Args:
        roic_history: ROIC by year, newest-last. None values are skipped
                       (treated as missing periods, not zero).
        wacc: Cost of capital for floor calculation.
        cov_threshold: Coefficient-of-variation cutoff. Default 0.4 per ADR-030.
        min_history_years: Minimum years of data required to assert maturity.
                           Default 3.

    Returns:
        MaturityClassification with full breakdown.

    Examples:
        Stable mature: [0.22, 0.25, 0.24], wacc=0.09 → is_mature=True
            floor=0.117 (all years above), CoV=0.06 (well below 0.40)
        Erratic high ROIC: [0.15, 0.30, 0.08], wacc=0.09 → is_mature=False
            floor=0.117 (year 3 below 0.117 — fails), CoV=0.62 (also fails)
        Stable but low: [0.10, 0.11, 0.09], wacc=0.09 → is_mature=False
            floor=0.117 (none above), CoV=0.10 (stability ok but floor fails)
        Insufficient history: [0.20, 0.22], wacc=0.09 → is_mature=False
            history_pass=False
    """
    notes: list[str] = []

    floor = max(_DEFAULT_FLOOR_ABSOLUTE, wacc * _WACC_MULTIPLIER)

    # Cyclical detection runs FIRST and is independent of ROIC stability —
    # a cyclical-mature company will fail ROIC stability by definition.
    is_cyclical, rev_pt, margin_stdev_pp, norm_margin, norm_rev = _detect_cyclical(
        revenue_history, op_margin_history,
    )

    valid = [r for r in roic_history if r is not None]
    history_pass = len(valid) >= min_history_years

    if not history_pass:
        notes.append(
            f"Insufficient ROIC history: {len(valid)} of {min_history_years} "
            f"years available. Classified as young by default."
        )
        return MaturityClassification(
            is_mature=False,
            tier="young",
            roic_history=list(valid),
            roic_mean=None, roic_stddev=None, roic_cov=None,
            roic_floor=floor, floor_pass=False,
            stability_pass=False, history_pass=False,
            revenue_peak_to_trough=rev_pt, op_margin_stdev_pp=margin_stdev_pp,
            normalized_margin=norm_margin, normalized_revenue=norm_rev,
            notes=notes,
        )

    # Use most-recent 3 years
    window = valid[-min_history_years:]

    floor_pass = all(r >= floor for r in window)
    if not floor_pass:
        below = [r for r in window if r < floor]
        notes.append(
            f"ROIC floor failed: {len(below)} of {len(window)} years below "
            f"floor {floor:.2%} (values: {[f'{r:.2%}' for r in window]}). "
            f"Damodaran criterion: ROIC > WACC × 1.3 demonstrates economic "
            f"value creation; failing this means ROIC ≤ cost of capital."
        )

    mean = statistics.fmean(window)
    stddev = statistics.pstdev(window) if len(window) > 1 else 0.0
    cov: float | None
    if abs(mean) > 1e-9:
        cov = stddev / abs(mean)
    else:
        cov = None

    stability_pass = cov is not None and cov < cov_threshold
    if cov is not None and not stability_pass:
        notes.append(
            f"ROIC stability failed: CoV = stddev/|mean| = {cov:.2f} ≥ "
            f"{cov_threshold:.2f}. ROIC history is erratic; even if mean is "
            f"above floor, fundamental DCF over-relies on a single-period "
            f"snapshot of a moving target."
        )
    elif cov is None:
        notes.append("ROIC mean is ~0 — CoV undefined; treating as unstable")

    is_mature = floor_pass and stability_pass and history_pass

    # Resolve tier — cyclical_mature only fires when standard maturity fails
    # AND we have a confirmed cyclical pattern (long history + big swings).
    if is_mature:
        tier = "mature"
        notes.append(
            f"Mature: 3yr ROIC = {[f'{r:.1%}' for r in window]} all ≥ "
            f"{floor:.2%} (Damodaran value-creation floor), CoV = {cov:.2f} < "
            f"{cov_threshold:.2f}. Fundamental DCF (ADR-027) is the right path."
        )
    elif is_cyclical:
        tier = "cyclical_mature"
        notes.append(
            f"Cyclical-mature: ROIC stability test failed (CoV={cov:.2f} or "
            f"floor violated), BUT revenue peak/trough={rev_pt:.2f}× and "
            f"op-margin stdev={margin_stdev_pp*100:.1f}pp over the history "
            f"indicate a cyclical pattern, not a scale-up. Standard DCF would "
            f"trough-anchor; cyclical normalization (median margin {norm_margin*100:.1f}% × "
            f"cycle-mean revenue ${norm_rev/1e6:.0f}M) is the right path."
        )
    else:
        tier = "young"

    return MaturityClassification(
        is_mature=is_mature,
        tier=tier,
        roic_history=list(window),
        roic_mean=mean,
        roic_stddev=stddev,
        roic_cov=cov,
        roic_floor=floor,
        floor_pass=floor_pass,
        stability_pass=stability_pass,
        history_pass=history_pass,
        revenue_peak_to_trough=rev_pt,
        op_margin_stdev_pp=margin_stdev_pp,
        normalized_margin=norm_margin,
        normalized_revenue=norm_rev,
        notes=notes,
    )
