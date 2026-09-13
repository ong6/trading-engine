// Pure coverage-family contracts used by the research-readiness projection.

import { isIsoDate, isNonnegativeInteger, isRecord } from "./response-contracts.js";

export const INPUT_STATUS_FIELDS = [
  "incompatible_columns",
  "input_status",
  "missing_columns",
  "missing_tables",
  "status",
];

function isDateOrNull(value) {
  return value === null || isIsoDate(value);
}

function calendarSpanDays(first, last) {
  return (Date.parse(`${last}T00:00:00Z`) - Date.parse(`${first}T00:00:00Z`)) / 86400000;
}

function validDateRange(count, first, last) {
  if (!isDateOrNull(first) || !isDateOrNull(last)) return false;
  if (count === 0) return first === null && last === null;
  if (first === null || last === null || first > last) return false;
  const span = calendarSpanDays(first, last);
  return (count !== 1 || span === 0) && count <= span + 1;
}

function exactKeys(value, expected) {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => keys.includes(key));
}

export function hasExactResearchFields(value, expected) {
  return isRecord(value) && exactKeys(value, expected);
}

export function validInputStatus(family) {
  if (
    !["ready", "missing", "invalid-schema"].includes(family.input_status) ||
    !Array.isArray(family.missing_tables) ||
    !family.missing_tables.every((value) => typeof value === "string" && value.length > 0) ||
    new Set(family.missing_tables).size !== family.missing_tables.length ||
    !isRecord(family.missing_columns) ||
    !isRecord(family.incompatible_columns) ||
    !Object.entries(family.missing_columns).every(
      ([, values]) =>
        Array.isArray(values) &&
        values.length > 0 &&
        new Set(values).size === values.length &&
        values.every((value) => typeof value === "string" && value.length > 0),
    ) ||
    !Object.entries(family.incompatible_columns).every(
      ([, columns]) =>
        isRecord(columns) &&
        Object.keys(columns).length > 0 &&
        Object.entries(columns).every(
          ([column, value]) => column.length > 0 && typeof value === "string" && value.length > 0,
        ),
    )
  ) {
    return false;
  }
  const missingColumnTables = Object.keys(family.missing_columns);
  const incompatibleColumnTables = Object.keys(family.incompatible_columns);
  if (
    missingColumnTables.some((table) => family.missing_tables.includes(table)) ||
    incompatibleColumnTables.some((table) => family.missing_tables.includes(table)) ||
    missingColumnTables.some((table) =>
      Object.keys(family.incompatible_columns[table] || {}).some((column) =>
        family.missing_columns[table].includes(column),
      ),
    )
  ) {
    return false;
  }
  if (family.input_status === "ready") {
    return (
      family.missing_tables.length === 0 &&
      missingColumnTables.length === 0 &&
      incompatibleColumnTables.length === 0
    );
  }
  if (family.input_status === "missing") {
    return (
      family.missing_tables.length > 0 &&
      missingColumnTables.length === 0 &&
      incompatibleColumnTables.length === 0
    );
  }
  return missingColumnTables.length > 0 || incompatibleColumnTables.length > 0;
}

export function validExpectedInputStatus(family, requiredInputs) {
  if (!isRecord(requiredInputs) || !validInputStatus(family)) return false;
  return (
    family.missing_tables.every((table) => Object.hasOwn(requiredInputs, table)) &&
    Object.entries(family.missing_columns).every(
      ([table, columns]) =>
        Object.hasOwn(requiredInputs, table) &&
        columns.every((column) => requiredInputs[table].includes(column)),
    ) &&
    Object.entries(family.incompatible_columns).every(
      ([table, columns]) =>
        Object.hasOwn(requiredInputs, table) &&
        Object.keys(columns).every((column) => requiredInputs[table].includes(column)),
    )
  );
}

export function validDatedCoverage(family, fields) {
  const observed = family[fields.observed];
  const qualifying = family[fields.qualifying];
  const first = family.first_date;
  const last = family.last_date;
  const qualifyingFirst = family.qualifying_first_date;
  const qualifyingLast = family.qualifying_last_date;
  return (
    isNonnegativeInteger(observed) &&
    isNonnegativeInteger(qualifying) &&
    qualifying <= observed &&
    isNonnegativeInteger(family[fields.observedBreadth]) &&
    (observed === 0) === (family[fields.observedBreadth] === 0) &&
    isNonnegativeInteger(family.qualifying_calendar_span_days) &&
    Number.isSafeInteger(family[fields.minimum]) &&
    family[fields.minimum] > 0 &&
    Number.isSafeInteger(family.minimum_calendar_span_days) &&
    family.minimum_calendar_span_days > 0 &&
    Number.isSafeInteger(family[fields.minimumBreadth]) &&
    family[fields.minimumBreadth] > 0 &&
    validDateRange(observed, first, last) &&
    validDateRange(qualifying, qualifyingFirst, qualifyingLast) &&
    family.qualifying_calendar_span_days ===
      (qualifying === 0 ? 0 : calendarSpanDays(qualifyingFirst, qualifyingLast)) &&
    (qualifying === 0 || (qualifyingFirst >= first && qualifyingLast <= last)) &&
    (family.input_status === "ready" ||
      (observed === 0 && qualifying === 0 && family[fields.observedBreadth] === 0))
  );
}

