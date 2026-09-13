import assert from "node:assert/strict";
import test from "node:test";

import {
  PUBLIC_PORTFOLIO_ID_MAX_CHARS,
  PUBLIC_SAFE_INTEGER_MAX,
  compareUnicodeCodePoints,
  isBoundedCollection,
  isIsoDate,
  isIsoTimestamp,
  isNonEmptyString,
  isNonnegativeInteger,
  isPositiveInteger,
  isPublicPortfolioId,
} from "../app/lib/response-contracts.js";
import {
  isCandidateProjection,
  isScreenProjection,
} from "../app/lib/market-contracts.js";
import {
  isBulkEquityProjection,
  isLeagueProjection,
} from "../app/lib/league-contracts.js";
import {
  isResearchReadinessProjection,
} from "../app/lib/research-contracts.js";

const clone = (value) => structuredClone(value);

test("ISO dates and timestamps reject normalized or malformed calendar values", () => {
  for (const value of ["2026-09-08", "2024-02-29", "0001-01-01"]) {
    assert.equal(isIsoDate(value), true, value);
  }
  for (const value of [
    "2026-02-29",
    "2024-02-30",
    "2026-99-99",
    "2026-00-01",
    "0000-01-01",
    "2026-9-08",
    "2026-09-08T00:00:00",
  ]) {
    assert.equal(isIsoDate(value), false, value);
  }

  for (const value of [
    "2026-07-18T15:35:39.553196",
    "2026-09-08T12:00:00Z",
    "2026-09-08T12:00:00+00:00",
  ]) {
    assert.equal(isIsoTimestamp(value), true, value);
  }
  for (const value of [
    "2026-02-30T00:00:00Z",
    "2026-09-08 12:00:00",
    "2026-09-08T24:00:00Z",
    "2026-09-08T12:60:00Z",
    "2026-09-08T12:00Z",
    "2026-09-08T12:00:00+14:01",
    "2026-09-08T12:00:00-23:00",
    "not-a-timestamp",
  ]) {
    assert.equal(isIsoTimestamp(value), false, value);
  }
});

function screenRow(overrides = {}) {
  return {
    run_date: "2026-09-04",
    ticker: "AAA",
    close: 101.5,
    rs_rank: 90,
    template_score: 7,
    passes_template: true,
    dist_50d: 0.1,
    dist_200d: 0.2,
    off_52w_low: 0.5,
    off_52w_high: -0.03,
    base_tight: true,
    vol_dryup: false,
    new_today: true,
    universe_policy: "all",
    ...overrides,
  };
}

function readinessFixture() {
  const datedFamily = {
    status: "WAITING",
    limitation: "collecting prospective data",
    first_date: "2026-09-01",
    last_date: "2026-09-04",
    qualifying_first_date: null,
    qualifying_last_date: null,
    qualifying_calendar_span_days: 0,
    minimum_calendar_span_days: 30,
  };
  return {
    schema_version: 10,
    purpose: "candidate_admission_only",
    paper_only: true,
    automatic_action: "none",
    ready_families: [],
    notice: "Evidence readiness does not promote or trade a strategy.",
    families: {
      stock_selection: {
        ...datedFamily,
        input_status: "ready",
        missing_tables: [],
        missing_columns: {},
        incompatible_columns: {},
        observed_shared_dates: 4,
        qualifying_shared_dates: 0,
        minimum_observed_names_per_date: 3,
        minimum_shared_dates: 20,
        minimum_names_per_date: 10,
        breadth_rule: "same_date_ticker_intersection",
      },
      fundamentals: {
        ...datedFamily,
        input_status: "ready",
        missing_tables: [],
        missing_columns: {},
        incompatible_columns: {},
        observed_snapshots: 4,
        qualifying_snapshots: 0,
        minimum_observed_names_per_snapshot: 3,
        minimum_snapshots: 20,
        minimum_names_per_snapshot: 10,
        numeric_rule: "finite_positive_market_cap_and_finite_valuation",
        usable_observation_rule: "point-in-time only",
      },
      intraday: {
        status: "WAITING",
        input_status: "ready",
        missing_tables: [],
        missing_columns: {},
        incompatible_columns: {},
        limitation: "collecting prospective data",
        required_intervals: ["1m", "5m"],
        minimum_sessions_per_interval: 20,
        minimum_calendar_span_days: 30,
        minimum_tickers_per_interval: 10,
        minimum_session_coverage_fraction: 0.75,
        session_schedule_source: "pandas_market_calendars:NYSE",
        usable_observation_rule: "substantial per-ticker bar coverage",
        observed_sessions: { "1m": 4, "5m": 4 },
        first_date: { "1m": "2026-09-01", "5m": "2026-09-01" },
        last_date: { "1m": "2026-09-04", "5m": "2026-09-04" },
        minimum_observed_names_per_session: { "1m": 3, "5m": 3 },
        minimum_usable_names_per_session: { "1m": 2, "5m": 2 },
        qualifying_sessions: { "1m": 0, "5m": 0 },
        qualifying_first_date: { "1m": null, "5m": null },
        qualifying_last_date: { "1m": null, "5m": null },
        qualifying_calendar_span_days: { "1m": 0, "5m": 0 },
      },
    },
  };
}

