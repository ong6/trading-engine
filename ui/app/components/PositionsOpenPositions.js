import Link from "next/link";
import { candidateHref } from "../lib/candidate-route";
import {
  fmtInt,
  fmtMoney,
  fmtPct,
  fmtPrice,
  fmtR,
} from "../lib/format";
import FilterSelect from "./FilterSelect";
import StateNotice from "./StateNotice";

const DISC = "discretionary";

export default function PositionsOpenPositions({
  leagueRes,
  positionsRes,
  positions,
  portfolio,
  portfolioOptions,
}) {
  const positionsTruncated = positionsRes.ok && positionsRes.data?.truncated === true;
  const positionLimit = Number.isSafeInteger(positionsRes.data?.limit)
    ? positionsRes.data.limit
    : null;
  const matchingPositionCount = Number.isSafeInteger(positionsRes.data?.matching_count)
    ? positionsRes.data.matching_count
    : null;

  return (
    <>
      <h2>Open positions</h2>
      {!leagueRes.ok ? <StateNotice res={leagueRes} /> : null}
      <div className="filters">
        <FilterSelect
          param="portfolio"
          label="Portfolio"
          options={portfolioOptions}
          value={portfolio}
        />
      </div>
      {!positionsRes.ok ? (
        <StateNotice res={positionsRes} />
      ) : positions.length === 0 ? (
        <div className="empty">No open positions{portfolio ? ` for ${portfolio}` : ""}.</div>
      ) : (
        <>
          {positionsTruncated ? (
            <div className="notice">
              {positionLimit != null && matchingPositionCount != null
                ? `Showing first ${fmtInt(positionLimit)} of ${fmtInt(
                    matchingPositionCount,
                  )} matching active-book positions, ordered by portfolio and ticker.`
                : "Open positions are truncated."}
            </div>
          ) : null}
          <div className="table-wrap">
            <table>
            <thead>
              <tr>
                <th>Portfolio</th>
                <th>Ticker</th>
                <th className="num">Qty</th>
                <th className="num">Avg cost</th>
                <th className="num">Close</th>
                <th className="num">Mkt value</th>
                <th className="num">Unrealized</th>
                <th className="num">%</th>
                <th className="num">Stop</th>
                <th className="num">Dist to stop</th>
                <th className="num">Unreal R</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position, index) => {
                const discretionary = position.portfolio_id === DISC;
                return (
                  <tr key={`${position.portfolio_id}-${position.ticker}-${index}`}>
                    <td>{position.portfolio_id}</td>
                    <td>
                      <Link href={candidateHref(position.ticker)}>
                        <strong>{position.ticker}</strong>
                      </Link>
                    </td>
                    <td className="num">{fmtInt(position.qty)}</td>
                    <td className="num">{fmtPrice(position.avg_cost)}</td>
                    <td className="num">{fmtPrice(position.close)}</td>
                    <td className="num">{fmtMoney(position.market_value)}</td>
                    <td
                      className={`num ${
                        typeof position.unrealized_pnl === "number"
                          ? position.unrealized_pnl >= 0
                            ? "pos"
                            : "neg"
                          : ""
                      }`}
                    >
                      {fmtMoney(position.unrealized_pnl)}
                    </td>
                    <td
                      className={`num ${
                        typeof position.unrealized_pnl_pct === "number"
                          ? position.unrealized_pnl_pct >= 0
                            ? "pos"
                            : "neg"
                          : ""
                      }`}
                    >
                      {fmtPct(position.unrealized_pnl_pct)}
                    </td>
                    <td className="num">
                      {discretionary ? fmtPrice(position.stop) : "—"}
                    </td>
                    <td className="num">
                      {discretionary ? fmtPct(position.dist_to_stop_pct) : "—"}
                    </td>
                    <td
                      className={`num ${
                        discretionary && typeof position.unrealized_r === "number"
                          ? position.unrealized_r >= 0
                            ? "pos"
                            : "neg"
                          : ""
                      }`}
                    >
                      {discretionary ? fmtR(position.unrealized_r) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
