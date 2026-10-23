const TITLES: Record<string, string> = {
  F1: "Pre-Discovery Alpha", F2: "Momentum", F3: "Innovation Compounder",
  F4: "Stealth Accumulation", F5: "Growth Quality", F6: "Platform Dominator", F7: "Smart Beta Timing",
};

function level(score: number): "hi" | "mid" | "lo" {
  return score >= 7 ? "hi" : score >= 4 ? "mid" : "lo";
}

export default function Equalizer({
  scores, height = 52, variant = "main",
}: {
  scores: { code: string; score: number | null }[];
  height?: number;
  variant?: "main" | "mini";
}) {
  if (variant === "mini") {
    // Screener board (Turn 3) — no popover, no interactivity, just density.
    return (
      <div className="mini">
        {scores.map(({ code, score }) => (
          <span
            key={code} className="mbt" style={{ height }}
            aria-label={score !== null ? `${code} score ${score.toFixed(1)} of 10` : `${code}: no score`}
          >
            {score !== null && <span className={`mbf lvl-${level(score)}`} style={{ height: `${score * 10}%` }} />}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="eq" style={{ height }}>
      {scores.map(({ code, score }) => {
        if (score === null) {
          return (
            <div key={code} className="bar" style={{ height, opacity: 0.25, cursor: "default" }} title={`${code}: no score`} />
          );
        }
        const lvl = level(score);
        return (
          <button key={code} className="bar" style={{ height }} aria-label={`${code} ${TITLES[code] ?? ""}, score ${score.toFixed(1)} of 10`}>
            <span className={`barfill lvl-${lvl}`} style={{ height: `${score * 10}%` }} />
            <span className="pop">
              <span className="popn">{code} · {score.toFixed(1)} / 10</span>
              {TITLES[code] ?? ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}
