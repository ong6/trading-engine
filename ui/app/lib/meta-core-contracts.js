import {
  isBoundedCollection,
  isIsoDate,
  isIsoTimestamp,
  isNonEmptyString,
  isNonnegativeInteger,
  isRecord,
} from "./response-contracts.js";
import { isCandidateTicker } from "./candidate-route.js";
import {
  compareOffsetIsoTimestamps,
  hasExactFields,
  hasOptional,
  isNullable,
  isOffsetIsoTimestamp,
} from "./meta-contract-utils.js";

const META_SUMMARY_FIELDS = new Set(["regime", "last_run", "last_screen", "screen_date"]);
const PRICE_VERIFICATION_FIELDS = [
  "status",
  "as_of",
  "verified_at",
  "names_selected",
  "names_checked",
  "names_agreeing",
  "names_disagreeing",
  "names_not_checked",
  "n_disagreements",
  "n_material",
  "n_parse_errors",
  "tolerance_bp",
  "tolerance_abs_usd",
  "material_bp",
  "disagreements",
  "disagreements_limit",
  "disagreements_matching_count",
  "disagreements_truncated",
];
const PRICE_DISAGREEMENT_LIMIT = 20;
const PRICE_DIFF_BP_ROUNDING_TOLERANCE = 0.005001;
const PRICE_FIELDS = new Set(["open", "high", "low", "close"]);

function hasExactReason(evidence, status, reason) {
  return evidence.status === status && evidence.reason === reason;
}

function priceVerificationStatusMatches(evidence, latestPricesDate, nightly) {
  // Only the server can compare against its exact request-time clock.
  if (hasExactReason(evidence, "invalid", "future-verification")) return true;
  if (latestPricesDate === null) {
    return hasExactReason(evidence, "unknown", "market-date-unavailable");
  }
  if (evidence.as_of > latestPricesDate) {
    return hasExactReason(evidence, "invalid", "future-market-date");
  }
  if (evidence.as_of < latestPricesDate) {
    return hasExactReason(evidence, "stale", "market-date-behind");
  }
  if (
    isRecord(nightly) &&
    nightly.status === "ok" &&
    isOffsetIsoTimestamp(nightly.started_at) &&
    compareOffsetIsoTimestamps(evidence.verified_at, nightly.started_at) === -1
  ) {
    return hasExactReason(evidence, "stale", "not-refreshed-by-latest-nightly");
  }
  if (evidence.names_checked === 0) {
    return hasExactReason(evidence, "incomplete", "no-names-checked");
  }
  if (evidence.n_disagreements > 0 || evidence.n_parse_errors > 0) {
    return hasExactReason(evidence, "issues", "disagreements-or-parse-errors");
  }
  if (evidence.names_not_checked > 0) {
    return hasExactReason(evidence, "partial", "selected-names-not-checked");
  }
  return evidence.status === "current" && !Object.hasOwn(evidence, "reason");
}

function isMetaSummary(meta) {
  return (
    isRecord(meta) &&
    Object.keys(meta).every((field) => META_SUMMARY_FIELDS.has(field)) &&
    hasOptional(meta, "regime", (value) => ["risk-on", "risk-off"].includes(value)) &&
    hasOptional(meta, "last_run", (value) => isNullable(value, isOffsetIsoTimestamp)) &&
    hasOptional(meta, "last_screen", (value) => isNullable(value, isOffsetIsoTimestamp)) &&
    hasOptional(meta, "screen_date", (value) => isNullable(value, isIsoDate))
  );
}

function isMetaFile(metaFile) {
  if (!isRecord(metaFile) || !["ok", "missing", "invalid"].includes(metaFile.status)) {
    return false;
  }
  const fields = Object.keys(metaFile).sort().join(",");
  if (metaFile.status !== "invalid") {
    return fields === "status";
  }
  return (
    fields === "reason,status" &&
    ["malformed", "malformed-summary", "not-regular", "unreadable-or-malformed"].includes(
      metaFile.reason,
    )
  );
}

