"""
Base types shared across all framework modules.

Public surface:
  - FrameworkResult        standardised output from any F1–F7 scorer
  - MissingDataError       raised when a required field is unavailable
  - InsufficientHistoryError raised when too few periods exist
                              (e.g. recent IPO with <2 annuals for Piotroski)
  - DataRequirement        per-framework declaration of what data it needs
  - merge_requirements     union the requirements across selected frameworks
                            so the pipeline fetches the minimum superset
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal
from config.constants import DEFAULT_HISTORY_YEARS


# ── Output types ──────────────────────────────────────────────────────────


@dataclass
class FrameworkResult:
    framework: str                                      # 'F1' | 'F2' | ... | 'F7'
    score: float                                        # 0.0 – 10.0
    max_score: float = 10.0
    signals: dict[str, Any] = field(default_factory=dict)
    verdict: Literal["strong_fit", "partial", "fail"] = "fail"
    data_gaps: list[str] = field(default_factory=list)
    overlay_triggers: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def score_pct(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0

    @property
    def is_strong(self) -> bool:
        return self.score >= 7.0

    @property
    def is_partial(self) -> bool:
        return 4.0 <= self.score < 7.0


# ── Exceptions ────────────────────────────────────────────────────────────


class MissingDataError(Exception):
    """A required field was unavailable from any data source."""
    def __init__(self, field_name: str, source: str, ticker: str) -> None:
        self.field_name = field_name
        self.source = source
        self.ticker = ticker
        super().__init__(
            f"[{ticker}] Missing required field '{field_name}' from source: {source}"
        )


class InsufficientHistoryError(Exception):
    """
    Raised when a framework needs N periods of history but the database has
    fewer. Common case: recently-IPO'd companies. The orchestrator catches
    this and surfaces it as a per-framework "unfeasible: insufficient history"
    in the deep-dive output rather than failing the whole run.
    """
    def __init__(self, framework: str, needed: int, got: int, period_kind: str = "annual") -> None:
        self.framework = framework
        self.needed = needed
        self.got = got
        self.period_kind = period_kind
        super().__init__(
            f"{framework} requires {needed} {period_kind} period(s); only {got} available"
        )


# ── Per-framework data requirements ───────────────────────────────────────


@dataclass(frozen=True)
class DataRequirement:
    """
    What a framework needs from the persistent store. The deep-dive
    orchestrator unions these across the requested frameworks and passes
    the result to refresh_ticker(), which fetches the minimum superset.

    All numeric fields default to 0 / False — a framework only opts in to
    what it actually uses, so an F1-only deep dive doesn't trigger a 10yr
    fetch.
    """
    annual_years: int = 0                       # last N annual Financial periods to FETCH
    # Minimum annual periods needed to RUN, when lower than the fetch target.
    # The two are distinct: the year-coverage gate anchors its window on the
    # current calendar year, so a fetch target must carry headroom for fiscal
    # years SEC cannot have yet — while the feasibility floor must stay at what
    # the score function actually enforces. Conflating them means asking for
    # headroom makes a framework fail its own pre-flight (ADR-030-A2).
    min_annual_years: int | None = None
    quarterly_count: int = 0                    # last N quarterly Financial periods
    price_history_years: int = 0                # 0 = skip yfinance .history() download
    needs_insider_transactions: bool = False    # F1 cluster, F4 stealth (Form 4)
    needs_proxy_ownership: bool = False         # F5/F6 CEO equity (DEF 14A HTML)
    needs_customer_concentration: bool = False  # F6 (XBRL + 10-K text regex)
    needs_founder_status: bool = False          # F5/F6 (10-K + DEF 14A regex)
    needs_analyst_coverage: bool = False        # F1 neglect, F4
    needs_short_interest_history: bool = False  # F4 (snapshots accumulate)
    needs_institutional_holders: bool = False   # F4
    needs_earnings_history: bool = False        # F3 surprise streak, F4 PEAD
    needs_retention_metrics: bool = False       # F6 NRR/GRR (10-K MD&A regex, 5k-7)
    needs_patent_disclosure: bool = False       # F3 patent count (10-K text regex, 5k-6 partial)
    needs_arr_metrics: bool = False             # F5 Cloud ARR + Total ARR (ADR-026 5Q-5)


def merge_requirements(reqs: Iterable[DataRequirement]) -> DataRequirement:
    """
    Union the requirements across selected frameworks. Numeric fields take
    max; boolean fields take any. Returns a no-op (all-zero) requirement if
    `reqs` is empty.
    """
    reqs_list = list(reqs)
    if not reqs_list:
        return DataRequirement()
    return DataRequirement(
        annual_years=max(r.annual_years for r in reqs_list),
        min_annual_years=max(
            (r.min_annual_years for r in reqs_list if r.min_annual_years is not None),
            default=None,
        ),
        quarterly_count=max(r.quarterly_count for r in reqs_list),
        price_history_years=max(r.price_history_years for r in reqs_list),
        needs_insider_transactions=any(r.needs_insider_transactions for r in reqs_list),
        needs_proxy_ownership=any(r.needs_proxy_ownership for r in reqs_list),
        needs_customer_concentration=any(r.needs_customer_concentration for r in reqs_list),
        needs_founder_status=any(r.needs_founder_status for r in reqs_list),
        needs_analyst_coverage=any(r.needs_analyst_coverage for r in reqs_list),
        needs_short_interest_history=any(r.needs_short_interest_history for r in reqs_list),
        needs_institutional_holders=any(r.needs_institutional_holders for r in reqs_list),
        needs_earnings_history=any(r.needs_earnings_history for r in reqs_list),
        needs_retention_metrics=any(r.needs_retention_metrics for r in reqs_list),
        needs_patent_disclosure=any(r.needs_patent_disclosure for r in reqs_list),
        needs_arr_metrics=any(r.needs_arr_metrics for r in reqs_list),
    )


def screener_data_requirement() -> DataRequirement:
    """
    Minimum data needed for the screener's Tier 5 hard gates.

    Excludes the dive-only sources (Form 4, DEF 14A, 10-K text, full
    institutional holders) — those are too heavy to fetch for ~300
    shortlist candidates and the screener gates don't need them.
    """
    return DataRequirement(
        annual_years=3,                       # G4 asset growth YoY, G6 Piotroski, 3yr CAGR
        quarterly_count=4,                    # for TTM-equivalent computation
        price_history_years=2,                # G7 12-month momentum + decile rank
        needs_insider_transactions=False,
        needs_proxy_ownership=False,
        needs_customer_concentration=False,
        needs_founder_status=False,
        needs_analyst_coverage=True,          # G3 analyst ≥ 1
        needs_short_interest_history=False,
        needs_institutional_holders=False,
        needs_earnings_history=False,
    )


def kitchen_sink_requirement(years: int = DEFAULT_HISTORY_YEARS) -> DataRequirement:
    """
    Convenience builder for the legacy `years=N` knob — returns a requirement
    that fetches everything (used by `invest data refresh TICKER` when no
    framework selection is given). Bound by `years` on historical depth.
    """
    return DataRequirement(
        annual_years=years,
        quarterly_count=max(years, 8),
        price_history_years=years,
        needs_insider_transactions=True,
        needs_proxy_ownership=True,
        needs_customer_concentration=True,
        needs_founder_status=True,
        needs_analyst_coverage=True,
        needs_short_interest_history=True,
        needs_institutional_holders=True,
        needs_earnings_history=True,
        needs_retention_metrics=True,
        needs_patent_disclosure=True,
        needs_arr_metrics=True,
    )


def requirement_for_frameworks(framework_names: Iterable[str]) -> DataRequirement:
    """
    Look up each framework's DATA_REQUIREMENT module-level constant and merge.
    Unknown framework names are silently dropped (caller validates).
    """
    import importlib
    reqs: list[DataRequirement] = []
    for name in framework_names:
        module_name = _FRAMEWORK_MODULES.get(name.upper())
        if not module_name:
            continue
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            continue
        req = getattr(mod, "DATA_REQUIREMENT", None)
        if isinstance(req, DataRequirement):
            reqs.append(req)
    return merge_requirements(reqs)


# Registry of framework name → module path. Source of truth for `--frameworks`.
_FRAMEWORK_MODULES: dict[str, str] = {
    "F1": "frameworks.f1_pre_discovery",
    "F2": "frameworks.f2_momentum",
    "F3": "frameworks.f3_innovation",
    "F4": "frameworks.f4_stealth",
    "F5": "frameworks.f5_growth_quality",
    "F6": "frameworks.f6_platform",
    "F7": "frameworks.f7_smart_beta",
}


def known_frameworks() -> list[str]:
    return sorted(_FRAMEWORK_MODULES.keys())


__all__ = [
    "FrameworkResult", "MissingDataError", "InsufficientHistoryError",
    "DataRequirement", "merge_requirements",
    "kitchen_sink_requirement", "screener_data_requirement",
    "requirement_for_frameworks",
    "known_frameworks", "replace",
]
