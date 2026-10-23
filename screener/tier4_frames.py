"""
Tier 4: SEC frames-driven universe-wide fundamentals RANK (v2 — soft)
(docs/architecture/SCREENER_PIPELINE.md §1 Tier 4, DECISIONS.md DEC-09 + DEC-15).

Narrows ~1000 → ~300 candidates by RANKING on a Tier 4 quality score, NOT by
hard binary cuts. The actual hard stops live in Tier 5's 7 gates, which have
full Financial history to evaluate against. A single calendar-year snapshot
is too thin a signal to permanently exclude a ticker.

Design:
  - 13 (concept, period, unit) tuples → 13 SEC frames calls (universe-wide)
  - Build per-CIK Tier4Snapshot
  - HARD drops: only on truly missing data (no CIK, no XBRL, missing
    revenue, missing assets — without these we can't even rank)
  - SOFT flags: ROIC<5%, D/E>1.0, FCF<0, OCF<0 — carried forward as a
    `flags: list[str]` on the survivor; Tier 5 sees them
  - Composite Tier 4 quality score → sort desc → take top N (default 300)
  - Tickers below the cutoff are NOT marked failed — they just don't
    proceed THIS run. Next quarter's screen re-evaluates from scratch.

Why rank instead of cut: a one-year-bad ticker (turnaround story, capex
cycle, M&A absorption) shouldn't be permanently excluded from the screener.
Ranking lets Tier 4 surface the strongest 300 candidates while letting
weaker ones re-enter on the next run if their trajectory improves.

Period selection: `latest_complete_calendar_year(today)` from edgar_frames.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from data.edgar_frames import FrameEntry, latest_complete_calendar_year

logger = logging.getLogger(__name__)


# ── Filter thresholds ────────────────────────────────────────────────────
# Loose pre-cuts; Tier 5 applies the strict 7 gates from PROJECT_SPEC.
TIER4_MIN_REVENUE: float = 10_000_000        # $10M revenue floor
# First match wins, as in edgar_companyfacts. ASC 606 filers tag only the
# second or third (CRWD, VLO, ODFL use the third).
_REVENUE_CONCEPTS: tuple[str, ...] = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
TIER4_MIN_ROIC: float = 0.05                  # 5% ROIC pre-cut
TIER4_MAX_DEBT_TO_EQUITY: float = 1.0         # 1.0× debt/equity ceiling


# ── Snapshot type ────────────────────────────────────────────────────────


@dataclass
class Tier4Snapshot:
    """
    Per-ticker fundamentals snapshot built from frames data.

    All fields are Optional — frames may not have a concept for every filer
    (smaller companies, sparse XBRL tagging). Filter logic treats `None`
    leniently: it only fails on EXPLICITLY bad values, not missing ones,
    so Tier 5 has a chance to recover via per-ticker companyfacts.
    """
    cik: int
    period_end: date | None = None        # from Revenues@CY{N} entry's `end`

    # Income statement (CY{N})
    revenue: float | None = None
    revenue_prior: float | None = None
    net_income: float | None = None
    net_income_prior: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None

    # Balance sheet (CY{N}Q4I)
    assets: float | None = None
    assets_prior: float | None = None
    equity: float | None = None
    long_term_debt: float | None = None
    cash: float | None = None

    # Cash flow (CY{N})
    operating_cash_flow: float | None = None
    capex: float | None = None

    # ── Derived ratios ──────────────────────────────────────────────

    @property
    def free_cash_flow(self) -> float | None:
        if self.operating_cash_flow is None or self.capex is None:
            return None
        return self.operating_cash_flow - abs(self.capex)

    @property
    def roic_loose(self) -> float | None:
        """Net income / (equity + long-term debt). None if any input missing."""
        if self.net_income is None:
            return None
        invested = (self.equity or 0.0) + (self.long_term_debt or 0.0)
        return (self.net_income / invested) if invested else None

    @property
    def debt_to_equity(self) -> float | None:
        if self.long_term_debt is None or not self.equity:
            return None
        return self.long_term_debt / self.equity

    @property
    def asset_growth_yoy(self) -> float | None:
        if self.assets is None or not self.assets_prior:
            return None
        return (self.assets - self.assets_prior) / self.assets_prior

    @property
    def revenue_growth_yoy(self) -> float | None:
        if self.revenue is None or not self.revenue_prior:
            return None
        return (self.revenue - self.revenue_prior) / self.revenue_prior


# ── Concept/period spec ──────────────────────────────────────────────────


def screener_concepts_periods(
    today: date | None = None,
) -> list[tuple[str, str, str]]:
    """
    Return the 17 (concept, period, unit) tuples Tier 4 fetches.
    `today` defaults to today; override for testing.
    """
    cy = latest_complete_calendar_year(today)
    cy_prev = cy - 1

    return [
        # Income statement (duration, USD)
        *((c, f"CY{cy}", "USD") for c in _REVENUE_CONCEPTS),
        ("NetIncomeLoss", f"CY{cy}", "USD"),
        ("GrossProfit", f"CY{cy}", "USD"),
        ("OperatingIncomeLoss", f"CY{cy}", "USD"),
        # Income statement prior year (for YoY revenue/earnings growth)
        *((c, f"CY{cy_prev}", "USD") for c in _REVENUE_CONCEPTS),
        ("NetIncomeLoss", f"CY{cy_prev}", "USD"),
        # Balance sheet (instantaneous, point-in-time at year-end Q4)
        ("Assets", f"CY{cy}Q4I", "USD"),
        ("StockholdersEquity", f"CY{cy}Q4I", "USD"),
        ("LongTermDebt", f"CY{cy}Q4I", "USD"),
        ("CashAndCashEquivalentsAtCarryingValue", f"CY{cy}Q4I", "USD"),
        # Balance sheet prior year (for asset growth decile)
        ("Assets", f"CY{cy_prev}Q4I", "USD"),
        # Cash flow (duration)
        ("NetCashProvidedByUsedInOperatingActivities", f"CY{cy}", "USD"),
        ("PaymentsToAcquirePropertyPlantAndEquipment", f"CY{cy}", "USD"),
    ]


# ── Snapshot building ────────────────────────────────────────────────────


def build_tier4_snapshots(
    frames: dict[int, dict[str, FrameEntry]],
    today: date | None = None,
) -> dict[int, Tier4Snapshot]:
    """Convert {cik: {key: FrameEntry}} → {cik: Tier4Snapshot}."""
    cy = latest_complete_calendar_year(today)
    cy_prev = cy - 1

    snapshots: dict[int, Tier4Snapshot] = {}
    for cik, entries in frames.items():
        snap = Tier4Snapshot(cik=cik)

        rev_entry = _first(entries, _REVENUE_CONCEPTS, f"CY{cy}")
        prior_entry = _first(entries, _REVENUE_CONCEPTS, f"CY{cy_prev}")
        snap.revenue = rev_entry.val if rev_entry else None
        snap.revenue_prior = prior_entry.val if prior_entry else None
        snap.net_income = _val(entries, f"NetIncomeLoss@CY{cy}")
        snap.net_income_prior = _val(entries, f"NetIncomeLoss@CY{cy_prev}")
        snap.gross_profit = _val(entries, f"GrossProfit@CY{cy}")
        snap.operating_income = _val(entries, f"OperatingIncomeLoss@CY{cy}")

        snap.assets = _val(entries, f"Assets@CY{cy}Q4I")
        snap.assets_prior = _val(entries, f"Assets@CY{cy_prev}Q4I")
        snap.equity = _val(entries, f"StockholdersEquity@CY{cy}Q4I")
        snap.long_term_debt = _val(entries, f"LongTermDebt@CY{cy}Q4I")
        snap.cash = _val(entries, f"CashAndCashEquivalentsAtCarryingValue@CY{cy}Q4I")

        snap.operating_cash_flow = _val(
            entries, f"NetCashProvidedByUsedInOperatingActivities@CY{cy}",
        )
        snap.capex = _val(entries, f"PaymentsToAcquirePropertyPlantAndEquipment@CY{cy}")

        # Period end from the revenue entry (most reliable; off-fiscal-year companies
        # report their actual period_end in this field — see DATA_LAYER.md)
        if rev_entry:
            snap.period_end = rev_entry.end

        snapshots[cik] = snap
    return snapshots


def _first(
    entries: dict[str, FrameEntry], concepts: tuple[str, ...], period: str,
) -> FrameEntry | None:
    return next((e for c in concepts if (e := entries.get(f"{c}@{period}"))), None)


def _val(entries: dict[str, FrameEntry], key: str) -> float | None:
    e = entries.get(key)
    return e.val if e else None


# ── Filter ───────────────────────────────────────────────────────────────


@dataclass
class Tier4Result:
    """One candidate's Tier 4 outcome — survivor (with optional flags) or hard-failure."""
    ticker: str
    cik: str | None
    snapshot: Tier4Snapshot | None
    quality_score: float                  # higher = better
    flags: list[str]                       # soft warnings; carried into Tier 5
    hard_failure_reason: str | None        # set ONLY for missing-data drops


