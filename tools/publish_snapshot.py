#!/usr/bin/env python3
"""Publish an immutable, consistent read-only copy of the engine database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.snapshots import LATEST_NAME, snapshot_directory
from tools import backup_database

KEEP_SNAPSHOTS = 2


class SnapshotError(RuntimeError):
    """The snapshot could not be published without disturbing the prior one."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _data_commit(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-list", "-1", "HEAD", "--", "data/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def _unique_destination(directory: Path, now: datetime) -> Path:
    stem = now.astimezone(timezone.utc).strftime("market-%Y%m%dT%H%M%S%fZ")
    destination = directory / f"{stem}.duckdb"
    suffix = 1
    while os.path.lexists(destination) or os.path.lexists(destination.with_suffix(".json")):
        destination = directory / f"{stem}-{suffix}.duckdb"
        suffix += 1
    return destination


def _write_manifest(path: Path, manifest: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _swap_latest(directory: Path, destination: Path) -> None:
    temporary = directory / f".{LATEST_NAME}.{secrets.token_hex(8)}.tmp"
    try:
        os.symlink(destination.name, temporary)
        os.replace(temporary, directory / LATEST_NAME)
        _sync_directory(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _retain_newest(directory: Path) -> None:
    snapshots = sorted(
        path for path in directory.glob("market-*.duckdb")
        if path.name != LATEST_NAME and not path.is_symlink()
    )
    for old in snapshots[:-KEEP_SNAPSHOTS]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)
    _sync_directory(directory)


def publish_snapshot(
    repo_root: Path,
    source: Path,
    *,
    now: datetime | None = None,
    held_locks: frozenset[str] = frozenset(),
) -> dict:
    """Copy, fsync, atomically publish, and retain two database snapshots."""
    repo_root = repo_root.resolve()
    source = source.resolve(strict=True)
    directory = snapshot_directory(source)
    directory.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(directory, now or datetime.now(timezone.utc))
    temporary = directory / f".{destination.name}.{secrets.token_hex(8)}.tmp"
    manifest_path = destination.with_suffix(".json")
    published = False
    try:
        with backup_database._exclusive_backup_window(repo_root, skip_locks=held_locks):
            snapshot = backup_database._copy_database(source, temporary)
            os.chmod(temporary, 0o600)
            _sync_file(temporary)
            as_of = datetime.now(timezone.utc)
            manifest = {
                "schema_version": 1,
                "snapshot": destination.name,
                "source_database": str(source.relative_to(repo_root)),
                "source_data_commit": _data_commit(repo_root),
                "as_of": as_of.isoformat(),
                "size_bytes": temporary.stat().st_size,
                "sha256": _sha256(temporary),
                "row_counts": snapshot["row_counts"],
            }
            os.replace(temporary, destination)
            _write_manifest(manifest_path, manifest)
            _sync_directory(directory)
            _swap_latest(directory, destination)
            published = True
            _retain_newest(directory)
            return manifest
    except (OSError, ValueError, backup_database.BackupError) as exc:
        raise SnapshotError(str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)
        if not published:
            destination.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--held-lock",
        action="append",
        default=[],
        choices=backup_database.LOCK_FILES,
        help="producer lock already inherited by this process",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    source = args.source if args.source.is_absolute() else repo_root / args.source
    try:
        result = publish_snapshot(
            repo_root, source, held_locks=frozenset(args.held_lock)
        )
    except SnapshotError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "published", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
