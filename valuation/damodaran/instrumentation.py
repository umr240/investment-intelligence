"""IV-run instrumentation logging.

Append a JSONL record per IV computation to `narrative_dumps/iv_runs.jsonl`
so we can:

  1. Build empirical priors on the misclassification distribution
  2. Track tier-routing changes over time as new ADRs ship (29 → 30 → 28-amend)
  3. Detect drift when reference data refreshes (Damodaran ERP, industry betas)
  4. Build dashboards over historical runs without re-computing

JSONL chosen over Parquet for the v1:
  - Zero new deps (Python stdlib json)
  - Append-only, line-oriented — easy to grep, easy to ship as a chunk
  - When file size becomes a problem (>100MB), trivially convertible

Record schema (1 line = 1 dict per IV computation):
{
  "ts": "2026-05-14T09:30:00",
  "ticker": "INTA",
  "tier": "B_young",
  "iv_per_share": 5.31,
  "current_price": 23.98,
  "mos_pct": -3.52,
  "epv_per_share": 5.54,
  "mos_vs_epv_pct": -2.93,
  "reverse_implied_g": null,
  "reverse_feasibility": null,
  "narrative_premium_pct": 0.78,
  "narrative_premium_vs_epv_pct": 0.77,
  "wacc": 0.0917,
  "nopat_source": "pt_adjusted",
  "n_data_gaps": 6,
  "maturity_mature": false,
  "maturity_floor": 0.117,
  "maturity_cov": 0.18,
  "yc_scenario_name": null,
  "yc_target_margin": null,
  "yc_survival": null,
  "version": "ADR-030"
}
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


_LOG_PATH = Path("narrative_dumps/iv_runs.jsonl")
_SCHEMA_VERSION = "ADR-030"


def log_iv_run(
    ticker: str,
    iv_result: Any,
    extras: dict | None = None,
) -> None:
    """Append a single IV run to the JSONL log.

    Safe to call from any tier path. Silently no-ops on filesystem errors
    (we never want logging failures to break the calc).

    Args:
        ticker: Ticker symbol.
        iv_result: An IVResult dataclass — duck-typed (we read fields).
        extras: Optional dict merged into the record (e.g., caller-specific
                trace context).
    """
    try:
        wacc = None
        if getattr(iv_result, "wacc_result", None) is not None:
            wacc = iv_result.wacc_result.wacc

        maturity = getattr(iv_result, "maturity_classification", None)
        maturity_dict: dict[str, Any] = {}
        if maturity is not None:
            maturity_dict = {
                "maturity_mature": maturity.is_mature,
                "maturity_floor": maturity.roic_floor,
                "maturity_cov": maturity.roic_cov,
                "maturity_floor_pass": maturity.floor_pass,
                "maturity_stability_pass": maturity.stability_pass,
                "maturity_history_pass": maturity.history_pass,
            }

        record = {
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "ticker": ticker,
            "tier": getattr(iv_result, "tier", None),
            "iv_per_share": getattr(iv_result, "intrinsic_value_per_share", None),
            "current_price": getattr(iv_result, "current_price", None),
            "mos_pct": getattr(iv_result, "margin_of_safety_pct", None),
            "epv_per_share": getattr(iv_result, "epv_per_share", None),
            "epv_total": getattr(iv_result, "epv_total", None),
            "mos_vs_epv_pct": getattr(iv_result, "mos_vs_epv_pct", None),
            "reverse_implied_g": getattr(iv_result, "reverse_implied_growth_rate", None),
            "reverse_feasibility": getattr(iv_result, "reverse_implied_growth_feasibility", None),
            "narrative_premium_pct": getattr(iv_result, "narrative_premium_pct", None),
            "narrative_premium_vs_epv_pct": getattr(iv_result, "narrative_premium_vs_epv_pct", None),
            "wacc": wacc,
            "nopat_source": getattr(iv_result, "nopat_source", None),
            "n_data_gaps": len(getattr(iv_result, "data_gaps", []) or []),
            # ADR-028 young-company fields
            "yc_scenario_name": getattr(iv_result, "young_company_scenario_name", None),
            "yc_target_margin": getattr(iv_result, "young_company_target_margin", None),
            "yc_survival": getattr(iv_result, "young_company_survival_probability", None),
            "yc_cash_runway_years": getattr(iv_result, "young_company_cash_runway_years", None),
            # ADR-030 maturity classification
            **maturity_dict,
            "version": _SCHEMA_VERSION,
        }
        if extras:
            record.update(extras)

        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:                                    # noqa: BLE001
        # Never break the calc on logging failure
        sys.stderr.write(f"[instrumentation] log_iv_run failed: {exc}\n")


def read_iv_runs(limit: int | None = None) -> list[dict]:
    """Read the JSONL log. Returns newest-last list of dicts."""
    if not _LOG_PATH.exists():
        return []
    records = []
    with _LOG_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None:
        records = records[-limit:]
    return records
