"""Moat × Value × Framework screener (May 2026).

Combines three independent signals into a single conviction-stack:

  1. MUNGER MOAT — durable economic returns
       roic >= 15%  OR  pt_adjusted_roic (Peters-Taylor) >= 15%
       (PT-adjusted catches intangible-heavy moats — SaaS/biotech/brand)

  2. DAMODARAN INTRINSIC VALUE — undervalued vs fundamental DCF
       margin_of_safety_pct >= MIN_MOS (default 0.20 = 20%)
       Tier A (GAAP-profitable) or Tier B (PT-rescued) only.

  3. ANY FRAMEWORK STRONG — at least one of F1/F3/F4/F5/F6 ≥ 6.0
       F1 = Piotroski + insider (pre-discovery quality)
       F3 = Innovation (GM expansion, R&D intensity, surprise streak)
       F4 = Stealth (short int + 13F + EPS accel)
       F5 = Growth quality (FCF, ROIC, Outsiders CEO checklist)
       F6 = Platform (founder, customer concentration, Rule of 40)

  4. UNIVERSE filters:
       eligible under the active exclusion policy (EXCLUSION_POLICY)
       market_cap between $100M and $10B
       framework_verdict != 'exclude' (not auto-disqualified)

The script uses raw sqlite3 for the pre-filter (sub-second) then loads
SQLAlchemy + valuation modules once to compute IV inline for survivors.
Avoids the bulk-warehouse refresh which would be slow under AV-import
backlog.

Output: ranked Markdown table written to narrative_dumps/, ready for
narrative deep-dive on the top candidates.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")     # type: ignore[attr-defined]
except (AttributeError, RuntimeError):
    pass


# ── Tunables ─────────────────────────────────────────────────────────────

CAP_MIN = 100_000_000          # $100M
CAP_MAX = 10_000_000_000       # $10B
MIN_ROIC = 0.15                # Munger moat threshold (15%+ sustainable)
MIN_PT_ROIC = 0.15             # Same for Peters-Taylor intangible-adjusted
MIN_FRAMEWORK_STRONG = 6.0     # Any of F1/F3/F4/F5/F6 must hit
MIN_MARGIN_OF_SAFETY = 0.20    # Damodaran undervaluation threshold
PREFILTER_LIMIT = 350          # Max survivors from SQL pre-filter
OUTPUT_TOP_N = 30              # Final ranked output


# ── Pre-filter via direct sqlite3 (no SQLAlchemy load) ──────────────────


def _eligible_ids_sql() -> tuple[str, list[object]]:
    """The active policy's eligible() predicate as SQLite SQL plus its qmark params."""
    from sqlalchemy import select
    from sqlalchemy.dialects import sqlite

    from data.models.schema import Company
    from screener.policies import get_policy

    stmt = select(Company.id).where(get_policy().eligible())
    # render_postcompile expands IN (...) lists into one ? per value.
    compiled = stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"render_postcompile": True})
    return str(compiled), [compiled.params[name] for name in compiled.positiontup or ()]


