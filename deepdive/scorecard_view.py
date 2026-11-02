"""
ScorecardView — typed loader + view for a deep-dive scorecard.

This module is the **SINGLE SOURCE OF TRUTH** consumed by:
  1. `invest score-card TICKER` (the CLI rendering — Rich panels)
  2. `deepdive/narrative.py` (Phase 6 — the LLM narrative layer)

Both consume the same `ScorecardView` instance. The LLM is constrained to
reference only fields exposed here. No recomputation. No raw financial
data → no hallucination opportunities.

Source of data:
  - `framework_scores.scorecard_json` (composite + per-framework signals)
  - `deepdive_runs.overlays_triggered_json` (passive overlay triggers)
  - `companies` (header — name, sector, cap, CEO, IPO, etc.)
  - latest `Financial` row (current period anchors only — no recompute)

Future NLP / ML hooks:
  - `to_llm_context()` → exact JSON the LLM prompt embeds
  - `framework_signal_summaries()` → list[str] of one-line signals for
    keyword extraction / FinBERT sentiment passes
  - `key_metrics_table()` → flat dict suitable for LightGBM feature input

CLAUDE.md guarantee: this module is deterministic. Zero LLM calls. The
LLM lives one layer up in `deepdive/narrative.py` and consumes this view.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, desc

from data.db import get_session
from data.models.schema import (
    Company,
    DeepDiveRun,
    Financial,
    FrameworkScore,
)

if TYPE_CHECKING:
    from deepdive.citable_fields import CitableField

logger = logging.getLogger(__name__)


# ── View dataclasses (the "contract" for both CLI + AI) ──────────────────


@dataclass
class CompanyHeader:
    ticker: str
    name: str
    sector: str | None
    industry: str | None
    market_cap_usd: float | None
    cik: str | None
    ipo_date: date | None
    exchange: str | None
    fiscal_year_end_month: int | None

    # CEO / governance — populated via ADR-018 D1/D2/D3
    ceo_name: str | None
    ceo_equity_pct: float | None
    ceo_equity_pct_state: str | None    # disclosed_exact | parser_uncertain | not_disclosed
    is_founder_ceo: bool | None

    # Latest valuation snapshot
    pe_trailing: float | None
    pb_ratio: float | None
    ev_ebitda: float | None
    beta: float | None

    # Latest annual anchor (for context display)
    latest_fiscal_year: int | None
    latest_period_end: date | None
    latest_revenue: float | None
    latest_net_income: float | None

    # Defaulted and placed last so existing constructions stay valid. Consumers
    # must gate `ipo_date` on this: the 657 parser_uncertain rows hold a filing
    # date, not a listing date (KO -> 2018, GE -> 2019).
    ipo_date_state: str | None = None


@dataclass
class StageView:
    stage: str                          # pre_profitability | mid_cap | established
    reasoning: dict[str, Any]


@dataclass
class CompositeView:
    score: float                        # 0-10
    verdict: str                        # ADR-054 label (frameworks/composite.py)
    mode_resolved: str                  # 'A' | 'B' | 'C'
    weights_used: dict[str, float]      # {'F1': 0.15, 'F2': 0.20, ...}
    weights_renormalised: bool


@dataclass
class FrameworkView:
    """One framework's row in the scorecard view."""
    code: str                            # 'F1', 'F2', ...
    title: str                           # 'Pre-Discovery Alpha', ...
    score: float                         # 0-10
    max_score: float                     # 10 typically
    verdict: str                         # strong_fit | partial | fail | unfeasible
    band: str                            # bucket label for display
    key_signals: list[tuple[str, str]]   # [(label, formatted_value), ...]
    data_gaps: list[str]                 # framework-level gaps
    notes: str = ""                      # e.g. F7's contested-disclaimer
    is_unfeasible: bool = False
    unfeasible_reason: str = ""


@dataclass
class OverlayTriggerView:
    overlay_type: str                    # 'ICA' | 'PSA' | 'BEW'
    trigger_id: str                      # 'ICA-1' etc.
    condition: str
    relevant_numbers: dict[str, Any]
    framework_section: str


