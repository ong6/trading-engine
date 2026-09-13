// Pure contracts for operational league and equity-series responses.

import {
  compareUnicodeCodePoints,
  isIsoDate,
  isNonEmptyString,
  isNonnegativeInteger,
  isNullableFiniteNumber,
  isPositiveInteger,
  isPublicPortfolioId,
  isRecord,
} from "./response-contracts.js";

const LEAGUE_ROWS_LIMIT = 100;
const EQUITY_SERIES_LIMIT = 500;

const LEAGUE_PROJECTION_KEYS = [
  "as_of",
  "comparison_basis",
  "evidence_role",
  "limit",
  "matching_count",
  "notice",
  "ranking_basis",
  "reference_notional",
  "regime",
  "rows",
  "truncated",
];
const LEAGUE_ROW_KEYS = [
  "current",
  "equity",
  "equity_as_of",
  "execution_profile",
  "id",
  "inception",
  "initial_cash",
  "last5",
  "mdd",
  "n_fills",
  "n_open",
  "name",
  "rank",
  "total_ret",
  "vs_spy",
];
const BULK_EQUITY_PROJECTION_KEYS = [
  "as_of",
  "equity_by_portfolio",
  "limit_per_portfolio",
  "matching_count_by_portfolio",
  "portfolio_limit",
  "portfolio_matching_count",
  "portfolios_truncated",
  "truncated_by_portfolio",
];
const EQUITY_ROW_KEYS = ["cash", "date", "equity", "n_positions", "portfolio_id"];

