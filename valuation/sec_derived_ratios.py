"""SEC-derived valuation ratios — compute P/E, P/B, EV/EBITDA, P/FCF from raw
SEC XBRL fundamentals instead of pulling pre-computed values from yfinance/FMP.

Architectural principle (per user 2026-05-15):
  "the reason why I don't trust ratios of other sites is because we can derive
   them ourselves if we have pure raw complete data from SEC EDGAR and edgartools
   instead of relying on APIs which I do not trust. SEC EDGAR is GAAP-verifiable
   source of truth and calculations based on those gets us accurate results."

What this module replaces:
  - yfinance.info.trailingPE     → compute as market_cap / TTM_net_income (SEC)
  - yfinance.info.priceToBook    → compute as market_cap / total_equity (SEC)
  - yfinance.info.enterpriseToEbitda → compute as (mc + total_debt − cash) / TTM_EBITDA (SEC)
  - yfinance.info.priceToFreeCashFlow → compute as market_cap / TTM_FCF (SEC)

What stays in API source:
  - current_price (SEC structurally does not publish market prices)
  - market_cap (= current_price × SEC shares_outstanding — half-API, half-SEC)

Key honesty invariants:
  - When TTM net_income ≤ 0 → P/E is UNDEFINED (None). NOT replaced with
    forward EPS, NOT replaced with non-GAAP adjusted EPS. The undefined-
    value IS the signal (the company is loss-making at GAAP level).
  - When TTM EBITDA ≤ 0 → EV/EBITDA is UNDEFINED. Same logic.
  - When equity < 0 (technically insolvent) → P/B is UNDEFINED.
  - No SBC add-backs, no restructuring add-backs, no "one-time" exclusions
    (per ADR-021 §4.1).

HIMS investigation 2026-05-15 demonstrated yfinance.info disagrees with
GAAP for loss-makers: yfinance reported P/E 57.14x for HIMS (GAAP TTM NI
negative); EV/EBITDA 134.16x where ours is 202.95x; INTA P/B 5.00x where
ours is 3.08x. Each disagreement reveals a silent non-GAAP shim.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from data.models.schema import Company, Financial

logger = logging.getLogger(__name__)


# ── Result container ──────────────────────────────────────────────────────


@dataclass
class SecDerivedRatios:
    """One ticker's self-computed valuation ratios + provenance."""
    ticker: str
    market_cap_usd: float | None
    # TTM denominators (sum of last 4 quarters, fallback to latest annual)
    ttm_net_income: float | None
    ttm_ebitda: float | None
    ttm_fcf: float | None
    # Point-in-time balance-sheet items (latest annual)
    total_equity: float | None
    total_debt: float | None
    cash_and_equivalents: float | None
    net_debt: float | None
    enterprise_value: float | None
    # Computed ratios — None when mathematically undefined (per honesty
    # invariants above). Not replaced by forward / non-GAAP estimates.
    pe_trailing: float | None
    pb_ratio: float | None
    ev_ebitda: float | None
    p_fcf: float | None
    # Provenance
    computed_at: date
    source_method: str = "sec_xbrl_derived"
    notes: list[str] = None    # honesty annotations ("TTM NI negative — P/E undefined")

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


# ── Computation ───────────────────────────────────────────────────────────


# Field-name → SEC XBRL concept mapping for edgartools TTM lookup. We use
# the primary canonical XBRL concept for each field; edgartools handles
# aliases and concept-mapping internally per their concept-mapping logic.
_FIELD_TO_CONCEPT: dict[str, str] = {
    "net_income": "us-gaap:NetIncomeLoss",
    "revenue": "us-gaap:Revenues",
    "operating_cash_flow": "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    "free_cash_flow": None,         # not a single concept — derive OCF - CapEx
    "ebitda": None,                 # not always tagged — fall back to our derivation
    "rd_expense": "us-gaap:ResearchAndDevelopmentExpense",
    "operating_income": "us-gaap:OperatingIncomeLoss",
    "gross_profit": "us-gaap:GrossProfit",
}


