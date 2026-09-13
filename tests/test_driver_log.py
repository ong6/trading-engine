"""Tests for scheduled-driver run-log parsing."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from server import (
    driver_log,
)


def test_run_fields_fails_closed_if_timestamp_parser_has_no_result(monkeypatch):
    match = driver_log._DRIVER_START.fullmatch(
        "=== run_daily 2026-09-10T22:30:01Z ==="
    )
    assert match is not None
    monkeypatch.setattr(driver_log, "_started_at", lambda value, checked_at: (None, None))

    assert driver_log._run_fields(
        match,
        None,
        None,
        lock_path=None,
        lock_before=None,
        checked_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        stale_after=timedelta(hours=24),
    ) == {"status": "invalid", "reason": "invalid-started-at"}


def test_driver_status_reports_latest_failure(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text(
        "=== run_weekly_walkforward 2026-08-30T06:00:00Z ===\n"
        "=== done 2026-08-30T09:00:00Z ===\n"
        "=== run_weekly_walkforward 2026-09-06T06:00:01Z ===\n"
        "TODO: run_weekly_walkforward failed 2026-09-06T06:00:02Z "
        "(stage=enqueue exit 1) — inspect log\n"
    )
    assert driver_log.driver_status(log) == {
        "name": "run_weekly_walkforward",
        "started_at": "2026-09-06T06:00:01Z",
        "status": "failed",
        "log": str(log),
        "finished_at": "2026-09-06T06:00:02Z",
        "stage": "enqueue",
        "exit_code": 1,
    }


def test_driver_status_distinguishes_empty_and_malformed_logs(tmp_path):
    log = tmp_path / "cron.log"
    log.touch()
    assert driver_log.driver_status(log) is None

    log.write_text("some output without a driver marker\n")
    assert driver_log.driver_status(log) == {
        "status": "invalid",
        "reason": "missing-start-marker",
        "log": str(log),
    }


def test_driver_status_reports_unreadable_log(tmp_path, monkeypatch):
    log = tmp_path / "cron.log"
    log.write_text("content")

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(driver_log, "open_regular", denied)
    status = driver_log.driver_status(log)
    assert status["status"] == "invalid"
    assert status["reason"] == "log-unreadable"
    assert "detail" not in status


@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink", "directory", "fifo"])
def test_driver_status_rejects_non_regular_log_without_following_or_blocking(tmp_path, kind):
    log = tmp_path / "cron.log"
    if kind == "symlink":
        external = tmp_path / "external.log"
        external.write_text(
            "=== run_daily 2026-09-10T22:30:01Z ===\n"
            "=== done 2026-09-10T23:00:00Z ===\n"
        )
        log.symlink_to(external)
    elif kind == "dangling-symlink":
        log.symlink_to(tmp_path / "missing.log")
    elif kind == "directory":
        log.mkdir()
    else:
        os.mkfifo(log)

    assert driver_log.driver_status(log) == {
        "status": "invalid",
        "reason": "log-not-regular",
        "log": str(log),
    }


def test_driver_status_rejects_log_replaced_during_read(tmp_path, monkeypatch):
    log = tmp_path / "cron.log"
    log.write_text(
        "=== run_daily 2026-09-10T22:30:01Z ===\n"
        "=== done 2026-09-10T23:00:00Z ===\n"
    )
    replacement = tmp_path / "replacement.log"
    replacement.write_text(log.read_text())
    original = driver_log._latest_run_markers

    def parse_then_replace(handle, position):
        result = original(handle, position)
        replacement.replace(log)
        return result

    monkeypatch.setattr(driver_log, "_latest_run_markers", parse_then_replace)

    assert driver_log.driver_status(log) == {
        "status": "invalid",
        "reason": "log-changed-during-read",
        "log": str(log),
    }


@pytest.mark.parametrize("mutation", ["append", "truncate"])
def test_driver_status_rejects_same_inode_log_mutation_during_read(
    tmp_path, monkeypatch, mutation
):
    log = tmp_path / "cron.log"
    log.write_text(
        "=== run_daily 2026-09-10T22:30:01Z ===\n"
        "=== done 2026-09-10T23:00:00Z ===\n"
    )
    original = driver_log._latest_run_markers

    def parse_then_mutate(handle, position):
        result = original(handle, position)
        if mutation == "append":
            with log.open("ab") as destination:
                destination.write(b"later output\n")
        else:
            log.write_bytes(b"")
        return result

    monkeypatch.setattr(driver_log, "_latest_run_markers", parse_then_mutate)

    assert driver_log.driver_status(log) == {
        "status": "invalid",
        "reason": "log-changed-during-read",
        "log": str(log),
    }


def test_driver_status_reports_failure_without_stage_breadcrumb(tmp_path):
    log = tmp_path / "liquid-cron.log"
    log.write_text(
        "=== run_weekly_liquid 2026-09-06T02:00:01Z ===\n"
        "TODO: run_weekly_liquid failed 2026-09-06T02:10:02Z "
        "(exit 2) — inspect log\n"
    )
    assert driver_log.driver_status(log) == {
        "name": "run_weekly_liquid",
        "started_at": "2026-09-06T02:00:01Z",
        "status": "failed",
        "log": str(log),
        "finished_at": "2026-09-06T02:10:02Z",
        "exit_code": 2,
    }


@pytest.mark.parametrize(
    "terminals",
    [
        (
            "=== done 2026-09-10T23:00:00Z ===\n"
            "TODO: run_daily failed 2026-09-10T23:00:01Z (exit 1)\n"
        ),
        (
            "TODO: run_daily failed 2026-09-10T22:59:59Z (exit 1)\n"
            "=== done 2026-09-10T23:00:00Z ===\n"
        ),
        (
            "=== done 2026-09-10T23:00:00Z ===\n"
            "=== done 2026-09-10T23:00:01Z ===\n"
        ),
    ],
)
def test_driver_status_rejects_multiple_terminals_for_latest_run(tmp_path, terminals):
    log = tmp_path / "cron.log"
    log.write_text("=== run_daily 2026-09-10T22:30:01Z ===\n" + terminals)

    assert driver_log.driver_status(
        log, now=datetime(2026, 9, 11, tzinfo=timezone.utc)
    ) == {
        "name": "run_daily",
        "started_at": "2026-09-10T22:30:01Z",
        "status": "invalid",
        "log": str(log),
        "reason": "multiple-terminal-markers",
    }


@pytest.mark.parametrize(
    "terminal",
    [
        "=== done ===",
        "TODO: run_daily failed malformed",
    ],
)
def test_driver_status_rejects_malformed_terminal_for_latest_run(tmp_path, terminal):
    log = tmp_path / "cron.log"
    log.write_text(
        "=== run_daily 2026-09-10T22:30:01Z ===\n"
        f"{terminal}\n"
    )

    assert driver_log.driver_status(
        log, now=datetime(2026, 9, 11, tzinfo=timezone.utc)
    ) == {
        "name": "run_daily",
        "started_at": "2026-09-10T22:30:01Z",
        "status": "invalid",
        "log": str(log),
        "reason": "malformed-terminal-marker",
    }


def test_driver_status_ignores_unrelated_todo_and_manual_marker_output(tmp_path):
    log = tmp_path / "cron.log"
    log.write_text(
        "=== run_daily 2026-09-10T22:30:01Z ===\n"
        "TODO: corporate actions need review (1):\n"
        "=== marker: manual operator note ===\n"
        "=== done 2026-09-10T23:00:00Z ===\n"
    )

    assert driver_log.driver_status(
        log, now=datetime(2026, 9, 11, tzinfo=timezone.utc)
    )["status"] == "ok"


@pytest.mark.parametrize(
    "latest",
    [
        "=== run_daily ===\n",
        "=== run_daily 2026-09-10T22:30:01Z extra ===\n",
        "=== run_daily ===\n=== done 2026-09-10T23:00:00Z ===\n",
    ],
)
def test_driver_status_does_not_borrow_older_run_after_malformed_start(tmp_path, latest):
    log = tmp_path / "cron.log"
    log.write_text(
        "=== run_daily 2026-09-09T22:30:01Z ===\n"
        "=== done 2026-09-09T23:00:00Z ===\n"
        f"{latest}"
    )

    assert driver_log.driver_status(
        log, now=datetime(2026, 9, 11, tzinfo=timezone.utc)
    ) == {
        "status": "invalid",
        "reason": "malformed-start-marker",
        "log": str(log),
    }


def test_driver_status_handles_success_larger_than_one_tail_chunk(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text(
        "=== run_weekly_walkforward 2026-09-06T06:00:01Z ===\n"
        + "fold output\n" * 20_000
        + "=== done 2026-09-06T10:00:02Z ===\n"
    )
    status = driver_log.driver_status(log)
    assert status["status"] == "ok"
    assert status["name"] == "run_weekly_walkforward"
    assert status["finished_at"] == "2026-09-06T10:00:02Z"


def test_driver_status_ignores_non_marker_binary_output(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_bytes(
        b"=== run_weekly_walkforward 2026-09-06T06:00:01Z ===\n"
        + b"\xff noisy output\n" * 20_000
        + b"=== done 2026-09-06T10:00:02Z ===\n"
    )

    status = driver_log.driver_status(log)

    assert status["status"] == "ok"
    assert status["finished_at"] == "2026-09-06T10:00:02Z"


def test_driver_status_reads_start_marker_on_first_physical_line(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text(
        "=== run_weekly_walkforward 2026-09-06T06:00:01Z ===\n=== done 2026-09-06T10:00:02Z ===\n"
    )
    assert driver_log.driver_status(log) == {
        "name": "run_weekly_walkforward",
        "started_at": "2026-09-06T06:00:01Z",
        "status": "ok",
        "log": str(log),
        "finished_at": "2026-09-06T10:00:02Z",
    }


def test_driver_status_reads_recent_running_line_without_newline(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text("=== run_weekly_walkforward 2026-09-06T06:00:01Z ===")
    status = driver_log.driver_status(log, now=datetime(2026, 9, 6, 7, tzinfo=timezone.utc))
    assert status["status"] == "running"


def test_driver_status_marks_old_unterminated_start_interrupted(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text("=== run_weekly_walkforward 2026-09-06T06:00:01Z ===")
    status = driver_log.driver_status(
        log,
        now=datetime(2026, 9, 7, 7, tzinfo=timezone.utc),
        stale_after=timedelta(hours=16),
    )
    assert status["status"] == "interrupted"
    assert status["reason"] == "stale-start"


def test_driver_status_uses_lock_as_authoritative_liveness(tmp_path):
    import fcntl

    log = tmp_path / "walkforward-cron.log"
    lock = tmp_path / ".walkforward.lock"
    log.write_text("=== run_weekly_walkforward 2026-09-06T06:00:01Z ===")
    lock.touch()

    free = driver_log.driver_status(
        log,
        lock_path=lock,
        now=datetime(2026, 9, 6, 6, 1, tzinfo=timezone.utc),
    )
    assert free["status"] == "interrupted"
    assert free["reason"] == "lock-not-held"
    assert free["lock_held"] is False

    with lock.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = driver_log.driver_status(
            log,
            lock_path=lock,
            now=datetime(2026, 9, 6, 7, tzinfo=timezone.utc),
        )
    assert held["status"] == "running"
    assert held["lock_held"] is True


def test_driver_status_marks_overlong_locked_run_stale(tmp_path):
    import fcntl

    log = tmp_path / "nightly-cron.log"
    lock = tmp_path / ".nightly.lock"
    log.write_text("=== run_daily 2026-09-07T22:30:01Z ===\n")
    lock.touch()
    with lock.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = driver_log.driver_status(
            log,
            lock_path=lock,
            now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
            stale_after=timedelta(hours=6),
        )
    assert status["status"] == "stale-running"
    assert status["reason"] == "runtime-exceeded"
    assert status["lock_held"] is True


def test_driver_status_does_not_follow_symlinked_lock_for_liveness(tmp_path):
    import fcntl

    log = tmp_path / "nightly-cron.log"
    target = tmp_path / "external.lock"
    lock = tmp_path / ".nightly.lock"
    log.write_text("=== run_daily 2026-09-06T22:30:01Z ===\n")
    target.touch()
    lock.symlink_to(target)

    with target.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = driver_log.driver_status(
            log,
            lock_path=lock,
            now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc),
            stale_after=timedelta(hours=6),
        )

    assert status["status"] == "interrupted"
    assert status["reason"] == "stale-start"
    assert "lock_held" not in status


def test_lock_replaced_during_liveness_probe_is_unavailable(tmp_path, monkeypatch):
    lock = tmp_path / ".nightly.lock"
    replacement = tmp_path / "replacement.lock"
    lock.touch()
    replacement.touch()
    def inspect_then_replace(_identity):
        replacement.replace(lock)
        return False

    monkeypatch.setattr(driver_log, "_lock_table_contains", inspect_then_replace)

    assert driver_log._lock_held(lock) is None


def test_lock_table_scan_finds_lock_across_chunk_boundary(tmp_path):
    identity = "08:01:12345"
    table = tmp_path / "locks"
    prefix = b"x" * (64 * 1024 - 4)
    table.write_bytes(prefix + b"\n1: FLOCK ADVISORY WRITE 1 " + identity.encode() + b" 0 EOF\n")

    assert driver_log._lock_table_contains(identity, table) is True


def test_lock_table_scan_fails_closed_above_byte_limit(tmp_path):
    table = tmp_path / "locks"
    table.write_bytes(b"x" * (driver_log.MAX_PROC_LOCK_BYTES + 1))

    assert driver_log._lock_table_contains("08:01:12345", table) is None


def test_lock_table_scan_allows_bounded_no_match(tmp_path):
    table = tmp_path / "locks"
    table.write_text("1: POSIX ADVISORY WRITE 1 08:01:999 0 EOF\n")

    assert driver_log._lock_table_contains("08:01:12345", table) is False


@pytest.mark.parametrize(
    ("marker", "reason"),
    [
        ("not-a-timestamp", "invalid-started-at"),
        ("2026-09-06T06:00:01+00:00", "invalid-started-at"),
    ],
)
def test_driver_status_rejects_malformed_start_timestamp(tmp_path, marker, reason):
    log = tmp_path / "walkforward-cron.log"
    log.write_text(f"=== run_weekly_walkforward {marker} ===\n")
    status = driver_log.driver_status(log)
    assert status["status"] == "invalid"
    assert status["reason"] == reason


def test_driver_status_rejects_future_start_timestamp(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text("=== run_weekly_walkforward 2026-09-06T08:00:00Z ===\n")

    status = driver_log.driver_status(
        log,
        now=datetime(2026, 9, 6, 7, tzinfo=timezone.utc),
    )

    assert status == {
        "name": "run_weekly_walkforward",
        "started_at": "2026-09-06T08:00:00Z",
        "status": "invalid",
        "log": str(log),
        "reason": "future-started-at",
    }


def test_driver_status_rejects_malformed_terminal_timestamp(tmp_path):
    log = tmp_path / "walkforward-cron.log"
    log.write_text(
        "=== run_weekly_walkforward 2026-09-06T06:00:01Z ===\n=== done not-a-timestamp ===\n"
    )
    status = driver_log.driver_status(log)
    assert status["status"] == "invalid"
    assert status["reason"] == "invalid-finished-at"


@pytest.mark.parametrize(
    ("terminal", "now", "reason"),
    [
        (
            "TODO: another_driver failed 2026-09-06T06:01:00Z (exit 2)",
            datetime(2026, 9, 6, 7, tzinfo=timezone.utc),
            "terminal-name-mismatch",
        ),
        (
            "=== done 2026-09-06T05:59:00Z ===",
            datetime(2026, 9, 6, 7, tzinfo=timezone.utc),
            "finished-before-start",
        ),
        (
            "=== done 2026-09-06T08:00:00Z ===",
            datetime(2026, 9, 6, 7, tzinfo=timezone.utc),
            "future-finished-at",
        ),
    ],
)
def test_driver_status_rejects_incoherent_terminal_marker(tmp_path, terminal, now, reason):
    log = tmp_path / "walkforward-cron.log"
    log.write_text(f"=== run_weekly_walkforward 2026-09-06T06:00:01Z ===\n{terminal}\n")
    status = driver_log.driver_status(log, now=now)
    assert status["status"] == "invalid"
    assert status["reason"] == reason
