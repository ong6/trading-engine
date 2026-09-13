import {
  isBoundedCollection,
  isIsoDate,
  isNullableFiniteNumber,
  isNullableString,
  isPositiveInteger,
  isPublicPortfolioId,
  isRecord,
  isRiskGateResult,
} from "./response-contracts.js";
import { isCandidateTicker } from "./candidate-route.js";

const JOURNAL_PROJECTION_KEYS = [
  "discretionary",
  "league_events",
  "league_events_limit",
  "league_events_matching_count",
  "league_events_truncated",
];
const DISCRETIONARY_KEYS = [
  "tickets",
  "tickets_limit",
  "tickets_matching_count",
  "tickets_truncated",
  "round_trips",
  "round_trips_limit",
  "round_trips_matching_count",
  "round_trips_truncated",
];
const TICKET_KEYS = [
  "id",
  "ticker",
  "side",
  "qty",
  "entry_ref",
  "stop",
  "target",
  "playbook",
  "emotion",
  "notes",
  "detail_truncated",
  "status",
  "order_id",
  "created_at",
  "gates",
  "fills",
  "fills_limit",
  "fills_matching_count",
  "fills_truncated",
];
const GATE_KEYS = ["name", "status", "detail"];
const FILL_KEYS = ["ticker", "side", "qty", "fill_date", "fill_px"];
const ROUND_TRIP_KEYS = [
  "ticker",
  "qty",
  "entry_px",
  "exit_px",
  "exit_date",
  "realized_r",
];
const LEAGUE_EVENT_KEYS = [
  "order_id",
  "portfolio_id",
  "ticker",
  "side",
  "qty",
  "fill_date",
  "fill_px",
];
const JOURNAL_COLLECTION_LIMIT = 100;
const JOURNAL_TICKET_TIMESTAMP =
  /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{6})?$/;

