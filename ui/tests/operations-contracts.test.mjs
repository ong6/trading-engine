import assert from "node:assert/strict";
import test from "node:test";

import {
  isJournalProjection,
  isOrdersProjection,
  isPositionsProjection,
} from "../app/lib/operations-contracts.js";

const clone = (value) => structuredClone(value);

test("positions projection enforces filter identity and quote-dependent fields", () => {
  const valid = {
    portfolio: "discretionary",
    limit: 500,
    matching_count: 1,
    truncated: false,
    positions: [
      {
        portfolio_id: "discretionary",
        ticker: "AAA",
        qty: 10,
        avg_cost: 100,
        close: 105,
        market_value: 1050,
        unrealized_pnl: 50,
        unrealized_pnl_pct: 0.05,
        stop: 95,
        dist_to_stop_pct: 10 / 105,
        unrealized_r: 1,
      },
    ],
  };
  assert.equal(isPositionsProjection(valid, "discretionary"), true);
  assert.equal(isPositionsProjection(valid, "another-book"), false);

  const extraEnvelope = clone(valid);
  extraEnvelope.internal = "not public";
  assert.equal(isPositionsProjection(extraEnvelope, "discretionary"), false);

  const extraRow = clone(valid);
  extraRow.positions[0].internal = "not public";
  assert.equal(isPositionsProjection(extraRow, "discretionary"), false);

  const duplicate = clone(valid);
  duplicate.positions.push(clone(duplicate.positions[0]));
  duplicate.matching_count = 2;
  assert.equal(isPositionsProjection(duplicate, "discretionary"), false);

  const unicodeOrder = clone(valid);
  unicodeOrder.portfolio = null;
  unicodeOrder.matching_count = 2;
  unicodeOrder.positions = ["\uF900", "\u{10000}"].map((portfolio_id) => {
    const row = clone(valid.positions[0]);
    row.portfolio_id = portfolio_id;
    delete row.stop;
    delete row.dist_to_stop_pct;
    delete row.unrealized_r;
    return row;
  });
  assert.equal(isPositionsProjection(unicodeOrder), true);
  unicodeOrder.positions.reverse();
  assert.equal(isPositionsProjection(unicodeOrder), false);

  const inventedLimit = clone(valid);
  inventedLimit.limit = 1;
  assert.equal(isPositionsProjection(inventedLimit, "discretionary"), false);

  const malformedPortfolio = clone(valid);
  malformedPortfolio.portfolio = "discretionary\nother";
  malformedPortfolio.positions[0].portfolio_id = "discretionary\nother";
  assert.equal(isPositionsProjection(malformedPortfolio, "discretionary\nother"), false);

  const malformedTicker = clone(valid);
  malformedTicker.positions[0].ticker = "AAA\nBAD";
  assert.equal(isPositionsProjection(malformedTicker, "discretionary"), false);

  const wrongCount = clone(valid);
  wrongCount.matching_count = 2;
  assert.equal(isPositionsProjection(wrongCount, "discretionary"), false);

  const wrongTruncation = clone(valid);
  wrongTruncation.truncated = true;
  assert.equal(isPositionsProjection(wrongTruncation, "discretionary"), false);

  const missingValuation = clone(valid);
  delete missingValuation.positions[0].market_value;
  assert.equal(isPositionsProjection(missingValuation, "discretionary"), false);

  const inconsistentValuation = clone(valid);
  inconsistentValuation.positions[0].market_value = 1049;
  assert.equal(isPositionsProjection(inconsistentValuation, "discretionary"), false);

  const inconsistentReturn = clone(valid);
  inconsistentReturn.positions[0].unrealized_pnl_pct = 0.5;
  assert.equal(isPositionsProjection(inconsistentReturn, "discretionary"), false);

  const inconsistentStopDistance = clone(valid);
  inconsistentStopDistance.positions[0].dist_to_stop_pct = 0.5;
  assert.equal(isPositionsProjection(inconsistentStopDistance, "discretionary"), false);

  const nonpositiveClose = clone(valid);
  nonpositiveClose.positions[0].close = 0;
  assert.equal(isPositionsProjection(nonpositiveClose, "discretionary"), false);

  const zeroAverageCost = clone(valid);
  zeroAverageCost.positions[0].avg_cost = 0;
  assert.equal(isPositionsProjection(zeroAverageCost, "discretionary"), false);

  const nonfiniteQuantity = clone(valid);
  nonfiniteQuantity.positions[0].qty = Number.POSITIVE_INFINITY;
  assert.equal(isPositionsProjection(nonfiniteQuantity, "discretionary"), false);

  const nonpositiveStop = clone(valid);
  nonpositiveStop.positions[0].stop = 0;
  assert.equal(isPositionsProjection(nonpositiveStop, "discretionary"), false);

  const missingQuote = clone(valid);
  missingQuote.positions[0].close = null;
  delete missingQuote.positions[0].market_value;
  delete missingQuote.positions[0].unrealized_pnl;
  delete missingQuote.positions[0].unrealized_pnl_pct;
  delete missingQuote.positions[0].dist_to_stop_pct;
  delete missingQuote.positions[0].unrealized_r;
  assert.equal(isPositionsProjection(missingQuote, "discretionary"), true);

  const nonDiscretionary = clone(valid);
  nonDiscretionary.portfolio = "book-a";
  nonDiscretionary.positions[0].portfolio_id = "book-a";
  delete nonDiscretionary.positions[0].stop;
  delete nonDiscretionary.positions[0].dist_to_stop_pct;
  delete nonDiscretionary.positions[0].unrealized_r;
  assert.equal(isPositionsProjection(nonDiscretionary, "book-a"), true);
  nonDiscretionary.positions[0].stop = 95;
  assert.equal(isPositionsProjection(nonDiscretionary, "book-a"), false);
});

