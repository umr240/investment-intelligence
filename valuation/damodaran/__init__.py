"""Damodaran intrinsic value toolkit (ADR-027).

Public API:
  - cost_of_capital.compute_wacc(...)              — Phase A
  - nopat.compute_nopat(...)                       — Phase B
  - reinvestment.compute_reinvestment(...)         — Phase B
  - growth.compute_fundamental_growth(...)         — Phase B
  - fcff.project_fcff(...)                         — Phase B
  - terminal.compute_terminal_value(...)           — Phase B
  - sensitivity.sensitivity_grid(...)              — Phase B
  - intrinsic.compute_intrinsic_value(inputs)      — Phase B (top-level)

Per CLAUDE.md:
  - Deterministic. No LLM calls in this package.
  - Lazy-load: only fires on explicit user instruction.
  - data_gaps[] first-class. Missing inputs surface, never hallucinate.
"""
from valuation.damodaran.cost_of_capital import (
    WACCResult,
    compute_after_tax_cost_of_debt,
    compute_cost_of_equity,
    compute_wacc,
    relevel_beta,
)
from valuation.damodaran.fcff import FCFFProjection, project_fcff
from valuation.damodaran.growth import GrowthResult, compute_fundamental_growth
from valuation.damodaran.intrinsic import (
    IntrinsicValueInputs,
    IVResult,
    compute_intrinsic_value,
)
from valuation.damodaran.epv import EPVResult, compute_epv
from valuation.damodaran.instrumentation import log_iv_run, read_iv_runs
from valuation.damodaran.loader import (
    CompanyNotFoundError,
    InsufficientDataError,
    compute_and_persist,
    load_inputs,
    persist_intrinsic_value,
)
from valuation.damodaran.maturity import MaturityClassification, classify_maturity
from valuation.damodaran.reverse_dcf import ReverseDCFResult, reverse_solve_growth
from valuation.damodaran.nopat import (
    EBITResult,
    NOPATResult,
    Tier,
    classify_tier,
    compute_economic_ebit,
    compute_nopat,
)
from valuation.damodaran.reinvestment import (
    ReinvestmentResult,
    compute_reinvestment,
)
from valuation.damodaran.sensitivity import SensitivityResult, sensitivity_grid
from valuation.damodaran.terminal import (
    TerminalValueResult,
    compute_terminal_value,
)

__all__ = [
    # Phase A — cost of capital
    "WACCResult",
    "compute_cost_of_equity",
    "compute_after_tax_cost_of_debt",
    "compute_wacc",
    "relevel_beta",
    # Phase B — NOPAT
    "Tier",
    "EBITResult",
    "NOPATResult",
    "classify_tier",
    "compute_economic_ebit",
    "compute_nopat",
    # Phase B — reinvestment
    "ReinvestmentResult",
    "compute_reinvestment",
    # Phase B — growth
    "GrowthResult",
    "compute_fundamental_growth",
    # Phase B — FCFF
    "FCFFProjection",
    "project_fcff",
    # Phase B — terminal
    "TerminalValueResult",
    "compute_terminal_value",
    # Phase B — sensitivity
    "SensitivityResult",
    "sensitivity_grid",
    # Phase B — orchestration
    "IntrinsicValueInputs",
    "IVResult",
    "compute_intrinsic_value",
    # Phase D — DB loader + warehouse persistence
    "CompanyNotFoundError",
    "InsufficientDataError",
    "load_inputs",
    "persist_intrinsic_value",
    "compute_and_persist",
]