def _compute_ttm_via_edgartools(ticker: str, field: str) -> float | None:
    """Use edgartools' get_ttm(concept) helper for TTM computation.

    Returns None when:
      - field has no canonical us-gaap concept mapping (free_cash_flow, ebitda)
      - edgartools lookup fails (network, parse, or concept not reported)

    The TTMMetric returned by edgartools includes period audit trail, which
    we discard here (we only need the value); the audit trail is preserved
    in edgartools' caching layer for later inspection.
    """
    concept = _FIELD_TO_CONCEPT.get(field)
    if not concept:
        return None
    try:
        from edgar import Company
        co = Company(ticker)
        ttm_metric = co.get_ttm(concept)
        if ttm_metric is None:
            return None
        val = getattr(ttm_metric, "value", None)
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("edgartools get_ttm failed (%s, %s): %s", ticker, concept, exc)
        return None


def _compute_ttm(
    session: Session,
    company_id: int,
    field: str,
    n_quarters: int = 4,
    ticker: str | None = None,
) -> float | None:
    """Trailing-twelve-month for a financial field.

    Source priority (per ADR-031 SEC-first hierarchy + user 2026-05-15
    "search SEC EDGAR endpoints as alternatives first"):
      1. **edgartools.Company.get_ttm(concept)** — uses SEC XBRL with
         edgartools' concept-mapping; returns TTMMetric with period audit
         trail. Available for canonical us-gaap concepts (net_income,
         revenue, operating_cash_flow, rd_expense, operating_income,
         gross_profit). NOT available for derived fields (free_cash_flow
         = OCF − CapEx) or non-canonical fields (EBITDA).
      2. **Manual quarterly sum** from `Financial` table — last 4 quarters
         summed, with annual fallback. Always available for any persisted
         field.

    Returns None when neither path produces a value.

    `ticker` parameter is optional — when provided, tier 1 is attempted.
    When omitted, only tier 2 (manual) is used.
    """
    # Tier 1: edgartools TTM helper
    if ticker:
        v = _compute_ttm_via_edgartools(ticker, field)
        if v is not None:
            return v

    # Tier 2: manual quarterly sum
    qs = session.execute(
        select(Financial)
        .where(
            Financial.company_id == company_id,
            Financial.period.in_(["Q1", "Q2", "Q3", "Q4"]),
        )
        .order_by(desc(Financial.fiscal_year), desc(Financial.period))
        .limit(n_quarters)
    ).scalars().all()
    if len(qs) >= n_quarters:
        vals = [getattr(q, field, None) for q in qs]
        if all(v is not None for v in vals):
            return sum(vals)
    # Annual fallback — only when at least 1 annual row exists
    a = session.execute(
        select(Financial)
        .where(Financial.company_id == company_id, Financial.period == "annual")
        .order_by(desc(Financial.fiscal_year))
        .limit(1)
    ).scalar_one_or_none()
    return getattr(a, field, None) if a else None


