import {
  PUBLIC_SAFE_INTEGER_MAX,
  isBoundedPrintableLine,
  isIsoDate,
  isNonEmptyString,
  isNonnegativeInteger,
  isPositiveInteger,
  isRecord,
} from "./response-contracts.js";
import {
  compareOffsetIsoTimestamps,
  hasExactFields,
  hasOptional,
  isOffsetIsoTimestamp,
  isStringArray,
} from "./meta-contract-utils.js";

const FRIDAY_POSTFLIGHT_STATUSES = new Set([
  "current",
  "failed",
  "invalid",
  "not-yet-run",
  "overdue",
  "stale",
  "updating",
]);
const SCHEDULER_STATUSES = new Set([
  "degraded",
  "inactive",
  "invalid",
  "misconfigured",
  "ok",
  "unknown",
]);
const SOURCE_CONTROL_STATUSES = new Set([
  "behind",
  "current",
  "diverged",
  "invalid",
  "local-only",
  "unpushed",
]);
const SCHEDULER_SERVICE_UNITS = new Set([
  "cron",
  "crond",
]);
const SCHEDULER_SERVICE_STATES = new Set([
  "active",
  "activating",
  "deactivating",
  "failed",
  "inactive",
  "maintenance",
  "refreshing",
  "reloading",
  "unknown",
]);
const SCHEDULER_ENABLEMENT_STATES = new Set([
  "disabled",
  "enabled",
  "enabled-runtime",
  "generated",
  "indirect",
  "linked",
  "linked-runtime",
  "masked",
  "masked-runtime",
  "static",
  "transient",
  "unknown",
]);
const SCHEDULER_FIELDS = [
  "status",
  "cron_service",
  "cron_service_unit",
  "cron_service_enabled",
  "timezone",
  "expected_timezone",
  "timezone_ok",
  "expected_entries",
  "matched_entries",
  "missing_drivers",
  "duplicate_drivers",
  "auxiliary_expected_entries",
  "auxiliary_matched_entries",
  "missing_auxiliary_entries",
  "duplicate_auxiliary_entries",
  "unlaunchable_auxiliary_entries",
  "unexecutable_drivers",
  "unsafe_log_targets",
  "log_directory_writable",
  "user_units",
  "backup",
];
const SCHEDULER_UNIT_STATUSES = new Set(["degraded", "ok", "unknown"]);
const SCHEDULER_BACKUP_STATUSES = new Set(["current", "stale", "unknown"]);
const SCHEDULER_BACKUP_STATES = new Set(["absent", "failed", "ok", "retry", "unknown"]);
const SCHEDULER_UNIT_NAME = /^[A-Za-z0-9:_.@\\-]{1,255}\.[a-z]+$/;
const SOURCE_CONTROL_FIELDS = [
  "status",
  "reason",
  "branch",
  "remote",
  "upstream",
  "ahead",
  "behind",
  "network_checked",
];
const PRODUCTION_DRIVERS = new Set([
  "run_daily",
  "run_weekly_liquid",
  "run_weekly_verify",
  "run_weekly_walkforward",
  "run_weekend_sweeps",
]);
const AUXILIARY_JOBS = new Set(["friday_postflight"]);
const LOG_TARGETS = new Set([...PRODUCTION_DRIVERS, ...AUXILIARY_JOBS]);
const SCHEDULER_INVALID_REASONS = new Set([
  "crontab-unreadable",
  "projection-error",
]);
const POSTFLIGHT_INVALID_REASONS = new Set([
  "projection-error",
  "receipt-before-first-schedule",
  "receipt-from-future-slot",
  "receipt-invalid",
]);
const SOURCE_CONTROL_INVALID_REASONS = new Set([
  "branch-unavailable",
  "git-unavailable",
  "projection-error",
  "tracking-count-invalid",
  "tracking-identity-invalid",
]);
const SOURCE_CONTROL_LOCAL_ONLY_REASONS = new Set([
  "no-upstream",
  "tracking-ref-missing",
]);
const SCHEDULE_CONTRACT_STATUSES = new Set([
  "absent",
  "error",
  "invalid",
  "ok",
  "stale",
  "violations",
]);
const SCHEDULE_CONTRACT_FIELDS = [
  "status",
  "checked_at",
  "age_minutes",
  "stale_after_minutes",
  "violation_count",
  "violations",
  "truncated",
];
// server/schedule_contract.py STATIC_RULES | LIVE_RULES
const SCHEDULE_CONTRACT_RULES = new Set([
  "autostart-drift",
  "cron-drift",
  "duplicate-cron",
  "failed",
  "foreign-holder",
  "held-active",
  "held-autostart",
  "held-cron",
  "held-enabled",
  "held-holder",
  "holder-outside-window",
  "lane-path",
  "manifest-invalid",
  "manifest-source-missing",
  "max-runtime-drift",
  "missing-cron",
  "not-active",
  "not-enabled",
  "not-installed",
  "off-manifest-cron",
  "off-manifest-unit",
  "state-drift",
  "stops-live-unit",
  "timer-drift",
  "unbounded",
  "undeclared-holder",
  "undeclared-writer",
  "unit-not-in-manifest",
]);
const SCHEDULE_CONTRACT_VIOLATION_LIMIT = 20;
const SCHEDULE_CONTRACT_SUBJECT_MAX_CHARS = 255;
const INVARIANTS_STATUSES = new Set([
  "absent",
  "error",
  "invalid",
  "pass",
  "regression",
  "stale",
]);
const INVARIANT_RESULT_STATUSES = new Set(["error", "pass", "regression"]);
const INVARIANTS_FIELDS = [
  "status",
  "mode",
  "checked_at",
  "age_minutes",
  "stale_after_minutes",
  "snapshot_as_of",
  "snapshot_current",
  "regression_count",
  "baselined_count",
  "invariants",
  "regressions",
  "truncated",
];
// server/invariants_status.py INVARIANT_NAMES
const INVARIANT_NAMES = new Set([
  "closeouts_once",
  "equity_per_active_book",
  "experiment_results_finite",
  "fee_row_per_fill",
  "ohlc_geometry",
  "one_split_basis_per_ticker",
  "preopen_not_voided",
  "publication_order",
  "split_recorded_vs_restated",
  "walkforward_results_finite",
]);
const INVARIANTS_REGRESSION_LIMIT = 20;
const INVARIANTS_SUBJECT_MAX_CHARS = 120;
const INVARIANT_CLASS_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
const FIRST_POSTFLIGHT_AT = "2026-09-12T05:15:00+00:00";
const SCHEDULER_TIMEZONE_MAX_CHARS = 255;
const SOURCE_CONTROL_IDENTITY_MAX_CHARS = 4096;
const SOURCE_CONTROL_TRACKING_COUNT_MAX = PUBLIC_SAFE_INTEGER_MAX;
const DAY_MS = 24 * 60 * 60 * 1000;
const POSTFLIGHT_EXPECTED_UTC_DAY = 5;
const POSTFLIGHT_SCHEDULE_HOUR = 5;
const POSTFLIGHT_SCHEDULE_MINUTE = 15;
const POSTFLIGHT_UTC_OFFSET_MS =
  (POSTFLIGHT_SCHEDULE_HOUR * 60 + POSTFLIGHT_SCHEDULE_MINUTE) * 60 * 1000;

