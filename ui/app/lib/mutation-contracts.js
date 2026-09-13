// Pure contracts and calculations shared by client-side mutation controls.

import {
  isIsoDate,
  isIsoTimestamp,
  isNonEmptyString,
  isPositiveInteger,
  isRecord,
  isRiskGateResult,
} from "./response-contracts.js";

const EQUITY_SOURCES = {
  active: "current_discretionary_equity",
  "not-created": "configured_initial_cash",
};
const TICKET_CONTEXT_KEYS = [
  "portfolio_id",
  "status",
  "as_of",
  "equity",
  "equity_source",
  "risk_pct",
  "experiment_max_pct",
  "max_open_r",
];
const TICKET_MUTATION_KEYS = [
  "ticket_id",
  "allowed",
  "status",
  "order_id",
  "signal_date",
  "gates",
  "reasons",
];
const TICKET_CANCELLATION_KEYS = ["ticket_id", "order_id", "status"];
const REVIEW_COMPLETION_KEYS = ["ok", "kind", "ts", "detail"];
const RISK_GATE_KEYS = ["name", "status", "detail"];
const MAX_PUBLIC_GATES = 32;
const MAX_GATE_NAME_CHARS = 128;
const MAX_GATE_DETAIL_CHARS = 4096;
const MAX_PUBLIC_REASONS = 32;
const MAX_REASON_CHARS = MAX_GATE_NAME_CHARS + " unacknowledged: ".length + MAX_GATE_DETAIL_CHARS;

function hasExactKeys(value, keys) {
  return (
    isRecord(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

export function isTicketMutationProjection(data) {
  if (
    !hasExactKeys(data, TICKET_MUTATION_KEYS) ||
    !isPositiveInteger(data.ticket_id) ||
    typeof data.allowed !== "boolean" ||
    !isIsoDate(data.signal_date) ||
    !Array.isArray(data.gates) ||
    data.gates.length === 0 ||
    data.gates.length > MAX_PUBLIC_GATES ||
    !data.gates.every(
      (gate) =>
        isRiskGateResult(gate) &&
        hasExactKeys(gate, RISK_GATE_KEYS) &&
        [...gate.name].length <= MAX_GATE_NAME_CHARS &&
        [...gate.detail].length <= MAX_GATE_DETAIL_CHARS,
    ) ||
    !Array.isArray(data.reasons) ||
    data.reasons.length > MAX_PUBLIC_REASONS ||
    !data.reasons.every(
      (reason) =>
        isNonEmptyString(reason) && [...reason].length <= MAX_REASON_CHARS,
    )
  ) {
    return false;
  }
  return data.allowed
    ? data.status === "submitted" &&
        isPositiveInteger(data.order_id) &&
        data.reasons.length === 0
    : data.status === "rejected" &&
        data.order_id === null &&
        data.reasons.length > 0;
}

export function isTicketCancellationProjection(data, ticketId) {
  return (
    hasExactKeys(data, TICKET_CANCELLATION_KEYS) &&
    isPositiveInteger(ticketId) &&
    data.ticket_id === ticketId &&
    isPositiveInteger(data.ticket_id) &&
    isPositiveInteger(data.order_id) &&
    data.status === "cancelled"
  );
}

export function isReviewCompletionProjection(data) {
  return (
    hasExactKeys(data, REVIEW_COMPLETION_KEYS) &&
    data.ok === true &&
    data.kind === "circuit_breaker" &&
    isIsoTimestamp(data.ts) &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(data.ts) &&
    isNonEmptyString(data.detail)
  );
}

export function isTicketContextProjection(data) {
  if (
    !hasExactKeys(data, TICKET_CONTEXT_KEYS) ||
    data.portfolio_id !== "discretionary" ||
    !["active", "not-created", "inactive", "unavailable"].includes(data.status) ||
    !Number.isFinite(data.risk_pct) ||
    data.risk_pct <= 0 ||
    data.risk_pct > 1 ||
    !Number.isFinite(data.experiment_max_pct) ||
    data.experiment_max_pct <= 0 ||
    data.experiment_max_pct > data.risk_pct ||
    !Number.isFinite(data.max_open_r) ||
    data.max_open_r <= 0
  ) {
    return false;
  }
  if (data.status === "active" || data.status === "not-created") {
    const expectedSource = EQUITY_SOURCES[data.status];
    return (
      isIsoDate(data.as_of) &&
      Number.isFinite(data.equity) &&
      data.equity > 0 &&
      data.equity_source === expectedSource
    );
  }
  return (
    data.equity === null &&
    data.equity_source === null &&
    (data.status === "inactive" ? isIsoDate(data.as_of) : data.as_of === null)
  );
}

export function isSizingContext(context, latestCloseDate) {
  const expectedSource = EQUITY_SOURCES[context?.status];
  return Boolean(
    expectedSource &&
      context.portfolio_id === "discretionary" &&
      context.equity_source === expectedSource &&
      isIsoDate(context.as_of) &&
      context.as_of === latestCloseDate &&
      Number.isFinite(context.equity) &&
      context.equity > 0 &&
      Number.isFinite(context.risk_pct) &&
      context.risk_pct > 0 &&
      context.risk_pct <= 1
  );
}

export function suggestedTicketQty(entry, stop, equity, riskPct) {
  const entryNumber = parseFloat(entry);
  const stopNumber = parseFloat(stop);
  if (
    !Number.isFinite(entryNumber) ||
    !Number.isFinite(stopNumber) ||
    entryNumber <= stopNumber ||
    !Number.isFinite(equity) ||
    equity <= 0 ||
    !Number.isFinite(riskPct) ||
    riskPct <= 0 ||
    riskPct > 1
  ) {
    return null;
  }
  return Math.floor((riskPct * equity) / (entryNumber - stopNumber));
}
