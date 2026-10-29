import { useEffect, useState } from "react";
import { generateNarrative, getChatHistory, getNarrative, sendChatMessage } from "../api";
import type { ChatMessage, Narrative } from "../types";

// Turn 2 ("Deep Dive + Narrative") from Claude Design. Reads (GET
// narrative/chat history) auto-load — free, already-persisted. Both
// POST actions (generate narrative, send a chat message) spend real
// Anthropic/OpenAI tokens and require an explicit click — never fired
// on mount, mirroring `--narrate` / `invest chat` in the CLI.

const SUGGESTIONS = ["Steelman the bear", "What flips it to watchlist?"];

export default function NarrativeRail({ ticker }: { ticker: string }) {
  const [narrative, setNarrative] = useState<Narrative | null>(null);
  const [genLoading, setGenLoading] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  useEffect(() => {
    getNarrative(ticker).then(setNarrative).catch(() => setNarrative({ generated: false }));
    getChatHistory(ticker).then(setChat).catch(() => setChat([]));
  }, [ticker]);

  async function handleGenerate() {
    setGenLoading(true);
    setGenError(null);
    try {
      const n = await generateNarrative(ticker);
      setNarrative(n);
    } catch (e) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenLoading(false);
    }
  }

  const withheld = !!narrative?.stale; // DEC-47: chat follows the narrative's rule

  async function handleSend(message: string) {
    if (!message.trim()) return;
    setChatLoading(true);
    setChatError(null);
    setChat((prev) => [...prev, { role: "user", content: message, cost_usd: null }]);
    setChatInput("");
    try {
      const r = await sendChatMessage(ticker, message);
      setChat((prev) => [...prev, { role: "assistant", content: r.reply, cost_usd: r.cost_usd }]);
      if (r.guard_warnings.length > 0) {
        setChatError(`Guard warnings: ${r.guard_warnings.join("; ")}`);
      }
    } catch (e) {
      setChatError(e instanceof Error ? e.message : String(e));
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <div style={{ borderLeft: "2px solid var(--color-divider)", background: "var(--color-surface)", display: "flex", flexDirection: "column", minHeight: 400 }}>
      <div style={{ padding: "18px 20px", borderBottom: "2px solid var(--color-divider)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h4>Narrative</h4>
          {narrative?.generated && (narrative.audit?.status === "ok" && !(narrative.guard_warnings ?? []).length ? (
            <span className="mono dim" style={{ display: "flex", alignItems: "center", gap: 6 }} data-testid="narrative-grounded">
              <span className="live" />grounded
            </span>
          ) : (
            <span className="mono" style={{ color: "var(--color-accent-800)" }} data-testid="narrative-guard-failed">
              guard failed
            </span>
          ))}
        </div>
        <p className="mono dim" style={{ marginTop: 8 }}>
          Editorial synthesis — bull, bear, risk. Every claim cites a scorecard number. No new facts introduced.
        </p>
      </div>

      <div style={{ padding: "4px 20px 8px", overflow: "auto", flex: 1 }}>
        {narrative?.stale && (
          <div style={{ padding: "16px 0" }} data-testid="narrative-stale">
            <p>Narrative withheld: {narrative.stale_reason}.</p>
            <p className="dim">Re-run the dive, then generate a narrative.</p>
          </div>
        )}

        {!narrative?.generated && !narrative?.stale && (
          <div style={{ padding: "16px 0" }}>
            <p className="dim">No narrative generated yet for this dive.</p>
            <button onClick={handleGenerate} disabled={genLoading}>
              {genLoading ? "Generating…" : "Generate Narrative (real token spend)"}
            </button>
            {genError && <div className="error-box">{genError}</div>}
          </div>
        )}

        {narrative?.generated && (
          <>
            {narrative.one_liner && <p style={{ fontStyle: "italic", padding: "12px 0", borderBottom: "1px solid var(--color-divider)" }}>{narrative.one_liner}</p>}

            {narrative.verdict && (
              <div style={{ padding: "16px 0", borderBottom: "1px solid var(--color-divider)" }} data-testid="narrative-verdict">
                <div className="mono dim" style={{ letterSpacing: ".1em", marginBottom: 8 }}>VERDICT</div>
                <strong>{narrative.verdict}</strong>
                {narrative.verdict_reason && <p style={{ fontSize: 13, lineHeight: 1.55, margin: "4px 0 6px" }}>{narrative.verdict_reason}</p>}
                <p className="mono dim" style={{ margin: "4px 0" }}>
                  Owner-operator answer: {narrative.owner_operator_answer ?? "—"} · Moat direction: {narrative.moat_direction ?? "—"}
                </p>
                {(narrative.triggers ?? []).length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div className="mono dim" style={{ marginBottom: 4 }}>Triggers that would change it</div>
                    {narrative.triggers!.map((t, i) => (
                      <div key={i} style={{ fontSize: 13, margin: "2px 0" }}>
                        <span className="cite" style={{ marginRight: 6 }}>{t.field_id}</span>{t.condition}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {(narrative.bull ?? []).length > 0 && (
              <div style={{ padding: "16px 0", borderBottom: "1px solid var(--color-divider)" }}>
                <div className="mono dim" style={{ letterSpacing: ".1em", marginBottom: 8 }}>BULL CASE</div>
                {narrative.bull!.map((p, i) => (
                  <div key={i} style={{ marginBottom: 10 }}>
                    <strong>{p.headline}</strong>
                    <p style={{ fontSize: 13, lineHeight: 1.55, margin: "4px 0 6px" }}>{p.detail}</p>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {p.framework_codes.map((c) => <span key={c} className="cite">{c}</span>)}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {(narrative.bear ?? []).length > 0 && (
              <div style={{ padding: "16px 0", borderBottom: "1px solid var(--color-divider)" }}>
                <div className="mono dim" style={{ letterSpacing: ".1em", marginBottom: 8 }}>BEAR CASE</div>
                {narrative.bear!.map((p, i) => (
                  <div key={i} style={{ marginBottom: 10 }}>
                    <strong>{p.headline}</strong>
                    <p style={{ fontSize: 13, lineHeight: 1.55, margin: "4px 0 6px" }}>{p.detail}</p>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {p.framework_codes.map((c) => <span key={c} className="cite">{c}</span>)}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {(narrative.risks ?? []).length > 0 && (
              <div style={{ padding: "16px 0", borderBottom: "1px solid var(--color-divider)" }}>
                <div className="mono dim" style={{ letterSpacing: ".1em", marginBottom: 8 }}>KEY RISKS</div>
                {narrative.risks!.map((r, i) => (
                  <div key={i} style={{ marginBottom: 8, fontSize: 13 }}>
                    <span className="badge exclude" style={{ marginRight: 6 }}>{r.severity}</span>
                    {r.factor} <span className="cite">{r.grounded_in}</span>
                  </div>
                ))}
              </div>
            )}

            {(narrative.data_caveats ?? []).length > 0 && (
              <div style={{ padding: "12px 0" }}>
                <div className="mono dim" style={{ letterSpacing: ".1em", marginBottom: 6 }}>DATA CAVEATS</div>
                {narrative.data_caveats!.map((c, i) => <p key={i} className="dim" style={{ margin: "2px 0" }}>· {c}</p>)}
              </div>
            )}

            {(narrative.guard_warnings ?? []).length > 0 && (
              <div className="error-box">
                ⚠ Hallucination guard warnings — treat with extra scrutiny:
                {narrative.guard_warnings!.map((w, i) => <div key={i}>· {w}</div>)}
              </div>
            )}

            <button className="btn-secondary" style={{ marginTop: 12 }} onClick={handleGenerate} disabled={genLoading}>
              {genLoading ? "Regenerating…" : "Regenerate (new spend)"}
            </button>
          </>
        )}

        {chat.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "2px solid var(--color-divider)", paddingTop: 12 }}>
            <div className="mono dim" style={{ letterSpacing: ".1em", marginBottom: 8 }}>CONVERSATION</div>
            {chat.map((m, i) => (
              <div key={i} className={`chat-turn ${m.role}`}>
                <span className="role">{m.role}{m.cost_usd !== null ? ` · $${m.cost_usd.toFixed(4)}` : ""}</span>
                {m.content}
              </div>
            ))}
          </div>
        )}
        {chatError && <div className="error-box">{chatError}</div>}
      </div>

      <div style={{ marginTop: "auto", padding: "16px 20px", borderTop: "2px solid var(--color-divider)" }}>
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 12 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip-sug" onClick={() => handleSend(s)} disabled={chatLoading || withheld}>{s}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            placeholder={withheld ? "Chat withheld: re-run the dive" : "Ask about this dive…"} value={chatInput}
            disabled={withheld} data-testid="chat-input"
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSend(chatInput); }}
            style={{ flex: 1 }}
          />
          <button onClick={() => handleSend(chatInput)} disabled={chatLoading || withheld || !chatInput.trim()}>
            {chatLoading ? "…" : "Send"}
          </button>
        </div>
        <p className="dim" style={{ marginTop: 6 }}>Real token spend per message — open conversation, grounded in this dive's scorecard.</p>
      </div>
    </div>
  );
}
