"""Discovery and freshness checks for immutable read-only database snapshots."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.lib.settings import DEFAULT_DB

LATEST_NAME = "market-latest.duckdb"
SNAPSHOT_PATTERN = re.compile(r"market-\d{8}T\d{12}Z(?:-\d+)?\.duckdb")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class SnapshotInfo:
    path: Path
    manifest_path: Path
    as_of: datetime
    sha256: str
    row_counts: dict[str, int]
    source_data_commit: str | None


def snapshot_directory(database: Path = DEFAULT_DB) -> Path:
    return Path(database).absolute().parent / "snapshots"


def _utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def latest_snapshot(
    database: Path = DEFAULT_DB, *, newer_than_database: bool = False,
) -> SnapshotInfo | None:
    """Return a valid latest snapshot, optionally only when newer than the store.

    The immutable file named by the symlink selects its same-stem manifest. The
    link is read once, so a concurrent publisher cannot mix database and
    manifest generations.
    """
    database = Path(database).absolute()
    directory = snapshot_directory(database)
    latest = directory / LATEST_NAME
    try:
        target = os.readlink(latest)
    except OSError:
        return None
    target_path = Path(target)
    if target_path.is_absolute() or len(target_path.parts) != 1:
        return None
    if SNAPSHOT_PATTERN.fullmatch(target_path.name) is None:
        return None
    snapshot = directory / target_path.name
    manifest_path = snapshot.with_suffix(".json")
    try:
        if snapshot.is_symlink() or not snapshot.is_file() or manifest_path.is_symlink():
            return None
        with manifest_path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return None
    as_of = _utc_timestamp(manifest.get("as_of"))
    sha256 = manifest.get("sha256")
    source_commit = manifest.get("source_data_commit")
    row_counts = manifest.get("row_counts")
    if (
        as_of is None
        or manifest.get("snapshot") != snapshot.name
        or not isinstance(sha256, str)
        or SHA256_PATTERN.fullmatch(sha256) is None
        or (
            source_commit is not None
            and (
                not isinstance(source_commit, str)
                or GIT_SHA_PATTERN.fullmatch(source_commit) is None
            )
        )
        or not isinstance(row_counts, dict)
        or any(
            not isinstance(name, str) or type(count) is not int or count < 0
            for name, count in row_counts.items()
        )
    ):
        return None
    if newer_than_database:
        try:
            last_write = datetime.fromtimestamp(database.stat().st_mtime_ns / 1e9, timezone.utc)
        except OSError:
            return None
        if as_of <= last_write:
            return None
    return SnapshotInfo(
        path=snapshot,
        manifest_path=manifest_path,
        as_of=as_of,
        sha256=sha256,
        row_counts=row_counts,
        source_data_commit=source_commit,
    )