function isMarketFreshness(market) {
  if (
    !isRecord(market) ||
    !hasExactFields(market, [
      "status",
      "as_of",
      "latest_date",
      "calendar_days",
      "missing_completed_sessions",
      "first_missing_session",
      "last_missing_session",
      "next_session",
    ]) ||
    !["future", "ok", "stale", "unknown"].includes(market.status) ||
    !isIsoDate(market.as_of) ||
    !isNullable(market.latest_date, isIsoDate) ||
    !(market.calendar_days === null || Number.isSafeInteger(market.calendar_days)) ||
    !isNullable(market.first_missing_session, isIsoDate) ||
    !isNullable(market.last_missing_session, isIsoDate) ||
    !isNullable(market.next_session, isIsoDate) ||
    !isNullable(market.missing_completed_sessions, isNonnegativeInteger)
  ) {
    return false;
  }
  const missing = market.missing_completed_sessions;
  return (
    (market.status === "unknown" &&
      market.latest_date === null &&
      market.calendar_days === null &&
      missing === null &&
      market.first_missing_session === null &&
      market.last_missing_session === null &&
      market.next_session === null) ||
    (market.status === "stale" &&
      market.latest_date !== null &&
      market.calendar_days >= 0 &&
      missing > 0 &&
      market.first_missing_session !== null &&
      market.last_missing_session !== null &&
      market.first_missing_session <= market.last_missing_session &&
      market.next_session !== null) ||
    (market.status === "future" &&
      market.latest_date !== null &&
      market.latest_date > market.as_of &&
      market.calendar_days < 0 &&
      missing === 0 &&
      market.first_missing_session === null &&
      market.last_missing_session === null &&
      market.next_session === null) ||
    (market.status === "ok" &&
      market.latest_date !== null &&
      market.latest_date <= market.as_of &&
      market.calendar_days >= 0 &&
      missing === 0 &&
      market.first_missing_session === null &&
      market.last_missing_session === null &&
      market.next_session !== null)
  );
}

function isPriceVerification(evidence, latestPricesDate, nightly) {
  if (
    !isRecord(evidence) ||
    !new Set([
      "current",
      "incomplete",
      "invalid",
      "issues",
      "missing",
      "partial",
      "stale",
      "unknown",
    ]).has(evidence.status)
  ) {
    return false;
  }
  const hasSelected = Object.prototype.hasOwnProperty.call(evidence, "names_selected");
  const hasChecked = Object.prototype.hasOwnProperty.call(evidence, "names_checked");
  if (hasSelected !== hasChecked) return false;
  if (!hasSelected) {
    return evidence.status === "missing"
      ? hasExactFields(evidence, ["status"])
      : evidence.status === "invalid" &&
          hasExactFields(evidence, ["status", "reason"]) &&
          ["malformed-evidence", "not-an-object"].includes(evidence.reason);
  }
  if (
    !hasExactFields(evidence, PRICE_VERIFICATION_FIELDS, ["reason"]) ||
    !hasOptional(evidence, "reason", isNonEmptyString) ||
    !isIsoDate(evidence.as_of) ||
    !isOffsetIsoTimestamp(evidence.verified_at) ||
    !Number.isFinite(evidence.tolerance_bp) ||
    evidence.tolerance_bp <= 0 ||
    !Number.isFinite(evidence.tolerance_abs_usd) ||
    evidence.tolerance_abs_usd <= 0 ||
    !Number.isFinite(evidence.material_bp) ||
    evidence.material_bp < evidence.tolerance_bp ||
    !isBoundedCollection(
      evidence,
      "disagreements",
      "disagreements_limit",
      "disagreements_matching_count",
      "disagreements_truncated",
    ) ||
    evidence.disagreements_limit !== PRICE_DISAGREEMENT_LIMIT
  ) {
    return false;
  }
  const countFields = [
    "names_selected",
    "names_checked",
    "names_agreeing",
    "names_disagreeing",
    "names_not_checked",
    "n_disagreements",
    "n_material",
    "n_parse_errors",
  ];
  if (
    !countFields.every((field) => isNonnegativeInteger(evidence[field])) ||
    evidence.names_checked + evidence.names_not_checked !== evidence.names_selected ||
    evidence.names_agreeing + evidence.names_disagreeing !== evidence.names_checked ||
    evidence.n_material > evidence.n_disagreements ||
    evidence.names_disagreeing > evidence.n_disagreements ||
    evidence.disagreements_matching_count !== evidence.n_disagreements
  ) {
    return false;
  }
  const identities = new Set();
  const tickers = new Set();
  let previousDiff = null;
  let listedMaterial = 0;
  const detailsValid = evidence.disagreements.every((item) => {
    if (
      !hasExactFields(item, ["ticker", "date", "field", "store", "source", "diff_bp"]) ||
      !isCandidateTicker(item.ticker) ||
      !isIsoDate(item.date) ||
      item.date > evidence.as_of ||
      !PRICE_FIELDS.has(item.field) ||
      !Number.isFinite(item.store) ||
      item.store <= 0 ||
      !Number.isFinite(item.source) ||
      item.source <= 0 ||
      !Number.isFinite(item.diff_bp) ||
      item.diff_bp < 0 ||
      Math.abs(
        item.diff_bp -
          (Math.abs(item.store - item.source) / Math.max(item.store, item.source)) * 10000,
      ) > PRICE_DIFF_BP_ROUNDING_TOLERANCE ||
      item.diff_bp <= evidence.tolerance_bp ||
      Math.abs(item.store - item.source) < evidence.tolerance_abs_usd ||
      (previousDiff !== null && item.diff_bp > previousDiff)
    ) {
      return false;
    }
    const identity = `${item.ticker}\u0000${item.date}\u0000${item.field}`;
    if (identities.has(identity)) return false;
    identities.add(identity);
    tickers.add(item.ticker);
    previousDiff = item.diff_bp;
    if (item.diff_bp > evidence.material_bp) listedMaterial += 1;
    return true;
  });
  return (
    detailsValid &&
    tickers.size <= evidence.names_disagreeing &&
    (evidence.n_disagreements > PRICE_DISAGREEMENT_LIMIT ||
      tickers.size === evidence.names_disagreeing) &&
    listedMaterial === Math.min(evidence.n_material, PRICE_DISAGREEMENT_LIMIT) &&
    priceVerificationStatusMatches(evidence, latestPricesDate, nightly)
  );
}

