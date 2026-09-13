import assert from "node:assert/strict";
import test from "node:test";

import {
  compareOffsetIsoTimestamps,
  isOffsetIsoTimestamp,
} from "../app/lib/meta-contract-utils.js";
import { isMetaProjection } from "../app/lib/meta-contracts.js";

const clone = (value) => structuredClone(value);

test("offset timestamps retain canonical microsecond ordering", () => {
  const earlier = "2026-09-12T00:30:01.123001+00:00";
  const later = "2026-09-12T02:30:01.123999+02:00";
  assert.equal(Date.parse(earlier), Date.parse(later));
  assert.equal(compareOffsetIsoTimestamps(earlier, later), -1);
  assert.equal(compareOffsetIsoTimestamps(later, earlier), 1);
  assert.equal(
    compareOffsetIsoTimestamps(
      "2026-09-12T00:30:01.123001Z",
      "2026-09-12T02:30:01.123001+02:00",
    ),
    0,
  );
  assert.equal(isOffsetIsoTimestamp("2026-09-12T00:30:01Z"), true);
  assert.equal(isOffsetIsoTimestamp("2026-09-12T00:30:01.123456+00:00"), true);
  assert.equal(isOffsetIsoTimestamp("2026-09-12T00:30:01.000000+00:00"), false);
  assert.equal(isOffsetIsoTimestamp("2026-09-12T00:30:01.1+00:00"), false);
  assert.equal(compareOffsetIsoTimestamps("not-a-timestamp", later), null);
});

function validMeta() {
  return {
    meta: {
      regime: "risk-on",
      last_run: "2026-09-07T22:30:11.394991+00:00",
      last_screen: null,
      screen_date: "2026-09-04",
    },
    meta_file: { status: "ok" },
    latest_prices_date: "2026-09-04",
    freshness_days: 3,
    price_quarantines: [],
    price_quarantines_limit: 100,
    price_quarantines_matching_count: 0,
    price_quarantines_truncated: false,
    market_freshness: {
      status: "ok",
      as_of: "2026-09-07",
      latest_date: "2026-09-04",
      calendar_days: 3,
      missing_completed_sessions: 0,
      first_missing_session: null,
      last_missing_session: null,
      next_session: "2026-09-08",
    },
    price_verification: {
      status: "current",
      as_of: "2026-09-04",
      verified_at: "2026-09-07T22:40:00+00:00",
      names_selected: 162,
      names_checked: 162,
      names_agreeing: 162,
      names_disagreeing: 0,
      names_not_checked: 0,
      n_disagreements: 0,
      n_material: 0,
      n_parse_errors: 0,
      tolerance_bp: 10,
      tolerance_abs_usd: 0.01,
      material_bp: 200,
      disagreements: [],
      disagreements_limit: 20,
      disagreements_matching_count: 0,
      disagreements_truncated: false,
    },
    queue: {
      counts: { done: 10, failed: 1 },
      actionable_failure_count: 0,
      actionable_failures: [],
      actionable_failures_limit: 100,
      actionable_failures_truncated: false,
      historical_failure_count: 1,
      historical_failures: [
        {
          id: 7,
          kind: "sweep",
          updated_at: "2026-09-05T20:00:23.920443+00:00",
          classification: "recurring sweep charter is closed",
        },
      ],
      historical_failures_limit: 100,
      historical_failures_truncated: false,
      latest_research_job: {
        id: 8,
        kind: "walkforward",
        state: "done",
        updated_at: "2026-09-06T20:00:23.920443+00:00",
      },
    },
    nightly_evidence: { status: "current" },
    miner_evidence: {
      status: "incomplete",
      current: 3,
      expected: 4,
      miners: {
        intraday: { status: "current" },
        signals: { status: "current" },
        earnings: { status: "current" },
        fundamentals: { status: "missing" },
      },
    },
    sweep_evidence: {
      status: "idle",
      reason: "no-open-recurring-charters",
      current_charters: 0,
      open_charters: 0,
      charters: [],
    },
    liquidity_evidence: {
      status: "not-yet-run",
      reason: "no-scheduled-run",
    },
    stale_exposure: {
      as_of: "2026-09-04",
      ticker_count: 0,
      position_count: 0,
      pending_order_count: 0,
      positions: [],
      positions_limit: 100,
      positions_truncated: false,
      pending_orders: [],
      pending_orders_limit: 100,
      pending_orders_truncated: false,
    },
    scheduler: {
      status: "ok",
      cron_service: "active",
      cron_service_unit: "cron",
      cron_service_enabled: "enabled",
      timezone: "Etc/UTC",
      expected_timezone: "UTC",
      timezone_ok: true,
      expected_entries: 5,
      matched_entries: 5,
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
    },
    friday_postflight: {
      status: "not-yet-run",
      next_expected_at: "2026-09-12T05:15:00+00:00",
    },
    source_control: {
      status: "local-only",
      reason: "no-upstream",
      branch: "main",
      remote: null,
      upstream: null,
      ahead: null,
      behind: null,
      network_checked: false,
    },
    nightly: {
      status: "ok",
      name: "run_daily",
      started_at: "2026-09-07T22:30:01Z",
      finished_at: "2026-09-08T00:30:01Z",
    },
    weekly_verify: {
      status: "running",
      name: "run_weekly_verify",
      started_at: "2026-09-12T02:00:01Z",
      lock_held: true,
    },
    weekly_sweeps: {
      status: "failed",
      name: "run_weekend_sweeps",
      started_at: "2026-09-12T06:00:01Z",
      finished_at: "2026-09-12T06:01:01Z",
      exit_code: 1,
      stage: "sweep",
    },
    weekly_walkforward: {
      status: "recovered",
      name: "run_weekly_walkforward",
      started_at: "2026-09-06T06:00:01Z",
      finished_at: "2026-09-06T06:00:02Z",
      exit_code: 1,
      stage: "enqueue",
      previous_status: "failed",
      refresh_job_count: 18,
      refresh_job_counts: { done: 18 },
      refreshed_at: "2026-09-09T02:21:39.988557",
      recovery_job_count: 18,
      recovery_job_counts: { done: 18 },
      recovered_at: "2026-09-09T02:21:39.988557",
    },
    weekly_liquidity: null,
    walkforward_evidence: {
      status: "current",
      expected_results: 18,
      available_results: 18,
      cohort_signature_count: 1,
      diagnostic_list_limit: 100,
      diagnostic_value_max_chars: 256,
      missing_results: [],
      missing_results_count: 0,
      missing_results_truncated: false,
      missing_results_values_truncated: false,
      invalid_files: [],
      invalid_files_count: 0,
      invalid_files_truncated: false,
      invalid_files_values_truncated: false,
      config_mismatches: [],
      config_mismatches_count: 0,
      config_mismatches_truncated: false,
      config_mismatches_values_truncated: false,
      registration_mismatches: [],
      registration_mismatches_count: 0,
      registration_mismatches_truncated: false,
      registration_mismatches_values_truncated: false,
      duplicate_config_ids: [],
      duplicate_config_ids_count: 0,
      duplicate_config_ids_truncated: false,
      duplicate_config_ids_values_truncated: false,
      invalid_registrations: [],
      invalid_registrations_count: 0,
      invalid_registrations_truncated: false,
      invalid_registrations_values_truncated: false,
    },
    forward_review: {
      status: "ACCUMULATING",
      paper_only: true,
      automatic_action: "none",
      runtime_contract_version: 4,
      runtime_contract_sha256: "a".repeat(64),
      shared_sessions: 1,
      minimum_shared_sessions: 200,
      eligible_after: "2027-09-04",
    },
    xs_forward_review: {
      status: "WAITING",
      paper_only: true,
      automatic_action: "none",
      runtime_contract_version: 10,
      runtime_contract_sha256: "b".repeat(64),
      signal_date: "2026-09-30",
      eligible_after: "2031-10-01",
      paired_complete_months: 0,
      minimum_paired_months: 48,
    },
    e1_forward: {
      status: "ACCUMULATING",
      paper_only: true,
      automatic_action: "none",
      runtime_contract_version: 4,
      runtime_contract_sha256: "c".repeat(64),
      observations: 7,
      target_observations: 40,
      sample_end: "2027-05-10",
    },
  };
}

