// Mirrors deepdive/scorecard_view.py dataclasses field-for-field (ADR-040:
// frontend renders only what the API returns — no client-side scoring).

export interface CompanyHeader {
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  market_cap_usd: number | null;
  cik: string | null;
  ipo_date: string | null;
  exchange: string | null;
  fiscal_year_end_month: number | null;
  ceo_name: string | null;
  ceo_equity_pct: number | null;
  ceo_equity_pct_state: string | null;
  is_founder_ceo: boolean | null;
  pe_trailing: number | null;
  pb_ratio: number | null;
  ev_ebitda: number | null;
  beta: number | null;
  latest_fiscal_year: number | null;
  latest_period_end: string | null;
  latest_revenue: number | null;
  latest_net_income: number | null;
}

export interface StageView {
  stage: string;
  reasoning: Record<string, unknown>;
}

export interface CompositeView {
  score: number;
  verdict: string;
  mode_resolved: string;
  weights_used: Record<string, number>;
  weights_renormalised: boolean;
}

export interface FrameworkView {
  code: string;
  title: string;
  score: number;
  max_score: number;
  verdict: string;
  band: string;
  key_signals: [string, string][];
  data_gaps: string[];
  notes: string;
  is_unfeasible: boolean;
  unfeasible_reason: string;
}

export interface OverlayTriggerView {
  overlay_type: string;
  trigger_id: string;
  condition: string;
  relevant_numbers: Record<string, unknown>;
  framework_section: string;
}

export interface ScorecardView {
  ticker: string;
  run_date: string;
  mode_used: string;
  company: CompanyHeader;
  stage: StageView;
  composite: CompositeView;
  frameworks: FrameworkView[];
  overlay_triggers: OverlayTriggerView[];
  fetch_data_gaps: string[];
  overlay_verdicts: Record<string, string>;
  schema_version: string;
}

export interface SkillInfo {
  name: string;
  version?: string;
  dangerous?: boolean;
  description?: string;
  shadow_status?: {
    total_invocations: number;
    clean_invocations: number;
    needed_to_graduate: number;
    currently_in_shadow: boolean;
  };
  error?: string;
}

export interface SkillResult {
  success: boolean;
  postconditions: { pass_: boolean; observed: string; expected: string }[];
  anomalies: Record<string, unknown>[];
  render_output: string;
  cost_usd: number;
  error_message: string | null;
}

export interface ScheduledJob {
  name: string;
  type: string;
  cron: string;
  tickers?: string[];
  frameworks?: string[] | null;
  tier?: number;
  registered_at: string;
  last_run: string | null;
}

export interface ScreenerCandidate {
  ticker: string;
  name: string;
  sector: string;
  market_cap_b: number;
  exclusion_status: string | null;  // null under the `none` policy
  last_screened: string;
  retention_days: number;
}

export interface ScreenerRun {
  id: number;
  run_date: string;
  region: string;
  mode: string;
  universe: number;
  passed_gates: number;
}

export interface ScreenerBoardRow {
  ticker: string;
  name: string;
  sector: string;
  market_cap_b: number;
  exclusion_status: string | null;
  exclusion_reason: string | null;  // set when the policy recorded one
  excluded: boolean;                 // the policy's own predicate, whatever its status words
  composite: number | null;
  verdict: string | null;
  f1: number | null; f2: number | null; f3: number | null; f4: number | null;
  f5: number | null; f6: number | null; f7: number | null;
}

export interface BullBearPoint {
  headline: string;
  detail: string;
  framework_codes: string[];
}

export interface RiskFactor {
  factor: string;
  severity: string;
  grounded_in: string;
}

export interface NarrativeAudit {
  provider?: string;
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  fallback_used?: boolean;
  status?: string;
}

export interface Narrative {
  generated: boolean;
  run_id?: number;
  one_liner?: string;
  bull?: BullBearPoint[];
  bear?: BullBearPoint[];
  risks?: RiskFactor[];
  data_caveats?: string[];
  audit?: NarrativeAudit;
  guard_warnings?: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  cost_usd: number | null;
}

export interface ChatResponse {
  reply: string;
  provider: string;
  model: string;
  cost_usd: number;
  guard_warnings: string[];
}

export interface OverviewStats {
  screener_candidates: number;
  deep_dives_30d: number;
  deep_dives_30d_by_verdict: Record<string, number>;
  avg_composite_30d: number | null;
  universe_count: number | null;
}

export interface RecentDive {
  ticker: string;
  name: string;
  sector: string | null;
  stage: string | null;
  composite: number | null;
  verdict: string | null;
  run_date: string;
  f1: number | null; f2: number | null; f3: number | null; f4: number | null;
  f5: number | null; f6: number | null; f7: number | null;
}

// ── Valuation (ADR-027 Damodaran + ADR-042 Greenwald) ────────────────────
// Mirrors api/app.py::valuation. `reliability.verdict` is load-bearing: a
// client MUST NOT render damodaran.intrinsic_value_per_share as a valuation
// when it is "unreliable" (ADR-030/042 — a correct calculation on an
// inapplicable model anchors harder than no number at all).

export interface ValuationReliability {
  verdict: "reliable" | "qualified" | "unreliable" | "unavailable";
  reasons: string[];
}

export interface DamodaranView {
  tier: string;
  maturity_tier: string | null;
  intrinsic_value_per_share: number | null;
  current_price: number | null;
  margin_of_safety_pct: number | null;
  anchor_epv_per_share: number | null;
  mos_vs_epv_pct: number | null;
  reverse_implied_growth_rate: number | null;
  reverse_implied_growth_feasibility: string | null;
  narrative_premium_pct: number | null;
  wacc: number | null;
  inversion_questions: string[];
  data_gaps: string[];
}

export interface GreenwaldView {
  wacc_used: number;
  wacc_source: string;
  current_price: number | null;
  epv_applicability: "applicable" | "inflecting" | "not_applicable";
  epv_applicability_reason: string;
  asset_value_per_share: number | null;
  asset_value_total: number | null;
  epv_per_share_full_history: number | null;
  normalized_op_margin: number | null;
  growth_capex_added_back: number | null;
  epv_per_share_recent_regime: number | null;
  recent_regime_margin: number | null;
  franchise_verdict: "franchise" | "no_franchise" | "value_destruction" | "indeterminate";
  epv_to_av_ratio: number | null;
  growth_is_worth_paying_for: boolean | null;
  franchise_interpretation: string;
  data_gaps: string[];
}

export interface ValuationView {
  ticker: string;
  damodaran: DamodaranView | null;
  greenwald: GreenwaldView | null;
  reliability: ValuationReliability;
  synthesis: string;
  errors: string[];
}