function hasExactKeys(value, keys) {
  return (
    isRecord(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function isJournalTicketTimestamp(value) {
  if (typeof value !== "string") return false;
  const match = JOURNAL_TICKET_TIMESTAMP.exec(value);
  return match !== null && isIsoDate(match[1]);
}

function validFill(fill, ticket) {
  return (
    hasExactKeys(fill, FILL_KEYS) &&
    isCandidateTicker(fill.ticker) &&
    ["buy", "sell"].includes(fill.side) &&
    Number.isFinite(fill.qty) &&
    fill.qty > 0 &&
    isIsoDate(fill.fill_date) &&
    Number.isFinite(fill.fill_px) &&
    fill.fill_px > 0 &&
    fill.ticker === ticket.ticker &&
    fill.side === ticket.side
  );
}

function validJournalGate(gate) {
  return (
    isRiskGateResult(gate) &&
    hasExactKeys(gate, GATE_KEYS) &&
    [...gate.name].length <= 128 &&
    [...gate.detail].length <= 4096
  );
}

function hasClippedTicketText(ticket) {
  return [
    [ticket.playbook, 128],
    [ticket.emotion, 32],
    [ticket.notes, 4096],
  ].some(
    ([value, limit]) => typeof value === "string" && [...value].length === limit,
  );
}

function fillFollows(previous, fill) {
  if (fill.fill_date !== previous.fill_date) {
    return fill.fill_date > previous.fill_date;
  }
  if (fill.qty !== previous.qty) return fill.qty >= previous.qty;
  return fill.fill_px >= previous.fill_px;
}

function validTicket(ticket) {
  if (!isRecord(ticket) || !Array.isArray(ticket.gates)) return false;
  const gateErrorPresent = Object.prototype.hasOwnProperty.call(ticket, "gates_error");
  if (!hasExactKeys(ticket, gateErrorPresent ? [...TICKET_KEYS, "gates_error"] : TICKET_KEYS)) {
    return false;
  }
  const validGates = gateErrorPresent
    ? ticket.gates.length === 0 &&
      ["malformed-json", "not-an-array", "invalid-entries"].includes(
        ticket.gates_error,
      )
    : ticket.gates.length <= 32 && ticket.gates.every(validJournalGate);
  const validOrderLink =
    ticket.status === "rejected"
      ? ticket.order_id === null
      : isPositiveInteger(ticket.order_id);
  return (
    isPositiveInteger(ticket.id) &&
    isCandidateTicker(ticket.ticker) &&
    ["buy", "sell"].includes(ticket.side) &&
    Number.isFinite(ticket.qty) &&
    ticket.qty > 0 &&
    isNullableFiniteNumber(ticket.entry_ref) &&
    isNullableFiniteNumber(ticket.stop) &&
    isNullableFiniteNumber(ticket.target) &&
    isNullableString(ticket.playbook) &&
    (ticket.playbook === null || [...ticket.playbook].length <= 128) &&
    isNullableString(ticket.emotion) &&
    (ticket.emotion === null || [...ticket.emotion].length <= 32) &&
    isNullableString(ticket.notes) &&
    (ticket.notes === null || [...ticket.notes].length <= 4096) &&
    typeof ticket.detail_truncated === "boolean" &&
    (!ticket.detail_truncated || hasClippedTicketText(ticket)) &&
    ["submitted", "rejected", "cancelled", "filled"].includes(ticket.status) &&
    validOrderLink &&
    isJournalTicketTimestamp(ticket.created_at) &&
    validGates &&
    ticket.fills_limit === JOURNAL_COLLECTION_LIMIT &&
    isBoundedCollection(
      ticket,
      "fills",
      "fills_limit",
      "fills_matching_count",
      "fills_truncated",
    ) &&
    ticket.fills.every(
      (fill, index, fills) =>
        validFill(fill, ticket) &&
        (index === 0 || fillFollows(fills[index - 1], fill)),
    )
  );
}

function validRoundTrip(roundTrip) {
  return (
    hasExactKeys(roundTrip, ROUND_TRIP_KEYS) &&
    isCandidateTicker(roundTrip.ticker) &&
    Number.isFinite(roundTrip.qty) &&
    roundTrip.qty > 0 &&
    Number.isFinite(roundTrip.entry_px) &&
    roundTrip.entry_px > 0 &&
    Number.isFinite(roundTrip.exit_px) &&
    roundTrip.exit_px > 0 &&
    isIsoDate(roundTrip.exit_date) &&
    Number.isFinite(roundTrip.realized_r)
  );
}

function validLeagueEvent(event) {
  return (
    hasExactKeys(event, LEAGUE_EVENT_KEYS) &&
    isPositiveInteger(event.order_id) &&
    isPublicPortfolioId(event.portfolio_id) &&
    isCandidateTicker(event.ticker) &&
    ["buy", "sell"].includes(event.side) &&
    Number.isFinite(event.qty) &&
    event.qty > 0 &&
    isIsoDate(event.fill_date) &&
    Number.isFinite(event.fill_px) &&
    event.fill_px > 0
  );
}

export function isJournalProjection(data) {
  const discretionary = data?.discretionary;
  if (
    !hasExactKeys(data, JOURNAL_PROJECTION_KEYS) ||
    !hasExactKeys(discretionary, DISCRETIONARY_KEYS) ||
    discretionary.tickets_limit !== JOURNAL_COLLECTION_LIMIT ||
    discretionary.round_trips_limit !== JOURNAL_COLLECTION_LIMIT ||
    data.league_events_limit !== JOURNAL_COLLECTION_LIMIT ||
    !isBoundedCollection(
      discretionary,
      "tickets",
      "tickets_limit",
      "tickets_matching_count",
      "tickets_truncated",
    ) ||
    !isBoundedCollection(
      discretionary,
      "round_trips",
      "round_trips_limit",
      "round_trips_matching_count",
      "round_trips_truncated",
    ) ||
    !isBoundedCollection(
      data,
      "league_events",
      "league_events_limit",
      "league_events_matching_count",
      "league_events_truncated",
    )
  ) {
    return false;
  }

  const ticketIds = new Set();
  let previousTicket = null;
  const validTickets = discretionary.tickets.every((ticket) => {
    const ordered =
      previousTicket === null ||
      ticket?.created_at < previousTicket.created_at ||
      (ticket?.created_at === previousTicket.created_at &&
        ticket?.id < previousTicket.id);
    const valid = validTicket(ticket) && !ticketIds.has(ticket.id) && ordered;
    if (valid) {
      ticketIds.add(ticket.id);
      previousTicket = ticket;
    }
    return valid;
  });
  const validRoundTrips = discretionary.round_trips.every(
    (roundTrip, index, roundTrips) =>
      validRoundTrip(roundTrip) &&
      (index === 0 || roundTrip.exit_date <= roundTrips[index - 1].exit_date),
  );
  const validEvents = data.league_events.every(
    (event, index, events) =>
      validLeagueEvent(event) &&
      (index === 0 ||
        event.fill_date < events[index - 1].fill_date ||
        (event.fill_date === events[index - 1].fill_date &&
          event.order_id <= events[index - 1].order_id)),
  );
  return Boolean(validTickets && validRoundTrips && validEvents);
}
