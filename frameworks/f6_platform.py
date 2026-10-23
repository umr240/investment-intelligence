"""
F6 — Platform Dominator (Mode C).

PROJECT_SPEC §F6 weights the score 60% academic / 40% practitioner:

  ACADEMIC ANCHORS (6.0 points)
    1. Fahlenbrach 2009 founder-CEO premium                    2.0
       founder=True AND ceo_equity_pct/100 > 0.05
    2. Patatoukas 2012 customer concentration sweet spot       2.0
       15-30% top-customer revenue share AND ≥3yr relationship
    3. Novy-Marx 2013 GP/A top-40%                             2.0
       gp/a >= 0.20

  PRACTITIONER HEURISTICS — flagged as ◯ confirmatory (4.0 points)
    4. Rule of 40 (Brad Feld blog ◯)                           2.0
       revenue_growth_rate + fcf_margin >= 35
    5. NRR ≥ 110% (◯)                                          1.0
       NOT in our data layer — data gap, scored 0
    6. GRR proxy ≥ 90% (◯)                                     1.0
       NOT in our data layer — data gap, scored 0

The 3-state semantics from ADR-018 are honored:
  - customer_concentration_state='not_disclosed' → 0 Patatoukas points
    (NOT a parser failure; absence of disclosure is genuine signal)
  - customer_concentration_state='parser_uncertain' → 1 partial point
  - ceo_equity_pct_state='parser_uncertain' (e.g. AAPL <1% sentinel) → no
    Fahlenbrach credit (sentinel never crosses 5%)

Customer concentration uses REVENUE concentration only. Receivables
concentration (a different SEC disclosure) is NOT the Patatoukas signal.

Switching costs / network effects = qualitative; deferred to deepdive
narrative (Phase 6 LLM layer per CLAUDE.md).
"""
from __future__ import annotations

from typing import Any

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
)


DATA_REQUIREMENT = DataRequirement(
    annual_years=3,
    quarterly_count=8,
    needs_proxy_ownership=True,
    needs_founder_status=True,
    needs_customer_concentration=True,
    needs_retention_metrics=True,    # 5k-7: NRR/GRR regex on 10-K MD&A
)


# ── Tunables ──────────────────────────────────────────────────────────────

CEO_EQUITY_THRESHOLD = 0.05               # Fahlenbrach >5% (ratio, not %)

PATATOUKAS_CONC_LO = 15.0                 # Patatoukas sweet spot 15-30%
PATATOUKAS_CONC_HI = 30.0
PATATOUKAS_RELATIONSHIP_MIN_YEARS = 3.0

GP_A_TOP_TIER = 0.20                      # Novy-Marx top-40% proxy

RULE_OF_40_TARGET = 35.0                  # revenue_growth% + fcf_margin% (both as %)
RULE_OF_40_PARTIAL = 25.0

# Phase 5k-7: NRR/GRR scoring bands. Practitioner heuristic ◯ — values come
# from 10-K MD&A regex (data/edgar_text_parser.py). Best-in-class SaaS NRR
# is ≥110%; ≥100% means existing-customer revenue at minimum stable;
# <90% indicates real churn risk. GRR best-in-class ≥90%; <85% suggests
# product-market-fit issues.
NRR_BEST_IN_CLASS = 110.0
NRR_HEALTHY = 100.0
GRR_BEST_IN_CLASS = 90.0
GRR_HEALTHY = 85.0

# Component max points (sum to 10.0)
FOUNDER_MAX = 2.0
PATATOUKAS_MAX = 2.0
GP_A_MAX = 2.0
RULE40_MAX = 2.0
NRR_MAX = 1.0
GRR_MAX = 1.0


