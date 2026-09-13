import PositionsOpenPositions from "../components/PositionsOpenPositions";
import PositionsOrders from "../components/PositionsOrders";
import { apiFetch, validateApiResponse } from "../lib/api";
import { isOrdersProjection, isPositionsProjection } from "../lib/operations-contracts";
import { isLeagueProjection } from "../lib/league-contracts";
import { compareUnicodeCodePoints } from "../lib/response-contracts";

export const dynamic = "force-dynamic";

const DISC = "discretionary";
const STATUSES = ["pending", "filled", "rejected", "cancelled"];

function positionsResponse(res, requestedPortfolio) {
  return validateApiResponse(res, "positions", (data) =>
    isPositionsProjection(data, requestedPortfolio),
  );
}

function ordersResponse(res, requestedStatus) {
  return validateApiResponse(res, "orders", (data) =>
    isOrdersProjection(data, requestedStatus),
  );
}

function leagueResponse(res) {
  return validateApiResponse(res, "league", isLeagueProjection);
}

export default async function PositionsPage({ searchParams }) {
  const sp = (await searchParams) || {};
  const portfolio = sp.portfolio || "";
  const status = sp.status || "";

  const [rawPosRes, rawOrdRes, rawLeagueRes] = await Promise.all([
    apiFetch(`/positions${portfolio ? `?portfolio=${encodeURIComponent(portfolio)}` : ""}`),
    apiFetch(`/orders${status ? `?status=${encodeURIComponent(status)}` : ""}`),
    apiFetch("/league"),
  ]);
  const posRes = positionsResponse(rawPosRes, portfolio);
  const ordRes = ordersResponse(rawOrdRes, status);
  const leagueRes = leagueResponse(rawLeagueRes);

  const positions = posRes.ok ? posRes.data.positions : [];
  const orders = ordRes.ok ? ordRes.data.orders : [];

  // Portfolio filter options from the active league, plus discretionary.
  const pfIds = new Set();
  if (leagueRes.ok && leagueRes.data) {
    (leagueRes.data.rows || []).forEach((r) => pfIds.add(r.id));
  }
  positions.forEach((p) => pfIds.add(p.portfolio_id));
  pfIds.add(DISC);
  const pfOptions = [
    { value: "", label: "All portfolios" },
    ...[...pfIds]
      .sort(compareUnicodeCodePoints)
      .map((id) => ({ value: id, label: id })),
  ];
  const statusOptions = [
    { value: "", label: "All statuses" },
    ...STATUSES.map((s) => ({ value: s, label: s })),
  ];

  return (
    <div>
      <h1>Positions &amp; Orders</h1>
      <PositionsOpenPositions
        leagueRes={leagueRes}
        positionsRes={posRes}
        positions={positions}
        portfolio={portfolio}
        portfolioOptions={pfOptions}
      />
      <PositionsOrders
        ordersRes={ordRes}
        orders={orders}
        status={status}
        statusOptions={statusOptions}
      />
    </div>
  );
}
