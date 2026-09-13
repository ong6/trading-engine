// Pure contracts for screen and candidate market-data responses.

import {
  compareUnicodeCodePoints,
  isIsoDate,
  isNonEmptyString,
  isNonnegativeInteger,
  isPositiveInteger,
  isRecord,
} from "./response-contracts.js";
import { isCandidateTicker } from "./candidate-route.js";

const SCREEN_RESULTS_LIMIT = 100;

const SCREEN_RESULT_KEYS = [
  "base_tight",
  "close",
  "dist_200d",
  "dist_50d",
  "new_today",
  "off_52w_high",
  "off_52w_low",
  "passes_template",
  "rs_rank",
  "run_date",
  "template_score",
  "ticker",
  "universe_policy",
  "vol_dryup",
];
const SCREEN_PROJECTION_KEYS = [
  "n_new_today",
  "n_passing",
  "n_total",
  "results",
  "results_has_next",
  "results_has_previous",
  "results_limit",
  "results_matching_count",
  "results_new_today",
  "results_offset",
  "results_page",
  "results_total_pages",
  "results_truncated",
  "run_date",
];
const CANDIDATE_PROJECTION_KEYS = [
  "as_of",
  "bars",
  "latest_close",
  "latest_close_date",
  "n_bars",
  "screen",
  "ticker",
];
const CANDIDATE_BAR_KEYS = ["close", "date", "high", "low", "open", "volume"];

function hasExactKeys(value, keys) {
  return (
    Object.keys(value).length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function hasExactScreenResultKeys(row) {
  return hasExactKeys(row, SCREEN_RESULT_KEYS);
}

export function isScreenResult(
  row,
  { runDate = null, ticker = null, passingOnly = false } = {},
) {
  return (
    isRecord(row) &&
    hasExactScreenResultKeys(row) &&
    isIsoDate(row.run_date) &&
    (runDate === null || row.run_date === runDate) &&
    isCandidateTicker(row.ticker) &&
    (ticker === null || row.ticker === ticker) &&
    Number.isFinite(row.close) &&
    row.close > 0 &&
    Number.isSafeInteger(row.rs_rank) &&
    row.rs_rank >= 1 &&
    row.rs_rank <= 99 &&
    Number.isSafeInteger(row.template_score) &&
    row.template_score >= 0 &&
    row.template_score <= 8 &&
    typeof row.passes_template === "boolean" &&
    (!passingOnly || row.passes_template) &&
    Number.isFinite(row.dist_50d) &&
    Number.isFinite(row.dist_200d) &&
    Number.isFinite(row.off_52w_low) &&
    Number.isFinite(row.off_52w_high) &&
    typeof row.base_tight === "boolean" &&
    typeof row.vol_dryup === "boolean" &&
    typeof row.new_today === "boolean" &&
    ["all", "ex-leveraged"].includes(row.universe_policy)
  );
}

export function isScreenProjection(data) {
  if (
    !isRecord(data) ||
    !hasExactKeys(data, SCREEN_PROJECTION_KEYS) ||
    !isIsoDate(data.run_date) ||
    !Array.isArray(data.results) ||
    !Number.isSafeInteger(data.n_total) ||
    !Number.isSafeInteger(data.n_passing) ||
    !Number.isSafeInteger(data.n_new_today) ||
    !isPositiveInteger(data.results_page) ||
    !isNonnegativeInteger(data.results_offset) ||
    data.results_limit !== SCREEN_RESULTS_LIMIT ||
    !isNonnegativeInteger(data.results_matching_count) ||
    !isPositiveInteger(data.results_total_pages) ||
    !isNonnegativeInteger(data.results_new_today) ||
    typeof data.results_truncated !== "boolean" ||
    typeof data.results_has_previous !== "boolean" ||
    typeof data.results_has_next !== "boolean" ||
    data.n_total < data.n_passing ||
    data.n_passing !== data.results_matching_count ||
    data.n_new_today < 0 ||
    data.n_new_today > data.n_passing ||
    data.results_total_pages !==
      Math.max(1, Math.ceil(data.results_matching_count / data.results_limit)) ||
    data.results_new_today !== data.results.filter((row) => row?.new_today === true).length ||
    data.results_offset !== (data.results_page - 1) * data.results_limit ||
    data.results.length !==
      Math.min(data.results_limit, Math.max(data.results_matching_count - data.results_offset, 0)) ||
    data.results_truncated !== (data.results_matching_count > data.results.length) ||
    data.results_has_previous !== (data.results_page > 1) ||
    data.results_has_next !==
      (data.results_offset + data.results.length < data.results_matching_count)
  ) {
    return false;
  }
  const tickers = new Set();
  let previous = null;
  return data.results.every((row) => {
    const validRow = isScreenResult(row, {
      runDate: data.run_date,
      passingOnly: true,
    });
    const ordered =
      previous === null ||
      (validRow &&
        (row.rs_rank < previous.rs_rank ||
          (row.rs_rank === previous.rs_rank &&
            compareUnicodeCodePoints(row.ticker, previous.ticker) > 0)));
    const valid = validRow && !tickers.has(row.ticker) && ordered;
    if (valid) {
      tickers.add(row.ticker);
      previous = row;
    }
    return valid;
  });
}

export function isCandidateProjection(data, expectedTicker) {
  if (
    !isRecord(data) ||
    !hasExactKeys(data, CANDIDATE_PROJECTION_KEYS) ||
    data.ticker !== expectedTicker ||
    !isIsoDate(data.as_of) ||
    !Array.isArray(data.bars) ||
    !Number.isSafeInteger(data.n_bars) ||
    data.n_bars !== data.bars.length ||
    data.n_bars < 1 ||
    data.n_bars > 250
  ) {
    return false;
  }
  let priorDate = null;
  const barsValid = data.bars.every((bar) => {
    const valid =
      isRecord(bar) &&
      hasExactKeys(bar, CANDIDATE_BAR_KEYS) &&
      isIsoDate(bar.date) &&
      (priorDate === null || bar.date > priorDate) &&
      bar.date <= data.as_of &&
      Number.isFinite(bar.open) &&
      bar.open > 0 &&
      Number.isFinite(bar.high) &&
      bar.high > 0 &&
      Number.isFinite(bar.low) &&
      bar.low > 0 &&
      Number.isFinite(bar.close) &&
      bar.close > 0 &&
      bar.high >= Math.max(bar.open, bar.close, bar.low) &&
      bar.low <= Math.min(bar.open, bar.close, bar.high) &&
      Number.isFinite(bar.volume) &&
      bar.volume >= 0;
    priorDate = bar?.date;
    return valid;
  });
  if (!barsValid) return false;

  const quoteMissing = data.latest_close_date === null && data.latest_close === null;
  const quoteBar = data.bars.find((bar) => bar.date === data.latest_close_date);
  const quoteValid =
    isIsoDate(data.latest_close_date) &&
    data.latest_close_date <= data.as_of &&
    Number.isFinite(data.latest_close) &&
    data.latest_close > 0 &&
    quoteBar?.close === data.latest_close;
  const screenValid =
    data.screen === null ||
    (isScreenResult(data.screen, { ticker: expectedTicker }) &&
      data.screen.run_date <= data.as_of);
  return (quoteMissing || quoteValid) && screenValid;
}