def evaluate_tier4(
    candidates: list,                          # list[_EnrichedTicker]
    snapshots: dict[int, Tier4Snapshot],
    min_revenue: float = TIER4_MIN_REVENUE,
    min_roic: float = TIER4_MIN_ROIC,
    max_debt_to_equity: float = TIER4_MAX_DEBT_TO_EQUITY,
) -> list[Tier4Result]:
    """
    Evaluate every candidate against the Tier 4 fundamental signals. Returns
    a Tier4Result per candidate.

      hard_failure_reason set  → can't be evaluated (missing CIK / XBRL /
                                  revenue / assets). EXCLUDED from this run.
      hard_failure_reason None → SURVIVOR. May carry soft `flags` (ROIC<5%,
                                  D/E>1.0, FCF<0, OCF<0) but proceeds to
                                  Tier 5 for full evaluation against history.

    Use `rank_and_truncate(results, top_n)` to narrow to the strongest N
    survivors before Tier 5.
    """
    results: list[Tier4Result] = []
    for c in candidates:
        ticker = getattr(c, "ticker", "?")
        cik_str = getattr(c, "cik", None)
        if not cik_str:
            results.append(Tier4Result(
                ticker=ticker, cik=None, snapshot=None, quality_score=0.0,
                flags=[], hard_failure_reason="no CIK (not SEC-filer)",
            ))
            continue
        try:
            cik_int = int(cik_str)
        except (TypeError, ValueError):
            results.append(Tier4Result(
                ticker=ticker, cik=cik_str, snapshot=None, quality_score=0.0,
                flags=[], hard_failure_reason=f"invalid CIK {cik_str!r}",
            ))
            continue

        snap = snapshots.get(cik_int)
        if snap is None:
            results.append(Tier4Result(
                ticker=ticker, cik=cik_str, snapshot=None, quality_score=0.0,
                flags=[], hard_failure_reason="no XBRL frames data",
            ))
            continue

        # Hard drops: data we MUST have to rank meaningfully
        if snap.revenue is None or snap.revenue < min_revenue:
            results.append(Tier4Result(
                ticker=ticker, cik=cik_str, snapshot=snap, quality_score=0.0,
                flags=[], hard_failure_reason=f"revenue<${min_revenue:,.0f} or missing",
            ))
            continue
        if snap.assets is None or snap.assets <= 0:
            results.append(Tier4Result(
                ticker=ticker, cik=cik_str, snapshot=snap, quality_score=0.0,
                flags=[], hard_failure_reason="assets missing or non-positive",
            ))
            continue

        # Soft flags — proceed to Tier 5 but record concerns
        flags: list[str] = []
        if snap.operating_cash_flow is not None and snap.operating_cash_flow <= 0:
            flags.append("operating_cash_flow_non_positive")
        if snap.free_cash_flow is not None and snap.free_cash_flow < 0:
            flags.append("free_cash_flow_negative")
        roic = snap.roic_loose
        if roic is not None and roic < min_roic:
            flags.append(f"roic_below_{min_roic*100:.0f}pct")
        de = snap.debt_to_equity
        if de is not None and de > max_debt_to_equity:
            flags.append(f"debt_to_equity_above_{max_debt_to_equity}")

        results.append(Tier4Result(
            ticker=ticker, cik=cik_str, snapshot=snap,
            quality_score=tier4_quality_score(snap),
            flags=flags, hard_failure_reason=None,
        ))
    return results