function isSortedUniqueSubset(value, allowed) {
  return (
    isStringArray(value) &&
    value.every((item) => allowed.has(item)) &&
    new Set(value).size === value.length &&
    value.every((item, index) => index === 0 || value[index - 1] < item)
  );
}

function fridayPostflightSlot(expectedDate) {
  if (!isIsoDate(expectedDate)) return null;
  const friday = Date.parse(`${expectedDate}T00:00:00Z`);
  if (
    !Number.isFinite(friday) ||
    new Date(friday).getUTCDay() !== POSTFLIGHT_EXPECTED_UTC_DAY
  ) {
    return null;
  }
  const slot = friday + DAY_MS + POSTFLIGHT_UTC_OFFSET_MS;
  return Number.isFinite(slot) ? slot : null;
}

function isExpectedPostflightSlot(expectedDate, expectedAt) {
  const slot = fridayPostflightSlotTimestamp(expectedDate);
  return slot !== null && compareOffsetIsoTimestamps(expectedAt, slot) === 0;
}

function fridayPostflightSlotTimestamp(expectedDate) {
  const slot = fridayPostflightSlot(expectedDate);
  return slot === null ? null : new Date(slot).toISOString().replace(".000Z", "Z");
}

function timestampAtOrAfter(value, boundary) {
  const comparison = compareOffsetIsoTimestamps(value, boundary);
  return comparison !== null && comparison >= 0;
}

function timestampAtOrBefore(value, boundary) {
  const comparison = compareOffsetIsoTimestamps(value, boundary);
  return comparison !== null && comparison <= 0;
}