function validCurrentPostflightMeta() {
  const value = validMeta();
  value.friday_postflight = {
    schema_version: 1,
    checked_at: "2026-09-12T05:15:05+00:00",
    status: "current",
    expected_date: "2026-09-11",
    market_date: "2026-09-11",
    nightly_started_at: "2026-09-11T22:30:01+00:00",
    nightly_finished_at: "2026-09-12T00:30:01+00:00",
    miner_job_ids: { earnings: 478, fundamentals: 479, intraday: 476, signals: 477 },
    miner_evidence_at: {
      earnings: "2026-09-12T00:20:00+00:00",
      fundamentals: "2026-09-12T00:29:59+00:00",
      intraday: "2026-09-11T22:45:00+00:00",
      signals: "2026-09-11T22:46:00+00:00",
    },
  };
  return value;
}

function validLiquidityResult(status = "current") {
  const backfillFailure = status === "backfill-issues";
  const candidateFailure = status === "issues";
  return {
    status: status === "current" ? "current" : "issues",
    reason: candidateFailure
      ? "candidate-download-failures"
      : backfillFailure
        ? "backfill-failures"
        : null,
    as_of: "2026-09-11",
    published_at: "2026-09-13T03:00:00+00:00",
    admitted: 1,
    demoted: 1,
    kept_held: 1,
    liquid_before: 2,
    liquid_after: 2,
    candidates_pulled: 3,
    candidates_failed: candidateFailure ? 1 : 0,
    backfill_processed: 1,
    backfill_failed: backfillFailure ? 1 : 0,
  };
}

test("meta projection requires exact coherent liquidity evidence", () => {
  const accepted = [
    { status: "not-yet-run", reason: "no-scheduled-run" },
    { status: "updating" },
    ...["failed", "interrupted", "invalid", "overdue", "stale-running"].map(
      (status) => ({ status, reason: "driver-not-successful" }),
    ),
    { status: "missing", reason: "evidence-missing" },
    { status: "unknown", reason: "market-date-unavailable" },
    { status: "invalid", reason: "future-evidence" },
    { status: "invalid", reason: "malformed-evidence" },
    { status: "invalid", reason: "projection-error" },
    {
      status: "invalid",
      reason: "evidence-postdates-latest-run",
      published_at: "2026-09-13T03:00:01.123001+00:00",
      finished_at: "2026-09-13T03:00:00.123001+00:00",
    },
    {
      status: "stale",
      reason: "store-count-mismatch",
      published_at: "2026-09-13T03:00:00+00:00",
      liquid_after: 3,
      store_liquid: 2,
    },
    {
      status: "stale",
      reason: "evidence-predates-latest-run",
      published_at: "2026-09-13T01:59:59+00:00",
    },
    {
      status: "stale",
      reason: "scheduled-market-date-mismatch",
      as_of: "2026-09-10",
      expected_as_of: "2026-09-11",
      latest_date: "2026-09-11",
    },
    {
      status: "invalid",
      reason: "scheduled-market-date-mismatch",
      as_of: "2026-09-12",
      expected_as_of: "2026-09-11",
      latest_date: "2026-09-11",
    },
    {
      status: "invalid",
      reason: "evidence-ahead-of-store",
      as_of: "2026-09-12",
      latest_date: "2026-09-11",
    },
    validLiquidityResult(),
    validLiquidityResult("issues"),
    validLiquidityResult("backfill-issues"),
    {
      ...validLiquidityResult("issues"),
      reason: "candidate-and-backfill-failures",
      backfill_failed: 1,
    },
  ];
  for (const evidence of accepted) {
    const payload = validMeta();
    payload.liquidity_evidence = evidence;
    assert.equal(isMetaProjection(payload), true, JSON.stringify(evidence));
  }

  const unsafe = Number.MAX_SAFE_INTEGER + 1;
  const rejected = [
    { status: "current", reason: "invented" },
    { ...validLiquidityResult(), private_path: "/tmp/evidence.json" },
    { ...validLiquidityResult(), published_at: "not-a-timestamp" },
    { ...validLiquidityResult(), as_of: "2026-09-31" },
    { ...validLiquidityResult(), admitted: unsafe },
    { ...validLiquidityResult(), liquid_after: 3 },
    { ...validLiquidityResult(), candidates_failed: 4 },
    { ...validLiquidityResult(), backfill_failed: 2 },
    { ...validLiquidityResult("issues"), reason: "backfill-failures" },
    { status: "not-yet-run", reason: "invented" },
    { status: "not-yet-run", reason: "no-scheduled-run", extra: true },
    { status: "updating", reason: null },
    { status: "failed", reason: "evidence-missing" },
    { status: "invalid", reason: "invented" },
    {
      status: "stale",
      reason: "store-count-mismatch",
      published_at: "2026-09-13T03:00:00+00:00",
      liquid_after: 2,
      store_liquid: 2,
    },
    {
      status: "stale",
      reason: "scheduled-market-date-mismatch",
      as_of: "2026-09-11",
      expected_as_of: "2026-09-11",
      latest_date: "2026-09-11",
    },
    {
      status: "invalid",
      reason: "evidence-postdates-latest-run",
      published_at: "2026-09-13T03:00:01.122999+00:00",
      finished_at: "2026-09-13T03:00:00.123001+00:00",
    },
  ];
  for (const evidence of rejected) {
    const payload = validMeta();
    payload.liquidity_evidence = evidence;
    assert.equal(isMetaProjection(payload), false, JSON.stringify(evidence));
  }
});