def tier4_quality_score(snap: Tier4Snapshot) -> float:
    """
    Composite quality score for ranking Tier 4 survivors. Higher = better.
    Components, each capped to [-1, 1] before summing:
      * ROIC  — capped 0 to 0.5; weight 1.5
      * FCF margin (FCF/revenue) — capped 0 to 0.4; weight 1.0
      * Debt/equity inverse — capped 0 to 1.0; weight 0.5
      * Revenue growth YoY — capped -0.5 to 0.5; weight 0.5
    Missing components contribute 0 (neutral). Score range roughly [-1.5, 4].
    """
    score = 0.0
    if snap.roic_loose is not None:
        score += 1.5 * max(-1.0, min(1.0, snap.roic_loose / 0.5))
    if snap.revenue and snap.free_cash_flow is not None:
        fcf_margin = snap.free_cash_flow / snap.revenue
        score += 1.0 * max(-1.0, min(1.0, fcf_margin / 0.4))
    if snap.debt_to_equity is not None:
        # Lower D/E is better; map [0..1] D/E to [1..0] contribution
        score += 0.5 * (1.0 - min(1.0, snap.debt_to_equity))
    rg = snap.revenue_growth_yoy
    if rg is not None:
        score += 0.5 * max(-1.0, min(1.0, rg / 0.5))
    return score


def rank_and_truncate(
    results: list[Tier4Result],
    top_n: int,
) -> tuple[list[Tier4Result], list[Tier4Result], list[Tier4Result]]:
    """
    Sort survivors by quality_score desc; take top N.
    Returns (selected, deferred, hard_failed) where:
      selected     = top N survivors (the only ones that proceed to Tier 5)
      deferred     = survivors below the cutoff (re-evaluated next run)
      hard_failed  = candidates with hard_failure_reason set
    """
    hard_failed = [r for r in results if r.hard_failure_reason is not None]
    survivors = [r for r in results if r.hard_failure_reason is None]
    survivors.sort(key=lambda r: r.quality_score, reverse=True)
    if top_n <= 0 or top_n >= len(survivors):
        return survivors, [], hard_failed
    return survivors[:top_n], survivors[top_n:], hard_failed
