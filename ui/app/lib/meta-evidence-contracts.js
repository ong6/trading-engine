import {
  compareUnicodeCodePoints,
  isIsoDate,
  isIsoTimestamp,
  isNonEmptyString,
  isNonnegativeInteger,
  isPositiveInteger,
  isRecord,
} from "./response-contracts.js";
import {
  compareOffsetIsoTimestamps,
  hasExactFields,
  hasStatus,
  isNullable,
  isOffsetIsoTimestamp,
} from "./meta-contract-utils.js";

const NIGHTLY_EVIDENCE_STATUSES = new Set([
  "current",
  "failed",
  "interrupted",
  "invalid",
  "missing",
  "overdue",
  "stale",
  "stale-running",
  "unknown",
  "updating",
]);

const LIQUIDITY_EVIDENCE_STATUSES = new Set([
  "current",
  "failed",
  "interrupted",
  "invalid",
  "issues",
  "missing",
  "not-yet-run",
  "overdue",
  "stale",
  "stale-running",
  "unknown",
  "updating",
]);

const LIQUIDITY_EVIDENCE_REASONS = new Set([
  "candidate-download-failures",
  "candidate-and-backfill-failures",
  "backfill-failures",
  "driver-not-successful",
  "evidence-ahead-of-store",
  "evidence-missing",
  "evidence-postdates-latest-run",
  "evidence-predates-latest-run",
  "future-evidence",
  "malformed-evidence",
  "market-date-unavailable",
  "no-scheduled-run",
  "projection-error",
  "scheduled-market-date-mismatch",
  "store-count-mismatch",
]);

const LIQUIDITY_DRIVER_FAILURE_STATUSES = new Set([
  "failed",
  "interrupted",
  "overdue",
  "stale-running",
]);

const LIQUIDITY_RESULT_FIELDS = [
  "status",
  "reason",
  "as_of",
  "published_at",
  "admitted",
  "demoted",
  "kept_held",
  "liquid_before",
  "liquid_after",
  "candidates_pulled",
  "candidates_failed",
  "backfill_processed",
  "backfill_failed",
];

const MINER_EVIDENCE_STATUSES = new Set([
  "current",
  "failed",
  "incomplete",
  "invalid",
  "issues",
  "stale",
  "unknown",
  "updating",
]);

const SWEEP_EVIDENCE_STATUSES = new Set([
  "current",
  "failed",
  "idle",
  "incomplete",
  "invalid",
  "stale",
  "updating",
]);

const WALKFORWARD_EVIDENCE_STATUSES = new Set([
  "current",
  "incomplete",
  "invalid",
  "mixed-cohort",
  "stale-source",
  "updating",
]);

const MINER_CHILD_STATUSES = new Set([
  "current",
  "failed",
  "invalid",
  "issues",
  "missing",
  "pending",
  "queued",
  "running",
  "stale",
  "superseded",
  "unknown",
]);

const SWEEP_CHILD_STATUSES = new Set([
  "current",
  "failed",
  "invalid",
  "missing",
  "pending",
  "queued",
  "running",
  "stale",
  "superseded",
]);

const SWEEP_JOB_STATUSES = new Set([
  "failed",
  "pending",
  "queued",
  "running",
  "superseded",
]);

const SWEEP_IDENTITY_FIELDS = ["grid", "charter_version", "status"];
const SWEEP_JOB_FIELDS = [...SWEEP_IDENTITY_FIELDS, "job_id", "job_state", "job_updated_at"];

function isLiquidityResult(evidence) {
  if (!hasExactFields(evidence, LIQUIDITY_RESULT_FIELDS)) return false;
  const candidateFailures = evidence.candidates_failed > 0;
  const backfillFailures = evidence.backfill_failed > 0;
  const expectedReason = candidateFailures
    ? backfillFailures
      ? "candidate-and-backfill-failures"
      : "candidate-download-failures"
    : backfillFailures
      ? "backfill-failures"
      : null;
  return (
    evidence.status === (expectedReason === null ? "current" : "issues") &&
    evidence.reason === expectedReason &&
    isIsoDate(evidence.as_of) &&
    isOffsetIsoTimestamp(evidence.published_at) &&
    [
      evidence.admitted,
      evidence.demoted,
      evidence.kept_held,
      evidence.liquid_before,
      evidence.liquid_after,
      evidence.candidates_pulled,
      evidence.candidates_failed,
      evidence.backfill_processed,
      evidence.backfill_failed,
    ].every(isNonnegativeInteger) &&
    Number.isSafeInteger(
      evidence.liquid_before + evidence.admitted - evidence.demoted,
    ) &&
    evidence.liquid_before + evidence.admitted - evidence.demoted ===
      evidence.liquid_after &&
    evidence.candidates_failed <= evidence.candidates_pulled &&
    evidence.backfill_failed <= evidence.backfill_processed
  );
}

