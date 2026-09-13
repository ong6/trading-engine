import Link from "next/link";
import { candidateHref } from "../lib/candidate-route";
import { fmtDate, fmtInt, fmtMoney, fmtPct, fmtPrice } from "../lib/format";
import StateNotice from "./StateNotice";

function EmptyScreen({ screen }) {
  return (
    <>
      <div className="empty">
        {screen.n_passing === 0
          ? "No names passed the template today."
          : `No candidates on page ${screen.results_page}.`}
      </div>
      {screen.results_has_previous ? (
        <p className="faint" style={{ marginTop: 10 }}>
          <Link href={`/?screen_page=${screen.results_total_pages}`}>
            ← Return to the last screen page
          </Link>
        </p>
      ) : null}
    </>
  );
}

function ScreenPagination({ screen }) {
  if (!screen.results_has_previous && !screen.results_has_next) return null;
  return (
    <p className="faint" style={{ marginTop: 10 }}>
      {screen.results_has_previous ? (
        <Link href={screen.results_page === 2 ? "/" : `/?screen_page=${screen.results_page - 1}`}>
          ← Previous screen page
        </Link>
      ) : null}
      {screen.results_has_previous && screen.results_has_next ? " · " : null}
      {screen.results_has_next ? (
        <Link href={`/?screen_page=${screen.results_page + 1}`}>Next screen page →</Link>
      ) : null}
    </p>
  );
}

function ScreenRows({ screen, rows }) {
  return (
    <>
      <p className="faint">
        Showing {fmtInt(screen.results_offset + 1)}–
        {fmtInt(screen.results_offset + rows.length)} of {fmtInt(screen.results_matching_count)}
        {` passing names · page ${screen.results_page} of ${screen.results_total_pages}`}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th className="num">Close</th>
              <th className="num">RS</th>
              <th className="num">Template</th>
              <th className="num">Dist 50d</th>
              <th className="num">Dist 200d</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ticker}>
                <td>
                  <Link href={candidateHref(row.ticker)}>
                    <strong>{row.ticker}</strong>
                  </Link>{" "}
                  {row.new_today ? <span className="tag new">new</span> : null}
                </td>
                <td className="num">{fmtPrice(row.close)}</td>
                <td className="num">{fmtInt(row.rs_rank)}</td>
                <td className="num">
                  {fmtInt(row.template_score)}
                  <span className="faint">/8</span>
                </td>
                <td className="num">{fmtPct(row.dist_50d)}</td>
                <td className="num">{fmtPct(row.dist_200d)}</td>
                <td>
                  <Link href={candidateHref(row.ticker)}>candidate →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ScreenPagination screen={screen} />
    </>
  );
}

export default function DashboardScreen({ res, league }) {
  const screen = res.ok ? res.data : null;
  const rows = (screen && screen.results) || [];
  return (
    <>
      <h2>
        Today&apos;s screen
        {screen ? (
          <span className="faint" style={{ fontWeight: 400 }}>
            {" "}
            · {fmtDate(screen.run_date)} · {fmtInt(screen.n_passing)} passing of{" "}
            {fmtInt(screen.n_total)} · {fmtInt(screen.n_new_today)} new today
          </span>
        ) : null}
      </h2>
      {!res.ok ? (
        <StateNotice res={res} />
      ) : rows.length === 0 ? (
        <EmptyScreen screen={screen} />
      ) : (
        <ScreenRows screen={screen} rows={rows} />
      )}
      {league && (
        <p className="faint" style={{ marginTop: 10 }}>
          Reference notional per paper portfolio:{" "}
          {fmtMoney(league.reference_notional)}
        </p>
      )}
    </>
  );
}