function hasExactKeys(value, keys) {
  return (
    isRecord(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function compareLeagueRows(left, right) {
  if (left.current !== right.current) return left.current ? -1 : 1;
  if ((left.total_ret === null) !== (right.total_ret === null)) {
    return left.total_ret === null ? 1 : -1;
  }
  if (left.total_ret !== null && left.total_ret !== right.total_ret) {
    return right.total_ret - left.total_ret;
  }
  return compareUnicodeCodePoints(left.id, right.id);
}

export function isLeagueProjection(data) {
  if (
    !isRecord(data) ||
    !hasExactKeys(data, LEAGUE_PROJECTION_KEYS) ||
    !Array.isArray(data.rows) ||
    data.limit !== LEAGUE_ROWS_LIMIT ||
    !isNonnegativeInteger(data.matching_count) ||
    typeof data.truncated !== "boolean" ||
    data.rows.length !== Math.min(data.matching_count, data.limit) ||
    data.truncated !== (data.matching_count > data.rows.length) ||
    !(data.as_of === null || isIsoDate(data.as_of)) ||
    !["risk-on", "risk-off", "unknown"].includes(data.regime) ||
    !Number.isFinite(data.reference_notional) ||
    data.reference_notional <= 0 ||
    data.ranking_basis !== "total_return_since_each_portfolio_inception" ||
    data.comparison_basis !== "SPY_over_each_portfolio_inception_window" ||
    data.evidence_role !== "operational_only" ||
    !isNonEmptyString(data.notice)
  ) {
    return false;
  }

  const ids = new Set();
  let expectedRank = 1;
  return data.rows.every((row, index, rows) => {
    if (
      !isRecord(row) ||
      !hasExactKeys(row, LEAGUE_ROW_KEYS) ||
      !isPublicPortfolioId(row.id) ||
      ids.has(row.id) ||
      !isNonEmptyString(row.name) ||
      !isIsoDate(row.inception) ||
      !(row.initial_cash === null || (Number.isFinite(row.initial_cash) && row.initial_cash > 0)) ||
      !(row.execution_profile === null || isNonEmptyString(row.execution_profile)) ||
      !isIsoDate(row.equity_as_of) ||
      typeof row.current !== "boolean" ||
      !Number.isFinite(row.equity) ||
      !isNullableFiniteNumber(row.total_ret) ||
      !isNullableFiniteNumber(row.vs_spy) ||
      !isNullableFiniteNumber(row.mdd) ||
      !isNullableFiniteNumber(row.last5) ||
      !isNonnegativeInteger(row.n_open) ||
      row.n_open < 0 ||
      !isNonnegativeInteger(row.n_fills) ||
      row.n_fills < 0 ||
      data.as_of === null ||
      row.equity_as_of > data.as_of ||
      row.current !== (row.equity_as_of === data.as_of) ||
      (index > 0 && compareLeagueRows(rows[index - 1], row) > 0) ||
      (row.current ? row.rank !== expectedRank : row.rank !== null)
    ) {
      return false;
    }
    ids.add(row.id);
    if (row.current) expectedRank += 1;
    return true;
  });
}

export function isBulkEquityProjection(data, league) {
  const leagueRows = league?.rows;
  const asOf = league?.as_of;
  if (
    !isRecord(data) ||
    !hasExactKeys(data, BULK_EQUITY_PROJECTION_KEYS) ||
    !isRecord(data.equity_by_portfolio) ||
    !isRecord(data.matching_count_by_portfolio) ||
    !isRecord(data.truncated_by_portfolio) ||
    !isPositiveInteger(data.portfolio_limit) ||
    !isNonnegativeInteger(data.portfolio_matching_count) ||
    typeof data.portfolios_truncated !== "boolean" ||
    data.limit_per_portfolio !== EQUITY_SERIES_LIMIT ||
    data.as_of !== asOf ||
    !Array.isArray(leagueRows) ||
    data.portfolio_limit !== league?.limit ||
    data.portfolio_matching_count !== league?.matching_count ||
    data.portfolios_truncated !== league?.truncated ||
    data.portfolios_truncated !==
      (data.portfolio_matching_count > data.portfolio_limit) ||
    !(asOf === null || isIsoDate(asOf))
  ) {
    return false;
  }
  const equityByPortfolio = data.equity_by_portfolio;
  const counts = data.matching_count_by_portfolio;
  const truncated = data.truncated_by_portfolio;
  const expectedIds = leagueRows.map((row) => row?.id);
  const portfolioIds = Object.keys(equityByPortfolio);
  if (
    expectedIds.some((id) => !isPublicPortfolioId(id)) ||
    new Set(expectedIds).size !== expectedIds.length ||
    portfolioIds.length !==
      Math.min(data.portfolio_matching_count, data.portfolio_limit) ||
    portfolioIds.length !== expectedIds.length ||
    expectedIds.some((id) => !Object.prototype.hasOwnProperty.call(equityByPortfolio, id)) ||
    Object.keys(counts).length !== portfolioIds.length ||
    Object.keys(truncated).length !== portfolioIds.length ||
    portfolioIds.some(
      (id) =>
        !Object.prototype.hasOwnProperty.call(counts, id) ||
        !Object.prototype.hasOwnProperty.call(truncated, id) ||
        !isNonnegativeInteger(counts[id]) ||
        typeof truncated[id] !== "boolean" ||
        equityByPortfolio[id]?.length !== Math.min(counts[id], data.limit_per_portfolio) ||
        truncated[id] !== (counts[id] > equityByPortfolio[id]?.length),
    )
  ) {
    return false;
  }
  const validSeries = Object.entries(equityByPortfolio).every(
    ([portfolioId, series]) => {
      if (!Array.isArray(series)) return false;
      let priorDate = null;
      return series.every((entry) => {
        const valid =
          isRecord(entry) &&
          hasExactKeys(entry, EQUITY_ROW_KEYS) &&
          entry.portfolio_id === portfolioId &&
          isIsoDate(entry.date) &&
          asOf !== null &&
          entry.date <= asOf &&
          Number.isFinite(entry.equity) &&
          Number.isFinite(entry.cash) &&
          isNonnegativeInteger(entry.n_positions) &&
          (priorDate === null || entry.date > priorDate);
        priorDate = entry?.date;
        return valid;
      });
    },
  );
  return (
    validSeries &&
    expectedIds.every((id) => equityByPortfolio[id].length > 0)
  );
}
