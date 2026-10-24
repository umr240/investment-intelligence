"""
Export functions for DeepDiveRun and ScreenerRun.

Zero AI calls — all output is pure formatting of pre-computed stored data.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from data.models.schema import DeepDiveRun, ScreenerRun


def export_deepdive_markdown(run: DeepDiveRun, company_name: str = "") -> str:
    """
    Render a DeepDiveRun as a markdown report.
    Reads only stored fields — never triggers new computation or AI calls.
    """
    ticker = run.ticker
    label = f"{ticker} — {company_name}" if company_name else ticker
    run_date = run.run_date.strftime("%Y-%m-%d") if isinstance(run.run_date, datetime) else str(run.run_date)
    score_str = f"{run.composite_score:.2f}" if run.composite_score is not None else "N/A"
    verdict = run.verdict or "N/A"
    tier_label = "Full (Tier 2)" if run.tier == 2 else "Quick (Tier 1)"

    lines: list[str] = [
        f"# {label}",
        f"**Date:** {run_date}  |  **Mode:** {run.mode}  |  **Depth:** {tier_label}",
        f"**Score:** {score_str} / 10  |  **Verdict:** {verdict.upper()}",
        "",
    ]
    if run.stale_reason:
        lines += [f"> **Stale:** {run.stale_reason}. Re-run the dive before relying on it.", ""]

    # EDGAR source
    if run.edgar_10k_accession:
        lines += [
            "## Data Source",
            f"SEC EDGAR 10-K — accession `{run.edgar_10k_accession}`",
            "",
        ]

    # Framework scorecards
    fw_results: dict = {}
    if run.framework_results_json:
        try:
            fw_results = json.loads(run.framework_results_json)
        except json.JSONDecodeError:
            pass

    fw_name_map = {
        "f1": "F1 — Pre-Discovery Alpha",
        "f2": "F2 — Momentum",
        "f3": "F3 — Innovation Compounder",
        "f4": "F4 — Stealth Accumulation",
        "f5": "F5 — Growth Quality",
        "f6": "F6 — Platform Economics",
        "f7": "F7 — Smart Beta (contested)",
    }
    score_attrs = {
        "f1": run.f1_score,
        "f2": run.f2_score,
        "f3": run.f3_score,
        "f4": run.f4_score,
        "f5": run.f5_score,
        "f6": run.f6_score,
        "f7": run.f7_score,
    }

    lines.append("## Framework Scorecards")
    for key, name in fw_name_map.items():
        score = score_attrs.get(key)
        if score is None:
            continue
        detail = fw_results.get(key, {})
        score_bar = _score_bar(score)
        lines.append(f"\n### {name}")
        lines.append(f"**Score:** {score:.1f} / 10  {score_bar}")
        summary = detail.get("summary", "")
        if summary:
            lines.append(summary)
        signals: list = detail.get("signals", [])
        if signals:
            lines.append("\n**Key signals:**")
            for sig in signals:
                lines.append(f"- {sig}")

    # Overlay results
    overlays_results: dict = {}
    if run.overlays_results_json:
        try:
            overlays_results = json.loads(run.overlays_results_json)
        except json.JSONDecodeError:
            pass

    if overlays_results:
        lines += ["", "## Diagnostic Overlays"]
        for overlay_name, overlay_data in overlays_results.items():
            lines.append(f"\n### {overlay_name}")
            if isinstance(overlay_data, dict):
                summary = overlay_data.get("summary", "")
                if summary:
                    lines.append(summary)
                findings: list = overlay_data.get("findings", [])
                for f in findings:
                    lines.append(f"- {f}")
            else:
                lines.append(str(overlay_data))

    # Narratives (AI-generated, stored once). Columns hold structured JSON
    # per `deepdive/narrative_output.py:NarrativeBody`. Render the structure
    # rather than dumping raw JSON — caller can still inspect raw via the
    # DB columns directly.
    if run.stale_reason and (run.bull_narrative or run.bear_narrative or run.risk_factors):
        lines += ["", "## Narrative", "Withheld: it was built on inputs since superseded (DEC-46)."]
    else:
        if run.bull_narrative:
            lines += ["", "## Bull Case"]
            lines += _render_case_points(run.bull_narrative)
        if run.bear_narrative:
            lines += ["", "## Bear Case"]
            lines += _render_case_points(run.bear_narrative)
        if run.risk_factors:
            lines += ["", "## Thesis-Validation Checkpoints"]
            lines += _render_risk_section(run.risk_factors)

    # Data gaps
    gaps: list = []
    if run.data_gaps_json:
        try:
            gaps = json.loads(run.data_gaps_json)
        except json.JSONDecodeError:
            pass
    if gaps:
        lines += ["", "## Data Gaps"]
        for gap in gaps:
            lines.append(f"- ⚠ {gap}")

    lines += ["", "---", "*Research purposes only. Not financial advice.*"]
    return "\n".join(lines)


def export_screener_csv(run: ScreenerRun) -> str:
    """
    Export a ScreenerRun with all its ScreenerResult rows as CSV.
    Falls back gracefully to results_json summary if normalised rows are absent.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        "rank", "ticker", "composite_score", "verdict",
        "hard_gate_passed", "gate_failures",
        "f1_proxy", "f2_proxy", "f3_proxy", "f4_proxy",
        "f5_proxy", "f6_proxy", "f7_proxy",
    ]
    writer.writerow(header)

    ticker_results = getattr(run, "ticker_results", []) or []

    if ticker_results:
        ranked = sorted(
            ticker_results,
            key=lambda r: (r.composite_score or 0.0),
            reverse=True,
        )
        for i, result in enumerate(ranked, 1):
            gate_failures = ""
            if result.gate_failures:
                try:
                    gate_failures = ", ".join(json.loads(result.gate_failures))
                except json.JSONDecodeError:
                    gate_failures = result.gate_failures or ""
            writer.writerow([
                i,
                result.ticker,
                f"{result.composite_score:.2f}" if result.composite_score is not None else "",
                result.verdict or "",
                "yes" if result.hard_gate_passed else "no",
                gate_failures,
                _fmt(result.f1_proxy),
                _fmt(result.f2_proxy),
                _fmt(result.f3_proxy),
                _fmt(result.f4_proxy),
                _fmt(result.f5_proxy),
                _fmt(result.f6_proxy),
                _fmt(result.f7_proxy),
            ])
    elif run.results_json:
        # Legacy JSON blob fallback
        try:
            rows = json.loads(run.results_json)
            for i, row in enumerate(rows, 1):
                writer.writerow([
                    i,
                    row.get("ticker", ""),
                    _fmt(row.get("composite_score")),
                    row.get("verdict", ""),
                    row.get("hard_gate_passed", ""),
                    ", ".join(row.get("gate_failures", [])),
                    _fmt(row.get("f1_proxy")),
                    _fmt(row.get("f2_proxy")),
                    _fmt(row.get("f3_proxy")),
                    _fmt(row.get("f4_proxy")),
                    _fmt(row.get("f5_proxy")),
                    _fmt(row.get("f6_proxy")),
                    _fmt(row.get("f7_proxy")),
                ])
        except (json.JSONDecodeError, TypeError):
            pass

    return output.getvalue()


