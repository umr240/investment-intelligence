import { useEffect, useState } from "react";
import { listSkills, runSkill } from "../api";
import type { SkillInfo, SkillResult } from "../types";

export default function SkillsPanel() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [ticker, setTicker] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, SkillResult | string>>({});

  useEffect(() => {
    listSkills().then(setSkills).catch((e) => setResults({ _load: String(e) }));
  }, []);

  async function invoke(name: string, confirm: boolean) {
    setBusy(name);
    setPendingConfirm(null);
    try {
      const r = await runSkill(name, ticker || undefined, confirm);
      setResults((prev) => ({ ...prev, [name]: r }));
    } catch (e) {
      setResults((prev) => ({ ...prev, [name]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  }

  function handleClick(s: SkillInfo) {
    if (s.dangerous) {
      setPendingConfirm(s.name);
    } else {
      invoke(s.name, false);
    }
  }

  return (
    <div>
      <div className="panel">
        <h2>Skills (ADR-032)</h2>
        <div className="form-row">
          <label>Ticker<input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="NVDA" style={{ width: 100 }} /></label>
        </div>
      </div>

      {skills.filter((s) => !s.error).map((s) => (
        <div className="panel" key={s.name}>
          <h3>
            /{s.name} {s.dangerous && <span className="badge exclude">dangerous</span>}
            <span className="dim"> v{s.version}</span>
          </h3>
          <p className="dim" style={{ whiteSpace: "pre-wrap" }}>{s.description}</p>
          {s.shadow_status && (
            <p className="dim">
              {s.shadow_status.currently_in_shadow ? "shadow-mode active" : "graduated"} ·{" "}
              {s.shadow_status.total_invocations} invocations, {s.shadow_status.clean_invocations} clean
            </p>
          )}

          <button onClick={() => handleClick(s)} disabled={busy !== null || (!ticker && s.name !== "dive-complete")}>
            {busy === s.name ? "Running…" : `Run /${s.name}`}
          </button>

          {pendingConfirm === s.name && (
            <div className="confirm-box">
              <strong>Confirm required</strong> — this skill is <code>dangerous: true</code> and calls
              Anthropic/OpenAI (real token spend, not a simulated cost). Per ADR-032 §2.4 this cannot be
              a single click.
              <div className="form-row" style={{ marginTop: 8 }}>
                <button onClick={() => invoke(s.name, true)}>Yes, run and spend tokens</button>
                <button className="secondary" onClick={() => setPendingConfirm(null)}>Cancel</button>
              </div>
            </div>
          )}

          {results[s.name] && (
            typeof results[s.name] === "string"
              ? <div className="error-box">{results[s.name] as string}</div>
              : (() => {
                  const r = results[s.name] as SkillResult;
                  return (
                    <div className={r.success ? "" : "error-box"}>
                      {r.success ? (
                        <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{r.render_output || JSON.stringify(r, null, 2)}</pre>
                      ) : (
                        r.error_message
                      )}
                    </div>
                  );
                })()
          )}
        </div>
      ))}

      {skills.some((s) => s.error) && (
        <div className="panel dim">
          {skills.filter((s) => s.error).map((s) => (
            <p key={s.name}>⚠ {s.name}: {s.error} (pre-existing, non-skill file in .claude/skills/)</p>
          ))}
        </div>
      )}
    </div>
  );
}