test("meta projection validates UI-consumed monitor fields and honest degraded states", () => {
  const valid = validMeta();
  assert.equal(isMetaProjection(valid), true);

  const omitted = clone(valid);
  delete omitted.weekly_liquidity;
  assert.equal(isMetaProjection(omitted), false);

  const missingMonitor = clone(valid);
  delete missingMonitor.scheduler;
  assert.equal(isMetaProjection(missingMonitor), false);

  for (const scheduler of [
    {
      ...clone(valid.scheduler),
      status: "inactive",
      cron_service: "inactive",
    },
    {
      ...clone(valid.scheduler),
      status: "unknown",
      cron_service: "unknown",
      cron_service_unit: null,
      cron_service_enabled: "unknown",
    },
    {
      ...clone(valid.scheduler),
      status: "misconfigured",
      matched_entries: 4,
      missing_drivers: ["run_weekly_verify"],
    },
    {
      ...clone(valid.scheduler),
      status: "misconfigured",
      timezone: "America/New_York",
      timezone_ok: false,
    },
  ]) {
    const statusVariant = clone(valid);
    statusVariant.scheduler = scheduler;
    assert.equal(isMetaProjection(statusVariant), true, scheduler.status);
  }

  const exactHostLabelBudgets = clone(valid);
  exactHostLabelBudgets.scheduler = {
    ...exactHostLabelBudgets.scheduler,
    status: "misconfigured",
    timezone: "x".repeat(255),
    timezone_ok: false,
  };
  exactHostLabelBudgets.source_control = {
    status: "current",
    reason: null,
    branch: "b".repeat(4096),
    remote: "r".repeat(4096),
    upstream: "u".repeat(4096),
    ahead: 0,
    behind: 0,
    network_checked: false,
  };
  assert.equal(isMetaProjection(exactHostLabelBudgets), true);

  const currentPostflight = validCurrentPostflightMeta();
  assert.equal(isMetaProjection(currentPostflight), true);

  const duplicatePostflightJob = validCurrentPostflightMeta();
  duplicatePostflightJob.friday_postflight.miner_job_ids.fundamentals =
    duplicatePostflightJob.friday_postflight.miner_job_ids.earnings;
  assert.equal(isMetaProjection(duplicatePostflightJob), false);

  const oversizedPostflightFailure = validCurrentPostflightMeta();
  oversizedPostflightFailure.friday_postflight = {
    schema_version: 1,
    checked_at: "2026-09-12T05:15:05+00:00",
    status: "failed",
    expected_date: "2026-09-11",
    reason: "x".repeat(1001),
  };
  assert.equal(isMetaProjection(oversizedPostflightFailure), false);

  const unicodePostflightFailure = validCurrentPostflightMeta();
  unicodePostflightFailure.friday_postflight = {
    schema_version: 1,
    checked_at: "2026-09-12T05:15:05+00:00",
    status: "failed",
    expected_date: "2026-09-11",
    reason: "💥".repeat(1000),
  };
  assert.equal(isMetaProjection(unicodePostflightFailure), true);

  const offsetPostflight = validCurrentPostflightMeta();
  offsetPostflight.friday_postflight.nightly_started_at = "2026-09-12T00:30:01+02:00";
  assert.equal(isMetaProjection(offsetPostflight), true);

  const precisePostflight = validCurrentPostflightMeta();
  precisePostflight.friday_postflight.nightly_finished_at =
    "2026-09-12T00:30:01.123001+00:00";
  precisePostflight.friday_postflight.miner_evidence_at.fundamentals =
    "2026-09-12T00:30:01.123999+00:00";
  assert.equal(
    Date.parse(precisePostflight.friday_postflight.nightly_finished_at),
    Date.parse(precisePostflight.friday_postflight.miner_evidence_at.fundamentals),
  );
  assert.equal(isMetaProjection(precisePostflight), false);

  for (const fridayPostflight of [
    {
      status: "updating",
      expected_date: "2026-09-18",
      expected_at: "2026-09-19T05:15:00+00:00",
      previous_status: "current",
    },
    {
      status: "overdue",
      expected_date: "2026-09-18",
      expected_at: "2026-09-19T05:15:00+00:00",
    },
    {
      status: "stale",
      expected_date: "2026-09-18",
      expected_at: "2026-09-19T05:15:00+00:00",
      observed_expected_date: "2026-09-11",
      checked_at: "2026-09-12T05:15:05+00:00",
    },
  ]) {
    const statusVariant = clone(valid);
    statusVariant.friday_postflight = fridayPostflight;
    assert.equal(isMetaProjection(statusVariant), true, fridayPostflight.status);
  }

  for (const sourceControl of [
    {
      status: "local-only",
      reason: "tracking-ref-missing",
      branch: "main",
      remote: "origin",
      upstream: null,
      ahead: null,
      behind: null,
      network_checked: false,
    },
    {
      status: "current",
      reason: null,
      branch: "main",
      remote: "origin",
      upstream: "origin/main",
      ahead: 0,
      behind: 0,
      network_checked: false,
    },
    {
      status: "unpushed",
      reason: null,
      branch: "main",
      remote: "origin",
      upstream: "origin/main",
      ahead: Number.MAX_SAFE_INTEGER,
      behind: 0,
      network_checked: false,
    },
    {
      status: "behind",
      reason: null,
      branch: "main",
      remote: "origin",
      upstream: "origin/main",
      ahead: 0,
      behind: 3,
      network_checked: false,
    },
    {
      status: "diverged",
      reason: null,
      branch: "main",
      remote: "origin",
      upstream: "origin/main",
      ahead: 2,
      behind: 3,
      network_checked: false,
    },
  ]) {
    const statusVariant = clone(valid);
    statusVariant.source_control = sourceControl;
    assert.equal(isMetaProjection(statusVariant), true, sourceControl.status);
  }

  const sparseFailures = clone(valid);
  sparseFailures.meta_file = { status: "invalid", reason: "malformed" };
  sparseFailures.price_verification = { status: "missing" };
  sparseFailures.miner_evidence = { status: "invalid" };
  sparseFailures.sweep_evidence = { status: "invalid", reason: "projection-error" };
  sparseFailures.liquidity_evidence = {
    status: "invalid",
    reason: "projection-error",
  };
  sparseFailures.nightly_evidence = { status: "unknown" };
  sparseFailures.walkforward_evidence = {
    status: "invalid",
    reason: "projection-error",
  };
  sparseFailures.forward_review = {
    status: "INVALID",
    paper_only: true,
    automatic_action: "none",
  };
  sparseFailures.xs_forward_review = clone(sparseFailures.forward_review);
  sparseFailures.e1_forward = clone(sparseFailures.forward_review);
  assert.equal(isMetaProjection(sparseFailures), true);

  for (const driver of [
    { status: "invalid", reason: "log-unreadable" },
    { status: "invalid", reason: "malformed-start-marker" },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "not-a-timestamp",
      reason: "invalid-started-at",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T08:00:00Z",
      reason: "future-started-at",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      reason: "multiple-terminal-markers",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      reason: "malformed-terminal-marker",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      finished_at: "not-a-timestamp",
      reason: "invalid-finished-at",
    },
    {
      status: "invalid",
      name: "run_daily",
      expected_name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      finished_at: "2026-09-13T03:00:01Z",
      reason: "driver-name-mismatch",
    },
    {
      status: "interrupted",
      name: "run_weekly_liquid",
      started_at: "2026-09-06T02:00:01Z",
      reason: "lock-not-held",
      lock_held: false,
    },
    {
      status: "ok",
      name: "run_weekly_liquid",
      started_at: "2026-09-06T02:00:01Z",
      finished_at: "2026-09-06T03:00:01Z",
    },
    {
      status: "overdue",
      name: "run_weekly_liquid",
      reason: "missed-schedule",
      expected_at: "2026-09-13T02:00:00Z",
      previous_status: "missing",
    },
    {
      status: "running",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      lock_held: true,
    },
    {
      status: "stale-running",
      name: "run_weekly_liquid",
      started_at: "2026-09-06T02:00:01Z",
      reason: "runtime-exceeded",
      lock_held: true,
    },
  ]) {
    const driverState = clone(valid);
    driverState.weekly_liquidity = driver;
    assert.equal(isMetaProjection(driverState), true, driver.status);
  }

  for (const driver of [
    { status: "invalid", reason: "invented" },
    { status: "invalid", reason: "log-unreadable", expected_name: "run_daily" },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      reason: "invalid-started-at",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "not-a-timestamp",
      reason: "future-started-at",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "not-a-timestamp",
      reason: "multiple-terminal-markers",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      finished_at: "2026-09-13T03:00:01Z",
      reason: "invalid-finished-at",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      reason: "driver-name-mismatch",
    },
    {
      status: "invalid",
      name: "run_weekly_liquid",
      expected_name: "run_weekly_liquid",
      started_at: "2026-09-13T02:00:01Z",
      reason: "driver-name-mismatch",
    },
  ]) {
    const driverState = clone(valid);
    driverState.weekly_liquidity = driver;
    assert.equal(isMetaProjection(driverState), false, driver.reason);
  }

  for (const driver of [
    valid.weekly_walkforward,
    {
      status: "updating",
      name: "run_weekly_walkforward",
      started_at: "2026-09-06T06:00:01Z",
      finished_at: "2026-09-06T07:00:01Z",
      previous_status: "ok",
      refresh_job_count: 18,
      refresh_job_counts: { done: 17, running: 1 },
      refresh_started_at: "2026-09-09T02:00:00",
    },
    {
      status: "updating",
      name: "run_weekly_walkforward",
      started_at: "2026-09-06T06:00:01Z",
      finished_at: "2026-09-06T06:00:02Z",
      exit_code: 1,
      previous_status: "failed",
      refresh_job_count: 18,
      refresh_job_counts: { done: 17, running: 1 },
      refresh_started_at: "2026-09-09T02:00:00",
      recovery_job_count: 18,
      recovery_job_counts: { done: 17, running: 1 },
      recovery_started_at: "2026-09-09T02:00:00",
    },
  ]) {
    const walkforwardState = clone(valid);
    walkforwardState.weekly_walkforward = driver;
    assert.equal(isMetaProjection(walkforwardState), true, driver.status);
  }

  const terminal = clone(valid);
  terminal.forward_review.status = "CONTINUE";
  terminal.forward_review.shared_sessions = 200;
  terminal.xs_forward_review.status = "PASS-FORWARD";
  terminal.xs_forward_review.paired_complete_months = 48;
  terminal.e1_forward.status = "SURVIVED";
  terminal.e1_forward.observations = 40;
  assert.equal(isMetaProjection(terminal), true);

  const currentEvidence = clone(valid);
  currentEvidence.miner_evidence.status = "current";
  currentEvidence.miner_evidence.current = 4;
  currentEvidence.miner_evidence.miners.fundamentals.status = "current";
  currentEvidence.sweep_evidence = {
    status: "current",
    current_charters: 1,
    open_charters: 1,
    charters: [
      {
        grid: "probe",
        charter_version: "charter-v1",
        status: "current",
        job_id: 1,
        job_state: "done",
        job_updated_at: "2026-09-05T07:00:00",
        generated_at: "2026-09-05T07:00:00+00:00",
        n_trials: 2,
      },
    ],
  };
  assert.equal(isMetaProjection(currentEvidence), true);

  const leakedSweepRanking = clone(currentEvidence);
  leakedSweepRanking.sweep_evidence.charters[0].ranking = "/private/ranking.json";
  assert.equal(isMetaProjection(leakedSweepRanking), false);

  const unexpectedSweepField = clone(currentEvidence);
  unexpectedSweepField.sweep_evidence.charters[0].internal = "not public";
  assert.equal(isMetaProjection(unexpectedSweepField), false);

  const unexpectedSweepEnvelopeField = clone(currentEvidence);
  unexpectedSweepEnvelopeField.sweep_evidence.internal = "not public";
  assert.equal(isMetaProjection(unexpectedSweepEnvelopeField), false);

  for (const [status, charter] of [
    [
      "incomplete",
      {
        grid: "probe",
        charter_version: "charter-v1",
        status: "missing",
        reason: "job-missing",
      },
    ],
    [
      "updating",
      {
        grid: "probe",
        charter_version: "charter-v1",
        status: "running",
        job_id: 1,
        job_state: "running",
        job_updated_at: null,
        reason: "latest-job-not-done",
      },
    ],
    [
      "invalid",
      {
        grid: "probe",
        charter_version: "charter-v1",
        status: "invalid",
        job_id: 1,
        job_state: "done",
        job_updated_at: "2026-09-05T07:00:00",
        reason: "ranking-invalid",
      },
    ],
    [
      "stale",
      {
        grid: "probe",
        charter_version: "charter-v1",
        status: "stale",
        job_id: 1,
        job_state: "done",
        job_updated_at: "2026-09-05T07:00:00",
        generated_at: "2026-09-05T05:00:00+00:00",
        n_trials: 2,
        reason: "ranking-predates-latest-job",
      },
    ],
  ]) {
    const alternateSweep = clone(valid);
    alternateSweep.sweep_evidence = {
      status,
      current_charters: 0,
      open_charters: 1,
      charters: [charter],
    };
    assert.equal(isMetaProjection(alternateSweep), true, status);
  }
});

