"""Parse scheduled-driver run logs and observe advisory-lock liveness."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from .file_utils import PathChangedError, open_regular, verify_visible_regular

log = logging.getLogger(__name__)

MAX_PROC_LOCK_BYTES = 1_048_576
_PROC_LOCKS = Path("/proc/locks")
_DRIVER_START = re.compile(r"^=== (?!done )(?P<name>\S+) (?P<at>\S+) ===$")
_DRIVER_START_PREFIX = re.compile(r"^=== run_[^ ]*(?: |$)")
_DRIVER_DONE = re.compile(r"^=== done (?P<at>\S+) ===$")
_DRIVER_DONE_PREFIX = re.compile(r"^=== done(?: |$)")
_DRIVER_FAILED = re.compile(
    r"^TODO: (?P<name>\S+) failed (?P<at>\S+) "
    r"\((?:stage=(?P<stage>[^ ]+) )?exit (?P<exit_code>\d+)\)"
)
_DRIVER_FAILED_PREFIX = re.compile(r"^TODO: \S+ failed(?: |$)")


def _lock_table_contains(identity: str, path: Path = _PROC_LOCKS) -> bool | None:
    """Scan the kernel lock table with bounded memory and total input."""
    expected = identity.encode("ascii")
    consumed = 0
    carry = b""
    with path.open("rb") as source:
        while consumed <= MAX_PROC_LOCK_BYTES:
            chunk = source.read(min(64 * 1024, MAX_PROC_LOCK_BYTES + 1 - consumed))
            if not chunk:
                fields = carry.split()
                return b"FLOCK" in fields and expected in fields
            consumed += len(chunk)
            if consumed > MAX_PROC_LOCK_BYTES:
                return None
            lines = (carry + chunk).split(b"\n")
            carry = lines.pop()
            for line in lines:
                fields = line.split()
                if b"FLOCK" in fields and expected in fields:
                    return True
    return None


def utc_timestamp(value: str) -> datetime | None:
    """Parse the exact UTC timestamp emitted by ``engine/lib/driver.sh``."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value else None


def _lock_held(lock_path: Path) -> bool | None:
    """Observe one pinned regular lock file without acquiring its advisory lock."""
    try:
        with open_regular(lock_path, label="lock") as handle:
            metadata = os.fstat(handle.fileno())
            identity = (
                f"{os.major(metadata.st_dev):02x}:"
                f"{os.minor(metadata.st_dev):02x}:{metadata.st_ino}"
            )
            held = _lock_table_contains(identity)
            verify_visible_regular(lock_path, handle, label="lock")
            return held
    except (OSError, ValueError):
        return None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _log_unreadable(log_path: Path, exc: OSError) -> dict:
    log.warning("scheduled-driver log is unreadable: %s", log_path, exc_info=exc)
    return {
        "status": "invalid",
        "reason": "log-unreadable",
        "log": str(log_path),
    }


def _log_not_regular(log_path: Path) -> dict:
    return {
        "status": "invalid",
        "reason": "log-not-regular",
        "log": str(log_path),
    }


def _log_changed(log_path: Path) -> dict:
    return {
        "status": "invalid",
        "reason": "log-changed-during-read",
        "log": str(log_path),
    }


def _open_regular_log(log_path: Path) -> BinaryIO:
    """Open one log without following a replaced path or blocking on a FIFO."""
    return open_regular(log_path, label="log")


def _reverse_lines(handle: BinaryIO, position: int) -> Iterator[bytes]:
    """Yield a binary log's raw lines newest-first with bounded memory."""
    carry = b""
    while position:
        size = min(position, 64 * 1024)
        position -= size
        handle.seek(position)
        chunk = handle.read(size) + carry
        lines = chunk.split(b"\n")
        carry = lines.pop(0)
        for raw in reversed(lines):
            yield raw
    yield carry


def _terminal_fields(
    terminal: re.Match[str],
    *,
    driver_name: str,
    started_at: datetime,
    checked_at: datetime,
) -> dict:
    if terminal.re is _DRIVER_DONE:
        result = {"status": "ok", "finished_at": terminal["at"]}
    else:
        result = {
            "status": "failed",
            "finished_at": terminal["at"],
            "exit_code": int(terminal["exit_code"]),
        }
        if terminal["stage"] is not None:
            result["stage"] = terminal["stage"]

    finished_at = utc_timestamp(terminal["at"])
    if finished_at is None:
        result.update(status="invalid", reason="invalid-finished-at")
    elif terminal.re is _DRIVER_FAILED and terminal["name"] != driver_name:
        result.update(status="invalid", reason="terminal-name-mismatch")
    elif finished_at < started_at:
        result.update(status="invalid", reason="finished-before-start")
    elif finished_at > checked_at:
        result.update(status="invalid", reason="future-finished-at")
    return result


def _unterminated_fields(
    started_at: datetime,
    *,
    lock_path: Path | None,
    lock_before: bool | None,
    checked_at: datetime,
    stale_after: timedelta,
) -> dict:
    elapsed = checked_at - started_at
    lock_after = _lock_held(lock_path) if lock_path is not None else None
    lock_held = True if True in (lock_before, lock_after) else lock_after
    if lock_held is True:
        result = {"status": "running", "lock_held": True}
        if elapsed > stale_after:
            result.update(status="stale-running", reason="runtime-exceeded")
        return result
    if lock_held is False:
        return {"status": "interrupted", "reason": "lock-not-held", "lock_held": False}
    if elapsed > stale_after:
        return {"status": "interrupted", "reason": "stale-start"}
    return {"status": "running"}


