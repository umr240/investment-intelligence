import { useEffect, useState } from "react";
import { overviewRecentDives, overviewStats, schedulerJobs, screenerRuns } from "../api";
import Equalizer from "./Equalizer";
import type { OverviewStats, RecentDive, ScheduledJob, ScreenerRun } from "../types";

// Turn 1 ("Conviction Board") from Claude Design's Overview Dashboard.dc.html
// (project 5adfde5a-10ed-4e12-8b76-e0349f598140). The mockup's own numbers
// (4,812 universe, TEM/SHOP/KLIC/ABCL demo rows) are NOT used — every value
// here comes from GET /overview/stats and /overview/recent-dives (real DB
// rows). "Data gaps flagged" (present in the mockup's right rail) is
// deliberately omitted — no aggregated-gaps-across-dives endpoint exists
// yet and this panel doesn't fabricate one.

function Badge({ label }: { label: string }) {
  return <span className={`badge ${label}`}>{label.replace(/_/g, " ")}</span>;
}

export default function OverviewPanel({ onOpenTicker }: { onOpenTicker: (ticker: string) => void }) {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [dives, setDives] = useState<RecentDive[]>([]);
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [runs, setRuns] = useState<ScreenerRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "watchlist">("all");
  const [sortKey, setSortKey] = useState<"comp" | "F1" | "F2" | "F3" | "F4" | "F5" | "F6" | "F7">("comp");
  const [asc, setAsc] = useState(false);

  useEffect(() => {
    Promise.all([overviewStats(), overviewRecentDives(20), schedulerJobs(), screenerRuns(1)])
      .then(([s, d, j, r]) => { setStats(s); setDives(d); setJobs(j); setRuns(r); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <div className="error-box">{error}</div>;
  if (!stats) return <p className="dim">Loading overview…</p>;

  const val = (d: RecentDive): number => {
    if (sortKey === "comp") return d.composite ?? -1;
    const f = d[sortKey.toLowerCase() as keyof RecentDive] as number | null;
    return f ?? -1;
  };
  const watchlisted = (v: string | null) => v === "priority_watchlist" || v === "watchlist";
  const filtered = dives.filter((d) => filter === "all" || watchlisted(d.verdict));
  const sorted = [...filtered].sort((a, b) => (asc ? val(a) - val(b) : val(b) - val(a)));

  const latestRun = runs[0];

  return (
    <div>
      {/* stats strip */}
      <div className="card" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", padding: 0 }}>
        <div style={{ padding: "20px 24px" }}>
          <h6>Screener candidates</h6>
          <div style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 34 }}>{stats.screener_candidates.toLocaleString()}</div>
          <div className="mono dim">eligible for promotion</div>
        </div>
        <div style={{ padding: "20px 24px", borderLeft: "2px solid var(--color-divider)" }}>
          <h6>Deep dives · 30d</h6>
          <div style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 34 }}>{stats.deep_dives_30d}</div>
          <div className="mono dim">
            {Object.entries(stats.deep_dives_30d_by_verdict).map(([v, n]) => `${n} ${v.replace(/_/g, " ")}`).join(" · ") || "none yet"}
          </div>
        </div>
        <div style={{ padding: "20px 24px", borderLeft: "2px solid var(--color-divider)" }}>
          <h6>Avg composite · 30d</h6>
          <div style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 34 }}>
            {stats.avg_composite_30d !== null ? stats.avg_composite_30d.toFixed(1) : "—"}
            <span style={{ fontSize: 16, color: "var(--color-neutral-500)" }}> /10</span>
          </div>
          <div className="mono dim">across scored dives</div>
        </div>
        <div style={{ padding: "20px 24px", borderLeft: "2px solid var(--color-divider)" }}>
          <h6>Universe</h6>
          <div style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 34, color: "var(--color-neutral-400)" }}>—</div>
          <div className="mono dim">not yet wired (no source)</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 340px", gap: 16 }}>
        {/* Conviction Board */}
        <div className="card">
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
            <h3>Conviction Board</h3>
            <div className="seg" role="group" aria-label="Filter by verdict">
              {(["all", "watchlist"] as const).map((f) => (
                <label key={f} className="seg-opt">
                  <input type="radio" name="cf" checked={filter === f} onChange={() => setFilter(f)} />
                  {f === "all" ? "All" : "Watchlist"}
                </label>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, margin: "0 0 16px" }}>
            <p className="mono dim">{sorted.length} recent deep dives</p>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span className="mono dim" style={{ textTransform: "uppercase", letterSpacing: ".06em" }}>Sort</span>
              {(["comp", "F1", "F2", "F3", "F4", "F5", "F6", "F7"] as const).map((k) => (
                <button
                  key={k} className="ctl" aria-pressed={sortKey === k}
                  onClick={() => setSortKey((prev) => { if (prev === k) setAsc((a) => !a); else setAsc(false); return k; })}
                >
                  {k === "comp" ? "Comp" : k}{sortKey === k ? (asc ? " ↑" : " ↓") : ""}
                </button>
              ))}
            </div>
          </div>

          <table>
            <thead>
              <tr><th>Company</th><th>Framework scorecard · F1–F7</th><th style={{ textAlign: "right" }}>Composite</th></tr>
            </thead>
            <tbody>
              {sorted.map((d) => (
                <tr key={d.ticker} className="barrow" style={{ cursor: "pointer" }} onClick={() => onOpenTicker(d.ticker)}>
                  <td>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                      <span style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 17 }}>{d.ticker}</span>
                      <span className="mono dim">{d.stage ?? ""}</span>
                    </div>
                    <div style={{ fontSize: 12.5 }}>{d.name}</div>
                    <div className="mono dim">{d.sector}</div>
                  </td>
                  <td>
                    <Equalizer
                      scores={(["F1", "F2", "F3", "F4", "F5", "F6", "F7"] as const).map((c) => ({
                        code: c, score: d[c.toLowerCase() as keyof RecentDive] as number | null,
                      }))}
                    />
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 22 }}>
                      {d.composite !== null ? d.composite.toFixed(1) : "—"}
                    </div>
                    {d.verdict && <Badge label={d.verdict} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {sorted.length === 0 && <p className="dim">No dives yet — run one from the Deep Dive tab.</p>}
        </div>

        {/* right rail */}
        <div className="card">
          <h6>Screener pipeline{latestRun ? ` · run #${latestRun.id}` : ""}</h6>
          {latestRun ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderTop: "1px solid var(--color-divider)" }}>
                <span>Universe scanned</span><span className="mono">{latestRun.universe.toLocaleString()}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderTop: "1px solid var(--color-divider)", borderBottom: "1px solid var(--color-divider)" }}>
                <span>Gates passed</span><span className="mono">{latestRun.passed_gates.toLocaleString()}</span>
              </div>
              <div className="mono dim" style={{ marginTop: 8 }}>region {latestRun.region} · mode {latestRun.mode}</div>
            </>
          ) : <p className="dim">No screener runs yet.</p>}

          <h6 style={{ marginTop: 24 }}>Scheduled jobs</h6>
          {jobs.slice(0, 4).map((j) => (
            <div key={j.name} style={{ padding: "8px 0", borderTop: "1px solid var(--color-divider)" }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{j.name}</div>
              <div className="mono dim">{j.tickers?.join(", ") || j.type} · {j.cron}</div>
            </div>
          ))}
          {jobs.length === 0 && <p className="dim">No jobs registered.</p>}
        </div>
      </div>
    </div>
  );
}
