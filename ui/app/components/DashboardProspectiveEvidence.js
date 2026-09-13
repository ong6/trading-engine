import { fmtDate, fmtInt } from "../lib/format";
import StateNotice from "./StateNotice";

export default function DashboardProspectiveEvidence({ res }) {
  const meta = res.ok ? res.data : null;
  const sectorForward = (meta && meta.forward_review) || null;
  const xsForward = (meta && meta.xs_forward_review) || null;
  const e1Forward = (meta && meta.e1_forward) || null;

  return (
    <>
      <h2>Prospective strategy evidence</h2>
      {!res.ok ? (
        <StateNotice res={res} />
      ) : (
        <>
          <div className="strip">
            <div className="stat">
              <div className="label">Sector momentum vs SPY</div>
              <div className="value">
                {fmtInt(sectorForward?.shared_sessions)} /{" "}
                {fmtInt(sectorForward?.minimum_shared_sessions)}
              </div>
              <div className="faint">
                shared sessions · {sectorForward?.status || "UNKNOWN"}
              </div>
              <div className="faint">
                no verdict before {fmtDate(sectorForward?.eligible_after)}
              </div>
            </div>
            <div className="stat">
              <div className="label">XS momentum vs equal weight</div>
              <div className="value">
                {fmtInt(xsForward?.paired_complete_months)} /{" "}
                {fmtInt(xsForward?.minimum_paired_months)}
              </div>
              <div className="faint">
                complete paired months · {xsForward?.status || "UNKNOWN"}
              </div>
              <div className="faint">
                first signal {fmtDate(xsForward?.signal_date)} · no verdict before{" "}
                {fmtDate(xsForward?.eligible_after)}
              </div>
            </div>
            <div className="stat">
              <div className="label">E1 SPY Monday</div>
              <div className="value">
                {fmtInt(e1Forward?.observations)} /{" "}
                {fmtInt(e1Forward?.target_observations)}
              </div>
              <div className="faint">
                immutable observations · {e1Forward?.status || "UNKNOWN"}
              </div>
              <div className="faint">
                frozen sample end {fmtDate(e1Forward?.sample_end)}
              </div>
            </div>
          </div>
          <p className="faint" style={{ marginTop: 8 }}>
            No candidate has established prospective positive excess return. These frozen,
            paper-only gates collect evidence; they cannot promote a strategy, allocate capital,
            or authorize live trading.
          </p>
        </>
      )}
    </>
  );
}