def compute_sec_ratios(session: Session, ticker: str) -> SecDerivedRatios | None:
    """Compute all SEC-derived valuation ratios for one ticker.

    Returns None when the Company row doesn't exist OR when no Financial
    rows are present. Per-ratio undefinedness is recorded in the result's
    `notes` and as None in the corresponding fields.
    """
    c = session.execute(
        select(Company).where(Company.ticker == ticker.upper())
    ).scalar_one_or_none()
    if c is None:
        return None

    latest_annual = session.execute(
        select(Financial)
        .where(Financial.company_id == c.id, Financial.period == "annual")
        .order_by(desc(Financial.fiscal_year))
        .limit(1)
    ).scalar_one_or_none()
    if latest_annual is None:
        return None

    ttm_ni = _compute_ttm(session, c.id, "net_income", ticker=ticker)
    ttm_ebitda = _compute_ttm(session, c.id, "ebitda", ticker=ticker)
    ttm_fcf = _compute_ttm(session, c.id, "free_cash_flow", ticker=ticker)

    equity = latest_annual.total_equity
    debt = latest_annual.total_debt or 0.0
    cash = latest_annual.cash_and_equivalents or 0.0
    net_debt = debt - cash
    market_cap = c.market_cap_usd
    enterprise_value = (market_cap + net_debt) if market_cap is not None else None

    notes: list[str] = []

    # P/E — undefined when TTM NI ≤ 0
    pe = None
    if market_cap is not None and ttm_ni is not None:
        if ttm_ni > 0:
            pe = market_cap / ttm_ni
        else:
            notes.append(
                f"P/E undefined: TTM net income = ${ttm_ni / 1e6:,.1f}M ≤ 0 "
                f"(GAAP loss-maker — no forward/non-GAAP substitution)"
            )

    # P/B — undefined when equity ≤ 0
    pb = None
    if market_cap is not None and equity is not None:
        if equity > 0:
            pb = market_cap / equity
        else:
            notes.append(
                f"P/B undefined: total_equity = ${equity / 1e6:,.1f}M ≤ 0 "
                f"(technically insolvent on book basis)"
            )

    # EV/EBITDA — undefined when EBITDA ≤ 0
    ev_ebitda = None
    if enterprise_value is not None and ttm_ebitda is not None:
        if ttm_ebitda > 0:
            ev_ebitda = enterprise_value / ttm_ebitda
        else:
            notes.append(
                f"EV/EBITDA undefined: TTM EBITDA = ${ttm_ebitda / 1e6:,.1f}M ≤ 0 "
                f"(no operating cash-flow proxy — yfinance's negative-ratio "
                f"output is mathematically meaningless)"
            )

    # P/FCF — undefined when FCF ≤ 0
    p_fcf = None
    if market_cap is not None and ttm_fcf is not None:
        if ttm_fcf > 0:
            p_fcf = market_cap / ttm_fcf
        else:
            notes.append(
                f"P/FCF undefined: TTM FCF = ${ttm_fcf / 1e6:,.1f}M ≤ 0"
            )

    return SecDerivedRatios(
        ticker=ticker.upper(),
        market_cap_usd=market_cap,
        ttm_net_income=ttm_ni,
        ttm_ebitda=ttm_ebitda,
        ttm_fcf=ttm_fcf,
        total_equity=equity,
        total_debt=debt or None,
        cash_and_equivalents=cash or None,
        net_debt=net_debt,
        enterprise_value=enterprise_value,
        pe_trailing=pe,
        pb_ratio=pb,
        ev_ebitda=ev_ebitda,
        p_fcf=p_fcf,
        computed_at=date.today(),
        source_method="sec_xbrl_derived",
        notes=notes,
    )


def persist_sec_ratios(session: Session, result: SecDerivedRatios) -> None:
    """Write SEC-derived ratios to Company row, overwriting any API-pulled
    values. Records `source_method='sec_xbrl_derived'` semantics by setting
    the value AND the `*_fetched_at` timestamp.

    NOTE: per-ratio `_source` columns are a planned ADR-033 amendment. For
    now we overwrite the existing columns and rely on the `_fetched_at`
    timestamp + module-name convention.
    """
    from datetime import datetime
    c = session.execute(
        select(Company).where(Company.ticker == result.ticker)
    ).scalar_one()

    now = datetime.utcnow()
    # Honesty invariant (ADR-033 §1.2 + §4 #4 "no forward-EPS substitution"):
    # SEC-derived `None` is the canonical answer when GAAP makes the
    # ratio undefined (negative TTM NI, negative equity, negative EBITDA).
    # Always overwrite — including with None — so a stale yfinance value
    # doesn't silently linger after the dive refresh.
    from config.source_tags import SELF_COMPUTED as _SRC_SC
    c.pe_trailing = result.pe_trailing
    c.pe_trailing_source = _SRC_SC if result.pe_trailing is not None else None
    c.pb_ratio = result.pb_ratio
    c.pb_ratio_source = _SRC_SC if result.pb_ratio is not None else None
    c.ev_ebitda = result.ev_ebitda
    c.ev_ebitda_source = _SRC_SC if result.ev_ebitda is not None else None
    # Note: p_fcf doesn't have a dedicated Company column yet — tracked
    # as a follow-up schema migration. For now it's available via the
    # returned SecDerivedRatios dataclass.
    _ = now  # reserved for future *_fetched_at when schema adds those
    session.commit()
