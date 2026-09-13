"""Tests for expected-slot and aggregate scheduled-driver monitoring."""

from datetime import datetime, timedelta, timezone

import pytest

from server import driver_monitor


def test_scheduled_driver_status_preserves_current_slot_result():
    status = {
        "name": "run_daily",
        "started_at": "2026-09-07T22:30:01Z",
        "status": "ok",
    }
    result = driver_monitor.scheduled_driver_status(
        status,
        name="run_daily",
        weekdays=(0, 1, 2, 3, 4),
        hour=22,
        minute=30,
        grace=timedelta(hours=6),
        now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
    )
    assert result == status


def test_scheduled_driver_status_marks_missed_slot_overdue():
    old = {
        "name": "run_daily",
        "started_at": "2026-09-04T22:30:01Z",
        "status": "ok",
        "finished_at": "2026-09-04T23:00:00Z",
    }
    result = driver_monitor.scheduled_driver_status(
        old,
        name="run_daily",
        weekdays=(0, 1, 2, 3, 4),
        hour=22,
        minute=30,
        grace=timedelta(hours=6),
        now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
    )
    assert result == {
        **old,
        "status": "overdue",
        "reason": "missed-schedule",
        "expected_at": "2026-09-07T22:30:00Z",
        "previous_status": "ok",
    }


def test_scheduled_driver_status_waits_for_grace_period():
    old = {
        "name": "run_daily",
        "started_at": "2026-09-04T22:30:01Z",
        "status": "ok",
    }
    result = driver_monitor.scheduled_driver_status(
        old,
        name="run_daily",
        weekdays=(0, 1, 2, 3, 4),
        hour=22,
        minute=30,
        grace=timedelta(hours=6),
        now=datetime(2026, 9, 8, 4, 29, tzinfo=timezone.utc),
    )
    assert result == old


def test_scheduled_driver_status_rejects_wrong_driver_name():
    status = {
        "name": "run_weekly_verify",
        "started_at": "2026-09-07T22:30:01Z",
        "status": "ok",
    }
    result = driver_monitor.scheduled_driver_status(
        status,
        name="run_daily",
        weekdays=(0, 1, 2, 3, 4),
        hour=22,
        minute=30,
        grace=timedelta(hours=6),
        now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
    )
    assert result["status"] == "invalid"
    assert result["reason"] == "driver-name-mismatch"
    assert result["expected_name"] == "run_daily"


def test_scheduled_driver_status_rejects_wrong_stale_driver_name():
    status = {
        "name": "run_weekly_verify",
        "started_at": "2026-09-01T22:30:01Z",
        "status": "stale-running",
        "reason": "runtime-exceeded",
        "lock_held": True,
    }

    result = driver_monitor.scheduled_driver_status(
        status,
        name="run_daily",
        weekdays=(0, 1, 2, 3, 4),
        hour=22,
        minute=30,
        grace=timedelta(hours=6),
        now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
    )

    assert result == {
        **status,
        "status": "invalid",
        "reason": "driver-name-mismatch",
        "expected_name": "run_daily",
    }


def test_scheduled_driver_status_honors_first_expected_run():
    first = datetime(2026, 9, 13, 2, tzinfo=timezone.utc)
    before = driver_monitor.scheduled_driver_status(
        None,
        name="run_weekly_liquid",
        weekdays=(6,),
        hour=2,
        minute=0,
        grace=timedelta(hours=4),
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        first_expected_at=first,
    )
    assert before is None

    after = driver_monitor.scheduled_driver_status(
        None,
        name="run_weekly_liquid",
        weekdays=(6,),
        hour=2,
        minute=0,
        grace=timedelta(hours=4),
        now=datetime(2026, 9, 13, 6, tzinfo=timezone.utc),
        first_expected_at=first,
    )
    assert after == {
        "name": "run_weekly_liquid",
        "status": "overdue",
        "reason": "missed-schedule",
        "expected_at": "2026-09-13T02:00:00Z",
        "previous_status": "missing",
    }


@pytest.mark.parametrize("status_name", ["invalid", "stale-running"])
def test_scheduled_driver_status_preserves_more_specific_failure(status_name):
    status = {
        "name": "run_daily",
        "started_at": "2026-09-01T22:30:01Z",
        "status": status_name,
    }
    result = driver_monitor.scheduled_driver_status(
        status,
        name="run_daily",
        weekdays=(0, 1, 2, 3, 4),
        hour=22,
        minute=30,
        grace=timedelta(hours=6),
        now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
    )
    assert result == status


def test_driver_statuses_covers_every_installed_schedule(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    completed = {
        "cron.log": ("run_daily", "2026-09-07T22:30:01Z", "2026-09-07T23:00:00Z"),
        "verify-cron.log": (
            "run_weekly_verify",
            "2026-09-05T02:00:01Z",
            "2026-09-05T05:00:00Z",
        ),
        "sweeps-cron.log": (
            "run_weekend_sweeps",
            "2026-09-05T06:00:01Z",
            "2026-09-05T06:01:00Z",
        ),
        "walkforward-cron.log": (
            "run_weekly_walkforward",
            "2026-09-06T06:00:01Z",
            "2026-09-06T10:00:00Z",
        ),
    }
    for filename, (name, started, finished) in completed.items():
        (logs / filename).write_text(f"=== {name} {started} ===\n=== done {finished} ===\n")

    result = driver_monitor.driver_statuses(
        logs_dir=logs,
        repo_root=tmp_path,
        now=datetime(2026, 9, 8, 2, tzinfo=timezone.utc),
    )
    assert set(result) == {
        "nightly",
        "weekly_verify",
        "weekly_sweeps",
        "weekly_liquidity",
        "weekly_walkforward",
    }
    assert result["nightly"]["status"] == "ok"
    assert result["weekly_verify"]["status"] == "ok"
    assert result["weekly_sweeps"]["status"] == "ok"
    assert result["weekly_walkforward"]["status"] == "ok"
    assert result["weekly_liquidity"] is None

    overdue = driver_monitor.driver_statuses(
        logs_dir=logs,
        repo_root=tmp_path,
        now=datetime(2026, 9, 13, 6, tzinfo=timezone.utc),
    )
    assert overdue["weekly_liquidity"]["status"] == "overdue"
    assert overdue["weekly_liquidity"]["expected_at"] == "2026-09-13T02:00:00Z"
