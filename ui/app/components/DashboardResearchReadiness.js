import { fmtInt } from "../lib/format";
import StateNotice from "./StateNotice";

export default function DashboardResearchReadiness({ res }) {
  const readiness = res.ok ? res.data : null;
  const families = (readiness && readiness.families) || {};
  const stock = families.stock_selection || {};
  const fundamentals = families.fundamentals || {};
  const intraday = families.intraday || {};
  const stockDates = stock.qualifying_shared_dates ?? stock.observed_shared_dates;
  const fundamentalDates = fundamentals.qualifying_snapshots ?? fundamentals.observed_snapshots;
  const sessions = intraday.qualifying_sessions || intraday.observed_sessions || {};

  return (
    <>
      <h2>Research data readiness</h2>
      {!res.ok ? (
        <StateNotice res={res} />
      ) : (
        <>
          <div className="strip">
            <div className="stat">
              <div className="label">Stock selection</div>
              <div className="value">
                {fmtInt(stockDates)} / {fmtInt(stock.minimum_shared_dates)}
              </div>
              <div className="faint">
                breadth-qualified dates · {stock.status} · input {stock.input_status}
              </div>
            </div>
            <div className="stat">
              <div className="label">Fundamentals</div>
              <div className="value">
                {fmtInt(fundamentalDates)} / {fmtInt(fundamentals.minimum_snapshots)}
              </div>
              <div className="faint">
                breadth-qualified snapshots · min {fmtInt(
                  fundamentals.minimum_observed_names_per_snapshot
                )} usable equities · {fundamentals.status} · input {fundamentals.input_status}
              </div>
            </div>
            {[
              ["1m", "Intraday 1m"],
              ["5m", "Intraday 5m"],
            ].map(([interval, label]) => (
              <div className="stat" key={interval}>
                <div className="label">{label}</div>
                <div className="value">
                  {fmtInt(sessions[interval])} /{" "}
                  {fmtInt(intraday.minimum_sessions_per_interval)}
                </div>
                <div className="faint">
                  substantial-bar, breadth-qualified sessions · {intraday.status} · input{" "}
                  {intraday.input_status}
                </div>
              </div>
            ))}
          </div>
          <p className="faint" style={{ marginTop: 8 }}>
            {readiness.notice}
          </p>
        </>
      )}
    </>
  );
}
