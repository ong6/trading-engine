"""Discovery, verification, and lifetime pins for immutable generations."""
from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import BinaryIO

import duckdb

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB

LATEST_NAME = "market-latest.duckdb"
# Retention keeps the generation market-latest names plus this many verified older ones.
KEEP_PREVIOUS_SNAPSHOTS = 1
SNAPSHOT_PATTERN = re.compile(r"market-(\d{8}T\d{12}Z)(?:-(\d+))?\.duckdb")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
GENERATION_MANIFEST_SCHEMA_VERSION = 2
MIGRATION_TABLE = "schema_migrations"
MIGRATION_MODULES = (
    "engine.migrations.0000_post_r15_baseline",
    "engine.migrations.0001_generation_storage",
)
MINIMUM_SCHEMA_ID = 0
CURRENT_SCHEMA_ID = len(MIGRATION_MODULES) - 1
MINIMUM_DATABASE_SCHEMA_ID = MINIMUM_SCHEMA_ID
CURRENT_DATABASE_SCHEMA_ID = CURRENT_SCHEMA_ID
COLD_TABLE_LAYOUTS = {
    "main.intraday_prices": ("as_of", ("ticker", "ts", "interval")),
    "main.bitemporal_facts": ("ingested_at", ("id",)),
    "main.source_response_receipts": ("received_at", ("id",)),
}
COLD_APPEND_FRONTIERS = {
    "main.bitemporal_facts": "id",
    "main.source_response_receipts": "id",
}
_VERIFIED_CACHE_LIMIT = 16
_verified_generations: dict[tuple, dict[Path, tuple[int, ...]]] = {}


class GenerationError(RuntimeError):
    """A published generation is absent, incompatible, or corrupt."""


class SchemaIdentityError(RuntimeError):
    """The database schema identity is missing, malformed, or incompatible."""


@dataclass(frozen=True)
class Migration:
    migration_id: int
    description: str
    sha256: str
    statements: tuple[str, ...]
    module: ModuleType


def _module_migration(name: str) -> Migration:
    module = importlib.import_module(name)
    module_path = Path(module.__file__ or "")
    migration_id = getattr(module, "MIGRATION_ID", None)
    description = getattr(module, "DESCRIPTION", None)
    statements = getattr(module, "STATEMENTS", None)
    if (
        type(migration_id) is not int
        or not isinstance(description, str)
        or not description
        or not isinstance(statements, tuple)
        or any(not isinstance(statement, str) or not statement.strip() for statement in statements)
    ):
        raise SchemaIdentityError(f"invalid migration module: {name}")
    dependencies = getattr(module, "DEPENDENCIES", ())
    if not isinstance(dependencies, tuple) or any(
        not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts
        for relative in dependencies
    ):
        raise SchemaIdentityError(f"invalid migration dependency list: {name}")
    root = module_path.resolve().parents[2]
    digest = hashlib.sha256()
    for path in (module_path, *(root / relative for relative in dependencies)):
        try:
            relative = path.resolve(strict=True).relative_to(root).as_posix()
            content = path.read_bytes()
        except (OSError, ValueError) as exc:
            raise SchemaIdentityError(f"migration dependency is unavailable: {path}") from exc
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative.encode())
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return Migration(
        migration_id=migration_id, description=description,
        sha256=digest.hexdigest(), statements=statements, module=module,
    )


def migrations() -> tuple[Migration, ...]:
    loaded = tuple(_module_migration(name) for name in MIGRATION_MODULES)
    if tuple(item.migration_id for item in loaded) != tuple(range(len(loaded))):
        raise SchemaIdentityError("migration IDs must be contiguous from zero")
    return loaded


def database_name(con: duckdb.DuckDBPyConnection) -> str:
    return str(con.execute("SELECT current_database()").fetchone()[0])


