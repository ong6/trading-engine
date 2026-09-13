import {
  isNonEmptyString,
  isNonnegativeInteger,
  isPositiveInteger,
  isIsoTimestamp,
  isRecord,
} from "./response-contracts.js";
import {
  hasExactFields,
  hasOptional,
  isNullable,
  isOffsetIsoTimestamp,
} from "./meta-contract-utils.js";

const DRIVER_STATUSES = new Set([
  "failed",
  "interrupted",
  "invalid",
  "ok",
  "overdue",
  "running",
  "stale-running",
]);

const WALKFORWARD_DRIVER_STATUSES = new Set([
  ...DRIVER_STATUSES,
  "recovered",
  "updating",
]);

const DRIVER_FIELDS = new Set([
  "status",
  "name",
  "started_at",
  "finished_at",
  "exit_code",
  "stage",
  "reason",
  "lock_held",
  "expected_at",
  "expected_name",
  "previous_status",
  "refresh_job_count",
  "refresh_job_counts",
  "refresh_started_at",
  "refreshed_at",
  "recovery_job_count",
  "recovery_job_counts",
  "recovery_started_at",
  "recovered_at",
]);
const DRIVER_RECOVERY_FIELDS = [
  "refresh_job_count",
  "refresh_job_counts",
  "refresh_started_at",
  "refreshed_at",
  "recovery_job_count",
  "recovery_job_counts",
  "recovery_started_at",
  "recovered_at",
];

const SPARSE_INVALID_DRIVER_REASONS = new Set([
  "log-changed-during-read",
  "log-not-regular",
  "log-unreadable",
  "malformed-start-marker",
  "missing-start-marker",
]);

const TERMINAL_INVALID_DRIVER_REASONS = new Set([
  "finished-before-start",
  "future-finished-at",
  "invalid-finished-at",
  "terminal-name-mismatch",
]);

const RUN_MARKER_INVALID_DRIVER_REASONS = new Set([
  "malformed-terminal-marker",
  "multiple-terminal-markers",
]);

const QUEUE_STATES = new Set([
  "done",
  "failed",
  "pending",
  "queued",
  "running",
  "superseded",
]);
const QUEUE_FAILURE_LIMIT = 100;

const QUEUE_FIELDS = new Set([
  "counts",
  "actionable_failure_count",
  "actionable_failures",
  "actionable_failures_limit",
  "actionable_failures_truncated",
  "historical_failure_count",
  "historical_failures",
  "historical_failures_limit",
  "historical_failures_truncated",
  "latest_research_job",
]);

function isQueueFailure(failure, classification) {
  const expectedFields = ["id", "kind", "updated_at"];
  if (classification === "historical") expectedFields.push("classification");
  return (
    isRecord(failure) &&
    Object.keys(failure).sort().join(",") === expectedFields.sort().join(",") &&
    isPositiveInteger(failure.id) &&
    isNonEmptyString(failure.kind) &&
    [...failure.kind].length <= 64 &&
    isQueueTimestamp(failure.updated_at) &&
    (classification === "historical"
      ? failure.classification === "recurring sweep charter is closed"
      : !Object.prototype.hasOwnProperty.call(failure, "classification"))
  );
}

function isQueueTimestamp(value) {
  return (
    value === null ||
    (isOffsetIsoTimestamp(value) &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?\+00:00$/.test(value))
  );
}

function queueFailureFollows(previous, current) {
  if (previous.updated_at === null) {
    return current.updated_at === null && current.id < previous.id;
  }
  if (current.updated_at === null) return true;
  if (current.updated_at !== previous.updated_at) {
    return current.updated_at < previous.updated_at;
  }
  return current.id < previous.id;
}

function isLatestResearchJob(job) {
  return (
    job === null ||
    (isRecord(job) &&
      Object.keys(job).sort().join(",") === "id,kind,state,updated_at" &&
      isPositiveInteger(job.id) &&
      ["walkforward", "sweep", "backtest"].includes(job.kind) &&
      ["queued", "pending", "running", "done", "failed", "superseded"].includes(job.state) &&
      isQueueTimestamp(job.updated_at))
  );
}