function isLiquidityEvidence(evidence) {
  if (
    !isRecord(evidence) ||
    !LIQUIDITY_EVIDENCE_STATUSES.has(evidence.status) ||
    (Object.prototype.hasOwnProperty.call(evidence, "reason") &&
      evidence.reason !== null &&
      !LIQUIDITY_EVIDENCE_REASONS.has(evidence.reason))
  ) {
    return false;
  }
  if (["current", "issues"].includes(evidence.status)) {
    return isLiquidityResult(evidence);
  }
  if (evidence.status === "not-yet-run") {
    return (
      hasExactFields(evidence, ["status", "reason"]) &&
      evidence.reason === "no-scheduled-run"
    );
  }
  if (evidence.status === "updating") {
    return hasExactFields(evidence, ["status"]);
  }
  if (LIQUIDITY_DRIVER_FAILURE_STATUSES.has(evidence.status)) {
    return (
      hasExactFields(evidence, ["status", "reason"]) &&
      evidence.reason === "driver-not-successful"
    );
  }
  if (evidence.status === "missing") {
    return (
      hasExactFields(evidence, ["status", "reason"]) &&
      evidence.reason === "evidence-missing"
    );
  }
  if (evidence.status === "unknown") {
    return (
      hasExactFields(evidence, ["status", "reason"]) &&
      evidence.reason === "market-date-unavailable"
    );
  }
  if (evidence.status === "stale" && evidence.reason === "store-count-mismatch") {
    return (
      hasExactFields(evidence, [
        "status",
        "reason",
        "published_at",
        "liquid_after",
        "store_liquid",
      ]) &&
      isOffsetIsoTimestamp(evidence.published_at) &&
      isNonnegativeInteger(evidence.liquid_after) &&
      isNonnegativeInteger(evidence.store_liquid) &&
      evidence.liquid_after !== evidence.store_liquid
    );
  }
  if (evidence.status === "stale" && evidence.reason === "evidence-predates-latest-run") {
    return (
      hasExactFields(evidence, ["status", "reason", "published_at"]) &&
      isOffsetIsoTimestamp(evidence.published_at)
    );
  }
  if (
    ["stale", "invalid"].includes(evidence.status) &&
    evidence.reason === "scheduled-market-date-mismatch"
  ) {
    return (
      hasExactFields(evidence, [
        "status",
        "reason",
        "as_of",
        "expected_as_of",
        "latest_date",
      ]) &&
      isIsoDate(evidence.as_of) &&
      isIsoDate(evidence.expected_as_of) &&
      isIsoDate(evidence.latest_date) &&
      (evidence.status === "stale"
        ? evidence.as_of < evidence.expected_as_of
        : evidence.as_of > evidence.expected_as_of)
    );
  }
  if (evidence.status === "invalid" && evidence.reason === "evidence-ahead-of-store") {
    return (
      hasExactFields(evidence, ["status", "reason", "as_of", "latest_date"]) &&
      isIsoDate(evidence.as_of) &&
      isIsoDate(evidence.latest_date) &&
      evidence.as_of > evidence.latest_date
    );
  }
  if (evidence.status === "invalid") {
    return (
      (hasExactFields(evidence, ["status", "reason"]) &&
        [
          "driver-not-successful",
          "future-evidence",
          "malformed-evidence",
          "projection-error",
        ].includes(evidence.reason)) ||
      (evidence.reason === "evidence-postdates-latest-run" &&
        hasExactFields(evidence, [
          "status",
          "reason",
          "published_at",
          "finished_at",
        ]) &&
        isOffsetIsoTimestamp(evidence.published_at) &&
        isOffsetIsoTimestamp(evidence.finished_at) &&
        compareOffsetIsoTimestamps(evidence.published_at, evidence.finished_at) > 0 &&
        Date.parse(evidence.published_at) - Date.parse(evidence.finished_at) >= 1000)
    );
  }
  return false;
}