test("meta projection requires bounded coherent walk-forward diagnostics", () => {
  const bounded = validMeta();
  Object.assign(bounded.walkforward_evidence, {
    status: "incomplete",
    expected_results: 3,
    available_results: 0,
    diagnostic_list_limit: 2,
    missing_results: ["alpha", "beta"],
    missing_results_count: 3,
    missing_results_truncated: true,
  });
  assert.equal(isMetaProjection(bounded), true);

  for (const mutate of [
    (value) => (value.missing_results = ["beta", "alpha"]),
    (value) => (value.missing_results = ["alpha", "alpha"]),
    (value) => (value.missing_results_count = 2),
    (value) => (value.missing_results_truncated = false),
    (value) => delete value.missing_results_values_truncated,
  ]) {
    const malformed = clone(bounded);
    mutate(malformed.walkforward_evidence);
    assert.equal(isMetaProjection(malformed), false);
  }

  const clippedPrefixes = validMeta();
  Object.assign(clippedPrefixes.walkforward_evidence, {
    status: "incomplete",
    expected_results: 2,
    available_results: 0,
    diagnostic_value_max_chars: 3,
    missing_results: ["abc", "abc"],
    missing_results_count: 2,
    missing_results_values_truncated: true,
  });
  assert.equal(isMetaProjection(clippedPrefixes), true);

  const falseClippingClaim = clone(clippedPrefixes);
  falseClippingClaim.walkforward_evidence.missing_results = ["ab", "ac"];
  assert.equal(isMetaProjection(falseClippingClaim), false);

  const unicodeCodePoints = validMeta();
  Object.assign(unicodeCodePoints.walkforward_evidence, {
    status: "incomplete",
    expected_results: 1,
    available_results: 0,
    diagnostic_value_max_chars: 2,
    missing_results: ["💥💥"],
    missing_results_count: 1,
    missing_results_values_truncated: true,
  });
  assert.equal(isMetaProjection(unicodeCodePoints), true);
});

test("meta projection requires bounded coherent price-quarantine details", () => {
  const valid = validMeta();
  valid.price_quarantines = [
    {
      ticker: "AAA",
      reason: "confirmed bad split",
      evidence: "manual source comparison",
      confirmed_at: "2026-09-04T12:00:00+00:00",
      detail_truncated: false,
    },
  ];
  valid.price_quarantines_matching_count = 1;
  assert.equal(isMetaProjection(valid), true);

  for (const mutate of [
    (value) => (value.price_quarantines_matching_count = 2),
    (value) => (value.price_quarantines_limit = 0),
    (value) => (value.price_quarantines_truncated = true),
    (value) => (value.price_quarantines[0].ticker = " "),
    (value) => (value.price_quarantines[0].ticker = "AAA\nBAD"),
    (value) => (value.price_quarantines[0].ticker = "A".repeat(33)),
    (value) => (value.price_quarantines[0].reason = ""),
    (value) => (value.price_quarantines[0].evidence = ""),
    (value) => (value.price_quarantines[0].confirmed_at = "2026-09-04"),
    (value) => (value.price_quarantines[0].detail_truncated = "false"),
    (value) => (value.price_quarantines[0].detail_truncated = true),
    (value) => (value.price_quarantines[0].internal = "not public"),
  ]) {
    const malformed = clone(valid);
    mutate(malformed);
    assert.equal(isMetaProjection(malformed), false);
  }

  const bounded = clone(valid);
  bounded.price_quarantines_limit = 1;
  bounded.price_quarantines_matching_count = 2;
  bounded.price_quarantines_truncated = true;
  assert.equal(isMetaProjection(bounded), true);

  const truncatedDetail = clone(valid);
  truncatedDetail.price_quarantines[0].reason = "x".repeat(1024);
  truncatedDetail.price_quarantines[0].detail_truncated = true;
  assert.equal(isMetaProjection(truncatedDetail), true);

  const truncatedUnicodeDetail = clone(valid);
  truncatedUnicodeDetail.price_quarantines[0].evidence = "💥".repeat(1024);
  truncatedUnicodeDetail.price_quarantines[0].detail_truncated = true;
  assert.equal(isMetaProjection(truncatedUnicodeDetail), true);

  const unordered = clone(valid);
  unordered.price_quarantines = [
    { ...valid.price_quarantines[0], ticker: "BBB" },
    valid.price_quarantines[0],
  ];
  unordered.price_quarantines_matching_count = 2;
  assert.equal(isMetaProjection(unordered), false);
});

