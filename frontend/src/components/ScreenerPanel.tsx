import { useEffect, useMemo, useState } from "react";
import { health, runStageA, runStageB, runStageC, screenerBoard, screenerRuns } from "../api";
import Equalizer from "./Equalizer";
import type { ScreenerBoardRow, ScreenerRun } from "../types";

// Turn 3 ("Screener") from Claude Design's Overview Dashboard.dc.html. The
// mockup's own demo candidates and status values ("review", SHOP/TEM/
// SNOW/...) are NOT used. The exclusion column and filter appear only when
// an exclusion policy is active, and use its stored vocabulary
// (pass/fail/unverified). Every row is either a real
// screener candidate that's been dived (scored) or one that hasn't
// (queued) — never fabricated.

function Badge({ label }: { label: string }) {
  return <span className={`badge ${label}`}>{label.replace(/_/g, " ")}</span>;
}

export default function ScreenerPanel({ onOpenTicker }: { onOpenTicker: (ticker: string) => void }) {
  const [rows, setRows] = useState<ScreenerBoardRow[]>([]);
  const [runs, setRuns] = useState<ScreenerRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(null);

  const [q, setQ] = useState("");
  const [sector, setSector] = useState("all");
  const [exclusion, setExclusion] = useState("all");
  const [policy, setPolicy] = useState("none");
  const [sortKey, setSortKey] = useState<"composite" | "cap">("composite");
  const [asc, setAsc] = useState(false);

  const [tickers, setTickers] = useState("");
  const [capMin, setCapMin] = useState("50M");
  const [capMax, setCapMax] = useState("10B");
  const [runId, setRunId] = useState("");

  async function refresh() {
    try {
      const [b, r, h] = await Promise.all([screenerBoard(), screenerRuns(1), health()]);
      setRows(b);
      setRuns(r);
      setPolicy(h.exclusion_policy);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const sectors = useMemo(() => ["all", ...Array.from(new Set(rows.map((r) => r.sector).filter(Boolean)))], [rows]);
  // Status words belong to the policy, so the filter offers whatever it stored.
  const statuses = useMemo(
    () => ["all", ...Array.from(new Set(rows.map((r) => r.exclusion_status).filter((s): s is string => !!s))).sort()],
    [rows],
  );

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase();
    let list = rows.filter((r) =>
      (!ql || r.ticker.toLowerCase().includes(ql) || r.name.toLowerCase().includes(ql)) &&
      (sector === "all" || r.sector === sector) &&
      (exclusion === "all" || r.exclusion_status === exclusion),
    );
    const val = (r: ScreenerBoardRow) => (sortKey === "cap" ? r.market_cap_b : r.composite ?? -1);
    list = [...list].sort((a, b) => (asc ? val(a) - val(b) : val(b) - val(a)));
    return list;
  }, [rows, q, sector, exclusion, sortKey, asc]);

  const scoredCount = filtered.filter((r) => r.composite !== null).length;
  const latestRun = runs[0];

  function actionFor(r: ScreenerBoardRow): { label: string; disabled: boolean } {
    if (r.excluded) return { label: "excluded", disabled: true };
    if (r.composite !== null) return { label: "Open dive →", disabled: false };
    return { label: "Run dive", disabled: false };
  }

  async function triggerStage(label: string, fn: () => Promise<Record<string, unknown>>) {
    setBusy(label);
    setError(null);
    try {
      const res = await fn();
      setLastResult(res);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="card">
        <div style={{ display: "flex", alignItems: "flex-end", gap: 20, flexWrap: "wrap", marginBottom: 8 }}>
          <label style={{ minWidth: 200 }}>
            Search
            <input placeholder="ticker or name…" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <div>
            <div className="mono dim" style={{ textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Sector</div>
            <div className="seg" role="group" aria-label="Filter by sector">
              {sectors.slice(0, 6).map((s) => (
                <label key={s} className="seg-opt">
                  <input type="radio" name="sec" checked={sector === s} onChange={() => setSector(s)} />
                  {s === "all" ? "All" : s}
                </label>
              ))}
            </div>
          </div>
          {policy !== "none" && (
            <div>
              <div className="mono dim" style={{ textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Exclusion · {policy}</div>
              <div className="seg" role="group" aria-label="Filter by exclusion status">
                {statuses.map((h) => (
                  <label key={h} className="seg-opt">
                    <input type="radio" name="excl" checked={exclusion === h} onChange={() => setExclusion(h)} />
                    {h === "all" ? "All" : h}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
            <span className="mono dim" style={{ textTransform: "uppercase", letterSpacing: ".06em" }}>Sort</span>
            {(["composite", "cap"] as const).map((k) => (
              <button
                key={k} className="ctl" aria-pressed={sortKey === k}
                onClick={() => setSortKey((prev) => { if (prev === k) setAsc((a) => !a); else setAsc(false); return k; })}
              >
                {k === "composite" ? "Composite" : "Cap"}{sortKey === k ? (asc ? " ↑" : " ↓") : ""}
              </button>
            ))}
          </div>
        </div>
        {error && <div className="error-box">{error}</div>}
        <p className="mono dim">{filtered.length} candidates · {scoredCount} scored · {filtered.length - scoredCount} queued</p>

        <table>
          <thead>
            <tr>
              <th style={{ width: 70 }}>Ticker</th>
              <th>Company</th>
              <th style={{ width: 80, textAlign: "right" }}>Cap $B</th>
              {policy !== "none" && <th style={{ width: 90 }}>Exclusion</th>}
              <th style={{ width: 150 }}>F1–F7</th>
              <th style={{ width: 110, textAlign: "right" }}>Composite</th>
              <th style={{ width: 110, textAlign: "right" }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 100).map((r) => {
              const action = actionFor(r);
              return (
                <tr key={r.ticker}>
                  <td style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 15 }}>{r.ticker}</td>
                  <td><div style={{ fontSize: 13.5 }}>{r.name}</div><div className="mono dim">{r.sector}</div></td>
                  <td className="mono" style={{ textAlign: "right" }}>{r.market_cap_b.toFixed(2)}</td>
                  {policy !== "none" && (
                    <td>
                      <span className="mono dim" style={{ textTransform: "uppercase" }}>{r.exclusion_status ?? "—"}</span>
                      {r.exclusion_reason && <div className="mono dim">{r.exclusion_reason.replace(/_/g, " ")}</div>}
                    </td>
                  )}
                  <td>
                    {r.composite !== null ? (
                      <Equalizer variant="mini" height={28}
                        scores={(["F1", "F2", "F3", "F4", "F5", "F6", "F7"] as const).map((c) => ({
                          code: c, score: r[c.toLowerCase() as keyof ScreenerBoardRow] as number | null,
                        }))}
                      />
                    ) : (
                      <span className="mono dim">— {r.excluded ? `excluded · ${policy} policy` : "queued for dive"}</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {r.composite !== null ? (
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8 }}>
                        <span style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 17 }}>{r.composite.toFixed(1)}</span>
                        {r.verdict && <Badge label={r.verdict} />}
                      </div>
                    ) : <span className="mono dim">—</span>}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn btn-ghost" disabled={action.disabled} onClick={() => onOpenTicker(r.ticker)}>
                      {action.label}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mono dim" style={{ marginTop: 14 }}>
          {policy !== "none" && <>Rows the <strong>{policy}</strong> policy excludes stay visible, never silently dropped. </>}Queued rows await a dive; scores are never fabricated.
        </p>
      </div>

      <div className="card">
        <h3>Staged pipeline (A → B → C)</h3>
        <p className="dim">
          Stage A is a heavy yfinance-scale universe scan — explicit trigger only, same as `invest screen-stage A`.
          {latestRun && ` Latest run #${latestRun.id}: ${latestRun.universe.toLocaleString()} scanned, ${latestRun.passed_gates.toLocaleString()} passed gates.`}
        </p>
        <div className="form-row">
          <label>Run ID (optional)<input value={runId} onChange={(e) => setRunId(e.target.value)} style={{ width: 80 }} /></label>
          <label>Cap min<input value={capMin} onChange={(e) => setCapMin(e.target.value)} style={{ width: 70 }} /></label>
          <label>Cap max<input value={capMax} onChange={(e) => setCapMax(e.target.value)} style={{ width: 70 }} /></label>
          <label>Test tickers (bypass universe)<input value={tickers} onChange={(e) => setTickers(e.target.value)} placeholder="NVDA,COST" style={{ width: 140 }} /></label>
        </div>
        <div className="form-row">
          <button
            disabled={busy !== null}
            onClick={() => triggerStage("A", () => runStageA({
              run_id: runId || undefined, cap_min: capMin, cap_max: capMax, tickers: tickers || undefined,
            }))}
          >
            {busy === "A" ? "Running Stage A…" : "Run Stage A"}
          </button>
          <button className="btn-secondary" disabled={busy !== null} onClick={() => triggerStage("B", () => runStageB(runId ? Number(runId) : undefined))}>
            {busy === "B" ? "Running Stage B…" : "Run Stage B (resume)"}
          </button>
          <button className="btn-secondary" disabled={busy !== null} onClick={() => triggerStage("C", () => runStageC(runId ? Number(runId) : undefined))}>
            {busy === "C" ? "Running Stage C…" : "Run Stage C (resume + persist)"}
          </button>
        </div>
        {lastResult && Array.isArray(lastResult.exclusions) && lastResult.exclusions.length > 0 && (
          <div className="mono dim" aria-label="Tier 3 exclusions">
            Excluded at Tier 3 by the {policy} policy:{" "}
            {(lastResult.exclusions as { ticker: string; reason: string }[])
              .map((x) => `${x.ticker} (${x.reason.replace(/_/g, " ")})`).join(", ")}
          </div>
        )}
        {lastResult && <p className="dim">Last result: {JSON.stringify(lastResult)}</p>}
      </div>
    </div>
  );
}