function isSortedUniqueUnitNames(value) {
  return (
    Array.isArray(value) &&
    value.every((item) => typeof item === "string" && SCHEDULER_UNIT_NAME.test(item)) &&
    value.every((item, index) => index === 0 || value[index - 1] < item)
  );
}

function isSchedulerUserUnits(units) {
  if (
    !hasExactFields(units, [
      "status",
      "autostart_expected",
      "autostart_not_enabled",
      "failed",
    ]) ||
    !SCHEDULER_UNIT_STATUSES.has(units.status) ||
    !isNonnegativeInteger(units.autostart_expected) ||
    !isSortedUniqueUnitNames(units.autostart_not_enabled) ||
    units.autostart_not_enabled.length > units.autostart_expected ||
    !isSortedUniqueUnitNames(units.failed)
  ) {
    return false;
  }
  const problems = units.autostart_not_enabled.length + units.failed.length;
  if (units.status === "unknown") return true;
  return units.status === (problems ? "degraded" : "ok");
}

function isSchedulerBackup(backup) {
  if (
    !hasExactFields(backup, [
      "status",
      "state",
      "last_success_at",
      "age_hours",
      "stale_after_hours",
    ]) ||
    !SCHEDULER_BACKUP_STATUSES.has(backup.status) ||
    !SCHEDULER_BACKUP_STATES.has(backup.state) ||
    !isPositiveInteger(backup.stale_after_hours)
  ) {
    return false;
  }
  if (backup.last_success_at === null || backup.age_hours === null) {
    return (
      backup.last_success_at === null &&
      backup.age_hours === null &&
      backup.status === "unknown"
    );
  }
  return (
    isOffsetIsoTimestamp(backup.last_success_at) &&
    typeof backup.age_hours === "number" &&
    Number.isFinite(backup.age_hours) &&
    backup.age_hours >= 0 &&
    backup.status === (backup.age_hours > backup.stale_after_hours ? "stale" : "current")
  );
}

function schedulerStatus(scheduler, scheduleReady, launchReady) {
  if (
    scheduler.cron_service === "active" &&
    scheduler.cron_service_enabled === "enabled" &&
    scheduler.timezone_ok &&
    scheduleReady &&
    launchReady
  ) {
    return scheduler.user_units.status === "ok" && scheduler.backup.status === "current"
      ? "ok"
      : "degraded";
  }
  if (
    scheduler.cron_service === "unknown" ||
    (scheduler.cron_service === "active" && scheduler.cron_service_enabled === "unknown")
  ) {
    return "unknown";
  }
  if (scheduler.cron_service !== "active") return "inactive";
  return "misconfigured";
}

