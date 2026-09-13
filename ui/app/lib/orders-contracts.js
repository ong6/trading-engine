import {
  isBoundedCollection,
  isIsoDate,
  isNonEmptyString,
  isPositiveInteger,
  isPublicPortfolioId,
  isRecord,
} from "./response-contracts.js";
import { isCandidateTicker } from "./candidate-route.js";

const ORDER_STATUSES = ["pending", "filled", "rejected", "cancelled"];
const ORDERS_LIMIT = 500;
const ORDERS_PROJECTION_KEYS = [
  "limit",
  "matching_count",
  "orders",
  "status",
  "truncated",
];
const ORDER_ROW_KEYS = [
  "id",
  "detail_truncated",
  "playbook",
  "portfolio_id",
  "qty",
  "reject_reason",
  "side",
  "signal_date",
  "status",
  "stop",
  "target",
  "ticker",
  "ticket_id",
];

function hasExactOrderKeys(row) {
  return (
    Object.keys(row).length === ORDER_ROW_KEYS.length &&
    ORDER_ROW_KEYS.every((key) => Object.prototype.hasOwnProperty.call(row, key))
  );
}

function hasExactProjectionKeys(data) {
  return (
    isRecord(data) &&
    Object.keys(data).length === ORDERS_PROJECTION_KEYS.length &&
    ORDERS_PROJECTION_KEYS.every((key) =>
      Object.prototype.hasOwnProperty.call(data, key),
    )
  );
}

function hasClippedOrderText(row) {
  return [
    [row.playbook, 128],
    [row.reject_reason, 4096],
  ].some(
    ([value, limit]) => typeof value === "string" && [...value].length === limit,
  );
}

export function isOrdersProjection(data, requestedStatus = "") {
  if (
    !(requestedStatus === "" || ORDER_STATUSES.includes(requestedStatus)) ||
    !hasExactProjectionKeys(data) ||
    !isBoundedCollection(data, "orders") ||
    data.limit !== ORDERS_LIMIT ||
    data.status !== (requestedStatus || null)
  ) {
    return false;
  }
  const ids = new Set();
  return data.orders.every((row, index, orders) => {
    const terminalWithoutFill = ["rejected", "cancelled"].includes(row?.status);
    const valid =
      isRecord(row) &&
      hasExactOrderKeys(row) &&
      isPositiveInteger(row.id) &&
      !ids.has(row.id) &&
      (index === 0 || row.id < orders[index - 1].id) &&
      isPublicPortfolioId(row.portfolio_id) &&
      isCandidateTicker(row.ticker) &&
      ["buy", "sell"].includes(row.side) &&
      Number.isFinite(row.qty) &&
      row.qty > 0 &&
      isIsoDate(row.signal_date) &&
      ORDER_STATUSES.includes(row.status) &&
      (!requestedStatus || row.status === requestedStatus) &&
      (terminalWithoutFill
        ? isNonEmptyString(row.reject_reason)
        : row.reject_reason === null) &&
      (row.ticket_id == null || isPositiveInteger(row.ticket_id)) &&
      (row.playbook == null ||
        (typeof row.playbook === "string" && [...row.playbook].length <= 128)) &&
      (row.reject_reason == null || [...row.reject_reason].length <= 4096) &&
      typeof row.detail_truncated === "boolean" &&
      (!row.detail_truncated || hasClippedOrderText(row)) &&
      (row.stop == null || (Number.isFinite(row.stop) && row.stop > 0)) &&
      (row.target == null || (Number.isFinite(row.target) && row.target > 0));
    if (valid) ids.add(row.id);
    return valid;
  });
}
