"""Discovery, verification, and lifetime pins for immutable generations."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

from engine import migrations as schema_registry
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB

LATEST_NAME = "market-latest.duckdb"
SNAPSHOT_PATTERN = re.compile(r"market-\d{8}T\d{12}Z(?:-\d+)?\.duckdb")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
GENERATION_MANIFEST_SCHEMA_VERSION = 2
MINIMUM_DATABASE_SCHEMA_ID = schema_registry.MINIMUM_SCHEMA_ID
CURRENT_DATABASE_SCHEMA_ID = schema_registry.CURRENT_SCHEMA_ID
_VERIFIED_CACHE_LIMIT = 16
_verified_generations: dict[tuple, dict[Path, tuple[int, ...]]] = {}


class GenerationError(RuntimeError):
    """A published generation is absent, incompatible, or corrupt."""


@dataclass(frozen=True)
class SnapshotInfo:
    path: Path
    manifest_path: Path
    as_of: datetime
    sha256: str
    row_counts: dict[str, int]
    source_data_commit: str | None
    size_bytes: int | None = None
    manifest_schema_version: int = 1
    database_schema_id: int | None = None
    catalog_sha256: str | None = None
    generation_id: str | None = None
    parts: tuple[dict, ...] = ()
    cold_tables: dict[str, dict] = field(default_factory=dict)
    cohort: dict[str, dict[str, dict]] = field(default_factory=dict)
    source_snapshot: dict | None = None
    manifest_sha256: str | None = None
    _lifetime_pin: object | None = field(default=None, compare=False, repr=False)


class SnapshotPin:
    """A process-held shared lock protecting one complete generation lifetime."""

    def __init__(self, info: SnapshotInfo, handle: BinaryIO):
        self.info = info
        self._handle = handle

    def close(self) -> None:
        if not self._handle.closed:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()

    def __enter__(self) -> SnapshotInfo:
        return self.info

    def __exit__(self, *_exc: object) -> None:
        self.close()


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


def _safe_relative(value: object) -> Path | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recorded_file(
    directory: Path, record: object, *, expected_path: Path | None = None,
) -> tuple[Path, int, str] | None:
    if not isinstance(record, dict) or set(record) != {"path", "size_bytes", "sha256"}:
        return None
    relative = _safe_relative(record.get("path"))
    size = record.get("size_bytes")
    digest = record.get("sha256")
    if (
        relative is None
        or (expected_path is not None and relative != expected_path)
        or type(size) is not int
        or size < 0
        or not isinstance(digest, str)
        or SHA256_PATTERN.fullmatch(digest) is None
    ):
        return None
    path = directory / relative
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            return None
    except OSError:
        return None
    return path, size, digest


def _generation_info(
    directory: Path, snapshot: Path, manifest_path: Path, manifest: dict,
) -> SnapshotInfo | None:
    body = dict(manifest)
    manifest_hash = body.pop("manifest_sha256", None)
    if (
        not isinstance(manifest_hash, str)
        or SHA256_PATTERN.fullmatch(manifest_hash) is None
        or canonical_sha256(body) != manifest_hash
    ):
        return None
    expected_fields = {
        "manifest_schema_version", "generation_id", "snapshot", "source_database",
        "source_data_commit", "as_of", "database_schema_id", "catalog_sha256",
        "hot_database", "row_counts", "source_snapshot", "parts", "cold_tables",
        "cohort", "metrics",
    }
    if set(body) != expected_fields or body.get("manifest_schema_version") != 2:
        return None
    generation_id = body.get("generation_id")
    if not isinstance(generation_id, str) or generation_id != snapshot.stem:
        return None
    hot = _recorded_file(directory, body.get("hot_database"), expected_path=Path(snapshot.name))
    as_of = _utc_timestamp(body.get("as_of"))
    schema_id = body.get("database_schema_id")
    catalog_hash = body.get("catalog_sha256")
    source_commit = body.get("source_data_commit")
    row_counts = body.get("row_counts")
    if (
        hot is None
        or body.get("snapshot") != snapshot.name
        or as_of is None
        or type(schema_id) is not int
        or schema_id < 0
        or not isinstance(catalog_hash, str)
        or SHA256_PATTERN.fullmatch(catalog_hash) is None
        or (
            source_commit is not None
            and (not isinstance(source_commit, str) or GIT_SHA_PATTERN.fullmatch(source_commit) is None)
        )
        or not isinstance(row_counts, dict)
        or any(
            not isinstance(name, str) or type(count) is not int or count < 0
            for name, count in row_counts.items()
        )
        or not isinstance(body.get("source_snapshot"), dict)
        or not isinstance(body.get("parts"), list)
        or not isinstance(body.get("cold_tables"), dict)
        or not isinstance(body.get("cohort"), dict)
        or not isinstance(body.get("metrics"), dict)
    ):
        return None
    if not (
        MINIMUM_DATABASE_SCHEMA_ID
        <= schema_id
        <= CURRENT_DATABASE_SCHEMA_ID
    ):
        return None
    expected_catalog = getattr(
        schema_registry.migrations()[schema_id].module, "EXPECTED_CATALOG_SHA256", None,
    )
    if expected_catalog is not None and catalog_hash != expected_catalog:
        return None
    parts: list[dict] = []
    for record in body["parts"]:
        if not isinstance(record, dict):
            return None
        file_record = {key: record.get(key) for key in ("path", "size_bytes", "sha256")}
        if _recorded_file(directory, file_record) is None:
            return None
        required = {
            "table", "partition", "path", "size_bytes", "sha256", "row_count",
            "source_bytes", "availability_column", "availability_min",
            "availability_max", "key_min", "key_max", "fingerprint_sha256",
        }
        if (
            set(record) != required
            or not isinstance(record.get("table"), str)
            or not isinstance(record.get("partition"), str)
            or not isinstance(record.get("availability_column"), str)
            or type(record.get("row_count")) is not int
            or record["row_count"] < 0
            or type(record.get("source_bytes")) is not int
            or record["source_bytes"] < 0
            or not isinstance(record.get("fingerprint_sha256"), str)
            or SHA256_PATTERN.fullmatch(record["fingerprint_sha256"]) is None
            or not isinstance(record.get("key_min"), list)
            or not isinstance(record.get("key_max"), list)
        ):
            return None
        parts.append(record)
    cold_tables = body["cold_tables"]
    for qualified_name, spec in cold_tables.items():
        if (
            not isinstance(qualified_name, str)
            or not isinstance(spec, dict)
            or set(spec) != {
                "schema", "table", "availability_column", "key_columns",
                "create_sql", "columns", "indexes",
            }
            or qualified_name != f"{spec.get('schema')}.{spec.get('table')}"
            or not isinstance(spec.get("availability_column"), str)
            or not isinstance(spec.get("key_columns"), list)
            or not spec["key_columns"]
            or any(not isinstance(value, str) or not value for value in spec["key_columns"])
            or not isinstance(spec.get("create_sql"), str)
            or not isinstance(spec.get("columns"), list)
            or not isinstance(spec.get("indexes"), list)
        ):
            return None
    if (
        {record["table"] for record in parts} - set(cold_tables)
        or any(
            sum(record["row_count"] for record in parts if record["table"] == table)
            != row_counts.get(table)
            for table in cold_tables
        )
        or body["source_snapshot"].get("row_counts") != row_counts
    ):
        return None
    metrics = body["metrics"]
    if (
        set(metrics) != {
            "wall_seconds", "writer_lock_seconds", "hot_size_bytes",
            "cold_part_bytes", "new_cold_part_bytes",
            "cold_bytes_read", "cold_bytes_serialized", "cold_copy_operations",
        }
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
            for value in metrics.values()
        )
    ):
        return None
    cohort: dict[str, dict[str, dict]] = {}
    for section, records in body["cohort"].items():
        if section not in {"prospective_evidence", "operational_artifacts", "operational_controls"}:
            return None
        if not isinstance(records, dict):
            return None
        cohort[section] = {}
        for logical_path, record in records.items():
            if not isinstance(logical_path, str) or _recorded_file(directory, record) is None:
                return None
            cohort[section][logical_path] = record
    return SnapshotInfo(
        path=hot[0], manifest_path=manifest_path, as_of=as_of, sha256=hot[2],
        row_counts=row_counts, source_data_commit=source_commit, size_bytes=hot[1],
        manifest_schema_version=2, database_schema_id=schema_id,
        catalog_sha256=catalog_hash, generation_id=generation_id, parts=tuple(parts),
        cold_tables=body["cold_tables"], cohort=cohort,
        source_snapshot=body["source_snapshot"],
        manifest_sha256=manifest_hash,
    )


def _legacy_info(snapshot: Path, manifest_path: Path, manifest: dict) -> SnapshotInfo | None:
    as_of = _utc_timestamp(manifest.get("as_of"))
    sha256 = manifest.get("sha256")
    source_commit = manifest.get("source_data_commit")
    row_counts = manifest.get("row_counts")
    if (
        manifest.get("schema_version") != 1
        or as_of is None
        or manifest.get("snapshot") != snapshot.name
        or not isinstance(sha256, str)
        or SHA256_PATTERN.fullmatch(sha256) is None
        or (
            source_commit is not None
            and (not isinstance(source_commit, str) or GIT_SHA_PATTERN.fullmatch(source_commit) is None)
        )
        or not isinstance(row_counts, dict)
        or any(
            not isinstance(name, str) or type(count) is not int or count < 0
            for name, count in row_counts.items()
        )
    ):
        return None
    return SnapshotInfo(
        path=snapshot, manifest_path=manifest_path, as_of=as_of, sha256=sha256,
        row_counts=row_counts, source_data_commit=source_commit,
        size_bytes=manifest.get("size_bytes"),
    )


def _latest_info(database: Path) -> SnapshotInfo | None:
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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("manifest_schema_version") == GENERATION_MANIFEST_SCHEMA_VERSION:
        return _generation_info(directory, snapshot, manifest_path, manifest)
    return _legacy_info(snapshot, manifest_path, manifest)


def latest_snapshot(
    database: Path = DEFAULT_DB, *, newer_than_database: bool = False,
) -> SnapshotInfo | None:
    """Resolve the current immutable generation without opening the primary."""
    database = Path(database).absolute()
    info = _latest_info(database)
    if info is None:
        return None
    if newer_than_database:
        try:
            last_write = datetime.fromtimestamp(database.stat().st_mtime_ns / 1e9, timezone.utc)
        except OSError:
            return None
        if info.as_of <= last_write:
            return None
    if info.manifest_schema_version == GENERATION_MANIFEST_SCHEMA_VERSION:
        try:
            pin = pin_latest_generation(
                database, newer_than_database=newer_than_database,
            )
        except GenerationError:
            return None
        return replace(pin.info, _lifetime_pin=pin)
    return info


def _file_identity(path: Path) -> tuple[int, ...]:
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _all_generation_files(info: SnapshotInfo) -> list[tuple[Path, int, str]]:
    directory = info.manifest_path.parent
    files = [(info.path, int(info.size_bytes or -1), info.sha256)]
    for record in info.parts:
        files.append((directory / record["path"], record["size_bytes"], record["sha256"]))
    for records in info.cohort.values():
        for record in records.values():
            files.append((directory / record["path"], record["size_bytes"], record["sha256"]))
    return files


def _verify_files(info: SnapshotInfo) -> None:
    manifest_stat = _file_identity(info.manifest_path)
    key = (
        info.manifest_path, *manifest_stat, info.manifest_sha256 or "legacy",
    )
    cached = _verified_generations.get(key)
    if cached is not None:
        try:
            if all(_file_identity(path) == identity for path, identity in cached.items()):
                return
        except OSError:
            pass
        raise GenerationError("verified generation files changed")
    identities: dict[Path, tuple[int, ...]] = {}
    for path, size, expected_hash in _all_generation_files(info):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
                raise GenerationError(f"generation file is missing or has the wrong length: {path.name}")
            if _hash_file(path) != expected_hash:
                raise GenerationError(f"generation file hash does not match: {path.name}")
            identities[path] = _file_identity(path)
        except OSError as exc:
            raise GenerationError(f"generation file is unreadable: {path.name}") from exc
    if len(_verified_generations) >= _VERIFIED_CACHE_LIMIT:
        _verified_generations.pop(next(iter(_verified_generations)))
    _verified_generations[key] = identities


def pin_latest_generation(
    database: Path = DEFAULT_DB,
    *,
    newer_than_database: bool = False,
    max_age: timedelta | None = None,
) -> SnapshotPin:
    """Resolve once, acquire a process-held pin, and verify every referenced byte."""
    database = Path(database).absolute()
    for _attempt in range(2):
        info = _latest_info(database)
        if info is None:
            raise GenerationError("no valid published generation")
        if info.manifest_schema_version != GENERATION_MANIFEST_SCHEMA_VERSION:
            raise GenerationError("latest snapshot is not a revision-16 generation")
        if max_age is not None and (
            max_age.total_seconds() < 0
            or info.as_of < datetime.now(timezone.utc) - max_age
        ):
            raise GenerationError("published generation exceeds its freshness budget")
        if newer_than_database:
            try:
                last_write = datetime.fromtimestamp(
                    database.stat().st_mtime_ns / 1e9, timezone.utc,
                )
            except OSError as exc:
                raise GenerationError("primary freshness marker is unavailable") from exc
            if info.as_of <= last_write:
                raise GenerationError("published generation is stale for evidence reads")
        pins = info.manifest_path.parent / "pins"
        pins.mkdir(mode=0o700, exist_ok=True)
        pin_path = pins / f"{info.generation_id}.lock"
        handle = pin_path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            if not info.manifest_path.exists():
                handle.close()
                continue
            _verify_files(info)
            return SnapshotPin(info, handle)
        except BaseException:
            handle.close()
            raise
    raise GenerationError("published generation changed during pin acquisition")
