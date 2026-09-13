import { fmtInt, fmtPct } from "../lib/format";

function Check({ label, ok, value }) {
  const mark = ok === true ? "✓" : ok === false ? "✗" : "·";
  const className = ok === true ? "pos" : ok === false ? "neg" : "faint";
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "5px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
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
          <Check
            label="Passes full template"
            ok={!!screen.passes_template}
            value={`${fmtInt(screen.template_score)}/8`}
          />
          <Check
            label="RS rank ≥ 70"
            ok={typeof screen.rs_rank === "number" ? screen.rs_rank >= 70 : null}
            value={fmtInt(screen.rs_rank)}
          />
          <Check
            label="Above 50d"
            ok={typeof screen.dist_50d === "number" ? screen.dist_50d >= 0 : null}
            value={fmtPct(screen.dist_50d)}
          />
          <Check
            label="Above 200d"
            ok={typeof screen.dist_200d === "number" ? screen.dist_200d >= 0 : null}
            value={fmtPct(screen.dist_200d)}
          />
          <Check
            label="Off 52w low"
            ok={typeof screen.off_52w_low === "number" ? screen.off_52w_low >= 0.3 : null}
            value={fmtPct(screen.off_52w_low)}
          />
          <Check
            label="Near 52w high"
            ok={typeof screen.off_52w_high === "number" ? screen.off_52w_high >= -0.25 : null}
            value={fmtPct(screen.off_52w_high)}
          />
          <Check
            label="Base tight"
            ok={screen.base_tight ?? null}
            value={String(screen.base_tight)}
          />
          <Check
            label="Volume dry-up"
            ok={screen.vol_dryup ?? null}
            value={String(screen.vol_dryup)}
          />
        </div>
      )}
    </div>
  );
}
