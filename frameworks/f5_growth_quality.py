"""
F5 — Growth Quality + Capital Allocation.

Seven academic signals combine to a 0-10 score:

  1. Revenue CAGR 3-year                                     1.5 points
     >10% sustained = quality compounder. Needs 4 annuals (3 deltas).

  2. FCF margin                                              1.5 points
     free_cash_flow / revenue > 20% = capital-efficient. The Fastenal /
     Visa shape.

  3. ROIC (primary capital-efficiency signal)                2.0 points
     >15% over the latest annual. Per PROJECT_SPEC §F5 the formula is
     NOPAT / invested_capital. We use the simpler net_income / (equity+
     debt) already computed on Financial.roic for v1; sector-specific
     refinement is deferred. ICA overlay trigger flagged in signals
     dict but no overlay framework yet — overlay layer is Phase 5.

  4. Novy-Marx GP/A (validated quality factor)               1.0 points
     gross_profit / total_assets > 0.20 = top-40% sector proxy.
     Same signal F1 uses; weighted differently here (F1 is
     pre-discovery; F5 is established-quality).

  5. Debt/EBITDA                                             1.0 points
     <2.0 = healthy leverage. Debt-free companies (no interest expense)
     get full points.

  6. Buyback yield                                           1.0 points
     share_repurchases_ttm / market_cap. 2-5% sweet spot per spec
     (heuristic). Companies that can afford buybacks AND aren't
     over-buying.

  7. CEO checklist (Fahlenbrach 2009)                        2.0 points
     Founder-CEO with >5% equity OR tenure ≥ 5 years. Uses ADR-018 D2
     (ceo_equity_pct) and D3 (is_founder_ceo). Honors `parser_uncertain`
     state by giving partial credit.

Total = 10.0 points.
"""
from __future__ import annotations

from typing import Any

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
)

DATA_REQUIREMENT = DataRequirement(
    annual_years=4,                       # 3yr CAGR needs 4 annuals
    quarterly_count=4,                    # TTM derivation (ADR-026)
    needs_proxy_ownership=True,           # CEO equity stake
    needs_founder_status=True,            # CEO alignment
    needs_arr_metrics=True,               # ADR-026 5Q-5: Cloud ARR / Total ARR
)


# ── Tunables (per PROJECT_SPEC §F5) ───────────────────────────────────────

CAGR_TARGET_3YR = 0.10
CAGR_PARTIAL_3YR = 0.05

FCF_MARGIN_TARGET = 0.20
FCF_MARGIN_PARTIAL = 0.10

ROIC_TARGET = 0.15
ROIC_PARTIAL = 0.10
ROIC_FLOOR = 0.0                  # below this is bad
ICA_OVERLAY_RD_INTENSITY = 0.10   # F5 flags ICA overlay candidate when

GP_A_TARGET = 0.20

DEBT_EBITDA_HEALTHY = 2.0
DEBT_EBITDA_ACCEPTABLE = 4.0

BUYBACK_YIELD_SWEET_LO = 0.02
BUYBACK_YIELD_SWEET_HI = 0.05

CEO_TENURE_THRESHOLD_YEARS = 5.0
CEO_EQUITY_THRESHOLD = 0.05       # 5% per Fahlenbrach


CAGR_MAX = 1.5
FCF_MARGIN_MAX = 1.5
ROIC_MAX = 2.0
GP_A_MAX = 1.0
DEBT_MAX = 1.0
BUYBACK_MAX = 1.0
CEO_MAX = 2.0


