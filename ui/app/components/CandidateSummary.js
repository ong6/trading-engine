import { fmtDate, fmtInt, fmtPrice } from "../lib/format";

export default function CandidateSummary({ data }) {
  const screen = data.screen;
  const provisional = data.bars.at(-1)?.provisional === true;
  return (
    <p className="muted">
      Latest close <span className="mono">{fmtPrice(data.latest_close)}</span> ·{" "}
      {fmtInt(data.n_bars)} bars
      {provisional ? <> · latest bar provisional until the next nightly re-fetch</> : null}
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
