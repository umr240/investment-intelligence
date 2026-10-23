"""
Tier 5b: the 7 hard gates (docs/architecture/SCREENER_PIPELINE.md §5).

Each gate returns a `GateResult(gate_id, severity, passed, reason)` where
severity is 'hard' (drop from clean tier) or 'soft' (tier-downgrade only).

Gate behaviour matrix:
  G1 Exclusion policy        hard (the active policy's rule; `none` passes)
  G2 Market cap              hard (already enforced at Tier 2 universe filter)
  G3 Analyst coverage ≥ 1    soft (tier-downgrade)
  G4 Asset growth decile     hard if decile 10; soft if decile 9
  G5 External financing      hard if severe; soft if mild
  G6 Piotroski subset ≥ 3    soft (tier-downgrade — coarse pre-filter)
  G7 Momentum decile ≥ 2     soft (tier-downgrade)

A ticker is `clean_tier` ONLY when every HARD gate passes. Soft-failed gates
move it to `flagged_tier` but it's still ranked + persisted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from config.constants import (
    DISQ_ASSET_GROWTH_DECILE,
    DISQ_DEBT_ISSUE_MAX,
    DISQ_EQUITY_ISSUE_MAX,
)
from data.reader import CompanyDataReader

if TYPE_CHECKING:
    from screener.policies.base import ExclusionPolicy

logger = logging.getLogger(__name__)


Severity = Literal["hard", "soft"]


@dataclass
class GateResult:
    gate_id: str
    severity: Severity
    passed: bool
    reason: str


def apply_all_gates(
    ticker: str,
    asset_growth_decile: int | None = None,
    momentum_decile: int | None = None,
    policy: ExclusionPolicy | None = None,
) -> list[GateResult]:
    """
    Apply G1–G7 to a single ticker. Returns 7 GateResult instances in order.

    `asset_growth_decile` (1–10, 10=worst) and `momentum_decile` (1–10, 1=worst)
    are precomputed by the universe-wide ranking pass — pass None to skip the
    decile check (gate then passes by default with reason 'no_universe_rank').
    """
    reader = CompanyDataReader(ticker)
    return [
        _gate_g1_policy(reader, policy),
        _gate_g2_market_cap(reader),
        _gate_g3_analyst_coverage(reader),
        _gate_g4_asset_growth(reader, asset_growth_decile),
        _gate_g5_external_financing(reader),
        _gate_g6_piotroski(reader),
        _gate_g7_momentum(reader, momentum_decile),
    ]


def is_clean(gates: list[GateResult]) -> bool:
    """True iff every HARD gate passes. Soft fails don't disqualify."""
    return all(g.passed for g in gates if g.severity == "hard")


def hard_failures(gates: list[GateResult]) -> list[str]:
    return [g.gate_id for g in gates if g.severity == "hard" and not g.passed]


def soft_failures(gates: list[GateResult]) -> list[str]:
    return [g.gate_id for g in gates if g.severity == "soft" and not g.passed]


# ── G1 Exclusion policy ──────────────────────────────────────────────────


def _gate_g1_policy(
    reader: CompanyDataReader, policy: ExclusionPolicy | None = None,
) -> GateResult:
    """The run's exclusion policy (default: the configured one) over fundamentals."""
    if policy is None:
        from screener.policies import get_policy

        policy = get_policy()
    verdict = policy.gate(reader)
    return GateResult("G1_policy", "hard", not verdict.excluded, verdict.reason or "")


# ── G2 Market cap ────────────────────────────────────────────────────────


def _gate_g2_market_cap(reader: CompanyDataReader) -> GateResult:
    """Already enforced at Tier 2 (universe filter). Defense-in-depth."""
    company = reader.company_or_none()
    if company is None:
        return GateResult("G2_market_cap", "hard", False, "company row missing")
    if not company.market_cap_usd:
        return GateResult("G2_market_cap", "hard", False, "market_cap_usd missing")
    return GateResult("G2_market_cap", "hard", True,
                      f"market_cap=${company.market_cap_usd / 1e9:.2f}B")


# ── G3 Analyst coverage ──────────────────────────────────────────────────


def _gate_g3_analyst_coverage(reader: CompanyDataReader) -> GateResult:
    """≥ 1 analyst covering — soft (tier-downgrade)."""
    cov = reader.latest_analyst_coverage()
    if cov is None or cov.analyst_count is None or cov.analyst_count < 1:
        return GateResult("G3_analyst_coverage", "soft", False,
                          "no analyst coverage on file")
    return GateResult("G3_analyst_coverage", "soft", True,
                      f"{cov.analyst_count} analysts")


# ── G4 Asset growth decile (Cooper-Gulen-Schill 2008) ────────────────────


