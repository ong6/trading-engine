#!/usr/bin/env python3
"""Emit a deterministic, read-only identity for a release candidate.

This tool hashes source and configuration and reads only the market database's
catalog schema. It does not read table rows, inspect credentials, contact
remotes, or claim that a backup or deployment is recoverable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

import duckdb

from engine.lib.provenance import SOURCE_FILES, SOURCE_ROOTS, canonical_sha256, runtime_source_hash
from engine.lib.settings import REPO_ROOT

SCHEMA_VERSION = 5

DEPENDENCY_FILES = (
    "pyproject.toml",
    "uv.lock",
    "engine/requirements.txt",
    "ui/package.json",
    "ui/package-lock.json",
)
SCHEMA_SOURCE_FILES = (
    "engine/lib/db.py",
    "engine/queue_runner.py",
    "sim/schema.py",
    "sim/settle.py",
)
SERVICE_FILES = (
    "server/trading-engine-api.service",
    "ui/trading-engine-ui.service",
)
RECOVERY_SOURCE_FILES = (
    "engine/__init__.py",
    "engine/lib/__init__.py",
    "engine/lib/log.py",
    "engine/lib/provenance.py",
    "engine/lib/resources.py",
    "engine/lib/settings.py",
    "engine/lib/util.py",
    "server/__init__.py",
    "server/driver_log.py",
    "server/driver_monitor.py",
    "server/file_utils.py",
    "server/json_utils.py",
    "server/nightly_monitor.py",
    "server/nightly_reports.py",
    "server/status_validation.py",
    "tools/__init__.py",
    "tools/backup_database.py",
    "tools/release_manifest.py",
)
AUDIT_SOURCE_FILES = (
    "tools/release_manifest.py",
    "tools/worktree_audit.py",
)
EXPERIMENT_REGISTRATION_FILES = (
    "farm/experiments/e1-spy-monday.forward.json",
    "farm/experiments/e1-spy-monday.yaml",
)
STRATEGY_REGISTRATION_FILES = ("sim/strategies/configs.py",)
EXECUTION_PROFILE_FILES = ("sim/execution.py",)
PROSPECTIVE_EVIDENCE_FILES = (
    "data/reports/experiments/e1-spy-monday-forward.json",
    "data/reports/forward/sector_momentum.json",
    "data/reports/forward/xs_momentum_12_1.json",
)
SCHEDULE_SOURCE_FILES = (
    "engine/lib/driver.sh",
    "engine/run_daily.sh",
    "engine/run_weekend_sweeps.sh",
    "engine/run_weekly_liquid.sh",
    "engine/run_weekly_verify.sh",
    "engine/run_weekly_walkforward.sh",
    "server/driver_monitor.py",
    "server/friday_postflight.py",
    "server/host_command.py",
    "server/scheduler_host.py",
    "server/scheduler_monitor.py",
    "tools/install_automation.py",
    "tools/verify_friday_postflight.py",
)
REQUIRED_FILES = tuple(
    sorted(
        set(
            DEPENDENCY_FILES
            + AUDIT_SOURCE_FILES
            + EXECUTION_PROFILE_FILES
            + EXPERIMENT_REGISTRATION_FILES
            + PROSPECTIVE_EVIDENCE_FILES
            + RECOVERY_SOURCE_FILES
            + SCHEMA_SOURCE_FILES
            + SERVICE_FILES
            + SCHEDULE_SOURCE_FILES
            + STRATEGY_REGISTRATION_FILES
        )
    )
)


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_value(repo_root: Path, *args: str) -> str | None:
    result = _git(repo_root, *args)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_paths(repo_root: Path) -> list[str] | None:
    """Return every tracked or unignored path without newline ambiguity."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return sorted(os.fsdecode(value) for value in result.stdout.split(b"\0") if value)