function hasSweepIdentity(charter) {
  return (
    isNonEmptyString(charter.grid) &&
    isNonEmptyString(charter.charter_version) &&
    SWEEP_CHILD_STATUSES.has(charter.status)
  );
}

function hasSweepJob(charter) {
  return (
    hasSweepIdentity(charter) &&
    isPositiveInteger(charter.job_id) &&
    [...SWEEP_JOB_STATUSES, "done"].includes(charter.job_state) &&
    isNullable(charter.job_updated_at, isIsoTimestamp)
  );
}

function isSweepCharter(charter) {
  if (!isRecord(charter) || !hasSweepIdentity(charter)) return false;
  if (charter.status === "missing") {
    return (
      hasExactFields(charter, [...SWEEP_IDENTITY_FIELDS, "reason"]) &&
      charter.reason === "job-missing"
    );
  }
  if (!hasSweepJob(charter)) return false;
  if (SWEEP_JOB_STATUSES.has(charter.status)) {
    return (
      hasExactFields(charter, [...SWEEP_JOB_FIELDS, "reason"]) &&
      charter.status === charter.job_state &&
      charter.reason === "latest-job-not-done"
    );
  }
  if (charter.job_state !== "done") return false;
  if (charter.status === "current") {
    return (
      hasExactFields(charter, [...SWEEP_JOB_FIELDS, "generated_at", "n_trials"]) &&
      isOffsetIsoTimestamp(charter.generated_at) &&
      isPositiveInteger(charter.n_trials)
    );
  }
  if (charter.status === "stale") {
    return (
      hasExactFields(charter, [
        ...SWEEP_JOB_FIELDS,
        "generated_at",
        "n_trials",
        "reason",
      ]) &&
      isOffsetIsoTimestamp(charter.generated_at) &&
      isPositiveInteger(charter.n_trials) &&
      charter.reason === "ranking-predates-latest-job"
    );
  }
  return (
    charter.status === "invalid" &&
    hasExactFields(charter, [...SWEEP_JOB_FIELDS, "reason"]) &&
    ["incoherent-done-job", "ranking-invalid"].includes(charter.reason)
  );
}

function derivedAggregateStatus(statuses, { unknown = false } = {}) {
  const observed = new Set(statuses);
  if (observed.size === 1 && observed.has("current")) return "current";
  if (unknown && observed.size === 1 && observed.has("unknown")) return "unknown";
  for (const status of ["invalid", "failed"]) {
    if (observed.has(status)) return status;
  }
  if (["pending", "queued", "running"].some((status) => observed.has(status))) {
    return "updating";
  }
  for (const status of ["issues", "stale"]) {
    if (observed.has(status)) return status;
  }
  return "incomplete";
}

function isMinerEvidence(evidence) {
  if (!hasStatus(evidence, MINER_EVIDENCE_STATUSES)) return false;
  const hasCurrent = Object.prototype.hasOwnProperty.call(evidence, "current");
  const hasExpected = Object.prototype.hasOwnProperty.call(evidence, "expected");
  if (hasCurrent !== hasExpected) return false;
  if (!hasCurrent) return evidence.status === "invalid";
  if (!isRecord(evidence.miners)) return false;
  const minerStatuses = Object.values(evidence.miners);
  return (
    isNonnegativeInteger(evidence.current) &&
    isPositiveInteger(evidence.expected) &&
    evidence.current <= evidence.expected &&
    minerStatuses.length === evidence.expected &&
    minerStatuses.every(
      (miner) => isRecord(miner) && MINER_CHILD_STATUSES.has(miner.status),
    ) &&
    minerStatuses.filter((miner) => miner.status === "current").length === evidence.current &&
    evidence.status ===
      derivedAggregateStatus(
        minerStatuses.map((miner) => miner.status),
        { unknown: true },
      )
  );
}

