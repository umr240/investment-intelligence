"""ADR-032/042 — /intrinsic-value skill handler.

Implementation of the workflow declared in `.claude/skills/intrinsic-value.md`.

Runs both valuation engines and returns a structured payload plus the two
postconditions that make the skill safe to expose in a UI:

  * ``damodaran_reliability_stated`` — the forward-DCF verdict is always
    present, so a caller cannot render an intrinsic value without also
    rendering whether it may be quoted.
  * ``franchise_verdict_stated`` — the franchise test is present or explicitly
    ``indeterminate``. Missing data must never render as "no moat".

Why this file exists at all: adding `.claude/skills/intrinsic-value.md` made the
skill appear in ``GET /skills`` (which globs ``*.md``) while
``POST /skill/intrinsic-value/run`` raised KeyError from ``get_handler`` and
surfaced as a bare HTTP 500. A skill the API advertises but cannot execute is
worse than an absent one, because a UI will offer the button.

Deterministic: zero LLM calls (``permitted_anthropic_calls: [none]``).
"""
from __future__ import annotations

import logging
from typing import Any

from cli.skills.runtime import PostCondition, SkillContext, SkillResult, register

logger = logging.getLogger(__name__)


def compute_valuation_payload(
    ticker: str,
    *,
    high_growth_years: int = 8,
    persist: bool = False,
    include_greenwald: bool = True,
) -> dict[str, Any]:
    """Both engines → one JSON-serialisable dict.

    Shared by the skill handler and the ``/valuation/{ticker}`` API route so the
    two can never drift into reporting different numbers for the same ticker
    (``single_source_of_truth``).
    """
    from valuation.damodaran import compute_and_persist
    from valuation.damodaran.loader import CompanyNotFoundError, InsufficientDataError

    payload: dict[str, Any] = {"ticker": ticker.upper(), "errors": []}

    # ── Damodaran ──
    try:
        iv = compute_and_persist(
            ticker, high_growth_years=high_growth_years, log_run=persist,
        )
    except (CompanyNotFoundError, InsufficientDataError) as exc:
        payload["errors"].append(f"damodaran: {exc.__class__.__name__}: {exc}")
        payload["damodaran"] = None
        payload["greenwald"] = None
        payload["reliability"] = {"verdict": "unavailable", "reasons": [str(exc)]}
        return payload

    # Reuse the CLI's reliability logic rather than restating the rules — one
    # definition of "may this number be quoted", used by CLI, skill and API.
    from cli.main import _iv_reliability

    verdict, reasons = _iv_reliability(iv)
    maturity = getattr(getattr(iv, "maturity_classification", None), "tier", None)

    payload["damodaran"] = {
        "tier": str(getattr(iv, "tier", "") or ""),
        "maturity_tier": maturity,
        "intrinsic_value_per_share": iv.intrinsic_value_per_share,
        "current_price": iv.current_price,
        "margin_of_safety_pct": iv.margin_of_safety_pct,
        "anchor_epv_per_share": iv.epv_per_share,
        "mos_vs_epv_pct": iv.mos_vs_epv_pct,
        "reverse_implied_growth_rate": iv.reverse_implied_growth_rate,
        "reverse_implied_growth_feasibility": iv.reverse_implied_growth_feasibility,
        "narrative_premium_pct": iv.narrative_premium_pct,
        "wacc": getattr(iv, "wacc", None),
        "inversion_questions": list(getattr(iv, "inversion_questions", []) or []),
        "data_gaps": list(getattr(iv, "data_gaps", []) or []),
    }
    payload["reliability"] = {"verdict": verdict, "reasons": reasons}

    # ── Greenwald ──
    payload["greenwald"] = None
    if include_greenwald:
        try:
            from valuation.greenwald import compute_greenwald_valuation

            gw = compute_greenwald_valuation(ticker)
            av, ep, fr = gw.asset_value, gw.earnings_power, gw.franchise
            recent = gw.epv_recent_regime
            payload["greenwald"] = {
                "wacc_used": gw.wacc_used,
                "wacc_source": gw.wacc_source,
                "current_price": gw.current_price,
                "epv_applicability": gw.epv_applicability,
                "epv_applicability_reason": gw.epv_applicability_reason,
                "asset_value_per_share": av.asset_value_per_share,
                "asset_value_total": av.asset_value_total,
                "epv_per_share_full_history": ep.epv_per_share,
                "normalized_op_margin": ep.normalized_op_margin,
                "growth_capex_added_back": ep.growth_capex_added_back,
                "epv_per_share_recent_regime": (
                    recent.epv_per_share if recent is not None else None
                ),
                "recent_regime_margin": (
                    recent.normalized_op_margin if recent is not None else None
                ),
                "franchise_verdict": fr.verdict,
                "epv_to_av_ratio": fr.epv_to_av_ratio,
                "growth_is_worth_paying_for": fr.growth_is_worth_paying_for,
                "franchise_interpretation": fr.interpretation,
                "data_gaps": list(gw.data_gaps or []),
            }
        except Exception as exc:  # noqa: BLE001 — Greenwald is additive, never fatal
            payload["errors"].append(f"greenwald: {exc.__class__.__name__}: {exc}")

    # Greenwald borrows the Damodaran loader for WACC, so the ticker's fetch
    # gaps land in BOTH lists and the UI rendered each one twice. Drop from the
    # Greenwald list anything the Damodaran list already carries — order
    # preserved, Greenwald-specific gaps (PP&E proxy, EPV applicability) kept.
    if payload.get("greenwald") and payload.get("damodaran"):
        seen = set(payload["damodaran"]["data_gaps"])
        payload["greenwald"]["data_gaps"] = [
            g for g in payload["greenwald"]["data_gaps"] if g not in seen
        ]

    # ── Cross-engine synthesis (same four cells as the CLI) ──
    gw_p = payload.get("greenwald")
    # Three states, not two. Collapsing "qualified" into "not usable" made the UI
    # contradict itself — the banner said "usable WITH caveats" while the
    # synthesis directly below said "not usable here". Caught only by reading the
    # rendered page (`test_behaviour_not_implementation`).
    verdict_now = payload["reliability"]["verdict"]
    dcf_usable = verdict_now == "reliable"
    dcf_qualified = verdict_now == "qualified"
    franchise_ok = gw_p.get("growth_is_worth_paying_for") if gw_p else None
    if franchise_ok is None:
        synth = (
            "Franchise test indeterminate — the forward DCF is unanchored: nothing "
            "independent confirms its growth assumption."
        )
    elif franchise_ok and dcf_usable:
        synth = (
            "Both engines agree: a franchise exists AND the forward model applies. "
            "The only configuration where a DCF growth assumption is independently "
            "supported."
        )
    elif franchise_ok and dcf_qualified:
        synth = (
            "Franchise confirmed, and the forward DCF is usable but qualified — read "
            "it alongside the caveats, not as a point estimate. The Greenwald ladder "
            "is the sturdier anchor of the two here."
        )
    elif franchise_ok:
        synth = (
            "Franchise confirmed, but the forward DCF is not usable here. The "
            "Greenwald ladder is the defensible anchor; growth has value but this "
            "model cannot size it."
        )
    else:
        synth = (
            "Divergence: the forward DCF prices growth, but the franchise test says "
            "returns have competed to reproduction cost. In commodity economics "
            "growth is worth ~zero — a DCF still assigns it value because g is an "
            "input, not a finding. Weight the EPV floor."
        )
    payload["synthesis"] = synth
    return payload


