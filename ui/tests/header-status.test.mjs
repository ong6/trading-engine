import assert from "node:assert/strict";
import test from "node:test";

import {
  driverAlert,
  fridayPostflightAlert,
  schedulerLabel,
  walkforwardLabel,
} from "../app/lib/header-status.js";

test("Friday postflight alerts only after an actionable result", () => {
  for (const status of ["current", "not-yet-run", "updating"]) {
    assert.equal(fridayPostflightAlert({ status }), false);
  }
  for (const status of ["failed", "invalid", "overdue", "stale"]) {
    assert.equal(fridayPostflightAlert({ status }), true);
  }
  assert.equal(fridayPostflightAlert(null), true);
});

test("driver alerts distinguish healthy progress and recovered runs from failures", () => {
  for (const status of ["ok", "running", "updating", "recovered"]) {
    assert.equal(driverAlert({ status }), false);
  }
  assert.equal(driverAlert({ status: "failed" }), true);
  assert.equal(driverAlert({ status: "overdue" }), true);
  assert.equal(driverAlert(null), false);
});

test("walk-forward labels disclose live progress and completed recovery", () => {
  assert.equal(walkforwardLabel(null, null), "unknown");
  assert.equal(
    walkforwardLabel(
      { status: "updating" },
      { done: 4, running: 2, pending: 12 },
    ),
    "updating (4 done · 2 running · 12 pending)",
  );
  assert.equal(
    walkforwardLabel({ status: "recovered", stage: "enqueue" }, { done: 18 }),
    "recovered (18 done)",
  );
  assert.equal(
    walkforwardLabel({ status: "failed", stage: "enqueue" }, null),
    "failed (enqueue)",
  );
});

test("scheduler label includes counts and every actionable continuity problem", () => {
  assert.equal(schedulerLabel(null), "unknown");
  assert.equal(
    schedulerLabel({
      status: "ok",
      matched_entries: 5,
      expected_entries: 5,
      missing_drivers: [],
      duplicate_drivers: [],
      auxiliary_expected_entries: 1,
      auxiliary_matched_entries: 1,
      missing_auxiliary_entries: [],
      duplicate_auxiliary_entries: [],
      unlaunchable_auxiliary_entries: [],
      unexecutable_drivers: [],
      unsafe_log_targets: [],
      log_directory_writable: true,
      timezone_ok: true,
      cron_service_enabled: "enabled",
    }),
    "ok (5/5 · postflight 1/1)",
  );
  assert.equal(
    schedulerLabel({
      status: "invalid",
      matched_entries: 2,
      expected_entries: 5,
      missing_drivers: ["nightly"],
      duplicate_drivers: ["weekly_verify"],
      auxiliary_expected_entries: 1,
      auxiliary_matched_entries: 0,
      missing_auxiliary_entries: ["friday_postflight"],
      duplicate_auxiliary_entries: [],
      unlaunchable_auxiliary_entries: ["friday_postflight"],
      unexecutable_drivers: ["weekly_liquidity"],
      unsafe_log_targets: ["run_daily", "friday_postflight"],
      log_directory_writable: false,
      timezone_ok: false,
      timezone: "Asia/Singapore",
      cron_service_enabled: "disabled",
    }),
    "invalid (2/5 · postflight 0/1) · missing nightly · duplicate weekly_verify · missing friday_postflight · cannot launch friday_postflight · not executable weekly_liquidity · unsafe logs run_daily, friday_postflight · logs not writable · timezone Asia/Singapore · boot disabled",
  );
});
