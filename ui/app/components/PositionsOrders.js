import Link from "next/link";
import { candidateHref } from "../lib/candidate-route";
import { fmtDate, fmtInt, fmtPrice } from "../lib/format";
import CancelButton from "./CancelButton";
import FilterSelect from "./FilterSelect";
import StateNotice from "./StateNotice";

const DISC = "discretionary";

export default function PositionsOrders({ ordersRes, orders, status, statusOptions }) {
  const ordersTruncated = ordersRes.ok && ordersRes.data?.truncated === true;
  const orderLimit = Number.isSafeInteger(ordersRes.data?.limit) ? ordersRes.data.limit : null;
  const matchingOrderCount = Number.isSafeInteger(ordersRes.data?.matching_count)
    ? ordersRes.data.matching_count
    : null;

  return (
    <>
      <h2>Orders</h2>
      <div className="filters">
        <FilterSelect
          param="status"
          label="Status"
          options={statusOptions}
          value={status}
        />
      </div>
      {!ordersRes.ok ? (
        <StateNotice res={ordersRes} />
      ) : orders.length === 0 ? (
        <div className="empty">No orders{status ? ` with status ${status}` : ""}.</div>
      ) : (
        <>
          {ordersTruncated ? (
            <div className="notice">
              {orderLimit != null && matchingOrderCount != null
                ? `Showing newest ${fmtInt(orderLimit)} of ${fmtInt(
                    matchingOrderCount,
                  )} matching active-book orders.`
                : "Order history is truncated."}
            </div>
          ) : null}
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
                {orders.map((order) => {
                  const canCancel =
                    order.portfolio_id === DISC &&
                    order.status === "pending" &&
                    order.ticket_id != null;
                  return (
                    <tr key={order.id}>
                      <td className="num">{fmtInt(order.id)}</td>
                      <td>{order.portfolio_id}</td>
                      <td>
                        <Link href={candidateHref(order.ticker)}>{order.ticker}</Link>
                      </td>
                      <td>{order.side}</td>
                      <td className="num">{fmtInt(order.qty)}</td>
                      <td>{fmtDate(order.signal_date)}</td>
                      <td>{order.status}</td>
                      <td>{order.playbook || "—"}</td>
                      <td className="num">{fmtPrice(order.stop)}</td>
                      <td className="num">{fmtPrice(order.target)}</td>
                      <td className="faint">{order.reject_reason || "—"}</td>
                      <td>
                        {canCancel ? <CancelButton ticketId={order.ticket_id} /> : null}
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