function isScheduler(scheduler) {
  if (
    !isRecord(scheduler) ||
    !hasExactFields(
      scheduler,
      SCHEDULER_FIELDS,
      scheduler.status === "invalid" ? ["reason"] : [],
    ) ||
    !SCHEDULER_STATUSES.has(scheduler.status) ||
    (scheduler.status === "invalid" && !isNonEmptyString(scheduler.reason)) ||
    !SCHEDULER_SERVICE_STATES.has(scheduler.cron_service) ||
    !(
      scheduler.cron_service_unit === null ||
      SCHEDULER_SERVICE_UNITS.has(scheduler.cron_service_unit)
    ) ||
    scheduler.expected_entries !== PRODUCTION_DRIVERS.size ||
    !isNonnegativeInteger(scheduler.matched_entries) ||
    scheduler.matched_entries > scheduler.expected_entries ||
    !isSortedUniqueSubset(scheduler.missing_drivers, PRODUCTION_DRIVERS) ||
    !isSortedUniqueSubset(scheduler.duplicate_drivers, PRODUCTION_DRIVERS) ||
    scheduler.auxiliary_expected_entries !== AUXILIARY_JOBS.size ||
    !isNonnegativeInteger(scheduler.auxiliary_matched_entries) ||
    scheduler.auxiliary_matched_entries > scheduler.auxiliary_expected_entries ||
    !isSortedUniqueSubset(scheduler.missing_auxiliary_entries, AUXILIARY_JOBS) ||
    !isSortedUniqueSubset(scheduler.duplicate_auxiliary_entries, AUXILIARY_JOBS) ||
    !isSortedUniqueSubset(scheduler.unlaunchable_auxiliary_entries, AUXILIARY_JOBS) ||
    !isSortedUniqueSubset(scheduler.unexecutable_drivers, PRODUCTION_DRIVERS) ||
    !isSortedUniqueSubset(scheduler.unsafe_log_targets, LOG_TARGETS) ||
    typeof scheduler.log_directory_writable !== "boolean" ||
    typeof scheduler.timezone_ok !== "boolean" ||
    !isBoundedPrintableLine(scheduler.timezone, SCHEDULER_TIMEZONE_MAX_CHARS) ||
    scheduler.expected_timezone !== "UTC" ||
    !SCHEDULER_ENABLEMENT_STATES.has(scheduler.cron_service_enabled) ||
    !isSchedulerUserUnits(scheduler.user_units) ||
    !isSchedulerBackup(scheduler.backup)
  ) {
    return false;
  }
  if (
    (scheduler.cron_service_unit === null &&
      (scheduler.cron_service !== "unknown" ||
        scheduler.cron_service_enabled !== "unknown")) ||
    (scheduler.cron_service_unit !== null && scheduler.cron_service === "unknown")
  ) {
    return false;
  }
  if (scheduler.timezone_ok !== ["UTC", "Etc/UTC"].includes(scheduler.timezone)) {
    return false;
  }
  if (scheduler.status === "invalid") {
    return (
      SCHEDULER_INVALID_REASONS.has(scheduler.reason) &&
      scheduler.matched_entries === 0 &&
      scheduler.missing_drivers.length === 0 &&
      scheduler.duplicate_drivers.length === 0 &&
      scheduler.auxiliary_matched_entries === 0 &&
      scheduler.missing_auxiliary_entries.length === 0 &&
      scheduler.duplicate_auxiliary_entries.length === 0
    );
  }
  const scheduleReady =
    scheduler.missing_drivers.length === 0 &&
    scheduler.duplicate_drivers.length === 0 &&
    scheduler.missing_auxiliary_entries.length === 0 &&
    scheduler.duplicate_auxiliary_entries.length === 0;
  const launchReady =
    scheduler.unlaunchable_auxiliary_entries.length === 0 &&
    scheduler.unexecutable_drivers.length === 0 &&
    scheduler.unsafe_log_targets.length === 0 &&
    scheduler.log_directory_writable;
  return (
    scheduler.matched_entries + scheduler.missing_drivers.length <=
      scheduler.expected_entries &&
    scheduler.expected_entries -
      scheduler.matched_entries -
      scheduler.missing_drivers.length <=
      scheduler.duplicate_drivers.length &&
    scheduler.auxiliary_matched_entries + scheduler.missing_auxiliary_entries.length <=
      scheduler.auxiliary_expected_entries &&
    scheduler.auxiliary_expected_entries -
      scheduler.auxiliary_matched_entries -
      scheduler.missing_auxiliary_entries.length <=
      scheduler.duplicate_auxiliary_entries.length &&
    scheduler.status === schedulerStatus(scheduler, scheduleReady, launchReady)
  );
}