def catalog(con: duckdb.DuckDBPyConnection) -> dict:
    """Stable schema identity; sequence position is deliberately separate."""
    database = database_name(con)
    return {
        "tables": con.execute(
            "SELECT schema_name, table_name, sql FROM duckdb_tables() "
            "WHERE database_name=? AND NOT internal AND NOT temporary "
            "AND table_name<>? ORDER BY schema_name, table_name",
            [database, MIGRATION_TABLE],
        ).fetchall(),
        "views": con.execute(
            "SELECT schema_name, view_name, sql FROM duckdb_views() "
            "WHERE database_name=? AND NOT internal AND NOT temporary "
            "ORDER BY schema_name, view_name", [database],
        ).fetchall(),
        "indexes": con.execute(
            "SELECT schema_name, index_name, table_name, is_unique, is_primary, sql "
            "FROM duckdb_indexes() WHERE database_name=? AND table_name<>? "
            "ORDER BY schema_name, index_name", [database, MIGRATION_TABLE],
        ).fetchall(),
        "sequences": con.execute(
            "SELECT schema_name, sequence_name, min_value, max_value, increment_by, cycle "
            "FROM duckdb_sequences() WHERE database_name=? AND NOT temporary "
            "ORDER BY schema_name, sequence_name", [database],
        ).fetchall(),
    }


def catalog_sha256(con: duckdb.DuckDBPyConnection) -> str:
    return canonical_sha256(catalog(con))


def sequence_state(
    con: duckdb.DuckDBPyConnection, database: str | None = None,
) -> list[dict]:
    """Return runtime sequence positions without folding them into schema identity."""
    database = database_name(con) if database is None else database
    rows = con.execute(
        "SELECT schema_name, sequence_name, min_value, max_value, increment_by, cycle, sql "
        "FROM duckdb_sequences() WHERE database_name=? AND NOT temporary "
        "ORDER BY schema_name, sequence_name", [database],
    ).fetchall()
    state = []
    for schema, name, minimum, maximum, increment, cycle, sql in rows:
        match = re.search(r"\bSTART\s+(-?\d+)\b", sql)
        if match is None:
            raise SchemaIdentityError(f"sequence next value is unavailable: {schema}.{name}")
        state.append({
            "schema": schema, "name": name, "min_value": minimum,
            "max_value": maximum, "increment_by": increment, "cycle": cycle,
            "next_value": int(match.group(1)),
        })
    return state


def sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def logical_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return [type(value).__name__, value]
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, (date, datetime)):
        return [type(value).__name__, value.isoformat()]
    return [type(value).__name__, str(value)]


def query_fingerprint(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    *,
    key_columns: tuple[str, ...] = (),
) -> tuple[str, int, int, list | None, list | None]:
    cursor = connection.execute(query)
    digest = hashlib.sha256()
    row_count = 0
    bytes_read = 0
    key_indexes = [
        index for index, description in enumerate(cursor.description)
        if description[0] in key_columns
    ]
    key_min = key_max = None
    while rows := cursor.fetchmany(10_000):
        for row in rows:
            encoded = json.dumps(
                [logical_value(value) for value in row],
                separators=(",", ":"), sort_keys=False,
            ).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            bytes_read += len(encoded)
            key = [logical_value(row[index]) for index in key_indexes]
            key_min = key if key_min is None else key_min
            key_max = key
            row_count += 1
    return digest.hexdigest(), row_count, bytes_read, key_min, key_max


def table_logical_sha256(
    connection: duckdb.DuckDBPyConnection,
    database: str,
    schema: str,
    table: str,
) -> str:
    qualified_name = f"{schema}.{table}"
    qualified = ".".join(sql_identifier(name) for name in (database, schema, table))
    layout = COLD_TABLE_LAYOUTS.get(qualified_name)
    if layout is None:
        return query_fingerprint(connection, f"SELECT * FROM {qualified} ORDER BY ALL")[0]
    availability, keys = layout
    column = sql_identifier(availability)
    partitions = [
        str(row[0]) for row in connection.execute(
            f"SELECT DISTINCT COALESCE(CAST(CAST({column} AS DATE) AS VARCHAR), '__null__') "
            f"FROM {qualified} ORDER BY 1"
        ).fetchall()
    ]
    records = []
    order = ", ".join(sql_identifier(name) for name in keys)
    for partition in partitions:
        where = (
            f"{column} IS NULL" if partition == "__null__"
            else f"CAST({column} AS DATE)=DATE {sql_string(partition)}"
        )
        fingerprint, count, _read, _first, _last = query_fingerprint(
            connection,
            f"SELECT * FROM {qualified} WHERE {where} ORDER BY {order}",
            key_columns=keys,
        )
        records.append({
            "partition": partition, "row_count": count,
            "fingerprint_sha256": fingerprint,
        })
    return canonical_sha256(records)


def _has_migration_ledger(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?", [MIGRATION_TABLE],
    ).fetchone() is not None