function isPriceQuarantines(data) {
  if (
    !isBoundedCollection(
      data,
      "price_quarantines",
      "price_quarantines_limit",
      "price_quarantines_matching_count",
      "price_quarantines_truncated",
    )
  ) {
    return false;
  }
  const tickers = new Set();
  let previousTicker = null;
  return data.price_quarantines.every((row) => {
    const reasonLength = typeof row?.reason === "string" ? [...row.reason].length : null;
    const evidenceLength = typeof row?.evidence === "string" ? [...row.evidence].length : null;
    const valid =
      hasExactFields(row, [
        "ticker",
        "reason",
        "evidence",
        "confirmed_at",
        "detail_truncated",
      ]) &&
      isCandidateTicker(row.ticker) &&
      !tickers.has(row.ticker) &&
      isNonEmptyString(row.reason) &&
      reasonLength <= 1024 &&
      isNonEmptyString(row.evidence) &&
      evidenceLength <= 1024 &&
      isIsoTimestamp(row.confirmed_at) &&
      typeof row.detail_truncated === "boolean" &&
      (!row.detail_truncated || reasonLength === 1024 || evidenceLength === 1024) &&
      (previousTicker === null || row.ticker > previousTicker);
    tickers.add(row?.ticker);
    previousTicker = row?.ticker;
    return valid;
  });
}

export function isMetaCore(data) {
  return (
    isRecord(data) &&
    isMetaSummary(data.meta) &&
    isMetaFile(data.meta_file) &&
    (data.latest_prices_date === null || isIsoDate(data.latest_prices_date)) &&
    (data.freshness_days === null || Number.isSafeInteger(data.freshness_days)) &&
    isPriceQuarantines(data) &&
    isMarketFreshness(data.market_freshness) &&
    data.latest_prices_date === data.market_freshness.latest_date &&
    data.freshness_days === data.market_freshness.calendar_days &&
    isPriceVerification(data.price_verification, data.latest_prices_date, data.nightly)
  );
}