export function validIntradayCoverage(family) {
  const intervals = ["1m", "5m"];
  const maps = [
    "observed_sessions",
    "first_date",
    "last_date",
    "minimum_observed_names_per_session",
    "minimum_usable_names_per_session",
    "qualifying_sessions",
    "qualifying_first_date",
    "qualifying_last_date",
    "qualifying_calendar_span_days",
  ];
  if (
    !isRecord(family) ||
    !hasExactResearchFields(family, [
      ...INPUT_STATUS_FIELDS,
      "first_date",
      "last_date",
      "limitation",
      "minimum_calendar_span_days",
      "minimum_observed_names_per_session",
      "minimum_session_coverage_fraction",
      "minimum_sessions_per_interval",
      "minimum_tickers_per_interval",
      "minimum_usable_names_per_session",
      "observed_sessions",
      "qualifying_calendar_span_days",
      "qualifying_first_date",
      "qualifying_last_date",
      "qualifying_sessions",
      "required_intervals",
      "session_schedule_source",
      "usable_observation_rule",
    ]) ||
    !["WAITING", "READY_FOR_CHARTER"].includes(family.status) ||
    !validExpectedInputStatus(family, {
      intraday_prices: ["ticker", "ts", "interval"],
    }) ||
    (family.input_status !== "ready" && family.status !== "WAITING") ||
    !maps.every((field) => isRecord(family[field])) ||
    !maps.every((field) => exactKeys(family[field], intervals)) ||
    !Array.isArray(family.required_intervals) ||
    family.required_intervals.length !== intervals.length ||
    !intervals.every((interval, index) => family.required_intervals[index] === interval) ||
    !Number.isSafeInteger(family.minimum_sessions_per_interval) ||
    family.minimum_sessions_per_interval <= 0 ||
    !Number.isSafeInteger(family.minimum_calendar_span_days) ||
    family.minimum_calendar_span_days <= 0 ||
    !Number.isSafeInteger(family.minimum_tickers_per_interval) ||
    family.minimum_tickers_per_interval <= 0 ||
    typeof family.minimum_session_coverage_fraction !== "number" ||
    !Number.isFinite(family.minimum_session_coverage_fraction) ||
    family.minimum_session_coverage_fraction <= 0 ||
    family.minimum_session_coverage_fraction > 1 ||
    family.session_schedule_source !== "pandas_market_calendars:NYSE" ||
    typeof family.usable_observation_rule !== "string" ||
    family.usable_observation_rule.trim().length === 0 ||
    typeof family.limitation !== "string" ||
    family.limitation.trim().length === 0
  ) {
    return false;
  }
  return intervals.every((interval) => {
    const observed = family.observed_sessions[interval];
    const qualifying = family.qualifying_sessions[interval];
    const first = family.first_date[interval];
    const last = family.last_date[interval];
    const qualifyingFirst = family.qualifying_first_date[interval];
    const qualifyingLast = family.qualifying_last_date[interval];
    return (
      isNonnegativeInteger(observed) &&
      isNonnegativeInteger(qualifying) &&
      qualifying <= observed &&
      isNonnegativeInteger(family.minimum_observed_names_per_session[interval]) &&
      (observed === 0) ===
        (family.minimum_observed_names_per_session[interval] === 0) &&
      isNonnegativeInteger(family.minimum_usable_names_per_session[interval]) &&
      family.minimum_usable_names_per_session[interval] <=
        family.minimum_observed_names_per_session[interval] &&
      isNonnegativeInteger(family.qualifying_calendar_span_days[interval]) &&
      validDateRange(observed, first, last) &&
      validDateRange(qualifying, qualifyingFirst, qualifyingLast) &&
      family.qualifying_calendar_span_days[interval] ===
        (qualifying === 0 ? 0 : calendarSpanDays(qualifyingFirst, qualifyingLast)) &&
      (qualifying === 0 || (qualifyingFirst >= first && qualifyingLast <= last)) &&
      (family.input_status === "ready" ||
        (observed === 0 &&
          qualifying === 0 &&
          family.minimum_observed_names_per_session[interval] === 0 &&
          family.minimum_usable_names_per_session[interval] === 0))
    );
  });
}