test("orders projection enforces bounded metadata, requested status, and unique rows", () => {
  const order = {
    id: 1,
    portfolio_id: "book-a",
    ticker: "AAA",
    side: "buy",
    qty: 10,
    signal_date: "2026-09-04",
    status: "pending",
    reject_reason: null,
    ticket_id: null,
    playbook: null,
    stop: null,
    target: null,
    detail_truncated: false,
  };
  const valid = {
    status: "pending",
    orders: [order],
    limit: 500,
    matching_count: 1,
    truncated: false,
  };
  assert.equal(isOrdersProjection(valid, "pending"), true);
  assert.equal(isOrdersProjection(valid, "filled"), false);

  const unknownEmptyStatus = {
    status: "unknown",
    orders: [],
    limit: 500,
    matching_count: 0,
    truncated: false,
  };
  assert.equal(isOrdersProjection(unknownEmptyStatus, "unknown"), false);

  const extraEnvelope = clone(valid);
  extraEnvelope.internal = "not public";
  assert.equal(isOrdersProjection(extraEnvelope, "pending"), false);

  for (const field of ["id", "ticket_id"]) {
    const unsafeId = clone(valid);
    unsafeId.orders[0][field] = Number.MAX_SAFE_INTEGER + 1;
    assert.equal(isOrdersProjection(unsafeId, "pending"), false);
  }

  const duplicate = clone(valid);
  duplicate.orders.push(clone(order));
  duplicate.matching_count = 2;
  assert.equal(isOrdersProjection(duplicate, "pending"), false);

  const ordered = clone(valid);
  ordered.matching_count = 2;
  ordered.orders = [{ ...clone(order), id: 2 }, clone(order)];
  assert.equal(isOrdersProjection(ordered, "pending"), true);
  ordered.orders.reverse();
  assert.equal(isOrdersProjection(ordered, "pending"), false);

  const inventedLimit = clone(valid);
  inventedLimit.limit = 1;
  assert.equal(isOrdersProjection(inventedLimit, "pending"), false);

  const malformedDate = clone(valid);
  malformedDate.orders[0].signal_date = "tomorrow";
  assert.equal(isOrdersProjection(malformedDate, "pending"), false);

  const oversizedPortfolio = clone(valid);
  oversizedPortfolio.orders[0].portfolio_id = "x".repeat(129);
  assert.equal(isOrdersProjection(oversizedPortfolio, "pending"), false);

  const malformedTicker = clone(valid);
  malformedTicker.orders[0].ticker = "AAA\tBAD";
  assert.equal(isOrdersProjection(malformedTicker, "pending"), false);

  const unexpectedOrderField = clone(valid);
  unexpectedOrderField.orders[0].internal = "not public";
  assert.equal(isOrdersProjection(unexpectedOrderField, "pending"), false);

  const wrongTruncation = clone(valid);
  wrongTruncation.truncated = true;
  assert.equal(isOrdersProjection(wrongTruncation, "pending"), false);

  const pendingWithReason = clone(valid);
  pendingWithReason.orders[0].reject_reason = "not rejected";
  assert.equal(isOrdersProjection(pendingWithReason, "pending"), false);

  const rejectedWithoutReason = clone(valid);
  rejectedWithoutReason.status = "rejected";
  rejectedWithoutReason.orders[0].status = "rejected";
  assert.equal(isOrdersProjection(rejectedWithoutReason, "rejected"), false);

  const rejected = clone(rejectedWithoutReason);
  rejected.orders[0].reject_reason = "no_bar";
  assert.equal(isOrdersProjection(rejected, "rejected"), true);

  const oversizedReason = clone(rejected);
  oversizedReason.orders[0].reject_reason = "x".repeat(4097);
  assert.equal(isOrdersProjection(oversizedReason, "rejected"), false);

  const clippedReason = clone(rejected);
  clippedReason.orders[0].reject_reason = "x".repeat(4096);
  clippedReason.orders[0].detail_truncated = true;
  assert.equal(isOrdersProjection(clippedReason, "rejected"), true);

  const falseClippingClaim = clone(rejected);
  falseClippingClaim.orders[0].detail_truncated = true;
  assert.equal(isOrdersProjection(falseClippingClaim, "rejected"), false);

  const nonpositiveStop = clone(valid);
  nonpositiveStop.orders[0].stop = 0;
  assert.equal(isOrdersProjection(nonpositiveStop, "pending"), false);

  const nonfiniteQuantity = clone(valid);
  nonfiniteQuantity.orders[0].qty = Number.NaN;
  assert.equal(isOrdersProjection(nonfiniteQuantity, "pending"), false);
});