function isSweepEvidence(evidence) {
  if (!hasStatus(evidence, SWEEP_EVIDENCE_STATUSES)) return false;
  const hasCurrent = Object.prototype.hasOwnProperty.call(evidence, "current_charters");
  const hasOpen = Object.prototype.hasOwnProperty.call(evidence, "open_charters");
  const hasCharters = Object.prototype.hasOwnProperty.call(evidence, "charters");
  if (hasCurrent !== hasOpen || hasCurrent !== hasCharters) return false;
  if (!hasCurrent) {
    return (
      evidence.status === "invalid" &&
      evidence.reason === "projection-error" &&
      hasExactFields(evidence, ["status", "reason"])
    );
  }
  if (
    !Array.isArray(evidence.charters) ||
    !evidence.charters.every(isSweepCharter)
  ) {
    return false;
  }
  const charterStatuses = evidence.charters.map((charter) => charter.status);
  const derivedStatus =
    charterStatuses.length === 0
      ? evidence.status === "invalid"
        ? "invalid"
        : "idle"
      : derivedAggregateStatus(charterStatuses);
  const expectedReason =
    charterStatuses.length === 0
      ? evidence.status === "idle"
        ? "no-open-recurring-charters"
        : "recurring-allowlist-invalid"
      : null;
  const hasReason = Object.prototype.hasOwnProperty.call(evidence, "reason");
  if (
    !hasExactFields(
      evidence,
      ["status", "current_charters", "open_charters", "charters"],
      expectedReason === null && !charterStatuses.every((status) => status === "missing")
        ? []
        : ["reason"],
    ) ||
    (expectedReason !== null && evidence.reason !== expectedReason) ||
    (expectedReason === null && hasReason && evidence.reason !== "jobs-table-missing")
  ) {
    return false;
  }
  return (
    isNonnegativeInteger(evidence.current_charters) &&
    isNonnegativeInteger(evidence.open_charters) &&
    evidence.current_charters <= evidence.open_charters &&
    evidence.charters.length === evidence.open_charters &&
    evidence.charters.filter((charter) => charter?.status === "current").length ===
      evidence.current_charters &&
    evidence.status === derivedStatus
  );
}

const WALKFORWARD_DIAGNOSTIC_FIELDS = [
  "missing_results",
  "invalid_files",
  "config_mismatches",
  "registration_mismatches",
  "duplicate_config_ids",
  "invalid_registrations",
];

function isOrderedDiagnostic(values, valuesTruncated) {
  for (let index = 1; index < values.length; index += 1) {
    const comparison = compareUnicodeCodePoints(values[index - 1], values[index]);
    if (comparison > 0 || (!valuesTruncated && comparison === 0)) return false;
  }
  return true;
}

function isWalkforwardEvidence(evidence) {
  if (!hasStatus(evidence, WALKFORWARD_EVIDENCE_STATUSES)) return false;
  if (!Object.prototype.hasOwnProperty.call(evidence, "expected_results")) {
    return evidence.status === "invalid" && evidence.reason === "projection-error";
  }
  if (
    !isNonnegativeInteger(evidence.expected_results) ||
    !isNonnegativeInteger(evidence.available_results) ||
    evidence.available_results > evidence.expected_results ||
    !isNonnegativeInteger(evidence.cohort_signature_count) ||
    !isPositiveInteger(evidence.diagnostic_list_limit) ||
    !isPositiveInteger(evidence.diagnostic_value_max_chars)
  ) {
    return false;
  }
  for (const field of WALKFORWARD_DIAGNOSTIC_FIELDS) {
    const values = evidence[field];
    const count = evidence[`${field}_count`];
    const truncated = evidence[`${field}_truncated`];
    const valuesTruncated = evidence[`${field}_values_truncated`];
    if (
      !Array.isArray(values) ||
      !isNonnegativeInteger(count) ||
      values.length !== Math.min(count, evidence.diagnostic_list_limit) ||
      truncated !== (count > values.length) ||
      typeof valuesTruncated !== "boolean" ||
      values.some(
        (value) =>
          !isNonEmptyString(value) ||
          Array.from(value).length > evidence.diagnostic_value_max_chars,
      ) ||
      (valuesTruncated &&
        !values.some(
          (value) => Array.from(value).length === evidence.diagnostic_value_max_chars,
        )) ||
      !isOrderedDiagnostic(values, valuesTruncated)
    ) {
      return false;
    }
  }
  return (
    evidence.missing_results_count ===
    evidence.expected_results - evidence.available_results
  );
}

export function isMetaEvidence(data) {
  return (
    hasStatus(data.nightly_evidence, NIGHTLY_EVIDENCE_STATUSES) &&
    isMinerEvidence(data.miner_evidence) &&
    isSweepEvidence(data.sweep_evidence) &&
    isLiquidityEvidence(data.liquidity_evidence) &&
    isWalkforwardEvidence(data["walkforward_evidence"])
  );
}
