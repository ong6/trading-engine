import CandidateSummary from "../../components/CandidateSummary";
import CandidateTemplateChecks from "../../components/CandidateTemplateChecks";
import CandidateTicketPanel from "../../components/CandidateTicketPanel";
import PriceChart from "../../components/PriceChart";
import StateNotice from "../../components/StateNotice";
import { apiFetch, validateApiResponse } from "../../lib/api";
import { decodeCandidateSegment } from "../../lib/candidate-route";
import { isCandidateProjection } from "../../lib/market-contracts";
import { isTicketContextProjection } from "../../lib/mutation-contracts";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

function candidateResponse(res, expectedTicker) {
  return validateApiResponse(res, "candidate", (data) =>
    isCandidateProjection(data, expectedTicker),
  );
}

function ticketContextResponse(res) {
  return validateApiResponse(res, "ticket-context", isTicketContextProjection);
}

export default async function CandidatePage({ params }) {
  const { ticker } = await params;
  const tk = decodeCandidateSegment(ticker);
  if (tk === null) notFound();
  const [rawRes, rawContextRes] = await Promise.all([
    apiFetch(`/candidates/${encodeURIComponent(tk)}`),
    apiFetch("/tickets/context"),
  ]);
  const res = candidateResponse(rawRes, tk);
  const contextRes = ticketContextResponse(rawContextRes);

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
  const screen = data.screen;
  const latestClose = data.latest_close;

  return (
    <div>
      <h1>{tk}</h1>
      <CandidateSummary data={data} />

      <h2>Price</h2>
      <PriceChart bars={data.bars} />

      <div
        className="grid"
        style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", marginTop: 8 }}
      >
        <CandidateTemplateChecks screen={screen} />
        <CandidateTicketPanel
          ticker={tk}
          latestClose={latestClose}
          latestCloseDate={data.latest_close_date}
          contextRes={contextRes}
        />
      </div>
    </div>
  );
}