def _started_at(value: str, checked_at: datetime) -> tuple[datetime | None, str | None]:
    started_at = utc_timestamp(value)
    if started_at is None:
        return None, "invalid-started-at"
    if started_at > checked_at:
        return None, "future-started-at"
    return started_at, None


def _run_fields(
    match: re.Match[str],
    terminal: re.Match[str] | None,
    marker_error: str | None,
    *,
    lock_path: Path | None,
    lock_before: bool | None,
    checked_at: datetime,
    stale_after: timedelta,
) -> dict:
    started_at, invalid_reason = _started_at(match["at"], checked_at)
    if invalid_reason is not None or started_at is None:
        return {"status": "invalid", "reason": invalid_reason or "invalid-started-at"}
    if marker_error is not None:
        return {"status": "invalid", "reason": marker_error}
    if terminal is not None:
        return _terminal_fields(
            terminal,
            driver_name=match["name"],
            started_at=started_at,
            checked_at=checked_at,
        )
    return _unterminated_fields(
        started_at,
        lock_path=lock_path,
        lock_before=lock_before,
        checked_at=checked_at,
        stale_after=stale_after,
    )


def _run_status(
    match: re.Match[str],
    terminal: re.Match[str] | None,
    marker_error: str | None,
    *,
    log_path: Path,
    lock_path: Path | None,
    lock_before: bool | None,
    checked_at: datetime,
    stale_after: timedelta,
) -> dict:
    result = {
        "name": match["name"],
        "started_at": match["at"],
        "status": "running",
        "log": str(log_path),
    }
    result.update(
        _run_fields(
            match,
            terminal,
            marker_error,
            lock_path=lock_path,
            lock_before=lock_before,
            checked_at=checked_at,
            stale_after=stale_after,
        )
    )
    return result


def _latest_run_markers(
    handle: BinaryIO, position: int
) -> tuple[re.Match[str] | None, re.Match[str] | None, str | None]:
    terminal = None
    multiple_terminals = False
    malformed_terminal = False
    for raw in _reverse_lines(handle, position):
        if not raw.startswith((b"=== ", b"TODO: ")):
            continue
        line = raw.decode(errors="replace")
        candidate = _DRIVER_DONE.match(line) or _DRIVER_FAILED.match(line)
        if candidate is not None:
            if terminal is None:
                terminal = candidate
            else:
                multiple_terminals = True
        elif _DRIVER_DONE_PREFIX.match(line) or _DRIVER_FAILED_PREFIX.match(line):
            malformed_terminal = True
        if match := _DRIVER_START.match(line):
            if malformed_terminal:
                marker_error = "malformed-terminal-marker"
            elif multiple_terminals:
                marker_error = "multiple-terminal-markers"
            else:
                marker_error = None
            return match, terminal, marker_error
        if _DRIVER_START_PREFIX.match(line):
            return None, None, "malformed-start-marker"
    return None, terminal, None


def _stable_log_metadata(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_run_status(
    log_path: Path,
    *,
    lock_path: Path | None,
    lock_before: bool | None,
    checked_at: datetime,
    stale_after: timedelta,
) -> dict | None:
    with _open_regular_log(log_path) as handle:
        before = os.fstat(handle.fileno())
        handle.seek(0, 2)
        position = handle.tell()
        match, terminal, marker_error = (
            (None, None, None) if position == 0 else _latest_run_markers(handle, position)
        )
        after = os.fstat(handle.fileno())
        visible = verify_visible_regular(log_path, handle, label="log")
        if (
            _stable_log_metadata(before) != _stable_log_metadata(after)
            or _stable_log_metadata(after) != _stable_log_metadata(visible)
        ):
            raise PathChangedError("log changed while reading")
    if position == 0:
        return None
    if match is None:
        return {
            "status": "invalid",
            "reason": marker_error or "missing-start-marker",
            "log": str(log_path),
        }
    return _run_status(
        match,
        terminal,
        marker_error,
        log_path=log_path,
        lock_path=lock_path,
        lock_before=lock_before,
        checked_at=checked_at,
        stale_after=stale_after,
    )


def driver_status(
    log_path: Path,
    *,
    lock_path: Path | None = None,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(hours=24),
) -> dict | None:
    """Parse the final run and distinguish live work from an abandoned start.

    Current drivers hold ``lock_path`` for their entire process lifetime, so a
    held lock is authoritative. If a historical deployment has no readable
    lock, a conservative age limit prevents an unterminated marker from being
    reported as running forever.
    """
    # Sample liveness before parsing. Unterminated runs sample it again after
    # the log read so either observation can establish a live execution.
    lock_before = _lock_held(lock_path) if lock_path is not None else None
    # Search backwards: successful jobs can emit multi-megabyte logs, but their
    # terminal marker is always at the end. This keeps request-time memory flat.
    checked_at = as_utc(now or datetime.now(timezone.utc))
    try:
        return _read_run_status(
            log_path,
            lock_path=lock_path,
            lock_before=lock_before,
            checked_at=checked_at,
            stale_after=stale_after,
        )
    except FileNotFoundError:
        return None
    except PathChangedError:
        return _log_changed(log_path)
    except ValueError:
        return _log_not_regular(log_path)
    except OSError as exc:
        return _log_unreadable(log_path, exc)
