import Link from "next/link";
import { candidateHref } from "../lib/candidate-route";
import { fmtDate, fmtInt, fmtPrice, fmtR } from "../lib/format";

export default function JournalRoundTrips({ discretionary }) {
  const roundTrips = discretionary.round_trips || [];
  const truncated = discretionary.round_trips_truncated === true;

  return (
    <>
      <h2>Closed round-trips</h2>
      {truncated ? (
        <div className="notice">
          Showing newest {fmtInt(discretionary.round_trips_limit)} of{" "}
          {fmtInt(discretionary.round_trips_matching_count)} closed round-trips.
        </div>
      ) : null}
      {roundTrips.length === 0 ? (
        <div className="empty">No closed discretionary round-trips yet.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="num">Qty</th>
                <th className="num">Entry</th>
                <th className="num">Exit</th>
                <th>Exit date</th>
                <th className="num">Realized R</th>
              </tr>
            </thead>
            <tbody>
              {roundTrips.map((roundTrip, index) => (
                <tr key={index}>
                  <td>
                    <Link href={candidateHref(roundTrip.ticker)}>
                      {roundTrip.ticker}
                    </Link>
                  </td>
                  <td className="num">{fmtInt(roundTrip.qty)}</td>
                  <td className="num">{fmtPrice(roundTrip.entry_px)}</td>
                  <td className="num">{fmtPrice(roundTrip.exit_px)}</td>
                  <td>{fmtDate(roundTrip.exit_date)}</td>
                  <td
                    className={`num ${
                      typeof roundTrip.realized_r === "number"
                        ? roundTrip.realized_r >= 0
                          ? "pos"
                          : "neg"
                        : ""
                    }`}
                  >
                    {fmtR(roundTrip.realized_r)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