test("meta projection requires bounded coherent price-verification details", () => {
  const valid = validMeta();
  valid.price_verification = {
    status: "issues",
    reason: "disagreements-or-parse-errors",
    as_of: "2026-09-04",
    verified_at: "2026-09-07T22:40:00+00:00",
    names_selected: 162,
    names_checked: 162,
    names_agreeing: 160,
    names_disagreeing: 2,
    names_not_checked: 0,
    n_disagreements: 2,
    n_material: 1,
    n_parse_errors: 0,
    tolerance_bp: 10,
    tolerance_abs_usd: 0.01,
    material_bp: 200,
    disagreements: [
      {
        ticker: "VFLO",
        date: "2026-09-04",
        field: "close",
        store: 55.29,
        source: 85780.095,
        diff_bp: 9993.55,
      },
      {
        ticker: "VTEC",
        date: "2026-09-03",
        field: "open",
        store: 96.35,
        source: 96.947,
        diff_bp: 61.58,
      },
    ],
    disagreements_limit: 20,
    disagreements_matching_count: 2,
    disagreements_truncated: false,
  };
  assert.equal(isMetaProjection(valid), true);

  for (const mutate of [
    (value) => {
      value.price_verification.status = "current";
      delete value.price_verification.reason;
    },
    (value) => {
      value.price_verification.status = "partial";
      value.price_verification.reason = "selected-names-not-checked";
    },
    (value) => (value.price_verification.reason = "selected-names-not-checked"),
    (value) => (value.price_verification.disagreements_matching_count = 1),
    (value) => (value.price_verification.disagreements_limit = 21),
    (value) => (value.price_verification.disagreements_truncated = true),
    (value) => (value.price_verification.disagreements[0].ticker = " "),
    (value) => (value.price_verification.disagreements[0].date = "2026-09-05"),
    (value) => (value.price_verification.disagreements[0].field = "volume"),
    (value) => (value.price_verification.disagreements[0].store = 0),
    (value) => (value.price_verification.disagreements[0].source = Infinity),
    (value) => (value.price_verification.disagreements[0].diff_bp = -1),
    (value) => (value.price_verification.disagreements[0].diff_bp = 9993.54),
    (value) => (value.price_verification.disagreements[0].diff_bp = 9993.56),
    (value) => (value.price_verification.tolerance_bp = 0),
    (value) => (value.price_verification.tolerance_abs_usd = Infinity),
    (value) => (value.price_verification.material_bp = 9),
    (value) => (value.price_verification.material_bp = Infinity),
    (value) => (value.price_verification.n_material = 0),
    (value) => (value.price_verification.disagreements[0].internal = "not public"),
    (value) => (value.price_verification.disagreements[1].diff_bp = 9994),
    (value) =>
      (value.price_verification.disagreements[1] = {
        ...value.price_verification.disagreements[0],
      }),
  ]) {
    const malformed = clone(valid);
    mutate(malformed);
    assert.equal(isMetaProjection(malformed), false);
  }

  const bounded = clone(valid);
  bounded.price_verification.disagreements = Array.from({ length: 20 }, (_, index) => ({
    ticker: `T${index}`,
    date: "2026-09-04",
    field: "close",
    store: 100,
    source: 101.9 - index * 0.05,
    diff_bp: Number(
      (((1.9 - index * 0.05) / (101.9 - index * 0.05)) * 10000).toFixed(2),
    ),
  }));
  bounded.price_verification.names_agreeing = 142;
  bounded.price_verification.names_disagreeing = 20;
  bounded.price_verification.n_disagreements = 21;
  bounded.price_verification.n_material = 0;
  bounded.price_verification.disagreements_matching_count = 21;
  bounded.price_verification.disagreements_truncated = true;
  assert.equal(isMetaProjection(bounded), true);

  const cleanIssues = validMeta();
  cleanIssues.price_verification.status = "issues";
  cleanIssues.price_verification.reason = "disagreements-or-parse-errors";
  assert.equal(isMetaProjection(cleanIssues), false);

  const partial = validMeta();
  partial.price_verification.status = "partial";
  partial.price_verification.reason = "selected-names-not-checked";
  partial.price_verification.names_checked = 161;
  partial.price_verification.names_agreeing = 161;
  partial.price_verification.names_not_checked = 1;
  assert.equal(isMetaProjection(partial), true);

  const incomplete = validMeta();
  incomplete.price_verification.status = "incomplete";
  incomplete.price_verification.reason = "no-names-checked";
  incomplete.price_verification.names_checked = 0;
  incomplete.price_verification.names_agreeing = 0;
  incomplete.price_verification.names_not_checked = 162;
  assert.equal(isMetaProjection(incomplete), true);

  const staleNightly = validMeta();
  staleNightly.price_verification.status = "stale";
  staleNightly.price_verification.reason = "not-refreshed-by-latest-nightly";
  staleNightly.nightly = {
    status: "ok",
    name: "run_daily",
    started_at: "2026-09-07T22:50:00Z",
    finished_at: "2026-09-07T23:00:00Z",
  };
  assert.equal(isMetaProjection(staleNightly), true);

  const falseStaleNightly = clone(staleNightly);
  falseStaleNightly.price_verification.verified_at = "2026-09-07T22:55:00+00:00";
  assert.equal(isMetaProjection(falseStaleNightly), false);

  const preciseStaleNightly = validMeta();
  preciseStaleNightly.price_verification.status = "stale";
  preciseStaleNightly.price_verification.reason = "not-refreshed-by-latest-nightly";
  preciseStaleNightly.price_verification.verified_at =
    "2026-09-07T22:40:00.000001+00:00";
  preciseStaleNightly.nightly = {
    status: "ok",
    name: "run_daily",
    started_at: "2026-09-07T22:40:00Z",
    finished_at: "2026-09-07T23:00:00Z",
  };
  assert.equal(
    Date.parse(preciseStaleNightly.price_verification.verified_at),
    Date.parse(preciseStaleNightly.nightly.started_at),
  );
  assert.equal(isMetaProjection(preciseStaleNightly), false);
  preciseStaleNightly.price_verification.verified_at =
    "2026-09-07T22:39:59.999999+00:00";
  assert.equal(isMetaProjection(preciseStaleNightly), true);

  const malformedSparse = validMeta();
  malformedSparse.price_verification = { status: "invalid", reason: "arbitrary" };
  assert.equal(isMetaProjection(malformedSparse), false);
});

