// Pure contract for the research-data admission response.

import {
  hasExactResearchFields,
  INPUT_STATUS_FIELDS,
  validDatedCoverage,
  validExpectedInputStatus,
  validIntradayCoverage,
} from "./research-coverage-contracts.js";
import { isRecord } from "./response-contracts.js";

export function isResearchReadinessProjection(data) {
  if (
    !isRecord(data) ||
    !hasExactResearchFields(data, [
      "automatic_action",
      "families",
      "notice",
      "paper_only",
      "purpose",
      "ready_families",
      "schema_version",
    ]) ||
    data.schema_version !== 10 ||
    data.purpose !== "candidate_admission_only" ||
    data.paper_only !== true ||
    data.automatic_action !== "none" ||
    !Array.isArray(data.ready_families) ||
    typeof data.notice !== "string" ||
    data.notice.trim().length === 0 ||
    !isRecord(data.families)
  ) {
    return false;
  }
  const familyNames = ["stock_selection", "fundamentals", "intraday"];
  if (
    Object.keys(data.families).length !== familyNames.length ||
    !familyNames.every((name) => isRecord(data.families[name]))
  ) {
    return false;
  }
  const stock = data.families.stock_selection;
  const fundamentals = data.families.fundamentals;
  const validStatus = (family, requiredInputs) =>
    ["WAITING", "READY_FOR_CHARTER"].includes(family.status) &&
    validExpectedInputStatus(family, requiredInputs) &&
    (family.input_status === "ready" || family.status === "WAITING") &&
    typeof family.limitation === "string" &&
    family.limitation.trim().length > 0;
  const valid =
    hasExactResearchFields(stock, [
      ...INPUT_STATUS_FIELDS,
      "breadth_rule",
      "first_date",
      "last_date",
      "limitation",
      "minimum_calendar_span_days",
      "minimum_names_per_date",
      "minimum_observed_names_per_date",
      "minimum_shared_dates",
      "observed_shared_dates",
      "qualifying_calendar_span_days",
      "qualifying_first_date",
      "qualifying_last_date",
      "qualifying_shared_dates",
    ]) &&
    validStatus(stock, {
      universe_snapshot: ["snapshot_date", "ticker"],
      screen_results: ["run_date", "ticker"],
    }) &&
    stock.breadth_rule === "same_date_ticker_intersection" &&
    validDatedCoverage(stock, {
      observed: "observed_shared_dates",
      qualifying: "qualifying_shared_dates",
      observedBreadth: "minimum_observed_names_per_date",
      minimum: "minimum_shared_dates",
      minimumBreadth: "minimum_names_per_date",
    }) &&
    hasExactResearchFields(fundamentals, [
      ...INPUT_STATUS_FIELDS,
      "first_date",
      "last_date",
      "limitation",
      "minimum_calendar_span_days",
      "minimum_names_per_snapshot",
      "minimum_observed_names_per_snapshot",
      "minimum_snapshots",
      "numeric_rule",
      "observed_snapshots",
      "qualifying_calendar_span_days",
      "qualifying_first_date",
      "qualifying_last_date",
      "qualifying_snapshots",
      "usable_observation_rule",
    ]) &&
    validStatus(fundamentals, {
      fundamentals: [
        "ticker",
        "as_of",
        "quote_type",
        "market_cap",
        "trailing_pe",
        "price_to_book",
        "ev_to_ebitda",
      ],
    }) &&
    fundamentals.numeric_rule === "finite_positive_market_cap_and_finite_valuation" &&
    typeof fundamentals.usable_observation_rule === "string" &&
    fundamentals.usable_observation_rule.trim().length > 0 &&
    validDatedCoverage(fundamentals, {
      observed: "observed_snapshots",
      qualifying: "qualifying_snapshots",
      observedBreadth: "minimum_observed_names_per_snapshot",
      minimum: "minimum_snapshots",
      minimumBreadth: "minimum_names_per_snapshot",
    }) &&
    validIntradayCoverage(data.families.intraday);
  if (!valid) return false;
  const expectedStatuses = {
    stock_selection:
      stock.input_status === "ready" &&
      stock.qualifying_shared_dates >= stock.minimum_shared_dates &&
      stock.qualifying_calendar_span_days >= stock.minimum_calendar_span_days
        ? "READY_FOR_CHARTER"
        : "WAITING",
    fundamentals:
      fundamentals.input_status === "ready" &&
      fundamentals.qualifying_snapshots >= fundamentals.minimum_snapshots &&
      fundamentals.qualifying_calendar_span_days >= fundamentals.minimum_calendar_span_days
        ? "READY_FOR_CHARTER"
        : "WAITING",
    intraday: ["1m", "5m"].every(
      (interval) =>
        data.families.intraday.qualifying_sessions[interval] >=
          data.families.intraday.minimum_sessions_per_interval &&
        data.families.intraday.qualifying_calendar_span_days[interval] >=
          data.families.intraday.minimum_calendar_span_days,
    ) && data.families.intraday.input_status === "ready"
      ? "READY_FOR_CHARTER"
      : "WAITING",
  };
  if (
    !familyNames.every((name) => data.families[name].status === expectedStatuses[name])
  ) {
    return false;
  }
  const expectedReady = familyNames
    .filter((name) => data.families[name].status === "READY_FOR_CHARTER")
    .sort();
  return (
    data.ready_families.length === expectedReady.length &&
    data.ready_families.every((name, index) => name === expectedReady[index])
  );
}
