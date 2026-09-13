import { fmtDate, fmtInt, fmtMoney, fmtPct } from "../lib/format";
import Sparkline from "./Sparkline";

export default function LeagueStandings({ rows, equityByPortfolio, curvesAvailable }) {
  const series = Object.fromEntries(
    rows.map((row) => [
      row.id,
      curvesAvailable && Array.isArray(equityByPortfolio?.[row.id])
        ? equityByPortfolio[row.id].map((entry) => entry.equity)
        : [],
    ]),
  );

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Portfolio</th>
            <th className="num">Equity</th>
            <th className="num">Return</th>
            <th className="num" title="Context only; not every strategy's registered control">
              vs SPY context
            </th>
            <th className="num">Max DD</th>
            <th className="num">5d</th>
            <th className="num">Open</th>
            <th className="num">Fills</th>
            <th>Equity curve</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const dormant = row.n_open === 0 && row.n_fills === 0;
            return (
              <tr key={row.id} className={dormant ? "dead" : ""}>
                <td className="num">{fmtInt(row.rank)}</td>
                <td>
                  <strong>{row.name}</strong>{" "}
                  {dormant ? <span className="tag dead">dormant</span> : null}
                  {!row.current ? (
                    <>
                      {" "}
                      <span className="tag dead">
                        stale · {fmtDate(row.equity_as_of)}
                      </span>
                    </>
                  ) : null}
                  <div className="faint" style={{ fontSize: 11 }}>
                    {row.id} · since {fmtDate(row.inception)}
                  </div>
                </td>
                <td className="num">{fmtMoney(row.equity)}</td>
                <td className={`num ${row.total_ret >= 0 ? "pos" : "neg"}`}>
                  {fmtPct(row.total_ret)}
                </td>
                <td
                  className={`num ${
                    typeof row.vs_spy === "number"
                      ? row.vs_spy >= 0
                        ? "pos"
                        : "neg"
                      : ""
                  }`}
                >
                  {fmtPct(row.vs_spy)}
                </td>
                <td className="num neg">{fmtPct(row.mdd)}</td>
                <td
                  className={`num ${
                    typeof row.last5 === "number"
                      ? row.last5 >= 0
                        ? "pos"
                        : "neg"
                      : ""
                  }`}
                >
                  {fmtPct(row.last5)}
                </td>
                <td className="num">{fmtInt(row.n_open)}</td>
                <td className="num">{fmtInt(row.n_fills)}</td>
                <td>
                  {curvesAvailable ? (
                    <Sparkline values={series[row.id]} />
                  ) : (
                    <span className="faint">unavailable</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