def _fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%" if pct else f"{value:,.2f}"


@register("intrinsic-value")
def run(ctx: SkillContext) -> SkillResult:
    ticker = str(ctx.args.get("ticker") or "").strip().upper()
    if not ticker:
        return SkillResult(success=False, error_message="ticker is required")

    years = int(ctx.args.get("years") or 8)
    payload = compute_valuation_payload(ticker, high_growth_years=years, persist=True)

    dmd = payload.get("damodaran")
    gw = payload.get("greenwald")
    rel = payload["reliability"]

    postconditions = [
        PostCondition(
            name="damodaran_reliability_stated",
            pass_=bool(rel.get("verdict")),
            observed=rel.get("verdict"),
            expected="one of reliable | qualified | unreliable | unavailable",
        ),
        PostCondition(
            name="franchise_verdict_stated",
            pass_=bool(gw and gw.get("franchise_verdict")),
            observed=(gw or {}).get("franchise_verdict"),
            expected="franchise | no_franchise | value_destruction | indeterminate",
        ),
    ]

    lines: list[str] = [f"Intrinsic value — {ticker}", ""]
    if dmd is None:
        lines.append(f"Damodaran: unavailable — {'; '.join(payload['errors'])}")
    else:
        lines += [
            f"Damodaran [{rel['verdict'].upper()}]  tier={dmd['tier']}  "
            f"maturity={dmd['maturity_tier']}",
            f"  price {_fmt(dmd['current_price'])}  ·  forward DCF "
            f"{_fmt(dmd['intrinsic_value_per_share'])}  ·  anchor EPV "
            f"{_fmt(dmd['anchor_epv_per_share'])}",
            f"  market-implied growth {_fmt(dmd['reverse_implied_growth_rate'], pct=True)}"
            f" ({dmd['reverse_implied_growth_feasibility']})",
        ]
        for reason in rel["reasons"]:
            lines.append(f"  ! {reason}")
    if gw:
        lines += [
            "",
            f"Greenwald  applicability={gw['epv_applicability']}  "
            f"WACC {gw['wacc_used'] * 100:.2f}%",
            f"  asset value {_fmt(gw['asset_value_per_share'])}  ·  EPV "
            f"{_fmt(gw['epv_per_share_full_history'])}"
            + (
                f"  ·  EPV(recent regime) {_fmt(gw['epv_per_share_recent_regime'])}"
                if gw["epv_per_share_recent_regime"] is not None else ""
            ),
            f"  FRANCHISE: {gw['franchise_verdict'].replace('_', ' ').upper()}"
            + (f"  ({gw['epv_to_av_ratio']:.2f}x)" if gw["epv_to_av_ratio"] else ""),
        ]
    lines += ["", f"Synthesis: {payload['synthesis']}"]

    anomalies: list[dict[str, Any]] = []
    if rel["verdict"] == "unreliable":
        anomalies.append({
            "kind": "headline_iv_not_quotable",
            "detail": "; ".join(rel["reasons"]) or rel["verdict"],
        })
    if gw and gw["epv_applicability"] != "applicable":
        anomalies.append({
            "kind": f"epv_{gw['epv_applicability']}",
            "detail": gw["epv_applicability_reason"],
        })

    return SkillResult(
        success=all(pc.pass_ for pc in postconditions),
        postconditions=postconditions,
        anomalies=anomalies,
        render_output="\n".join(lines),
        tool_calls_count=2 if gw else 1,
    )
