import Link from "next/link";
import { apiFetch } from "../lib/api";
import {
  fmtPrice,
  fmtR,
  fmtInt,
  fmtDate,
  fmtTime,
} from "../lib/format";
import GateList from "../components/GateList";
import StateNotice from "../components/StateNotice";
import ReviewDoneButton from "../components/ReviewDoneButton";

export const dynamic = "force-dynamic";

function gateSummary(gates) {
  if (!Array.isArray(gates)) return "";
  const c = { pass: 0, fail: 0, unknown: 0 };
  gates.forEach((g) => {
    const s = (g.status || "unknown").toLowerCase();
    if (c[s] != null) c[s] += 1;
  });
  return `${c.pass} pass · ${c.fail} fail · ${c.unknown} unknown`;
}

export default async function JournalPage() {
  const res = await apiFetch("/journal");
  if (!res.ok) {
    return (
      <div>
        <h1>Journal</h1>
        <StateNotice res={res} />
      </div>
    );
  }

  const disc = res.data.discretionary || {};
  const tickets = disc.tickets || [];
  const roundTrips = disc.round_trips || [];

  return (
    <div>
      <h1>Journal</h1>
      <p className="muted">
        Discretionary tickets with their gate results, and closed round-trips
        with realized R.
      </p>

      <div className="card" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: "0 0 6px" }}>Circuit breaker</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          After reviewing a losing streak, clear the breaker so new tickets can
          pass the circuit-breaker gate again.
        </p>
        <ReviewDoneButton />
      </div>

      <h2>Discretionary tickets</h2>
      {tickets.length === 0 ? (
        <div className="empty">No discretionary tickets yet.</div>
      ) : (
        <div className="grid">
          {tickets.map((t) => (
            <details key={t.id} className="card" open={t.status === "rejected"}>
              <summary style={{ cursor: "pointer" }}>
                <strong>
                  <Link href={`/candidates/${t.ticker}`}>{t.ticker}</Link>
                </strong>{" "}
                {t.side} {fmtInt(t.qty)} @ ref {fmtPrice(t.entry_ref)} · stop{" "}
                {fmtPrice(t.stop)} · target {fmtPrice(t.target)}{" "}
                <span
                  className={
                    t.status === "submitted"
                      ? "pos"
                      : t.status === "rejected"
                      ? "neg"
                      : "muted"
                  }
                >
                  [{t.status}]
                </span>{" "}
                <span className="faint" style={{ fontSize: 11 }}>
                  {t.playbook ? `· ${t.playbook} ` : ""}
                  {t.emotion ? `· ${t.emotion} ` : ""}· {fmtTime(t.created_at)} ·{" "}
                  {gateSummary(t.gates)}
                </span>
              </summary>
              <div style={{ marginTop: 10 }}>
                {t.notes ? (
                  <p className="muted" style={{ marginTop: 0 }}>
                    {t.notes}
                  </p>
                ) : null}
                <GateList gates={t.gates} />
                {Array.isArray(t.fills) && t.fills.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <span className="faint">Fills: </span>
                    {t.fills.map((f, i) => (
                      <span key={i} className="mono">
                        {f.side} {fmtInt(f.qty)} @ {fmtPrice(f.fill_px)} (
                        {fmtDate(f.fill_date)}){i < t.fills.length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>
      )}

      <h2>Closed round-trips</h2>
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
              {roundTrips.map((r, i) => (
                <tr key={i}>
                  <td>
                    <Link href={`/candidates/${r.ticker}`}>{r.ticker}</Link>
                  </td>
                  <td className="num">{fmtInt(r.qty)}</td>
                  <td className="num">{fmtPrice(r.entry_px)}</td>
                  <td className="num">{fmtPrice(r.exit_px)}</td>
                  <td>{fmtDate(r.exit_date)}</td>
                  <td
                    className={`num ${
                      typeof r.realized_r === "number"
                        ? r.realized_r >= 0
                          ? "pos"
                          : "neg"
                        : ""
                    }`}
                  >
                    {fmtR(r.realized_r)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
