// Pure status classification and labels for the persistent operational header.

const DRIVER_OK = new Set(["ok", "running", "updating", "recovered"]);

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
  return `${scheduler.status} ${count}${problems.length ? ` · ${problems.join(" · ")}` : ""}`;
}
