import { useEffect, useState } from "react";
import { getScorecard, runDive } from "../api";
import NarrativeRail from "./NarrativeRail";
import ValuationSection from "./ValuationSection";
import type { ScorecardView } from "../types";

function Badge({ label }: { label: string }) {
  return <span className={`badge ${label}`}>{label.replace(/_/g, " ")}</span>;
}

function ScoreBar({ score, max }: { score: number; max: number }) {
  return (
    <div className="score-bar-track">
      <div className="score-bar-fill" style={{ width: `${(score / max) * 100}%` }} />
    </div>
  );
}

export default function DivePanel({ initialTicker }: { initialTicker?: string }) {
  const [ticker, setTicker] = useState(initialTicker ?? "");
  const [tier, setTier] = useState(2);
  const [mode, setMode] = useState("");
  const [frameworks, setFrameworks] = useState("");
  const [force, setForce] = useState(false);
  const [autoOverlays] = useState(true); // always true — no interactive confirm over HTTP (ADR-040)
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ScorecardView | null>(null);

  async function loadScorecard(t: string) {
    const sc = await getScorecard(t);
    setView(sc);
  }

  useEffect(() => {
    // Coming from Overview's Conviction Board: read-only, already-persisted
    // scorecard — same as clicking "Load Existing Scorecard", not a new fetch.
    if (initialTicker) {
      loadScorecard(initialTicker).catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTicker]);

  async function handleDive() {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const t = ticker.trim().toUpperCase();
      await runDive(t, { tier, mode: mode || undefined, frameworks: frameworks || undefined, force });
      await loadScorecard(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadOnly() {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await loadScorecard(ticker.trim().toUpperCase());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="panel">
        <h2>Deep Dive</h2>
        <div className="form-row">
          <label>
            Ticker
            <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="NVDA" style={{ width: 100 }} />
          </label>
          <label>
            Tier
            <select value={tier} onChange={(e) => setTier(Number(e.target.value))}>
              <option value={1}>1 (quick)</option>
              <option value={2}>2 (full)</option>
            </select>
          </label>
          <label>
            Mode
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="">all 7 (default)</option>
              <option value="A">A — F1,F2,F3</option>
              <option value="B">B — F1-F5</option>
              <option value="C">C — all 7</option>
            </select>
          </label>
          <label>
            Frameworks override
            <input value={frameworks} onChange={(e) => setFrameworks(e.target.value)} placeholder="F1,F5" style={{ width: 100 }} />
          </label>
          <label>
            <span>&nbsp;</span>
            <span><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> force refresh</span>
          </label>
        </div>
        <div className="form-row">
          <button onClick={handleDive} disabled={loading || !ticker.trim()}>
            {loading ? "Running…" : "Run Dive"}
          </button>
          <button className="secondary" onClick={handleLoadOnly} disabled={loading || !ticker.trim()}>
            Load Existing Scorecard
          </button>
          <span className="dim">
            {autoOverlays ? "Auto-overlays: BEW mandatory, ICA/PSA trigger-gated (no interactive confirm over HTTP)" : ""}
          </span>
        </div>
        {error && <div className="error-box">{error}</div>}
      </div>

      {view && (
        <div className="card" style={{ padding: 0, display: "grid", gridTemplateColumns: "minmax(0,1fr) 400px" }}>
          <div style={{ padding: "26px 28px 30px" }}>
            <h2>{view.company.name} ({view.ticker})</h2>
            <p className="dim">
              {view.company.sector} / {view.company.industry} · Cap ${((view.company.market_cap_usd || 0) / 1e9).toFixed(2)}B ·
              {" "}Stage: {view.stage.stage} · Run date: {view.run_date}
            </p>
            {view.stale_reason && (
              <div className="error-box" data-testid="dive-stale">
                Stale dive: {view.stale_reason}. Re-run the dive before relying on these scores.
              </div>
            )}
            <p>
              Composite: <strong>{view.composite.score.toFixed(2)}/10</strong>{" "}
              <Badge label={view.composite.verdict} />{" "}
              <span className="dim">
                mode {view.composite.mode_resolved}
                {view.composite.weights_renormalised ? " (weights renormalised — some frameworks unfeasible)" : ""}
              </span>
            </p>

            <h3>Frameworks</h3>
            <table>
              <thead>
                <tr><th>Code</th><th>Title</th><th>Score</th><th></th><th>Verdict</th><th>Key signals</th></tr>
              </thead>
              <tbody>
                {view.frameworks.map((fw) => (
                  <tr key={fw.code}>
                    <td>{fw.code}</td>
                    <td>{fw.title}</td>
                    <td>{fw.is_unfeasible ? "—" : `${fw.score.toFixed(1)}/${fw.max_score}`}</td>
                    <td>{!fw.is_unfeasible && <ScoreBar score={fw.score} max={fw.max_score} />}</td>
                    <td>
                      {fw.is_unfeasible ? <Badge label="unfeasible" /> : <Badge label={fw.verdict} />}
                    </td>
                    <td className="dim">
                      {fw.is_unfeasible
                        ? fw.unfeasible_reason
                        : fw.key_signals.map(([k, v]) => `${k}: ${v}`).join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {view.overlay_triggers.length > 0 && (
              <>
                <h3>Overlay triggers</h3>
                <table>
                  <thead><tr><th>Type</th><th>Trigger</th><th>Condition</th></tr></thead>
                  <tbody>
                    {view.overlay_triggers.map((t) => (
                      <tr key={t.trigger_id}>
                        <td>{t.overlay_type}</td>
                        <td>{t.trigger_id}</td>
                        <td className="dim">{t.condition}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {/* Valuation sits AFTER the framework scores deliberately. The
                frameworks answer "is this a business worth owning"; the
                valuation answers "at what price". Reading price first is how
                you end up reverse-engineering a thesis from a number. */}
            <ValuationSection ticker={view.ticker} />

            {view.fetch_data_gaps.length > 0 && (
              <>
                <h3>Data gaps</h3>
                <ul className="gap-list">
                  {view.fetch_data_gaps.map((g, i) => <li key={i}>{g}</li>)}
                </ul>
              </>
            )}
          </div>

          <NarrativeRail ticker={view.ticker} />
        </div>
      )}
    </div>
  );
}
