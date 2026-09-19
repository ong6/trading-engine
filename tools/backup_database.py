#!/usr/bin/env python3
"""Create or verify a transactionally consistent local recovery bundle."""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.resources import write_text_atomic
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from server import nightly_monitor
from server.driver_monitor import DRIVER_SCHEDULES
from server.file_utils import MAX_OPERATIONAL_FILE_BYTES
from server.json_utils import load_object
from tools import release_manifest

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, SCHEMA_VERSION})
DATABASE_FILENAME = "market.duckdb"
MANIFEST_FILENAME = "manifest.json"
REQUIRED_TABLES = frozenset(
    {"prices", "jobs", "portfolios", "sim_orders", "sim_fills", "sim_equity"}
)
EVIDENCE_FILES = release_manifest.PROSPECTIVE_EVIDENCE_FILES
LOCK_FILES = tuple(
    sorted(
        {row[3] for row in DRIVER_SCHEDULES}
        | {
            ".agent-shadow.lock",
            "store/.agent-fault-drill.lock",
            ".queue-drain.lock",
            ".backup.lock",
            "data/_meta.json.lock",
            "store/agent-shadow-control.json.lock",
        }
    )
)
V1_MANIFEST_FIELDS = {
    "schema_version",
    "created_at",
    "source_database",
    "database",
    "prospective_evidence",
    "release_identity",
}
V2_MANIFEST_FIELDS = V1_MANIFEST_FIELDS | {"operational_artifacts"}
V3_MANIFEST_FIELDS = V2_MANIFEST_FIELDS | {"operational_controls"}
RELEASE_IDENTITY_FIELDS = {
    "status",
    "release_eligible",
    "manifest_sha256",
    "git_sha",
    "working_tree_sha256",
    "research_runtime",
}
DATABASE_FIELDS = {"filename", "size_bytes", "sha256", "snapshot"}
SNAPSHOT_FIELDS = {
    "schema_sha256",
    "table_count",
    "view_count",
    "index_count",
    "row_counts",
    "latest_price_date",
    "job_states",
    "active_portfolio_count",
    "active_portfolios_sha256",
}
# The first schema-v1 bundle predates index_count. Keep it verifiable while
# requiring every newly emitted field to have a strict type.
LEGACY_SNAPSHOT_FIELDS = SNAPSHOT_FIELDS - {"index_count"}
EVIDENCE_RECORD_FIELDS = {"bundle_path", "size_bytes", "sha256"}
OPERATIONAL_STATIC_FILES = (
    "data/_meta.json",
    "logs/friday-postflight.json",
    "data/screens/latest.md",
    "data/reports/league.md",
    "data/reports/league.csv",
)
OPTIONAL_OPERATIONAL_CONTROL_FILES = ("store/agent-shadow-control.json",)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
RENAME_NOREPLACE = 1


class BackupError(RuntimeError):
    """The backup could not be created or did not verify."""


class SourceFileMissing(BackupError):
    """An optional source artifact did not exist during the locked snapshot."""


