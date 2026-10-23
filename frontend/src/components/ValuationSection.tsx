import { useEffect, useState } from "react";
import { getValuation } from "../api";
import type { ValuationView } from "../types";

// Lazy by construction (ADR-040 / CLAUDE.md §LAZY LOAD EVERYTHING): nothing
// fires on mount. Two reasons, one technical and one analytical —
//   1. It runs two full valuation engines per call.
//   2. An intrinsic value the user did not ask for is an anchor they did not
//      choose. Rendering a number before it is requested is the anchoring
//      failure mode ADR-042 exists to avoid (`bias/anchoring_bias`).

const VERDICT_COPY: Record<string, string> = {
  reliable: "Headline forward DCF is usable.",
  qualified: "Headline forward DCF is usable WITH the caveats below.",
  unreliable: "Headline forward DCF is NOT usable as a valuation.",
  unavailable: "The engine could not produce a forward DCF.",
};

const FRANCHISE_COPY: Record<string, string> = {
  franchise: "Earnings power exceeds reproduction cost — growth is worth paying for.",
  no_franchise: "Commodity economics — growth is worth approximately ZERO.",
  value_destruction: "Assets earn less than they cost to assemble — growth destroys value.",
  indeterminate: "UNEVAL — not enough data to test. This is NOT the same as 'no moat'.",
};

function num(v: number | null | undefined, dp = 2): string {
  return v === null || v === undefined ? "—" : v.toLocaleString(undefined, {
    minimumFractionDigits: dp, maximumFractionDigits: dp,
  });
}

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

// Gap to price, normalised BY PRICE, so every row in the column is comparable.
//
// The column previously showed `margin_of_safety_pct`, which the engine defines
// as (IV − price) / IV — normalised by the intrinsic value, not the price. Under
// a "vs price" header that read as NVDA's DCF being 272% below price when the
// actual gap is 73%. Same number, wrong denominator, wrong story. Margin of
// safety is still reported, but labelled as itself.
function vsPrice(value: number | null | undefined, price: number | null | undefined): string {
  if (value === null || value === undefined || !price) return "—";
  return `${(((value - price) / price) * 100).toFixed(1)}%`;
}