test("meta projection requires exact ordered unique stale-exposure rows", () => {
  const valid = validMeta();
  valid.stale_exposure = {
    as_of: "2026-09-04",
    ticker_count: 4,
    position_count: 2,
    pending_order_count: 2,
    positions: [
      { portfolio_id: "book-a", ticker: "AAA", qty: 1, last_traded: null },
      { portfolio_id: "book-b", ticker: "BBB", qty: 2, last_traded: "2026-09-03" },
    ],
    positions_limit: 100,
    positions_truncated: false,
    pending_orders: [
      {
        id: 2,
        portfolio_id: "book-a",
        ticker: "CCC",
        side: "buy",
        qty: 3,
        signal_date: "2026-09-04",
        last_traded: null,
      },
      {
        id: 1,
        portfolio_id: "book-b",
        ticker: "DDD",
        side: "sell",
        qty: 4,
        signal_date: "2026-09-03",
        last_traded: "2026-09-02",
      },
    ],
    pending_orders_limit: 100,
    pending_orders_truncated: false,
  };
  assert.equal(isMetaProjection(valid), true);

  for (const mutate of [
    (value) => value.stale_exposure.positions.reverse(),
    (value) => value.stale_exposure.pending_orders.reverse(),
    (value) => {
      value.stale_exposure.positions[1] = { ...value.stale_exposure.positions[0] };
      value.stale_exposure.ticker_count = 3;
    },
    (value) => {
      value.stale_exposure.pending_orders[1].id = 2;
    },
  ]) {
    const malformed = clone(valid);
    mutate(malformed);
    assert.equal(isMetaProjection(malformed), false);
  }

  const unicodeOrder = clone(valid);
  unicodeOrder.stale_exposure.positions = [
    { portfolio_id: "\uf900", ticker: "AAA", qty: 1, last_traded: null },
    { portfolio_id: "𐀀", ticker: "BBB", qty: 2, last_traded: null },
  ];
  assert.equal(isMetaProjection(unicodeOrder), true);
});

