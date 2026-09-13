import {
  compareUnicodeCodePoints,
  isIsoDate,
  isNonnegativeInteger,
  isPositiveInteger,
  isPublicPortfolioId,
} from "./response-contracts.js";
import { isCandidateTicker } from "./candidate-route.js";
import { hasExactFields } from "./meta-contract-utils.js";

const STALE_DETAIL_LIMIT = 100;
const STALE_EXPOSURE_FIELDS = [
  "as_of",
  "ticker_count",
  "position_count",
  "pending_order_count",
  "positions",
  "positions_limit",
  "positions_truncated",
  "pending_orders",
  "pending_orders_limit",
  "pending_orders_truncated",
];
const POSITION_FIELDS = ["portfolio_id", "ticker", "qty", "last_traded"];
const PENDING_ORDER_FIELDS = [
  "id",
  "portfolio_id",
  "ticker",
  "side",
  "qty",
  "signal_date",
  "last_traded",
];

function compareStaleRows(left, right, withId) {
  const leftDate = left.last_traded || "";
  const rightDate = right.last_traded || "";
  if (leftDate !== rightDate) return leftDate < rightDate ? -1 : 1;
  if (left.portfolio_id !== right.portfolio_id) {
    return compareUnicodeCodePoints(left.portfolio_id, right.portfolio_id);
  }
  if (withId && left.id !== right.id) return left.id < right.id ? -1 : 1;
  return compareUnicodeCodePoints(left.ticker, right.ticker);
}

function isOrderedUnique(rows, identity, withId) {
  const identities = new Set();
  return rows.every((row, index) => {
    const key = identity(row);
    if (identities.has(key)) return false;
    identities.add(key);
    return index === 0 || compareStaleRows(rows[index - 1], row, withId) <= 0;
  });
}

export function isMetaExposure(data) {
  const exposure = data.stale_exposure;
  if (
    !hasExactFields(exposure, STALE_EXPOSURE_FIELDS) ||
    !(exposure.as_of === null || isIsoDate(exposure.as_of)) ||
    !Array.isArray(exposure.positions) ||
    !Array.isArray(exposure.pending_orders) ||
    exposure.positions_limit !== STALE_DETAIL_LIMIT ||
    exposure.pending_orders_limit !== STALE_DETAIL_LIMIT ||
    typeof exposure.positions_truncated !== "boolean" ||
    typeof exposure.pending_orders_truncated !== "boolean" ||
    !exposure.positions.every(
      (row) =>
        hasExactFields(row, POSITION_FIELDS) &&
        isPublicPortfolioId(row.portfolio_id) &&
        isCandidateTicker(row.ticker) &&
        Number.isFinite(row.qty) &&
        row.qty > 0 &&
        (row.last_traded === null ||
          (isIsoDate(row.last_traded) &&
            exposure.as_of !== null &&
            row.last_traded < exposure.as_of)),
    ) ||
    !exposure.pending_orders.every(
      (row) =>
        hasExactFields(row, PENDING_ORDER_FIELDS) &&
        isPositiveInteger(row.id) &&
        isPublicPortfolioId(row.portfolio_id) &&
        isCandidateTicker(row.ticker) &&
        ["buy", "sell"].includes(row.side) &&
        Number.isFinite(row.qty) &&
        row.qty > 0 &&
        isIsoDate(row.signal_date) &&
        exposure.as_of !== null &&
        row.signal_date <= exposure.as_of &&
        (row.last_traded === null ||
          (isIsoDate(row.last_traded) &&
            exposure.as_of !== null &&
            row.last_traded < exposure.as_of)),
    )
  ) {
    return false;
  }
  const tickers = new Set(
    [...exposure.positions, ...exposure.pending_orders].map((row) => row.ticker),
  );
  return (
    isNonnegativeInteger(exposure.ticker_count) &&
    isNonnegativeInteger(exposure.position_count) &&
    isNonnegativeInteger(exposure.pending_order_count) &&
    exposure.positions.length ===
      Math.min(exposure.position_count, exposure.positions_limit) &&
    exposure.pending_orders.length ===
      Math.min(exposure.pending_order_count, exposure.pending_orders_limit) &&
    exposure.positions_truncated ===
      (exposure.position_count > exposure.positions.length) &&
    exposure.pending_orders_truncated ===
      (exposure.pending_order_count > exposure.pending_orders.length) &&
    isOrderedUnique(
      exposure.positions,
      (row) => `${row.portfolio_id}\u0000${row.ticker}`,
      false,
    ) &&
    isOrderedUnique(exposure.pending_orders, (row) => row.id, true) &&
    exposure.ticker_count >= tickers.size &&
    exposure.ticker_count <= exposure.position_count + exposure.pending_order_count &&
    (exposure.positions_truncated || exposure.pending_orders_truncated ||
      exposure.ticker_count === tickers.size) &&
    (exposure.as_of !== null ||
      (exposure.ticker_count === 0 &&
        exposure.position_count === 0 &&
        exposure.pending_order_count === 0))
  );
}
