#!/usr/bin/env python3
"""Verify Friday's real nightly and miner evidence through the read-only API."""

from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
import secrets
import stat
import sys
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from engine.lib.settings import LOGS_DIR
from server.friday_postflight import (
    EXPECTED_MINERS,
    FIRST_EXPECTED_AT,
    MAX_FAILURE_REASON_LENGTH,
    SCHEDULE_TIME,
)
from server.json_utils import MAX_JSON_FILE_BYTES, loads_object

DEFAULT_META_URL = "http://127.0.0.1:8000/meta"
DEFAULT_RECEIPT_PATH = LOGS_DIR / "friday-postflight.json"
MAX_META_RESPONSE_BYTES = MAX_JSON_FILE_BYTES
RENAME_NOREPLACE = 1
RENAME_EXCHANGE = 2


class PostflightError(ValueError):
    """Evidence is unavailable, malformed, or not current for the expected Friday."""


def _identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _stable_metadata(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _exchange_metadata(value: os.stat_result) -> tuple[int, int, int, int, int]:
    """Identity and content metadata unaffected by a rename's ctime update."""
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


@contextmanager
def _directory_chain(path: Path, *, create: bool):
    """Open one absolute directory chain without following component symlinks."""
    absolute = Path(os.path.abspath(path))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise OSError("secure receipt publication is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    with ExitStack() as stack:
        current = os.open(absolute.anchor, flags)
        stack.callback(os.close, current)
        identities = [_identity(os.fstat(current))]
        for part in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
            current = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, current)
            identities.append(_identity(os.fstat(current)))
        yield current, tuple(identities)


def _directory_chain_matches(path: Path, expected: tuple[tuple[int, int], ...]) -> bool:
    try:
        with _directory_chain(path, create=False) as (_descriptor, visible):
            return visible == expected
    except OSError:
        return False


def _target_mode(directory_fd: int, leaf: str, path: Path) -> tuple[int, os.stat_result | None]:
    try:
        target = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return 0o644, None
    if not stat.S_ISREG(target.st_mode):
        raise OSError(f"receipt target must be a regular file: {path}")
    return stat.S_IMODE(target.st_mode), target


def _same_target(
    directory_fd: int, leaf: str, expected: os.stat_result | None
) -> bool:
    try:
        visible = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return expected is None
    return expected is not None and _stable_metadata(visible) == _stable_metadata(expected)


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short receipt write")
        view = view[written:]


def _rename_at2(parent_fd: int, source: str, destination: str, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as exc:
        raise OSError("atomic receipt publication is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(destination),
            flags,
        )
        == 0
    ):
        return
    error_number = ctypes.get_errno()
    raise OSError(error_number, os.strerror(error_number))


def _opened_leaf_visible(directory_fd: int, leaf: str, descriptor: int) -> bool:
    try:
        visible = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError:
        return False
    return stat.S_ISREG(visible.st_mode) and _identity(visible) == _identity(opened)


def _publish_receipt(
    parent_fd: int,
    temporary: str,
    leaf: str,
    descriptor: int,
    target: os.stat_result | None,
    path: Path,
) -> None:
    """Atomically publish only against the target state observed before staging."""
    if not _opened_leaf_visible(parent_fd, temporary, descriptor):
        raise OSError(f"temporary receipt changed before publication: {path}")
    if target is None:
        try:
            _rename_at2(parent_fd, temporary, leaf, RENAME_NOREPLACE)
        except OSError as exc:
            if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise OSError(f"receipt target changed before publication: {path}") from exc
            raise
        return

    try:
        _rename_at2(parent_fd, temporary, leaf, RENAME_EXCHANGE)
    except OSError as exc:
        raise OSError(f"receipt target changed before publication: {path}") from exc
    try:
        displaced = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _exchange_metadata(displaced) != _exchange_metadata(target)
            or not _opened_leaf_visible(parent_fd, leaf, descriptor)
        ):
            raise OSError(f"receipt target changed during publication: {path}")
    except OSError:
        if _opened_leaf_visible(parent_fd, leaf, descriptor):
            try:
                _rename_at2(parent_fd, temporary, leaf, RENAME_EXCHANGE)
            except OSError:
                pass
        raise
    os.unlink(temporary, dir_fd=parent_fd)