@dataclass
class ScorecardView:
    """The single contract consumed by both CLI rendering and AI narrative.

    Built from the most-recent persisted run for a ticker. Stable schema
    so the AI prompt remains valid as new fields are added.
    """
    ticker: str
    run_date: date
    mode_used: str

    company: CompanyHeader
    stage: StageView
    composite: CompositeView
    frameworks: list[FrameworkView]
    overlay_triggers: list[OverlayTriggerView]
    fetch_data_gaps: list[str]
    # Per-overlay final verdict from `overlays_results_json` (post-trigger
    # deeper analysis). Maps overlay_type → verdict string. Distinct from
    # `overlay_triggers` (which records WHICH trigger condition fired)
    # because a trigger may fire but the overlay's deeper analysis can
    # self-disqualify (e.g., PSA-3 fires on F7 unfeasibility, but the
    # spinoff-listing check then sets verdict="not_a_spinoff_candidate"
    # for a 158-month-old issuer — LULU case 2026-05-16).
    overlay_verdicts: dict[str, str] = field(default_factory=dict)
    schema_version: str = "1.0"

    # ── Serialisation ────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable dict. Used by `--json` flag + LLM prompt."""
        return asdict(self)

    def to_llm_context(self) -> str:
        """JSON string for embedding in an LLM prompt.

        The narrative layer's prompt template uses this directly:
          messages=[{
            "role": "user",
            "content": f"Generate narrative for:\\n{view.to_llm_context()}"
          }]
        Pretty-printed with stable key order so prompt-cache hits are
        more likely across runs of the same ticker.
        """
        return json.dumps(self.to_dict(), indent=2, default=_json_default,
                          sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScorecardView:
        """Inverse of to_dict over its JSON form (dates as ISO strings)."""
        co = dict(d["company"])
        for k in ("ipo_date", "latest_period_end"):
            co[k] = date.fromisoformat(co[k]) if co.get(k) else None
        return cls(
            ticker=d["ticker"],
            run_date=date.fromisoformat(d["run_date"]),
            mode_used=d["mode_used"],
            company=CompanyHeader(**co),
            stage=StageView(**d["stage"]),
            composite=CompositeView(**d["composite"]),
            frameworks=[
                FrameworkView(**{**f, "key_signals": [tuple(s) for s in f["key_signals"]]})
                for f in d["frameworks"]
            ],
            overlay_triggers=[OverlayTriggerView(**t) for t in d["overlay_triggers"]],
            fetch_data_gaps=list(d["fetch_data_gaps"]),
            overlay_verdicts=dict(d.get("overlay_verdicts") or {}),
            schema_version=d.get("schema_version", "1.0"),
        )

    # ── Convenience views (for AI layer + ML feature pipelines) ──────────

    def framework_signal_summaries(self) -> list[str]:
        """One-line signals per framework — for FinBERT / NLP passes."""
        out: list[str] = []
        for fv in self.frameworks:
            if fv.is_unfeasible:
                out.append(f"{fv.code}: unfeasible — {fv.unfeasible_reason}")
                continue
            sig_text = "; ".join(f"{label}={val}" for label, val in fv.key_signals)
            out.append(f"{fv.code} ({fv.score}/10 {fv.verdict}): {sig_text}")
        return out

    def key_metrics_table(self) -> dict[str, Any]:
        """Flat dict for ML feature input. Stable keys; missing → None.

        Designed to be appended-to over time without breaking trained models
        (new keys arrive at the end; existing keys never change semantics).
        """
        return {
            "composite_score": self.composite.score,
            "verdict": self.composite.verdict,
            "stage": self.stage.stage,
            **{f"{fv.code.lower()}_score": fv.score for fv in self.frameworks},
            **{f"{fv.code.lower()}_verdict": fv.verdict for fv in self.frameworks},
            "market_cap_usd": self.company.market_cap_usd,
            "pe_trailing": self.company.pe_trailing,
            "pb_ratio": self.company.pb_ratio,
            "ev_ebitda": self.company.ev_ebitda,
            "beta": self.company.beta,
            "ceo_equity_pct": self.company.ceo_equity_pct,
            "is_founder_ceo": self.company.is_founder_ceo,
            "n_overlay_triggers": len(self.overlay_triggers),
            "overlay_types": sorted({t.overlay_type for t in self.overlay_triggers}),
        }

    def citable_fields(self) -> dict[str, CitableField]:
        """Stable ID -> value the narrative may cite (ADR-045 §2.1)."""
        from deepdive.citable_fields import build_citable_fields

        return build_citable_fields(self)


# ── Public loader ────────────────────────────────────────────────────────


def load_scorecard_view(
    ticker: str, *, mode: str | None = None, run_id: int | None = None
) -> ScorecardView | None:
    """Load the latest scorecard for `ticker` from the persisted run.

    `mode`: filter to a specific mode ('A'/'B'/'C'/'default'). When None,
    picks the most-recent row regardless of mode. `run_id`: take overlays and
    gaps from that run, not the most recent one.

    Returns None if no dive history exists for the ticker.
    """
    ticker = ticker.upper()

    with get_session() as s:
        co = s.execute(
            select(Company).where(Company.ticker == ticker)
        ).scalar_one_or_none()
        if co is None:
            return None

        q = (
            select(FrameworkScore)
            .where(FrameworkScore.company_id == co.id)
            .order_by(desc(FrameworkScore.run_date))
        )
        if mode is not None:
            q = q.where(FrameworkScore.mode == mode)
        fs = s.execute(q).scalars().first()
        if fs is None:
            return None

        # Overlay triggers + fetch gaps: the given run (a dive freezing its own
        # view), else the most recent one.
        if run_id is not None:
            run = s.get(DeepDiveRun, run_id)
        else:
            run = s.execute(
                select(DeepDiveRun).where(DeepDiveRun.company_id == co.id)
                .where(DeepDiveRun.run_date >= fs.run_date)
                .order_by(desc(DeepDiveRun.run_date))
            ).scalars().first()

        # Latest annual for header context
        latest_annual = s.execute(
            select(Financial).where(Financial.company_id == co.id)
            .where(Financial.period == "annual")
            .order_by(desc(Financial.fiscal_year))
        ).scalars().first()

        # Detach so we can use after session closes
        s.expunge(co)
        s.expunge(fs)
        if run is not None:
            s.expunge(run)
        if latest_annual is not None:
            s.expunge(latest_annual)

    # ── Build the view from persisted JSON ───────────────────────────────
    scorecard = json.loads(fs.scorecard_json or "{}")

    company = CompanyHeader(
        ticker=ticker,
        name=co.name,
        sector=co.sector,
        industry=co.industry,
        market_cap_usd=co.market_cap_usd,
        cik=co.cik,
        ipo_date=co.ipo_date,
        ipo_date_state=co.ipo_date_state,
        exchange=co.exchange,
        fiscal_year_end_month=co.fiscal_year_end_month,
        ceo_name=co.ceo_name,
        ceo_equity_pct=co.ceo_equity_pct,
        ceo_equity_pct_state=co.ceo_equity_pct_state,
        is_founder_ceo=co.is_founder_ceo,
        pe_trailing=co.pe_trailing,
        pb_ratio=co.pb_ratio,
        ev_ebitda=co.ev_ebitda,
        beta=co.beta,
        latest_fiscal_year=(latest_annual.fiscal_year if latest_annual else None),
        latest_period_end=(latest_annual.period_end_date if latest_annual else None),
        latest_revenue=(latest_annual.revenue if latest_annual else None),
        latest_net_income=(latest_annual.net_income if latest_annual else None),
    )

    composite_block = scorecard.get("_composite", {}) or {}
    stage = StageView(
        stage=composite_block.get("stage") or fs.company_stage or "mid_cap",
        reasoning=composite_block.get("stage_reasoning") or {},
    )
    composite = CompositeView(
        score=float(fs.composite_score or 0.0),
        verdict=fs.verdict or "monitor",
        mode_resolved=composite_block.get("mode_resolved") or fs.mode or "default",
        weights_used=composite_block.get("weights_used") or {},
        weights_renormalised=bool(composite_block.get("weights_renormalised", False)),
    )

    frameworks = _build_framework_views(scorecard, fs)

    overlay_triggers = []
    if run and run.overlays_triggered_json:
        try:
            triggers_raw = json.loads(run.overlays_triggered_json)
            overlay_triggers = [
                OverlayTriggerView(
                    overlay_type=t.get("overlay_type", "?"),
                    trigger_id=t.get("trigger_id", "?"),
                    condition=t.get("trigger_condition", ""),
                    relevant_numbers=t.get("relevant_numbers", {}),
                    framework_section=t.get("framework_section", ""),
                )
                for t in triggers_raw
                if isinstance(t, dict)
            ]
        except (json.JSONDecodeError, TypeError):
            pass

    fetch_data_gaps: list[str] = []
    if run and run.data_gaps_json:
        try:
            fetch_data_gaps = list(json.loads(run.data_gaps_json) or [])
        except (json.JSONDecodeError, TypeError):
            pass

    # Overlay verdicts (post-trigger deeper-analysis conclusions). Used by
    # narrative._select_archetype to filter out self-disqualified overlays
    # (e.g., PSA-3 fires but verdict="not_a_spinoff_candidate" for a
    # mature issuer — LULU case 2026-05-16).
    overlay_verdicts: dict[str, str] = {}
    if run and run.overlays_results_json:
        try:
            results_raw = json.loads(run.overlays_results_json)
            if isinstance(results_raw, dict):
                for overlay_type, result in results_raw.items():
                    if isinstance(result, dict) and result.get("verdict"):
                        overlay_verdicts[overlay_type] = str(result["verdict"])
        except (json.JSONDecodeError, TypeError):
            pass

    return ScorecardView(
        ticker=ticker,
        run_date=fs.run_date,
        mode_used=fs.mode or "default",
        company=company,
        stage=stage,
        composite=composite,
        frameworks=frameworks,
        overlay_triggers=overlay_triggers,
        fetch_data_gaps=fetch_data_gaps,
        overlay_verdicts=overlay_verdicts,
    )


def load_frozen_scorecard_view(run_id: int) -> ScorecardView | None:
    """The view a dive froze onto its row (DEC-46); None if it has none, its hash does
    not match, or it no longer fits the dataclasses (a later schema change)."""
    with get_session() as s:
        run = s.get(DeepDiveRun, run_id)
        if run is None or not run.scorecard_view_json:
            return None
        body, sha = str(run.scorecard_view_json), run.scorecard_view_sha256
    if sha != hashlib.sha256(body.encode("utf-8")).hexdigest():
        logger.warning("dive %s: frozen view does not match its stored hash", run_id)
        return None
    try:
        return ScorecardView.from_dict(json.loads(body))
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("dive %s: frozen view no longer fits ScorecardView: %r", run_id, exc)
        return None


# ── Internals ─────────────────────────────────────────────────────────────


_FRAMEWORK_TITLES = {
    "F1": "Pre-Discovery Alpha",
    "F2": "Momentum",
    "F3": "Innovation Compounder",
    "F4": "Stealth Accumulation",
    "F5": "Growth Quality",
    "F6": "Platform Dominator",
    "F7": "Smart Beta Timing",
}


def _build_framework_views(scorecard: dict, fs: FrameworkScore) -> list[FrameworkView]:
    """Materialise one FrameworkView per F1..F7.

    Reads from the per-framework block in scorecard_json, falling back to
    the scalar f1_score..f7_score columns when scorecard_json predates the
    current dive shape.
    """
    out: list[FrameworkView] = []
    for code in ("F1", "F2", "F3", "F4", "F5", "F6", "F7"):
        block = scorecard.get(code)
        scalar_score = getattr(fs, f"{code.lower()}_score", None)

        # Unfeasible either way; the difference is whether the dive recorded WHY.
        # Runs predating that persistence have no block, hence the fallback text.
        declared_unfeasible = bool((block or {}).get("is_unfeasible"))
        if declared_unfeasible or (block is None and scalar_score is None):
            out.append(FrameworkView(
                code=code,
                title=_FRAMEWORK_TITLES.get(code, code),
                score=0.0,
                max_score=10.0,
                verdict="unfeasible",
                band="unfeasible",
                key_signals=[],
                data_gaps=list((block or {}).get("data_gaps", []) or []),
                is_unfeasible=True,
                unfeasible_reason=(
                    (block or {}).get("unfeasible_reason")
                    or "no scorecard entry persisted"
                ),
            ))
            continue

        score = float((block or {}).get("score", scalar_score or 0.0))
        verdict = (block or {}).get("verdict") or _verdict_from_score(score)
        signals = (block or {}).get("signals", {}) or {}
        gaps = list((block or {}).get("data_gaps", []) or [])
        notes = (block or {}).get("notes", "") or ""

        key_signals = _extract_key_signals(code, signals)

        out.append(FrameworkView(
            code=code,
            title=_FRAMEWORK_TITLES.get(code, code),
            score=score,
            max_score=10.0,
            verdict=verdict,
            band=_band_from_score(score),
            key_signals=key_signals,
            data_gaps=gaps,
            notes=notes,
        ))
    return out


def _extract_key_signals(code: str, signals: dict) -> list[tuple[str, str]]:
    """Pull the 3-5 most informative signals per framework for display.

    NOT EXHAUSTIVE — full signal payload remains in scorecard_json. This
    is a curated "what the user / LLM should see at a glance" list.
    """
    out: list[tuple[str, str]] = []
    if code == "F1":
        out.append(("Piotroski", f"{signals.get('piotroski_score','?')}/9"))
        ag = (signals.get("asset_growth") or {})
        out.append(("Asset growth band", str(ag.get("decile_band", "?"))))
        ins = (signals.get("insider") or {})
        out.append(("90d open-market buyers", str(ins.get("unique_buyers_90d", "?"))))
        out.append(("Sloan high quality", str(signals.get("sloan_high_quality", "?"))))
        out.append(("GP/A strong", str(signals.get("gp_a_strong", "?"))))
    elif code == "F2":
        mom = signals.get("momentum") or {}
        nh = signals.get("near_52w_high") or {}
        pead = signals.get("pead") or {}
        out.append(("12-1 momentum", _pct(mom.get("return_12_1"))))
        out.append(("% from 52w high", _pct(nh.get("pct_from_high"))))
        out.append(("PEAD signal", str(pead.get("pead_signal", "?"))))
    elif code == "F3":
        gm = signals.get("gm_trajectory") or {}
        rd = signals.get("rd_intensity") or {}
        ss = signals.get("surprise_streak") or {}
        pat = signals.get("patent_disclosure") or {}
        out.append(("Avg GM expansion", f"{gm.get('avg_yoy_bps','?')} bps/yr"))
        # Phase 5S-2: state-aware R&D rendering. `bundled_in_opex` =
        # HIMS-style filer (R&D activity confirmed via tax footnote but
        # not separately tagged in XBRL). `disclosed_exact` = standard
        # ResearchAndDevelopmentExpense line. `not_disclosed` = no
        # evidence either way (treat as data gap).
        rd_state = rd.get("state")
        if rd_state == "bundled_in_opex":
            out.append(("R&D intensity", "bundled in OpEx (tax-credit signal present)"))
            out.append(("R&D band", "bundled_in_opex"))
        else:
            out.append(("R&D intensity", _pct(rd.get("latest_rd_intensity"))))
            out.append(("R&D band", str(rd.get("band", "?"))))
        out.append(("Surprise streak", f"{ss.get('streak','?')} qtrs"))
        # Phase 5k-6 partial: patent count from 10-K text.
        pat_val = pat.get("value")
        if pat_val is not None:
            out.append((
                "Patent portfolio (10-K)",
                f"{pat_val:,} ({pat.get('band', '?')})",
            ))
        else:
            out.append(("Patent portfolio (10-K)", "not_disclosed"))
    elif code == "F4":
        si = signals.get("short_interest") or {}
        ea = signals.get("eps_acceleration") or {}
        out.append(("Short int (current)", f"{si.get('current_pct_float','?')}%"))
        out.append(("Short int (peak)", f"{si.get('peak_pct_float','?')}%"))
        out.append(("Decline signal", str(si.get("decline_signal", "?"))))
        out.append(("EPS acceleration", str(ea.get("band", "?"))))
    elif code == "F5":
        cagr = signals.get("revenue_cagr_3yr") or {}
        fcf = signals.get("fcf_margin") or {}
        roic = signals.get("roic") or {}
        debt = signals.get("debt_ebitda") or {}
        ceo = signals.get("ceo_checklist") or {}
        out.append(("Revenue CAGR 3y", _pct(cagr.get("cagr_3yr"))))
        out.append(("FCF margin", _pct(fcf.get("fcf_margin"))))
        out.append(("ROIC", _pct(roic.get("roic"))))
        out.append(("Debt/EBITDA", str(debt.get("debt_ebitda", "?"))))
        out.append(("CEO alignment", str(ceo.get("band", "?"))))
    elif code == "F6":
        cust = signals.get("customer_concentration") or {}
        gpa = signals.get("gp_a") or {}
        r40 = signals.get("rule_of_40") or {}
        fnd = signals.get("founder_ceo") or {}
        # Phase 5k / DEC-31: relabel `not_disclosed` → `diversified_base_case`.
        # Patatoukas (2012) implicitly treats absence-of-top-customer disclosure
        # as the diversified default. PAYC (36k clients) literally has no top
        # customer to disclose — that's the CORRECT answer, not a data gap.
        # Schema column stays `not_disclosed`; relabel at presentation only.
        _state = cust.get("state", "?")
        _label = {
            "not_disclosed": "diversified_base_case",
            "disclosed_exact": "disclosed",
            "parser_uncertain": "uncertain",
        }.get(_state, str(_state))
        out.append(("Customer concentration", _label))
        # Phase 5k-7: NRR/GRR from 10-K MD&A regex.
        nrr = signals.get("nrr") or {}
        grr = signals.get("grr") or {}
        nrr_val = nrr.get("value")
        grr_val = grr.get("value")
        if nrr_val is not None:
            out.append((
                "NRR (Net Revenue Retention)",
                f"{nrr_val:.1f}% ({nrr.get('band', '?')})",
            ))
        else:
            out.append((
                "NRR (Net Revenue Retention)",
                str(nrr.get("state", "not_disclosed")),
            ))
        if grr_val is not None:
            out.append((
                "GRR (Gross Revenue Retention)",
                f"{grr_val:.1f}% ({grr.get('band', '?')})",
            ))
        else:
            out.append((
                "GRR (Gross Revenue Retention)",
                str(grr.get("state", "not_disclosed")),
            ))
        out.append(("GP/A band", str(gpa.get("band", "?"))))
        out.append(("Rule of 40", str(r40.get("rule_of_40", "?"))))
        out.append(("Fahlenbrach signal", str(fnd.get("fahlenbrach_signal", "?"))))
    elif code == "F7":
        ev = signals.get("ev_revenue_z") or {}
        pb = signals.get("pb_z") or {}
        out.append(("EV/Rev z-score", str(ev.get("z", "?"))))
        out.append(("EV/Rev band", str(ev.get("band", "?"))))
        out.append(("P/B z-score", str(pb.get("z", "?"))))
        out.append(("P/B band", str(pb.get("band", "?"))))
    return out


def _pct(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v * 100:+.1f}%" if abs(v) < 10 else f"{v:+.1f}"


def _band_from_score(score: float) -> str:
    if score >= 7.0:
        return "strong"
    if score >= 4.0:
        return "moderate"
    return "weak"


def _verdict_from_score(score: float) -> str:
    if score >= 7.0:
        return "strong_fit"
    if score >= 4.0:
        return "partial"
    return "fail"


def _json_default(obj: Any) -> Any:
    """Default JSON encoder for date / datetime / dataclass objects."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")
