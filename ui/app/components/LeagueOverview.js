import { fmtDate, fmtMoney } from "../lib/format";
import RegimeBadge from "./RegimeBadge";
import StateNotice from "./StateNotice";

export default function LeagueOverview({
  league,
  equitiesRes,
  curvesAvailable,
  truncatedCurves,
  staleCount,
}) {
  return (
    <>
      {!curvesAvailable ? (
        <div style={{ marginBottom: 14 }}>
          <StateNotice res={equitiesRes} />
          <p className="faint">Portfolio standings remain available; equity curves are unavailable.</p>
        </div>
      ) : null}
      {truncatedCurves ? (
        <p className="faint">
          {truncatedCurves} equity curve{truncatedCurves === 1 ? " shows" : "s show"} only
          {` the newest ${equitiesRes.data.limit_per_portfolio} observations.`}
        </p>
      ) : null}
      {league.truncated ? (
        <p className="research-fail">
          Showing the first {league.limit} ranked portfolios of {league.matching_count} active
          books with equity history. Ranking was calculated across the complete matching cohort.
        </p>
      ) : null}
      {staleCount ? (
        <p className="research-fail">
          {staleCount} active portfolio{staleCount === 1 ? " is" : "s are"}
          {" behind the operational date and excluded from ranking."}
        </p>
      ) : null}
      <div className="strip" style={{ marginBottom: 14 }}>
        <div className="stat">
          <div className="label">As of</div>
          <div className="value" style={{ fontSize: 14 }}>
            {fmtDate(league.as_of)}
          </div>
        </div>
        <div className="stat">
          <div className="label">Regime</div>
          <div className="value">
            <RegimeBadge regime={league.regime} />
          </div>
        </div>
        <div className="stat">
          <div className="label">Notional</div>
          <div className="value" style={{ fontSize: 14 }}>
            {fmtMoney(league.reference_notional)}
          </div>
        </div>
      </div>
    </>
  );
}
