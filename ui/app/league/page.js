import { apiFetch } from "../lib/api";
import { fmtPrice, fmtPct, fmtInt, fmtDate, fmtMoney } from "../lib/format";
import RegimeBadge from "../components/RegimeBadge";
import StateNotice from "../components/StateNotice";
import Sparkline from "../components/Sparkline";

export const dynamic = "force-dynamic";

export default async function LeaguePage() {
  const leagueRes = await apiFetch("/league");
  const league = leagueRes.ok ? leagueRes.data : null;
  const rows = (league && league.rows) || [];

  // Pull each portfolio's equity series in parallel for the sparklines.
  const series = {};
  if (rows.length) {
    const eqResults = await Promise.all(
      rows.map((r) => apiFetch(`/league/${encodeURIComponent(r.id)}/equity`))
    );
    rows.forEach((r, i) => {
      const er = eqResults[i];
      series[r.id] =
        er.ok && er.data && Array.isArray(er.data.equity)
          ? er.data.equity.map((e) => e.equity)
          : [];
    });
  }

  return (
    <div>
      <h1>League</h1>
      <p className="muted">
        Every paper portfolio — live and tombstoned. Ranked by total return.
      </p>

      {!leagueRes.ok ? (
        <StateNotice res={leagueRes} />
      ) : rows.length === 0 ? (
        <div className="empty">No portfolios have equity history yet.</div>
      ) : (
        <>
          <div className="strip" style={{ marginBottom: 14 }}>
            <div className="stat">
              <div className="label">As of</div>
              <div className="value" style={{ fontSize: 14 }}>
                {fmtDate(league.as_of)}
              </div>
            </div>
            <div className="stat">
              <div className="label">Regime</div>
              <div className="value">
                <RegimeBadge regime={league.regime} />
              </div>
            </div>
            <div className="stat">
              <div className="label">Notional</div>
              <div className="value" style={{ fontSize: 14 }}>
                {fmtMoney(league.reference_notional)}
              </div>
            </div>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Portfolio</th>
                  <th className="num">Equity</th>
                  <th className="num">Return</th>
                  <th className="num">vs SPY</th>
                  <th className="num">Max DD</th>
                  <th className="num">5d</th>
                  <th className="num">Open</th>
                  <th className="num">Fills</th>
                  <th>Equity curve</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const dead = r.n_open === 0 && r.n_fills === 0;
                  return (
                    <tr key={r.id} className={dead ? "dead" : ""}>
                      <td className="num">{fmtInt(r.rank)}</td>
                      <td>
                        <strong>{r.name}</strong>{" "}
                        {dead ? <span className="tag dead">dormant</span> : null}
                        <div className="faint" style={{ fontSize: 11 }}>
                          {r.id} · since {fmtDate(r.inception)}
                        </div>
                      </td>
                      <td className="num">{fmtMoney(r.equity)}</td>
                      <td className={`num ${r.total_ret >= 0 ? "pos" : "neg"}`}>
                        {fmtPct(r.total_ret)}
                      </td>
                      <td
                        className={`num ${
                          typeof r.vs_spy === "number"
                            ? r.vs_spy >= 0
                              ? "pos"
                              : "neg"
                            : ""
                        }`}
                      >
                        {fmtPct(r.vs_spy)}
                      </td>
                      <td className="num neg">{fmtPct(r.mdd)}</td>
                      <td
                        className={`num ${
                          typeof r.last5 === "number"
                            ? r.last5 >= 0
                              ? "pos"
                              : "neg"
                            : ""
                        }`}
                      >
                        {fmtPct(r.last5)}
                      </td>
                      <td className="num">{fmtInt(r.n_open)}</td>
                      <td className="num">{fmtInt(r.n_fills)}</td>
                      <td>
                        <Sparkline values={series[r.id]} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
