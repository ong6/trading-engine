import DashboardLeagueSummary from "./components/DashboardLeagueSummary";
import DashboardProspectiveEvidence from "./components/DashboardProspectiveEvidence";
import DashboardResearchReadiness from "./components/DashboardResearchReadiness";
import DashboardScreen from "./components/DashboardScreen";
import { apiFetch, validateApiResponse } from "./lib/api";
import { isLeagueProjection } from "./lib/league-contracts";
import { isScreenProjection } from "./lib/market-contracts";
import { isResearchReadinessProjection } from "./lib/research-contracts";
import { getMeta } from "./lib/server-api";

export const dynamic = "force-dynamic";

function screenResponse(res, expectedPage) {
  return validateApiResponse(
    res,
    "screen",
    (data) => isScreenProjection(data) && data.results_page === expectedPage,
  );
}

function leagueResponse(res) {
  return validateApiResponse(res, "league", isLeagueProjection);
}

function readinessResponse(res) {
  return validateApiResponse(
    res,
    "research-readiness",
    isResearchReadinessProjection,
  );
}

function requestedPage(searchParams) {
  const requested = /^\d+$/.test(searchParams.screen_page || "")
    ? Number(searchParams.screen_page)
    : 1;
  return Number.isSafeInteger(requested) && requested >= 1
    ? Math.min(requested, 1_000_000)
    : 1;
}

export default async function Dashboard({ searchParams }) {
  const screenPage = requestedPage((await searchParams) || {});
  const [rawScreenRes, rawLeagueRes, rawReadinessRes, metaRes] = await Promise.all([
    apiFetch(`/screen/latest?page=${screenPage}`),
    apiFetch("/league"),
    apiFetch("/research/readiness"),
    getMeta(),
  ]);
  const screenRes = screenResponse(rawScreenRes, screenPage);
  const leagueRes = leagueResponse(rawLeagueRes);
  const readinessRes = readinessResponse(rawReadinessRes);
  const league = leagueRes.ok ? leagueRes.data : null;

  return (
    <div>
      <h1>Dashboard</h1>
      <p className="muted">
        Today&apos;s Minervini-template screen and the paper league at a glance.
      </p>
      <DashboardLeagueSummary res={leagueRes} />
      <DashboardProspectiveEvidence res={metaRes} />
      <DashboardResearchReadiness res={readinessRes} />
      <DashboardScreen res={screenRes} league={league} />
    </div>
  );
}
