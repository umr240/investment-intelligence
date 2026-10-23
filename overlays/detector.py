"""
Passive overlay trigger scanner — zero token cost.

Per CLAUDE.md "Overlay detector is always passive": this module ONLY scans
the dive scorecard for trigger conditions and returns a trigger list. It
never executes an overlay automatically. The CLI presents triggers and
waits for explicit user confirmation (`invest overlay run TICKER --type X`)
before any overlay function is invoked.

Trigger conditions per PROJECT_SPEC §6.1:
  ICA-1: F5 ROIC < 0.15 AND R&D intensity ≥ 0.10
  ICA-2: F5 ROIC < 0.15 AND sector ∈ INNOVATION_SECTORS (5: saas/biotech/semis/deep_tech/pharma)
  ICA-3: GAAP net_income < 0 AND |OCF / net_income| > 2.0
  ICA-4: P/B > 4.0 AND GP/A in top sector tercile AND R&D intensity > 0.15
         (current code approximates "top tercile" as gp_a >= 0.20 — a TODO
         is to compute the actual sector 67th-percentile at runtime)
  PSA-1: months since listing < 36 AND listing_type ∈ {spinoff, demerger, carve_out}
  PSA-2: financials_comparable == False
  PSA-3: F7 skipped due to insufficient history
  PSA-4: F1 piotroski ≤ 4 AND ocf_positive AND GP/A in top sector tercile
  BEW-1: F3 ≥ 7 AND F6 ≥ 7 AND EV/Rev z-score > 0 (expensive vs own history)
  BEW-2: F1 ≥ 6 AND F3 ≥ 6 AND EV/Rev > sector median
  BEW-3: 12-1 momentum > 0.50 (compounded > 50%)
  BEW-5: idio_vol > 0.30 AND R&D ≥ 0.33 (top tercile) AND market_cap < $2B

Triggers labelled "user language" (ICA-5, PSA-5, BEW-4) are CLI-layer —
they fire when the user types phrases like "intangible-heavy" — not in
this module.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal

from config.constants import (
    ICA_PB_TRIGGER,
    INNOVATION_SECTORS,
)


# ── Trigger types ────────────────────────────────────────────────────────


@dataclass
class OverlayTrigger:
    overlay_type: Literal["ICA", "PSA", "BEW"]
    trigger_id: str           # e.g. 'ICA-1', 'PSA-3', 'BEW-2'
    trigger_condition: str    # human-readable explanation
    relevant_numbers: dict[str, Any]
    framework_section: str    # which framework's section to append output to

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Public scan function ──────────────────────────────────────────────────


def scan_for_triggers(
    ticker: str,
    *,
    reader: Any,
    framework_results: dict[str, Any],
    company_stage: str | None = None,
) -> list[OverlayTrigger]:
    """Pure function. Scans the scorecard and returns triggers.

    Reads only from the SQLite warehouse via `reader` and from the in-memory
    `framework_results`. Never makes API calls. Never raises (per branch
    isolation contract).
    """
    triggers: list[OverlayTrigger] = []

    company = reader.company_or_none() if hasattr(reader, "company_or_none") else None
    annuals = reader.annuals(last_n=2) if hasattr(reader, "annuals") else []
    latest = annuals[0] if annuals else None

    # Pull framework scores + selected signals once
    f_scores = {
        name.upper(): float(getattr(res, "score", 0.0) or 0.0)
        for name, res in framework_results.items()
    }
    f1_signals = (framework_results.get("F1") or _empty_obj()).signals or {}
    f5_signals = (framework_results.get("F5") or _empty_obj()).signals or {}
    f7_signals = (framework_results.get("F7") or _empty_obj()).signals or {}

    # Source-of-truth metric extraction
    f5_roic = (f5_signals.get("roic") or {}).get("roic")
    rd_intensity = latest.rd_intensity if latest else None
    sector = (company.sector or "").lower() if company else ""
    market_cap = company.market_cap_usd if company else None

    # ── ICA triggers ────────────────────────────────────────────────────
    triggers.extend(_scan_ica(ticker, latest, f5_roic, rd_intensity, sector, company))
    # ── PSA triggers ────────────────────────────────────────────────────
    triggers.extend(_scan_psa(ticker, company, framework_results))
    # ── BEW triggers ────────────────────────────────────────────────────
    triggers.extend(_scan_bew(ticker, f_scores, f7_signals, market_cap, rd_intensity,
                              latest, framework_results))

    return triggers


# ── ICA condition implementations ─────────────────────────────────────────


def _scan_ica(
    ticker: str, latest: Any, roic: float | None,
    rd_intensity: float | None, sector: str, company: Any,
) -> list[OverlayTrigger]:
    out: list[OverlayTrigger] = []

    # ICA-1: ROIC<15% + R&D≥10% (intangible-heavy with low GAAP capital efficiency)
    if (roic is not None and roic < 0.15
            and rd_intensity is not None and rd_intensity >= 0.10):
        out.append(OverlayTrigger(
            overlay_type="ICA",
            trigger_id="ICA-1",
            trigger_condition=(
                "F5 ROIC < 15% AND R&D intensity ≥ 10% — GAAP under-reports "
                "capital efficiency for intangible-heavy companies"
            ),
            relevant_numbers={
                "f5_roic": round(roic, 4),
                "rd_intensity": round(rd_intensity, 4),
                "roic_threshold": 0.15,
                "rd_threshold": 0.10,
            },
            framework_section="F5",
        ))

    # ICA-2: ROIC<15% + sector ∈ INNOVATION_SECTORS
    if (roic is not None and roic < 0.15 and sector in INNOVATION_SECTORS):
        out.append(OverlayTrigger(
            overlay_type="ICA",
            trigger_id="ICA-2",
            trigger_condition=(
                f"F5 ROIC < 15% AND sector='{sector}' is in INNOVATION_SECTORS — "
                "intangible-capital adjustment likely material"
            ),
            relevant_numbers={
                "f5_roic": round(roic, 4),
                "sector": sector,
            },
            framework_section="F5",
        ))

    # ICA-3: GAAP loss BUT OCF strongly positive — accounting-noise loss
    if latest and latest.net_income is not None and latest.net_income < 0:
        ocf = latest.operating_cash_flow
        if ocf is not None and abs(latest.net_income) > 0:
            ratio = ocf / abs(latest.net_income)
            if ratio > 2.0:
                out.append(OverlayTrigger(
                    overlay_type="ICA",
                    trigger_id="ICA-3",
                    trigger_condition=(
                        "GAAP net_income < 0 AND OCF/|net_income| > 2x — earnings "
                        "depressed by non-cash items (R&D, intangible amortisation); "
                        "ICA-adjusted ROIC may flip to positive"
                    ),
                    relevant_numbers={
                        "gaap_net_income": latest.net_income,
                        "operating_cash_flow": ocf,
                        "ocf_to_loss_ratio": round(ratio, 2),
                        "threshold": 2.0,
                    },
                    framework_section="F1",
                ))

    # ICA-4: P/B > 4 + GP/A in top sector tercile + R&D > 15%.
    # NOTE: code approximates "top sector tercile" with absolute gp_a >= 0.20
    # because we don't yet compute live sector-percentile lookups. Tightening
    # to an actual sector-percentile calculation is a TODO (would need
    # per-sector aggregate query at trigger time).
    if (
        company and company.pb_ratio is not None and company.pb_ratio > ICA_PB_TRIGGER
        and latest and latest.gp_a is not None and latest.gp_a >= 0.20
        and rd_intensity is not None and rd_intensity > 0.15
    ):
        out.append(OverlayTrigger(
            overlay_type="ICA",
            trigger_id="ICA-4",
            trigger_condition=(
                f"P/B > {ICA_PB_TRIGGER} AND GP/A in top sector tercile AND R&D intensity > 15% — "
                "high book multiple may reflect unrecognised intangible capital"
            ),
            relevant_numbers={
                "pb_ratio": company.pb_ratio,
                "gp_a": round(latest.gp_a, 4),
                "rd_intensity": round(rd_intensity, 4),
                "pb_threshold": ICA_PB_TRIGGER,
            },
            framework_section="F5",
        ))

    # ICA-5 (ADR-021): GAAP↔non-GAAP ROIC gap ≥ 3pp regardless of GAAP level.
    # The most academically defensible ICA trigger — ICA exists to surface
    # the wedge between regulatory and economic capital efficiency. Fires
    # in BOTH directions: a 3pp upward adjustment (GAAP under-reports
    # because R&D is expensed) AND a 3pp downward adjustment (GAAP over-
    # reports because off-balance-sheet intangibles inflate the "true"
    # invested capital base). Both views matter — the gap itself is the
    # signal.
    #
    # Methodology consistency (per Munger-style triangulation, user note
    # 2026-05-09): both legs MUST come from the same SEC 10-K XBRL source
    # and apply only Peters-Taylor capitalisation (no SBC/restructuring/
    # acquisition add-backs — see ADR-021 §4.1). This is enforced
    # structurally by the data pipeline (deterministic SEC-XBRL only) but
    # we declare it explicitly in `relevant_numbers` so the trigger is
    # self-auditable: the reader can see the methodology without consulting
    # the ADR. If we ever add a third-party data source (FactSet, Yahoo
    # consensus, etc.) this trigger MUST be updated to declare which
    # source each leg uses, and the gap should be discarded if sources
    # differ.
    if (
        company is not None
        and company.roic is not None
        and company.pt_adjusted_roic is not None
    ):
        gap_pp = abs(company.pt_adjusted_roic - company.roic) * 100.0
        if gap_pp >= 3.0:
            direction = (
                "upward (economic > GAAP — R&D/SG&A under-capitalised)"
                if company.pt_adjusted_roic > company.roic
                else "downward (economic < GAAP — invested-capital base inflated by intangibles)"
            )
            out.append(OverlayTrigger(
                overlay_type="ICA",
                trigger_id="ICA-5",
                trigger_condition=(
                    f"|Peters-Taylor non-GAAP ROIC − GAAP ROIC| = {gap_pp:.2f}pp "
                    f"≥ 3pp ({direction}) — economic capital efficiency materially "
                    "diverges from GAAP; ICA restatement is informative regardless "
                    "of GAAP ROIC level. Methodology-consistent: both legs from "
                    "same SEC 10-K XBRL; no SBC/restructuring/acquisition add-backs "
                    "(ADR-021 §4.1)"
                ),
                relevant_numbers={
                    "roic_gaap": round(company.roic, 4),
                    "pt_adjusted_roic": round(company.pt_adjusted_roic, 4),
                    "gap_pp": round(gap_pp, 2),
                    "gap_threshold_pp": 3.0,
                    "direction": "upward" if company.pt_adjusted_roic > company.roic else "downward",
                    "methodology": {
                        "source_gaap": "SEC 10-K XBRL (companyfacts.json)",
                        "source_non_gaap": "SEC 10-K XBRL (companyfacts.json)",
                        "same_source": True,
                        "non_gaap_method": "Peters-Taylor (2017 JFE) capitalisation",
                        "addbacks_excluded": ["SBC", "restructuring", "acquisition_costs", "impairment", "one-time_items"],
                        "addbacks_included": ["R&D capitalised as KC (15%/yr amortisation)", "25% of SG&A capitalised as OC (20%/yr amortisation)"],
                        "adr_reference": "ADR-021",
                    },
                },
                framework_section="F5",
            ))

    return out


# ── PSA condition implementations ─────────────────────────────────────────


def _scan_psa(
    ticker: str, company: Any, framework_results: dict[str, Any],
) -> list[OverlayTrigger]:
    out: list[OverlayTrigger] = []
    if not company:
        return out

    # PSA-1: <36 months listed AND listing_type spinoff/demerger/carve_out
    from data.reader import trusted_listing_date

    listing_date = trusted_listing_date(
        company.ipo_date, getattr(company, "ipo_date_state", None)
    )
    months_since_listing = _months_since(listing_date) if listing_date else None
    listing_type = (company.listing_type or "").lower()
    if (
        months_since_listing is not None and months_since_listing < 36
        and listing_type in ("spinoff", "demerger", "carve_out")
    ):
        out.append(OverlayTrigger(
            overlay_type="PSA",
            trigger_id="PSA-1",
            trigger_condition=(
                f"Listed < 36 months ({months_since_listing}mo) AND "
                f"listing_type='{listing_type}' — Cusatis-Desai-Jain spinoff window"
            ),
            relevant_numbers={
                "months_since_listing": months_since_listing,
                "listing_type": listing_type,
                "ipo_date": listing_date,
            },
            framework_section="F1",
        ))

    # PSA-2: financials_comparable=False — we don't track this column today
    # (would require manual flag from 10-K parsing). Skipped in v1.

    # PSA-3: F7 skipped because the registrant is too young to z-score, which is
    # the case a spinoff workflow speaks to. Qualitative gates (split-affected
    # window, regime break) also report "insufficient history" but say nothing
    # about listing age, so they must not fire this.
    f7_unfeasible = framework_results.get("__unfeasible__", {}).get("F7", "")
    reason_lc = f7_unfeasible.lower()
    is_history_gap = "insufficient" in reason_lc or "history" in reason_lc
    is_qualitative_gate = any(k in reason_lc for k in ("split", "regime"))
    if is_history_gap and not is_qualitative_gate:
        # Only claim a recent listing when the date supports it; CSGP (listed
        # 1998) was previously reported as a recent IPO.
        recent = months_since_listing is None or months_since_listing < 60
        lead = (
            "F7 unfeasible — recent listing"
            if recent else
            "F7 unfeasible on annual history, though the registrant is long-listed"
        )
        out.append(OverlayTrigger(
            overlay_type="PSA",
            trigger_id="PSA-3",
            trigger_condition=(
                f"{lead}: {f7_unfeasible}. Spinoff/demerger PSA workflow may "
                "apply if listing_type confirms"
            ),
            relevant_numbers={
                "f7_unfeasible_reason": f7_unfeasible,
                "listing_type": listing_type,
                "months_since_listing": months_since_listing,
            },
            framework_section="F7",
        ))

    # PSA-4: F1 piotroski ≤ 4 AND OCF positive AND GP/A high
    f1_signals = (framework_results.get("F1") or _empty_obj()).signals or {}
    piotroski = f1_signals.get("piotroski_score")
    p_signals = f1_signals.get("piotroski") or {}
    ocf_pos = p_signals.get("P2_ocf_positive")
    annuals = []
    if hasattr(framework_results.get("F1"), "signals"):
        # We can't read reader from here — pull GP/A from f1_signals:
        # F1 includes gp_a in 'gp_a_strong' signal but not the value. Use heuristic.
        pass
    # Trigger only with the pieces we have on F1
    if (
        piotroski is not None and piotroski <= 4
        and ocf_pos is True
        and f1_signals.get("gp_a_strong") is True
    ):
        out.append(OverlayTrigger(
            overlay_type="PSA",
            trigger_id="PSA-4",
            trigger_condition=(
                "Piotroski ≤ 4 AND OCF positive AND GP/A in top sector tercile — anomaly: "
                "low Piotroski but cash + quality intact (PSA-style mispricing)"
            ),
            relevant_numbers={
                "piotroski": piotroski,
                "ocf_positive": ocf_pos,
                "gp_a_strong": True,
            },
            framework_section="F1",
        ))

    return out


# ── BEW condition implementations ─────────────────────────────────────────


def _scan_bew(
    ticker: str,
    f_scores: dict[str, float],
    f7_signals: dict[str, Any],
    market_cap: float | None,
    rd_intensity: float | None,
    latest: Any,
    framework_results: dict[str, Any],
) -> list[OverlayTrigger]:
    out: list[OverlayTrigger] = []

    f3 = f_scores.get("F3")
    f6 = f_scores.get("F6")
    f1 = f_scores.get("F1")

    ev_rev_z = (f7_signals.get("ev_revenue_z") or {}).get("z")

    # BEW-1: F3 ≥ 7 AND F6 ≥ 7 AND EV/Rev z-score > 0 (expensive vs own history)
    if (
        f3 is not None and f3 >= 7.0
        and f6 is not None and f6 >= 7.0
        and ev_rev_z is not None and ev_rev_z > 0
    ):
        out.append(OverlayTrigger(
            overlay_type="BEW",
            trigger_id="BEW-1",
            trigger_condition=(
                "F3 ≥ 7 AND F6 ≥ 7 AND EV/Rev z-score > 0 — strong innovation "
                "compounder + platform moat trading at premium to own history; "
                "Bessembinder extreme-winner candidate"
            ),
            relevant_numbers={
                "f3_score": f3,
                "f6_score": f6,
                "ev_revenue_z": round(ev_rev_z, 3),
            },
            framework_section="F3",
        ))

    # BEW-2: F1 ≥ 6 AND F3 ≥ 6 AND EV/Rev > sector median (we don't have sector
    # median; use absolute >5 as rough proxy)
    f7_ev_rev_current = (f7_signals.get("ev_revenue_z") or {}).get("current")
    if (
        f1 is not None and f1 >= 6.0
        and f3 is not None and f3 >= 6.0
        and f7_ev_rev_current is not None and f7_ev_rev_current > 5.0
    ):
        out.append(OverlayTrigger(
            overlay_type="BEW",
            trigger_id="BEW-2",
            trigger_condition=(
                "F1 ≥ 6 AND F3 ≥ 6 AND EV/Rev > 5x (rough sector-median proxy) — "
                "quality + innovation trading rich"
            ),
            relevant_numbers={
                "f1_score": f1,
                "f3_score": f3,
                "current_ev_revenue": round(f7_ev_rev_current, 3),
            },
            framework_section="F3",
        ))

    # BEW-3: 12-month return > 50% (F2 momentum signal — use return_12_1 as proxy)
    f2_signals = (framework_results.get("F2") or _empty_obj()).signals or {}
    return_12_1 = (f2_signals.get("momentum") or {}).get("return_12_1")
    if return_12_1 is not None and return_12_1 > 0.50:
        out.append(OverlayTrigger(
            overlay_type="BEW",
            trigger_id="BEW-3",
            trigger_condition=(
                f"12-1 momentum return > 50% ({round(return_12_1 * 100, 1)}%) — "
                "compounding pace warrants extreme-winner check"
            ),
            relevant_numbers={
                "return_12_1": round(return_12_1, 4),
                "threshold": 0.50,
            },
            framework_section="F2",
        ))

    # BEW-5: idio_vol > 0.30 AND R&D ≥ 0.33 AND market_cap < $2B
    # We don't currently compute idiosyncratic vol — skip the idio_vol gate
    # but still flag the small-cap-high-R&D pattern as BEW-5-partial.
    if (
        market_cap is not None and market_cap < 2_000_000_000
        and rd_intensity is not None and rd_intensity >= 0.33
    ):
        out.append(OverlayTrigger(
            overlay_type="BEW",
            trigger_id="BEW-5",
            trigger_condition=(
                "Market cap < $2B AND R&D intensity ≥ 33% (top tercile) — "
                "small-cap heavy-R&D Bessembinder candidate"
            ),
            relevant_numbers={
                "market_cap_usd": market_cap,
                "rd_intensity": round(rd_intensity, 4),
                "note": "Idiosyncratic vol not yet computed; partial trigger",
            },
            framework_section="F3",
        ))

    return out


# ── Helpers ───────────────────────────────────────────────────────────────


class _EmptyObj:
    score = 0.0
    signals: dict[str, Any] = {}
    verdict = "fail"
    data_gaps: list[str] = []


def _empty_obj() -> _EmptyObj:
    return _EmptyObj()


def _months_since(d: Any) -> int | None:
    if d is None:
        return None
    from datetime import date as _date
    try:
        today = _date.today()
        return (today.year - d.year) * 12 + (today.month - d.month)
    except (AttributeError, TypeError):
        return None


# ── Legacy async stubs (kept for backwards-compat with router calls) ──────


async def scan_for_triggers_async(scorecard: Any) -> list[OverlayTrigger]:
    """Async wrapper for callers that still expect the old signature.
    The current scan is sync; this exists for the router/CLI shim.
    """
    return []


async def run_overlay_by_type(ticker: str, overlay_type: str) -> dict[str, Any]:
    """Manual overlay execution dispatcher. Implemented by overlays.{ica,psa,bew}.

    Returns a dict result. Raises ValueError on unknown overlay_type.
    """
    from data.reader import CompanyDataReader
    reader = CompanyDataReader(ticker)
    overlay_type = overlay_type.upper()
    if overlay_type == "ICA":
        from overlays.ica import run_ica
        return await run_ica(ticker, reader=reader)
    if overlay_type == "PSA":
        from overlays.psa import run_psa
        return await run_psa(ticker, reader=reader)
    if overlay_type == "BEW":
        from overlays.bew import run_bew
        return await run_bew(ticker, reader=reader)
    raise ValueError(f"Unknown overlay type: {overlay_type}")


async def get_detected_triggers(ticker: str) -> list[OverlayTrigger]:
    """Read previously persisted triggers from deepdive_runs.overlays_triggered_json."""
    from data.db import get_session
    from data.models.schema import Company, DeepDiveRun
    from sqlalchemy import select, desc
    import json

    with get_session() as s:
        co = s.execute(select(Company).where(Company.ticker == ticker)).scalar_one_or_none()
        if not co:
            return []
        run = s.execute(
            select(DeepDiveRun).where(DeepDiveRun.company_id == co.id)
            .order_by(desc(DeepDiveRun.run_date))
        ).scalars().first()
        if not run or not run.overlays_triggered_json:
            return []
        try:
            payload = json.loads(run.overlays_triggered_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return [
            OverlayTrigger(**p) for p in payload
            if isinstance(p, dict) and "overlay_type" in p
        ]
