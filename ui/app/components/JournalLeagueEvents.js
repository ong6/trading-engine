import Link from "next/link";
import { candidateHref } from "../lib/candidate-route";
import { fmtDate, fmtInt, fmtPrice } from "../lib/format";

export default function JournalLeagueEvents({ journal }) {
  const leagueEvents = Array.isArray(journal.league_events) ? journal.league_events : [];
  const truncated = journal.league_events_truncated === true;
  const limit = Number.isSafeInteger(journal.league_events_limit)
    ? journal.league_events_limit
    : null;
  const matchingCount = Number.isSafeInteger(journal.league_events_matching_count)
    ? journal.league_events_matching_count
    : null;

  return (
    <>
      <h2>Recent league events</h2>
      <p className="muted">Newest fills from active paper books; this is not a complete archive.</p>
      {truncated ? (
        <div className="notice">
          {limit != null && matchingCount != null
            ? `Showing newest ${fmtInt(limit)} of ${fmtInt(
                matchingCount,
              )} active-book fills.`
            : "League-event history is truncated."}
        </div>
      ) : null}
      {leagueEvents.length === 0 ? (
        <div className="empty">No active-book fills yet.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Portfolio</th>
                <th>Ticker</th>
                <th>Side</th>
                <th className="num">Qty</th>
                <th className="num">Fill</th>
                <th className="num">Order</th>
              </tr>
            </thead>
            <tbody>
              {leagueEvents.map((event, index) => (
                <tr key={`${event.order_id}-${event.fill_date}-${index}`}>
                  <td>{fmtDate(event.fill_date)}</td>
                  <td>{event.portfolio_id}</td>
                  <td>
                    <Link href={candidateHref(event.ticker)}>{event.ticker}</Link>
                  </td>
                  <td>{event.side}</td>
                  <td className="num">{fmtInt(event.qty)}</td>
                  <td className="num">{fmtPrice(event.fill_px)}</td>
                  <td className="num">{fmtInt(event.order_id)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
