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
# Retention keeps the snapshot market-latest names plus this many verified older ones.
KEEP_PREVIOUS_SNAPSHOTS = 1
SNAPSHOT_PATTERN = re.compile(r"market-(\d{8}T\d{12}Z)(?:-(\d+))?\.duckdb")
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


def _read_manifest(snapshot: Path) -> dict | None:
    """Return the same-stem manifest of a regular snapshot file, if well formed."""
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
    return manifest


def _snapshot_info(snapshot: Path) -> SnapshotInfo | None:
    manifest = _read_manifest(snapshot)
    if manifest is None:
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
    return SnapshotInfo(
        path=snapshot,
        manifest_path=snapshot.with_suffix(".json"),
        as_of=as_of,
        sha256=sha256,
        row_counts=row_counts,
        source_data_commit=source_commit,
    )


def _latest_target(directory: Path) -> Path | None:
    """Resolve market-latest to its same-directory snapshot file name, read once."""
    try:
        target = os.readlink(directory / LATEST_NAME)
    except OSError:
        return None
    target_path = Path(target)
    if target_path.is_absolute() or len(target_path.parts) != 1:
        return None
    if SNAPSHOT_PATTERN.fullmatch(target_path.name) is None:
        return None
    return directory / target_path.name


def latest_snapshot(
    database: Path = DEFAULT_DB, *, newer_than_database: bool = False,
) -> SnapshotInfo | None:
    """Return a valid latest snapshot, optionally only when newer than the store.

    The immutable file named by the symlink selects its same-stem manifest. The
    link is read once, so a concurrent publisher cannot mix database and
    manifest generations.
    """
    database = Path(database).absolute()
    snapshot = _latest_target(snapshot_directory(database))
    if snapshot is None:
        return None
    info = _snapshot_info(snapshot)
    if info is None:
        return None
    if newer_than_database:
        try:
            last_write = datetime.fromtimestamp(database.stat().st_mtime_ns / 1e9, timezone.utc)
        except OSError:
            return None
        if info.as_of <= last_write:
            return None
    return info


@dataclass(frozen=True)
class RetentionPlan:
    """Which snapshot files retention keeps and deletes, decided without opening them."""
    latest: Path | None
    keep: tuple[Path, ...]
    delete: tuple[Path, ...]
    unverified: tuple[Path, ...]


def _publication_order(path: Path) -> tuple[str, int]:
    match = SNAPSHOT_PATTERN.fullmatch(path.name)
    if match is None:
        raise ValueError(f"not a published snapshot name: {path.name}")
    return match.group(1), int(match.group(2) or 0)


def _verified(snapshot: Path) -> bool:
    """A manifest that validates and records the file's current size.

    Re-hashing every retained copy on each publication would read tens of GiB,
    so the recorded sha256 is checked by readers that need it, not here.
    """
    manifest = _read_manifest(snapshot)
    if manifest is None or _snapshot_info(snapshot) is None:
        return False
    size = manifest.get("size_bytes")
    try:
        return type(size) is int and snapshot.stat().st_size == size
    except OSError:
        return False


def retention_plan(
    directory: Path, keep_previous: int = KEEP_PREVIOUS_SNAPSHOTS,
) -> RetentionPlan:
    """Plan to keep the latest snapshot plus ``keep_previous`` verified older ones.

    The file market-latest names is never deleted, verified or not. Without a
    valid market-latest nothing is deleted. Unverified files newer than latest
    may be a publication in flight and are kept; older unverified files, and
    verified ones beyond ``keep_previous``, are deleted.
    """
    if keep_previous < 0:
        raise ValueError("keep_previous must be non-negative")
    directory = Path(directory)
    try:
        candidates = sorted(
            (
                path for path in directory.iterdir()
                if SNAPSHOT_PATTERN.fullmatch(path.name) is not None
                and not path.is_symlink()
                and path.is_file()
            ),
            key=_publication_order,
        )
    except FileNotFoundError:
        candidates = []
    unverified = tuple(path for path in candidates if not _verified(path))
    latest = _latest_target(directory)
    if latest is None or latest not in candidates:
        return RetentionPlan(None, tuple(candidates), (), unverified)
    latest_order = _publication_order(latest)
    newer = [path for path in candidates if _publication_order(path) > latest_order]
    older = [path for path in candidates if _publication_order(path) < latest_order]
    previous = [path for path in older if path not in unverified]
    kept_previous = previous[len(previous) - keep_previous:] if keep_previous else []
    keep = tuple(sorted({latest, *kept_previous, *newer}, key=_publication_order))
    delete = tuple(path for path in older if path not in kept_previous)
    return RetentionPlan(latest, keep, delete, unverified)
