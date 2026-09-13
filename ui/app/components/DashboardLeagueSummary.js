import Link from "next/link";
import { fmtInt, fmtPct } from "../lib/format";
import RegimeBadge from "./RegimeBadge";
import StateNotice from "./StateNotice";

export default function DashboardLeagueSummary({ res }) {
  const league = res.ok ? res.data : null;
  const rows = (league && league.rows) || [];
  const currentLeagueRows = rows.filter((row) => row.current !== false);
  const staleCount = rows.length - currentLeagueRows.length;

  return (
    <>
      <h2>Operational league summary</h2>
      {!res.ok ? (
        <StateNotice res={res} />
      ) : currentLeagueRows.length === 0 ? (
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
            <div className="label">Current portfolios</div>
            <div className="value">{fmtInt(currentLeagueRows.length)}</div>
          </div>
          {currentLeagueRows.slice(0, 4).map((row) => (
            <div className="stat" key={row.id}>
              <div className="label">{row.name}</div>
              <div className="value">
                <span className={row.total_ret >= 0 ? "pos" : "neg"}>
                  {fmtPct(row.total_ret)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
      {staleCount > 0 ? (
        <p className="research-fail" style={{ marginTop: 8 }}>
          {staleCount} active portfolio{staleCount === 1 ? " is" : "s are"}
          {" behind the operational date and excluded from this summary."}
        </p>
      ) : null}
      {league?.truncated ? (
        <p className="research-fail" style={{ marginTop: 8 }}>
          Showing {rows.length} of {league.matching_count} ranked portfolios; open the League page
          for the bounded operational table.
        </p>
      ) : null}
      {rows.length > 0 && (
        <>
          <p className="faint" style={{ marginTop: 8 }}>
            Raw return since each book&apos;s own inception; this ordering is not comparable
            research evidence or a promotion signal.
          </p>
          <p className="faint" style={{ marginTop: 8 }}>
            <Link href="/league">Full operational league table →</Link>
          </p>
        </>
      )}
    </>
  );
}