async def score_f5(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F5 — Growth Quality score.

    ADR-026 (Phase 5Q-6): current-state ratios (FCF margin, ROIC, GP/A,
    Debt/EBITDA) now sourced from LTM (rolling-4-quarters) when available,
    falling back to the latest annual when fewer than 4 quarters exist.
    Revenue CAGR stays on annuals (multi-year trajectory). Buyback yield
    stays on annuals (year-over-year comparison). CEO checklist reads
    from the Company row.
    """
    annuals = reader.annuals(last_n=4)
    if len(annuals) < 2:
        raise InsufficientHistoryError(
            "F5", needed=2, got=len(annuals), period_kind="annual"
        )

    annual_current = annuals[0]
    ttm = reader.ttm()    # may be None for recent IPOs with <4 quarters
    # current_state is used for ratio signals; trajectory keeps annuals
    current_state = ttm if ttm is not None else annual_current
    source_tag = "LTM" if ttm is not None else "FY annual"
    company = reader.company_or_none()

    signals: dict[str, Any] = {}
    data_gaps: list[str] = []
    overlay_triggers: list[str] = []

    # ── 1. Revenue CAGR 3yr (annual trajectory — keep as annuals) ────────
    cagr_pts, cagr_signals, cagr_gap = _compute_cagr(annuals, ticker)
    signals["revenue_cagr_3yr"] = cagr_signals
    if cagr_gap:
        data_gaps.append(cagr_gap)

    # ── 2. FCF margin (current state — LTM) ──────────────────────────────
    fcf_pts, fcf_signals, fcf_gap = _compute_fcf_margin(current_state, ticker)
    fcf_signals["source"] = source_tag
    signals["fcf_margin"] = fcf_signals
    if fcf_gap:
        data_gaps.append(fcf_gap)

    # ── 3. ROIC + ICA overlay trigger (current state — LTM) ──────────────
    roic_pts, roic_signals, ica_trigger, roic_gap = _compute_roic(current_state, ticker)
    roic_signals["source"] = source_tag
    signals["roic"] = roic_signals
    if roic_gap:
        data_gaps.append(roic_gap)
    if ica_trigger:
        overlay_triggers.append("ICA")

    # ── 4. Novy-Marx GP/A (current state — LTM) ──────────────────────────
    gp_pts, gp_signals, gp_gap = _compute_gp_a(current_state, ticker)
    gp_signals["source"] = source_tag
    signals["gp_a"] = gp_signals
    if gp_gap:
        data_gaps.append(gp_gap)

    # ── 5. Debt/EBITDA (current state — LTM) ─────────────────────────────
    debt_pts, debt_signals, debt_gap = _compute_debt_ebitda(current_state, ticker)
    debt_signals["source"] = source_tag
    signals["debt_ebitda"] = debt_signals
    if debt_gap:
        data_gaps.append(debt_gap)

    # ── 6. Buyback yield ─────────────────────────────────────────────────
    # Buyback yield stays on annuals — year-over-year share-repurchase
    # comparison is the meaningful signal, not LTM.
    buyback_pts, buyback_signals, buyback_gap = _compute_buyback_yield(annual_current, ticker)
    signals["buyback_yield"] = buyback_signals
    if buyback_gap:
        data_gaps.append(buyback_gap)

    # ── 7. CEO checklist ─────────────────────────────────────────────────
    ceo_pts, ceo_signals, ceo_gap = _compute_ceo_checklist(company, ticker)
    signals["ceo_checklist"] = ceo_signals
    if ceo_gap:
        data_gaps.append(ceo_gap)

    # ── ARR disclosure (ADR-026 5Q-5 — display only, not scoring) ────────
    # Cloud ARR is the forward-looking SaaS commitment metric. We surface
    # it here for transparency; banding/scoring it requires a calibration
    # study (best-in-class Cloud ARR growth thresholds by company size)
    # that isn't in scope for ADR-026 v1.
    arr_signals = {
        "cloud_arr_usd": annual_current.cloud_arr_usd if annual_current.cloud_arr_usd else None,
        "cloud_arr_growth_yoy_pct": annual_current.cloud_arr_growth_yoy_pct,
        "total_arr_usd": annual_current.total_arr_usd if annual_current.total_arr_usd else None,
        "total_arr_growth_yoy_pct": annual_current.total_arr_growth_yoy_pct,
        "state": annual_current.arr_state or "not_disclosed",
        "source": (
            "10-Q MD&A (freshest disclosure)"
            if annual_current.arr_state == "disclosed_exact" else "n/a"
        ),
    }
    signals["arr_disclosure"] = arr_signals

    # ── Phase 5R-2: data-quality signals (display only, not scoring) ─────
    # SBC intensity, goodwill concentration, share dilution. Each is
    # surfaced as a discrete signal with a banded interpretation so the
    # reader can apply the latticework (Mauboussin SBC = real cost;
    # Outsiders capital-allocator inversion; serial-acquirer flag) without
    # the system pretending it's a calibrated numeric score.
    signals["sbc_intensity"] = _compute_sbc_intensity(annual_current)
    signals["goodwill_concentration"] = _compute_goodwill_concentration(annual_current)
    signals["share_dilution"] = _compute_share_dilution(annuals)
    # Phase 5S-4: trajectory needs both current LTM AND prior LTM (the 12
    # months immediately preceding the current LTM window) to compute a
    # meaningful YoY growth comparison. The pre-5S-4 calc
    # `(LTM − latest_FY) / latest_FY` was meaningless when LTM and FY share
    # 9-12 months of overlap — it measured the one-quarter delta as a % of
    # the full year, giving NVDA "0% growth" when 0 fresh quarters past FY
    # existed, and HIMS 0.9% when only 1 fresh quarter was past FY.
    #
    # Prior-LTM anchoring: `as_of = ttm.period_start_date − 1 day` finds
    # the 4 quarters ending immediately BEFORE the current LTM window starts.
    # Naive `period_end − 365 days` fails on fiscal calendars where quarter
    # ends shift by ±1-2 days year-over-year (NVDA Q4 FY25 ended Jan 26 2025
    # but `Jan 25 2026 − 365 days` lands on Jan 25 2025, excluding it and
    # producing a misleadingly inflated YoY).
    prior_ttm: Any | None = None
    if ttm is not None and getattr(ttm, "period_start_date", None) is not None:
        from datetime import timedelta as _td
        prior_ttm = reader.ttm_at(as_of=ttm.period_start_date - _td(days=1))
    signals["revenue_trajectory"] = _compute_revenue_trajectory(annuals, ttm, prior_ttm)

    score = round(
        cagr_pts + fcf_pts + roic_pts + gp_pts + debt_pts + buyback_pts + ceo_pts,
        2,
    )
    score = min(max(score, 0.0), 10.0)
    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    return FrameworkResult(
        framework="F5",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
        overlay_triggers=overlay_triggers,
    )


# ── 1. Revenue CAGR 3yr ───────────────────────────────────────────────────


def _compute_cagr(
    annuals: list[Any], ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    if len(annuals) < 4:
        return 0.0, {
            "n_periods": len(annuals),
            "cagr_3yr": None,
            "points": 0.0,
        }, f"{ticker}: F5 CAGR — need 4 annuals, have {len(annuals)}"
    current = annuals[0]
    three_back = annuals[3]
    if not current.revenue or not three_back.revenue or three_back.revenue <= 0:
        return 0.0, {
            "current_revenue": current.revenue,
            "three_back_revenue": three_back.revenue,
            "cagr_3yr": None,
            "points": 0.0,
        }, f"{ticker}: F5 CAGR — missing revenue data"
    cagr = (current.revenue / three_back.revenue) ** (1.0 / 3.0) - 1.0
    if cagr >= CAGR_TARGET_3YR:
        pts = CAGR_MAX
        band = "strong"
    elif cagr >= CAGR_PARTIAL_3YR:
        pts = 1.0
        band = "moderate"
    elif cagr >= 0.0:
        pts = 0.5
        band = "slow"
    else:
        pts = 0.0
        band = "shrinking"
    return pts, {
        "current_fy": current.fiscal_year,
        "three_back_fy": three_back.fiscal_year,
        "current_revenue": current.revenue,
        "three_back_revenue": three_back.revenue,
        "cagr_3yr": round(cagr, 4),
        "band": band,
        "points": pts,
    }, None


# ── 2. FCF margin ─────────────────────────────────────────────────────────


def _compute_fcf_margin(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    if current.fcf_margin is None:
        if current.free_cash_flow is None:
            return 0.0, {
                "fcf_margin": None,
                "free_cash_flow": None,
                "points": 0.0,
            }, f"{ticker}: F5 FCF margin — no free_cash_flow"
        if not current.revenue or current.revenue == 0:
            return 0.0, {
                "fcf_margin": None,
                "free_cash_flow": current.free_cash_flow,
                "points": 0.0,
            }, f"{ticker}: F5 FCF margin — no revenue"
        m = current.free_cash_flow / current.revenue
    else:
        m = current.fcf_margin

    if m >= FCF_MARGIN_TARGET:
        pts = FCF_MARGIN_MAX
        band = "elite"
    elif m >= FCF_MARGIN_PARTIAL:
        pts = 1.0
        band = "healthy"
    elif m >= 0:
        pts = 0.5
        band = "thin_positive"
    else:
        pts = 0.0
        band = "negative"

    return pts, {
        "fcf_margin": round(m, 4),
        "free_cash_flow": current.free_cash_flow,
        "revenue": current.revenue,
        "band": band,
        "points": pts,
    }, None


# ── 3. ROIC + ICA overlay trigger ─────────────────────────────────────────


def _compute_roic(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], bool, str | None]:
    """ROIC > 15% target. Trigger ICA overlay when ROIC < 15% AND R&D
    intensity > 10% (intangible-heavy company under-reporting capital).
    """
    roic = current.roic
    if roic is None:
        return 0.0, {
            "roic": None, "points": 0.0, "ica_trigger": False,
        }, False, f"{ticker}: F5 ROIC — no value computed"

    if roic >= ROIC_TARGET:
        pts = ROIC_MAX
        band = "strong"
    elif roic >= ROIC_PARTIAL:
        pts = 1.5
        band = "acceptable"
    elif roic >= ROIC_FLOOR:
        pts = 0.5
        band = "weak"
    else:
        pts = 0.0
        band = "negative"

    # ICA overlay trigger (per PROJECT_SPEC): ROIC < 15% with high R&D
    ica_trigger = (
        roic < ROIC_TARGET
        and (current.rd_intensity or 0) > ICA_OVERLAY_RD_INTENSITY
    )

    return pts, {
        "roic": round(roic, 4),
        "rd_intensity": current.rd_intensity,
        "band": band,
        "ica_trigger": ica_trigger,
        "points": pts,
    }, ica_trigger, None


# ── 4. Novy-Marx GP/A ─────────────────────────────────────────────────────


def _compute_gp_a(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    g = current.gp_a
    if g is None:
        return 0.0, {"gp_a": None, "points": 0.0}, f"{ticker}: F5 GP/A — no value"
    if g >= GP_A_TARGET:
        pts = GP_A_MAX
        band = "strong"
    elif g >= GP_A_TARGET * 0.5:
        pts = 0.5
        band = "moderate"
    else:
        pts = 0.0
        band = "weak"
    return pts, {
        "gp_a": round(g, 4),
        "target": GP_A_TARGET,
        "band": band,
        "points": pts,
    }, None


# ── 5. Debt/EBITDA ────────────────────────────────────────────────────────


def _compute_debt_ebitda(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Debt/EBITDA on NET basis (Phase 5S-5): net_debt = total_debt − cash
    − short_term_investments. Companies sitting on more liquid assets than
    debt are net-cash and earn full points regardless of gross debt level
    (the cash neutralises the obligation). <2x = healthy. The pre-5S-5
    gross-debt version reported HIMS as 7x leveraged when economically
    net-cash, and missed NVDA's ~$30B net-cash position entirely."""
    td = current.total_debt or 0
    cash = getattr(current, "cash_and_equivalents", None) or 0
    sti = getattr(current, "short_term_investments", None) or 0
    net_debt = td - cash - sti

    # Debt-free OR net-cash — full points either way. Both mean the balance
    # sheet is not a constraint on the business.
    if td == 0 or net_debt <= 0:
        band = "debt_free" if td == 0 else "net_cash"
        return DEBT_MAX, {
            "total_debt": td,
            "cash_and_equivalents": cash,
            "short_term_investments": sti,
            "net_debt": net_debt,
            "ebitda": current.ebitda,
            "debt_ebitda": 0.0,
            "band": band,
            "points": DEBT_MAX,
        }, None

    if current.ebitda is None or current.ebitda == 0:
        return 0.0, {
            "total_debt": td,
            "cash_and_equivalents": cash,
            "short_term_investments": sti,
            "net_debt": net_debt,
            "ebitda": current.ebitda,
            "debt_ebitda": None,
            "points": 0.0,
        }, f"{ticker}: F5 Debt/EBITDA — no EBITDA"

    if current.ebitda <= 0:
        return 0.0, {
            "total_debt": td,
            "cash_and_equivalents": cash,
            "short_term_investments": sti,
            "net_debt": net_debt,
            "ebitda": current.ebitda,
            "debt_ebitda": None,
            "band": "negative_ebitda",
            "points": 0.0,
        }, None

    ratio = net_debt / current.ebitda
    if ratio < DEBT_EBITDA_HEALTHY:
        pts = DEBT_MAX
        band = "healthy"
    elif ratio < DEBT_EBITDA_ACCEPTABLE:
        pts = 0.5
        band = "elevated"
    else:
        pts = 0.0
        band = "leveraged"

    return pts, {
        "total_debt": td,
        "cash_and_equivalents": cash,
        "short_term_investments": sti,
        "net_debt": net_debt,
        "ebitda": current.ebitda,
        "debt_ebitda": round(ratio, 3),
        "band": band,
        "points": pts,
    }, None


# ── 6. Buyback yield ──────────────────────────────────────────────────────


def _compute_buyback_yield(
    current: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Sweet spot 2-5% per spec heuristic. Persisted as buyback_yield
    on the most-recent annual Financial via pipeline._compute_buyback_yields.
    """
    by = current.buyback_yield
    if by is None:
        return 0.0, {
            "buyback_yield": None,
            "points": 0.0,
        }, f"{ticker}: F5 buyback yield — not persisted (no market_cap or share_repurchases)"

    if BUYBACK_YIELD_SWEET_LO <= by <= BUYBACK_YIELD_SWEET_HI:
        pts = BUYBACK_MAX
        band = "sweet_spot"
    elif by > BUYBACK_YIELD_SWEET_HI:
        pts = 0.5
        band = "aggressive"
    elif 0 < by < BUYBACK_YIELD_SWEET_LO:
        pts = 0.5
        band = "modest"
    else:
        pts = 0.0
        band = "no_buyback"

    return pts, {
        "buyback_yield": round(by, 4),
        "sweet_band": (BUYBACK_YIELD_SWEET_LO, BUYBACK_YIELD_SWEET_HI),
        "band": band,
        "points": pts,
    }, None


# ── 7. CEO checklist (Fahlenbrach) ────────────────────────────────────────


def _compute_ceo_checklist(
    company: Any, ticker: str,
) -> tuple[float, dict[str, Any], str | None]:
    """Fahlenbrach (2009) ★★ — founder-CEO with >5% equity OR tenure ≥ 5yr.

    Honors ADR-018 three-state semantics:
      ceo_equity_pct_state = 'parser_uncertain' (e.g. AAPL <1% sentinel) →
        scored as below-threshold (correct: a sentinel "<1%" never crosses 5%)
      is_founder_ceo_state = 'not_disclosed' → not penalised, just unknown
    """
    if company is None:
        return 0.0, {
            "founder_ceo": None, "ceo_equity_pct": None,
            "ceo_tenure_years": None, "points": 0.0,
        }, f"{ticker}: F5 CEO — no Company row"

    is_founder = company.is_founder_ceo                # True | False | None
    equity_pct = company.ceo_equity_pct                # raw percentage 0-100
    tenure = company.ceo_tenure_years                  # years
    equity_state = company.ceo_equity_pct_state
    founder_state = company.is_founder_ceo_state

    # Convert equity_pct from percentage to ratio for Fahlenbrach threshold
    equity_ratio = (equity_pct / 100.0) if equity_pct is not None else None

    # The Fahlenbrach OR-clause
    founder_with_skin = (
        is_founder is True
        and equity_ratio is not None
        and equity_ratio > CEO_EQUITY_THRESHOLD
    )
    long_tenure = tenure is not None and tenure >= CEO_TENURE_THRESHOLD_YEARS

    # Substantial equity (>5%) is itself a strong skin-in-game signal even
    # when founder status is False or unconfirmed. INTA's John Hall (7.64%)
    # is co-founder per Intapp's history but our parser conservatively
    # returns False because his title doesn't carry "founder". The Fahlenbrach
    # finding tracks alignment-of-interests, which is what the equity-pct
    # primarily captures — give those CEOs the bulk of the points.
    high_equity_alone = (
        equity_ratio is not None and equity_ratio > CEO_EQUITY_THRESHOLD
    )

    if founder_with_skin or long_tenure:
        pts = CEO_MAX
        band = "founder_aligned" if founder_with_skin else "long_tenured"
    elif high_equity_alone:
        # Skin-in-game without founder confirmation OR with disclosed-False
        # founder flag. Still >5% equity = meaningful alignment.
        pts = 1.5
        band = "high_equity_unconfirmed_founder"
    elif (
        (is_founder is True and equity_ratio is not None and equity_ratio > 0.01)
        or (tenure is not None and tenure >= 3.0)
    ):
        pts = 1.0
        band = "partial_alignment"
    else:
        pts = 0.0
        band = "no_alignment"

    return pts, {
        "is_founder_ceo": is_founder,
        "is_founder_ceo_state": founder_state,
        "ceo_equity_pct": equity_pct,
        "ceo_equity_pct_state": equity_state,
        "ceo_equity_ratio": round(equity_ratio, 4) if equity_ratio is not None else None,
        "ceo_tenure_years": tenure,
        "founder_with_skin": founder_with_skin,
        "long_tenure": long_tenure,
        "band": band,
        "points": pts,
    }, None


# ── Phase 5R-2/3: data-quality signal helpers (display-only) ─────────────


# SBC intensity bands. Calibrated against Damodaran / Mauboussin guidance.
_SBC_RED_FLAG = 0.20
_SBC_CONCERNING = 0.10
# Goodwill concentration band. >40% of assets = serial acquirer.
_GOODWILL_HEAVY = 0.40
# Share dilution YoY % thresholds (positive = dilutive).
_DILUTION_HIGH = 0.05
_DILUTION_MEDIUM = 0.02
_BUYBACK_ACCRETIVE = -0.02


def _compute_sbc_intensity(current: Any) -> dict[str, Any]:
    """Surface SBC as % of revenue (Phase 5R-2)."""
    sbc = getattr(current, "share_based_compensation", None)
    pct = getattr(current, "sbc_pct_of_revenue", None)
    if sbc is None or pct is None:
        return {
            "value_usd": None, "pct_of_revenue": None,
            "band": "not_disclosed",
            "note": (
                "ShareBasedCompensation tag not reported; SBC dilution "
                "magnitude cannot be assessed from XBRL"
            ),
        }
    if pct >= _SBC_RED_FLAG:
        band = "red_flag"
        note = (
            "SBC at-or-above 20 percent of revenue is structural dilution. "
            "Damodaran/Mauboussin treat as real recurring cost. F5 ROIC stays "
            "GAAP per ADR-021 but 'real' FCF margin equals reported FCF margin "
            "minus SBC intensity."
        )
    elif pct >= _SBC_CONCERNING:
        band = "concerning"
        note = (
            "SBC 10-20 percent of revenue. Common SaaS profile but monitor. "
            "Headline non-GAAP profitability is materially SBC add-back."
        )
    else:
        band = "healthy"
        note = "SBC below 10 percent of revenue. Normal-range dilution."
    return {
        "value_usd": round(sbc, 0),
        "pct_of_revenue": round(pct * 100, 2),
        "band": band,
        "note": note,
        "thresholds": {
            "red_flag_pct": _SBC_RED_FLAG * 100,
            "concerning_pct": _SBC_CONCERNING * 100,
        },
    }


def _compute_goodwill_concentration(current: Any) -> dict[str, Any]:
    """Surface Goodwill / Total Assets ratio (Phase 5R-2)."""
    gw = getattr(current, "goodwill", None)
    pct = getattr(current, "goodwill_pct_of_assets", None)
    ta = getattr(current, "total_assets", None)
    if gw is None or pct is None:
        return {
            "value_usd": None, "pct_of_assets": None,
            "band": "not_disclosed",
            "note": "Goodwill not on balance sheet (organic-growth filer).",
        }
    if pct >= _GOODWILL_HEAVY:
        band = "serial_acquirer"
        note = (
            "Goodwill at-or-above 40 percent of total assets indicates "
            "serial-acquisition growth. Per Stewart/Mauboussin goodwill "
            "stays in IC (don't strip it). Evaluate M&A discipline via "
            "Outsiders 8-traits test separately."
        )
    elif pct >= 0.15:
        band = "moderate_m_and_a"
        note = "Goodwill 15-40 percent of assets. Moderate M&A history."
    else:
        band = "organic_or_light_m_and_a"
        note = "Goodwill below 15 percent. Primarily organic growth."
    return {
        "value_usd": round(gw, 0),
        "total_assets_usd": round(ta, 0) if ta is not None else None,
        "pct_of_assets": round(pct * 100, 2),
        "band": band,
        "note": note,
    }


def _compute_share_dilution(annuals: list[Any]) -> dict[str, Any]:
    """YoY share dilution rate from annual shares_outstanding series.

    Positive = dilutive (more shares); negative = buyback (fewer shares).
    """
    series = [
        (a.fiscal_year, a.shares_outstanding) for a in annuals
        if a.shares_outstanding is not None
    ]
    if len(series) < 2:
        return {
            "yoy_pct": None, "avg_yoy_pct": None,
            "band": "insufficient_history",
            "note": "Need 2+ annuals with shares_outstanding.",
        }
    yoy_rates: list[float] = []
    for i in range(len(series) - 1):
        new = series[i][1]
        old = series[i + 1][1]
        if old and old > 0:
            yoy_rates.append((new - old) / old)
    if not yoy_rates:
        return {
            "yoy_pct": None, "avg_yoy_pct": None,
            "band": "insufficient_history",
            "note": "Could not compute any YoY share-count change.",
        }
    latest_yoy = yoy_rates[0]
    avg_yoy = sum(yoy_rates) / len(yoy_rates)
    if avg_yoy >= _DILUTION_HIGH:
        band = "high_dilution"
        note = (
            f"Avg net dilution ≥ 5%/yr across {len(yoy_rates)} periods. "
            "Outsiders capital-allocator inversion — buybacks not "
            "keeping up with issuance."
        )
    elif avg_yoy >= _DILUTION_MEDIUM:
        band = "moderate_dilution"
        note = (
            "Avg net dilution 2-5%/yr — monitor whether buybacks "
            "accelerate or issuance slows."
        )
    elif avg_yoy <= _BUYBACK_ACCRETIVE:
        band = "net_accretive"
        note = (
            "Avg net buyback ≥ 2%/yr — Outsiders-aligned, share count "
            "compressing over time."
        )
    else:
        band = "approximately_flat"
        note = "Net share count ±2%/yr — neither materially dilutive nor accretive."
    cumulative_change = (
        ((series[0][1] / series[-1][1]) - 1) if series[-1][1] else None
    )
    return {
        "latest_yoy_pct": round(latest_yoy * 100, 2),
        "avg_yoy_pct": round(avg_yoy * 100, 2),
        "n_periods": len(yoy_rates),
        "shares_latest": series[0][1],
        "shares_earliest": series[-1][1],
        "cumulative_change_pct": (
            round(cumulative_change * 100, 2)
            if cumulative_change is not None else None
        ),
        "band": band,
        "note": note,
    }


def _compute_revenue_trajectory(
    annuals: list[Any],
    ttm: Any | None,
    prior_ttm: Any | None = None,
) -> dict[str, Any]:
    """Detect monotonic revenue-growth deceleration (Phase 5R-3 — Lynch story-break).

    Flag when ≥3 consecutive periods show declining YoY growth rates AND
    latest growth is <70% of earliest in the window.

    Phase 5S-4: the LTM trajectory entry is `(LTM_revenue − prior_LTM_revenue) /
    prior_LTM_revenue` — a true trailing-twelve-month YoY growth rate, not
    the buggy `(LTM − latest_FY) / latest_FY` which compared overlapping
    windows. The old calc gave NVDA 0% (when LTM = FY because no fresh
    quarter was available), and HIMS 0.9% (because LTM and FY shared 9
    months of Q2-Q4 FY25 = the LTM/FY delta was just Q1_FY26 − Q1_FY25
    expressed as % of FY25 total). When `prior_ttm` is unavailable, the
    LTM entry is omitted entirely rather than reporting a misleading value.
    """
    growth_sequence: list[tuple[str, float]] = []
    ann_rev = [
        (a.fiscal_year, a.revenue) for a in reversed(annuals)
        if a.revenue is not None
    ]
    for i in range(1, len(ann_rev)):
        prior_fy, prior_rev = ann_rev[i - 1]
        cur_fy, cur_rev = ann_rev[i]
        if prior_rev and prior_rev > 0:
            growth_sequence.append((f"FY{cur_fy}", (cur_rev - prior_rev) / prior_rev))
    if (
        ttm is not None
        and ttm.revenue
        and prior_ttm is not None
        and getattr(prior_ttm, "revenue", None)
        and prior_ttm.revenue > 0
    ):
        growth_sequence.append((
            "LTM YoY",
            (ttm.revenue - prior_ttm.revenue) / prior_ttm.revenue,
        ))

    if len(growth_sequence) < 3:
        return {
            "growth_sequence": [
                (lbl, round(g * 100, 2)) for lbl, g in growth_sequence
            ],
            "band": "insufficient_history",
            "note": "Need 3+ YoY growth observations to detect deceleration.",
        }

    window = growth_sequence[-4:]
    is_monotonic_decel = all(
        window[i][1] < window[i - 1][1] for i in range(1, len(window))
    )
    earliest_growth = window[0][1]
    latest_growth = window[-1][1]
    earliest_to_latest_ratio = (
        latest_growth / earliest_growth
        if earliest_growth and earliest_growth > 0 else None
    )
    materially_decelerated = (
        earliest_growth > 0 and earliest_to_latest_ratio is not None
        and earliest_to_latest_ratio < 0.70
    )

    if is_monotonic_decel and materially_decelerated:
        band = "decelerating"
        note = (
            f"Growth decelerated monotonically across {len(window)} periods "
            f"({window[0][0]}={window[0][1]*100:.1f}% → "
            f"{window[-1][0]}={window[-1][1]*100:.1f}%). Lynch story-break "
            "candidate."
        )
    elif is_monotonic_decel:
        band = "mildly_decelerating"
        note = (
            "Monotonic deceleration but <30% over window. Could be normal "
            "scaling or early-stage thesis weakness — monitor."
        )
    elif materially_decelerated:
        band = "lumpy_decline"
        note = (
            "Latest growth <70% of earliest, but path was non-monotonic. "
            "Either acquisition-distorted or reversal-after-bounce."
        )
    else:
        band = "stable_or_accelerating"
        note = "Revenue growth pattern not in deceleration territory."
    return {
        "growth_sequence": [(lbl, round(g * 100, 2)) for lbl, g in window],
        "n_periods": len(window),
        "is_monotonic_decel": is_monotonic_decel,
        "earliest_to_latest_ratio": (
            round(earliest_to_latest_ratio, 3)
            if earliest_to_latest_ratio is not None else None
        ),
        "band": band,
        "note": note,
    }