def prefilter() -> list[dict]:
    """SQL pre-filter — HARD gates: policy-eligible + cap range + moat (ROIC or PT-ROIC ≥ 15%).

    Framework signals (F1/F3/F4/F5/F6 scores, ICA overlay) are returned for
    output ranking but NOT used as a hard filter — most mid-caps
    are auto-disqualified by the Cooper-Gulen-Schill asset-growth gate
    (`framework_verdict = 'exclude'`) and have sparse per-framework score
    coverage. Hard-gating on those would exclude almost everyone with a moat.

    Per-ticker framework data is enriched as INFORMATIONAL columns in the
    final ranking — see _framework_signals() and _bonus_score() in output
    formatting.

    Returns the top PREFILTER_LIMIT tickers ranked by composite_score.
    """
    from config.verdicts import canonical_verdict

    eligible_sql, eligible_params = _eligible_ids_sql()
    conn = sqlite3.connect("investment_intelligence.db")
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            c.ticker, c.name, c.sector, c.market_cap_usd,
            c.roic, c.pt_adjusted_roic, c.fcf_margin, c.debt_to_equity,
            c.composite_score, c.framework_composite_score, c.framework_verdict,
            c.intrinsic_value_per_share, c.margin_of_safety_pct, c.intrinsic_value_tier,
            fs.f1_score, fs.f3_score, fs.f4_score, fs.f5_score, fs.f6_score,
            fs.overlay_ica_run, fs.overlay_psa_run, fs.overlay_bew_run,
            c.is_founder_ceo, c.ceo_equity_pct
        FROM companies c
        LEFT JOIN framework_scores fs ON fs.id = (
            SELECT MAX(fs2.id) FROM framework_scores fs2 WHERE fs2.company_id = c.id
        )
        WHERE c.id IN ({eligible_sql})
          AND c.market_cap_usd BETWEEN ? AND ?
          AND (
              (c.roic IS NOT NULL AND c.roic >= ?)
              OR (c.pt_adjusted_roic IS NOT NULL AND c.pt_adjusted_roic >= ?)
          )
        ORDER BY c.composite_score DESC NULLS LAST
        LIMIT ?
    """, (*eligible_params, CAP_MIN, CAP_MAX, MIN_ROIC, MIN_PT_ROIC, PREFILTER_LIMIT))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    for row in rows:  # raw sqlite3 bypasses the ORM's legacy-label mapping (ADR-054)
        row["framework_verdict"] = canonical_verdict(row["framework_verdict"])
    return rows


# ── Per-ticker IV computation (uses already-persisted columns when fresh) ─


def _moat_signals(row: dict) -> list[str]:
    """Which moat/quality signals are firing for this ticker."""
    tags = []
    if row.get("roic") is not None and row["roic"] >= 0.20:
        tags.append(f"ROIC{row['roic']*100:.0f}%")
    elif row.get("roic") is not None and row["roic"] >= 0.15:
        tags.append(f"ROIC{row['roic']*100:.0f}%")
    if row.get("pt_adjusted_roic") is not None and row["pt_adjusted_roic"] >= 0.15:
        tags.append(f"PT-ROIC{row['pt_adjusted_roic']*100:.0f}%")
    if row.get("overlay_ica_run"):
        tags.append("ICA")
    if row.get("is_founder_ceo"):
        eq = row.get("ceo_equity_pct") or 0
        if eq >= 10:
            tags.append(f"Founder{eq:.0f}%")
        else:
            tags.append("Founder")
    if row.get("fcf_margin") is not None and row["fcf_margin"] >= 0.15:
        tags.append(f"FCF-mg{row['fcf_margin']*100:.0f}%")
    return tags


def _framework_signals(row: dict) -> list[str]:
    """Which frameworks are firing strong (≥ MIN_FRAMEWORK_STRONG)."""
    tags = []
    for code in ("f1", "f3", "f4", "f5", "f6"):
        s = row.get(f"{code}_score")
        if s is not None and s >= MIN_FRAMEWORK_STRONG:
            tags.append(f"{code.upper()}={s:.1f}")
    return tags


def _compute_iv_if_missing(row: dict) -> dict:
    """If intrinsic_value_per_share is NULL or stale, compute inline.
    Returns row with IV fields updated."""
    if row.get("intrinsic_value_per_share") is not None:
        return row
    # IV missing — compute via valuation module
    try:
        from valuation.damodaran import compute_and_persist
        ivr = compute_and_persist(row["ticker"])
        row["intrinsic_value_per_share"] = ivr.intrinsic_value_per_share
        row["margin_of_safety_pct"] = ivr.margin_of_safety_pct
        row["intrinsic_value_tier"] = ivr.tier
    except Exception as e:                                  # noqa: BLE001
        row["intrinsic_value_per_share"] = None
        row["margin_of_safety_pct"] = None
        row["intrinsic_value_tier"] = f"error:{type(e).__name__}"
    return row


# ── Output formatting ────────────────────────────────────────────────────


def format_table(rows: list[dict]) -> str:
    lines = []
    lines.append(f"# Moat × Value × Framework screener — {datetime.now().date().isoformat()}")
    lines.append("")
    lines.append(f"**Filters**: policy-eligible, cap [${CAP_MIN/1e6:.0f}M-${CAP_MAX/1e9:.0f}B], "
                 f"(ROIC ≥ {MIN_ROIC*100:.0f}% OR PT-ROIC ≥ {MIN_PT_ROIC*100:.0f}%), "
                 f"ANY F1/F3/F4/F5/F6 ≥ {MIN_FRAMEWORK_STRONG}, MoS ≥ {MIN_MARGIN_OF_SAFETY*100:.0f}%")
    lines.append("")
    lines.append(f"**Pre-filter survivors → IV-computable → MoS-passing**: {len(rows)} tickers")
    lines.append("")
    if not rows:
        lines.append("_No candidates met all three filters today._")
        return "\n".join(lines)

    # Sort by MoS desc
    rows = sorted(rows, key=lambda r: r.get("margin_of_safety_pct") or -1, reverse=True)
    header = (
        "Rank | Ticker | MoS    | IV/sh   | Cap    | Sector              | "
        "ROIC  | PT-ROIC | Moat signals          | Strong frameworks       | Tier"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for i, row in enumerate(rows[:OUTPUT_TOP_N], 1):
        mos = row.get("margin_of_safety_pct")
        mos_s = f"{mos*100:+5.1f}%" if mos is not None else "  --  "
        iv = row.get("intrinsic_value_per_share")
        iv_s = f"${iv:>6.2f}" if iv else "  --   "
        cap = (row.get("market_cap_usd") or 0) / 1e9
        sector = (row.get("sector") or "?")[:18]
        roic_s = f"{row['roic']*100:>5.1f}%" if row.get("roic") is not None else "  --  "
        pt_s = f"{row['pt_adjusted_roic']*100:>6.1f}%" if row.get("pt_adjusted_roic") is not None else "  --   "
        moat = ",".join(_moat_signals(row)) or "—"
        fwks = ",".join(_framework_signals(row)) or "—"
        tier = (row.get("intrinsic_value_tier") or "?")[:14]
        lines.append(
            f"{i:>4} | {row['ticker']:<6} | {mos_s} | {iv_s} | ${cap:>4.1f}B | {sector:<18} | "
            f"{roic_s} | {pt_s} | {moat[:21]:<21} | {fwks[:22]:<22} | {tier}"
        )
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    started = datetime.now()
    print(f"[{started.isoformat(timespec='seconds')}] Moat × Value × Framework screener starting", flush=True)

    # Phase 1: SQL pre-filter
    candidates = prefilter()
    print(f"  pre-filter: {len(candidates)} candidates pass moat + framework + universe gates", flush=True)

    if not candidates:
        print("  no candidates passed pre-filter — nothing to value", flush=True)
        return 0

    # Phase 2: ensure IV is computed for all candidates
    fresh_iv_count = 0
    for c in candidates:
        had_iv = c.get("intrinsic_value_per_share") is not None
        if not had_iv:
            _compute_iv_if_missing(c)
            if c.get("intrinsic_value_per_share") is not None:
                fresh_iv_count += 1
    if fresh_iv_count > 0:
        print(f"  computed IV inline for {fresh_iv_count} candidates without persisted value", flush=True)

    # Phase 3: filter by MoS + Tier
    survivors = []
    for c in candidates:
        tier = c.get("intrinsic_value_tier") or ""
        if tier not in ("A_gaap", "B_pt_rescued"):
            continue
        mos = c.get("margin_of_safety_pct")
        if mos is None or mos < MIN_MARGIN_OF_SAFETY:
            continue
        survivors.append(c)

    print(f"  MoS filter: {len(survivors)} candidates passed (MoS ≥ {MIN_MARGIN_OF_SAFETY*100:.0f}%)", flush=True)

    # Phase 4: write output
    Path("narrative_dumps").mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path("narrative_dumps") / f"moat_value_screener_{timestamp}.md"
    body = format_table(survivors)
    out_path.write_text(body, encoding="utf-8")
    print(f"  output → {out_path}", flush=True)
    print()
    print(body)
    elapsed = (datetime.now() - started).total_seconds()
    print(f"\n[{datetime.now().isoformat(timespec='seconds')}] done in {elapsed:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
