import { useEffect, useState } from "react";
import OverviewPanel from "./components/OverviewPanel";
import DivePanel from "./components/DivePanel";
import ScreenerPanel from "./components/ScreenerPanel";
import SkillsPanel from "./components/SkillsPanel";
import SchedulerPanel from "./components/SchedulerPanel";
import { health } from "./api";

// Nav order matches Claude Design's Overview Dashboard.dc.html (Modernist
// project, 5adfde5a-...): Overview / Screener / Deep Dive / Narrative /
// Scheduler. "Skills" isn't in that mockup's nav — kept anyway since it's
// real, working functionality (ADR-032). "Narrative" in the mockup is a
// rail WITHIN the Deep Dive page (two-column layout), not a separate
// route — its nav link just opens Deep Dive, same as clicking a row.
// Turn 2 (Deep Dive + Narrative) and Turn 3 (Screener) both finished in
// Claude Design 2026-08-09 — both backed by real endpoints now:
// deepdive/narrative.py (bull/bear/risk) and deepdive/conversation.py
// (the open-conversation chat, via the existing `invest chat` machinery).
type Tab = "overview" | "screener" | "dive" | "scheduler" | "skills";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "screener", label: "Screener" },
  { id: "dive", label: "Deep Dive" },
  { id: "scheduler", label: "Scheduler" },
  { id: "skills", label: "Skills" },
];

function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [diveTicker, setDiveTicker] = useState<string | undefined>(undefined);
  const [backend, setBackend] = useState<string>("checking…");

  useEffect(() => {
    health()
      .then((h) => setBackend(`${h.db_backend} · ${h.environment}`))
      .catch(() => setBackend("API unreachable — is uvicorn running on :8000?"));
  }, []);

  function openTicker(ticker: string) {
    setDiveTicker(ticker);
    setTab("dive");
  }

  return (
    <>
      <div className="nav">
        <span className="nav-brand">INVESTMENT<span style={{ color: "var(--color-accent)" }}>·</span>INTELLIGENCE</span>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`navlink ${tab === t.id ? "navlink-active" : ""}`}
            aria-current={tab === t.id ? "page" : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
        <button className="navlink" onClick={() => setTab("dive")}>Narrative</button>
        <span className="mono dim" style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, marginLeft: 8 }}>
          <span className="live" />{backend}
        </span>
      </div>

      <div style={{ padding: "20px 24px" }}>
        {tab === "overview" && <OverviewPanel onOpenTicker={openTicker} />}
        {tab === "dive" && <DivePanel initialTicker={diveTicker} />}
        {tab === "screener" && <ScreenerPanel onOpenTicker={openTicker} />}
        {tab === "skills" && <SkillsPanel />}
        {tab === "scheduler" && <SchedulerPanel />}
      </div>
    </>
  );
}

export default App;