function isQueue(queue) {
  if (
    !isRecord(queue) ||
    Object.keys(queue).length !== QUEUE_FIELDS.size ||
    !Object.keys(queue).every((field) => QUEUE_FIELDS.has(field)) ||
    !isRecord(queue.counts) ||
    !Object.entries(queue.counts).every(
      ([state, count]) => QUEUE_STATES.has(state) && isNonnegativeInteger(count),
    )
  ) {
    return false;
  }
  const failureIds = new Set();
  for (const prefix of ["actionable", "historical"]) {
    const count = queue[`${prefix}_failure_count`];
    const failures = queue[`${prefix}_failures`];
    const limit = queue[`${prefix}_failures_limit`];
    const truncated = queue[`${prefix}_failures_truncated`];
    if (
      !isNonnegativeInteger(count) ||
      !Array.isArray(failures) ||
      !failures.every((failure, index) => {
        const valid =
          isQueueFailure(failure, prefix) &&
          !failureIds.has(failure.id) &&
          (index === 0 || queueFailureFollows(failures[index - 1], failure));
        if (valid) failureIds.add(failure.id);
        return valid;
      }) ||
      limit !== QUEUE_FAILURE_LIMIT ||
      typeof truncated !== "boolean" ||
      failures.length !== Math.min(count, limit) ||
      truncated !== (count > failures.length)
    ) {
      return false;
    }
  }
  return (
    (queue.counts.failed || 0) ===
      queue.actionable_failure_count + queue.historical_failure_count &&
    isLatestResearchJob(queue.latest_research_job)
  );
}

function hasOwn(value, field) {
  return Object.prototype.hasOwnProperty.call(value, field);
}

function isDriverUtcTimestamp(value) {
  return isIsoTimestamp(value) && value.endsWith("Z") && !value.includes(".");
}

function hasDriverIdentity(driver, { finished = false } = {}) {
  return (
    isNonEmptyString(driver.name) &&
    isDriverUtcTimestamp(driver.started_at) &&
    (!finished ||
      (isDriverUtcTimestamp(driver.finished_at) &&
        Date.parse(driver.started_at) <= Date.parse(driver.finished_at)))
  );
}

function hasNoFields(driver, fields) {
  return fields.every((field) => !hasOwn(driver, field));
}

function hasTerminalMetadata(driver, { exitRequired = false } = {}) {
  const hasExit = hasOwn(driver, "exit_code");
  const hasStage = hasOwn(driver, "stage");
  return (
    (!exitRequired || hasExit) &&
    (!hasExit || isNonnegativeInteger(driver.exit_code)) &&
    (!hasStage || (hasExit && isNonEmptyString(driver.stage)))
  );
}

function hasOrderedDriverTimestamps(driver) {
  return (
    isDriverUtcTimestamp(driver.started_at) &&
    isDriverUtcTimestamp(driver.finished_at) &&
    Date.parse(driver.started_at) <= Date.parse(driver.finished_at)
  );
}