def _write_receipt_atomic(path: Path, text: str) -> None:
    """Publish one durable receipt through a retained no-follow parent descriptor."""
    absolute = Path(os.path.abspath(path))
    if absolute.name in {"", ".", ".."}:
        raise OSError(f"receipt path has no file name: {path}")
    content = text.encode("utf-8")
    temporary = f".{absolute.name}.{secrets.token_hex(8)}.tmp"
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("secure receipt publication is unavailable")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | nofollow
    with _directory_chain(absolute.parent, create=True) as (parent_fd, parent_chain):
        mode, target = _target_mode(parent_fd, absolute.name, absolute)
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
            _write_all(descriptor, content)
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
            if not _same_target(parent_fd, absolute.name, target):
                raise OSError(f"receipt target changed before publication: {path}")
            if not _directory_chain_matches(absolute.parent, parent_chain):
                raise OSError(f"receipt parent changed before publication: {path}")
            _publish_receipt(
                parent_fd, temporary, absolute.name, descriptor, target, absolute
            )
            os.fsync(parent_fd)
            if not _directory_chain_matches(absolute.parent, parent_chain):
                raise OSError(f"receipt parent changed during publication: {path}")
        finally:
            if descriptor >= 0 and _opened_leaf_visible(parent_fd, temporary, descriptor):
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except OSError:
                    pass
            if descriptor >= 0:
                os.close(descriptor)


def _same_publication_path(left: Path, right: Path) -> bool:
    """Compare normalized pathnames without granting authority through symlinks."""
    return os.path.abspath(left) == os.path.abspath(right)


def most_recent_friday(checked_at: datetime) -> date:
    """Return the Friday on or before a timezone-aware UTC observation time."""
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise PostflightError("checked_at must be timezone-aware")
    utc_date = checked_at.astimezone(timezone.utc).date()
    return utc_date - timedelta(days=(utc_date.weekday() - 4) % 7)


def publication_slot(expected_date: date) -> datetime:
    """Return the UTC Saturday publication slot for one Friday."""
    if expected_date.weekday() != 4:
        raise PostflightError("expected date must be a Friday")
    return datetime.combine(expected_date + timedelta(days=1), SCHEDULE_TIME)