def _git_changed_path_count(repo_root: Path) -> int | None:
    """Count porcelain records without treating newlines in paths as separators."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=repo_root,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    fields = result.stdout.split(b"\0")
    count = 0
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            return None
        status = record[:2]
        count += 1
        if status[:1] in {b"R", b"C"} or status[1:] in {b"R", b"C"}:
            if index >= len(fields) or not fields[index]:
                return None
            index += 1
    return count


def _file_read_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@contextmanager
def _open_path_parent(anchor: Path, parts: tuple[str, ...]):
    """Open one absolute parent chain without following component symlinks."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise OSError("secure release-file traversal is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    with ExitStack() as stack:
        current = os.open(anchor, flags)
        stack.callback(os.close, current)
        identities = [(os.fstat(current).st_dev, os.fstat(current).st_ino)]
        for part in parts:
            current = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, current)
            opened = os.fstat(current)
            identities.append((opened.st_dev, opened.st_ino))
        yield current, tuple(identities)


def _read_stable_regular_file(path: Path) -> tuple[bytes, int]:
    """Read one regular file through stable no-follow parent and leaf descriptors."""
    requested = path.absolute()
    anchor = Path(requested.anchor)
    parts = requested.relative_to(anchor).parts
    if not parts:
        raise OSError("release file path has no leaf")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("secure release-file opening is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )
    with _open_path_parent(anchor, parts[:-1]) as (parent_fd, parent_chain):
        descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise OSError("release file is not regular")
            chunks = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(descriptor)
            anchored = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        finally:
            os.close(descriptor)
        with _open_path_parent(anchor, parts[:-1]) as (visible_parent_fd, visible_chain):
            visible = os.stat(
                parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False
            )
    content = b"".join(chunks)
    if (
        parent_chain != visible_chain
        or not stat.S_ISREG(after.st_mode)
        or not stat.S_ISREG(anchored.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or _file_read_identity(before) != _file_read_identity(after)
        or _file_read_identity(after) != _file_read_identity(anchored)
        or _file_read_identity(anchored) != _file_read_identity(visible)
        or len(content) != before.st_size
    ):
        raise OSError("release file changed during read")
    return content, before.st_mode


def _read_stable_symlink(path: Path) -> bytes:
    """Read one symlink target without following a changing leaf or parent chain."""
    requested = path.absolute()
    anchor = Path(requested.anchor)
    parts = requested.relative_to(anchor).parts
    if not parts:
        raise OSError("release symlink path has no leaf")
    with _open_path_parent(anchor, parts[:-1]) as (parent_fd, parent_chain):
        before = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode):
            raise OSError("release path is not a symlink")
        target = os.readlink(parts[-1], dir_fd=parent_fd)
        after = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        with _open_path_parent(anchor, parts[:-1]) as (visible_parent_fd, visible_chain):
            visible = os.stat(
                parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False
            )
            visible_target = os.readlink(parts[-1], dir_fd=visible_parent_fd)
    if (
        parent_chain != visible_chain
        or not stat.S_ISLNK(after.st_mode)
        or not stat.S_ISLNK(visible.st_mode)
        or _file_read_identity(before) != _file_read_identity(after)
        or _file_read_identity(after) != _file_read_identity(visible)
        or target != visible_target
    ):
        raise OSError("release symlink changed during read")
    return os.fsencode(target)


def _sha256(path: Path) -> str:
    content, _mode = _read_stable_regular_file(path)
    return hashlib.sha256(content).hexdigest()


def _is_in_tree_regular_file(repo_root: Path, relative: str) -> bool:
    current = repo_root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            return False
    return current.is_file()


def _file_set(repo_root: Path, relative_paths: tuple[str, ...]) -> dict:
    files: dict[str, str | None] = {}
    complete = True
    for relative in sorted(relative_paths):
        path = repo_root / relative
        if not _is_in_tree_regular_file(repo_root, relative):
            files[relative] = None
            complete = False
            continue
        try:
            file_hash = _sha256(path)
        except OSError:
            files[relative] = None
            complete = False
            continue
        files[relative] = file_hash
    return {
        "sha256": canonical_sha256(files) if complete else None,
        "file_count": len(relative_paths),
        "files": files,
    }


def _working_tree_identity(repo_root: Path) -> dict:
    """Bind names, types, executable bits, and bytes of the reviewable tree."""
    relative_paths = _git_paths(repo_root)
    if relative_paths is None:
        return {"sha256": None, "file_count": None, "missing_paths": []}

    digest = hashlib.sha256()
    missing_paths: list[str] = []
    for relative in relative_paths:
        path = repo_root / relative
        encoded_path = os.fsencode(relative)
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        if path.is_symlink():
            try:
                content = _read_stable_symlink(path)
            except OSError:
                kind = b"missing"
                content = b""
                executable = b"0"
                missing_paths.append(relative)
            else:
                kind = b"symlink"
                executable = b"0"
        elif path.is_file():
            try:
                content, mode = _read_stable_regular_file(path)
            except OSError:
                kind = b"missing"
                content = b""
                executable = b"0"
                missing_paths.append(relative)
            else:
                kind = b"file"
                executable = b"1" if mode & 0o111 else b"0"
        else:
            kind = b"missing"
            content = b""
            executable = b"0"
            missing_paths.append(relative)
        for value in (kind, executable, content):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return {
        "sha256": digest.hexdigest(),
        "file_count": len(relative_paths),
        "missing_paths": missing_paths,
    }


def _working_tree_filesystem_identity(
    repo_root: Path,
) -> dict[str, tuple[int, int, int, int, int, int] | None] | None:
    """Capture private change-detection metadata for files and their parent paths."""
    relative_paths = _git_paths(repo_root)
    if relative_paths is None:
        return None
    paths = {Path(".")}
    for relative in relative_paths:
        current = Path(relative)
        paths.add(current)
        paths.update(current.parents)
    identity = {}
    for relative in sorted(paths, key=lambda path: path.as_posix()):
        try:
            value = (repo_root / relative).lstat()
        except OSError:
            identity[relative.as_posix()] = None
            continue
        identity[relative.as_posix()] = (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    return identity


def research_runtime_identity(repo_root: Path) -> dict:
    """Return the established source hash only for an in-tree regular-file runtime."""
    has_symlink = False
    for root_name in SOURCE_ROOTS:
        root = repo_root / root_name
        has_symlink = has_symlink or root.is_symlink()
        if root.is_dir() and not root.is_symlink():
            has_symlink = has_symlink or any(path.is_symlink() for path in root.rglob("*"))
    has_symlink = has_symlink or any((repo_root / name).is_symlink() for name in SOURCE_FILES)
    sha256, file_count = runtime_source_hash(repo_root)
    return {"sha256": None if has_symlink else sha256, "file_count": file_count}


def _database_location(repo_root: Path, database: Path) -> dict:
    try:
        relative = database.relative_to(repo_root)
    except ValueError:
        return {"kind": "external", "path": None}
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _database_schema_failure(status: str, reason: str, location: dict) -> dict:
    return {
        "status": status,
        "reason": reason,
        "location": location,
        "sha256": None,
        "table_count": None,
        "view_count": None,
        "index_count": None,
    }


def _database_catalog(connection: duckdb.DuckDBPyConnection) -> dict:
    tables = connection.execute(
        "SELECT schema_name, table_name, sql FROM duckdb_tables() "
        "WHERE database_name = current_database() AND NOT internal AND NOT temporary "
        "ORDER BY schema_name, table_name"
    ).fetchall()
    views = connection.execute(
        "SELECT schema_name, view_name, sql FROM duckdb_views() "
        "WHERE database_name = current_database() AND NOT internal AND NOT temporary "
        "ORDER BY schema_name, view_name"
    ).fetchall()
    indexes = connection.execute(
        "SELECT schema_name, index_name, table_name, is_unique, is_primary, sql "
        "FROM duckdb_indexes() WHERE database_name = current_database() "
        "ORDER BY schema_name, index_name"
    ).fetchall()
    return {"tables": tables, "views": views, "indexes": indexes}


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _database_parent_chain_identity(
    chain: tuple[tuple[int, int, int, int, int], ...],
) -> tuple[tuple[int, ...], ...]:
    """Bind every path component without treating unrelated child churn as replacement."""
    return tuple(value[:2] for value in chain)


def _database_identity(
    parent_chain: tuple[tuple[int, int, int, int, int], ...],
    leaf: os.stat_result,
) -> tuple[tuple[tuple[int, ...], ...], tuple[int, int, int, int, int]]:
    return _database_parent_chain_identity(parent_chain), _stat_identity(leaf)


@contextmanager
def _open_database_parent(anchor: Path, parts: tuple[str, ...]):
    """Open an absolute directory chain without following symlinks."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise OSError("secure database schema traversal is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    with ExitStack() as stack:
        current = os.open(anchor, flags)
        stack.callback(os.close, current)
        identities = [_stat_identity(os.fstat(current))]
        for part in parts:
            child = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, child)
            current = child
            identities.append(_stat_identity(os.fstat(current)))
        yield current, tuple(identities)


@contextmanager
def _open_database_schema_path(database: Path):
    """Open an absolute database path without following any symlink component."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("secure database schema traversal is unavailable")
    anchor = Path(database.anchor)
    parts = database.relative_to(anchor).parts
    if not parts:
        raise OSError("database schema path has no file leaf")
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow
    with _open_database_parent(anchor, parts[:-1]) as (parent_fd, parent_chain):
        descriptor = os.open(parts[-1], file_flags, dir_fd=parent_fd)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise OSError("database schema path is not a regular file")
            yield parent_fd, descriptor, opened, parent_chain
        finally:
            os.close(descriptor)


def _database_descriptor_path(descriptor: int) -> Path:
    path = Path("/proc/self/fd") / str(descriptor)
    visible = path.stat()
    opened = os.fstat(descriptor)
    if (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino):
        raise OSError("database descriptor path changed")
    return path


def _database_filesystem_identity(
    database: Path,
) -> tuple[
    tuple[tuple[int, ...], ...], tuple[int, int, int, int, int]
] | None:
    """Return private parent/leaf identity without following path symlinks."""
    try:
        with _open_database_schema_path(database) as (
            _parent_fd,
            _descriptor,
            opened,
            parent_chain,
        ):
            return _database_identity(parent_chain, opened)
    except OSError:
        return None


def _database_path_unchanged(
    database: Path,
    parent_fd: int,
    descriptor: int,
    initial: os.stat_result,
    initial_parent_chain: tuple[tuple[int, int, int, int, int], ...],
) -> bool:
    anchor = Path(database.anchor)
    parts = database.relative_to(anchor).parts
    try:
        opened = os.fstat(descriptor)
        anchored = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        with _open_database_parent(anchor, parts[:-1]) as (
            visible_parent_fd,
            visible_parent_chain,
        ):
            visible_parent = os.fstat(visible_parent_fd)
            visible = os.stat(parts[-1], dir_fd=visible_parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return (
        (os.fstat(parent_fd).st_dev, os.fstat(parent_fd).st_ino)
        == (visible_parent.st_dev, visible_parent.st_ino)
        and _database_parent_chain_identity(initial_parent_chain)
        == _database_parent_chain_identity(visible_parent_chain)
        and stat.S_ISREG(opened.st_mode)
        and stat.S_ISREG(anchored.st_mode)
        and stat.S_ISREG(visible.st_mode)
        and _stat_identity(initial) == _stat_identity(opened)
        and _stat_identity(opened) == _stat_identity(anchored)
        and _stat_identity(anchored) == _stat_identity(visible)
    )


def _read_database_schema(database: Path) -> dict:
    connection = duckdb.connect(str(database), read_only=True)
    try:
        return _database_catalog(connection)
    finally:
        connection.close()


def _database_schema(
    repo_root: Path,
    database: Path,
    *,
    location_database: Path | None = None,
    trusted_read_path: bool = False,
    expected_identity: tuple[
        tuple[tuple[int, ...], ...], tuple[int, int, int, int, int]
    ] | None = None,
) -> dict:
    """Hash stable DDL catalog fields without reading application rows."""
    location = _database_location(repo_root, location_database or database)
    try:
        if trusted_read_path:
            if not database.is_file():
                return _database_schema_failure("missing", "database-missing", location)
            schema = _read_database_schema(database)
        else:
            with _open_database_schema_path(database) as (
                parent_fd,
                descriptor,
                initial,
                parent_chain,
            ):
                if (
                    expected_identity is not None
                    and _database_identity(parent_chain, initial) != expected_identity
                ):
                    return _database_schema_failure(
                        "unsafe", "database-schema-path-unsafe", location
                    )
                schema = _read_database_schema(_database_descriptor_path(descriptor))
                if not _database_path_unchanged(
                    database, parent_fd, descriptor, initial, parent_chain
                ):
                    return _database_schema_failure(
                        "unsafe", "database-schema-path-unsafe", location
                    )
    except FileNotFoundError:
        return _database_schema_failure("missing", "database-missing", location)
    except (OSError, duckdb.Error):
        reason = "database-schema-unreadable" if trusted_read_path else "database-schema-path-unsafe"
        status = "unreadable" if trusted_read_path else "unsafe"
        return _database_schema_failure(status, reason, location)

    return {
        "status": "ok",
        "reason": None,
        "location": location,
        "sha256": canonical_sha256(schema),
        "table_count": len(schema["tables"]),
        "view_count": len(schema["views"]),
        "index_count": len(schema["indexes"]),
    }


def _git_reference_identity(repo_root: Path) -> dict:
    """Return Git ref, index, and status identity without hashing worktree bytes."""
    changed_paths = _git_changed_path_count(repo_root)

    tracked_result = _git(repo_root, "ls-files", "--", *REQUIRED_FILES)
    tracked = (
        set(tracked_result.stdout.splitlines())
        if tracked_result is not None and tracked_result.returncode == 0
        else None
    )
    untracked_required = (
        sorted(set(REQUIRED_FILES) - tracked) if tracked is not None else list(REQUIRED_FILES)
    )

    return {
        "sha": _git_value(repo_root, "rev-parse", "HEAD"),
        "tree": _git_value(repo_root, "rev-parse", "HEAD^{tree}"),
        "branch": _git_value(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD"),
        "dirty": bool(changed_paths) if changed_paths is not None else None,
        "changed_path_count": changed_paths,
        "required_files_tracked": tracked is not None and not untracked_required,
        "untracked_required_files": untracked_required,
        "network_checked": False,
    }


def _git_identity(repo_root: Path) -> dict:
    return {
        **_git_reference_identity(repo_root),
        "working_tree": _working_tree_identity(repo_root),
    }


def _identity_complete(
    git: dict,
    git_identity_stable: bool,
    final_working_tree: dict,
    filesystem_identity_stable: bool,
    database_schema: dict,
    research_runtime: dict,
    research_runtime_stable: bool,
    file_groups: tuple[dict, ...],
) -> bool:
    return (
        git["sha"] is not None
        and git["tree"] is not None
        and git["dirty"] is not None
        and git_identity_stable
        and git["working_tree"]["sha256"] is not None
        and not git["working_tree"]["missing_paths"]
        and final_working_tree == git["working_tree"]
        and filesystem_identity_stable
        and research_runtime["sha256"] is not None
        and research_runtime_stable
        and all(group["sha256"] is not None for group in file_groups)
        and database_schema["status"] == "ok"
    )


def _git_incomplete_reasons(
    git: dict,
    git_identity_stable: bool,
    final_working_tree: dict,
    filesystem_identity_stable: bool,
) -> list[str]:
    reasons: list[str] = []
    if git["sha"] is None or git["tree"] is None or git["dirty"] is None:
        reasons.append("git-identity-incomplete")
    elif not git_identity_stable:
        reasons.append("git-identity-changed-during-scan")
    if git["working_tree"]["sha256"] is None:
        reasons.append("working-tree-identity-incomplete")
    elif git["working_tree"]["missing_paths"]:
        reasons.append("working-tree-paths-missing")
    if final_working_tree != git["working_tree"] or not filesystem_identity_stable:
        reasons.append("working-tree-changed-during-scan")
    if git["dirty"]:
        reasons.append("dirty-working-tree")
    if not git["required_files_tracked"]:
        reasons.append("required-files-untracked")
    return reasons


def _incomplete_reasons(
    git: dict,
    git_identity_stable: bool,
    final_working_tree: dict,
    filesystem_identity_stable: bool,
    database_schema: dict,
    research_runtime: dict,
    research_runtime_stable: bool,
    named_file_groups: tuple[tuple[str, dict], ...],
) -> list[str]:
    reasons = _git_incomplete_reasons(
        git, git_identity_stable, final_working_tree, filesystem_identity_stable
    )
    if research_runtime["sha256"] is None:
        reasons.append("research-runtime-incomplete")
    elif not research_runtime_stable:
        reasons.append("research-runtime-changed-during-scan")
    reasons.extend(
        f"{name}-incomplete" for name, group in named_file_groups if group["sha256"] is None
    )
    if database_schema["status"] != "ok":
        reasons.append(database_schema["reason"])
    return reasons


def _resolved_database(repo_root: Path, database: Path | None) -> Path:
    database = database or Path("store/market.duckdb")
    requested = database if database.is_absolute() else repo_root / database
    return Path(os.path.abspath(requested))


def _file_groups(repo_root: Path) -> dict[str, dict]:
    return {
        "audit_sources": _file_set(repo_root, AUDIT_SOURCE_FILES),
        "dependencies": _file_set(repo_root, DEPENDENCY_FILES),
        "strategy_registrations": _file_set(repo_root, STRATEGY_REGISTRATION_FILES),
        "execution_profiles": _file_set(repo_root, EXECUTION_PROFILE_FILES),
        "experiment_registrations": _file_set(repo_root, EXPERIMENT_REGISTRATION_FILES),
        "prospective_evidence": _file_set(repo_root, PROSPECTIVE_EVIDENCE_FILES),
        "recovery_sources": _file_set(repo_root, RECOVERY_SOURCE_FILES),
        "schema_sources": _file_set(repo_root, SCHEMA_SOURCE_FILES),
        "service_units": _file_set(repo_root, SERVICE_FILES),
        "schedule_sources": _file_set(repo_root, SCHEDULE_SOURCE_FILES),
    }


def _named_file_groups(groups: dict[str, dict]) -> tuple[tuple[str, dict], ...]:
    return (
        ("audit-sources", groups["audit_sources"]),
        ("dependencies", groups["dependencies"]),
        ("strategy-registrations", groups["strategy_registrations"]),
        ("execution-profiles", groups["execution_profiles"]),
        ("experiment-registrations", groups["experiment_registrations"]),
        ("prospective-evidence", groups["prospective_evidence"]),
        ("recovery-sources", groups["recovery_sources"]),
        ("schema-sources", groups["schema_sources"]),
        ("services", groups["service_units"]),
        ("schedules", groups["schedule_sources"]),
    )


def _manifest_body(
    *,
    git: dict,
    groups: dict[str, dict],
    research_runtime: dict,
    database_schema: dict,
    identity_complete: bool,
    reasons: list[str],
) -> dict:
    release_eligible = identity_complete and not reasons
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "release-candidate" if release_eligible else "non-releasable",
        "release_eligible": release_eligible,
        "identity_complete": identity_complete,
        "reasons": reasons,
        "git": git,
        "audit_sources": groups["audit_sources"],
        "research_runtime": research_runtime,
        "dependencies": groups["dependencies"],
        "experiment_registrations": groups["experiment_registrations"],
        "prospective_evidence": groups["prospective_evidence"],
        "recovery_sources": groups["recovery_sources"],
        "strategy_registrations": groups["strategy_registrations"],
        "execution_profiles": groups["execution_profiles"],
        "schema_sources": groups["schema_sources"],
        "database_schema": database_schema,
        "service_units": groups["service_units"],
        "schedule_sources": groups["schedule_sources"],
    }


def build_manifest(
    repo_root: Path = REPO_ROOT,
    database: Path | None = None,
    *,
    _database_read_path: Path | None = None,
) -> dict:
    """Build a deterministic manifest without changing repository or host state."""
    repo_root = repo_root.resolve()
    requested_database = _resolved_database(repo_root, database)
    public_database_identity = (
        None
        if _database_read_path is not None
        else _database_filesystem_identity(requested_database)
    )
    initial_filesystem_identity = _working_tree_filesystem_identity(repo_root)
    git = _git_identity(repo_root)
    groups = _file_groups(repo_root)
    database_schema = _database_schema(
        repo_root,
        _database_read_path or requested_database,
        location_database=requested_database,
        trusted_read_path=_database_read_path is not None,
        expected_identity=public_database_identity,
    )
    research_runtime = research_runtime_identity(repo_root)
    final_working_tree = _working_tree_identity(repo_root)
    final_filesystem_identity = _working_tree_filesystem_identity(repo_root)
    research_runtime_stable = research_runtime_identity(repo_root) == research_runtime
    initial_git_reference = {
        key: value for key, value in git.items() if key != "working_tree"
    }
    git_identity_stable = _git_reference_identity(repo_root) == initial_git_reference
    final_public_database_identity = (
        None
        if _database_read_path is not None
        else _database_filesystem_identity(requested_database)
    )
    if _database_read_path is None and (
        (
            public_database_identity is None
            and database_schema["status"] == "ok"
        )
        or (
            public_database_identity is not None
            and final_public_database_identity != public_database_identity
        )
    ):
        database_schema = _database_schema_failure(
            "unsafe",
            "database-schema-path-unsafe",
            _database_location(repo_root, requested_database),
        )
    filesystem_identity_stable = (
        initial_filesystem_identity is not None
        and final_filesystem_identity == initial_filesystem_identity
    )
    named_file_groups = _named_file_groups(groups)
    reasons = _incomplete_reasons(
        git,
        git_identity_stable,
        final_working_tree,
        filesystem_identity_stable,
        database_schema,
        research_runtime,
        research_runtime_stable,
        named_file_groups,
    )
    identity_complete = _identity_complete(
        git,
        git_identity_stable,
        final_working_tree,
        filesystem_identity_stable,
        database_schema,
        research_runtime,
        research_runtime_stable,
        tuple(group for _name, group in named_file_groups),
    )
    body = _manifest_body(
        git=git,
        groups=groups,
        research_runtime=research_runtime,
        database_schema=database_schema,
        identity_complete=identity_complete,
        reasons=reasons,
    )
    return {**body, "manifest_sha256": canonical_sha256(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="repository to inspect (default: this checkout)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="DuckDB file whose schema is identified (default: <repo-root>/store/market.duckdb)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="return success for a complete diagnostic snapshot; status remains non-releasable",
    )
    args = parser.parse_args(argv)

    manifest = build_manifest(args.repo_root, args.database)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest["release_eligible"]:
        return 0
    if args.allow_dirty and manifest["identity_complete"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
