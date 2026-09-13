import { fmtDate, fmtInt, fmtPrice } from "../lib/format";

export default function CandidateSummary({ data }) {
  const screen = data.screen;
  return (
    <p className="muted">
      Latest close <span className="mono">{fmtPrice(data.latest_close)}</span> ·{" "}
      {fmtInt(data.n_bars)} bars
      {screen ? (
        <>
          {" "}
          · screen {fmtDate(screen.run_date)} ·{" "}
          {screen.passes_template ? (
            <span className="pos">passes template</span>
          ) : (
            <span className="neg">does not pass</span>
          )}
        </>
      ) : (
        <> · not in the latest screen</>
      )}
    </p>
  );
}