function isInvalidDriverState(driver) {
  if (SPARSE_INVALID_DRIVER_REASONS.has(driver.reason)) {
    return hasExactFields(driver, ["status", "reason"]);
  }
  if (driver.reason === "invalid-started-at") {
    return (
      hasExactFields(driver, ["status", "reason", "name", "started_at"]) &&
      isNonEmptyString(driver.name) &&
      isNonEmptyString(driver.started_at) &&
      !isDriverUtcTimestamp(driver.started_at)
    );
  }
  if (driver.reason === "future-started-at") {
    return (
      hasExactFields(driver, ["status", "reason", "name", "started_at"]) &&
      hasDriverIdentity(driver)
    );
  }
  if (RUN_MARKER_INVALID_DRIVER_REASONS.has(driver.reason)) {
    return (
      hasExactFields(driver, ["status", "reason", "name", "started_at"]) &&
      hasDriverIdentity(driver)
    );
  }
  if (TERMINAL_INVALID_DRIVER_REASONS.has(driver.reason)) {
    return (
      hasExactFields(
        driver,
        ["status", "reason", "name", "started_at", "finished_at"],
        ["exit_code", "stage"],
      ) &&
      isNonEmptyString(driver.name) &&
      isDriverUtcTimestamp(driver.started_at) &&
      (driver.reason === "invalid-finished-at"
        ? isNonEmptyString(driver.finished_at) &&
          !isDriverUtcTimestamp(driver.finished_at)
        : isDriverUtcTimestamp(driver.finished_at)) &&
      hasTerminalMetadata(driver, {
        exitRequired: driver.reason === "terminal-name-mismatch",
      }) &&
      (driver.reason !== "finished-before-start" ||
        Date.parse(driver.finished_at) < Date.parse(driver.started_at)) &&
      (driver.reason !== "future-finished-at" ||
        Date.parse(driver.started_at) <= Date.parse(driver.finished_at))
    );
  }
  if (driver.reason === "driver-name-mismatch") {
    return (
      hasExactFields(
        driver,
        ["status", "reason", "name", "expected_name"],
        ["started_at", "finished_at", "exit_code", "stage", "lock_held"],
      ) &&
      driver.name !== driver.expected_name &&
      isDriverUtcTimestamp(driver.started_at) &&
      (!hasOwn(driver, "finished_at") ||
        hasOrderedDriverTimestamps(driver)) &&
      (!hasOwn(driver, "exit_code") || hasOwn(driver, "finished_at")) &&
      (!hasOwn(driver, "lock_held") || typeof driver.lock_held === "boolean") &&
      (!hasOwn(driver, "lock_held") || !hasOwn(driver, "finished_at")) &&
      hasTerminalMetadata(driver)
    );
  }
  return false;
}

function hasOverduePriorState(driver) {
  const prior = driver.previous_status;
  const hasStarted = hasOwn(driver, "started_at");
  const hasFinished = hasOwn(driver, "finished_at");
  const hasExit = hasOwn(driver, "exit_code");
  const hasStage = hasOwn(driver, "stage");
  const hasLock = hasOwn(driver, "lock_held");
  if (prior === "missing") {
    return !hasStarted && !hasFinished && !hasExit && !hasStage && !hasLock;
  }
  if (!hasStarted || !isDriverUtcTimestamp(driver.started_at)) return false;
  if (prior === "ok") {
    return hasFinished && hasOrderedDriverTimestamps(driver) && !hasExit && !hasStage && !hasLock;
  }
  if (prior === "failed") {
    return (
      hasFinished &&
      hasOrderedDriverTimestamps(driver) &&
      hasExit &&
      hasTerminalMetadata(driver, { exitRequired: true }) &&
      !hasLock
    );
  }
  if (["interrupted", "running"].includes(prior)) {
    return (
      !hasFinished &&
      !hasExit &&
      !hasStage &&
      (!hasLock || driver.lock_held === (prior === "running"))
    );
  }
  if (prior === "overdue" && hasOwn(driver, "refresh_job_count")) {
    return hasFinished
      ? hasOrderedDriverTimestamps(driver) && hasTerminalMetadata(driver) && !hasLock
      : !hasExit && !hasStage;
  }
  return false;
}

