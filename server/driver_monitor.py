"""Project scheduled-driver health against expected UTC run slots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.lib.settings import LOGS_DIR, REPO_ROOT
from server import driver_log


def _expected_completed_slot(
    checked_at: datetime,
    weekdays: tuple[int, ...],
    hour: int,
    minute: int,
    grace: timedelta,
    first_expected: datetime | None,
) -> datetime | None:
    for days_ago in range(15):
        candidate_date = checked_at.date() - timedelta(days=days_ago)
        if candidate_date.weekday() not in weekdays:
            continue
        candidate = datetime(
            candidate_date.year,
            candidate_date.month,
            candidate_date.day,
            hour,
            minute,
            tzinfo=timezone.utc,
        )
        if first_expected is not None and candidate < first_expected:
            continue
        if candidate + grace <= checked_at:
            return candidate
    return None


def _driver_name_mismatch(status: dict | None, expected_name: str) -> dict | None:
    if status is None or status.get("name") == expected_name:
        return None
    result = dict(status)
    result.update(
        status="invalid",
        reason="driver-name-mismatch",
        expected_name=expected_name,
    )
    return result


def _missed_slot(status: dict | None, expected_at: datetime | None) -> bool:
    if expected_at is None:
        return False
    if status is None:
        return True
    started_at = driver_log.utc_timestamp(str(status.get("started_at", "")))
    return started_at is not None and started_at < expected_at


def _overdue_status(status: dict | None, name: str, expected_at: datetime) -> dict:
    result = dict(status or {})
    previous_status = result.get("status", "missing")
    result.update(
        name=name,
        status="overdue",
        reason="missed-schedule",
        expected_at=expected_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        previous_status=previous_status,
    )
    return result


def scheduled_driver_status(
    status: dict | None,
    *,
    name: str,
    weekdays: tuple[int, ...],
    hour: int,
    minute: int,
    grace: timedelta,
    now: datetime | None = None,
    first_expected_at: datetime | None = None,
) -> dict | None:
    """Mark a driver overdue once a completed cron slot has no matching start."""
    checked_at = driver_log.as_utc(now or datetime.now(timezone.utc))
    first_expected = driver_log.as_utc(first_expected_at) if first_expected_at else None
    if status is not None and status.get("status") == "invalid":
        return status
    mismatch = _driver_name_mismatch(status, name)
    if mismatch is not None:
        return mismatch
    if status is not None and status.get("status") == "stale-running":
        return status
    expected_at = _expected_completed_slot(
        checked_at, weekdays, hour, minute, grace, first_expected
    )
    if not _missed_slot(status, expected_at):
        return status
    return _overdue_status(status, name, expected_at)


DRIVER_SCHEDULES = (
    (
        "nightly",
        "run_daily",
        "cron.log",
        ".nightly.lock",
        (0, 1, 2, 3, 4),
        22,
        30,
        6,
        None,
    ),
    (
        "weekly_verify",
        "run_weekly_verify",
        "verify-cron.log",
        ".verify.lock",
        (5,),
        2,
        0,
        4,
        None,
    ),
    (
        "weekly_sweeps",
        "run_weekend_sweeps",
        "sweeps-cron.log",
        ".sweeps.lock",
        (5,),
        6,
        0,
        24,
        None,
    ),
    (
        "weekly_liquidity",
        "run_weekly_liquid",
        "liquid-cron.log",
        ".liquid.lock",
        (6,),
        2,
        0,
        4,
        datetime(2026, 9, 13, 2, tzinfo=timezone.utc),
    ),
    (
        "weekly_walkforward",
        "run_weekly_walkforward",
        "walkforward-cron.log",
        ".walkforward.lock",
        (6,),
        6,
        0,
        18,
        None,
    ),
)


def _project_driver_status(
    schedule: tuple,
    *,
    logs_dir: Path,
    repo_root: Path,
    checked_at: datetime,
) -> tuple[str, dict | None]:
    key, name, log, lock, weekdays, hour, minute, grace_hours, first_expected = schedule
    grace = timedelta(hours=grace_hours)
    parsed = driver_log.driver_status(
        logs_dir / log,
        lock_path=repo_root / lock,
        now=checked_at,
        stale_after=grace,
    )
    return key, scheduled_driver_status(
        parsed,
        name=name,
        weekdays=weekdays,
        hour=hour,
        minute=minute,
        grace=grace,
        now=checked_at,
        first_expected_at=first_expected,
    )


def driver_statuses(
    *,
    logs_dir: Path = LOGS_DIR,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
) -> dict[str, dict | None]:
    """Project every installed UTC cron schedule from its log and live lock."""
    checked_at = driver_log.as_utc(now or datetime.now(timezone.utc))
    return dict(
        _project_driver_status(
            schedule,
            logs_dir=logs_dir,
            repo_root=repo_root,
            checked_at=checked_at,
        )
        for schedule in DRIVER_SCHEDULES
    )