test("bounded collection metadata must describe the returned rows", () => {
  const valid = { items: [1, 2], limit: 2, matching_count: 3, truncated: true };
  assert.equal(isBoundedCollection(valid, "items"), true);
  assert.equal(isBoundedCollection({ ...valid, truncated: false }, "items"), false);
  assert.equal(isBoundedCollection({ ...valid, items: [1] }, "items"), false);
  assert.equal(
    isBoundedCollection({ ...valid, limit: Number.MAX_SAFE_INTEGER + 1 }, "items"),
    false,
  );
  assert.equal(
    isBoundedCollection({ ...valid, matching_count: Number.MAX_SAFE_INTEGER + 1 }, "items"),
    false,
  );
});

test("shared non-empty strings reject whitespace-only identifiers", () => {
  assert.equal(isNonEmptyString("book-a"), true);
  assert.equal(isNonEmptyString("  "), false);
});

test("public portfolio identifiers are trimmed printable lines of at most 128 characters", () => {
  assert.equal(PUBLIC_PORTFOLIO_ID_MAX_CHARS, 128);
  for (const value of [
    "book-a",
    "book alpha",
    "💥".repeat(PUBLIC_PORTFOLIO_ID_MAX_CHARS),
  ]) {
    assert.equal(isPublicPortfolioId(value), true, value);
  }
  for (const value of [
    "",
    " ",
    " book",
    "book ",
    "book\nother",
    "book\tother",
    "x".repeat(PUBLIC_PORTFOLIO_ID_MAX_CHARS + 1),
  ]) {
    assert.equal(isPublicPortfolioId(value), false, JSON.stringify(value));
  }
});

