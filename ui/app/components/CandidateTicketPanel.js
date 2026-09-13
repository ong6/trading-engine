import StateNotice from "./StateNotice";
import TicketForm from "./TicketForm";

export default function CandidateTicketPanel({
  ticker,
  latestClose,
  latestCloseDate,
  contextRes,
}) {
  return (
    <div>
      <h2>New ticket</h2>
      {!contextRes.ok ? <StateNotice res={contextRes} /> : null}
      <TicketForm
        ticker={ticker}
        latestClose={latestClose}
        latestCloseDate={latestCloseDate}
        contextRes={contextRes}
      />
    </div>
  );
}