function isFridayPostflight(postflight) {
  if (!isRecord(postflight) || !FRIDAY_POSTFLIGHT_STATUSES.has(postflight.status)) {
    return false;
  }
  if (postflight.status === "invalid") {
    return (
      hasExactFields(postflight, ["status", "reason"]) &&
      POSTFLIGHT_INVALID_REASONS.has(postflight.reason)
    );
  }
  if (postflight.status === "not-yet-run") {
    return (
      hasExactFields(postflight, ["status", "next_expected_at"]) &&
      postflight.next_expected_at === FIRST_POSTFLIGHT_AT
    );
  }
  if (["updating", "overdue"].includes(postflight.status)) {
    return (
      hasExactFields(
        postflight,
        ["status", "expected_date", "expected_at"],
        postflight.status === "updating" ? ["previous_status"] : [],
      ) &&
      isExpectedPostflightSlot(postflight.expected_date, postflight.expected_at) &&
      hasOptional(postflight, "previous_status", (value) =>
        ["current", "failed"].includes(value),
      )
    );
  }
  if (postflight.status === "stale") {
    return (
      hasExactFields(postflight, [
        "status",
        "expected_date",
        "expected_at",
        "observed_expected_date",
        "checked_at",
      ]) &&
      isExpectedPostflightSlot(postflight.expected_date, postflight.expected_at) &&
      isIsoDate(postflight.observed_expected_date) &&
      postflight.observed_expected_date < postflight.expected_date &&
      timestampAtOrAfter(
        postflight.checked_at,
        fridayPostflightSlotTimestamp(postflight.observed_expected_date),
      )
    );
  }
  if (
    !hasExactFields(
      postflight,
      postflight.status === "failed"
        ? ["schema_version", "checked_at", "status", "expected_date", "reason"]
        : [
            "schema_version",
            "checked_at",
            "status",
            "expected_date",
            "market_date",
            "nightly_started_at",
            "nightly_finished_at",
            "miner_job_ids",
            "miner_evidence_at",
          ],
    ) ||
    postflight.schema_version !== 1 ||
    !timestampAtOrAfter(
      postflight.checked_at,
      fridayPostflightSlotTimestamp(postflight.expected_date),
    )
  ) {
    return false;
  }
  if (postflight.status === "failed") {
    return isNonEmptyString(postflight.reason) && [...postflight.reason].length <= 1000;
  }
  const jobIds = postflight.miner_job_ids;
  const evidenceAt = postflight.miner_evidence_at;
  const expectedMiners = ["earnings", "fundamentals", "intraday", "signals"];
  const startedAt = Date.parse(postflight.nightly_started_at);
  return (
    isIsoDate(postflight.market_date) &&
    postflight.market_date <= postflight.expected_date &&
    isOffsetIsoTimestamp(postflight.nightly_started_at) &&
    isOffsetIsoTimestamp(postflight.nightly_finished_at) &&
    new Date(startedAt).toISOString().slice(0, 10) === postflight.expected_date &&
    timestampAtOrBefore(postflight.nightly_started_at, postflight.nightly_finished_at) &&
    timestampAtOrBefore(postflight.nightly_finished_at, postflight.checked_at) &&
    isRecord(jobIds) &&
    isRecord(evidenceAt) &&
    Object.keys(jobIds).sort().join(",") === expectedMiners.join(",") &&
    Object.keys(evidenceAt).sort().join(",") === expectedMiners.join(",") &&
    Object.values(jobIds).every(isPositiveInteger) &&
    new Set(Object.values(jobIds)).size === expectedMiners.length &&
    Object.values(evidenceAt).every(
      (timestamp) =>
        isOffsetIsoTimestamp(timestamp) &&
        timestampAtOrAfter(timestamp, postflight.nightly_started_at) &&
        timestampAtOrBefore(timestamp, postflight.nightly_finished_at),
    )
  );
}

function isSourceControl(source) {
  if (
    !isRecord(source) ||
    !hasExactFields(source, SOURCE_CONTROL_FIELDS) ||
    source.network_checked !== false
  ) {
    return false;
  }
  const { ahead, behind, branch, reason, remote, status, upstream } = source;
  const validName = (value) =>
    isBoundedPrintableLine(value, SOURCE_CONTROL_IDENTITY_MAX_CHARS);
  const nullableName = (value) => value === null || validName(value);
  if (!SOURCE_CONTROL_STATUSES.has(status) || ![branch, remote, upstream].every(nullableName)) {
    return false;
  }
  if (status === "invalid") {
    return (
      SOURCE_CONTROL_INVALID_REASONS.has(reason) &&
      branch === null &&
      remote === null &&
      upstream === null &&
      ahead === null &&
      behind === null
    );
  }
  if (status === "local-only") {
    return (
      SOURCE_CONTROL_LOCAL_ONLY_REASONS.has(reason) &&
      validName(branch) &&
      upstream === null &&
      ahead === null &&
      behind === null &&
      ((reason === "no-upstream" && remote === null) ||
        (reason === "tracking-ref-missing" && validName(remote)))
    );
  }
  if (
    reason !== null ||
    !validName(branch) ||
    !validName(remote) ||
    !validName(upstream) ||
    !isNonnegativeInteger(ahead) ||
    !isNonnegativeInteger(behind) ||
    ahead > SOURCE_CONTROL_TRACKING_COUNT_MAX ||
    behind > SOURCE_CONTROL_TRACKING_COUNT_MAX
  ) {
    return false;
  }
  if (status === "current") return ahead === 0 && behind === 0;
  if (status === "unpushed") return ahead > 0 && behind === 0;
  if (status === "behind") return ahead === 0 && behind > 0;
  return status === "diverged" && ahead > 0 && behind > 0;
}

