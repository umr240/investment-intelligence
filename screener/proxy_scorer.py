"""
Proxy scorer — lightweight per-framework scores used during screener ranking.
Avoids full deep-dive computation; uses screener-available signals only.

Each proxy returns a `ProxyScore(raw, confidence, notes)`:
  raw         0.0 – 10.0   coarse score signal
  confidence  0.0 – 1.0    how much we trust it given data availability
  notes       list[str]    diagnostic flags

Composite is weighted: `composite = sum(w_i * raw_i * conf_i) / sum(w_i * conf_i)`.
This NORMALISES for missing data — a ticker with patchy F4 history won't have
its F4 score zero out the composite; instead the F4 weight effectively shrinks.

Mode weights come from `config/constants.py:WEIGHTS_B / WEIGHTS_C`. We use
the `mid_cap` slice as the default for screener-time ranking; full mode-aware
weighting belongs in the dive (where company_stage is known).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from config.constants import (
    F1_GP_A_PERCENTILE_MIN,
    F2_52WK_HIGH_PROXIMITY,
    F3_GM_EXPANSION_MIN,
    F3_RD_INTENSITY_MAX,
    F3_RD_INTENSITY_MIN,
    F5_BUYBACK_YIELD_MIN,
    F5_DEBT_EBITDA_MAX,
    F5_FCF_MARGIN_MIN,
    F5_REVENUE_CAGR_MIN,
    F5_ROIC_MIN,
    WEIGHTS_B,
    WEIGHTS_C,
)
from data.reader import CompanyDataReader

logger = logging.getLogger(__name__)


@dataclass
class ProxyScore:
    framework: str
    raw: float
    confidence: float
    notes: list[str] = field(default_factory=list)

    @property
    def weighted(self) -> float:
        return self.raw * self.confidence


# ── Public entrypoints ───────────────────────────────────────────────────


def compute_all_proxies(
    ticker: str,
    asset_growth_decile: int | None = None,
    momentum_decile: int | None = None,
) -> dict[str, ProxyScore]:
    """Compute lightweight proxy scores for all 7 frameworks."""
    reader = CompanyDataReader(ticker)
    return {
        "F1": _proxy_f1(reader, asset_growth_decile),
        "F2": _proxy_f2(reader, momentum_decile),
        "F3": _proxy_f3(reader),
        "F4": _proxy_f4(reader),
        "F5": _proxy_f5(reader),
        "F6": _proxy_f6(reader),
        "F7": _proxy_f7(reader),
    }


def composite(
    proxies: dict[str, ProxyScore],
    mode: str,
) -> tuple[float, float]:
    """
    Returns (composite_score, overall_confidence).
      composite_score   = weighted_sum / confidence_sum (0.0-10.0)
      overall_confidence = confidence_sum / weight_sum (0.0-1.0)
    Both are 0 when no proxies have any confidence.
    """
    weights = _mode_weights(mode)
    weighted_sum = 0.0
    conf_weighted = 0.0
    weight_total = 0.0
    for fw, w in weights.items():
        ps = proxies.get(fw.upper())
        if ps is None or w == 0:
            continue
        weighted_sum += w * ps.weighted
        conf_weighted += w * ps.confidence
        weight_total += w
    if weight_total == 0 or conf_weighted == 0:
        return 0.0, 0.0
    return weighted_sum / conf_weighted, conf_weighted / weight_total


def _mode_weights(mode: str) -> dict[str, float]:
    """Use mid_cap weights as default screener weighting; dive does proper stage-aware."""
    table = WEIGHTS_C if mode.upper() == "C" else WEIGHTS_B
    return table.get("mid_cap", next(iter(table.values())))


# ── Per-framework proxies ────────────────────────────────────────────────


def _proxy_f1(reader: CompanyDataReader, asset_growth_decile: int | None) -> ProxyScore:
    """F1 Pre-Discovery proxy: Piotroski subset + GP/A."""
    notes: list[str] = []
    annuals = reader.annuals(last_n=2)
    if len(annuals) < 2:
        return ProxyScore("F1", raw=5.0, confidence=0.2, notes=["<2 annuals"])

    cur, prior = annuals[0], annuals[1]
    confidence = 1.0

    # Piotroski subset (max 9, scaled to 0-5 contribution)
    p_score = 0
    if (cur.roa or 0) > 0: p_score += 1
    if (cur.operating_cash_flow or 0) > 0: p_score += 1
    if (cur.roa or 0) > (prior.roa or 0): p_score += 1
    if (cur.operating_cash_flow or 0) > (cur.net_income or 0): p_score += 1
    if (cur.long_term_debt or 0) <= (prior.long_term_debt or 0): p_score += 1
    if (cur.current_ratio or 0) > (prior.current_ratio or 0): p_score += 1
    if (cur.gross_margin or 0) > (prior.gross_margin or 0): p_score += 1
    if (cur.asset_turnover or 0) > (prior.asset_turnover or 0): p_score += 1
    pio_contrib = (p_score / 9.0) * 5.0    # 0-5

    # GP/A (Novy-Marx) — needs sector universe to compute true percentile;
    # at screener stage use absolute threshold (>0.30 = "high quality" per Novy-Marx)
    gp_a = cur.gp_a
    gp_a_contrib = 0.0
    if gp_a is None:
        confidence *= 0.7
        notes.append("gp_a missing")
    elif gp_a >= 0.30:
        gp_a_contrib = 2.5
    elif gp_a >= 0.20:
        gp_a_contrib = 1.5

    # Asset growth (low = good for F1 quality interpretation)
    ag_contrib = 0.0
    if asset_growth_decile is not None:
        # Decile 1-5 = +2.5, 6-8 = +1, 9-10 = 0
        if asset_growth_decile <= 5:
            ag_contrib = 2.5
        elif asset_growth_decile <= 8:
            ag_contrib = 1.0
    else:
        confidence *= 0.8
        notes.append("no asset_growth_decile")

    raw = pio_contrib + gp_a_contrib + ag_contrib
    return ProxyScore("F1", raw=min(10.0, raw), confidence=confidence, notes=notes)


def _proxy_f2(reader: CompanyDataReader, momentum_decile: int | None) -> ProxyScore:
    """F2 Momentum proxy: 12mo return decile + 52-week-high proximity."""
    notes: list[str] = []
    confidence = 1.0

    decile_contrib = 0.0
    if momentum_decile is None:
        confidence *= 0.3
        notes.append("no momentum decile (insufficient price history)")
    else:
        # Decile 10 = +5, decile 1 = 0
        decile_contrib = (momentum_decile - 1) * (5.0 / 9.0)

    # 52-week-high proximity from Company.... actually we don't store this directly.
    # Use latest price vs the max in the last 52 weekly bars.
    prices = reader.price_history(within_days=400)
    proximity_contrib = 0.0
    if len(prices) < 4:
        confidence *= 0.4
        notes.append("<4 price bars")
    else:
        latest_close = prices[0].close or 0
        wk52_high = max((p.close or 0) for p in prices[: min(52, len(prices))])
        if latest_close > 0 and wk52_high > 0:
            distance = (wk52_high - latest_close) / wk52_high
            if distance <= F2_52WK_HIGH_PROXIMITY:    # within 10%
                proximity_contrib = 5.0
            elif distance <= 0.20:
                proximity_contrib = 2.5

    return ProxyScore("F2",
                      raw=min(10.0, decile_contrib + proximity_contrib),
                      confidence=confidence, notes=notes)


def _proxy_f3(reader: CompanyDataReader) -> ProxyScore:
    """F3 Innovation proxy: gross margin trajectory + R&D intensity sweet spot."""
    notes: list[str] = []
    annuals = reader.annuals(last_n=5)
    if len(annuals) < 2:
        return ProxyScore("F3", raw=5.0, confidence=0.2, notes=["<2 annuals"])

    confidence = 1.0
    if len(annuals) < 5:
        confidence *= 0.7
        notes.append(f"only {len(annuals)} annuals (<5)")

    # Gross margin expansion: linear trend / years
    gm_contrib = 0.0
    margins = [a.gross_margin for a in annuals if a.gross_margin is not None]
    if len(margins) >= 2:
        years = len(margins) - 1
        delta = margins[0] - margins[-1]
        annual_expansion = delta / years
        if annual_expansion >= F3_GM_EXPANSION_MIN:    # ≥200bps/yr
            gm_contrib = 5.0
        elif annual_expansion >= 0.005:
            gm_contrib = 2.5

    # R&D intensity sweet spot
    cur = annuals[0]
    rd_contrib = 0.0
    rd_int = cur.rd_intensity
    if rd_int is None:
        confidence *= 0.7
        notes.append("rd_intensity missing")
    elif F3_RD_INTENSITY_MIN <= rd_int <= F3_RD_INTENSITY_MAX:
        rd_contrib = 5.0
    elif 0.05 <= rd_int < F3_RD_INTENSITY_MIN or F3_RD_INTENSITY_MAX < rd_int <= 0.50:
        rd_contrib = 2.5

    return ProxyScore("F3", raw=min(10.0, gm_contrib + rd_contrib),
                      confidence=confidence, notes=notes)


def _proxy_f4(reader: CompanyDataReader) -> ProxyScore:
    """
    F4 Stealth proxy: SI snapshot + EPS acceleration.
    Confidence starts low because SI trend needs accumulated snapshots
    (the monthly scheduler builds this up over time).
    """
    notes: list[str] = []
    confidence = 0.4    # always low at screener time; better via dive after months of accumulation

    company = reader.company_or_none()
    if company is None:
        return ProxyScore("F4", raw=5.0, confidence=0.1, notes=["no company"])

    si_contrib = 0.0
    si = company.short_pct_float_latest
    if si is None:
        notes.append("short interest missing")
        confidence *= 0.7
    elif si > 5:
        # Short interest snapshot — high SI is interesting (potential squeeze /
        # mispricing); but without trend we don't know if declining.
        si_contrib = 2.5

    si_history = reader.short_interest_history(last_n=4)
    if len(si_history) >= 3:
        confidence = min(1.0, confidence + 0.3)
        # Declining trend?
        if si_history[0].short_pct_float < si_history[-1].short_pct_float:
            si_contrib += 2.5

    eps_contrib = 0.0
    quarterlies = reader.quarterlies(last_n=4)
    if len(quarterlies) >= 4:
        eps_seq = [q.eps_diluted for q in quarterlies if q.eps_diluted is not None]
        if len(eps_seq) >= 3:
            # Simple acceleration: each subsequent quarter EPS > prior
            accel = sum(
                1 for i in range(len(eps_seq) - 1)
                if eps_seq[i] >= eps_seq[i + 1]
            )
            if accel >= 2:
                eps_contrib = 5.0
            elif accel >= 1:
                eps_contrib = 2.5
    else:
        notes.append("<4 quarterlies for EPS sequence")

    return ProxyScore("F4", raw=min(10.0, si_contrib + eps_contrib),
                      confidence=confidence, notes=notes)


def _proxy_f5(reader: CompanyDataReader) -> ProxyScore:
    """F5 Growth Quality proxy: 3yr CAGR + FCF margin + ROIC + D/EBITDA."""
    notes: list[str] = []
    annuals = reader.annuals(last_n=4)
    if len(annuals) < 2:
        return ProxyScore("F5", raw=5.0, confidence=0.2, notes=["<2 annuals"])

    confidence = 1.0 if len(annuals) >= 4 else 0.7
    cur = annuals[0]

    cagr_contrib = 0.0
    if len(annuals) >= 4 and annuals[3].revenue and cur.revenue:
        cagr_3y = (cur.revenue / annuals[3].revenue) ** (1 / 3) - 1
        if cagr_3y >= F5_REVENUE_CAGR_MIN:
            cagr_contrib = 3.0
        elif cagr_3y >= 0.05:
            cagr_contrib = 1.5
    else:
        notes.append("3yr CAGR not computable")
        confidence *= 0.8

    fcf_contrib = 0.0
    if cur.fcf_margin is not None:
        if cur.fcf_margin >= F5_FCF_MARGIN_MIN:
            fcf_contrib = 3.0
        elif cur.fcf_margin >= 0.10:
            fcf_contrib = 1.5

    roic_contrib = 0.0
    if cur.roic is not None:
        if cur.roic >= F5_ROIC_MIN:
            roic_contrib = 3.0
        elif cur.roic >= 0.10:
            roic_contrib = 1.5

    debt_penalty = 0.0
    if cur.debt_to_ebitda is not None and cur.debt_to_ebitda > F5_DEBT_EBITDA_MAX:
        debt_penalty = 1.0
        notes.append(f"debt/ebitda={cur.debt_to_ebitda:.1f} > {F5_DEBT_EBITDA_MAX}")

    raw = cagr_contrib + fcf_contrib + roic_contrib - debt_penalty
    return ProxyScore("F5", raw=max(0.0, min(10.0, raw)),
                      confidence=confidence, notes=notes)


def _proxy_f6(reader: CompanyDataReader) -> ProxyScore:
    """F6 Platform proxy: Rule of 40 + buyback yield."""
    notes: list[str] = []
    annuals = reader.annuals(last_n=2)
    if len(annuals) < 2:
        return ProxyScore("F6", raw=5.0, confidence=0.2, notes=["<2 annuals"])

    confidence = 0.7    # F6 requires customer concentration etc which need DEF14A
    cur, prior = annuals[0], annuals[1]

    rule40_contrib = 0.0
    if cur.revenue and prior.revenue and cur.fcf_margin is not None:
        rev_growth = (cur.revenue - prior.revenue) / prior.revenue
        rule40 = (rev_growth + cur.fcf_margin) * 100
        if rule40 >= 40:
            rule40_contrib = 5.0
        elif rule40 >= 25:
            rule40_contrib = 2.5

    buyback_contrib = 0.0
    if cur.buyback_yield is not None and cur.buyback_yield >= F5_BUYBACK_YIELD_MIN:
        buyback_contrib = 5.0
    elif cur.buyback_yield is not None and cur.buyback_yield >= 0.01:
        buyback_contrib = 2.5

    return ProxyScore("F6", raw=min(10.0, rule40_contrib + buyback_contrib),
                      confidence=confidence, notes=notes)


def _proxy_f7(reader: CompanyDataReader) -> ProxyScore:
    """
    F7 Smart Beta proxy: requires 10yr EV/Rev z-score history. At screener
    time we don't have this — return low confidence with absolute valuation
    proxy via Company.pe_trailing.
    """
    notes: list[str] = ["10yr z-scores not computed at screener time"]
    confidence = 0.3

    company = reader.company_or_none()
    if company is None:
        return ProxyScore("F7", raw=5.0, confidence=0.1, notes=["no company"])

    # Coarse PE-based valuation proxy
    pe = company.pe_trailing
    raw = 5.0
    if pe is not None:
        if pe < 12:
            raw = 8.0    # cheap
        elif pe < 20:
            raw = 6.0    # fair
        elif pe < 35:
            raw = 4.0
        else:
            raw = 2.0    # expensive

    return ProxyScore("F7", raw=raw, confidence=confidence, notes=notes)