def migration_records(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    if not _has_migration_ledger(con):
        return []
    try:
        return con.execute(
            f"SELECT migration_id, migration_sha256, source_commit, "
            f"pre_catalog_sha256, post_catalog_sha256, recovery_manifest_sha256 "
            f"FROM {MIGRATION_TABLE} ORDER BY migration_id"
        ).fetchall()
    except duckdb.Error as exc:
        raise SchemaIdentityError("schema migration ledger has an invalid shape") from exc


def recorded_schema_id(con: duckdb.DuckDBPyConnection) -> int | None:
    rows = migration_records(con)
    return None if not rows else int(rows[-1][0])


def require_compatible_schema(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum: int = MINIMUM_SCHEMA_ID,
    maximum: int = CURRENT_SCHEMA_ID,
) -> dict:
    """Verify exact migrations, source identities, catalog chain, and current catalog."""
    expected = migrations()
    rows = migration_records(con)
    if not rows:
        raise SchemaIdentityError("database has no recorded operational schema migration")
    ids = tuple(int(row[0]) for row in rows)
    if ids != tuple(range(len(rows))) or ids[-1] >= len(expected):
        raise SchemaIdentityError("database migration history is not supported")
    for index, (row, migration) in enumerate(zip(rows, expected, strict=False)):
        if row[1] != migration.sha256:
            raise SchemaIdentityError(
                f"database migration {migration.migration_id:04d} hash does not match source"
            )
        if not isinstance(row[2], str) or GIT_SHA_PATTERN.fullmatch(row[2]) is None:
            raise SchemaIdentityError("database migration source commit is invalid")
        if any(
            not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None
            for value in row[3:]
        ):
            raise SchemaIdentityError("database migration history contains an invalid hash")
        if index and row[3] != rows[index - 1][4]:
            raise SchemaIdentityError("database migration catalog chain is broken")
        expected_post = getattr(migration.module, "EXPECTED_CATALOG_SHA256", None)
        if expected_post is not None and row[4] != expected_post:
            raise SchemaIdentityError(
                f"database migration {migration.migration_id:04d} catalog does not match source"
            )
    current = ids[-1]
    if not minimum <= current <= maximum:
        raise SchemaIdentityError(
            f"database schema ID {current} is outside supported range {minimum}..{maximum}"
        )
    current_hash = catalog_sha256(con)
    if rows[-1][4] != current_hash:
        raise SchemaIdentityError("database catalog changed outside the migration sequence")
    return {"database_schema_id": current, "catalog_sha256": current_hash}


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
    source_storage_identity: dict | None = None
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

    def __del__(self) -> None:
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


def _storage_file_identity(path: Path) -> dict[str, int]:
    value = path.stat()
    if not path.is_file() or path.is_symlink():
        raise OSError(f"storage identity is not a regular file: {path.name}")
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "size_bytes": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def source_storage_identity(database: Path) -> dict[str, dict[str, int] | None]:
    """Identify the primary and its committed WAL without opening DuckDB."""
    database = Path(database).absolute()
    wal = database.with_name(f"{database.name}.wal")
    return {
        "database": _storage_file_identity(database),
        "wal": _storage_file_identity(wal) if wal.exists() else None,
    }


def _valid_source_storage_identity(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"database", "wal"}:
        return False
    fields = {"device", "inode", "size_bytes", "mtime_ns", "ctime_ns"}
    for label in ("database", "wal"):
        record = value[label]
        if label == "wal" and record is None:
            continue
        if (
            not isinstance(record, dict)
            or set(record) != fields
            or any(type(record[field]) is not int or record[field] < 0 for field in fields)
        ):
            return False
    return True


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
        "source_data_commit", "source_storage_identity", "as_of",
        "database_schema_id", "catalog_sha256",
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
        or not _valid_source_storage_identity(body.get("source_storage_identity"))
    ):
        return None
    if not (
        MINIMUM_DATABASE_SCHEMA_ID
        <= schema_id
        <= CURRENT_DATABASE_SCHEMA_ID
    ):
        return None
    expected_catalog = getattr(
        migrations()[schema_id].module, "EXPECTED_CATALOG_SHA256", None,
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
                "create_sql", "columns", "indexes", "append_key", "append_frontier",
            }
            or qualified_name != f"{spec.get('schema')}.{spec.get('table')}"
            or not isinstance(spec.get("availability_column"), str)
            or not isinstance(spec.get("key_columns"), list)
            or not spec["key_columns"]
            or any(not isinstance(value, str) or not value for value in spec["key_columns"])
            or not isinstance(spec.get("create_sql"), str)
            or not isinstance(spec.get("columns"), list)
            or not isinstance(spec.get("indexes"), list)
            or spec.get("append_key") != COLD_APPEND_FRONTIERS.get(qualified_name)
            or (
                spec.get("append_key") is not None
                and (
                    not isinstance(spec["append_key"], str)
                    or not spec["append_key"]
                    or spec["append_key"] not in spec["key_columns"]
                    or (
                        spec.get("append_frontier") is not None
                        and type(spec["append_frontier"]) is not int
                    )
                )
            )
            or (
                spec.get("append_key") is None
                and spec.get("append_frontier") is not None
            )
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
            "cold_frontier_reused_parts", "cold_verification_rows",
            "cold_verification_seconds",
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
        source_storage_identity=body["source_storage_identity"],
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


