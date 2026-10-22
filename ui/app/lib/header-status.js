// Pure status classification and labels for the persistent operational header.

const DRIVER_OK = new Set(["ok", "running", "updating", "recovered"]);

export function nightlyEvidenceAlert(evidence) {
  return evidence ? !["updating", "current"].includes(evidence.status) : false;
}

export function countedEvidenceLabel(evidence, currentKey, expectedKey) {
  const counts = Number.isSafeInteger(evidence[currentKey]) &&
    Number.isSafeInteger(evidence[expectedKey])
    ? ` (${evidence[currentKey]}/${evidence[expectedKey]})` : "";
  return `${evidence.status}${counts}`;
}

export function e1EvidenceLabel(evidence) {
  const details = [];
  if (Number.isSafeInteger(evidence.observations) && Number.isSafeInteger(evidence.target_observations)) {
    details.push(`${evidence.observations}/${evidence.target_observations}`);
  }
  if (Number.isSafeInteger(evidence.runtime_contract_version)) {
    details.push(`v${evidence.runtime_contract_version}`);
  }
  return `${evidence.status.toLowerCase()}${details.length ? ` (${details.join(", ")})` : ""}`;
}

export function driverAlert(driver) {
  return driver ? !DRIVER_OK.has(driver.status) : false;
}

export function fridayPostflightAlert(postflight) {
  return postflight
    ? !["current", "not-yet-run", "updating"].includes(postflight.status)
    : true;
}

export function walkforwardLabel(weekly, refreshCounts) {
  if (!weekly) return "unknown";
  if (weekly.status === "updating" && refreshCounts) {
    return `${weekly.status} (${refreshCounts.done || 0} done · ${refreshCounts.running || 0} running · ${refreshCounts.pending || 0} pending)`;
  }
  if (weekly.status === "recovered" && refreshCounts) {
    return `${weekly.status} (${refreshCounts.done || 0} done)`;
  }
  return `${weekly.status}${weekly.stage ? ` (${weekly.stage})` : ""}`;
}

export function schedulerLabel(scheduler) {
  if (!scheduler) return "unknown";
  const production = `${scheduler.matched_entries || 0}/${scheduler.expected_entries || 0}`;
  const auxiliary = `${scheduler.auxiliary_matched_entries || 0}/${scheduler.auxiliary_expected_entries || 0}`;
  const count = `(${production} · postflight ${auxiliary})`;
  const problems = [];
  if (scheduler.missing_drivers?.length) {
    problems.push(`missing ${scheduler.missing_drivers.join(", ")}`);
  }
  if (scheduler.duplicate_drivers?.length) {
    problems.push(`duplicate ${scheduler.duplicate_drivers.join(", ")}`);
  }
  if (scheduler.missing_auxiliary_entries?.length) {
    problems.push(`missing ${scheduler.missing_auxiliary_entries.join(", ")}`);
  }
  if (scheduler.duplicate_auxiliary_entries?.length) {
    problems.push(`duplicate ${scheduler.duplicate_auxiliary_entries.join(", ")}`);
  }
  if (scheduler.unlaunchable_auxiliary_entries?.length) {
    problems.push(`cannot launch ${scheduler.unlaunchable_auxiliary_entries.join(", ")}`);
  }
  if (scheduler.unexecutable_drivers?.length) {
    problems.push(`not executable ${scheduler.unexecutable_drivers.join(", ")}`);
  }
  if (scheduler.unsafe_log_targets?.length) {
    problems.push(`unsafe logs ${scheduler.unsafe_log_targets.join(", ")}`);
  }
  if (!scheduler.log_directory_writable) {
    problems.push("logs not writable");
  }
  if (!scheduler.timezone_ok) {
    problems.push(`timezone ${scheduler.timezone || "unknown"}`);
  }
  if (scheduler.cron_service_enabled !== "enabled") {
    problems.push(`boot ${scheduler.cron_service_enabled || "unknown"}`);
  }
  const units = scheduler.user_units;
  if (units?.status === "unknown") problems.push("units unknown");
  if (units?.autostart_not_enabled?.length) {
    problems.push(`not enabled ${units.autostart_not_enabled.join(", ")}`);
  }
  if (units?.failed?.length) problems.push(`failed ${units.failed.join(", ")}`);
  const backup = scheduler.backup;
  // A skipped (retry) or failed latest run backed up nothing, even while the last
  // good backup is still current.
  if (
    backup &&
    (backup.status !== "current" || backup.state === "retry" || backup.state === "failed")
  ) {
    const age = backup.age_hours === null ? "" : ` ${backup.age_hours}h`;
    problems.push(`backup ${backup.status}${age} (${backup.state})`);
  }
  return `${scheduler.status} ${count}${problems.length ? ` · ${problems.join(" · ")}` : ""}`;
}