test("shared integer predicates require exactly representable JSON integers", () => {
  assert.equal(PUBLIC_SAFE_INTEGER_MAX, Number.MAX_SAFE_INTEGER);
  for (const value of [0, 1, 42, Number.MAX_SAFE_INTEGER]) {
    assert.equal(isNonnegativeInteger(value), true);
  }
  for (const value of [1, 42, Number.MAX_SAFE_INTEGER]) {
    assert.equal(isPositiveInteger(value), true);
  }
  for (const value of [true, false, -1, 1.5, "1", null, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(isNonnegativeInteger(value), false);
  }
  for (const value of [0, -1, true, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(isPositiveInteger(value), false);
  }
});

test("shared string ordering follows Unicode code points instead of UTF-16 units", () => {
  assert.equal("\u{10000}" < "\uF900", true);
  assert.equal(compareUnicodeCodePoints("\uF900", "\u{10000}") < 0, true);
});

test("screen projection requires coherent counts, dates, and unique passing tickers", () => {
  const valid = {
    run_date: "2026-09-04",
    n_total: 5,
    n_passing: 2,
    n_new_today: 1,
    results_page: 1,
    results_offset: 0,
    results_limit: 100,
    results_matching_count: 2,
    results_total_pages: 1,
    results_new_today: 1,
    results_truncated: false,
    results_has_previous: false,
    results_has_next: false,
    results: [screenRow(), screenRow({ ticker: "BBB", new_today: false })],
  };
  assert.equal(isScreenProjection(valid), true);

  const unsafeCount = clone(valid);
  unsafeCount.n_total = Number.MAX_SAFE_INTEGER + 1;
  assert.equal(isScreenProjection(unsafeCount), false);

  const wrongCount = clone(valid);
  wrongCount.results_matching_count = 1;
  assert.equal(isScreenProjection(wrongCount), false);

  const wrongPageCount = clone(valid);
  wrongPageCount.results_new_today = 0;
  assert.equal(isScreenProjection(wrongPageCount), false);

  const wrongTotalPages = clone(valid);
  wrongTotalPages.results_total_pages = 2;
  assert.equal(isScreenProjection(wrongTotalPages), false);

  const wrongOffset = clone(valid);
  wrongOffset.results_page = 2;
  assert.equal(isScreenProjection(wrongOffset), false);

  const wrongNext = clone(valid);
  wrongNext.results_has_next = true;
  assert.equal(isScreenProjection(wrongNext), false);

  const duplicate = clone(valid);
  duplicate.results[1].ticker = "AAA";
  assert.equal(isScreenProjection(duplicate), false);

  const malformedTicker = clone(valid);
  malformedTicker.results[0].ticker = "AAA\nBAD";
  assert.equal(isScreenProjection(malformedTicker), false);

  const wrongDate = clone(valid);
  wrongDate.results[0].run_date = "2026-09-03";
  assert.equal(isScreenProjection(wrongDate), false);

  const failedRow = clone(valid);
  failedRow.results[0].passes_template = false;
  assert.equal(isScreenProjection(failedRow), false);

  const unexpectedField = clone(valid);
  unexpectedField.results[0].internal = "not public";
  assert.equal(isScreenProjection(unexpectedField), false);

  const unknownUniversePolicy = clone(valid);
  unknownUniversePolicy.results[0].universe_policy = "unknown";
  assert.equal(isScreenProjection(unknownUniversePolicy), false);

  const nonfiniteClose = clone(valid);
  nonfiniteClose.results[0].close = Number.NaN;
  assert.equal(isScreenProjection(nonfiniteClose), false);

  const fractionalRank = clone(valid);
  fractionalRank.results[0].rs_rank = 90.5;
  assert.equal(isScreenProjection(fractionalRank), false);

  const unordered = clone(valid);
  unordered.results.reverse();
  assert.equal(isScreenProjection(unordered), false);

  const unicodeTie = clone(valid);
  unicodeTie.results = [
    screenRow({ ticker: "\uF900" }),
    screenRow({ ticker: "\u{10000}", new_today: false }),
  ];
  assert.equal(isScreenProjection(unicodeTie), true);
  unicodeTie.results.reverse();
  assert.equal(isScreenProjection(unicodeTie), false);

  const inventedLimit = clone(valid);
  inventedLimit.results_limit = 2;
  assert.equal(isScreenProjection(inventedLimit), false);

  const extraEnvelopeField = clone(valid);
  extraEnvelopeField.internal = "not public";
  assert.equal(isScreenProjection(extraEnvelopeField), false);
});

test("league projection distinguishes ranked current rows from stale rows", () => {
  const valid = {
    as_of: "2026-09-04",
    regime: "risk-on",
    reference_notional: 39_000,
    ranking_basis: "total_return_since_each_portfolio_inception",
    comparison_basis: "SPY_over_each_portfolio_inception_window",
    evidence_role: "operational_only",
    notice: "Not research evidence.",
    limit: 100,
    matching_count: 2,
    truncated: false,
    rows: [
      {
        id: "current",
        name: "Current book",
        inception: "2026-01-01",
        initial_cash: 39_000,
        execution_profile: "baseline_v1",
        equity_as_of: "2026-09-04",
        current: true,
        rank: 1,
        equity: 40_000,
        total_ret: 0.02,
        vs_spy: -0.01,
        mdd: -0.03,
        last5: 0.01,
        n_open: 2,
        n_fills: 10,
      },
      {
        id: "stale",
        name: "Stale book",
        inception: "2026-01-01",
        initial_cash: null,
        execution_profile: null,
        equity_as_of: "2026-09-03",
        current: false,
        rank: null,
        equity: 39_500,
        total_ret: null,
        vs_spy: null,
        mdd: null,
        last5: null,
        n_open: 0,
        n_fills: 0,
      },
    ],
  };
  assert.equal(isLeagueProjection(valid), true);

  const extraEnvelope = clone(valid);
  extraEnvelope.internal = "not public";
  assert.equal(isLeagueProjection(extraEnvelope), false);

  const extraRowField = clone(valid);
  extraRowField.rows[0].internal = "not public";
  assert.equal(isLeagueProjection(extraRowField), false);

  const rankedStale = clone(valid);
  rankedStale.rows[1].rank = 2;
  assert.equal(isLeagueProjection(rankedStale), false);

  const duplicate = clone(valid);
  duplicate.rows[1].id = "current";
  assert.equal(isLeagueProjection(duplicate), false);

  const futureEquity = clone(valid);
  futureEquity.rows[0].equity_as_of = "2026-09-05";
  assert.equal(isLeagueProjection(futureEquity), false);

  const whitespaceId = clone(valid);
  whitespaceId.rows[0].id = "  ";
  assert.equal(isLeagueProjection(whitespaceId), false);

  const multilineId = clone(valid);
  multilineId.rows[0].id = "current\nother";
  assert.equal(isLeagueProjection(multilineId), false);

  const oversizedId = clone(valid);
  oversizedId.rows[0].id = "x".repeat(129);
  assert.equal(isLeagueProjection(oversizedId), false);

  const unknownRegime = clone(valid);
  unknownRegime.regime = "maybe";
  assert.equal(isLeagueProjection(unknownRegime), false);

  const wrongSemantics = clone(valid);
  wrongSemantics.ranking_basis = "latest_equity";
  assert.equal(isLeagueProjection(wrongSemantics), false);

  const staleFirst = clone(valid);
  staleFirst.rows.reverse();
  staleFirst.rows[0].rank = null;
  staleFirst.rows[1].rank = 1;
  assert.equal(isLeagueProjection(staleFirst), false);

  const wrongReturnOrder = clone(valid);
  wrongReturnOrder.rows = [
    clone(valid.rows[0]),
    { ...clone(valid.rows[0]), id: "better", name: "Better", rank: 2, total_ret: 0.03 },
  ];
  assert.equal(isLeagueProjection(wrongReturnOrder), false);

  const unicodeTie = clone(valid);
  unicodeTie.rows = [
    { ...clone(valid.rows[0]), id: "\uF900", name: "BMP", rank: 1 },
    {
      ...clone(valid.rows[0]),
      id: "\u{10000}",
      name: "non-BMP",
      rank: 2,
    },
  ];
  assert.equal(isLeagueProjection(unicodeTie), true);
  unicodeTie.rows.reverse();
  unicodeTie.rows[0].rank = 1;
  unicodeTie.rows[1].rank = 2;
  assert.equal(isLeagueProjection(unicodeTie), false);

  const invalidCapital = clone(valid);
  invalidCapital.rows[0].initial_cash = 0;
  assert.equal(isLeagueProjection(invalidCapital), false);

  const inconsistentTotal = clone(valid);
  inconsistentTotal.matching_count = 3;
  assert.equal(isLeagueProjection(inconsistentTotal), false);

  const inventedLimit = clone(valid);
  inventedLimit.limit = 1;
  inventedLimit.matching_count = 2;
  inventedLimit.truncated = true;
  inventedLimit.rows = inventedLimit.rows.slice(0, 1);
  assert.equal(isLeagueProjection(inventedLimit), false);
});

test("bulk equity requires every League book and ordered coherent series", () => {
  const rows = [{ id: "book-a" }, { id: "book-b" }];
  const league = {
    as_of: "2026-09-04",
    limit: 100,
    matching_count: 2,
    truncated: false,
    rows,
  };
  const valid = {
    as_of: "2026-09-04",
    portfolio_limit: 100,
    portfolio_matching_count: 2,
    portfolios_truncated: false,
    limit_per_portfolio: 500,
    equity_by_portfolio: {
      "book-a": [
        {
          portfolio_id: "book-a",
          date: "2026-09-03",
          equity: 39_000,
          cash: 1_000,
          n_positions: 2,
        },
        {
          portfolio_id: "book-a",
          date: "2026-09-04",
          equity: 39_500,
          cash: 500,
          n_positions: 3,
        },
      ],
      "book-b": [
        {
          portfolio_id: "book-b",
          date: "2026-09-04",
          equity: 40_000,
          cash: 2_000,
          n_positions: 1,
        },
      ],
    },
    matching_count_by_portfolio: { "book-a": 2, "book-b": 1 },
    truncated_by_portfolio: { "book-a": false, "book-b": false },
  };
  assert.equal(isBulkEquityProjection(valid, league), true);

  const extraEnvelope = clone(valid);
  extraEnvelope.internal = "not public";
  assert.equal(isBulkEquityProjection(extraEnvelope, league), false);

  const extraRowField = clone(valid);
  extraRowField.equity_by_portfolio["book-a"][0].internal = "not public";
  assert.equal(isBulkEquityProjection(extraRowField, league), false);

  const omitted = clone(valid);
  delete omitted.equity_by_portfolio["book-b"];
  assert.equal(isBulkEquityProjection(omitted, league), false);

  const mismatchedAsOf = clone(valid);
  mismatchedAsOf.as_of = "2026-09-03";
  assert.equal(isBulkEquityProjection(mismatchedAsOf, league), false);

  const mismatchedPortfolioCount = clone(valid);
  mismatchedPortfolioCount.portfolio_matching_count = 3;
  assert.equal(isBulkEquityProjection(mismatchedPortfolioCount, league), false);

  const mismatchedPortfolioTruncation = clone(valid);
  mismatchedPortfolioTruncation.portfolios_truncated = true;
  assert.equal(isBulkEquityProjection(mismatchedPortfolioTruncation, league), false);

  const extra = clone(valid);
  extra.equity_by_portfolio["new-book"] = [];
  extra.matching_count_by_portfolio["new-book"] = 0;
  extra.truncated_by_portfolio["new-book"] = false;
  assert.equal(isBulkEquityProjection(extra, league), false);

  extra.equity_by_portfolio["new-book"] = [
    {
      portfolio_id: "new-book",
      date: "2026-09-04",
      equity: 40_000,
      cash: 2_000,
      n_positions: 1,
    },
  ];
  assert.equal(isBulkEquityProjection(extra, league), false);

  assert.equal(
    isBulkEquityProjection(valid, {
      ...league,
      rows: [{ id: "book-a" }, { id: "book-a" }],
    }),
    false,
  );

  const mismatchedBook = clone(valid);
  mismatchedBook.equity_by_portfolio["book-a"][0].portfolio_id = "book-b";
  assert.equal(isBulkEquityProjection(mismatchedBook, league), false);

  const unordered = clone(valid);
  unordered.equity_by_portfolio["book-a"].reverse();
  assert.equal(isBulkEquityProjection(unordered, league), false);

  const nonFinite = clone(valid);
  nonFinite.equity_by_portfolio["book-b"][0].equity = Number.NaN;
  assert.equal(isBulkEquityProjection(nonFinite, league), false);

  const nonFiniteCash = clone(valid);
  nonFiniteCash.equity_by_portfolio["book-b"][0].cash = Number.POSITIVE_INFINITY;
  assert.equal(isBulkEquityProjection(nonFiniteCash, league), false);

  const unsafePositionCount = clone(valid);
  unsafePositionCount.equity_by_portfolio["book-b"][0].n_positions =
    Number.MAX_SAFE_INTEGER + 1;
  assert.equal(isBulkEquityProjection(unsafePositionCount, league), false);

  const future = clone(valid);
  future.equity_by_portfolio["book-a"][1].date = "2026-09-05";
  assert.equal(isBulkEquityProjection(future, league), false);

  const inventedSeriesLimit = clone(valid);
  inventedSeriesLimit.limit_per_portfolio = 2;
  assert.equal(isBulkEquityProjection(inventedSeriesLimit, league), false);

  for (const mutate of [
    (value) => (value.limit_per_portfolio = 0),
    (value) => (value.matching_count_by_portfolio["book-a"] = 3),
    (value) => (value.truncated_by_portfolio["book-a"] = true),
    (value) => delete value.matching_count_by_portfolio["book-b"],
    (value) => (value.truncated_by_portfolio["book-b"] = "false"),
  ]) {
    const malformed = clone(valid);
    mutate(malformed);
    assert.equal(isBulkEquityProjection(malformed, league), false);
  }
});

test("research readiness derives status and the ready-family list from thresholds", () => {
  const waiting = readinessFixture();
  assert.equal(isResearchReadinessProjection(waiting), true);

  const unsafeMinimum = clone(waiting);
  unsafeMinimum.families.stock_selection.minimum_shared_dates =
    Number.MAX_SAFE_INTEGER + 1;
  assert.equal(isResearchReadinessProjection(unsafeMinimum), false);

  const falseReady = clone(waiting);
  falseReady.families.stock_selection.status = "READY_FOR_CHARTER";
  assert.equal(isResearchReadinessProjection(falseReady), false);

  const countOnlyStockBreadth = clone(waiting);
  countOnlyStockBreadth.families.stock_selection.breadth_rule = "minimum_table_count";
  assert.equal(isResearchReadinessProjection(countOnlyStockBreadth), false);

  const looseFundamentalNumbers = clone(waiting);
  looseFundamentalNumbers.families.fundamentals.numeric_rule = "non_null";
  assert.equal(isResearchReadinessProjection(looseFundamentalNumbers), false);

  const inventedReadyList = clone(waiting);
  inventedReadyList.ready_families = ["stock_selection"];
  assert.equal(isResearchReadinessProjection(inventedReadyList), false);

  const extraFamily = clone(waiting);
  extraFamily.families.unregistered = {};
  assert.equal(isResearchReadinessProjection(extraFamily), false);

  const impossibleUsableBreadth = clone(waiting);
  impossibleUsableBreadth.families.intraday.minimum_usable_names_per_session["1m"] = 4;
  assert.equal(isResearchReadinessProjection(impossibleUsableBreadth), false);

  const invalidCoverageFraction = clone(waiting);
  invalidCoverageFraction.families.intraday.minimum_session_coverage_fraction = 1.1;
  assert.equal(isResearchReadinessProjection(invalidCoverageFraction), false);

  const wrongSchedule = clone(waiting);
  wrongSchedule.families.intraday.session_schedule_source = "inferred";
  assert.equal(isResearchReadinessProjection(wrongSchedule), false);

  const missingReadyInput = clone(waiting);
  missingReadyInput.families.stock_selection.input_status = "missing";
  missingReadyInput.families.stock_selection.missing_tables = ["screen_results"];
  assert.equal(isResearchReadinessProjection(missingReadyInput), false);
  Object.assign(missingReadyInput.families.stock_selection, {
    observed_shared_dates: 0,
    first_date: null,
    last_date: null,
    minimum_observed_names_per_date: 0,
  });
  assert.equal(isResearchReadinessProjection(missingReadyInput), true);

  missingReadyInput.families.stock_selection.status = "READY_FOR_CHARTER";
  assert.equal(isResearchReadinessProjection(missingReadyInput), false);

  const malformedInputDescription = clone(waiting);
  malformedInputDescription.families.intraday.input_status = "invalid-schema";
  assert.equal(isResearchReadinessProjection(malformedInputDescription), false);

  const incompatibleInput = clone(waiting);
  incompatibleInput.families.intraday.input_status = "invalid-schema";
  incompatibleInput.families.intraday.incompatible_columns = {
    intraday_prices: { ts: "VARCHAR" },
  };
  Object.assign(incompatibleInput.families.intraday, {
    observed_sessions: { "1m": 0, "5m": 0 },
    first_date: { "1m": null, "5m": null },
    last_date: { "1m": null, "5m": null },
    minimum_observed_names_per_session: { "1m": 0, "5m": 0 },
    minimum_usable_names_per_session: { "1m": 0, "5m": 0 },
  });
  assert.equal(isResearchReadinessProjection(incompatibleInput), true);

  incompatibleInput.families.intraday.status = "READY_FOR_CHARTER";
  assert.equal(isResearchReadinessProjection(incompatibleInput), false);

  for (const mutate of [
    (value) => (value.families.stock_selection.qualifying_calendar_span_days = 1),
    (value) => (value.families.stock_selection.last_date = "2026-09-02"),
    (value) => (value.families.stock_selection.missing_tables = ["invented"]),
    (value) =>
      (value.families.stock_selection.missing_columns = {
        universe_snapshot: ["invented"],
      }),
    (value) => (value.families.intraday.observed_sessions.tick = 4),
    (value) => (value.families.intraday.qualifying_calendar_span_days["1m"] = 1),
    (value) => (value.internal = "not public"),
    (value) => (value.families.stock_selection.internal = "not public"),
    (value) => (value.families.fundamentals.internal = "not public"),
    (value) => (value.families.intraday.internal = "not public"),
    (value) => (value.notice = "   "),
    (value) => (value.families.stock_selection.limitation = "   "),
    (value) => (value.families.fundamentals.usable_observation_rule = "   "),
    (value) => (value.families.intraday.limitation = "   "),
  ]) {
    const malformed = clone(waiting);
    mutate(malformed);
    assert.equal(isResearchReadinessProjection(malformed), false);
  }
});

test("candidate projection requires ordered coherent bars and an exact quote", () => {
  const valid = {
    ticker: "AAA",
    as_of: "2026-09-04",
    n_bars: 2,
    bars: [
      { date: "2026-09-03", open: 99, high: 102, low: 98, close: 101, volume: 1000 },
      { date: "2026-09-04", open: 101, high: 104, low: 100, close: 103, volume: 1200 },
    ],
    latest_close_date: "2026-09-04",
    latest_close: 103,
    screen: screenRow({ ticker: "AAA" }),
  };
  assert.equal(isCandidateProjection(valid, "AAA"), true);

  const unsafeBarCount = clone(valid);
  unsafeBarCount.n_bars = Number.MAX_SAFE_INTEGER + 1;
  assert.equal(isCandidateProjection(unsafeBarCount, "AAA"), false);

  const reversed = clone(valid);
  reversed.bars.reverse();
  assert.equal(isCandidateProjection(reversed, "AAA"), false);

  const impossibleBar = clone(valid);
  impossibleBar.bars[0].high = 100;
  assert.equal(isCandidateProjection(impossibleBar, "AAA"), false);

  const negativeVolume = clone(valid);
  negativeVolume.bars[0].volume = -1;
  assert.equal(isCandidateProjection(negativeVolume, "AAA"), false);

  const staleQuote = clone(valid);
  staleQuote.latest_close = 102;
  assert.equal(isCandidateProjection(staleQuote, "AAA"), false);

  const wrongTicker = clone(valid);
  wrongTicker.ticker = "BBB";
  assert.equal(isCandidateProjection(wrongTicker, "AAA"), false);

  const extraEnvelopeField = clone(valid);
  extraEnvelopeField.internal = "not public";
  assert.equal(isCandidateProjection(extraEnvelopeField, "AAA"), false);

  const extraBarField = clone(valid);
  extraBarField.bars[0].adjusted_close = 100;
  assert.equal(isCandidateProjection(extraBarField, "AAA"), false);

  const tooManyBars = clone(valid);
  tooManyBars.bars = Array.from({ length: 251 }, (_, index) => ({
    date: `2025-${String(Math.floor(index / 28) + 1).padStart(2, "0")}-${String((index % 28) + 1).padStart(2, "0")}`,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 1000,
  }));
  tooManyBars.n_bars = tooManyBars.bars.length;
  assert.equal(isCandidateProjection(tooManyBars, "AAA"), false);
});
