"""NOPAT computation with Tier A / B / C selection (ADR-027).

Damodaran's NOPAT discipline:
  NOPAT = EBIT × (1 − marginal_tax_rate)

Where EBIT is "economic" — NOT necessarily the GAAP operating income line.
Per ADR-027 §Decision the three tiers are:

  Tier A — GAAP-profitable (EBIT_gaap > 0)
      EBIT = Financial.operating_income (as reported)
      NOPAT = EBIT × (1 − t)

  Tier B — PT-rescued loss-maker (EBIT_gaap < 0 BUT EBIT + R&D > 0)
      EBIT_economic = EBIT_gaap + R&D_current − R&D_amortization
      NOPAT = EBIT_economic × (1 − t)
      Per Damodaran "Investment Valuation" Ch.9: capitalize R&D, amortize
      straight-line over 5-10yr (5 default for software/tech, 10 for pharma).
      We use 5yr as the project's default; specific industry overrides
      could refine in a future enhancement.

  Tier C — true loss-maker (EBIT + R&D ≤ 0)
      NOPAT not computable from this framework. Return None.
      Caller surfaces a data_gap and emits no intrinsic value. The
      young-company target-margin DCF (ADR-028, deferred) is the right
      tool for these.

Why "EBIT + R&D" is the simple Tier B test (not a full Peters-Taylor):
  - The full PT calc adds capitalized R&D to invested capital AND amortizes
    over multiple years. That changes both numerator (NOPAT) and denominator
    (IC).
  - For the TIER GATE specifically — "is this company economically profitable
    when R&D is treated as investment?" — `EBIT + R&D > 0` is sufficient:
    if even adding back ALL current R&D doesn't flip EBIT positive, no
    amortization schedule will.
  - The MAGNITUDE adjustment uses R&D − amort (the increment to knowledge
    capital), not just R&D, so the NOPAT magnitude is consistent with
    Damodaran's textbook formulation.

Public API:
  classify_tier(...) -> Tier
  compute_economic_ebit(...) -> EBITResult
  compute_nopat(...) -> NOPATResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


# ── Constants ────────────────────────────────────────────────────────────

# Damodaran's R&D capitalization useful-life defaults (years).
# Tech / consumer / general → 5; pharma / biotech → 10. We default to 5 and
# let caller override for specific industries.
_R_AND_D_AMORT_YEARS_DEFAULT = 5
_R_AND_D_AMORT_YEARS_PHARMA = 10


# ── Result types ─────────────────────────────────────────────────────────


class Tier(str, Enum):
    A_GAAP = "A_gaap"                 # EBIT_gaap > 0
    B_PT_RESCUED = "B_pt_rescued"     # EBIT_gaap < 0 BUT EBIT + R&D > 0
    C_INSUFFICIENT = "C_insufficient" # Even with R&D adj, still negative


@dataclass(frozen=True)
class EBITResult:
    tier: Tier
    ebit_gaap: float | None
    rd_expense_current: float | None
    rd_amortization_current: float | None
    ebit_economic: float | None      # None when tier == C_INSUFFICIENT
    nopat_source: str                 # "gaap" | "pt_adjusted" | "n/a"
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NOPATResult:
    tier: Tier
    ebit_economic: float | None
    marginal_tax_rate: float
    nopat: float | None              # None when tier == C_INSUFFICIENT
    nopat_source: str
    notes: list[str] = field(default_factory=list)


# ── Pure functions ───────────────────────────────────────────────────────


def _rd_amortization(
    rd_history: Sequence[float | None],
    amort_years: int = _R_AND_D_AMORT_YEARS_DEFAULT,
) -> float | None:
    """Compute current-year R&D amortization assuming straight-line over
    `amort_years`. Uses the most-recent `amort_years` of R&D expense from
    `rd_history` (newest-last convention).

    Damodaran's formula: amortization = avg(R&D_{t-1} .. R&D_{t-amort_years}) /
    amort_years × amort_years = sum / amort_years.

    Equivalently: take the last `amort_years` of R&D, sum them, divide by
    `amort_years` — that's the current amortization charge against the
    accumulated R&D asset.

    Returns None when fewer than 2 years of R&D data available (can't
    estimate meaningfully).
    """
    if not rd_history:
        return None
    valid = [v for v in rd_history if v is not None and v > 0]
    if len(valid) < 2:
        return None
    window = valid[-amort_years:]
    return sum(window) / len(window)


def classify_tier(
    ebit_gaap: float | None,
    rd_current: float | None,
    rd_history: Sequence[float | None] | None = None,
) -> Tier:
    """Quick gate (no magnitude calc): which tier does this filer fall into?

    Args:
        ebit_gaap: Reported operating income (Financial.operating_income).
        rd_current: Current-period R&D expense.
        rd_history: Optional N-year R&D history for amortization-aware
                    classification. When omitted, falls back to the simple
                    `ebit + rd > 0` test.
    """
    if ebit_gaap is None:
        return Tier.C_INSUFFICIENT
    if ebit_gaap > 0:
        return Tier.A_GAAP

    # ebit_gaap <= 0 — check if R&D rescue applies
    if rd_current is None or rd_current <= 0:
        return Tier.C_INSUFFICIENT

    # Simple rescue test: does EBIT + current R&D become positive?
    if ebit_gaap + rd_current > 0:
        return Tier.B_PT_RESCUED

    return Tier.C_INSUFFICIENT


def compute_economic_ebit(
    ebit_gaap: float | None,
    rd_current: float | None,
    rd_history: Sequence[float | None] | None = None,
    amort_years: int = _R_AND_D_AMORT_YEARS_DEFAULT,
) -> EBITResult:
    """Compute the economic EBIT to use as NOPAT input, applying R&D
    capitalization (Tier B) when warranted.

    Tier A → ebit_economic = ebit_gaap, source = "gaap"
    Tier B → ebit_economic = ebit_gaap + rd_current − rd_amortization, source = "pt_adjusted"
    Tier C → ebit_economic = None
    """
    tier = classify_tier(ebit_gaap, rd_current, rd_history)
    notes: list[str] = []

    if tier == Tier.A_GAAP:
        return EBITResult(
            tier=tier,
            ebit_gaap=ebit_gaap,
            rd_expense_current=rd_current,
            rd_amortization_current=None,
            ebit_economic=ebit_gaap,
            nopat_source="gaap",
            notes=notes,
        )

    if tier == Tier.C_INSUFFICIENT:
        notes.append(
            "Tier C — EBIT remains non-positive even after R&D add-back. "
            "Damodaran intrinsic value not computable from this framework. "
            "See ADR-028 (young-company target-margin DCF, deferred)."
        )
        return EBITResult(
            tier=tier,
            ebit_gaap=ebit_gaap,
            rd_expense_current=rd_current,
            rd_amortization_current=None,
            ebit_economic=None,
            nopat_source="n/a",
            notes=notes,
        )

    # Tier B — R&D rescue. Compute amortization if history available.
    amort = _rd_amortization(rd_history or (), amort_years=amort_years)
    if amort is None:
        # Fall back to "no amortization" (treats all R&D as the current-year
        # increment to knowledge capital). Slightly aggressive — surfaces
        # in notes for transparency.
        amort = 0.0
        notes.append(
            f"Tier B — R&D amortization defaulted to 0 (insufficient history; "
            f"need ≥2 years of R&D data, got {len([v for v in (rd_history or ()) if v])}). "
            f"Economic EBIT = EBIT_gaap + R&D_current with no amort offset. "
            f"This is the most aggressive Tier B treatment; refresh once 5y of R&D data available."
        )
    else:
        notes.append(
            f"Tier B — R&D capitalized with {amort_years}-year straight-line amortization. "
            f"Current amortization = ${amort:,.0f}. Economic EBIT = "
            f"GAAP EBIT + R&D − amortization = "
            f"${ebit_gaap:,.0f} + ${rd_current:,.0f} − ${amort:,.0f}."
        )

    ebit_econ = ebit_gaap + (rd_current or 0.0) - amort

    # Reconciliation gate: classify_tier uses the SIMPLE rescue test
    # (ebit + rd_current > 0) without amortization. For hyper-growers
    # whose R&D is still ramping fast (SNOW, etc.), the 5yr amortization
    # of accumulated R&D can exceed current-year add-back, flipping
    # economic EBIT back negative. The classifier and the calc must agree
    # — the calc is truth. Re-classify as Tier C so downstream (project_fcff,
    # terminal value) is never called with a non-positive NOPAT base.
    # `< 0` strict: ebit_econ = 0 is the borderline rescue case (preserved
    # for existing test contract). Downstream projection still cannot run
    # with NOPAT=0, but that's a separate caller-side gate.
    if ebit_econ < 0:
        notes.append(
            f"Tier B → C downgrade — amortization-adjusted economic EBIT "
            f"= ${ebit_econ:,.0f} (still non-positive). "
            f"R&D add-back of ${rd_current:,.0f} is more than offset by 5yr-window "
            f"amortization of ${amort:,.0f} (rapid R&D growth pattern). "
            f"Damodaran fundamental DCF not applicable — needs ADR-028 "
            f"young-company target-margin path (deferred / scenario-based)."
        )
        return EBITResult(
            tier=Tier.C_INSUFFICIENT,
            ebit_gaap=ebit_gaap,
            rd_expense_current=rd_current,
            rd_amortization_current=amort,
            ebit_economic=None,
            nopat_source="n/a",
            notes=notes,
        )

    return EBITResult(
        tier=tier,
        ebit_gaap=ebit_gaap,
        rd_expense_current=rd_current,
        rd_amortization_current=amort,
        ebit_economic=ebit_econ,
        nopat_source="pt_adjusted",
        notes=notes,
    )


def compute_nopat(
    ebit_gaap: float | None,
    marginal_tax_rate: float,
    rd_current: float | None = None,
    rd_history: Sequence[float | None] | None = None,
    amort_years: int = _R_AND_D_AMORT_YEARS_DEFAULT,
) -> NOPATResult:
    """Compute NOPAT (= EBIT_economic × (1 − t)) with full Tier classification.

    NOPAT = None when tier == C_INSUFFICIENT (signals to caller: emit data_gap,
    no intrinsic value).
    """
    ebit_result = compute_economic_ebit(
        ebit_gaap=ebit_gaap,
        rd_current=rd_current,
        rd_history=rd_history,
        amort_years=amort_years,
    )

    if ebit_result.ebit_economic is None:
        return NOPATResult(
            tier=ebit_result.tier,
            ebit_economic=None,
            marginal_tax_rate=marginal_tax_rate,
            nopat=None,
            nopat_source=ebit_result.nopat_source,
            notes=ebit_result.notes,
        )

    nopat = ebit_result.ebit_economic * (1.0 - marginal_tax_rate)
    return NOPATResult(
        tier=ebit_result.tier,
        ebit_economic=ebit_result.ebit_economic,
        marginal_tax_rate=marginal_tax_rate,
        nopat=nopat,
        nopat_source=ebit_result.nopat_source,
        notes=ebit_result.notes,
    )