async def score_f6(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F6 — Platform Dominator score."""
    annuals = reader.annuals(last_n=3)
    if len(annuals) < 2:
        raise InsufficientHistoryError(
            "F6", needed=2, got=len(annuals), period_kind="annual"
        )

    current = annuals[0]
    prior = annuals[1]
    company = reader.company_or_none()

    signals: dict[str, Any] = {}
    data_gaps: list[str] = []

    # ── 1. Fahlenbrach founder-CEO premium ───────────────────────────────
    fnd_pts, fnd_signals, fnd_gap = _compute_founder_signal(company, ticker)
    signals["founder_ceo"] = fnd_signals
    if fnd_gap:
        data_gaps.append(fnd_gap)

    # ── 2. Patatoukas customer concentration ─────────────────────────────
    pat_pts, pat_signals, pat_gap = _compute_patatoukas(current, ticker)
    signals["customer_concentration"] = pat_signals
    if pat_gap:
        data_gaps.append(pat_gap)

    # ── 3. Novy-Marx GP/A ────────────────────────────────────────────────
    gpa_pts, gpa_signals, gpa_gap = _compute_gp_a(current, ticker)
    signals["gp_a"] = gpa_signals
    if gpa_gap:
        data_gaps.append(gpa_gap)

    # ── 4. Rule of 40 ────────────────────────────────────────────────────
    r40_pts, r40_signals, r40_gap = _compute_rule_of_40(current, prior, ticker)
    signals["rule_of_40"] = r40_signals
    if r40_gap:
        data_gaps.append(r40_gap)

    # ── 5+6. NRR / GRR — Phase 5k-7 (10-K MD&A regex extraction) ─────────
    nrr_pts, nrr_signals, nrr_gap = _compute_nrr(current, ticker)
    signals["nrr"] = nrr_signals
    if nrr_gap:
        data_gaps.append(nrr_gap)

    grr_pts, grr_signals, grr_gap = _compute_grr(current, ticker)
    signals["grr"] = grr_signals
    if grr_gap:
        data_gaps.append(grr_gap)

    score = round(fnd_pts + pat_pts + gpa_pts + r40_pts + nrr_pts + grr_pts, 2)
    score = min(max(score, 0.0), 10.0)
    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    notes = (
        "F6 NRR + GRR populated when 10-K MD&A discloses retention metrics "
        "(typical SaaS practice; ~30-40% hit rate across SaaS universe). "
        "Absence treated as `not_disclosed` zero-points — same as the F6 "
        "customer_concentration semantics."
    )

    return FrameworkResult(
        framework="F6",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
        notes=notes,
    )


# ── 1. Fahlenbrach founder-CEO + skin in the game ────────────────────────


def _compute_founder_signal(
    company: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Founder-CEO with >5% equity = Fahlenbrach signal full points.

    Honors ADR-018 D2 'parser_uncertain' state — a sentinel value (e.g.
    AAPL's <1% placeholder of 0.5) cannot earn Fahlenbrach credit because
    the threshold is 5% and a sentinel never crosses it.
    """
    if company is None:
        return 0.0, {"founder": None, "equity_pct": None, "points": 0.0}, \
               f"{ticker}: F6 founder-CEO — no Company row"

    is_founder = company.is_founder_ceo
    equity_pct = company.ceo_equity_pct
    equity_state = company.ceo_equity_pct_state
    equity_ratio = (equity_pct / 100.0) if equity_pct is not None else None

    fahlenbrach_signal = (
        is_founder is True
        and equity_ratio is not None
        and equity_ratio > CEO_EQUITY_THRESHOLD
        and equity_state != "parser_uncertain"
    )

    if fahlenbrach_signal:
        pts = FOUNDER_MAX
        band = "founder_with_skin"
    elif is_founder is True and equity_ratio is not None and equity_ratio > 0.01:
        # Founder-CEO but equity below 5% threshold — partial
        pts = 1.0
        band = "founder_low_equity"
    elif equity_ratio is not None and equity_ratio > CEO_EQUITY_THRESHOLD and equity_state != "parser_uncertain":
        # Non-founder with material skin — Fahlenbrach is specifically founder
        # so we give half credit (alignment without founder premium)
        pts = 1.0
        band = "non_founder_high_equity"
    else:
        pts = 0.0
        band = "no_signal"

    return pts, {
        "is_founder_ceo": is_founder,
        "ceo_equity_pct": equity_pct,
        "ceo_equity_pct_state": equity_state,
        "fahlenbrach_signal": fahlenbrach_signal,
        "band": band,
        "points": pts,
    }, None


# ── 2. Patatoukas customer concentration ──────────────────────────────────


def _compute_patatoukas(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Patatoukas 2012: 15-30% top customer share + ≥3yr relationship = positive.

    Respects three-state semantics:
      - state='not_disclosed' → 0 (NOT a gap; the company is diversified)
      - state='parser_uncertain' → 0.5 partial points
      - state='disclosed_exact' → score by sweet-spot bands
    Receivables concentration (a different SEC disclosure) does NOT count.
    """
    pct = current.customer_concentration_pct
    state = current.customer_concentration_state
    rel_years = current.customer_relationship_years

    if state == "not_disclosed":
        return 0.0, {
            "concentration_pct": None,
            "relationship_years": None,
            "state": state,
            "patatoukas_signal": False,
            "band": "diversified_no_concentration",
            "points": 0.0,
            "note": ("not_disclosed is a positive diversification signal; "
                     "Patatoukas requires a top-customer disclosure to fire"),
        }, None

    if pct is None:
        return 0.0, {
            "concentration_pct": None,
            "relationship_years": None,
            "state": state,
            "points": 0.0,
        }, None

    in_sweet = PATATOUKAS_CONC_LO <= pct <= PATATOUKAS_CONC_HI
    has_rel = rel_years is not None and rel_years >= PATATOUKAS_RELATIONSHIP_MIN_YEARS
    full_signal = in_sweet and has_rel

    if full_signal:
        pts = PATATOUKAS_MAX
        band = "patatoukas_full"
    elif in_sweet and rel_years is None:
        # Sweet-spot concentration, relationship duration unknown — partial
        pts = 1.0
        band = "patatoukas_partial_no_relationship"
    elif pct > PATATOUKAS_CONC_HI:
        # Too concentrated → above-sweet-spot is a RISK not a moat
        pts = 0.0
        band = "over_concentrated"
    elif state == "parser_uncertain":
        pts = 0.5
        band = "uncertain"
    else:
        pts = 0.0
        band = "below_sweet_spot"

    return pts, {
        "concentration_pct": pct,
        "relationship_years": rel_years,
        "state": state,
        "in_sweet_spot": in_sweet,
        "has_mature_relationship": has_rel,
        "patatoukas_signal": full_signal,
        "band": band,
        "points": pts,
    }, None


# ── 3. Novy-Marx GP/A top-tier ────────────────────────────────────────────


def _compute_gp_a(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    g = current.gp_a
    if g is None:
        return 0.0, {"gp_a": None, "points": 0.0}, f"{ticker}: F6 GP/A — no value"
    if g >= GP_A_TOP_TIER:
        pts = GP_A_MAX
        band = "top_40pct_proxy"
    elif g >= GP_A_TOP_TIER * 0.5:
        pts = 1.0
        band = "moderate"
    else:
        pts = 0.0
        band = "weak"
    return pts, {
        "gp_a": round(g, 4),
        "target": GP_A_TOP_TIER,
        "band": band,
        "points": pts,
    }, None


# ── 4. Rule of 40 ─────────────────────────────────────────────────────────


def _compute_rule_of_40(
    current: Any, prior: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Rule of 40 (Brad Feld practitioner heuristic ◯):
       revenue_growth_rate + fcf_margin >= 35.

    Both as percentages (0-100), summed.
    """
    if not (current.revenue and prior.revenue):
        return 0.0, {
            "revenue_growth_pct": None,
            "fcf_margin_pct": None,
            "rule_of_40": None,
            "points": 0.0,
        }, f"{ticker}: F6 Rule of 40 — missing revenue"

    growth = ((current.revenue - prior.revenue) / prior.revenue) * 100.0
    fcf_m = (current.fcf_margin or 0) * 100.0
    r40 = growth + fcf_m

    if r40 >= RULE_OF_40_TARGET:
        pts = RULE40_MAX
        band = "passing"
    elif r40 >= RULE_OF_40_PARTIAL:
        pts = 1.0
        band = "near"
    else:
        pts = 0.0
        band = "below"

    return pts, {
        "revenue_growth_pct": round(growth, 2),
        "fcf_margin_pct": round(fcf_m, 2),
        "rule_of_40": round(r40, 2),
        "target": RULE_OF_40_TARGET,
        "band": band,
        "points": pts,
    }, None


# ── 5. Net Revenue Retention — Phase 5k-7 ────────────────────────────────


def _compute_nrr(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Net Revenue Retention from 10-K MD&A regex (PROJECT_SPEC §F6 #5).

    Score bands:
      - ≥ 110%   → 1.0pt  (best-in-class SaaS — net expansion dominates)
      - 100-110% → 0.5pt  (stable existing-customer base)
      - <100%    → 0.0pt  (net contraction)
      - not_disclosed → 0.0pt with positive-signal note (most companies
                              don't quantify; absence ≠ failure)
      - parser_uncertain → 0.5pt partial (phrase matched, value didn't)
    """
    nrr = current.nrr_pct
    state = current.retention_state
    if nrr is not None:
        if nrr >= NRR_BEST_IN_CLASS:
            pts = NRR_MAX
            band = "best_in_class"
        elif nrr >= NRR_HEALTHY:
            pts = 0.5
            band = "stable"
        else:
            pts = 0.0
            band = "contraction"
        return pts, {
            "value": round(nrr, 2),
            "band": band,
            "points": pts,
            "max_points": NRR_MAX,
            "state": state or "disclosed_exact",
        }, None
    if state == "parser_uncertain":
        return 0.5, {
            "value": None,
            "band": "uncertain",
            "points": 0.5,
            "max_points": NRR_MAX,
            "state": state,
            "note": "retention phrase matched but value couldn't be tied",
        }, None
    return 0.0, {
        "value": None,
        "band": "not_disclosed",
        "points": 0.0,
        "max_points": NRR_MAX,
        "state": "not_disclosed",
        "note": "company does not disclose NRR in 10-K MD&A",
    }, None


# ── 6. Gross Revenue Retention — Phase 5k-7 ──────────────────────────────


def _compute_grr(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Gross Revenue Retention from 10-K MD&A regex (PROJECT_SPEC §F6 #6).

    Score bands:
      - ≥ 90%   → 1.0pt  (best-in-class — minimal churn)
      - 85-90%  → 0.5pt  (acceptable — modest churn)
      - <85%    → 0.0pt  (product-market-fit concern)
      - not_disclosed → 0.0pt
    """
    grr = current.grr_pct
    state = current.retention_state
    if grr is not None:
        if grr >= GRR_BEST_IN_CLASS:
            pts = GRR_MAX
            band = "best_in_class"
        elif grr >= GRR_HEALTHY:
            pts = 0.5
            band = "acceptable"
        else:
            pts = 0.0
            band = "high_churn"
        return pts, {
            "value": round(grr, 2),
            "band": band,
            "points": pts,
            "max_points": GRR_MAX,
            "state": state or "disclosed_exact",
        }, None
    # When GRR value is None, force state to "not_disclosed" regardless of
    # overall retention_state — the overall state captures whether ANY metric
    # was disclosed (NRR present alone shouldn't make GRR look "disclosed").
    return 0.0, {
        "value": None,
        "band": "not_disclosed",
        "points": 0.0,
        "max_points": GRR_MAX,
        "state": "not_disclosed",
    }, None