def validate_authoritative_publication(expected_date: date, checked_at: datetime) -> None:
    """Reject canonical publication outside the current Friday's scheduled window."""
    current_friday = most_recent_friday(checked_at)
    slot = publication_slot(expected_date)
    if slot < FIRST_EXPECTED_AT:
        raise PostflightError(
            f"authoritative publication starts at {FIRST_EXPECTED_AT.isoformat()}"
        )
    if expected_date != current_friday:
        raise PostflightError(
            f"authoritative publication requires current Friday {current_friday}, "
            f"not {expected_date}"
        )
    if checked_at < slot:
        raise PostflightError(f"authoritative publication is not due before {slot.isoformat()}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise PostflightError(f"{field} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostflightError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PostflightError(f"{field} has no timezone")
    return parsed.astimezone(timezone.utc)


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise PostflightError(f"{field} is not a date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PostflightError(f"{field} is not an ISO date") from exc


def _nightly_window(
    payload: dict[str, Any], expected_date: date
) -> tuple[datetime, datetime, date]:
    nightly = payload.get("nightly")
    nightly_evidence = payload.get("nightly_evidence")
    if not isinstance(nightly, dict) or not isinstance(nightly_evidence, dict):
        raise PostflightError("nightly status is missing")
    if nightly.get("status") != "ok":
        raise PostflightError(f"nightly status is {nightly.get('status')!r}, not 'ok'")

    started_at = _timestamp(nightly.get("started_at"), "nightly.started_at")
    finished_at = _timestamp(nightly.get("finished_at"), "nightly.finished_at")
    if started_at.date() != expected_date:
        raise PostflightError(
            f"latest nightly started on {started_at.date()}, expected {expected_date}"
        )
    if finished_at < started_at:
        raise PostflightError("nightly finished before it started")
    if nightly_evidence.get("status") != "current":
        raise PostflightError(
            f"nightly evidence is {nightly_evidence.get('status')!r}, not 'current'"
        )
    market_date = _date(nightly_evidence.get("as_of"), "nightly_evidence.as_of")
    if market_date > expected_date:
        raise PostflightError(
            f"nightly evidence market date {market_date} is after Friday {expected_date}"
        )
    return started_at, finished_at, market_date


def _miner_receipt(
    kind: str,
    item: object,
    started_at: datetime,
    finished_at: datetime,
) -> tuple[int, str]:
    if not isinstance(item, dict) or item.get("status") != "current":
        raise PostflightError(f"{kind} evidence is not current")
    job_id = item.get("job_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise PostflightError(f"{kind}.job_id is invalid")
    item_evidence_at = _timestamp(item.get("evidence_at"), f"{kind}.evidence_at")
    if not started_at <= item_evidence_at <= finished_at:
        raise PostflightError(f"{kind} evidence falls outside Friday's nightly window")
    return job_id, item_evidence_at.isoformat()


def _miner_receipts(
    value: object,
    started_at: datetime,
    finished_at: datetime,
) -> tuple[dict[str, int], dict[str, str]]:
    if not isinstance(value, dict):
        raise PostflightError("miner evidence is missing")

    miners = value.get("miners")
    if (
        not isinstance(miners, dict)
        or not EXPECTED_MINERS.issubset(miners)
    ):
        raise PostflightError("canonical miner cohort is not current at 4/4")

    job_ids: dict[str, int] = {}
    evidence_at: dict[str, str] = {}
    for kind in sorted(EXPECTED_MINERS):
        job_id, item_evidence_at = _miner_receipt(kind, miners[kind], started_at, finished_at)
        job_ids[kind] = job_id
        evidence_at[kind] = item_evidence_at
    if len(set(job_ids.values())) != len(job_ids):
        raise PostflightError("canonical miner job IDs are not unique")
    return job_ids, evidence_at


def verify(payload: dict[str, Any], expected_date: date) -> dict[str, Any]:
    """Return a compact receipt only when Friday's complete evidence is current."""
    publication_slot(expected_date)
    started_at, finished_at, market_date = _nightly_window(payload, expected_date)
    job_ids, evidence_at = _miner_receipts(payload.get("miner_evidence"), started_at, finished_at)

    return {
        "status": "current",
        "expected_date": expected_date.isoformat(),
        "market_date": market_date.isoformat(),
        "nightly_started_at": started_at.isoformat(),
        "nightly_finished_at": finished_at.isoformat(),
        "miner_job_ids": job_ids,
        "miner_evidence_at": evidence_at,
    }


def fetch_meta(url: str, *, timeout: float) -> dict[str, Any]:
    """Fetch and strictly decode one local metadata response."""
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - operator-supplied URL
            payload = response.read(MAX_META_RESPONSE_BYTES + 1)
            if len(payload) > MAX_META_RESPONSE_BYTES:
                raise PostflightError(f"response exceeds {MAX_META_RESPONSE_BYTES} bytes")
            return loads_object(payload)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise PostflightError(f"unable to read {url}: {exc}") from exc


def _failure(expected_date: date, reason: object) -> dict[str, str]:
    """Build a failure body that every downstream receipt validator accepts."""
    message = str(reason).strip() or "postflight verification failed"
    return {
        "status": "failed",
        "expected_date": expected_date.isoformat(),
        "reason": message[:MAX_FAILURE_REASON_LENGTH],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the latest Friday nightly and all four canonical miner receipts."
    )
    parser.add_argument("--url", default=DEFAULT_META_URL)
    parser.add_argument("--expected-date", type=date.fromisoformat)
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--publish",
        dest="publish",
        action="store_true",
        help="atomically publish the result to the authoritative receipt path",
    )
    output.add_argument(
        "--dry-run",
        dest="publish",
        action="store_false",
        help="print without publishing (the default; retained for explicit operator commands)",
    )
    parser.set_defaults(publish=False)
    parser.add_argument(
        "--receipt",
        type=Path,
        help="alternate publication path; requires --publish",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


def _verification_result(url: str, timeout: float, expected: date) -> dict:
    try:
        return verify(fetch_meta(url, timeout=timeout), expected)
    except PostflightError as exc:
        return _failure(expected, exc)


def _render_receipt(result: dict, checked_at: datetime) -> str:
    receipt = {"schema_version": 1, "checked_at": checked_at.isoformat(), **result}
    return json.dumps(receipt, sort_keys=True)


def _emit_result(rendered: str, result: dict, *, publish: bool, path: Path, expected: date) -> int:
    if publish:
        try:
            _write_receipt_atomic(path, f"{rendered}\n")
        except OSError as exc:
            print(
                json.dumps(
                    _failure(expected, f"unable to publish postflight receipt: {exc}"),
                    sort_keys=True,
                )
            )
            return 1
    print(rendered)
    return 0 if result["status"] == "current" else 1


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.receipt is not None and not args.publish:
        parser.error("--receipt requires --publish")

    started_at = _utc_now()
    expected = args.expected_date or most_recent_friday(started_at)
    receipt_path = args.receipt or DEFAULT_RECEIPT_PATH
    if args.publish and _same_publication_path(receipt_path, DEFAULT_RECEIPT_PATH):
        try:
            validate_authoritative_publication(expected, started_at)
        except PostflightError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    result = _verification_result(args.url, args.timeout, expected)
    rendered = _render_receipt(result, _utc_now())
    return _emit_result(
        rendered, result, publish=args.publish, path=receipt_path, expected=expected
    )


if __name__ == "__main__":
    sys.exit(main())
