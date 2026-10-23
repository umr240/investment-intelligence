import { useEffect, useState } from "react";
import { addDeepdiveJob, removeJob, schedulerJobs } from "../api";
import type { ScheduledJob } from "../types";

export default function SchedulerPanel() {
  const [jobs, setJobs] = useState<ScheduledJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [tickers, setTickers] = useState("");
  const [cron, setCron] = useState("0 8 * * 1");
  const [tier, setTier] = useState(1);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setJobs(await schedulerJobs());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleAdd() {
    if (!name.trim() || !tickers.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await addDeepdiveJob({ name: name.trim(), tickers: tickers.trim(), cron, tier });
      setName("");
      setTickers("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(jobName: string) {
    setBusy(true);
    try {
      await removeJob(jobName);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="panel">
        <h2>Scheduler</h2>
        <p className="dim">
          Registers into the same <code>.ii_jobs.json</code> <code>invest scheduler add-deepdive</code> writes.
          Jobs only fire once <code>invest scheduler start</code> is running as a separate daemon — the
          in-process scheduler (ADR-040 §3.4) isn't wired up yet, so registering here does not itself
          make anything execute on schedule.
        </p>
        <div className="form-row">
          <label>Job name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="monday-watch" style={{ width: 160 }} /></label>
          <label>Tickers<input value={tickers} onChange={(e) => setTickers(e.target.value)} placeholder="NVDA,COST" style={{ width: 140 }} /></label>
          <label>Cron<input value={cron} onChange={(e) => setCron(e.target.value)} style={{ width: 120 }} /></label>
          <label>
            Tier
            <select value={tier} onChange={(e) => setTier(Number(e.target.value))}>
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>
          </label>
          <button onClick={handleAdd} disabled={busy || !name.trim() || !tickers.trim()}>Add Deep-Dive Job</button>
        </div>
        {error && <div className="error-box">{error}</div>}
      </div>

      <div className="panel">
        <h2>Registered jobs</h2>
        <table>
          <thead><tr><th>Name</th><th>Type</th><th>Cron</th><th>Tickers</th><th>Last run</th><th></th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.name}>
                <td>{j.name}</td>
                <td>{j.type}</td>
                <td>{j.cron}</td>
                <td>{j.tickers?.join(", ") || "—"}</td>
                <td>{j.last_run || "never"}</td>
                <td><button className="danger" disabled={busy} onClick={() => handleRemove(j.name)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && <p className="dim">No jobs registered.</p>}
      </div>
    </div>
  );
}
