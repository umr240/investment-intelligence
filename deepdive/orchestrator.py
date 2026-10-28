"""
Deep dive orchestrator.

Pluggable, framework-aware lazy load:
  1. Caller selects a set of frameworks (or a Mode mapping to a set).
  2. Orchestrator merges each framework's DATA_REQUIREMENT into a single
     superset requirement.
  3. orchestrator.refresh_for_dive(ticker, requirement) calls the data
     pipeline, which fetches only what's missing AND only what the
     requirement asks for.
  4. Each framework's score function runs against a CompanyDataReader.
     If a framework cannot run on a recent IPO (insufficient history) it
     raises InsufficientHistoryError; the orchestrator catches this and
     surfaces it as a per-framework "unfeasible" status — never crashes
     the run.

Phases 4+ implement the score functions. Today this module provides the
orchestration scaffolding: requirement merging, refresh dispatch, framework
feasibility checking.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from frameworks.base import (
    DataRequirement,
    FrameworkResult,
    InsufficientHistoryError,
    requirement_for_frameworks,
)
from config.constants import DEFAULT_HISTORY_YEARS

logger = logging.getLogger(__name__)


@dataclass
class DeepDiveOutcome:
    """Aggregate result of a deep-dive run."""
    ticker: str
    mode: str
    selected_frameworks: list[str]
    requirement: DataRequirement
    fetch_gaps: list[str]
    framework_results: dict[str, FrameworkResult]
    framework_unfeasible: dict[str, str]    # framework → reason
    overlay_triggers: list = field(default_factory=list)    # OverlayTrigger list
    # Phase 5M / DEC-33: auto-overlay results are surfaced on the outcome so
    # the CLI renderer can show BEW (mandatory) and ICA/PSA (trigger-gated)
    # uniformly. Keyed by overlay type ('BEW' | 'ICA' | 'PSA') → result dict.
    auto_overlay_results: dict[str, dict] = field(default_factory=dict)
    # Peters-Taylor non-GAAP ROIC computed inline during Phase-1 (ADR-021).
    # Dict keys: value, mode ('full'|'oc_only'|'unavailable'), components,
    # data_gaps, ticker. None when the warehouse company row is missing.
    pt_result: dict | None = None
    # Dual composite results — populated during _persist_dive_results:
    #   composite_gaap: composite using GAAP ROIC for F5 (existing behaviour)
    #   composite_non_gaap: composite using Peters-Taylor ROIC for F5
    #   gaap_non_gaap_gap_pp: |non_gaap - gaap| in percentage points (×100)
    composite_gaap: float | None = None
    composite_non_gaap: float | None = None
    gaap_non_gaap_gap_pp: float | None = None


# ── Mode → framework selection (mirrors PROJECT_SPEC.md Mode A/B/C/D) ──────


_MODE_FRAMEWORKS: dict[str, list[str]] = {
    "A": ["F1", "F2", "F3"],                            # top-journal only
    "B": ["F1", "F2", "F3", "F4", "F5"],                # full academic
    "C": ["F1", "F2", "F3", "F4", "F5", "F6", "F7"],    # all frameworks
}

# Default deep-dive set — runs everything. Frameworks unsuited to the company
# (recent IPO → F7's 10yr z-score, F2's 12-month momentum) are auto-marked
# as unfeasible by `_check_feasibility` rather than crashing.
DEFAULT_FRAMEWORKS: list[str] = list(_MODE_FRAMEWORKS["C"])


def frameworks_for_mode(mode: str) -> list[str]:
    return list(_MODE_FRAMEWORKS.get(mode.upper(), _MODE_FRAMEWORKS["C"]))


# ── Requirement merging entry point ──────────────────────────────────────


def build_requirement(framework_names: Iterable[str]) -> DataRequirement:
    """Public alias — usable from CLI to inspect what would be fetched."""
    return requirement_for_frameworks(framework_names)


# ── Refresh dispatch ─────────────────────────────────────────────────────


async def refresh_for_dive(
    ticker: str,
    framework_names: Iterable[str],
    force_refresh: bool = False,
) -> tuple[DataRequirement, list[str]]:
    """
    Compute the requirement union and call refresh_ticker. Returns the
    merged requirement (so caller can log it) and the gap list.
    """
    from data.pipeline import refresh_ticker

    requirement = requirement_for_frameworks(framework_names)
    if requirement == DataRequirement():
        # No frameworks selected, or none declared anything → no-op refresh.
        logger.info("refresh_for_dive: %s — empty requirement, skipping fetch", ticker)
        return requirement, []

    gaps = await refresh_ticker(
        ticker, force_refresh=force_refresh, requirement=requirement
    )
    return requirement, gaps


# ── Framework dispatch (Phase 4+) ────────────────────────────────────────


def _check_feasibility(
    ticker: str,
    framework_names: Iterable[str],
) -> tuple[list[str], dict[str, str]]:
    """
    Full DATA_REQUIREMENT pre-flight: walk each framework's declared
    requirements and compare against what's actually persisted. Returns
    (feasible, unfeasible) where `unfeasible[name] = reason` for frameworks
    that can't run cleanly.

    Phase 5c expansion: the original gate only covered annual_years /
    quarterly_count / price_history_years. Now also validates the boolean
    requirements (insider, short_interest, institutional, analyst,
    earnings, proxy, customer, founder). When the data backing a boolean
    requirement is empty, the framework is marked UNFEASIBLE — not run
    with score=0. This stops missing-data zeros from polluting composite
    scores; ``compute_composite_score`` renormalises around None.

    The score function itself is still expected to raise InsufficientHistoryError
    if it discovers a finer-grained gap; this pre-flight is the first-line
    filter, not a contract.
    """
    import importlib

    from data.reader import CompanyDataReader
    reader = CompanyDataReader(ticker)
    annuals = sorted(reader.annual_year_set(), reverse=True)
    have_annuals = len(annuals)
    have_quarterlies = len(reader.quarterlies())
    have_price_days = 0
    if reader.price_history(last_n=1):
        latest = reader.price_history(last_n=1)[0]
        oldest = reader.price_history(last_n=10_000)
        if oldest:
            have_price_days = (latest.date - oldest[-1].date).days

    # Coverage probes for the boolean DATA_REQUIREMENT fields. Computed
    # ONCE per ticker (each call is a small SQL count); reused across
    # frameworks. None means "framework didn't ask for this" so we don't
    # emit a misleading reason.
    have_insiders = bool(reader.insider_transactions(within_days=720))
    have_short_interest = bool(reader.short_interest_history(last_n=1))
    have_institutional = bool(reader.institutional_holders())
    have_analyst = reader.latest_analyst_coverage() is not None
    have_earnings = bool(reader.earnings_history(last_n=1))

    company = reader.company_or_none()
    # ADR-018 three-state semantics: a NON-NULL state means the parser ran,
    # whether the result was a value, 'not_disclosed', or 'parser_uncertain'.
    # F5 + F6 know how to score all three (not_disclosed → zero Fahlenbrach
    # credit + note; parser_uncertain → sentinel handling). Only state=NULL
    # is genuine unfeasibility (parser never attempted). Parallels the
    # customer_concentration_state check below.
    have_proxy = company is not None and company.ceo_equity_pct_state is not None
    have_founder = company is not None and company.is_founder_ceo_state is not None
    # F6 feasibility: the parser emits one of three states
    #   {disclosed_exact, parser_uncertain, not_disclosed}
    # All three are *valid* Patatoukas inputs — `not_disclosed` is a
    # genuine diversification signal (zero points + positive note), not a
    # data gap. Only state=NULL means the parser never ran for this
    # ticker, which is the real unfeasibility condition.
    latest_annual = reader.annuals(last_n=1)
    have_customer = (
        bool(latest_annual)
        and latest_annual[0] is not None
        and latest_annual[0].customer_concentration_state is not None
    )

    def _annual_history_reason(needed: int, have: int, company: Any) -> str:
        """Attribute a shortfall to a recent listing only when the date supports it.

        A long-listed issuer that is short a year or two is a backfill gap, not a
        recent IPO — CSGP (listed 1998) was reported as one with 9 of 10 years.
        """
        base = f"insufficient annual history (needs {needed}yr, have {have})"
        ipo = getattr(company, "ipo_date", None) if company is not None else None
        if ipo is None:
            return base
        ipo_year = getattr(ipo, "year", None) or int(str(ipo)[:4])
        listed_years = date.today().year - ipo_year
        if listed_years < needed:
            return f"recent IPO / {base}; listed {listed_years}yr"
        return f"{base}; listed since {ipo_year} — backfill available"

    feasible: list[str] = []
    unfeasible: dict[str, str] = {}

    for name in framework_names:
        name = name.upper()
        module_name = _resolve_module(name)
        if not module_name:
            unfeasible[name] = "unknown framework"
            continue
        try:
            mod = importlib.import_module(module_name)
        except ImportError as exc:
            unfeasible[name] = f"module import failed: {exc}"
            continue

        req = getattr(mod, "DATA_REQUIREMENT", None)
        if req is None:
            feasible.append(name)
            continue

        # ── Numeric history checks ──────────────────────────────────────
        # Gate on what the framework needs to RUN, not on the fetch target,
        # which carries headroom for fiscal years SEC cannot have yet.
        floor = req.min_annual_years or req.annual_years
        if floor and have_annuals < floor:
            unfeasible[name] = _annual_history_reason(
                needed=floor, have=have_annuals, company=company
            )
            continue
        if req.quarterly_count and have_quarterlies < req.quarterly_count:
            unfeasible[name] = (
                f"insufficient quarterly history "
                f"(needs {req.quarterly_count}Q, have {have_quarterlies})"
            )
            continue
        if req.price_history_years:
            need_days = req.price_history_years * 365
            if have_price_days < need_days * 0.9:    # 10% slack for weekends/holidays
                unfeasible[name] = (
                    f"insufficient price history "
                    f"(needs {req.price_history_years}yr, have ~{have_price_days // 365}yr)"
                )
                continue

        # ── Boolean prerequisite checks (Phase 5c) ──────────────────────
        # When a framework declares it needs a data source and that source
        # is empty for this ticker, mark unfeasible. Composite renormalises
        # around the missing framework instead of weighting a 0-from-no-data
        # score as if the framework genuinely scored 0.
        if req.needs_insider_transactions and not have_insiders:
            unfeasible[name] = "no Form 4 insider history persisted (needs_insider_transactions)"
            continue
        if req.needs_short_interest_history and not have_short_interest:
            unfeasible[name] = "no short-interest rows persisted (needs_short_interest_history)"
            continue
        if req.needs_institutional_holders and not have_institutional:
            unfeasible[name] = "no institutional holders persisted (needs_institutional_holders)"
            continue
        if req.needs_analyst_coverage and not have_analyst:
            unfeasible[name] = "no analyst coverage row persisted (needs_analyst_coverage)"
            continue
        if req.needs_earnings_history and not have_earnings:
            unfeasible[name] = "no earnings history persisted (needs_earnings_history)"
            continue
        if req.needs_proxy_ownership and not have_proxy:
            unfeasible[name] = "no DEF 14A proxy ownership persisted (needs_proxy_ownership)"
            continue
        if req.needs_founder_status and not have_founder:
            unfeasible[name] = "founder status not extracted (needs_founder_status)"
            continue
        if req.needs_customer_concentration and not have_customer:
            unfeasible[name] = "no customer concentration extracted (needs_customer_concentration)"
            continue

        feasible.append(name)

    return feasible, unfeasible


async def run_frameworks(
    ticker: str,
    framework_names: Iterable[str],
) -> tuple[dict[str, FrameworkResult], dict[str, str]]:
    """
    Run each selected framework's score function against the persistent store.

    Returns (results, unfeasible) where:
      results[name] = FrameworkResult       (framework ran successfully)
      unfeasible[name] = reason string      (framework couldn't run)

    Flow:
      1. Pre-flight `_check_feasibility` filters out frameworks whose
         DATA_REQUIREMENT exceeds what's in the DB (recent IPO, missing yfinance
         price history, etc).
      2. Surviving frameworks are invoked. If they raise InsufficientHistoryError
         from a finer-grained internal check (e.g. F4 needs 4Q EPS sequence but
         we have 3), they're caught and surface as unfeasible.
      3. NotImplementedError → "pending implementation" (Phase 4 stub).
    """
    import importlib

    from data.reader import CompanyDataReader

    results: dict[str, FrameworkResult] = {}

    feasible, unfeasible = _check_feasibility(ticker, framework_names)

    for name in feasible:
        module_name = _resolve_module(name)
        if not module_name:
            unfeasible[name] = "unknown framework"
            continue
        try:
            mod = importlib.import_module(module_name)
        except ImportError as exc:
            unfeasible[name] = f"module import failed: {exc}"
            continue

        score_fn = getattr(mod, f"score_{name.lower()}", None)
        if score_fn is None:
            unfeasible[name] = "no score function exported"
            continue

        try:
            reader = CompanyDataReader(ticker)
            result = await score_fn(ticker, reader)
            if isinstance(result, FrameworkResult):
                results[name] = result
            else:
                unfeasible[name] = (
                    f"score function returned {type(result).__name__}, "
                    f"expected FrameworkResult"
                )
        except InsufficientHistoryError as exc:
            unfeasible[name] = f"insufficient history ({exc})"
        except NotImplementedError as exc:
            unfeasible[name] = f"pending implementation ({exc})"
        except Exception as exc:    # noqa: BLE001 — orchestrator must catch all
            unfeasible[name] = f"runtime error: {exc}"

    return results, unfeasible


def _resolve_module(framework_name: str) -> str | None:
    from frameworks.base import _FRAMEWORK_MODULES  # type: ignore[attr-defined]
    return _FRAMEWORK_MODULES.get(framework_name.upper())


# ── Tier 1 / Tier 2 entry points (used by CLI) ───────────────────────────


async def run_tier1(
    ticker: str,
    mode: str | None = None,
    framework_names: Iterable[str] | None = None,
    force_refresh: bool = False,
) -> DeepDiveOutcome:
    """
    Tier-1 quick deep-dive.

    Selection precedence (most specific wins):
      1. explicit `framework_names` — run exactly those (user override)
      2. `mode` (A/B/C) — preset framework groups
      3. else — default to all 7 frameworks (orchestrator marks any that the
         company isn't suitable for as 'unfeasible' rather than crashing).

    The recent-IPO case is handled by `_check_feasibility` after the data
    refresh: F7 (10yr) and F2 (12-month momentum) auto-skip if the company
    hasn't been listed long enough.
    """
    if framework_names:
        selected = [f.upper() for f in framework_names]
    elif mode:
        selected = frameworks_for_mode(mode)
    else:
        selected = list(DEFAULT_FRAMEWORKS)

    requirement, gaps = await refresh_for_dive(ticker, selected, force_refresh=force_refresh)

    # ── Peters-Taylor non-GAAP ROIC (ADR-021) ─────────────────────────────
    # Auto-trigger inline so the dive always has a fresh non-GAAP read,
    # rather than depending on the bulk warehouse FundamentalsTask cadence
    # (90d). Persists pt_adjusted_roic on Company when computable. Falls
    # back to OC-only Eisfeldt-Papanikolaou (2013) when the company doesn't
    # disclose R&D as a separate XBRL fact.
    pt_result: dict | None = None
    try:
        from screener.tasks.fundamentals import compute_pt_for_ticker
        pt_result = compute_pt_for_ticker(ticker.upper(), persist=True)
    except Exception as exc:    # noqa: BLE001
        logger.debug("Peters-Taylor compute failed for %s: %s", ticker, exc)

    results, unfeasible = await run_frameworks(ticker, selected)

    # ── Auto-extend on unfeasible due to insufficient history ────────────
    # When F3/F5/F7 declare DATA_REQUIREMENT.annual_years=5 but the company
    # has 7-9 years available (e.g. PAYC with FY2017-FY2025), the parser's
    # default cap may have left those frameworks short. Detect "insufficient
    # history" reasons and retry once with annual_years=10. Cap at one retry
    # so a recent IPO with genuinely <5 years still terminates.
    if (
        _has_history_unfeasible(unfeasible)
        and (requirement.annual_years or 0) < DEFAULT_HISTORY_YEARS
    ):
        from data.pipeline import refresh_ticker
        from frameworks.base import replace as _dc_replace
        extended_req = _dc_replace(
            requirement,
            annual_years=DEFAULT_HISTORY_YEARS,
            price_history_years=max(
                requirement.price_history_years or 0, DEFAULT_HISTORY_YEARS
            ),
        )
        try:
            extra_gaps = await refresh_ticker(
                ticker.upper(), force_refresh=False, requirement=extended_req,
            )
            # Dedupe on extend. The retry re-runs the SAME fetch, so every
            # persistent gap (ESEF index lag, quarterly supplementation,
            # jurisdiction-absent Form 4, missing short interest) is emitted a
            # second time and the dive rendered each one twice. Order-preserving
            # so the original sequence still reads as the fetch produced it.
            _seen = set(gaps)
            gaps.extend(g for g in (extra_gaps or []) if not (g in _seen or _seen.add(g)))
            results, unfeasible = await run_frameworks(ticker, selected)
            requirement = extended_req
        except Exception as exc:    # noqa: BLE001
            import logging
            logging.getLogger(__name__).debug(
                "auto-extend refresh failed (%s): %s", ticker, exc,
            )

    # Overlay-trigger detection. Per DEC-30 (Phase 5j) + DEC-33 (Phase 5M):
    # ICA + PSA are TRIGGER-GATED — auto-run only when their detector
    # conditions fire. BEW is MANDATORY — runs on every dive regardless
    # of trigger conditions per the methodology decision that every
    # long-horizon investor must confront Bessembinder's 4%-of-stocks
    # question on every name (not just those passing pre-screens).
    # Each overlay still produces a structured dict; only ICA restates a
    # metric (PT ROIC). PSA/BEW contribute small bounded bonuses
    # (capped at TOTAL_OVERLAY_BONUS_CAP combined) so Goodhart risk
    # stays low. BEW returns verdict="no_winner_pattern" with 0 bonus
    # for the 96% of names that aren't extreme-winner candidates —
    # mandatory execution doesn't inflate composites, it forces an
    # explicit "no" rather than a silent skip.
    overlay_triggers: list = []
    auto_overlay_results: dict[str, dict] = {}
    try:
        from data.reader import CompanyDataReader
        from overlays.detector import scan_for_triggers
        reader = CompanyDataReader(ticker.upper())
        results_for_scan = dict(results)
        # Stash unfeasible map under a sentinel key so the detector's
        # PSA-3 trigger can read F7's unfeasible reason.
        results_for_scan["__unfeasible__"] = unfeasible
        overlay_triggers = scan_for_triggers(
            ticker.upper(), reader=reader, framework_results=results_for_scan,
        )
        triggered_types = {
            getattr(t, "overlay_type", "") for t in overlay_triggers
        }
        if "ICA" in triggered_types:
            try:
                from overlays.ica import run_ica
                ica_result = await run_ica(ticker.upper(), reader=reader)
                if isinstance(ica_result, dict):
                    auto_overlay_results["ICA"] = ica_result
            except Exception as exc:    # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(
                    "auto-ICA failed for %s: %s", ticker, exc,
                )
        if "PSA" in triggered_types:
            try:
                from overlays.psa import run_psa
                psa_result = await run_psa(ticker.upper(), reader=reader)
                if isinstance(psa_result, dict):
                    auto_overlay_results["PSA"] = psa_result
            except Exception as exc:    # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(
                    "auto-PSA failed for %s: %s", ticker, exc,
                )
        # BEW is MANDATORY per DEC-33 — runs on every dive regardless of
        # whether BEW-1..5 triggers fire. Bessembinder (1926-2016)
        # empirical work shows 4% of stocks deliver all wealth; every
        # long-horizon investor confronts this on every name. Returns
        # verdict="no_winner_pattern" cleanly for non-candidates, so
        # mandatory execution costs ~80ms per dive and yields an
        # explicit "no" instead of a silent skip.
        try:
            from overlays.bew import run_bew
            f3_res = results.get("F3")
            f3_score = float(getattr(f3_res, "score", None)) if f3_res else None
            bew_result = await run_bew(
                ticker.upper(), reader=reader, f3_score=f3_score,
            )
            if isinstance(bew_result, dict):
                auto_overlay_results["BEW"] = bew_result
        except Exception as exc:    # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "BEW (mandatory) failed for %s: %s", ticker, exc,
            )

        # SIM (Structural Intelligence Moat) — DEC-33 / Phase 5N. Soft
        # overlay scored only for technology-sector tickers. NOT added
        # to composite_score; surfaces as a separate panel. Tagged ◯
        # heuristic-tier per scope decision. AI-relevant sector gate is
        # inside run_sim() — non-tech tickers return ok=False cleanly
        # so no SIM key lands in auto_overlay_results for non-tech.
        try:
            from overlays.sim import is_ai_relevant_sector, run_sim
            company = reader.company_or_none()
            sector = getattr(company, "sector", None) if company else None
            industry = getattr(company, "industry", None) if company else None
            if is_ai_relevant_sector(sector, industry):
                # Pull 10-K Item 1 + Item 7 text for SIM-3 ontology regex
                tenk_text = ""
                business_desc = ""
                try:
                    from data.edgar_fetcher import (
                        _read_tenk_sections,
                        fetch_latest_10k_filing,
                    )
                    filing = fetch_latest_10k_filing(ticker.upper())
                    if filing is not None:
                        tk = filing.obj() if hasattr(filing, "obj") else filing
                        sections = _read_tenk_sections(tk)
                        if sections:
                            tenk_text = "\n\n".join(sections.values())
                            business_desc = sections.get("Item 1", "")
                except Exception as exc:    # noqa: BLE001
                    import logging
                    logging.getLogger(__name__).debug(
                        "SIM 10-K section fetch failed for %s: %s", ticker, exc,
                    )
                sim_result = await run_sim(
                    ticker.upper(),
                    sector=sector, industry=industry,
                    tenk_text=tenk_text, business_description=business_desc,
                )
                if isinstance(sim_result, dict) and sim_result.get("ok"):
                    auto_overlay_results["SIM"] = sim_result
        except Exception as exc:    # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "SIM (soft overlay) failed for %s: %s", ticker, exc,
            )
    except Exception as exc:    # noqa: BLE001
        import logging
        logging.getLogger(__name__).debug(
            "overlay trigger scan failed for %s: %s", ticker, exc,
        )

    composite_gaap: float | None = None
    composite_non_gaap: float | None = None
    try:
        composite_gaap, composite_non_gaap, run_id = _persist_dive_results(
            ticker=ticker.upper(),
            mode=mode or "default",
            tier=1,
            results=results,
            unfeasible=unfeasible,
            fetch_gaps=gaps,
            overlay_triggers=overlay_triggers,
            auto_overlay_results=auto_overlay_results,
            pt_result=pt_result,
        )
        if run_id is not None:
            try:
                _record_scorecard_view(run_id, ticker.upper(), mode or "default")
            except Exception as exc:  # noqa: BLE001
                gaps.append(
                    f"{ticker.upper()}: scorecard view not recorded on dive {run_id} ({exc})"
                )
    except Exception as exc:    # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("dive persistence failed (%s): %s", ticker, exc)
    gap_pp: float | None = None
    if composite_gaap is not None and composite_non_gaap is not None:
        gap_pp = round((composite_non_gaap - composite_gaap), 4)
    return DeepDiveOutcome(
        ticker=ticker.upper(),
        mode=mode or "default",
        selected_frameworks=selected,
        requirement=requirement,
        fetch_gaps=gaps,
        framework_results=results,
        framework_unfeasible=unfeasible,
        overlay_triggers=overlay_triggers,
        auto_overlay_results=auto_overlay_results,
        pt_result=pt_result,
        composite_gaap=composite_gaap,
        composite_non_gaap=composite_non_gaap,
        gaap_non_gaap_gap_pp=gap_pp,
    )


def _has_history_unfeasible(unfeasible: dict[str, str]) -> bool:
    """Return True iff at least one framework was marked unfeasible due to
    insufficient annual / price history. Used to gate the auto-extend retry.
    """
    if not unfeasible:
        return False
    keywords = ("insufficient history", "insufficient annual", "needs", "ipo")
    for reason in unfeasible.values():
        r = (reason or "").lower()
        if any(k in r for k in keywords):
            return True
    return False


def _f5_roic_points(roic: float | None) -> float:
    """Replicate frameworks.f5_growth_quality._compute_roic banding so we
    can recompute F5's ROIC contribution from a substituted ROIC value
    (Peters-Taylor non-GAAP) without re-running the whole framework. Stays
    in sync with F5's ROIC_TARGET / ROIC_PARTIAL / ROIC_FLOOR thresholds.
    """
    from frameworks.f5_growth_quality import (
        ROIC_FLOOR,
        ROIC_MAX,
        ROIC_PARTIAL,
        ROIC_TARGET,
    )
    if roic is None:
        return 0.0
    if roic >= ROIC_TARGET:
        return ROIC_MAX
    if roic >= ROIC_PARTIAL:
        return 1.5
    if roic >= ROIC_FLOOR:
        return 0.5
    return 0.0


def _alt_f5_score(
    original_result, pt_roic: float | None,
) -> float | None:
    """Substitute Peters-Taylor ROIC into F5 and return the rebalanced
    F5 score. Pure delta math: only the ROIC component changes; the other
    six F5 components (CAGR, FCF margin, GP/A, debt, buyback, CEO) are
    unaffected. Returns None when the original F5 didn't run or pt_roic
    is None.
    """
    if original_result is None or pt_roic is None:
        return None
    original_score = float(getattr(original_result, "score", 0.0) or 0.0)
    signals = getattr(original_result, "signals", {}) or {}
    roic_block = signals.get("roic") or {}
    original_roic_pts = float(roic_block.get("points") or 0.0)
    new_roic_pts = _f5_roic_points(pt_roic)
    delta = new_roic_pts - original_roic_pts
    alt_score = round(min(max(original_score + delta, 0.0), 10.0), 2)
    return alt_score


def _record_scorecard_view(run_id: int, ticker: str, mode: str) -> None:
    """DEC-46: freeze the ScorecardView this dive produced onto its row, with its hash."""
    import hashlib

    from data.db import get_session
    from data.models.schema import DeepDiveRun
    from deepdive.scorecard_view import load_scorecard_view

    view = load_scorecard_view(ticker, mode=mode, run_id=run_id)
    if view is None:
        raise RuntimeError("no scorecard view for the run just persisted")
    body = view.to_llm_context()
    with get_session() as session:
        run = session.get(DeepDiveRun, run_id)
        if run is not None:
            run.scorecard_view_json = body
            run.scorecard_view_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()


def _persist_dive_results(
    *, ticker: str, mode: str, tier: int,
    results: dict, unfeasible: dict, fetch_gaps: list[str],
    overlay_triggers: list | None = None,
    auto_overlay_results: dict | None = None,
    pt_result: dict | None = None,
) -> tuple[float | None, float | None, int | None]:
    """Write the dive's framework scores into framework_scores + deepdive_runs.

    Composite is stage-weighted per PROJECT_SPEC §4.4 (replaces the earlier
    simple-average). Stage = pre_profitability | mid_cap | established
    via `frameworks.composite.classify_company_stage`. When a framework
    is unfeasible (e.g. F7 on recent IPO) its weight is renormalised
    among the remaining frameworks rather than dragging composite to zero.

    Idempotent per (ticker, run_date) — multiple dives the same day update
    the existing row. Cross-day dives create new history.
    """
    import json
    from datetime import date as _date

    from data.db import get_session
    from data.dive_staleness import (
        fundamentals_digest,
        fundamentals_parser_version,
        latest_10k_accession,
    )
    from data.models.schema import Company, DeepDiveRun, FrameworkScore
    from data.reader import CompanyDataReader
    from frameworks.composite import classify_company_stage, compute_composite_score

    today = _date.today()
    # score_map values are typed as Optional[float]; None = framework absent.
    score_map: dict[str, float | None] = {}
    signals_map: dict[str, dict] = {}
    for name, res in results.items():
        score_map[name.upper()] = float(getattr(res, "score", 0.0) or 0.0)
        signals_map[name.upper()] = getattr(res, "signals", {}) or {}

    # Classify stage from persisted data (deterministic, no API call).
    reader = CompanyDataReader(ticker)
    stage = classify_company_stage(reader)

    # Apply stage-weighted composite per PROJECT_SPEC §4.4.
    composite_out = compute_composite_score(
        score_map, mode=mode, stage=stage.stage,
    )
    composite_pre_overlays = composite_out.score
    overlay_bonus, overlay_bonus_breakdown = _compute_overlay_composite_bonus(
        auto_overlay_results or {},
        original_f5_verdict=getattr(results.get("F5"), "verdict", None),
    )
    composite = _apply_overlay_bonus(composite_pre_overlays, overlay_bonus)
    verdict = composite_out.verdict

    # ── Dual composite (ADR-021): GAAP vs Peters-Taylor non-GAAP ─────────
    # The framework-weighted composite above uses F5 with GAAP ROIC. We
    # additionally compute a parallel composite that substitutes Peters-
    # Taylor non-GAAP ROIC into F5 (ROIC component re-banded; other six
    # F5 components unchanged). When the GAAP↔non-GAAP gap is small the
    # two composites are nearly identical; when it's large, the divergence
    # is itself the signal — surfaces in the CLI as side-by-side numbers.
    pt_value = (pt_result or {}).get("value")
    pt_mode = (pt_result or {}).get("mode")
    composite_non_gaap = composite       # default fallback when PT unavailable
    composite_non_gaap_pre_overlays = composite_pre_overlays
    f5_score_non_gaap = score_map.get("F5")
    if pt_value is not None:
        f5_score_non_gaap = _alt_f5_score(results.get("F5"), pt_value)
        if f5_score_non_gaap is not None:
            alt_score_map = dict(score_map)
            alt_score_map["F5"] = f5_score_non_gaap
            alt_out = compute_composite_score(
                alt_score_map, mode=mode, stage=stage.stage,
            )
            composite_non_gaap_pre_overlays = alt_out.score
            composite_non_gaap = _apply_overlay_bonus(alt_out.score, overlay_bonus)

    composite_gaap = composite       # alias for return clarity

    framework_results_json = json.dumps({
        "_composite": {
            "score": composite,
            "score_pre_overlays": composite_pre_overlays,
            "score_non_gaap": composite_non_gaap,
            "score_non_gaap_pre_overlays": composite_non_gaap_pre_overlays,
            "f5_score_gaap": score_map.get("F5"),
            "f5_score_non_gaap": f5_score_non_gaap,
            "pt_roic": pt_value,
            "pt_mode": pt_mode,
            "overlay_bonus": round(overlay_bonus, 4),
            "overlay_bonus_breakdown": overlay_bonus_breakdown,
            "verdict": verdict,
            "mode_resolved": composite_out.mode_resolved,
            "stage": stage.stage,
            "stage_reasoning": stage.reasoning,
            "weights_used": composite_out.weights_used,
            "weights_renormalised": composite_out.weights_renormalised,
        },
        **{
            name: {
                "score": getattr(res, "score", None),
                "verdict": getattr(res, "verdict", None),
                "signals": getattr(res, "signals", {}),
                "data_gaps": getattr(res, "data_gaps", []),
                "notes": getattr(res, "notes", ""),
            }
            for name, res in results.items()
        },
        # Unfeasible frameworks were computed and then dropped, so the UI could
        # only report "no scorecard entry persisted" — the reason existed at dive
        # time and was thrown away. An explicit gap is the whole point.
        **{
            name: {
                "score": None,
                "verdict": None,
                "is_unfeasible": True,
                "unfeasible_reason": reason,
                "signals": {},
                "data_gaps": [],
                "notes": "",
            }
            for name, reason in (unfeasible or {}).items()
            if name not in results
        },
    }, default=str)
    data_gaps_json = json.dumps(list(fetch_gaps or []))

    with get_session() as session:
        company = session.query(Company).filter_by(ticker=ticker).first()
        if not company:
            return None, None, None  # ticker not yet in DB; persistence is best-effort

        # ── framework_scores upsert (one row per ticker per day) ─────────
        existing = (
            session.query(FrameworkScore)
            .filter_by(company_id=company.id, run_date=today, mode=mode)
            .first()
        )
        target = existing or FrameworkScore(
            company_id=company.id, run_date=today, mode=mode,
        )
        target.company_stage = stage.stage
        target.f1_score = score_map.get("F1")
        target.f2_score = score_map.get("F2")
        target.f3_score = score_map.get("F3")
        target.f4_score = score_map.get("F4")
        target.f5_score = score_map.get("F5")
        target.f6_score = score_map.get("F6")
        target.f7_score = score_map.get("F7")
        target.composite_score = composite
        target.verdict = verdict
        target.piotroski_score = (
            signals_map.get("F1", {}).get("piotroski_score")
        )
        target.scorecard_json = framework_results_json
        if existing is None:
            session.add(target)

        # ── Overlay persistence ──────────────────────────────────────────
        # Triggers: every detected trigger goes to overlays_triggered_json.
        # Results: ICA + PSA + BEW results from auto-run (Phase 5j / DEC-30)
        # go to overlays_results_json AND set the per-overlay flags on
        # FrameworkScore (overlay_ica_run / overlay_psa_run / overlay_bew_run)
        # plus a structured overlay_notes summary.
        overlays_triggered_json = json.dumps(
            [
                trig.to_dict() if hasattr(trig, "to_dict") else trig
                for trig in (overlay_triggers or [])
            ],
            default=str,
        )
        overlay_results = auto_overlay_results or {}
        overlays_results_json = (
            json.dumps(overlay_results, default=str) if overlay_results else None
        )
        existing_notes = target.overlay_notes
        if existing_notes:
            try:
                notes_dict = json.loads(existing_notes)
            except (json.JSONDecodeError, TypeError):
                notes_dict = {}
        else:
            notes_dict = {}

        ica_result = overlay_results.get("ICA")
        if ica_result is not None:
            target.overlay_ica_run = True
            notes_dict["ICA"] = {
                "verdict": ica_result.get("verdict"),
                "adj_roic": ica_result.get("adj_roic"),
                "f5_verdict_revised": ica_result.get("f5_verdict_revised"),
            }

        psa_result = overlay_results.get("PSA")
        if psa_result is not None:
            target.overlay_psa_run = True
            notes_dict["PSA"] = {
                "verdict": psa_result.get("verdict"),
                "structural_score": (
                    psa_result.get("structural_mispricing", {}).get("score")
                    if isinstance(psa_result.get("structural_mispricing"), dict)
                    else None
                ),
                "documented_excess": (
                    psa_result.get("desai_jain_focus_test", {}).get("documented_excess_return")
                    if isinstance(psa_result.get("desai_jain_focus_test"), dict)
                    else None
                ),
            }

        bew_result = overlay_results.get("BEW")
        if bew_result is not None:
            target.overlay_bew_run = True
            notes_dict["BEW"] = {
                "verdict": bew_result.get("verdict"),
                "score": bew_result.get("score"),
                "n_evaluable": bew_result.get("n_checks_evaluable"),
            }

        notes_dict["_composite_overlay_bonus"] = {
            "applied": round(overlay_bonus, 4),
            "breakdown": overlay_bonus_breakdown,
        }
        if notes_dict:
            try:
                target.overlay_notes = json.dumps(notes_dict, default=str)
            except Exception as exc:    # noqa: BLE001
                import logging
                logging.getLogger(__name__).debug(
                    "overlay notes write failed for %s: %s", ticker, exc,
                )

        # ── deepdive_runs append (one row per dive run, full history) ────
        run = DeepDiveRun(
            company_id=company.id,
            ticker=ticker,
            tier=tier,
            mode=mode,
            composite_score=composite,
            verdict=verdict,
            f1_score=score_map.get("F1"),
            f2_score=score_map.get("F2"),
            f3_score=score_map.get("F3"),
            f4_score=score_map.get("F4"),
            f5_score=score_map.get("F5"),
            f6_score=score_map.get("F6"),
            f7_score=score_map.get("F7"),
            framework_results_json=framework_results_json,
            data_gaps_json=data_gaps_json,
            overlays_triggered_json=overlays_triggered_json,
            overlays_results_json=overlays_results_json,
            parser_version=fundamentals_parser_version(session, ticker),
            edgar_10k_accession=latest_10k_accession(session, ticker),
            inputs_sha256=fundamentals_digest(session, ticker),
        )
        session.add(run)
        session.flush()
        run_id = int(run.id)

    return composite_gaap, composite_non_gaap, run_id


# ── Overlay → composite bonus helpers (Phase 5j / DEC-30) ──────────────────
#
# Each auto-run overlay can lift the framework-weighted composite by a
# small, capped amount. The cap (TOTAL_OVERLAY_BONUS_CAP = 1.0) keeps
# overlay influence < ~10% of the 0-10 composite scale, so a strong
# framework signal still dominates. Conservative bonuses by design —
# the ROIC restatement (ICA's headline contribution) is already baked
# into Company.pt_adjusted_roic at the screener level (DEC-28); this
# additive bonus is for the *dive*-level composite where stage-weighted
# framework scores are summed.
ICA_BONUS_PER_VERDICT_BAND = 0.30
ICA_MAX_BONUS = 0.60
PSA_BONUS_STRONG = 0.50
PSA_BONUS_MODERATE = 0.25
BEW_BONUS_EXTREME = 0.50
BEW_BONUS_MODERATE = 0.25
TOTAL_OVERLAY_BONUS_CAP = 1.0

_VERDICT_RANK = {"fail": 0, "partial": 1, "strong_fit": 2}


def _apply_overlay_bonus(composite: float | None, bonus: float) -> float | None:
    """The dive composite: framework composite plus the capped bonus, clamped at 10."""
    return None if composite is None else round(min(composite + bonus, 10.0), 4)


def _compute_overlay_composite_bonus(
    auto_overlay_results: dict[str, dict],
    *,
    original_f5_verdict: str | None,
) -> tuple[float, dict[str, float]]:
    """Translate auto-run overlay verdicts into a capped composite bonus.

    Returns (total_bonus, breakdown). Each breakdown entry is the bonus
    contributed by that overlay BEFORE the global cap is applied. The
    returned total is post-cap.
    """
    breakdown: dict[str, float] = {}

    ica = auto_overlay_results.get("ICA") or {}
    if isinstance(ica, dict) and ica.get("ok") is True:
        revised = ica.get("f5_verdict_revised")
        original_rank = _VERDICT_RANK.get((original_f5_verdict or "").lower())
        revised_rank = _VERDICT_RANK.get((revised or "").lower())
        if original_rank is not None and revised_rank is not None:
            steps_up = max(0, revised_rank - original_rank)
            ica_bonus = min(steps_up * ICA_BONUS_PER_VERDICT_BAND, ICA_MAX_BONUS)
        else:
            ica_bonus = 0.0
        if ica_bonus > 0:
            breakdown["ICA"] = round(ica_bonus, 4)

    psa = auto_overlay_results.get("PSA") or {}
    if isinstance(psa, dict) and psa.get("ok") is True:
        v = (psa.get("verdict") or "").lower()
        if v == "strong_psa_candidate":
            breakdown["PSA"] = PSA_BONUS_STRONG
        elif v == "moderate_psa_candidate":
            breakdown["PSA"] = PSA_BONUS_MODERATE

    bew = auto_overlay_results.get("BEW") or {}
    if isinstance(bew, dict) and bew.get("ok") is True:
        v = (bew.get("verdict") or "")
        if v == "EXTREME_WINNER_CANDIDATE":
            breakdown["BEW"] = BEW_BONUS_EXTREME
        elif v == "moderate_winner_candidate":
            breakdown["BEW"] = BEW_BONUS_MODERATE

    raw_total = sum(breakdown.values())
    capped = min(raw_total, TOTAL_OVERLAY_BONUS_CAP)
    if raw_total > TOTAL_OVERLAY_BONUS_CAP and raw_total > 0:
        # Pro-rate breakdown so the user can see what was clipped.
        scale = TOTAL_OVERLAY_BONUS_CAP / raw_total
        breakdown = {k: round(v * scale, 4) for k, v in breakdown.items()}
    return capped, breakdown


async def run_tier2(
    ticker: str,
    mode: str | None = None,
    framework_names: Iterable[str] | None = None,
    force_refresh: bool = False,
) -> DeepDiveOutcome:
    """
    Tier-2 full deep-dive — same dispatch shape as tier-1, plus overlay
    detection (Phase 5).
    """
    return await run_tier1(ticker, mode, framework_names, force_refresh=force_refresh)