def _fmt(val: float | None) -> str:
    return f"{val:.2f}" if val is not None else ""


def _score_bar(score: float, width: int = 10) -> str:
    filled = round(score)
    return "█" * filled + "░" * (width - filled)


def _render_case_points(raw: str | None) -> list[str]:
    """Render a bull/bear narrative column (JSON list of point dicts) as
    structured markdown. Falls back to raw text on parse failure (legacy
    pre-ADR-023 prose-string narratives stay readable).
    """
    if not raw:
        return []
    try:
        points = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [raw]   # legacy plain-string narrative
    if not isinstance(points, list):
        return [str(points)]

    lines: list[str] = []
    for i, p in enumerate(points, 1):
        if not isinstance(p, dict):
            continue
        headline = p.get("headline") or p.get("title") or "(no headline)"
        detail = p.get("detail") or ""
        codes = p.get("framework_codes") or []
        codes_str = ", ".join(codes) if codes else "—"
        lines.append("")
        lines.append(f"### {i}. {headline}")
        lines.append(f"*Grounded in:* `{codes_str}`")
        if detail:
            lines.append("")
            lines.append(detail)
    return lines


def _render_risk_section(raw: str | None) -> list[str]:
    """Render the risk_factors column (NarrativeBody risks dict) as
    structured markdown. Surfaces one_liner, risks[], data_caveats[],
    and a small audit footer.
    """
    if not raw:
        return []
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [raw]
    if not isinstance(body, dict):
        return [str(body)]

    lines: list[str] = []

    one_liner = body.get("one_liner")
    if one_liner:
        lines.append("")
        lines.append(f"> {one_liner}")

    risks: list = body.get("risks") or []
    if risks:
        lines.append("")
        lines.append("Conditions to monitor across the 5-year hold "
                     "(not stop-loss triggers — per DEC-23 hold-logic):")
        lines.append("")
        for i, r in enumerate(risks, 1):
            if not isinstance(r, dict):
                continue
            sev = (r.get("severity") or "").upper() or "—"
            grounded = r.get("grounded_in") or "—"
            factor = r.get("factor") or r.get("headline") or "(no factor text)"
            lines.append(f"{i}. **[{sev}]** *(grounded: `{grounded}`)*  {factor}")

    caveats: list = body.get("data_caveats") or []
    if caveats:
        lines.append("")
        lines.append("### Data Caveats")
        lines.append("")
        for c in caveats:
            lines.append(f"- {c}")

    audit = body.get("_audit") or {}
    if audit:
        lines.append("")
        lines.append("### Narrative Audit")
        lines.append("")
        provider = audit.get("provider") or "?"
        model = audit.get("model") or "?"
        ptok = audit.get("prompt_tokens")
        ctok = audit.get("completion_tokens")
        gen_at = audit.get("generated_at")
        warns = audit.get("guard_warnings") or []
        lines.append(f"- Provider: `{provider}` / Model: `{model}`")
        if ptok is not None or ctok is not None:
            lines.append(f"- Tokens: prompt={ptok}, completion={ctok}")
        if gen_at:
            lines.append(f"- Generated: `{gen_at}`")
        lines.append(f"- Guard warnings: {len(warns)}")

    return lines
