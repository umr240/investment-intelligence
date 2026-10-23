// Thin fetch wrappers over api/app.py (ADR-040). One function per endpoint,
// no client-side transformation of the response — the API's JSON is the
// contract, this file just gives it a name and a type.

import type {
  ChatMessage,
  ChatResponse,
  Narrative,
  OverviewStats,
  RecentDive,
  ScheduledJob,
  ScorecardView,
  ScreenerBoardRow,
  ScreenerCandidate,
  ScreenerRun,
  SkillInfo,
  SkillResult,
  ValuationView,
} from "./types";

const BASE = "http://127.0.0.1:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function overviewStats() {
  return req<OverviewStats>("/overview/stats");
}

export function overviewRecentDives(limit = 10) {
  return req<RecentDive[]>(`/overview/recent-dives?limit=${limit}`);
}

export function health() {
  return req<{ ok: boolean; db_backend: string; environment: string; exclusion_policy: string }>("/health");
}

// ── Dive ─────────────────────────────────────────────────────────────────

export function runDive(ticker: string, opts: { tier?: number; mode?: string; frameworks?: string; force?: boolean }) {
  const p = new URLSearchParams();
  if (opts.tier) p.set("tier", String(opts.tier));
  if (opts.mode) p.set("mode", opts.mode);
  if (opts.frameworks) p.set("frameworks", opts.frameworks);
  if (opts.force) p.set("force", "true");
  return req<Record<string, unknown>>(`/dive/${ticker}?${p}`, { method: "POST" });
}

export function getScorecard(ticker: string) {
  return req<ScorecardView>(`/dive/${ticker}/scorecard`);
}

// ── Narrative + Chat ────────────────────────────────────────────────────
// Real Anthropic/OpenAI spend on the POST calls (~$0.08/narrative on Claude
// Sonnet 4.6, measured 2026-10-23; ADR-031 §3). Never call these from a useEffect / on mount — only from a click
// the user explicitly initiated, same role --narrate / invest chat plays
// in the CLI.

export function getNarrative(ticker: string) {
  return req<Narrative>(`/dive/${ticker}/narrative`);
}

export function generateNarrative(ticker: string) {
  return req<Narrative>(`/dive/${ticker}/narrative`, { method: "POST" });
}

export function getChatHistory(ticker: string) {
  return req<ChatMessage[]>(`/dive/${ticker}/chat`);
}

export function sendChatMessage(ticker: string, message: string) {
  const p = new URLSearchParams({ message });
  return req<ChatResponse>(`/dive/${ticker}/chat?${p}`, { method: "POST" });
}

// ── Overlays ─────────────────────────────────────────────────────────────

export function overlayStatus(ticker: string) {
  return req<Record<string, unknown>[]>(`/overlay/${ticker}`);
}

export function runOverlay(ticker: string, overlayType: string) {
  return req<Record<string, unknown>>(`/overlay/${ticker}/run?overlay_type=${overlayType}`, { method: "POST" });
}

// ── Screener ─────────────────────────────────────────────────────────────

export function screenerBoard() {
  return req<ScreenerBoardRow[]>("/screener/board");
}

export function screenerRuns(limit = 20) {
  return req<ScreenerRun[]>(`/screener/runs?limit=${limit}`);
}

export function screenerRunDetail(runId: number, tier = "all", limit = 50) {
  return req<Record<string, unknown>[]>(`/screener/runs/${runId}?tier=${tier}&limit=${limit}`);
}

export function screenerCandidates(sector?: string) {
  const p = sector ? `?sector=${encodeURIComponent(sector)}` : "";
  return req<ScreenerCandidate[]>(`/screener/candidates${p}`);
}

export function runStageA(opts: Record<string, string | number | undefined>) {
  const p = new URLSearchParams();
  Object.entries(opts).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
  return req<Record<string, unknown>>(`/screener/stage/a?${p}`, { method: "POST" });
}

export function runStageB(runId?: number) {
  const p = runId ? `?run_id=${runId}` : "";
  return req<Record<string, unknown>>(`/screener/stage/b${p}`, { method: "POST" });
}

export function runStageC(runId?: number, mode = "B") {
  const p = new URLSearchParams({ mode });
  if (runId) p.set("run_id", String(runId));
  return req<Record<string, unknown>>(`/screener/stage/c?${p}`, { method: "POST" });
}

// ── Skills ───────────────────────────────────────────────────────────────

export function listSkills() {
  return req<SkillInfo[]>("/skills");
}

export function runSkill(name: string, ticker?: string, confirm = false) {
  const p = new URLSearchParams();
  if (ticker) p.set("ticker", ticker);
  if (confirm) p.set("confirm", "true");
  return req<SkillResult>(`/skill/${name}/run?${p}`, { method: "POST" });
}

// ── Scheduler ────────────────────────────────────────────────────────────

export function schedulerJobs() {
  return req<ScheduledJob[]>("/scheduler/jobs");
}

export function addDeepdiveJob(opts: { name: string; tickers: string; cron: string; frameworks?: string; tier?: number }) {
  const p = new URLSearchParams({ name: opts.name, tickers: opts.tickers, cron: opts.cron });
  if (opts.frameworks) p.set("frameworks", opts.frameworks);
  if (opts.tier) p.set("tier", String(opts.tier));
  return req<{ ok: boolean }>(`/scheduler/jobs/deepdive?${p}`, { method: "POST" });
}

export function removeJob(name: string) {
  return req<{ ok: boolean }>(`/scheduler/jobs/${name}`, { method: "DELETE" });
}

// ── Valuation ────────────────────────────────────────────────────────────
// Deterministic — no LLM spend, so unlike the narrative endpoints this is
// safe to call freely. It is still LAZY (button-triggered, never on mount)
// because it runs two full valuation engines per call, and because an
// intrinsic value the user did not ask for is an anchor they did not choose.

export function getValuation(
  ticker: string,
  opts: { years?: number; greenwald?: boolean } = {},
) {
  const p = new URLSearchParams();
  if (opts.years) p.set("years", String(opts.years));
  if (opts.greenwald === false) p.set("greenwald", "false");
  return req<ValuationView>(`/valuation/${ticker}?${p}`);
}
