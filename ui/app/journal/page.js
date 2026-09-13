import JournalCircuitBreaker from "../components/JournalCircuitBreaker";
import JournalLeagueEvents from "../components/JournalLeagueEvents";
import JournalRoundTrips from "../components/JournalRoundTrips";
import JournalTickets from "../components/JournalTickets";
import StateNotice from "../components/StateNotice";
import { apiFetch, validateApiResponse } from "../lib/api";
import { isJournalProjection } from "../lib/operations-contracts";

export const dynamic = "force-dynamic";

function journalResponse(res) {
  return validateApiResponse(res, "journal", isJournalProjection);
}

export default async function JournalPage() {
  const res = journalResponse(await apiFetch("/journal"));
  if (!res.ok) {
    return (
      <div>
        <h1>Journal</h1>
        <StateNotice res={res} />
      </div>
    );
  }

  const disc = res.data.discretionary || {};
  return (
    <div>
      <h1>Journal</h1>
      <p className="muted">
        Discretionary tickets with their gate results, and closed round-trips
        with realized R.
      </p>

      <JournalCircuitBreaker />
      <JournalTickets discretionary={disc} />
      <JournalRoundTrips discretionary={disc} />
      <JournalLeagueEvents journal={res.data} />
    </div>
  );
}