function isBaseDriverState(driver) {
  const hasReason = hasOwn(driver, "reason");
  const hasExpected = hasOwn(driver, "expected_at");
  const hasFinished = hasOwn(driver, "finished_at");
  const hasExit = hasOwn(driver, "exit_code");
  const hasStage = hasOwn(driver, "stage");
  if (hasStage && !hasExit) return false;
  if (hasExit && !hasFinished) return false;

  if (driver.status === "ok") {
    return (
      hasDriverIdentity(driver, { finished: true }) &&
      !hasReason &&
      !hasExpected &&
      !hasExit &&
      hasNoFields(driver, ["stage", "lock_held", "expected_name", "previous_status"])
    );
  }
  if (driver.status === "failed") {
    return (
      hasDriverIdentity(driver, { finished: true }) &&
      hasExit &&
      !hasReason &&
      !hasExpected &&
      hasNoFields(driver, ["lock_held", "expected_name", "previous_status"])
    );
  }
  if (driver.status === "running") {
    return (
      hasDriverIdentity(driver) &&
      !hasReason &&
      !hasExpected &&
      !hasFinished &&
      !hasExit &&
      !hasStage &&
      hasNoFields(driver, ["expected_name", "previous_status"]) &&
      (!hasOwn(driver, "lock_held") || driver.lock_held === true)
    );
  }
  if (driver.status === "interrupted") {
    return (
      hasDriverIdentity(driver) &&
      ["lock-not-held", "stale-start"].includes(driver.reason) &&
      !hasExpected &&
      !hasFinished &&
      !hasExit &&
      !hasStage &&
      hasNoFields(driver, ["expected_name", "previous_status"]) &&
      (driver.reason === "lock-not-held"
        ? driver.lock_held === false
        : !hasOwn(driver, "lock_held"))
    );
  }
  if (driver.status === "stale-running") {
    return (
      hasDriverIdentity(driver) &&
      driver.reason === "runtime-exceeded" &&
      driver.lock_held === true &&
      !hasExpected &&
      !hasFinished &&
      !hasExit &&
      !hasStage &&
      hasNoFields(driver, ["expected_name", "previous_status"])
    );
  }
  if (driver.status === "overdue") {
    return (
      isNonEmptyString(driver.name) &&
      driver.reason === "missed-schedule" &&
      isDriverUtcTimestamp(driver.expected_at) &&
      !hasOwn(driver, "expected_name") &&
      hasOverduePriorState(driver)
    );
  }
  if (driver.status === "invalid") {
    return hasReason && !hasExpected && isInvalidDriverState(driver);
  }
  return false;
}

function isJobCountPair(driver, prefix) {
  const countField = `${prefix}_job_count`;
  const countsField = `${prefix}_job_counts`;
  if (!isPositiveInteger(driver[countField]) || !isRecord(driver[countsField])) {
    return false;
  }
  const entries = Object.entries(driver[countsField]);
  return (
    entries.length > 0 &&
    entries.every(
      ([state, count]) => QUEUE_STATES.has(state) && isPositiveInteger(count),
    ) &&
    entries.reduce((sum, [, count]) => sum + count, 0) === driver[countField]
  );
}

function isWalkforwardOverlay(driver) {
  const hasRefreshCount = hasOwn(driver, "refresh_job_count");
  const hasRefreshCounts = hasOwn(driver, "refresh_job_counts");
  const hasRefreshed = hasOwn(driver, "refreshed_at");
  const hasRefreshStarted = hasOwn(driver, "refresh_started_at");
  const hasRecoveryCount = hasOwn(driver, "recovery_job_count");
  const hasRecoveryCounts = hasOwn(driver, "recovery_job_counts");
  const hasRecovered = hasOwn(driver, "recovered_at");
  const hasRecoveryStarted = hasOwn(driver, "recovery_started_at");
  if (
    hasRefreshCount !== hasRefreshCounts ||
    hasRecoveryCount !== hasRecoveryCounts ||
    (!hasRefreshCount && DRIVER_RECOVERY_FIELDS.some((field) => hasOwn(driver, field))) ||
    (hasRefreshed && hasRefreshStarted) ||
    (hasRecovered && hasRecoveryStarted)
  ) {
    return false;
  }
  if (!hasRefreshCount) return !["recovered", "updating"].includes(driver.status);
  if (
    !isJobCountPair(driver, "refresh") ||
    !["failed", "ok", "overdue", "running"].includes(driver.previous_status) ||
    (hasRefreshed && !isIsoTimestamp(driver.refreshed_at)) ||
    (hasRefreshStarted && !isIsoTimestamp(driver.refresh_started_at))
  ) {
    return false;
  }
  const recoveryExpected = driver.previous_status === "failed";
  if (
    hasRecoveryCount !== recoveryExpected ||
    (hasRecoveryCount &&
      (!isJobCountPair(driver, "recovery") ||
        driver.recovery_job_count !== driver.refresh_job_count ||
        JSON.stringify(driver.recovery_job_counts) !==
          JSON.stringify(driver.refresh_job_counts))) ||
    hasRecovered !== (recoveryExpected && hasRefreshed) ||
    hasRecoveryStarted !== (recoveryExpected && hasRefreshStarted) ||
    (hasRecovered && driver.recovered_at !== driver.refreshed_at) ||
    (hasRecoveryStarted && driver.recovery_started_at !== driver.refresh_started_at)
  ) {
    return false;
  }
  if (hasRefreshed) {
    return driver.status === (recoveryExpected ? "recovered" : driver.previous_status);
  }
  if (hasRefreshStarted) return driver.status === "updating";
  return driver.status === driver.previous_status;
}