def _gate_g4_asset_growth(
    reader: CompanyDataReader, decile: int | None,
) -> GateResult:
    """
    Decile 10 (top 10% asset growth) = HARD fail.
    Decile 9 = SOFT (tier-downgrade).
    No decile (universe rank not provided) = pass with note.
    """
    if decile is None:
        return GateResult("G4_asset_growth", "hard", True,
                          "no universe rank — skipped")
    if decile == 10:
        return GateResult("G4_asset_growth", "hard", False,
                          f"asset growth decile=10 (top 10%, disqualifying)")
    if decile == DISQ_ASSET_GROWTH_DECILE:    # 9
        return GateResult("G4_asset_growth", "soft", False,
                          f"asset growth decile=9 (top 20%, downgrade)")
    return GateResult("G4_asset_growth", "hard", True,
                      f"asset growth decile={decile}")


# ── G5 External financing ────────────────────────────────────────────────


def _gate_g5_external_financing(reader: CompanyDataReader) -> GateResult:
    """
    Severe (>5% equity issuance OR >20% debt issuance) → HARD.
    Mild positive issuance → SOFT (tier-downgrade).
    Net repurchases / no growth → pass.
    """
    annuals = reader.annuals(last_n=2)
    if len(annuals) < 2:
        return GateResult("G5_external_financing", "hard", True,
                          "<2 annuals — insufficient history, pass")
    company = reader.company_or_none()
    if company is None or not company.market_cap_usd:
        return GateResult("G5_external_financing", "hard", True,
                          "market_cap missing — skip")

    cur, prior = annuals[0], annuals[1]
    market_cap = company.market_cap_usd

    # Equity-issuance proxy: shares outstanding YoY * approximated price
    cur_shares = cur.shares_outstanding or 0
    prior_shares = prior.shares_outstanding or 0
    if cur_shares > 0:
        equity_issued_value = (cur_shares - prior_shares) * (market_cap / cur_shares)
        equity_issued_pct = equity_issued_value / market_cap
    else:
        equity_issued_pct = 0.0

    # Debt-issuance proxy: long-term-debt YoY delta / prior debt
    cur_debt = cur.long_term_debt or 0
    prior_debt = prior.long_term_debt or 0
    debt_issued_pct = (
        (cur_debt - prior_debt) / prior_debt if prior_debt > 0 else 0.0
    )

    severe = (
        equity_issued_pct > DISQ_EQUITY_ISSUE_MAX
        or debt_issued_pct > DISQ_DEBT_ISSUE_MAX
    )
    mild = (
        (0.02 < equity_issued_pct <= DISQ_EQUITY_ISSUE_MAX)
        or (0.10 < debt_issued_pct <= DISQ_DEBT_ISSUE_MAX)
    )
    if severe:
        return GateResult("G5_external_financing", "hard", False,
                          f"severe issuance (equity {equity_issued_pct:.1%}, debt {debt_issued_pct:.1%})")
    if mild:
        return GateResult("G5_external_financing", "soft", False,
                          f"mild issuance (equity {equity_issued_pct:.1%}, debt {debt_issued_pct:.1%})")
    return GateResult("G5_external_financing", "hard", True,
                      "no concerning issuance")


# ── G6 Piotroski subset ──────────────────────────────────────────────────


def _gate_g6_piotroski(reader: CompanyDataReader) -> GateResult:
    """
    Coarse 9-signal subset — F1 will compute the full Piotroski later.
    Here we just check whether 3+ of the easy-to-compute signals fire.
    Below 3 = SOFT downgrade.
    """
    annuals = reader.annuals(last_n=2)
    if len(annuals) < 2:
        return GateResult("G6_piotroski", "soft", True,
                          "<2 annuals — pass with note")
    cur, prior = annuals[0], annuals[1]

    score = 0
    if (cur.roa or 0) > 0:
        score += 1
    if (cur.operating_cash_flow or 0) > 0:
        score += 1
    if (cur.roa or 0) > (prior.roa or 0):
        score += 1
    if (cur.operating_cash_flow or 0) > (cur.net_income or 0):
        score += 1
    if (cur.long_term_debt or 0) <= (prior.long_term_debt or 0):
        score += 1
    if (cur.current_ratio or 0) > (prior.current_ratio or 0):
        score += 1
    cur_s = cur.shares_outstanding or 0
    prior_s = prior.shares_outstanding or 0
    if prior_s and (cur_s - prior_s) / prior_s <= 0.02:
        score += 1
    if (cur.gross_margin or 0) > (prior.gross_margin or 0):
        score += 1
    if (cur.asset_turnover or 0) > (prior.asset_turnover or 0):
        score += 1

    if score >= 3:
        return GateResult("G6_piotroski", "soft", True, f"piotroski_subset={score}/9")
    return GateResult("G6_piotroski", "soft", False, f"piotroski_subset={score}/9 (<3)")


# ── G7 Momentum decile ───────────────────────────────────────────────────


def _gate_g7_momentum(
    reader: CompanyDataReader, decile: int | None,
) -> GateResult:
    """Decile 1 = SOFT downgrade. None = pass with note."""
    if decile is None:
        return GateResult("G7_momentum", "soft", True,
                          "no universe rank — skipped")
    if decile <= 1:
        return GateResult("G7_momentum", "soft", False,
                          f"momentum decile=1 (bottom 10%)")
    return GateResult("G7_momentum", "soft", True,
                      f"momentum decile={decile}")
