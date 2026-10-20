import { fmtInt, fmtPct } from "../lib/format";

function Check({ label, ok, value }) {
  const mark = ok === true ? "✓" : ok === false ? "✗" : "·";
  const className = ok === true ? "pos" : ok === false ? "neg" : "faint";
  return (
    <div style={{ display: "flex", gap: 12, justifyContent: "space-between",
      padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
      <span>
        <span className={className} style={{ fontFamily: "var(--mono)", marginRight: 8 }}>
          {mark}
        </span>
        {label}
      </span>
      <span className="mono muted">{value}</span>
    </div>
  );
}

export default function CandidateTemplateChecks({ screen }) {
  return (
    <div>
      <h2>Template checks</h2>
      {!screen ? (
        <div className="empty">This ticker is not in the screen table.</div>
      ) : (
        <div className="card">
          <p className={screen.passes_template ? "pos" : "neg"}>
            {screen.passes_template ? "Passes full template" : "Does not pass full template"}
            {" · "}{fmtInt(screen.template_score)}/8
          </p>
          <h3>Eight scored criteria</h3>
          <div data-scored-criteria>
            <Check label="Close > SMA150 and SMA200" ok={null} value="Not recorded" />
            <Check label="SMA150 > SMA200" ok={null} value="Not recorded" />
            <Check label="SMA200 > its value 21 sessions ago" ok={null} value="Not recorded" />
            <Check label="SMA50 > SMA150 > SMA200" ok={null} value="Not recorded" />
            <Check label="Close > SMA50" ok={screen.dist_50d > 0} value={fmtPct(screen.dist_50d)} />
            <Check label="Close ≥ 1.30 × 52w low" ok={screen.off_52w_low >= 0.3}
              value={fmtPct(screen.off_52w_low)} />
            <Check label="Close ≥ 0.75 × 52w high" ok={screen.off_52w_high >= -0.25}
              value={fmtPct(screen.off_52w_high)} />
            <Check label="RS rank ≥ 70" ok={screen.rs_rank >= 70} value={fmtInt(screen.rs_rank)} />
          </div>
          <p className="faint">
            The stored score includes all eight criteria. Individual results for the four
            SMA relationship and slope criteria are not recorded; the other four use
            stored screen summaries.
          </p>
          <h3>Supplemental context · unscored</h3>
          <p>Base tight: {String(screen.base_tight)} · Volume dry-up: {String(screen.vol_dryup)}</p>
          <p className="faint">These context checks do not contribute to the score.</p>
        </div>
      )}
    </div>
  );
}
