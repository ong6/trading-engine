import Link from "next/link";
import { candidateHref } from "../lib/candidate-route";
import { fmtDate, fmtInt, fmtPrice, fmtTime } from "../lib/format";
import GateList from "./GateList";

function gateSummary(gates) {
  if (!Array.isArray(gates)) return "";
  const counts = { pass: 0, fail: 0, unknown: 0 };
  gates.forEach((gate) => {
    const status = (gate.status || "unknown").toLowerCase();
    if (counts[status] != null) counts[status] += 1;
  });
  return `${counts.pass} pass · ${counts.fail} fail · ${counts.unknown} unknown`;
}

function gateErrorMessage(error) {
  if (error === "malformed-json") {
    return "Stored risk-gate results contain malformed JSON.";
  }
  if (error === "not-an-array") {
    return "Stored risk-gate results are not a list.";
  }
  if (error === "invalid-entries") {
    return "Stored risk-gate results contain invalid entries.";
  }
  return null;
}

export default function JournalTickets({ discretionary }) {
  const tickets = discretionary.tickets || [];
  const truncated = discretionary.tickets_truncated === true;

  return (
    <>
      <h2>Discretionary tickets</h2>
      {truncated ? (
        <div className="notice">
          Showing newest {fmtInt(discretionary.tickets_limit)} of{" "}
          {fmtInt(discretionary.tickets_matching_count)} discretionary tickets.
        </div>
      ) : null}
      {tickets.length === 0 ? (
        <div className="empty">No discretionary tickets yet.</div>
      ) : (
        <div className="grid">
          {tickets.map((ticket) => (
            <details
              key={ticket.id}
              className="card"
              open={ticket.status === "rejected"}
            >
              <summary style={{ cursor: "pointer" }}>
                <strong>
                  <Link href={candidateHref(ticket.ticker)}>{ticket.ticker}</Link>
                </strong>{" "}
                {ticket.side} {fmtInt(ticket.qty)} @ ref {fmtPrice(ticket.entry_ref)} · stop{" "}
                {fmtPrice(ticket.stop)} · target {fmtPrice(ticket.target)}{" "}
                <span
                  className={
                    ticket.status === "submitted"
                      ? "pos"
                      : ticket.status === "rejected"
                        ? "neg"
                        : "muted"
                  }
                >
                  [{ticket.status}]
                </span>{" "}
                <span className="faint" style={{ fontSize: 11 }}>
                  {ticket.playbook ? `· ${ticket.playbook} ` : ""}
                  {ticket.emotion ? `· ${ticket.emotion} ` : ""}·{" "}
                  {fmtTime(ticket.created_at)} · {gateSummary(ticket.gates)}
                </span>
              </summary>
              <div style={{ marginTop: 10 }}>
                {gateErrorMessage(ticket.gates_error) ? (
                  <div className="notice error" style={{ marginBottom: 8 }}>
                    {gateErrorMessage(ticket.gates_error)}
                  </div>
                ) : null}
                {ticket.notes ? (
                  <p className="muted" style={{ marginTop: 0 }}>
                    {ticket.notes}
                  </p>
                ) : null}
                <GateList gates={ticket.gates} />
                {Array.isArray(ticket.fills) && ticket.fills.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <span className="faint">Fills: </span>
                    {ticket.fills.map((fill, index) => (
                      <span key={index} className="mono">
                        {fill.side} {fmtInt(fill.qty)} @ {fmtPrice(fill.fill_px)} (
                        {fmtDate(fill.fill_date)})
                        {index < ticket.fills.length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      )}
    </>
  );
}
