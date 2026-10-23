"""
F1 — Pre-Discovery Alpha Framework.

Composes seven academic signals into a single 0-10 score:

  1. Piotroski F-Score (Piotroski 2000)               9 binary signals
  2. Sloan Accruals quality check (Sloan 1996)        accruals_ratio sign
  3. Novy-Marx Gross Profitability (Novy-Marx 2013)   gp/a level
  4. Lakonishok-Lee Insider Cluster (LakLee 2001)     ≥3 unique P-buys / 90d
  5. Hong-Lim-Stein Analyst Neglect (HLS 2000)        analyst_count ≤ 3
  6. Cooper-Gulen-Schill Asset Growth (CGS 2008)      <5% positive, >25% disqualifies
  7. Bradshaw-Richardson-Sloan Ext. Financing flag    SKIPPED in v1

Frameworks consume `CompanyDataReader` (read-only). They never raise on
missing optional inputs — gaps go onto `FrameworkResult.data_gaps`.

`InsufficientHistoryError` is raised only when YoY Piotroski cannot be
computed (i.e. <2 annual periods). The orchestrator catches that and
flags the framework as "unfeasible" rather than failing the whole dive.

The PROJECT_SPEC reference: docs/methodology/PROJECT_SPEC.md §F1.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
)


# Per-framework data needs — used by the orchestrator to compute the minimum
# data superset before fetching. F1 needs only 2 annual periods (YoY signals).
DATA_REQUIREMENT = DataRequirement(
    annual_years=2,
    quarterly_count=4,
    needs_insider_transactions=True,
    needs_analyst_coverage=True,
)


# ── Tunables (per PROJECT_SPEC §F1) ───────────────────────────────────────

INSIDER_CLUSTER_WINDOW_DAYS: int = 90
INSIDER_CLUSTER_THRESHOLD: int = 3      # ≥ 3 unique insiders → cluster signal

NEGLECT_ANALYST_THRESHOLD: int = 3      # ≤ 3 analysts → neglect premium

ASSET_GROWTH_DISQUALIFY: float = 0.25   # >25% YoY assets growth = top decile / disqualify
ASSET_GROWTH_POSITIVE_BAND: float = 0.05  # <5% YoY = bottom decile / positive

GP_A_TARGET: float = 0.20               # gross_profit / total_assets target (≈top 40% sector)


# Component weights when assembling the 0-10 composite. Piotroski carries the
# bulk weight because it has 9 sub-signals; the other components add 0.5-1.5
# each. Sum of max points = 10.0.
PIOTROSKI_MAX_POINTS: float = 6.0       # 0-9 Piotroski → 0-6 contribution
SLOAN_MAX_POINTS: float = 1.0           # accruals quality bonus
GP_A_MAX_POINTS: float = 1.0            # gross profitability bonus
INSIDER_MAX_POINTS: float = 0.5         # cluster signal bonus
NEGLECT_MAX_POINTS: float = 0.5         # neglect premium bonus
ASSET_GROWTH_MAX_POINTS: float = 1.0    # CGS bonus / penalty


async def score_f1(ticker: str, reader: Any) -> FrameworkResult:
    """Compute F1 — Pre-Discovery Alpha score for `ticker`.

    `reader` is a `CompanyDataReader`. We never call EDGAR / yfinance from
    inside a score function — all data must already be persisted (Phase 1
    of the dive pipeline filled it in).
    """
    annuals = reader.annuals(last_n=3)
    if len(annuals) < 2:
        raise InsufficientHistoryError("F1", needed=2, got=len(annuals), period_kind="annual")

    current = annuals[0]                # most recent annual
    prior = annuals[1]                  # one year back
    prior2 = annuals[2] if len(annuals) >= 3 else None

    signals: dict[str, Any] = {}
    data_gaps: list[str] = []

    # ── 1. Piotroski F-Score ──────────────────────────────────────────────
    f_score, piotroski_signals, piotroski_gaps = _compute_piotroski(
        ticker, current, prior, prior2,
    )
    signals["piotroski"] = piotroski_signals
    signals["piotroski_score"] = f_score
    data_gaps.extend(piotroski_gaps)

    # ── 2. Sloan accruals quality (already computed on Financial row) ────
    sloan_signal, sloan_gap = _compute_sloan(current)
    signals["sloan_accruals_ratio"] = current.accruals_ratio
    signals["sloan_high_quality"] = sloan_signal
    if sloan_gap:
        data_gaps.append(sloan_gap)

    # ── 3. Novy-Marx GP/A ────────────────────────────────────────────────
    gp_a_signal, gp_a_signals_dict, gp_a_gap = _compute_gp_a(ticker, current)
    signals["gp_a"] = current.gp_a
    signals["gp_a_strong"] = gp_a_signal
    signals["gp_a_peer"] = gp_a_signals_dict
    if gp_a_gap:
        data_gaps.append(gp_a_gap)

    # ── 4. Insider cluster (Lakonishok-Lee) ──────────────────────────────
    insider_signal, insider_signals_dict = _compute_insider_cluster(reader)
    signals["insider"] = insider_signals_dict

    # ── 5. Analyst neglect (Hong-Lim-Stein) ──────────────────────────────
    neglect_signal, neglect_signals_dict, neglect_gap = _compute_neglect(reader)
    signals["analyst"] = neglect_signals_dict
    if neglect_gap:
        data_gaps.append(neglect_gap)

    # ── 6. Asset growth (Cooper-Gulen-Schill) ────────────────────────────
    asset_growth_pts, asset_growth_signals = _compute_asset_growth(current, prior)
    signals["asset_growth"] = asset_growth_signals
    disqualified_for_asset_growth = asset_growth_signals.get("disqualified", False)

    # ── Composite assembly (0–10) ────────────────────────────────────────
    score = 0.0
    score += (f_score / 9.0) * PIOTROSKI_MAX_POINTS
    if sloan_signal is True:
        score += SLOAN_MAX_POINTS
    if gp_a_signal is True:
        score += GP_A_MAX_POINTS
    if insider_signal is True:
        score += INSIDER_MAX_POINTS
    if neglect_signal is True:
        score += NEGLECT_MAX_POINTS
    score += asset_growth_pts            # ASSET_GROWTH_MAX_POINTS down to 0

    score = round(min(max(score, 0.0), 10.0), 2)

    # CGS top-decile is a HARD disqualifier per PROJECT_SPEC. Override score.
    if disqualified_for_asset_growth:
        notes = (
            "Asset growth >25% YoY (top decile) — Cooper-Gulen-Schill 2008 "
            "disqualifier. Score capped."
        )
        score = min(score, 3.0)
    else:
        notes = ""

    verdict = "strong_fit" if score >= 7.0 else "partial" if score >= 4.0 else "fail"

    return FrameworkResult(
        framework="F1",
        score=score,
        max_score=10.0,
        signals=signals,
        verdict=verdict,
        data_gaps=data_gaps,
        notes=notes,
    )


# ── 1. Piotroski F-Score ────────────────────────────────────────────────────


def _compute_piotroski(
    ticker: str, current: Any, prior: Any, prior2: Any | None,
) -> tuple[int, dict[str, Any], list[str]]:
    """9 binary signals per Piotroski 2000. Returns (score, signals, data_gaps).

    Conventions matching PROJECT_SPEC §F1:
      P1 ROA > 0
      P2 Operating CF > 0
      P3 ROA increased YoY
      P4 OCF/Assets > NI/Assets (low accruals)
      L5 Long-term debt ratio decreased YoY
      L6 Current ratio increased YoY
      L7 Shares outstanding flat (≤ 2% increase)
      O8 Gross margin increased YoY
      O9 Asset turnover increased YoY

    Signals that can't be computed because input is missing are recorded as
    `None` and contribute 0 to the score (Piotroski's binary design treats
    "not improved" the same as "missing"; we surface the missingness via
    data_gaps so the consumer knows).
    """
    gaps: list[str] = []
    s: dict[str, Any] = {}

    # P1: ROA > 0
    p1 = _pos(_safe_div(current.net_income, current.total_assets))
    s["P1_roa_positive"] = p1
    if p1 is None:
        gaps.append(f"{ticker}: F1 P1 missing — net_income/total_assets")

    # P2: Operating CF > 0
    p2 = _pos(current.operating_cash_flow)
    s["P2_ocf_positive"] = p2
    if p2 is None:
        gaps.append(f"{ticker}: F1 P2 missing — operating_cash_flow")

    # P3: ROA increasing YoY
    roa_curr = _safe_div(current.net_income, current.total_assets)
    roa_prior = _safe_div(prior.net_income, prior.total_assets)
    if roa_curr is not None and roa_prior is not None:
        s["P3_roa_increasing"] = roa_curr > roa_prior
    else:
        s["P3_roa_increasing"] = None
        gaps.append(f"{ticker}: F1 P3 missing — ROA YoY needs both periods")

    # P4: low accruals — OCF/Assets > NI/Assets, equivalent to (OCF - NI) > 0
    if current.operating_cash_flow is not None and current.net_income is not None:
        s["P4_accruals_low"] = (current.operating_cash_flow > current.net_income)
    else:
        s["P4_accruals_low"] = None
        gaps.append(f"{ticker}: F1 P4 missing — accruals comparison")

    # L5: long-term debt ratio (LT debt / total_assets) decreased YoY.
    # Edge case: a company with NO long-term debt (genuinely debt-free, not
    # data-missing) carries debt_ratio = 0 in both periods — leverage is not
    # deteriorating, so L5 should pass. We distinguish "both None" (debt-
    # free) from "only one None" (real gap) by checking total_assets exists
    # for both periods. If total_assets is present but long_term_debt is
    # None, we coerce to 0.0 (debt-free interpretation).
    if current.total_assets and prior.total_assets:
        lt_curr_val = current.long_term_debt or 0.0
        lt_prior_val = prior.long_term_debt or 0.0
        lt_curr = lt_curr_val / current.total_assets
        lt_prior = lt_prior_val / prior.total_assets
        s["L5_lt_debt_decreasing"] = lt_curr <= lt_prior
    else:
        s["L5_lt_debt_decreasing"] = None
        gaps.append(f"{ticker}: F1 L5 missing — total_assets")

    # L6: current ratio increased YoY
    cr_curr = _safe_div(current.current_assets, current.current_liabilities)
    cr_prior = _safe_div(prior.current_assets, prior.current_liabilities)
    if cr_curr is not None and cr_prior is not None:
        s["L6_current_ratio_up"] = cr_curr > cr_prior
    else:
        s["L6_current_ratio_up"] = None
        gaps.append(f"{ticker}: F1 L6 missing — current_assets/liabilities")

    # L7: shares outstanding flat (≤2% increase = no dilution penalty)
    if current.shares_outstanding is not None and prior.shares_outstanding:
        s["L7_no_new_shares"] = (
            current.shares_outstanding <= prior.shares_outstanding * 1.02
        )
    else:
        s["L7_no_new_shares"] = None
        gaps.append(f"{ticker}: F1 L7 missing — shares_outstanding")

    # O8: gross margin increased YoY
    gm_curr = current.gross_margin
    gm_prior = prior.gross_margin
    if gm_curr is not None and gm_prior is not None:
        s["O8_gross_margin_up"] = gm_curr > gm_prior
    else:
        s["O8_gross_margin_up"] = None
        gaps.append(f"{ticker}: F1 O8 missing — gross_margin")

    # O9: asset turnover increased YoY
    at_curr = _safe_div(current.revenue, current.total_assets)
    at_prior = _safe_div(prior.revenue, prior.total_assets)
    if at_curr is not None and at_prior is not None:
        s["O9_asset_turnover_up"] = at_curr > at_prior
    else:
        s["O9_asset_turnover_up"] = None
        gaps.append(f"{ticker}: F1 O9 missing — asset_turnover")

    # Sum binary True signals (None counts as 0)
    f_score = sum(1 for k, v in s.items() if v is True)
    return f_score, s, gaps


# ── 2. Sloan accruals ───────────────────────────────────────────────────────


def _compute_sloan(current: Any) -> tuple[bool | None, str | None]:
    """Sloan accruals: negative ratio = HIGH QUALITY (cash > GAAP earnings).

    Returns (signal, gap_string_or_None). signal is True when accruals are
    "low / negative" by Sloan's definition.
    """
    ratio = current.accruals_ratio
    if ratio is None:
        return None, "F1 Sloan: accruals_ratio missing"
    return (ratio <= 0), None


# ── 3. Novy-Marx GP/A ───────────────────────────────────────────────────────


def _compute_gp_a(
    ticker: str,
    current: Any,
) -> tuple[bool | None, dict[str, Any], str | None]:
    """Novy-Marx (2013): GP/A = gross_profit / total_assets.

    Sector-percentile ranking (Tier 2.5 upgrade 2026-05-15): primary path
    uses SEC frames cross-sectional data filtered by SIC code prefix to
    compute the actual peer percentile. "Top tercile" = P67+ within the
    ticker's same-2-digit-SIC peer group (Novy-Marx 2013 §3 — relative
    quality is the signal, not absolute).

    Fallback: when SEC frames unavailable OR ticker has no SIC code
    persisted, use absolute threshold of 0.20 (~ top-40% across the
    broad universe — the original behaviour).

    Signal: True when ticker is in top tercile of SIC peer group, OR
    (fallback) when GP/A >= 0.20 absolute.
    """
    g = current.gp_a
    if g is None:
        return None, {}, "F1 GP/A: gp_a missing"

    signals: dict[str, Any] = {
        "gp_a_absolute": g,
        "method": "absolute_threshold",
    }

    # Tier 2.5 primary path: SIC-filtered peer percentile from SEC frames
    try:
        from sqlalchemy import select
        from data.db import SessionLocal
        from data.models.schema import Company
        from data.sec_frames import (
            build_sic_lookup_from_db,
            fetch_frame,
            get_percentile_rank,
        )

        with SessionLocal() as s:
            c = s.execute(
                select(Company).where(Company.ticker == ticker)
            ).scalar_one_or_none()
            if c is None or c.sic_code is None or c.cik is None:
                raise RuntimeError("no SIC code persisted")
            sic_str = str(c.sic_code).zfill(4)
            try:
                cik_int = int(c.cik.lstrip("0") or "0")
            except ValueError:
                raise RuntimeError("invalid CIK")

        # Derive the calendar period from the Financial row's period_end_date.
        # SEC frames are calendar-year-keyed; for non-December-FYE filers
        # (NVDA/LULU/MRVL Jan FYE, AAPL legacy June FYE) the fiscal year
        # mostly falls in the PRIOR calendar year. Try the period_end.year
        # first, then year-1 as fallback.
        period_end = getattr(current, "period_end_date", None)
        if period_end is None:
            raise RuntimeError("no period_end_date on current Financial row")

        ds_gp = None
        ds_assets = None
        period = None
        for year_candidate in (period_end.year, period_end.year - 1):
            period_try = f"CY{year_candidate}"
            period_instant_try = f"CY{year_candidate}Q4I"
            gp_try = fetch_frame("GrossProfit", period_try)
            assets_try = fetch_frame("Assets", period_instant_try)
            # Both must exist AND target CIK must be present in both
            if gp_try and assets_try:
                if cik_int in gp_try.by_cik() and cik_int in assets_try.by_cik():
                    ds_gp = gp_try
                    ds_assets = assets_try
                    period = period_try
                    break
        if ds_gp is None or ds_assets is None:
            raise RuntimeError(
                f"frames unavailable for {period_end.year} or {period_end.year - 1}"
            )

        sic_lookup = build_sic_lookup_from_db()
        # Prefer 2-digit SIC sector for a broader peer set (more
        # statistically meaningful); fall back to 4-digit if 2-digit
        # yields too few peers.
        for sic_prefix, label in [
            (sic_str[:2], "SIC 2-digit"),
            (sic_str, "SIC 4-digit (exact)"),
        ]:
            rank = get_percentile_rank(
                target_cik=cik_int,
                dataset_num=ds_gp,
                dataset_den=ds_assets,
                sic_lookup=sic_lookup,
                sic_prefix=sic_prefix,
                min_peer_count=8,
            )
            if rank is not None:
                # Top tercile = P67+
                top_tercile = rank["percentile"] >= 66.67
                signals.update({
                    "method": f"sic_filtered_percentile ({label}={sic_prefix})",
                    "peer_count": rank["peer_count"],
                    "percentile": round(rank["percentile"], 1),
                    "peer_median_gp_a": round(rank["median"], 4),
                    "top_tercile": top_tercile,
                    "sic_code": c.sic_code,
                    "period": period,
                })
                return top_tercile, signals, None
    except Exception as exc:
        logger.debug("SIC-filtered GP/A failed for %s: %s — using fallback", ticker, exc)
        signals["method"] = f"absolute_threshold (sic-filter failed: {type(exc).__name__})"

    # Fallback: absolute threshold
    return (g >= GP_A_TARGET), signals, None


# ── 4. Insider cluster ──────────────────────────────────────────────────────


def _compute_insider_cluster(reader: Any) -> tuple[bool, dict[str, Any]]:
    """Lakonishok-Lee (2001): ≥3 unique insiders with open-market PURCHASES
    in the last 90 days = bullish cluster.

    Reads from `insider_transactions` table; relies on ADR-018 D5's
    `transaction_type='P'` (SEC Form 4 code) being correctly populated.
    """
    txns = reader.insider_transactions(
        within_days=INSIDER_CLUSTER_WINDOW_DAYS,
        open_market_only=True,
        transaction_codes=("P",),
    )
    unique_buyers = {
        (t.insider_name or "").strip().lower()
        for t in txns
        if (t.insider_name or "").strip()
    }
    n_unique = len(unique_buyers)
    n_txns = len(txns)
    cluster = n_unique >= INSIDER_CLUSTER_THRESHOLD
    return cluster, {
        "purchase_txns_90d": n_txns,
        "unique_buyers_90d": n_unique,
        "cluster_threshold": INSIDER_CLUSTER_THRESHOLD,
        "cluster_signal": cluster,
    }


# ── 5. Analyst neglect ──────────────────────────────────────────────────────


def _compute_neglect(reader: Any) -> tuple[bool | None, dict[str, Any], str | None]:
    """Hong-Lim-Stein (2000): low analyst coverage → neglect premium.

    Threshold: ≤ 3 analysts. Returns None when no analyst row exists at
    all (caller emits a data gap).
    """
    row = reader.latest_analyst_coverage()
    if row is None or row.analyst_count is None:
        return None, {"analyst_count": None}, "F1 neglect: no analyst_coverage row"
    count = int(row.analyst_count)
    return (
        count <= NEGLECT_ANALYST_THRESHOLD,
        {"analyst_count": count, "neglect_threshold": NEGLECT_ANALYST_THRESHOLD},
        None,
    )


# ── 6. Asset growth (Cooper-Gulen-Schill) ───────────────────────────────────


def _compute_asset_growth(
    current: Any, prior: Any,
) -> tuple[float, dict[str, Any]]:
    """CGS (2008): top-decile asset growth (>25% YoY) is a strong negative
    predictor; bottom-decile (<5% positive) is favourable.

    Returns (points_to_add, signals_dict). Points scale:
      growth > 25%  → 0 points + disqualified flag
      growth ≥ 15%  → 0 points
      growth ≥ 5%   → 0.5 points
      growth ≥ 0    → 1.0 points (favourable, low-growth)
      growth < 0    → 0.5 points (asset shrinkage; not as good as low-positive)
    """
    if (
        current.total_assets is None
        or prior.total_assets is None
        or prior.total_assets == 0
    ):
        return 0.0, {"asset_growth_yoy": None, "disqualified": False}

    g = (current.total_assets - prior.total_assets) / prior.total_assets

    if g > ASSET_GROWTH_DISQUALIFY:
        pts = 0.0
        disq = True
    elif g >= 0.15:
        pts = 0.0
        disq = False
    elif g >= ASSET_GROWTH_POSITIVE_BAND:
        pts = 0.5
        disq = False
    elif g >= 0.0:
        pts = ASSET_GROWTH_MAX_POINTS
        disq = False
    else:
        pts = 0.5
        disq = False

    return pts, {
        "asset_growth_yoy": round(g, 4),
        "disqualified": disq,
        "decile_band": "top_decile" if disq else (
            "moderate" if g >= 0.15 else
            "low_positive" if g >= ASSET_GROWTH_POSITIVE_BAND else
            "bottom_decile" if g >= 0 else "shrinking"
        ),
    }


# ── helpers ────────────────────────────────────────────────────────────────


def _safe_div(num: Any, den: Any) -> float | None:
    if num is None or den is None or den == 0:
        return None
    try:
        return float(num) / float(den)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _pos(x: Any) -> bool | None:
    if x is None:
        return None
    try:
        return float(x) > 0
    except (TypeError, ValueError):
        return None