function isScheduleContractViolation(violation) {
  return (
    hasExactFields(violation, ["rule", "subject"]) &&
    SCHEDULE_CONTRACT_RULES.has(violation.rule) &&
    isBoundedPrintableLine(violation.subject, SCHEDULE_CONTRACT_SUBJECT_MAX_CHARS) &&
    !violation.subject.includes("/")
  );
}

function isScheduleContract(contract) {
  if (
    !hasExactFields(contract, SCHEDULE_CONTRACT_FIELDS) ||
    !SCHEDULE_CONTRACT_STATUSES.has(contract.status) ||
    !isPositiveInteger(contract.stale_after_minutes) ||
    !isNonnegativeInteger(contract.violation_count) ||
    typeof contract.truncated !== "boolean" ||
    !Array.isArray(contract.violations) ||
    contract.violations.length > SCHEDULE_CONTRACT_VIOLATION_LIMIT ||
    !contract.violations.every(isScheduleContractViolation) ||
    contract.truncated !== contract.violation_count > contract.violations.length ||
    (!contract.truncated && contract.violation_count !== contract.violations.length)
  ) {
    return false;
  }
  if (contract.checked_at === null) {
    return (
      ["absent", "invalid"].includes(contract.status) &&
      contract.age_minutes === null &&
      contract.violation_count === 0
    );
  }
  if (
    !isOffsetIsoTimestamp(contract.checked_at) ||
    !isNonnegativeInteger(contract.age_minutes) ||
    ["absent", "invalid"].includes(contract.status)
  ) {
    return false;
  }
  if (contract.status === "stale") return contract.age_minutes > contract.stale_after_minutes;
  if (contract.age_minutes > contract.stale_after_minutes) return false;
  if (contract.status === "ok") return contract.violation_count === 0;
  if (contract.status === "violations") return contract.violation_count > 0;
  return true;
}

function isInvariantRegression(item) {
  return (
    hasExactFields(item, ["invariant", "class", "subject"]) &&
    INVARIANT_NAMES.has(item.invariant) &&
    typeof item.class === "string" &&
    INVARIANT_CLASS_PATTERN.test(item.class) &&
    isBoundedPrintableLine(item.subject, INVARIANTS_SUBJECT_MAX_CHARS) &&
    !item.subject.includes("/")
  );
}

function isInvariantSummary(item) {
  return (
    hasExactFields(item, ["name", "status"]) &&
    INVARIANT_NAMES.has(item.name) &&
    INVARIANT_RESULT_STATUSES.has(item.status)
  );
}

function isInvariants(section) {
  if (
    !hasExactFields(section, INVARIANTS_FIELDS) ||
    !INVARIANTS_STATUSES.has(section.status) ||
    section.mode !== "shadow" ||
    !isPositiveInteger(section.stale_after_minutes) ||
    !isNonnegativeInteger(section.regression_count) ||
    !isNonnegativeInteger(section.baselined_count) ||
    typeof section.truncated !== "boolean" ||
    !Array.isArray(section.invariants) ||
    !section.invariants.every(isInvariantSummary) ||
    new Set(section.invariants.map((item) => item.name)).size !== section.invariants.length ||
    !Array.isArray(section.regressions) ||
    section.regressions.length > INVARIANTS_REGRESSION_LIMIT ||
    !section.regressions.every(isInvariantRegression) ||
    section.truncated !== section.regression_count > section.regressions.length ||
    ![null, true, false].includes(section.snapshot_current) ||
    (section.snapshot_as_of !== null && !isOffsetIsoTimestamp(section.snapshot_as_of))
  ) {
    return false;
  }
  if (section.checked_at === null) {
    return (
      ["absent", "invalid"].includes(section.status) &&
      section.age_minutes === null &&
      section.regression_count === 0 &&
      section.invariants.length === 0
    );
  }
  if (
    !isOffsetIsoTimestamp(section.checked_at) ||
    !isNonnegativeInteger(section.age_minutes) ||
    ["absent", "invalid"].includes(section.status)
  ) {
    return false;
  }
  const outdated =
    section.age_minutes > section.stale_after_minutes || section.snapshot_current === false;
  if (section.status === "stale") return outdated;
  if (outdated) return false;
  if (section.status === "pass") return section.regression_count === 0;
  if (section.status === "regression") return section.regression_count > 0;
  return true;
}

export function isMetaAutomation(data) {
  return (
    isScheduler(data.scheduler) &&
    isFridayPostflight(data.friday_postflight) &&
    isSourceControl(data.source_control) &&
    isScheduleContract(data.schedule_contract) &&
    isInvariants(data.invariants)
  );
}
