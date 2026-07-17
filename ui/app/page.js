import Link from "next/link";
import { apiFetch } from "./lib/api";
import { fmtPrice, fmtPct, fmtInt, fmtDate, fmtMoney } from "./lib/format";
import RegimeBadge from "./components/RegimeBadge";
import StateNotice from "./components/StateNotice";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const [screenRes, leagueRes] = await Promise.all([
    apiFetch("/screen/latest"),
    apiFetch("/league"),
  ]);

  const screen = screenRes.ok ? screenRes.data : null;
  const league = leagueRes.ok ? leagueRes.data : null;
  const rows = (screen && screen.results) || [];
  const leagueRows = (league && league.rows) || [];

  return (
    <div>
      <h1>Dashboard</h1>
      <p className="muted">
        Today&apos;s Minervini-template screen and the paper league at a glance.
      </p>

      {/* League summary strip */}
      <h2>League summary</h2>
      {!leagueRes.ok ? (
        <StateNotice res={leagueRes} />
      ) : leagueRows.length === 0 ? (
        <div className="empty">No portfolios yet.</div>
      ) : (
        <div className="strip">
          <div className="stat">
            <div className="label">Regime</div>
            <div className="value">
              <RegimeBadge regime={league.regime} />
            </div>
          </div>
          <div className="stat">
            <div className="label">Portfolios</div>
            <div className="value">{fmtInt(leagueRows.length)}</div>
          </div>
          {leagueRows.slice(0, 4).map((r) => (
            <div className="stat" key={r.id}>
              <div className="label">{r.name}</div>
              <div className="value">
                <span className={r.total_ret >= 0 ? "pos" : "neg"}>
                  {fmtPct(r.total_ret)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
      {leagueRows.length > 0 && (
        <p className="faint" style={{ marginTop: 8 }}>
          <Link href="/league">Full league table →</Link>
        </p>
      )}

      {/* Screen */}
      <h2>
        Today&apos;s screen
        {screen ? (
          <span className="faint" style={{ fontWeight: 400 }}>
            {" "}
            · {fmtDate(screen.run_date)} · {fmtInt(screen.n_passing)} passing of{" "}
            {fmtInt(screen.n_total)} · {fmtInt(screen.n_new_today)} new today
          </span>
        ) : null}
      </h2>

      {!screenRes.ok ? (
        <StateNotice res={screenRes} />
      ) : rows.length === 0 ? (
        <div className="empty">No names passed the template today.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="num">Close</th>
                <th className="num">RS</th>
                <th className="num">Template</th>
                <th className="num">Dist 50d</th>
                <th className="num">Dist 200d</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ticker}>
                  <td>
                    <Link href={`/candidates/${r.ticker}`}>
                      <strong>{r.ticker}</strong>
                    </Link>{" "}
                    {r.new_today ? <span className="tag new">new</span> : null}
                  </td>
                  <td className="num">{fmtPrice(r.close)}</td>
                  <td className="num">{fmtInt(r.rs_rank)}</td>
                  <td className="num">
                    {fmtInt(r.template_score)}
                    <span className="faint">/8</span>
                  </td>
                  <td className="num">{fmtPct(r.dist_50d)}</td>
                  <td className="num">{fmtPct(r.dist_200d)}</td>
                  <td>
                    <Link href={`/candidates/${r.ticker}`}>candidate →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {league && (
        <p className="faint" style={{ marginTop: 10 }}>
          Reference notional per paper portfolio:{" "}
          {fmtMoney(league.reference_notional)}
        </p>
      )}
    </div>
  );
}
