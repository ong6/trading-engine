import LeagueOverview from "../components/LeagueOverview";
import LeagueStandings from "../components/LeagueStandings";
import StateNotice from "../components/StateNotice";
import { apiFetch, validateApiResponse } from "../lib/api";
import {
  isBulkEquityProjection,
  isLeagueProjection,
} from "../lib/league-contracts";

export const dynamic = "force-dynamic";

function leagueResponse(res) {
  return validateApiResponse(res, "league", isLeagueProjection);
}

function equitiesResponse(res, league) {
  return validateApiResponse(res, "bulk-equity", (data) =>
    isBulkEquityProjection(data, league),
  );
}

export default async function LeaguePage() {
  const [rawLeagueRes, rawEquitiesRes] = await Promise.all([
    apiFetch("/league"),
    apiFetch("/league/equities"),
  ]);
  const leagueRes = leagueResponse(rawLeagueRes);
  const league = leagueRes.ok ? leagueRes.data : null;
  const rows = leagueRes.ok ? league.rows : [];
  const equitiesRes = equitiesResponse(rawEquitiesRes, league);
  const equityByPortfolio = equitiesRes.data?.equity_by_portfolio;
  const curvesAvailable = equitiesRes.ok;
  const truncatedCurves = curvesAvailable
    ? Object.values(equitiesRes.data.truncated_by_portfolio).filter(Boolean).length
    : 0;
  const staleCount = rows.filter((row) => row.current === false).length;

  return (
    <div>
      <h1>League</h1>
      <p className="muted">
        Active paper portfolios with equity history, ordered by raw return since each book&apos;s
        own inception. Retired books remain in historical reports rather than this live table.
      </p>
      {league?.notice ? <p className="research-fail">{league.notice}</p> : null}

      {!leagueRes.ok ? (
        <StateNotice res={leagueRes} />
      ) : rows.length === 0 ? (
        <div className="empty">No portfolios have equity history yet.</div>
      ) : (
        <>
          <LeagueOverview
            league={league}
            equitiesRes={equitiesRes}
            curvesAvailable={curvesAvailable}
            truncatedCurves={truncatedCurves}
            staleCount={staleCount}
          />
          <LeagueStandings
            rows={rows}
            equityByPortfolio={equityByPortfolio}
            curvesAvailable={curvesAvailable}
          />
        </>
      )}
    </div>
  );
}