@contextmanager
def _relative_directory_fd(root: Path, parts: tuple[str, ...], *, create: bool):
    """Open a directory chain without following any component symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise BackupError("secure descriptor-relative path traversal is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | directory
        | nofollow
    )
    with ExitStack() as stack:
        try:
            current = os.open(root, flags)
        except OSError as exc:
            raise BackupError("repository root must be a directory") from exc
        stack.callback(os.close, current)
        for part in parts:
            if part in {"", ".", ".."}:
                raise BackupError("relative path contains an unsafe directory component")
            if create:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise BackupError("could not create relative directory") from exc
            try:
                child = os.open(part, flags, dir_fd=current)
            except OSError as exc:
                raise BackupError("relative path parent must be a non-symlinked directory") from exc
            stack.callback(os.close, child)
            current = child
        yield current


def _open_lock_file(repo_root: Path, relative: str):
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute():
        raise BackupError(f"lock path is invalid: {relative}")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise BackupError("secure no-follow lock opening is unavailable")
    flags = (
        os.O_APPEND
        | os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | nofollow
        | getattr(os, "O_NONBLOCK", 0)
    )
    with _relative_directory_fd(repo_root, parts[:-1], create=True) as parent:
        try:
            descriptor = os.open(parts[-1], flags, 0o644, dir_fd=parent)
        except OSError as exc:
            raise BackupError(f"lock path must be a regular file: {relative}") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise BackupError(f"lock path must be a regular file: {relative}")
        except Exception:
            os.close(descriptor)
            raise
        return os.fdopen(descriptor, "a")


@contextmanager
def _exclusive_backup_window(repo_root: Path):
    """Prevent overlapping backups and cooperating scheduled writers."""
    with ExitStack() as stack:
        for relative in LOCK_FILES:
            handle = stack.enter_context(_open_lock_file(repo_root, relative))
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BackupError(f"active process holds {relative}; backup not started") from exc
            stack.callback(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
        yield


def _sql_string(value: str) -> str:
    if "\x00" in value:
        raise BackupError("database path contains a NUL byte")
    return "'" + value.replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _inode_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _read_bounded_descriptor(descriptor: int) -> bytes:
    chunks = []
    remaining = MAX_OPERATIONAL_FILE_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_source_file(repo_root: Path, relative: str, label: str) -> bytes:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute():
        raise BackupError(f"required {label} path is invalid: {relative}")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise BackupError("secure no-follow evidence opening is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | nofollow
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        with _relative_directory_fd(repo_root, parts[:-1], create=False) as parent:
            descriptor = os.open(parts[-1], flags, dir_fd=parent)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    raise BackupError(f"required {label} is not a regular file: {relative}")
                content = _read_bounded_descriptor(descriptor)
                after = os.fstat(descriptor)
                path_after = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            finally:
                os.close(descriptor)
    except BackupError:
        raise
    except FileNotFoundError as exc:
        raise SourceFileMissing(f"required {label} missing: {relative}") from exc
    except OSError as exc:
        raise BackupError(f"required {label} missing: {relative}") from exc
    if len(content) > MAX_OPERATIONAL_FILE_BYTES:
        raise BackupError(
            f"required {label} exceeds {MAX_OPERATIONAL_FILE_BYTES} bytes: {relative}"
        )
    if (
        _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(path_after)
        or not stat.S_ISREG(path_after.st_mode)
        or len(content) != before.st_size
    ):
        raise BackupError(f"{label} changed during backup: {relative}")
    return content


def _require_private(path: Path, *, directory: bool, label: str) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        expected_type = path.is_dir() if directory else path.is_file()
    except OSError as exc:
        raise BackupError(f"{label} is missing or unreadable") from exc
    if not expected_type or mode & 0o077:
        kind = "directory" if directory else "regular file"
        raise BackupError(f"{label} must be an owner-only {kind}")


def _mkdir_private_tree(root: Path, directory: Path) -> None:
    """Create a bundle-relative directory chain with explicit private modes."""
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise BackupError("backup directory path escapes bundle") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise BackupError("backup directory tree must not use symlinks")
        try:
            current.mkdir(mode=0o700, exist_ok=True)
            current.chmod(0o700)
        except OSError as exc:
            raise BackupError(f"could not create private backup directory: {current}") from exc
        _require_private(current, directory=True, label="backup directory")


def _publish_no_replace(parent_fd: int, source_name: str, destination_name: str) -> None:
    """Atomically rename two leaf names within one already-open directory."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as exc:
        raise BackupError("atomic no-replace publication is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        parent_fd,
        os.fsencode(source_name),
        parent_fd,
        os.fsencode(destination_name),
        RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise BackupError("backup destination already exists; refusing to overwrite")
    raise BackupError(
        f"could not atomically publish backup without overwrite: {os.strerror(error_number)}"
    )


@contextmanager
def _open_destination_parent(parent: Path):
    """Anchor a canonical destination parent without following a replacement symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise BackupError("secure destination parent opening is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    try:
        descriptor = os.open(parent, flags)
    except OSError as exc:
        raise BackupError("backup destination parent is unavailable") from exc
    try:
        _require_destination_parent_identity(parent, descriptor, published=False)
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _open_source_database(source: Path):
    """Retain a descriptor reached through a no-follow canonical parent chain."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise BackupError("secure source database opening is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow
    anchor = Path(source.anchor)
    parts = source.relative_to(anchor).parts
    if not parts:
        raise BackupError("source database is missing or is not a regular file")
    with _relative_directory_fd(anchor, parts[:-1], create=False) as parent_fd:
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
        except OSError as exc:
            raise BackupError("source database is missing or is not a regular file") from exc
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise BackupError("source database is missing or is not a regular file")
            yield parent_fd, descriptor, opened
        finally:
            os.close(descriptor)


@contextmanager
def _open_bundle_for_verification(bundle: Path):
    """Retain a bundle reached through a no-follow absolute parent chain."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise BackupError("secure backup bundle opening is unavailable")
    requested = bundle.absolute()
    anchor = Path(requested.anchor)
    parts = requested.relative_to(anchor).parts
    if not parts:
        raise BackupError("backup bundle must be a directory, not a symlink")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    with _relative_directory_fd(anchor, parts[:-1], create=False) as parent_fd:
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise BackupError("backup bundle is missing or unreadable") from exc
            raise BackupError("backup bundle must be a directory, not a symlink") from exc
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISDIR(opened.st_mode):
                raise BackupError("backup bundle must be a directory, not a symlink")
            yield requested, parent_fd, descriptor, opened
        finally:
            os.close(descriptor)


def _require_destination_parent_identity(
    parent: Path, parent_fd: int, *, published: bool
) -> None:
    """Require the visible destination parent to remain the opened directory."""
    try:
        opened = os.fstat(parent_fd)
        visible = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        phase = "after publication" if published else "during backup"
        raise BackupError(f"backup destination parent changed {phase}") from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(visible.st_mode)
        or _inode_identity(opened) != _inode_identity(visible)
    ):
        phase = "after publication" if published else "during backup"
        raise BackupError(f"backup destination parent changed {phase}")


def _require_source_database_identity(
    source: Path, source_parent_fd: int, source_fd: int, initial: os.stat_result
) -> None:
    """Require the no-follow source chain and opened database to remain unchanged."""
    anchor = Path(source.anchor)
    parts = source.relative_to(anchor).parts
    try:
        opened = os.fstat(source_fd)
        anchored = os.stat(parts[-1], dir_fd=source_parent_fd, follow_symlinks=False)
        with _relative_directory_fd(anchor, parts[:-1], create=False) as visible_parent_fd:
            visible_parent = os.fstat(visible_parent_fd)
            visible = os.stat(parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise BackupError("source database changed during backup") from exc
    except BackupError as exc:
        raise BackupError("source database changed during backup") from exc
    if (
        _inode_identity(os.fstat(source_parent_fd)) != _inode_identity(visible_parent)
        or not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(anchored.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or _stat_identity(initial) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(anchored)
        or _stat_identity(anchored) != _stat_identity(visible)
    ):
        raise BackupError("source database changed during backup")


def _require_verified_bundle_identity(
    bundle: Path, parent_fd: int, bundle_fd: int, initial: os.stat_result
) -> None:
    """Require the opened bundle and its visible no-follow path to remain unchanged."""
    anchor = Path(bundle.anchor)
    parts = bundle.relative_to(anchor).parts
    try:
        opened = os.fstat(bundle_fd)
        anchored = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        with _relative_directory_fd(anchor, parts[:-1], create=False) as visible_parent_fd:
            visible_parent = os.fstat(visible_parent_fd)
            visible = os.stat(parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False)
    except (OSError, BackupError) as exc:
        raise BackupError("backup bundle changed during verification") from exc
    if (
        _inode_identity(os.fstat(parent_fd)) != _inode_identity(visible_parent)
        or not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(anchored.st_mode)
        or not stat.S_ISDIR(visible.st_mode)
        or _stat_identity(initial) != _stat_identity(opened)
        or _stat_identity(opened) != _stat_identity(anchored)
        or _stat_identity(anchored) != _stat_identity(visible)
    ):
        raise BackupError("backup bundle changed during verification")


def _descriptor_path(descriptor: int) -> Path:
    """Return a pathname that remains bound to an already-open Linux object."""
    path = Path("/proc/self/fd") / str(descriptor)
    try:
        if _inode_identity(path.stat()) != _inode_identity(os.fstat(descriptor)):
            raise BackupError("directory descriptor path has changed")
    except OSError as exc:
        raise BackupError("directory descriptor path is unavailable") from exc
    return path


def _bundle_tree_identity(bundle: Path) -> dict[str, tuple[int, int, int, int, int, int]]:
    """Capture inode, type, size, and timestamp identity for a complete bundle tree."""
    try:
        paths = [bundle, *bundle.rglob("*")]
        result = {}
        for path in paths:
            relative = "." if path == bundle else path.relative_to(bundle).as_posix()
            value = path.lstat()
            result[relative] = (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
    except OSError as exc:
        raise BackupError("backup bundle changed during verification") from exc
    return result


def _make_temporary_bundle(parent_fd: int, destination_name: str) -> tuple[str, int]:
    """Create an owner-private temporary bundle relative to the anchored parent."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise BackupError("secure temporary bundle opening is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    for _attempt in range(100):
        name = f".{destination_name}.{secrets.token_hex(8)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        except OSError as exc:
            raise BackupError("could not create temporary backup bundle") from exc
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
            raise BackupError("could not open temporary backup bundle") from exc
        return name, descriptor
    raise BackupError("could not allocate a unique temporary backup bundle")


def _temporary_bundle_matches(parent_fd: int, name: str, bundle_fd: int) -> bool:
    """Return whether a parent entry still names the opened temporary directory."""
    try:
        visible = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(bundle_fd)
    except OSError:
        return False
    return (
        stat.S_ISDIR(visible.st_mode)
        and stat.S_ISDIR(opened.st_mode)
        and _inode_identity(visible) == _inode_identity(opened)
    )


def _require_temporary_bundle_identity(parent_fd: int, name: str, bundle_fd: int) -> None:
    if not _temporary_bundle_matches(parent_fd, name, bundle_fd):
        raise BackupError("temporary backup bundle changed during creation")


def _remove_temporary_bundle(parent_fd: int, name: str, bundle_fd: int) -> None:
    """Remove only the unchanged unpublished bundle entry through its parent."""
    if _temporary_bundle_matches(parent_fd, name, bundle_fd):
        shutil.rmtree(name, ignore_errors=True, dir_fd=parent_fd)


def _sync_directory_fd(descriptor: int, *, label: str) -> None:
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise BackupError(f"{label} has an unexpected file type")
        os.fsync(descriptor)
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(f"could not durably synchronize {label}: {exc}") from exc


def _fsync_path(path: Path, *, directory: bool, label: str) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or (directory and directory_flag is None):
        raise BackupError("durable no-follow backup synchronization is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow
    if directory:
        flags |= directory_flag
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            expected = stat.S_ISDIR(opened.st_mode) if directory else stat.S_ISREG(opened.st_mode)
            if not expected:
                raise BackupError(f"{label} has an unexpected file type")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(f"could not durably synchronize {label}: {exc}") from exc


def _sync_bundle(bundle: Path, bundle_fd: int | None = None) -> None:
    """Persist verified bundle content and directory entries before publication."""
    try:
        paths = list(bundle.rglob("*"))
    except OSError as exc:
        raise BackupError(f"backup tree is unreadable during synchronization: {exc}") from exc
    for path in (candidate for candidate in paths if not candidate.is_dir()):
        _fsync_path(path, directory=False, label="backup file")
    directories = [candidate for candidate in paths if candidate.is_dir()]
    for path in sorted(directories, key=lambda candidate: len(candidate.parts), reverse=True):
        _fsync_path(path, directory=True, label="backup directory")
    if bundle_fd is None:
        _fsync_path(bundle, directory=True, label="backup bundle")
    else:
        _sync_directory_fd(bundle_fd, label="backup bundle")


def _valid_hash(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _valid_optional_hash(value: object, pattern: re.Pattern[str], eligible: bool) -> bool:
    return _valid_hash(value, pattern) or (value is None and not eligible)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_nonnegative_int(value: object, label: str) -> None:
    if not _is_nonnegative_int(value):
        raise BackupError(f"{label} must be a non-negative integer")


def _validate_created_at(created_at: object) -> None:
    try:
        parsed_at = datetime.fromisoformat(created_at)
    except (TypeError, ValueError) as exc:
        raise BackupError("backup creation timestamp is invalid") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() != timezone.utc.utcoffset(parsed_at):
        raise BackupError("backup creation timestamp must be UTC")
    if parsed_at.isoformat() != created_at:
        raise BackupError("backup creation timestamp is not canonical")


def _validate_source_database(source: object) -> None:
    if not isinstance(source, dict) or set(source) != {"kind", "path"}:
        raise BackupError("source database location is invalid")
    kind = source["kind"]
    path = source["path"]
    if kind == "external":
        if path is not None:
            raise BackupError("external source database path must be omitted")
    elif kind == "repository-relative":
        if not isinstance(path, str) or not path:
            raise BackupError("repository source database path is invalid")
        relative = Path(path)
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or relative.as_posix() != path
        ):
            raise BackupError("repository source database path is invalid")
    else:
        raise BackupError("source database location kind is invalid")


def _validate_research_identity(research: object, eligible: bool) -> None:
    if not isinstance(research, dict) or set(research) != {"sha256", "file_count"}:
        raise BackupError("release research identity is invalid")
    if not _valid_optional_hash(research["sha256"], SHA256_PATTERN, eligible):
        raise BackupError("release research hash is invalid")
    file_count = research["file_count"]
    if isinstance(file_count, bool) or not isinstance(file_count, int) or file_count <= 0:
        raise BackupError("release research file count is invalid")


def _validate_release_identity(release: object) -> None:
    if not isinstance(release, dict) or set(release) != RELEASE_IDENTITY_FIELDS:
        raise BackupError("release identity is invalid")
    eligible = release["release_eligible"]
    status = release["status"]
    if not isinstance(eligible, bool) or status not in {"release-candidate", "non-releasable"}:
        raise BackupError("release identity status is invalid")
    if eligible != (status == "release-candidate"):
        raise BackupError("release identity eligibility is inconsistent")
    if not _valid_hash(release["manifest_sha256"], SHA256_PATTERN):
        raise BackupError("release identity manifest_sha256 is invalid")
    if not _valid_optional_hash(release["working_tree_sha256"], SHA256_PATTERN, eligible):
        raise BackupError("release identity working_tree_sha256 is invalid")
    if not _valid_optional_hash(release["git_sha"], GIT_SHA_PATTERN, eligible):
        raise BackupError("release identity git_sha is invalid")
    _validate_research_identity(release["research_runtime"], eligible)


def _validate_count_map(value: object, label: str) -> None:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key or not _is_nonnegative_int(count)
        for key, count in value.items()
    ):
        raise BackupError(f"backup database snapshot {label} is invalid")


def _validate_snapshot_fields(snapshot: object, allow_legacy: bool) -> dict:
    if not isinstance(snapshot, dict):
        raise BackupError("backup database snapshot has unexpected or missing fields")
    accepted_fields = {frozenset(SNAPSHOT_FIELDS)}
    if allow_legacy:
        accepted_fields.add(frozenset(LEGACY_SNAPSHOT_FIELDS))
    if frozenset(snapshot) not in accepted_fields:
        raise BackupError("backup database snapshot has unexpected or missing fields")
    return snapshot


def _validate_snapshot(snapshot: object, *, allow_legacy: bool) -> None:
    snapshot = _validate_snapshot_fields(snapshot, allow_legacy)
    if not _valid_hash(snapshot["schema_sha256"], SHA256_PATTERN):
        raise BackupError("backup database snapshot schema hash is invalid")
    if not _valid_hash(snapshot["active_portfolios_sha256"], SHA256_PATTERN):
        raise BackupError("backup database snapshot active-portfolios hash is invalid")
    for field in ("table_count", "view_count", "active_portfolio_count"):
        _validate_nonnegative_int(snapshot[field], f"backup database snapshot {field}")
    if "index_count" in snapshot:
        _validate_nonnegative_int(
            snapshot["index_count"], "backup database snapshot index_count"
        )
    _validate_count_map(snapshot["row_counts"], "row_counts")
    _validate_count_map(snapshot["job_states"], "job_states")
    latest_price_date = snapshot["latest_price_date"]
    if latest_price_date is not None:
        try:
            parsed_date = date.fromisoformat(latest_price_date)
        except (TypeError, ValueError) as exc:
            raise BackupError("backup database snapshot latest price date is invalid") from exc
        if parsed_date.isoformat() != latest_price_date:
            raise BackupError("backup database snapshot latest price date is invalid")


def _validate_database_metadata(database: object, *, allow_legacy: bool) -> None:
    if not isinstance(database, dict) or set(database) != DATABASE_FIELDS:
        raise BackupError("backup database manifest is invalid")
    if database["filename"] != DATABASE_FILENAME:
        raise BackupError("backup database filename is invalid")
    _validate_nonnegative_int(database["size_bytes"], "backup database size_bytes")
    if not _valid_hash(database["sha256"], SHA256_PATTERN):
        raise BackupError("backup database hash is invalid")
    _validate_snapshot(database["snapshot"], allow_legacy=allow_legacy)


def _validate_evidence_metadata(evidence: object) -> None:
    _validate_file_records(evidence, EVIDENCE_FILES, "prospective evidence")


def _operational_files(latest_price_date: object) -> tuple[str, ...]:
    if not isinstance(latest_price_date, str):
        raise BackupError("operational artifacts require a latest price date")
    return (*OPERATIONAL_STATIC_FILES, *(
        f"data/screens/{latest_price_date}.{suffix}" for suffix in ("md", "csv")
    ))


def _validate_file_records(files: object, expected: tuple[str, ...], label: str) -> None:
    if not isinstance(files, dict) or set(files) != set(expected):
        raise BackupError(f"{label} manifest has unexpected or missing entries")
    for relative, record in files.items():
        if not isinstance(record, dict) or set(record) != EVIDENCE_RECORD_FIELDS:
            raise BackupError(f"{label} manifest is invalid: {relative}")
        expected_path = (Path("evidence") / relative).as_posix()
        if not isinstance(record["bundle_path"], str) or record["bundle_path"] != expected_path:
            raise BackupError(f"{label} path is invalid: {relative}")
        _validate_nonnegative_int(record["size_bytes"], f"{label} size_bytes: {relative}")
        if not _valid_hash(record["sha256"], SHA256_PATTERN):
            raise BackupError(f"{label} hash is invalid: {relative}")


def _validate_operational_metadata(artifacts: object, snapshot: dict) -> None:
    _validate_file_records(
        artifacts,
        _operational_files(snapshot["latest_price_date"]),
        "operational artifacts",
    )


def _validate_operational_controls(controls: object) -> None:
    if not isinstance(controls, dict) or not set(controls).issubset(
        OPTIONAL_OPERATIONAL_CONTROL_FILES
    ):
        raise BackupError(
            "operational controls manifest has unexpected or missing entries"
        )
    _validate_file_records(
        controls,
        tuple(relative for relative in OPTIONAL_OPERATIONAL_CONTROL_FILES if relative in controls),
        "operational controls",
    )


def _validate_manifest_metadata(manifest: dict, schema_version: int) -> None:
    expected_fields = {
        1: V1_MANIFEST_FIELDS,
        2: V2_MANIFEST_FIELDS,
        3: V3_MANIFEST_FIELDS,
    }[schema_version]
    if set(manifest) != expected_fields:
        raise BackupError("backup manifest has unexpected or missing fields")
    _validate_created_at(manifest["created_at"])
    _validate_source_database(manifest["source_database"])
    _validate_database_metadata(manifest["database"], allow_legacy=schema_version == 1)
    _validate_evidence_metadata(manifest["prospective_evidence"])
    if schema_version >= 2:
        _validate_operational_metadata(
            manifest["operational_artifacts"], manifest["database"]["snapshot"]
        )
    if schema_version >= 3:
        _validate_operational_controls(manifest["operational_controls"])
    _validate_release_identity(manifest["release_identity"])


def _catalog_rows(connection: duckdb.DuckDBPyConnection, database: str) -> dict:
    tables = connection.execute(
        "SELECT schema_name, table_name, sql FROM duckdb_tables() "
        "WHERE database_name = ? AND NOT internal AND NOT temporary "
        "ORDER BY schema_name, table_name",
        [database],
    ).fetchall()
    views = connection.execute(
        "SELECT schema_name, view_name, sql FROM duckdb_views() "
        "WHERE database_name = ? AND NOT internal AND NOT temporary "
        "ORDER BY schema_name, view_name",
        [database],
    ).fetchall()
    indexes = connection.execute(
        "SELECT schema_name, index_name, table_name, is_unique, is_primary, sql "
        "FROM duckdb_indexes() WHERE database_name = ? "
        "ORDER BY schema_name, index_name",
        [database],
    ).fetchall()
    return {"tables": tables, "views": views, "indexes": indexes}


def _table_row_counts(
    connection: duckdb.DuckDBPyConnection,
    database: str,
    table_names: set[tuple[str, str]],
) -> dict[str, int]:
    row_counts = {}
    for schema, table in sorted(table_names):
        qualified = ".".join(map(_identifier, (database, schema, table)))
        row_counts[f"{schema}.{table}"] = connection.execute(
            f"SELECT COUNT(*) FROM {qualified}"
        ).fetchone()[0]
    return row_counts


def database_snapshot(connection: duckdb.DuckDBPyConnection, database: str) -> dict:
    """Return restore invariants for one attached database."""
    catalog = _catalog_rows(connection, database)
    table_names = {(schema, table) for schema, table, _sql in catalog["tables"]}
    missing = sorted(REQUIRED_TABLES - {table for _schema, table in table_names})
    if missing:
        raise BackupError(f"required database tables missing: {', '.join(missing)}")
    row_counts = _table_row_counts(connection, database, table_names)
    prefix = f"{_identifier(database)}.{_identifier('main')}"
    latest_price_date = connection.execute(
        f"SELECT CAST(MAX(date) AS VARCHAR) FROM {prefix}.{_identifier('prices')}"
    ).fetchone()[0]
    job_states = dict(
        connection.execute(
            f"SELECT state, COUNT(*) FROM {prefix}.{_identifier('jobs')} "
            "GROUP BY state ORDER BY state"
        ).fetchall()
    )
    active_portfolios = connection.execute(
        f"SELECT id, name, strategy, config, CAST(created AS VARCHAR), cash, initial_cash, "
        f"execution_profile FROM {prefix}.{_identifier('portfolios')} "
        "WHERE active ORDER BY id"
    ).fetchall()
    return {
        "schema_sha256": canonical_sha256(catalog),
        "table_count": len(catalog["tables"]),
        "view_count": len(catalog["views"]),
        "index_count": len(catalog["indexes"]),
        "row_counts": row_counts,
        "latest_price_date": latest_price_date,
        "job_states": job_states,
        "active_portfolio_count": len(active_portfolios),
        "active_portfolios_sha256": canonical_sha256(active_portfolios),
    }


def _copy_database(source: Path, destination: Path) -> dict:
    connection = duckdb.connect()
    try:
        connection.execute(f"ATTACH {_sql_string(str(destination))} AS backup_target")
        connection.execute(f"ATTACH {_sql_string(str(source))} AS backup_source (READ_ONLY)")
        source_snapshot = database_snapshot(connection, "backup_source")
        connection.execute("COPY FROM DATABASE backup_source TO backup_target")
        target_snapshot = database_snapshot(connection, "backup_target")
        connection.execute("DETACH backup_target")
        connection.execute("DETACH backup_source")
    except duckdb.Error as exc:
        raise BackupError(f"DuckDB snapshot failed: {exc}") from exc
    finally:
        connection.close()
    if target_snapshot != source_snapshot:
        raise BackupError("copied database invariants do not match the source snapshot")
    return target_snapshot


def _copy_files(
    repo_root: Path, bundle: Path, relatives: tuple[str, ...], label: str
) -> dict[str, dict]:
    result = {}
    for relative in relatives:
        destination = bundle / "evidence" / relative
        _mkdir_private_tree(bundle, destination.parent)
        content = _read_source_file(repo_root, relative, label)
        destination.write_bytes(content)
        destination.chmod(0o600)
        result[relative] = {
            "bundle_path": destination.relative_to(bundle).as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return result


def _copy_evidence(repo_root: Path, bundle: Path) -> dict[str, dict]:
    return _copy_files(repo_root, bundle, EVIDENCE_FILES, "prospective evidence")


def _copy_operational_artifacts(
    repo_root: Path, bundle: Path, latest_price_date: object
) -> dict[str, dict]:
    return _copy_files(
        repo_root,
        bundle,
        _operational_files(latest_price_date),
        "operational artifact",
    )


def _copy_optional_operational_controls(
    repo_root: Path,
    bundle: Path,
) -> dict[str, dict]:
    result = {}
    for relative in OPTIONAL_OPERATIONAL_CONTROL_FILES:
        try:
            content = _read_source_file(repo_root, relative, "operational control")
        except SourceFileMissing:
            continue
        destination = bundle / "evidence" / relative
        _mkdir_private_tree(bundle, destination.parent)
        destination.write_bytes(content)
        destination.chmod(0o600)
        result[relative] = {
            "bundle_path": destination.relative_to(bundle).as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return result


def _source_location(repo_root: Path, source: Path) -> dict:
    try:
        relative = source.relative_to(repo_root)
    except ValueError:
        return {"kind": "external", "path": None}
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _release_summary(repo_root: Path, source: Path, database_read_path: Path) -> dict:
    manifest = release_manifest.build_manifest(
        repo_root, source, _database_read_path=database_read_path
    )
    return {
        "status": manifest["status"],
        "release_eligible": manifest["release_eligible"],
        "manifest_sha256": manifest["manifest_sha256"],
        "git_sha": manifest["git"]["sha"],
        "working_tree_sha256": manifest["git"]["working_tree"]["sha256"],
        "research_runtime": manifest["research_runtime"],
    }


def _manifest_body(
    repo_root: Path,
    source: Path,
    database_read_path: Path,
    bundle: Path,
    snapshot: dict,
) -> dict:
    database = bundle / DATABASE_FILENAME
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_database": _source_location(repo_root, source),
        "database": {
            "filename": DATABASE_FILENAME,
            "size_bytes": database.stat().st_size,
            "sha256": _sha256(database),
            "snapshot": snapshot,
        },
        "prospective_evidence": _copy_evidence(repo_root, bundle),
        "operational_artifacts": _copy_operational_artifacts(
            repo_root, bundle, snapshot["latest_price_date"]
        ),
        "operational_controls": _copy_optional_operational_controls(repo_root, bundle),
        "release_identity": _release_summary(repo_root, source, database_read_path),
    }


def create_backup(repo_root: Path, source: Path, destination: Path) -> dict:
    """Create, verify, and atomically publish a new local recovery bundle."""
    repo_root = repo_root.resolve()
    source = source.resolve()
    if os.path.lexists(destination):
        raise BackupError("backup destination already exists; refusing to overwrite")
    destination = destination.absolute()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = destination.parent.resolve(strict=True) / destination.name
    except OSError as exc:
        raise BackupError("backup destination parent is unavailable") from exc
    if os.path.lexists(destination):
        raise BackupError("backup destination already exists; refusing to overwrite")
    if destination == repo_root or repo_root in destination.parents:
        raise BackupError("backup destination must be outside the repository")
    with _open_destination_parent(destination.parent) as parent_fd:
        temporary_name, temporary_fd = _make_temporary_bundle(parent_fd, destination.name)
        published = False
        try:
            temporary = _descriptor_path(temporary_fd)
            with _exclusive_backup_window(repo_root):
                with _open_source_database(source) as (
                    source_parent_fd,
                    source_fd,
                    source_initial,
                ):
                    source_read_path = _descriptor_path(source_fd)
                    database = temporary / DATABASE_FILENAME
                    snapshot = _copy_database(source_read_path, database)
                    database.chmod(0o600)
                    _require_source_database_identity(
                        source, source_parent_fd, source_fd, source_initial
                    )
                    body = _manifest_body(
                        repo_root, source, source_read_path, temporary, snapshot
                    )
                    manifest = {**body, "manifest_sha256": canonical_sha256(body)}
                    manifest_path = temporary / MANIFEST_FILENAME
                    write_text_atomic(
                        manifest_path,
                        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    )
                    manifest_path.chmod(0o600)
                    result = _verify_backup_at_descriptor(temporary_fd)
                    _sync_bundle(temporary, temporary_fd)
                    _require_source_database_identity(
                        source, source_parent_fd, source_fd, source_initial
                    )
                    _require_destination_parent_identity(
                        destination.parent, parent_fd, published=False
                    )
                    _require_temporary_bundle_identity(
                        parent_fd, temporary_name, temporary_fd
                    )
                    _publish_no_replace(parent_fd, temporary_name, destination.name)
                    published = True
                    _sync_directory_fd(parent_fd, label="backup parent directory")
                    _require_source_database_identity(
                        source, source_parent_fd, source_fd, source_initial
                    )
                    _require_destination_parent_identity(
                        destination.parent, parent_fd, published=True
                    )
        finally:
            if not published:
                _remove_temporary_bundle(parent_fd, temporary_name, temporary_fd)
            os.close(temporary_fd)
    return {**result, "bundle": str(destination)}


def _load_manifest(bundle: Path) -> tuple[dict, str]:
    manifest_path = bundle / MANIFEST_FILENAME
    if manifest_path.is_symlink():
        raise BackupError("backup manifest must be a regular file, not a symlink")
    _require_private(manifest_path, directory=False, label="backup manifest")
    try:
        manifest = load_object(manifest_path)
    except (OSError, ValueError) as exc:
        raise BackupError(f"backup manifest is unreadable: {exc}") from exc
    recorded_hash = manifest.pop("manifest_sha256", None)
    if recorded_hash != canonical_sha256(manifest):
        raise BackupError("backup manifest hash does not match its contents")
    schema_version = manifest.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise BackupError("unsupported backup manifest schema")
    _validate_manifest_metadata(manifest, schema_version)
    return manifest, recorded_hash


def _verify_database(bundle: Path, manifest: dict) -> tuple[dict, dict]:
    database = bundle / DATABASE_FILENAME
    expected = manifest["database"]
    if database.is_symlink():
        raise BackupError("backup database must be a regular file, not a symlink")
    _require_private(database, directory=False, label="backup database")
    if not database.is_file():
        raise BackupError("backup database is missing")
    if database.stat().st_size != expected["size_bytes"] or _sha256(database) != expected["sha256"]:
        raise BackupError("backup database file integrity check failed")
    try:
        connection = duckdb.connect(str(database), read_only=True)
        try:
            actual_snapshot = database_snapshot(connection, connection.execute(
                "SELECT current_database()"
            ).fetchone()[0])
        finally:
            connection.close()
    except duckdb.Error as exc:
        raise BackupError(f"backup database is unreadable: {exc}") from exc
    expected_snapshot = expected["snapshot"]
    comparable_snapshot = actual_snapshot
    if "index_count" not in expected_snapshot:
        comparable_snapshot = {
            key: value for key, value in actual_snapshot.items() if key != "index_count"
        }
    if comparable_snapshot != expected_snapshot:
        raise BackupError("backup database invariants do not match its manifest")
    return expected, actual_snapshot


def _bundled_file_path(bundle: Path, relative: str, record: dict, label: str) -> Path:
    bundle_path = record["bundle_path"]
    path = bundle / bundle_path
    current = bundle
    for part in Path(bundle_path).parts:
        current /= part
        if current.is_symlink():
            raise BackupError(f"{label} must not use symlinks: {relative}")
    return path


def _verify_file_records(bundle: Path, records: dict, label: str) -> None:
    for relative, expected_file in records.items():
        path = _bundled_file_path(bundle, relative, expected_file, label)
        _require_private(path, directory=False, label=f"{label} {relative}")
        if (
            path.stat().st_size != expected_file["size_bytes"]
            or _sha256(path) != expected_file["sha256"]
        ):
            raise BackupError(f"{label} integrity check failed: {relative}")


def _verify_evidence(bundle: Path, manifest: dict) -> dict:
    evidence = manifest["prospective_evidence"]
    _verify_file_records(bundle, evidence, "prospective evidence")
    return evidence


def _verify_operational_artifacts(bundle: Path, manifest: dict) -> dict:
    artifacts = manifest.get("operational_artifacts", {})
    _verify_file_records(bundle, artifacts, "operational artifact")
    return artifacts


def _verify_operational_controls(bundle: Path, manifest: dict) -> dict:
    controls = manifest.get("operational_controls", {})
    _verify_file_records(bundle, controls, "operational control")
    return controls


def _verify_exact_bundle_tree(bundle: Path, manifest: dict) -> None:
    expected_files = {DATABASE_FILENAME, MANIFEST_FILENAME}
    expected_files.update(
        record["bundle_path"]
        for section in (
            "prospective_evidence",
            "operational_artifacts",
            "operational_controls",
        )
        for record in manifest.get(section, {}).values()
    )
    expected_directories = set()
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    try:
        paths = list(bundle.rglob("*"))
    except OSError as exc:
        raise BackupError(f"backup tree is unreadable: {exc}") from exc
    actual = {path.relative_to(bundle).as_posix() for path in paths}
    if actual != expected_files | expected_directories:
        raise BackupError("backup tree has unexpected or missing entries")
    for path in paths:
        relative = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            raise BackupError(f"backup tree must not use symlinks: {relative}")
        _require_private(
            path,
            directory=relative in expected_directories,
            label=f"backup path {relative}",
        )


def _verify_operational_consistency(bundle: Path, manifest: dict) -> None:
    if manifest["schema_version"] == 1:
        return
    latest = date.fromisoformat(manifest["database"]["snapshot"]["latest_price_date"])
    data_dir = bundle / "evidence" / "data"
    try:
        meta = load_object(data_dir / "_meta.json")
        connection = duckdb.connect(str(bundle / DATABASE_FILENAME), read_only=True)
        try:
            result = nightly_monitor.validate_snapshot(
                meta, connection, latest, data_dir=data_dir
            )
        finally:
            connection.close()
    except (OSError, ValueError, duckdb.Error) as exc:
        raise BackupError(f"operational artifacts are unreadable: {exc}") from exc
    if result.get("status") != "current":
        reason = result.get("reason", result.get("status", "invalid"))
        raise BackupError(
            f"operational artifacts do not match backup database: {reason}"
        )


def _verify_backup(bundle: Path) -> dict:
    """Verify through a caller-owned descriptor-rooted bundle path."""
    _require_private(bundle, directory=True, label="backup bundle")
    manifest, recorded_hash = _load_manifest(bundle)
    expected, actual_snapshot = _verify_database(bundle, manifest)
    evidence = _verify_evidence(bundle, manifest)
    operational = _verify_operational_artifacts(bundle, manifest)
    controls = _verify_operational_controls(bundle, manifest)
    _verify_exact_bundle_tree(bundle, manifest)
    _verify_operational_consistency(bundle, manifest)
    return {
        "status": "ok",
        "bundle": str(bundle),
        "manifest_sha256": recorded_hash,
        "database_sha256": expected["sha256"],
        "database_size_bytes": expected["size_bytes"],
        "database_snapshot_sha256": canonical_sha256(actual_snapshot),
        "source_database": manifest["source_database"],
        "table_count": actual_snapshot["table_count"],
        "evidence_file_count": len(evidence),
        "operational_artifact_count": len(operational),
        "operational_control_count": len(controls),
    }


def _verify_backup_at_descriptor(bundle_fd: int) -> dict:
    """Verify a bundle through its retained directory descriptor."""
    bundle = _descriptor_path(bundle_fd)
    opened = os.fstat(bundle_fd)
    if not stat.S_ISDIR(opened.st_mode):
        raise BackupError("temporary backup bundle has an unexpected file type")
    return _verify_backup(bundle)


def verify_backup(bundle: Path) -> dict:
    """Verify a recovery bundle without changing it or the active database."""
    with _open_bundle_for_verification(bundle) as (
        requested,
        parent_fd,
        bundle_fd,
        initial,
    ):
        descriptor_root = _descriptor_path(bundle_fd)
        initial_tree = _bundle_tree_identity(descriptor_root)
        result = _verify_backup_at_descriptor(bundle_fd)
        if _bundle_tree_identity(descriptor_root) != initial_tree:
            raise BackupError("backup bundle changed during verification")
        _require_verified_bundle_identity(requested, parent_fd, bundle_fd, initial)
    return {**result, "bundle": str(requested)}


def _resolve_from_repo(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create a new recovery bundle")
    create.add_argument("destination", type=Path)
    create.add_argument("--source", type=Path, default=DEFAULT_DB)
    verify = subparsers.add_parser("verify", help="verify an existing recovery bundle")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        if args.command == "create":
            result = create_backup(
                repo_root,
                _resolve_from_repo(repo_root, args.source),
                _resolve_from_repo(repo_root, args.destination),
            )
        else:
            result = verify_backup(_resolve_from_repo(repo_root, args.bundle))
    except (BackupError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
