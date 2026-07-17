import Link from "next/link";
import { apiFetch } from "../lib/api";
import {
  fmtPrice,
  fmtPct,
  fmtInt,
  fmtR,
  fmtMoney,
  fmtDate,
} from "../lib/format";
import StateNotice from "../components/StateNotice";
import FilterSelect from "../components/FilterSelect";
import CancelButton from "../components/CancelButton";

export const dynamic = "force-dynamic";

const DISC = "discretionary";
const STATUSES = ["pending", "filled", "rejected", "cancelled"];

export default async function PositionsPage({ searchParams }) {
  const sp = (await searchParams) || {};
  const portfolio = sp.portfolio || "";
  const status = sp.status || "";

  const [posRes, ordRes, leagueRes] = await Promise.all([
    apiFetch(`/positions${portfolio ? `?portfolio=${encodeURIComponent(portfolio)}` : ""}`),
    apiFetch(`/orders${status ? `?status=${encodeURIComponent(status)}` : ""}`),
    apiFetch("/league"),
  ]);

  const positions = (posRes.ok && posRes.data && posRes.data.positions) || [];
  const orders = (ordRes.ok && ordRes.data && ordRes.data.orders) || [];

  // Portfolio filter options from the league (all portfolios), plus discretionary.
  const pfIds = new Set();
  if (leagueRes.ok && leagueRes.data) {
    (leagueRes.data.rows || []).forEach((r) => pfIds.add(r.id));
  }
  positions.forEach((p) => pfIds.add(p.portfolio_id));
  pfIds.add(DISC);
  const pfOptions = [
    { value: "", label: "All portfolios" },
    ...[...pfIds].sort().map((id) => ({ value: id, label: id })),
  ];
  const statusOptions = [
    { value: "", label: "All statuses" },
    ...STATUSES.map((s) => ({ value: s, label: s })),
  ];

  return (
    <div>
      <h1>Positions &amp; Orders</h1>

      <h2>Open positions</h2>
      <div className="filters">
        <FilterSelect
          param="portfolio"
          label="Portfolio"
          options={pfOptions}
          value={portfolio}
        />
      </div>
      {!posRes.ok ? (
        <StateNotice res={posRes} />
      ) : positions.length === 0 ? (
        <div className="empty">No open positions{portfolio ? ` for ${portfolio}` : ""}.</div>
      ) : (
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
              {positions.map((p, i) => {
                const disc = p.portfolio_id === DISC;
                return (
                  <tr key={`${p.portfolio_id}-${p.ticker}-${i}`}>
                    <td>{p.portfolio_id}</td>
                    <td>
                      <Link href={`/candidates/${p.ticker}`}>
                        <strong>{p.ticker}</strong>
                      </Link>
                    </td>
                    <td className="num">{fmtInt(p.qty)}</td>
                    <td className="num">{fmtPrice(p.avg_cost)}</td>
                    <td className="num">{fmtPrice(p.close)}</td>
                    <td className="num">{fmtMoney(p.market_value)}</td>
                    <td
                      className={`num ${
                        typeof p.unrealized_pnl === "number"
                          ? p.unrealized_pnl >= 0
                            ? "pos"
                            : "neg"
                          : ""
                      }`}
                    >
                      {fmtMoney(p.unrealized_pnl)}
                    </td>
                    <td
                      className={`num ${
                        typeof p.unrealized_pnl_pct === "number"
                          ? p.unrealized_pnl_pct >= 0
                            ? "pos"
                            : "neg"
                          : ""
                      }`}
                    >
                      {fmtPct(p.unrealized_pnl_pct)}
                    </td>
                    <td className="num">{disc ? fmtPrice(p.stop) : "—"}</td>
                    <td className="num">{disc ? fmtPct(p.dist_to_stop_pct) : "—"}</td>
                    <td
                      className={`num ${
                        disc && typeof p.unrealized_r === "number"
                          ? p.unrealized_r >= 0
                            ? "pos"
                            : "neg"
                          : ""
                      }`}
                    >
                      {disc ? fmtR(p.unrealized_r) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h2>Orders</h2>
      <div className="filters">
        <FilterSelect
          param="status"
          label="Status"
          options={statusOptions}
          value={status}
        />
      </div>
      {!ordRes.ok ? (
        <StateNotice res={ordRes} />
      ) : orders.length === 0 ? (
        <div className="empty">No orders{status ? ` with status ${status}` : ""}.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Portfolio</th>
                <th>Ticker</th>
                <th>Side</th>
                <th className="num">Qty</th>
                <th>Signal date</th>
                <th>Status</th>
                <th>Playbook</th>
                <th className="num">Stop</th>
                <th className="num">Target</th>
                <th>Reject reason</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => {
                const canCancel =
                  o.portfolio_id === DISC &&
                  o.status === "pending" &&
                  o.ticket_id != null;
                return (
                  <tr key={o.id}>
                    <td className="num">{fmtInt(o.id)}</td>
                    <td>{o.portfolio_id}</td>
                    <td>
                      <Link href={`/candidates/${o.ticker}`}>{o.ticker}</Link>
                    </td>
                    <td>{o.side}</td>
                    <td className="num">{fmtInt(o.qty)}</td>
                    <td>{fmtDate(o.signal_date)}</td>
                    <td>{o.status}</td>
                    <td>{o.playbook || "—"}</td>
                    <td className="num">{fmtPrice(o.stop)}</td>
                    <td className="num">{fmtPrice(o.target)}</td>
                    <td className="faint">{o.reject_reason || "—"}</td>
                    <td>
                      {canCancel ? <CancelButton ticketId={o.ticket_id} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
