import { apiFetch } from "../../lib/api";
import {
  fmtPrice,
  fmtPct,
  fmtInt,
  fmtDate,
} from "../../lib/format";
import PriceChart from "../../components/PriceChart";
import TicketForm from "../../components/TicketForm";
import StateNotice from "../../components/StateNotice";

export const dynamic = "force-dynamic";

function Check({ label, ok, value }) {
  const mark = ok === true ? "✓" : ok === false ? "✗" : "·";
  const cls = ok === true ? "pos" : ok === false ? "neg" : "faint";
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "5px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span>
        <span className={cls} style={{ fontFamily: "var(--mono)", marginRight: 8 }}>
          {mark}
        </span>
        {label}
      </span>
      <span className="mono muted">{value}</span>
    </div>
  );
}

export default async function CandidatePage({ params }) {
  const { ticker } = await params;
  const tk = decodeURIComponent(ticker).toUpperCase();
  const res = await apiFetch(`/candidates/${encodeURIComponent(tk)}`);

  if (!res.ok) {
    return (
      <div>
        <h1>{tk}</h1>
        {res.status === 404 ? (
          <div className="empty">No price bars for {tk}.</div>
        ) : (
          <StateNotice res={res} />
        )}
      </div>
    );
  }

  const data = res.data;
  const s = data.screen; // screen_results row or null
  const latestClose = data.latest_close;

  return (
    <div>
      <h1>{tk}</h1>
      <p className="muted">
        Latest close <span className="mono">{fmtPrice(latestClose)}</span> ·{" "}
        {fmtInt(data.n_bars)} bars
        {s ? (
          <>
            {" "}
            · screen {fmtDate(s.run_date)} ·{" "}
            {s.passes_template ? (
              <span className="pos">passes template</span>
            ) : (
              <span className="neg">does not pass</span>
            )}
          </>
        ) : (
          <> · not in the latest screen</>
        )}
      </p>

      <h2>Price</h2>
      <PriceChart bars={data.bars} />

      <div
        className="grid"
        style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", marginTop: 8 }}
      >
        <div>
          <h2>Template checks</h2>
          {!s ? (
            <div className="empty">This ticker is not in the screen table.</div>
          ) : (
            <div className="card">
              <Check
                label="Passes full template"
                ok={!!s.passes_template}
                value={`${fmtInt(s.template_score)}/8`}
              />
              <Check
                label="RS rank ≥ 70"
                ok={typeof s.rs_rank === "number" ? s.rs_rank >= 70 : null}
                value={fmtInt(s.rs_rank)}
              />
              <Check
                label="Above 50d"
                ok={typeof s.dist_50d === "number" ? s.dist_50d >= 0 : null}
                value={fmtPct(s.dist_50d)}
              />
              <Check
                label="Above 200d"
                ok={typeof s.dist_200d === "number" ? s.dist_200d >= 0 : null}
                value={fmtPct(s.dist_200d)}
              />
              <Check
                label="Off 52w low"
                ok={typeof s.off_52w_low === "number" ? s.off_52w_low >= 0.3 : null}
                value={fmtPct(s.off_52w_low)}
              />
              <Check
                label="Near 52w high"
                ok={typeof s.off_52w_high === "number" ? s.off_52w_high >= -0.25 : null}
                value={fmtPct(s.off_52w_high)}
              />
              <Check label="Base tight" ok={s.base_tight ?? null} value={String(s.base_tight)} />
              <Check label="Volume dry-up" ok={s.vol_dryup ?? null} value={String(s.vol_dryup)} />
            </div>
          )}
        </div>

        <div>
          <h2>New ticket</h2>
          <TicketForm ticker={tk} latestClose={latestClose} />
        </div>
      </div>
    </div>
  );
}