test("journal projection validates nested gates, fills, round trips, and events", () => {
  const valid = {
    discretionary: {
      tickets: [
        {
          id: 1,
          ticker: "AAA",
          side: "buy",
          qty: 10,
          entry_ref: 100,
          stop: 95,
          target: 110,
          playbook: "breakout",
          emotion: null,
          notes: null,
          detail_truncated: false,
          status: "filled",
          order_id: 11,
          created_at: "2026-09-04T12:00:00",
          gates: [{ name: "position_size", status: "pass", detail: "within cap" }],
          fills: [
            {
              ticker: "AAA",
              side: "buy",
              qty: 10,
              fill_date: "2026-09-04",
              fill_px: 101,
            },
          ],
          fills_limit: 100,
          fills_matching_count: 1,
          fills_truncated: false,
        },
      ],
      tickets_limit: 100,
      tickets_matching_count: 1,
      tickets_truncated: false,
      round_trips: [
        {
          ticker: "BBB",
          qty: 5,
          entry_px: 90,
          exit_px: 95,
          exit_date: "2026-09-04",
          realized_r: 1,
        },
      ],
      round_trips_limit: 100,
      round_trips_matching_count: 1,
      round_trips_truncated: false,
    },
    league_events: [
      {
        order_id: 12,
        portfolio_id: "book-a",
        ticker: "CCC",
        side: "sell",
        qty: 2,
        fill_date: "2026-09-04",
        fill_px: 80,
      },
    ],
    league_events_limit: 100,
    league_events_matching_count: 1,
    league_events_truncated: false,
  };
  assert.equal(isJournalProjection(valid), true);

  const microsecondOrdered = clone(valid);
  microsecondOrdered.discretionary.tickets = [
    {
      ...clone(valid.discretionary.tickets[0]),
      id: 1,
      order_id: 11,
      created_at: "2026-09-04T12:00:00.123999",
    },
    {
      ...clone(valid.discretionary.tickets[0]),
      id: 2,
      order_id: 12,
      created_at: "2026-09-04T12:00:00.123001",
    },
  ];
  microsecondOrdered.discretionary.tickets_matching_count = 2;
  assert.equal(Date.parse(microsecondOrdered.discretionary.tickets[0].created_at),
    Date.parse(microsecondOrdered.discretionary.tickets[1].created_at));
  assert.equal(isJournalProjection(microsecondOrdered), true);
  microsecondOrdered.discretionary.tickets.reverse();
  assert.equal(isJournalProjection(microsecondOrdered), false);

  for (const timestamp of [
    "2026-09-04T12:00:00Z",
    "2026-09-04T12:00:00+00:00",
    "2026-09-04T12:00:00.123",
    "2026-09-04T12:00:00.1234567",
  ]) {
    const noncanonicalTimestamp = clone(valid);
    noncanonicalTimestamp.discretionary.tickets[0].created_at = timestamp;
    assert.equal(isJournalProjection(noncanonicalTimestamp), false);
  }

  const extraTopLevel = clone(valid);
  extraTopLevel.internal = "not public";
  assert.equal(isJournalProjection(extraTopLevel), false);

  const extraDiscretionary = clone(valid);
  extraDiscretionary.discretionary.internal = "not public";
  assert.equal(isJournalProjection(extraDiscretionary), false);

  const extraTicket = clone(valid);
  extraTicket.discretionary.tickets[0].internal = "not public";
  assert.equal(isJournalProjection(extraTicket), false);

  const extraFill = clone(valid);
  extraFill.discretionary.tickets[0].fills[0].internal = "not public";
  assert.equal(isJournalProjection(extraFill), false);

  const extraRoundTrip = clone(valid);
  extraRoundTrip.discretionary.round_trips[0].internal = "not public";
  assert.equal(isJournalProjection(extraRoundTrip), false);

  const extraLeagueEvent = clone(valid);
  extraLeagueEvent.league_events[0].internal = "not public";
  assert.equal(isJournalProjection(extraLeagueEvent), false);

  for (const field of ["id", "order_id"]) {
    const unsafeTicketId = clone(valid);
    unsafeTicketId.discretionary.tickets[0][field] = Number.MAX_SAFE_INTEGER + 1;
    assert.equal(isJournalProjection(unsafeTicketId), false);
  }
  const unsafeEventId = clone(valid);
  unsafeEventId.league_events[0].order_id = Number.MAX_SAFE_INTEGER + 1;
  assert.equal(isJournalProjection(unsafeEventId), false);

  const nonfiniteTicketQuantity = clone(valid);
  nonfiniteTicketQuantity.discretionary.tickets[0].qty = Number.NaN;
  assert.equal(isJournalProjection(nonfiniteTicketQuantity), false);

  const wrongNestedFillTicker = clone(valid);
  wrongNestedFillTicker.discretionary.tickets[0].fills[0].ticker = "BBB";
  assert.equal(isJournalProjection(wrongNestedFillTicker), false);

  const nonpositiveEventPrice = clone(valid);
  nonpositiveEventPrice.league_events[0].fill_px = 0;
  assert.equal(isJournalProjection(nonpositiveEventPrice), false);

  const nonfiniteRoundTrip = clone(valid);
  nonfiniteRoundTrip.discretionary.round_trips[0].realized_r = Number.POSITIVE_INFINITY;
  assert.equal(isJournalProjection(nonfiniteRoundTrip), false);

  const malformedGate = clone(valid);
  malformedGate.discretionary.tickets[0].gates[0].status = "maybe";
  assert.equal(isJournalProjection(malformedGate), false);

  const multilinePortfolio = clone(valid);
  multilinePortfolio.league_events[0].portfolio_id = "book-a\nother";
  assert.equal(isJournalProjection(multilinePortfolio), false);

  const oversizedGateDetail = clone(valid);
  oversizedGateDetail.discretionary.tickets[0].gates[0].detail = "x".repeat(4097);
  assert.equal(isJournalProjection(oversizedGateDetail), false);

  const unicodeGateBounds = clone(valid);
  unicodeGateBounds.discretionary.tickets[0].gates[0].name = "💥".repeat(128);
  unicodeGateBounds.discretionary.tickets[0].gates[0].detail = "💥".repeat(4096);
  assert.equal(isJournalProjection(unicodeGateBounds), true);
  unicodeGateBounds.discretionary.tickets[0].gates[0].name += "💥";
  assert.equal(isJournalProjection(unicodeGateBounds), false);

  const oversizedNotes = clone(valid);
  oversizedNotes.discretionary.tickets[0].notes = "x".repeat(4097);
  assert.equal(isJournalProjection(oversizedNotes), false);

  const clippedNotes = clone(valid);
  clippedNotes.discretionary.tickets[0].notes = "x".repeat(4096);
  clippedNotes.discretionary.tickets[0].detail_truncated = true;
  assert.equal(isJournalProjection(clippedNotes), true);

  const falseTicketClippingClaim = clone(valid);
  falseTicketClippingClaim.discretionary.tickets[0].detail_truncated = true;
  assert.equal(isJournalProjection(falseTicketClippingClaim), false);

  const gateWithInternalField = clone(valid);
  gateWithInternalField.discretionary.tickets[0].gates[0].internal = "not public";
  assert.equal(isJournalProjection(gateWithInternalField), false);

  const excessiveGates = clone(valid);
  excessiveGates.discretionary.tickets[0].gates = Array.from(
    { length: 33 },
    () => ({ name: "gate", status: "pass", detail: "ok" }),
  );
  assert.equal(isJournalProjection(excessiveGates), false);

  const rejectedWithOrder = clone(valid);
  rejectedWithOrder.discretionary.tickets[0].status = "rejected";
  assert.equal(isJournalProjection(rejectedWithOrder), false);

  const filledWithoutOrder = clone(valid);
  filledWithoutOrder.discretionary.tickets[0].order_id = null;
  assert.equal(isJournalProjection(filledWithoutOrder), false);

  const visibleParseFailure = clone(valid);
  visibleParseFailure.discretionary.tickets[0].gates = [];
  visibleParseFailure.discretionary.tickets[0].gates_error = "malformed-json";
  assert.equal(isJournalProjection(visibleParseFailure), true);

  const nonArrayFailure = clone(valid);
  nonArrayFailure.discretionary.tickets[0].gates = [];
  nonArrayFailure.discretionary.tickets[0].gates_error = "not-an-array";
  assert.equal(isJournalProjection(nonArrayFailure), true);

  const invalidEntriesFailure = clone(valid);
  invalidEntriesFailure.discretionary.tickets[0].gates = [];
  invalidEntriesFailure.discretionary.tickets[0].gates_error = "invalid-entries";
  assert.equal(isJournalProjection(invalidEntriesFailure), true);

  const unnecessaryParseFailure = clone(valid);
  unnecessaryParseFailure.discretionary.tickets[0].gates_error = "malformed-json";
  assert.equal(isJournalProjection(unnecessaryParseFailure), false);

  const unknownParseFailure = clone(visibleParseFailure);
  unknownParseFailure.discretionary.tickets[0].gates_error = "parser-detail";
  assert.equal(isJournalProjection(unknownParseFailure), false);

  const leakedRawGate = clone(visibleParseFailure);
  leakedRawGate.discretionary.tickets[0].gates_raw = "not-json";
  assert.equal(isJournalProjection(leakedRawGate), false);

  const leakedParseDetail = clone(visibleParseFailure);
  leakedParseDetail.discretionary.tickets[0].gates_parse_error = "ValueError: secret";
  assert.equal(isJournalProjection(leakedParseDetail), false);

  const malformedFill = clone(valid);
  malformedFill.discretionary.tickets[0].fills[0].qty = 0;
  assert.equal(isJournalProjection(malformedFill), false);

  const mismatchedFill = clone(valid);
  mismatchedFill.discretionary.tickets[0].fills[0].ticker = "BBB";
  assert.equal(isJournalProjection(mismatchedFill), false);

  const nonpositiveFillPrice = clone(valid);
  nonpositiveFillPrice.discretionary.tickets[0].fills[0].fill_px = 0;
  assert.equal(isJournalProjection(nonpositiveFillPrice), false);

  const inconsistentTicketFills = clone(valid);
  inconsistentTicketFills.discretionary.tickets[0].fills_matching_count = 2;
  assert.equal(isJournalProjection(inconsistentTicketFills), false);

  const truncatedTicketFills = clone(valid);
  truncatedTicketFills.discretionary.tickets[0].fills_limit = 1;
  truncatedTicketFills.discretionary.tickets[0].fills_matching_count = 2;
  truncatedTicketFills.discretionary.tickets[0].fills_truncated = true;
  assert.equal(isJournalProjection(truncatedTicketFills), false);

  const malformedRoundTrip = clone(valid);
  malformedRoundTrip.discretionary.round_trips[0].realized_r = null;
  assert.equal(isJournalProjection(malformedRoundTrip), false);

  const inconsistentTickets = clone(valid);
  inconsistentTickets.discretionary.tickets_matching_count = 2;
  assert.equal(isJournalProjection(inconsistentTickets), false);

  const inconsistentRoundTrips = clone(valid);
  inconsistentRoundTrips.discretionary.round_trips_truncated = true;
  assert.equal(isJournalProjection(inconsistentRoundTrips), false);

  const inconsistentEvents = clone(valid);
  inconsistentEvents.league_events_matching_count = 2;
  assert.equal(isJournalProjection(inconsistentEvents), false);
});