function isWalkforwardBaseState(driver) {
  if (!hasOwn(driver, "refresh_job_count")) return isBaseDriverState(driver);
  if (driver.previous_status === "overdue") {
    return (
      driver.reason === "missed-schedule" &&
      isNonEmptyString(driver.name) &&
      isDriverUtcTimestamp(driver.expected_at) &&
      hasOrderedDriverTimestamps(driver) &&
      hasTerminalMetadata(driver) &&
      !hasOwn(driver, "lock_held") &&
      !hasOwn(driver, "expected_name")
    );
  }
  const base = { ...driver, status: driver.previous_status };
  delete base.previous_status;
  for (const field of DRIVER_RECOVERY_FIELDS) delete base[field];
  return isBaseDriverState(base);
}

function isDriver(driver, { expectedName, walkforward = false } = {}) {
  if (driver === null) return true;
  if (
    !isRecord(driver) ||
    !(walkforward ? WALKFORWARD_DRIVER_STATUSES : DRIVER_STATUSES).has(driver.status) ||
    !Object.keys(driver).every((field) => DRIVER_FIELDS.has(field))
  ) {
    return false;
  }
  const fieldsValid =
    ["name", "stage", "reason", "expected_name"].every((field) =>
      hasOptional(driver, field, isNonEmptyString),
    ) &&
    ["refresh_started_at", "refreshed_at", "recovery_started_at", "recovered_at"].every(
      (field) => hasOptional(driver, field, isIsoTimestamp),
    ) &&
    hasOptional(driver, "exit_code", isNonnegativeInteger) &&
    hasOptional(driver, "lock_held", (value) => typeof value === "boolean") &&
    hasOptional(driver, "previous_status", (status) =>
      status === "missing" || WALKFORWARD_DRIVER_STATUSES.has(status),
    );
  if (!fieldsValid) return false;
  if (
    [
      "failed",
      "interrupted",
      "ok",
      "overdue",
      "recovered",
      "running",
      "stale-running",
      "updating",
    ].includes(driver.status) &&
    driver.name !== expectedName
  ) {
    return false;
  }
  if (
    driver.status === "invalid" &&
    driver.reason === "driver-name-mismatch" &&
    driver.expected_name !== expectedName
  ) {
    return false;
  }
  if (!walkforward && DRIVER_RECOVERY_FIELDS.some((field) => hasOwn(driver, field))) {
    return false;
  }
  if (!isWalkforwardOverlay(driver)) return false;
  return walkforward ? isWalkforwardBaseState(driver) : isBaseDriverState(driver);
}

export function isMetaJobState(data) {
  const expectedNames = {
    nightly: "run_daily",
    weekly_verify: "run_weekly_verify",
    weekly_sweeps: "run_weekend_sweeps",
    weekly_liquidity: "run_weekly_liquid",
  };
  return (
    isQueue(data.queue) &&
    Object.entries(expectedNames).every(
      ([field, expectedName]) =>
        Object.prototype.hasOwnProperty.call(data, field) &&
        isDriver(data[field], { expectedName }),
    ) &&
    Object.prototype.hasOwnProperty.call(data, "weekly_walkforward") &&
    isDriver(data.weekly_walkforward, {
      expectedName: "run_weekly_walkforward",
      walkforward: true,
    })
  );
}
