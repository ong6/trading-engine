import {
  compareUnicodeCodePoints,
  isBoundedCollection,
  isNullableFiniteNumber,
  isPublicPortfolioId,
  isRecord,
} from "./response-contracts.js";
import { isCandidateTicker } from "./candidate-route.js";

const DISC = "discretionary";
const POSITIONS_LIMIT = 500;
const POSITIONS_PROJECTION_KEYS = [
  "limit",
  "matching_count",
  "portfolio",
  "positions",
  "truncated",
];
const POSITION_BASE_KEYS = ["avg_cost", "close", "portfolio_id", "qty", "ticker"];
const POSITION_VALUATION_KEYS = ["market_value", "unrealized_pnl", "unrealized_pnl_pct"];
const POSITION_RISK_KEYS = ["stop"];
const POSITION_RISK_VALUATION_KEYS = ["dist_to_stop_pct", "unrealized_r"];

function hasExactKeys(value, keys) {
  return (
    isRecord(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function expectedPositionKeys(row) {
  const keys = [...POSITION_BASE_KEYS];
  if (row.close !== null) keys.push(...POSITION_VALUATION_KEYS);
  if (row.portfolio_id === DISC) {
    keys.push(...POSITION_RISK_KEYS);
    if (row.stop !== null && row.close !== null) {
      keys.push(...POSITION_RISK_VALUATION_KEYS);
    }
  }
  return keys;
}

function nearlyEqual(actual, expected) {
  const scale = Math.max(1, Math.abs(actual), Math.abs(expected));
  return Math.abs(actual - expected) <= scale * 1e-12;
}

function comparePositions(left, right) {
  const portfolioOrder = compareUnicodeCodePoints(
    left.portfolio_id,
    right.portfolio_id,
  );
  return portfolioOrder || compareUnicodeCodePoints(left.ticker, right.ticker);
}

export function isPositionsProjection(data, requestedPortfolio = "") {
  if (
    !isRecord(data) ||
    !hasExactKeys(data, POSITIONS_PROJECTION_KEYS) ||
    !isBoundedCollection(data, "positions") ||
    data.limit !== POSITIONS_LIMIT ||
    !(data.portfolio === null || isPublicPortfolioId(data.portfolio)) ||
    data.portfolio !== (requestedPortfolio || null) ||
    !Array.isArray(data.positions)
  ) {
    return false;
  }
  const keys = new Set();
  return data.positions.every((row, index, positions) => {
    if (
      !isRecord(row) ||
      !hasExactKeys(row, expectedPositionKeys(row)) ||
      !isPublicPortfolioId(row.portfolio_id) ||
      !isCandidateTicker(row.ticker) ||
      !Number.isFinite(row.qty) ||
      row.qty <= 0 ||
      !Number.isFinite(row.avg_cost) ||
      row.avg_cost <= 0 ||
      !isNullableFiniteNumber(row.close) ||
      (requestedPortfolio && row.portfolio_id !== requestedPortfolio)
    ) {
      return false;
    }
    if (row.close !== null) {
      if (
        row.close <= 0 ||
        !Number.isFinite(row.market_value) ||
        !Number.isFinite(row.unrealized_pnl) ||
        !Number.isFinite(row.unrealized_pnl_pct) ||
        !nearlyEqual(row.market_value, row.qty * row.close) ||
        !nearlyEqual(row.unrealized_pnl, row.qty * (row.close - row.avg_cost)) ||
        !nearlyEqual(
          row.unrealized_pnl_pct,
          (row.close - row.avg_cost) / row.avg_cost,
        )
      ) {
        return false;
      }
    } else if (
      row.market_value !== undefined ||
      row.unrealized_pnl !== undefined ||
      row.unrealized_pnl_pct !== undefined
    ) {
      return false;
    }
    if (row.portfolio_id === DISC) {
      if (!isNullableFiniteNumber(row.stop) || (row.stop !== null && row.stop <= 0)) {
        return false;
      }
      if (row.stop !== null && row.close !== null) {
        const riskPerShare = row.avg_cost - row.stop;
        if (
          !Number.isFinite(row.dist_to_stop_pct) ||
          !nearlyEqual(row.dist_to_stop_pct, (row.close - row.stop) / row.close) ||
          (riskPerShare === 0
            ? row.unrealized_r !== null
            : !Number.isFinite(row.unrealized_r) ||
              !nearlyEqual(
                row.unrealized_r,
                (row.close - row.avg_cost) / riskPerShare,
              ))
        ) {
          return false;
        }
      } else if (
        row.dist_to_stop_pct !== undefined ||
        row.unrealized_r !== undefined
      ) {
        return false;
      }
    }
    const key = `${row.portfolio_id}\u0000${row.ticker}`;
    if (
      keys.has(key) ||
      (index > 0 && comparePositions(positions[index - 1], row) > 0)
    ) {
      return false;
    }
    keys.add(key);
    return true;
  });
}
