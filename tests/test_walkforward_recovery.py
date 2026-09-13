"""Tests for walk-forward driver recovery from queue cohorts."""

import json
from datetime import datetime

import pytest

from server import walkforward_recovery
from tests.walkforward_test_helpers import (
    failed_weekly_status,
    setup_walkforward_recovery,
)


def test_weekly_failure_is_reconciled_by_complete_later_cohort(con):
    setup_walkforward_recovery(con)
    result = walkforward_recovery.reconcile_driver_status(failed_weekly_status(), con)
    assert result["status"] == "recovered"
    assert result["previous_status"] == "failed"
    assert result["refresh_job_count"] == 2
    assert result["refresh_job_counts"] == {"done": 2}
    assert result["refreshed_at"] == "2026-09-07T08:00:01"
    assert result["recovery_job_count"] == 2
    assert result["recovery_job_counts"] == {"done": 2}
    assert result["recovered_at"] == "2026-09-07T08:00:01"


def test_weekly_failure_reports_newer_complete_cohort_in_progress(con):
    setup_walkforward_recovery(con, ("done", "running"))
    result = walkforward_recovery.reconcile_driver_status(failed_weekly_status(), con)

    assert result["status"] == "updating"
    assert result["previous_status"] == "failed"
    assert result["refresh_job_count"] == 2
    assert result["refresh_job_counts"] == {"done": 1, "running": 1}
    assert result["refresh_started_at"] == "2026-09-07T07:00:00"
    assert result["recovery_job_count"] == 2
    assert result["recovery_job_counts"] == {"done": 1, "running": 1}
    assert result["recovery_started_at"] == "2026-09-07T07:00:00"


def test_weekly_failure_is_not_hidden_by_partial_later_cohort(con):
    setup_walkforward_recovery(con, ("done",))
    result = walkforward_recovery.reconcile_driver_status(failed_weekly_status(), con)

    assert result["status"] == "failed"


def test_malformed_driver_boundary_cannot_claim_queue_recovery(con):
    setup_walkforward_recovery(con)
    status = {**failed_weekly_status(), "finished_at": "20260906T060002Z"}

    assert walkforward_recovery.reconcile_driver_status(status, con) == status


def test_newer_updating_cohort_takes_precedence_over_older_recovery(con):
    setup_walkforward_recovery(con)
    for i, (portfolio_id, state) in enumerate((("spy", "running"), ("sector", "pending")), start=3):
        con.execute(
            "INSERT INTO jobs VALUES (?, 'walkforward', ?, ?, ?, NULL, ?, ?)",
            [
                i,
                json.dumps({"config_id": portfolio_id}),
                state,
                "started" if state == "running" else "queued",
                datetime(2026, 9, 8, 7, 0, i),
                datetime(2026, 9, 8, 8, 0, i),
            ],
        )

    result = walkforward_recovery.reconcile_driver_status(failed_weekly_status(), con)

    assert result["status"] == "updating"
    assert result["recovery_job_counts"] == {"running": 1, "pending": 1}
    assert "recovered_at" not in result


def test_recovery_scan_crosses_batches_and_skips_newer_oversized_cohort(con, monkeypatch):
    setup_walkforward_recovery(con)
    monkeypatch.setattr(walkforward_recovery, "JOB_SCAN_BATCH_SIZE", 2)
    for job_id, portfolio_id in ((3, "spy"), (4, "sector"), (5, "extra")):
        con.execute(
            "INSERT INTO jobs VALUES (?, 'walkforward', ?, 'done', 'complete', NULL, ?, ?)",
            [
                job_id,
                json.dumps({"config_id": portfolio_id}),
                datetime(2026, 9, 8, 7, 0, job_id),
                datetime(2026, 9, 8, 8, 0, job_id),
            ],
        )

    result = walkforward_recovery.reconcile_driver_status(failed_weekly_status(), con)

    assert result["status"] == "recovered"
    assert result["refresh_job_count"] == 2
    assert result["refreshed_at"] == "2026-09-07T08:00:01"


@pytest.mark.parametrize("base_status", ["ok", "running"])
def test_active_exact_cohort_is_visible_after_nonfailed_driver(con, base_status):
    setup_walkforward_recovery(con, ("done", "running"))
    status = {
        "name": "run_weekly_walkforward",
        "status": base_status,
        "started_at": "2026-09-07T06:00:00Z",
        "finished_at": "2026-09-07T06:30:00Z",
    }

    result = walkforward_recovery.reconcile_driver_status(status, con)

    assert result["status"] == "updating"
    assert result["previous_status"] == base_status
    assert result["refresh_job_count"] == 2
    assert result["refresh_job_counts"] == {"done": 1, "running": 1}
    assert "recovery_job_count" not in result