export default function ValuationSection({ ticker }: { ticker: string }) {
  const [data, setData] = useState<ValuationView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showGaps, setShowGaps] = useState(false);

  // Reset on ticker change. Without this the component keeps the PREVIOUS
  // ticker's valuation: load NVDA → run → switch to BONEX.ST → the scorecard
  // above updates but this section still shows NVDA's $56.78 and 3.82x
  // franchise ratio, now captioned as BONEX. Rendering one company's intrinsic
  // value under another company's name is the worst failure this component can
  // have, and it is invisible to API tests — only switching tickers in the real
  // UI surfaces it.
  //
  // Done here rather than via a `key` prop in the parent so the guarantee is
  // self-contained: correct however DivePanel chooses to mount it.
  useEffect(() => {
    setData(null);
    setError(null);
    setShowGaps(false);
  }, [ticker]);

  async function handleRun() {
    setLoading(true);
    setError(null);
    try {
      setData(await getValuation(ticker));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const d = data?.damodaran ?? null;
  const g = data?.greenwald ?? null;
  const price = d?.current_price ?? g?.current_price ?? null;
  const verdict = data?.reliability.verdict;
  const ivUnusable = verdict === "unreliable" || verdict === "unavailable";

  return (
    <>
      <h3>Intrinsic value</h3>
      {!data && (
        <div className="form-row">
          <button onClick={handleRun} disabled={loading}>
            {loading ? "Valuing…" : "Run Intrinsic Value"}
          </button>
          <span className="dim">
            Damodaran forward DCF + Greenwald ladder (asset value → earnings power →
            franchise test). Deterministic, no LLM spend.
          </span>
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      {data && (
        <>
          <p>
            <strong>{VERDICT_COPY[verdict ?? "unavailable"]}</strong>{" "}
            <span className="dim">
              {d ? `tier ${d.tier}` : ""}{d?.maturity_tier ? ` · maturity ${d.maturity_tier}` : ""}
              {d?.wacc ? ` · WACC ${pct(d.wacc)}` : ""}
            </span>
          </p>

          <table>
            <thead>
              <tr><th>Lens</th><th>Per share</th><th>vs price</th><th>Reads as</th></tr>
            </thead>
            <tbody>
              <tr>
                <td>Market price</td>
                <td>{num(price)}</td>
                <td>—</td>
                <td className="dim">what you pay today</td>
              </tr>
              <tr>
                <td>Damodaran forward DCF</td>
                <td>
                  {ivUnusable
                    ? <span className="dim">withheld</span>
                    : num(d?.intrinsic_value_per_share)}
                </td>
                <td>
                  {ivUnusable ? "—" : vsPrice(d?.intrinsic_value_per_share, price)}
                </td>
                <td className="dim">
                  {ivUnusable
                    ? "not quotable — see caveats"
                    : <>growth + fade + terminal value · margin of safety{" "}
                        {pct(d?.margin_of_safety_pct)} (normalised by IV)</>}
                </td>
              </tr>
              {g && (
                <>
                  <tr>
                    <td>Greenwald asset value</td>
                    <td>{num(g.asset_value_per_share)}</td>
                    <td>{vsPrice(g.asset_value_per_share, price)}</td>
                    <td className="dim">competitor's cost to rebuild the assets</td>
                  </tr>
                  <tr>
                    <td>Greenwald EPV (full history)</td>
                    <td>{num(g.epv_per_share_full_history)}</td>
                    <td>{vsPrice(g.epv_per_share_full_history, price)}</td>
                    <td className="dim">
                      median margin {pct(g.normalized_op_margin)} at zero growth
                    </td>
                  </tr>
                  {g.epv_per_share_recent_regime !== null && (
                    <tr>
                      <td><strong>Greenwald EPV (recent regime)</strong></td>
                      <td><strong>{num(g.epv_per_share_recent_regime)}</strong></td>
                      <td><strong>{vsPrice(g.epv_per_share_recent_regime, price)}</strong></td>
                      <td className="dim">
                        post-inflection years only, median {pct(g.recent_regime_margin)}
                      </td>
                    </tr>
                  )}
                </>
              )}
              <tr>
                <td>Market-implied growth</td>
                <td>{pct(d?.reverse_implied_growth_rate)}</td>
                <td>—</td>
                <td className="dim">
                  feasibility: {d?.reverse_implied_growth_feasibility ?? "—"}
                  {d?.reverse_implied_growth_feasibility === "extreme" &&
                    " — saturated at the model's WACC−50bps ceiling, read as 'more than this model can express'"}
                </td>
              </tr>
            </tbody>
          </table>

          {g && (
            <>
              <h3>Franchise test</h3>
              <p>
                <span className={`badge ${g.franchise_verdict}`}>
                  {g.franchise_verdict.replace(/_/g, " ")}
                </span>{" "}
                {g.epv_to_av_ratio !== null && (
                  <strong>EPV / AV = {g.epv_to_av_ratio.toFixed(2)}×</strong>
                )}{" "}
                <span className="dim">{FRANCHISE_COPY[g.franchise_verdict]}</span>
              </p>
              <p className="dim">{g.franchise_interpretation}</p>
              {g.epv_applicability !== "applicable" && (
                <div className="error-box">
                  EPV applicability: <strong>{g.epv_applicability}</strong> —{" "}
                  {g.epv_applicability_reason}
                </div>
              )}
            </>
          )}

          {(data.reliability.reasons.length > 0) && (
            <>
              <h3>Why the headline is qualified</h3>
              <ul className="gap-list">
                {data.reliability.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </>
          )}

          <h3>Cross-engine reading</h3>
          <p>{data.synthesis}</p>

          {d && d.inversion_questions.length > 0 && (
            <>
              <h3>Inversion — what must be true for this to be wrong</h3>
              <ul className="gap-list">
                {d.inversion_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </>
          )}

          <div className="form-row">
            <button className="secondary" onClick={() => setShowGaps((s) => !s)}>
              {showGaps ? "Hide" : "Show"} data gaps (
              {(d?.data_gaps.length ?? 0) + (g?.data_gaps.length ?? 0)})
            </button>
            <button className="secondary" onClick={handleRun} disabled={loading}>
              {loading ? "Recomputing…" : "Recompute"}
            </button>
          </div>
          {showGaps && (
            <ul className="gap-list">
              {(d?.data_gaps ?? []).map((x, i) => <li key={`d${i}`}>{x}</li>)}
              {(g?.data_gaps ?? []).map((x, i) => <li key={`g${i}`}>[greenwald] {x}</li>)}
            </ul>
          )}
          {data.errors.length > 0 && (
            <ul className="gap-list">
              {data.errors.map((x, i) => <li key={`e${i}`}>{x}</li>)}
            </ul>
          )}
        </>
      )}
    </>
  );
}