test("meta projection rejects nested values that could misstate runtime evidence", () => {
  const response = validMeta();
  response.meta = { regime: "risk-off", screen_date: "2026-09-04" };
  response.meta_file = { status: "missing" };
  response.latest_prices_date = null;
  response.latest_prices_date = null;
  response.freshness_days = null;
  response.market_freshness = {
    status: "unknown",
    as_of: "2026-09-12",
    latest_date: null,
    calendar_days: null,
    missing_completed_sessions: null,
    first_missing_session: null,
    last_missing_session: null,
    next_session: null,
  };
  response.price_verification = { status: "missing" };
  response.queue = {
    counts: { failed: 1 },
    actionable_failure_count: 0,
    actionable_failures: [],
    actionable_failures_limit: 100,
    actionable_failures_truncated: false,
    historical_failure_count: 1,
    historical_failures: [
      {
        id: 7,
        kind: "sweep",
        updated_at: "2026-09-05T20:00:23.920443+00:00",
        classification: "recurring sweep charter is closed",
      },
    ],
    historical_failures_limit: 100,
    historical_failures_truncated: false,
    latest_research_job: {
      id: 8,
      kind: "walkforward",
      state: "done",
      updated_at: "2026-09-06T20:00:23.920443+00:00",
    },
  };
  response.nightly_evidence = { status: "missing" };
  response.miner_evidence = {
    status: "unknown",
    current: 0,
    expected: 4,
    miners: {
      intraday: { status: "unknown" },
      signals: { status: "unknown" },
      earnings: { status: "unknown" },
      fundamentals: { status: "unknown" },
    },
  };
  response.scheduler = {
    status: "invalid",
    reason: "projection-error",
    cron_service: "unknown",
    cron_service_unit: null,
    cron_service_enabled: "unknown",
    timezone: "unknown",
    expected_timezone: "UTC",
    timezone_ok: false,
    expected_entries: 5,
    matched_entries: 0,
    missing_drivers: [],
    duplicate_drivers: [],
    auxiliary_expected_entries: 1,
    auxiliary_matched_entries: 0,
    missing_auxiliary_entries: [],
    duplicate_auxiliary_entries: [],
    unlaunchable_auxiliary_entries: [],
    unexecutable_drivers: [],
    unsafe_log_targets: [],
    log_directory_writable: false,
  };
  response.source_control = {
    status: "invalid",
    reason: "projection-error",
    branch: null,
    remote: null,
    upstream: null,
    ahead: null,
    behind: null,
    network_checked: false,
  };
  response.nightly = null;
  response.weekly_verify = null;
  response.weekly_sweeps = null;
  response.weekly_walkforward = {
    status: "overdue",
    name: "run_weekly_walkforward",
    reason: "missed-schedule",
    expected_at: "2026-09-13T06:00:00Z",
    previous_status: "missing",
  };
  response.walkforward_evidence.status = "incomplete";
  response.forward_review = { status: "INVALID", paper_only: true, automatic_action: "none" };
  response.xs_forward_review = clone(response.forward_review);
  response.e1_forward = clone(response.forward_review);
  assert.equal(isMetaProjection(response), true);

  const unicodeFailureKind = clone(response);
  unicodeFailureKind.queue.historical_failures[0].kind = "💥".repeat(64);
  assert.equal(isMetaProjection(unicodeFailureKind), true);
  unicodeFailureKind.queue.historical_failures[0].kind += "💥";
  assert.equal(isMetaProjection(unicodeFailureKind), false);

  const orderedFailures = clone(response);
  orderedFailures.queue.counts.failed = 2;
  orderedFailures.queue.historical_failure_count = 2;
  orderedFailures.queue.historical_failures.unshift({
    id: 8,
    kind: "sweep",
    updated_at: "2026-09-05T20:00:23.920444+00:00",
    classification: "recurring sweep charter is closed",
  });
  assert.equal(isMetaProjection(orderedFailures), true);
  orderedFailures.queue.historical_failures.reverse();
  assert.equal(isMetaProjection(orderedFailures), false);

  const duplicateFailureId = clone(response);
  duplicateFailureId.queue.counts.failed = 2;
  duplicateFailureId.queue.actionable_failure_count = 1;
  duplicateFailureId.queue.actionable_failures = [
    {
      id: 7,
      kind: "signals",
      updated_at: "2026-09-06T20:00:23.920443+00:00",
    },
  ];
  assert.equal(isMetaProjection(duplicateFailureId), false);

  const inventedFailureLimit = clone(response);
  inventedFailureLimit.queue.historical_failures_limit = 1;
  assert.equal(isMetaProjection(inventedFailureLimit), false);

  const noncanonicalQueueTimestamp = clone(response);
  noncanonicalQueueTimestamp.queue.historical_failures[0].updated_at =
    "2026-09-05T20:00:23.920443Z";
  assert.equal(isMetaProjection(noncanonicalQueueTimestamp), false);

  for (const mutate of [
    (value) => (value.meta.screen_date = "2026-02-30"),
    (value) => (value.meta.last_run = "2026-09-07T22:30:11"),
    (value) => (value.meta.private_producer_detail = { rows: [1, 2, 3] }),
    (value) => (value.internal = "not public"),
    (value) => (value.meta_file = { status: "invalid" }),
    (value) =>
      (value.meta_file = {
        status: "invalid",
        reason: "malformed",
        detail: "private filesystem detail",
      }),
    (value) => (value.meta_file = { status: "ok", reason: "malformed" }),
    (value) => (value.meta_file = { status: "ok", path: "/private/data/_meta.json" }),
    (value) => (value.market_freshness.missing_completed_sessions = "0"),
    (value) => (value.market_freshness.internal = "not public"),
    (value) => (value.freshness_days = 4),
    (value) => (value.price_verification.names_selected = 10),
    (value) => (value.price_verification.disagreements_matching_count = 1),
    (value) => (value.price_verification.disagreements_limit = 0),
    (value) => (value.price_verification.internal = "not public"),
    (value) => (value.queue.counts.running = -1),
    (value) => (value.queue.counts.invented = 0),
    (value) => (value.queue.internal = "not public"),
    (value) => (value.queue.actionable_failure_count = "0"),
    (value) => (value.queue.actionable_failure_count = 1),
    (value) => (value.queue.actionable_failures_limit = 0),
    (value) => (value.queue.actionable_failures_truncated = true),
    (value) => (value.queue.historical_failure_count = 2),
    (value) => (value.queue.historical_failures_limit = "100"),
    (value) => (value.queue.latest_research_job.state = "complete"),
    (value) => (value.queue.latest_research_job.updated_at = "20260906T200023Z"),
    (value) => (value.queue.latest_research_job.updated_at = "2026-09-06T20:00:23"),
    (value) => (value.queue.latest_research_job.last_error = "internal error"),
    (value) => (value.queue.historical_failures[0].id = "7"),
    (value) => (value.queue.historical_failures[0].params = '{"grid":"closed"}'),
    (value) => delete value.queue.historical_failures[0].classification,
    (value) => (value.queue.historical_failures[0].classification = "closed"),
    (value) => (value.queue.historical_failures[0].updated_at = []),
    (value) => (value.queue.historical_failures[0].updated_at = "2026-09-05T20:00:23"),
    (value) => (value.nightly.status = "healthy"),
    (value) => (value.weekly_liquidity = { status: "recovered" }),
    (value) => (value.weekly_verify = { status: "updating" }),
    (value) => (value.weekly_sweeps = { status: "missing" }),
    (value) => (value.nightly.log = "/private/logs/cron.log"),
    (value) => (value.nightly.internal = "not public"),
    (value) => (value.nightly.command = ["python", "private.py"]),
    (value) => (value.nightly.path = "/private/repository"),
    (value) => (value.nightly.started_at = "20260912T020001Z"),
    (value) => (value.nightly.started_at = "2026-09-07T22:30:01+00:00"),
    (value) => (value.nightly.started_at = "2026-09-07T22:30:01.1Z"),
    (value) => (value.nightly.name = "run_weekly_verify"),
    (value) => {
      value.weekly_verify = {
        status: "stale-running",
        name: "run_daily",
        started_at: "2026-09-12T02:00:01Z",
        reason: "runtime-exceeded",
        lock_held: true,
      };
    },
    (value) => delete value.nightly.finished_at,
    (value) => (value.nightly.exit_code = -1),
    (value) => (value.nightly.lock_held = "true"),
    (value) => (value.nightly.lock_held = false),
    (value) => (value.nightly.previous_status = "failed"),
    (value) => (value.nightly.expected_name = "run_daily"),
    (value) => {
      value.weekly_verify = {
        status: "running",
        name: "run_weekly_verify",
        started_at: "2026-09-12T02:00:01Z",
        reason: "runtime-exceeded",
      };
    },
    (value) => {
      value.weekly_sweeps = {
        status: "failed",
        name: "run_weekend_sweeps",
        started_at: "2026-09-12T06:00:01Z",
        finished_at: "2026-09-12T06:01:01Z",
        exit_code: 1,
        reason: "worker-error",
      };
    },
    (value) => {
      value.weekly_sweeps = {
        status: "failed",
        name: "run_weekend_sweeps",
        started_at: "2026-09-12T06:00:01Z",
        finished_at: "2026-09-12T06:01:01Z",
      };
    },
    (value) => {
      value.weekly_walkforward = {
        ...clone(validMeta().weekly_walkforward),
        refresh_job_count: 17,
      };
    },
    (value) => {
      value.weekly_walkforward = {
        status: "updating",
        name: "run_weekly_walkforward",
        started_at: "2026-09-06T06:00:01Z",
        reason: "stale-start",
        previous_status: "interrupted",
        refresh_job_count: 18,
        refresh_job_counts: { done: 17, running: 1 },
        refresh_started_at: "2026-09-09T02:00:00",
      };
    },
    (value) => {
      value.weekly_walkforward = {
        ...clone(validMeta().weekly_walkforward),
        refresh_job_counts: { invented: 18 },
      };
    },
    (value) => {
      value.weekly_walkforward = { status: "recovered", refresh_job_count: 18 };
    },
    (value) => {
      value.weekly_walkforward = {
        ...clone(validMeta().weekly_walkforward),
        recovery_job_counts: { done: 17 },
      };
    },
    (value) => {
      value.weekly_walkforward = clone(validMeta().weekly_walkforward);
      delete value.weekly_walkforward.refreshed_at;
    },
    (value) => {
      value.weekly_walkforward = {
        ...clone(validMeta().weekly_walkforward),
        recovered_at: "2026-09-09T02:21:40",
      };
    },
    (value) => {
      value.weekly_walkforward = {
        ...clone(validMeta().weekly_walkforward),
        previous_status: "ok",
      };
    },
    (value) => {
      value.weekly_walkforward = {
        status: "updating",
        name: "run_weekly_walkforward",
        started_at: "2026-09-06T06:00:01Z",
        finished_at: "2026-09-06T07:00:01Z",
        exit_code: 1,
        previous_status: "ok",
        refresh_job_count: 18,
        refresh_job_counts: { done: 17, running: 1 },
        refresh_started_at: "2026-09-09T02:00:00",
      };
    },
    (value) => (value.miner_evidence.current = 5),
    (value) => (value.miner_evidence.current = 1),
    (value) => (value.miner_evidence.status = "current"),
    (value) => (value.miner_evidence.miners.fundamentals.status = "invented"),
    (value) => (value.sweep_evidence.open_charters = -1),
    (value) => (value.sweep_evidence.open_charters = 1),
    (value) => {
      value.sweep_evidence.status = "current";
    },
    (value) => (value.stale_exposure.position_count = "0"),
    (value) => (value.stale_exposure.ticker_count = 1),
    (value) => (value.stale_exposure.positions_limit = 0),
    (value) => (value.stale_exposure.positions_limit = 101),
    (value) => (value.stale_exposure.positions_truncated = true),
    (value) => (value.stale_exposure.pending_orders_limit = "100"),
    (value) => (value.stale_exposure.internal = "not public"),
    (value) => {
      value.stale_exposure.pending_orders = [{
        id: Number.MAX_SAFE_INTEGER + 1,
        portfolio_id: "book",
        ticker: "AAA",
        side: "buy",
        qty: 1,
        signal_date: "2026-09-04",
        last_traded: null,
      }];
      value.stale_exposure.ticker_count = 1;
      value.stale_exposure.pending_order_count = 1;
    },
    (value) => {
      value.stale_exposure.positions = [{
        portfolio_id: "book\nother",
        ticker: "STALE",
        qty: 1,
        last_traded: null,
      }];
      value.stale_exposure.ticker_count = 1;
      value.stale_exposure.position_count = 1;
    },
    (value) => {
      value.stale_exposure.positions = [{
        portfolio_id: "book",
        ticker: "STALE",
        qty: 1,
        last_traded: null,
        internal: "not public",
      }];
      value.stale_exposure.ticker_count = 1;
      value.stale_exposure.position_count = 1;
    },
    (value) => {
      value.stale_exposure.pending_orders = [{
        id: 1,
        portfolio_id: "book",
        ticker: "STALE",
        side: "buy",
        qty: 1,
        signal_date: "2026-09-05",
        last_traded: null,
      }];
      value.stale_exposure.ticker_count = 1;
      value.stale_exposure.pending_order_count = 1;
    },
    (value) => {
      value.stale_exposure.positions = [{
        portfolio_id: "book",
        ticker: "STALE",
        qty: 1,
        last_traded: null,
      }];
      value.stale_exposure.ticker_count = 1;
      value.stale_exposure.position_count = 1;
      value.stale_exposure.as_of = null;
    },
    (value) => {
      value.stale_exposure.positions = [{
        portfolio_id: "book",
        ticker: "STALE\nBAD",
        qty: 1,
        last_traded: null,
      }];
      value.stale_exposure.ticker_count = 1;
      value.stale_exposure.position_count = 1;
    },
    (value) => (value.scheduler.matched_entries = 6),
    (value) => (value.scheduler.auxiliary_matched_entries = 2),
    (value) => (value.scheduler.status = "misconfigured"),
    (value) => (value.scheduler.status = "inactive"),
    (value) => (value.scheduler.status = "unknown"),
    (value) => (value.scheduler.expected_entries = 6),
    (value) => (value.scheduler.auxiliary_expected_entries = 2),
    (value) => (value.scheduler.cron_service = "invented"),
    (value) => (value.scheduler.cron_service_enabled = "invented"),
    (value) => (value.scheduler.cron_service_unit = "invented.service"),
    (value) => {
      value.scheduler.cron_service = "active";
      value.scheduler.cron_service_unit = null;
      value.scheduler.cron_service_enabled = "enabled";
    },
    (value) => {
      value.scheduler.status = "unknown";
      value.scheduler.cron_service = "unknown";
      value.scheduler.cron_service_unit = "cron";
      value.scheduler.cron_service_enabled = "unknown";
    },
    (value) => (value.scheduler.missing_drivers = ["invented"]),
    (value) => (value.scheduler.duplicate_drivers = ["run_daily", "run_daily"]),
    (value) => (value.scheduler.unexecutable_drivers = ["run_daily", "run_daily"]),
    (value) => (value.scheduler.timezone_ok = true),
    (value) => (value.scheduler.timezone = "UTC\nEtc/UTC"),
    (value) => (value.scheduler.timezone = "x".repeat(256)),
    (value) => (value.friday_postflight.status = "healthy"),
    (value) => (value.friday_postflight = { status: "invalid", reason: "invented" }),
    (value) => (value.friday_postflight.next_expected_at = "20260912T051500Z"),
    (value) => (value.friday_postflight.next_expected_at = "2026-09-19T05:15:00+00:00"),
    (value) => (value.friday_postflight.internal = "not public"),
    (value) => (value.scheduler.missing_drivers = [""]),
    (value) => (value.scheduler.missing_auxiliary_entries = [""]),
    (value) => (value.scheduler.unlaunchable_auxiliary_entries = [""]),
    (value) => (value.scheduler.unsafe_log_targets = [""]),
    (value) => delete value.scheduler.unsafe_log_targets,
    (value) => (value.scheduler.internal = "not public"),
    (value) => (value.source_control.ahead = -1),
    (value) => (value.source_control.ahead = Number.MAX_SAFE_INTEGER + 1),
    (value) => (value.source_control.behind = Number.MAX_SAFE_INTEGER + 1),
    (value) => (value.source_control.internal = "not public"),
    (value) => (value.source_control.network_checked = true),
    (value) => (value.source_control.branch = "main\nother"),
    (value) => (value.source_control.branch = "x".repeat(4097)),
    (value) => {
      value.source_control = {
        status: "current",
        reason: null,
        branch: "main",
        remote: "origin\tmirror",
        upstream: "origin/main",
        ahead: 0,
        behind: 0,
        network_checked: false,
      };
    },
    (value) => {
      value.source_control = {
        status: "current",
        reason: null,
        branch: "main",
        remote: "origin",
        upstream: "u".repeat(4097),
        ahead: 0,
        behind: 0,
        network_checked: false,
      };
    },
    (value) => (value.source_control = {
      status: "invalid",
      reason: "invented",
      branch: null,
      remote: null,
      upstream: null,
      ahead: null,
      behind: null,
      network_checked: false,
    }),
    (value) => (value.source_control = {
      status: "invalid",
      reason: "git-unavailable",
      branch: "main",
      remote: null,
      upstream: null,
      ahead: null,
      behind: null,
      network_checked: false,
    }),
    (value) => {
      value.source_control = {
        status: "current",
        reason: null,
        branch: "main",
        remote: "origin",
        upstream: "origin/main",
        ahead: 1,
        behind: 0,
        network_checked: false,
      };
    },
    (value) => (value.walkforward_evidence.status = "fine"),
    (value) => (value.walkforward_evidence.status = "ok"),
    (value) => (value.miner_evidence.status = "idle"),
    (value) => (value.sweep_evidence.status = "unknown"),
    (value) => (value.nightly_evidence.status = "not-yet-run"),
    (value) => (value.liquidity_evidence.status = "mixed-cohort"),
    (value) => (value.forward_review.paper_only = false),
    (value) => (value.xs_forward_review.automatic_action = "promote"),
    (value) => (value.e1_forward.status = "PROFITABLE"),
    (value) => (value.forward_review.shared_sessions = 1),
  ]) {
    const malformed = clone(response);
    if (malformed.nightly === null) {
      malformed.nightly = {
        status: "ok",
        name: "run_daily",
        started_at: "2026-09-11T22:30:01Z",
        finished_at: "2026-09-12T00:30:01Z",
      };
    }
    mutate(malformed);
    assert.equal(isMetaProjection(malformed), false, mutate.toString());
  }

  const terminalBeforeEvidence = clone(validMeta());
  terminalBeforeEvidence.forward_review.status = "CONTINUE";
  assert.equal(isMetaProjection(terminalBeforeEvidence), false);

  const prematureE1Verdict = clone(validMeta());
  prematureE1Verdict.e1_forward.status = "SURVIVED";
  assert.equal(isMetaProjection(prematureE1Verdict), false);

  for (const mutate of [
    (value) => (value.expected_date = "2026-09-10"),
    (value) => (value.checked_at = "2026-09-12T05:14:59+00:00"),
    (value) => (value.nightly_started_at = "2026-09-10T22:30:01+00:00"),
    (value) => (value.nightly_finished_at = "2026-09-12T05:16:00+00:00"),
    (value) => (value.miner_evidence_at.fundamentals = "2026-09-12T00:31:00+00:00"),
    (value) => (value.internal = "not public"),
  ]) {
    const malformedPostflight = validCurrentPostflightMeta();
    mutate(malformedPostflight.friday_postflight);
    assert.equal(isMetaProjection(malformedPostflight), false);
  }

  for (const mutate of [
    (value) => (value.expected_date = "2026-09-17"),
    (value) => (value.expected_at = "2026-09-19T05:14:59+00:00"),
    (value) => (value.expected_at = "2026-09-20T05:15:00+00:00"),
  ]) {
    const malformedSchedule = clone(validMeta());
    malformedSchedule.friday_postflight = {
      status: "overdue",
      expected_date: "2026-09-18",
      expected_at: "2026-09-19T05:15:00+00:00",
    };
    mutate(malformedSchedule.friday_postflight);
    assert.equal(isMetaProjection(malformedSchedule), false);
  }

  const prematureStaleReceipt = clone(validMeta());
  prematureStaleReceipt.friday_postflight = {
    status: "stale",
    expected_date: "2026-09-18",
    expected_at: "2026-09-19T05:15:00+00:00",
    observed_expected_date: "2026-09-11",
    checked_at: "2026-09-12T05:14:59+00:00",
  };
  assert.equal(isMetaProjection(prematureStaleReceipt), false);
});