def structural_snapshot_info(snapshot: Path) -> SnapshotInfo | None:
    """Parse one generation/snapshot manifest and check recorded sizes, without hashing."""
    snapshot = Path(snapshot).absolute()
    if SNAPSHOT_PATTERN.fullmatch(snapshot.name) is None:
        return None
    manifest_path = snapshot.with_suffix(".json")
    try:
        if snapshot.is_symlink() or not snapshot.is_file() or manifest_path.is_symlink():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    info = (
        _generation_info(snapshot.parent, snapshot, manifest_path, manifest)
        if manifest.get("manifest_schema_version") == GENERATION_MANIFEST_SCHEMA_VERSION
        else _legacy_info(snapshot, manifest_path, manifest)
    )
    if info is None or info.manifest_schema_version == GENERATION_MANIFEST_SCHEMA_VERSION:
        return info
    try:
        size_ok = type(info.size_bytes) is int and snapshot.stat().st_size == info.size_bytes
    except OSError:
        return None
    return info if size_ok else None


def verified_snapshot_file(snapshot: Path) -> SnapshotInfo | None:
    """Return one fully byte-verified generation/snapshot file, if valid."""
    info = structural_snapshot_info(snapshot)
    if info is None:
        return None
    try:
        _verify_files(info)
    except GenerationError:
        return None
    return info


def _latest_target(directory: Path) -> Path | None:
    """Resolve market-latest to its same-directory generation file name, read once."""
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


@dataclass(frozen=True)
class RetentionPlan:
    """Which generation files retention keeps and deletes, decided without hashing them."""
    latest: Path | None
    keep: tuple[Path, ...]
    delete: tuple[Path, ...]
    unverified: tuple[Path, ...]


def _publication_order(path: Path) -> tuple[str, int]:
    match = SNAPSHOT_PATTERN.fullmatch(path.name)
    assert match is not None
    return match.group(1), int(match.group(2) or 0)


def retention_plan(
    directory: Path, keep_previous: int = KEEP_PREVIOUS_SNAPSHOTS,
) -> RetentionPlan:
    """Plan to keep the latest generation plus ``keep_previous`` verified older ones.

    Verified means the manifest validates and every recorded file has its recorded size;
    re-hashing every retained generation on each publication would read tens of GiB, so
    readers verify hashes when they pin. The file market-latest names is never deleted,
    verified or not. Without a valid market-latest nothing is deleted. Unverified files
    newer than latest are kept; older unverified files, and verified ones beyond
    ``keep_previous``, are deleted.
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
    unverified = tuple(path for path in candidates if structural_snapshot_info(path) is None)
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


def latest_snapshot(
    database: Path = DEFAULT_DB, *, newer_than_database: bool = False,
) -> SnapshotInfo | None:
    """Resolve the current immutable generation without opening the primary."""
    database = Path(database).absolute()
    info = _latest_info(database)
    if info is None:
        return None
    if newer_than_database and info.manifest_schema_version != GENERATION_MANIFEST_SCHEMA_VERSION:
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
                current_source = source_storage_identity(database)
            except OSError as exc:
                raise GenerationError("primary freshness marker is unavailable") from exc
            if info.source_storage_identity != current_source:
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
            if newer_than_database:
                try:
                    current_source = source_storage_identity(database)
                except OSError as exc:
                    raise GenerationError("primary freshness marker is unavailable") from exc
                if info.source_storage_identity != current_source:
                    raise GenerationError("published generation is stale for evidence reads")
            return SnapshotPin(info, handle)
        except BaseException:
            handle.close()
            raise
    raise GenerationError("published generation changed during pin acquisition")
