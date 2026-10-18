#!/usr/bin/env python3
"""Publish an immutable, consistent read-only copy of the engine database."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.snapshots import (
    LATEST_NAME,
    GenerationError,
    pin_latest_generation,
    snapshot_directory,
)
from tools import backup_database

KEEP_SNAPSHOTS = 2
COLD_TABLES = {
    "main.intraday_prices": ("as_of", ("ticker", "ts", "interval")),
    "main.bitemporal_facts": ("ingested_at", ("id",)),
    "main.source_response_receipts": ("received_at", ("id",)),
}
_PUBLICATION_LOCK_HELD: ContextVar[bool] = ContextVar(
    "generation_publication_lock_held", default=False,
)


class SnapshotError(RuntimeError):
    """The snapshot could not be published without disturbing the prior one."""


@contextmanager
def _publication_window(directory: Path):
    """Serialize install, pointer publication, verification, and garbage collection."""
    lock_path = directory / ".generation-publish.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SnapshotError("generation publication lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        token = _PUBLICATION_LOCK_HELD.set(True)
        try:
            yield
        finally:
            _PUBLICATION_LOCK_HELD.reset(token)
    finally:
        os.close(descriptor)


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


def _mkdir_durable(root: Path, directory: Path) -> None:
    """Create and fsync every directory entry from root through directory."""
    relative = directory.relative_to(root)
    current = root
    for part in relative.parts:
        child = current / part
        created = not child.exists()
        child.mkdir(mode=0o700, exist_ok=True)
        if created:
            _sync_directory(child)
            _sync_directory(current)
        current = child


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _qualified(schema: str, table: str, *, database: str | None = None) -> str:
    names = (schema, table) if database is None else (database, schema, table)
    return ".".join(_identifier(name) for name in names)


def _capture_cohort(repo_root: Path, snapshot: dict) -> dict[str, dict[str, bytes]]:
    sections: dict[str, dict[str, bytes]] = {
        "prospective_evidence": {},
        "operational_artifacts": {},
        "operational_controls": {},
    }
    for relative in backup_database.EVIDENCE_FILES:
        sections["prospective_evidence"][relative] = backup_database._read_source_file(
            repo_root, relative, "prospective evidence", data_dir=repo_root / "data",
        )
    for relative in backup_database._operational_files(snapshot["latest_price_date"]):
        sections["operational_artifacts"][relative] = backup_database._read_source_file(
            repo_root, relative, "operational artifact", data_dir=repo_root / "data",
        )
    for relative in backup_database.OPTIONAL_OPERATIONAL_CONTROL_FILES:
        try:
            content = backup_database._read_source_file(
                repo_root, relative, "operational control", data_dir=repo_root / "data",
            )
        except backup_database.SourceFileMissing:
            continue
        sections["operational_controls"][relative] = content
    return sections


def _install_bytes(directory: Path, content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("blobs") / digest[:2] / digest
    destination = directory / relative
    _mkdir_durable(directory, destination.parent)
    valid = (
        destination.exists()
        and not destination.is_symlink()
        and destination.stat().st_size == len(content)
        and _sha256(destination) == digest
    )
    if not valid:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(handle.fileno(), 0o400)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            _sync_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
    return {"path": relative.as_posix(), "size_bytes": len(content), "sha256": digest}


def _install_cohort(directory: Path, captured: dict[str, dict[str, bytes]]) -> dict:
    return {
        section: {
            relative: _install_bytes(directory, content)
            for relative, content in sorted(records.items())
        }
        for section, records in captured.items()
    }


def _cold_specs(connection: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    database = connection.execute("SELECT current_database()").fetchone()[0]
    available = {
        f"{schema}.{table}": sql
        for schema, table, sql in connection.execute(
            "SELECT schema_name, table_name, sql FROM duckdb_tables() "
            "WHERE database_name=? AND NOT internal AND NOT temporary",
            [database],
        ).fetchall()
    }
    specs = {}
    for qualified_name, (availability, keys) in COLD_TABLES.items():
        if qualified_name not in available:
            continue
        schema, table = qualified_name.split(".", 1)
        columns = [
            {"name": name, "type": data_type}
            for name, data_type in connection.execute(
                "SELECT column_name, data_type FROM duckdb_columns() "
                "WHERE database_name=? AND schema_name=? AND table_name=? "
                "ORDER BY column_index",
                [database, schema, table],
            ).fetchall()
        ]
        if availability not in {column["name"] for column in columns}:
            raise SnapshotError(f"cold table lacks availability column: {qualified_name}")
        specs[qualified_name] = {
            "schema": schema,
            "table": table,
            "availability_column": availability,
            "key_columns": list(keys),
            "create_sql": available[qualified_name],
            "columns": columns,
            "indexes": [
                sql
                for (sql,) in connection.execute(
                    "SELECT sql FROM duckdb_indexes() WHERE database_name=? "
                    "AND schema_name=? AND table_name=? ORDER BY index_name",
                    [database, schema, table],
                ).fetchall()
            ],
        }
    return specs


def _partition_values(
    connection: duckdb.DuckDBPyConnection, spec: dict,
) -> list[str]:
    table = _qualified(spec["schema"], spec["table"])
    column = _identifier(spec["availability_column"])
    rows = connection.execute(
        f"SELECT DISTINCT COALESCE(CAST(CAST({column} AS DATE) AS VARCHAR), '__null__') "
        f"FROM {table} ORDER BY 1"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _partition_where(spec: dict, partition: str) -> str:
    column = _identifier(spec["availability_column"])
    if partition == "__null__":
        return f"{column} IS NULL"
    return f"CAST({column} AS DATE) = DATE {backup_database._sql_string(partition)}"


def _fingerprint_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return [type(value).__name__, value]
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, (date, datetime)):
        return [type(value).__name__, value.isoformat()]
    return [type(value).__name__, str(value)]


def _partition_fingerprint(
    connection: duckdb.DuckDBPyConnection, spec: dict, where: str,
) -> tuple[str, int, int, list | None, list | None]:
    table = _qualified(spec["schema"], spec["table"])
    order = ", ".join(_identifier(name) for name in spec["key_columns"])
    cursor = connection.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order}")
    digest = hashlib.sha256()
    row_count = 0
    bytes_read = 0
    key_indexes = [
        index for index, description in enumerate(cursor.description)
        if description[0] in spec["key_columns"]
    ]
    key_min = key_max = None
    while rows := cursor.fetchmany(10_000):
        for row in rows:
            encoded = json.dumps(
                [_fingerprint_value(value) for value in row],
                separators=(",", ":"), sort_keys=False,
            ).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            bytes_read += len(encoded)
            key = [_fingerprint_value(row[index]) for index in key_indexes]
            key_min = key if key_min is None else key_min
            key_max = key
            row_count += 1
    return digest.hexdigest(), row_count, bytes_read, key_min, key_max


def _install_cold_parts(
    connection: duckdb.DuckDBPyConnection,
    directory: Path,
    previous_parts: tuple[dict, ...],
) -> tuple[list[dict], dict[str, dict], dict[str, int]]:
    installed: list[dict] = []
    metrics = {"new_bytes": 0, "read_bytes": 0, "serialized_bytes": 0, "copy_operations": 0}
    previous = {
        (record["table"], record["partition"]): record for record in previous_parts
        if "fingerprint_sha256" in record
    }
    specs = _cold_specs(connection)
    for qualified_name, spec in specs.items():
        table = _qualified(spec["schema"], spec["table"])
        order = ", ".join(_identifier(name) for name in spec["key_columns"])
        for partition in _partition_values(connection, spec):
            where = _partition_where(spec, partition)
            fingerprint, row_count, bytes_read, key_min, key_max = _partition_fingerprint(
                connection, spec, where,
            )
            metrics["read_bytes"] += bytes_read
            prior = previous.get((qualified_name, partition))
            if prior is not None and prior["fingerprint_sha256"] == fingerprint:
                prior_path = directory / prior["path"]
                if (
                    prior_path.is_file()
                    and not prior_path.is_symlink()
                    and prior_path.stat().st_size == prior["size_bytes"]
                    and _sha256(prior_path) == prior["sha256"]
                ):
                    installed.append(dict(prior))
                    continue
            temporary_dir = directory / ".parts"
            _mkdir_durable(directory, temporary_dir)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=temporary_dir, prefix=f".{spec['table']}.", suffix=".parquet.tmp",
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            temporary.unlink()
            try:
                connection.execute(
                    f"COPY (SELECT * FROM {table} WHERE {where} ORDER BY {order}) "
                    f"TO {backup_database._sql_string(str(temporary))} "
                    "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
                )
                metrics["copy_operations"] += 1
                metrics["serialized_bytes"] += temporary.stat().st_size
                digest = _sha256(temporary)
                relative = Path("parts") / spec["table"] / f"{partition}-{digest}.parquet"
                destination = directory / relative
                _mkdir_durable(directory, destination.parent)
                valid = (
                    destination.exists()
                    and not destination.is_symlink()
                    and destination.stat().st_size == temporary.stat().st_size
                    and _sha256(destination) == digest
                )
                if valid:
                    temporary.unlink()
                else:
                    os.chmod(temporary, 0o400)
                    _sync_file(temporary)
                    os.replace(temporary, destination)
                    _sync_directory(destination.parent)
                    metrics["new_bytes"] += destination.stat().st_size
                installed.append({
                    "table": qualified_name,
                    "partition": partition,
                    "path": relative.as_posix(),
                    "size_bytes": destination.stat().st_size,
                    "sha256": digest,
                    "fingerprint_sha256": fingerprint,
                    "row_count": row_count,
                    "source_bytes": bytes_read,
                    "availability_column": spec["availability_column"],
                    "availability_min": None if partition == "__null__" else partition,
                    "availability_max": None if partition == "__null__" else partition,
                    "key_min": key_min,
                    "key_max": key_max,
                })
            finally:
                temporary.unlink(missing_ok=True)
    return installed, specs, metrics


def _empty_relation(spec: dict) -> str:
    columns = ", ".join(
        f"CAST(NULL AS {column['type']}) AS {_identifier(column['name'])}"
        for column in spec["columns"]
    )
    return f"SELECT {columns} WHERE FALSE"


def _build_hot_database(
    capture: Path, destination: Path, parts: list[dict], cold_specs: dict[str, dict],
) -> None:
    connection = duckdb.connect(str(destination))
    try:
        connection.execute(
            f"ATTACH {backup_database._sql_string(str(capture))} AS generation_source (READ_ONLY)"
        )
        database = "generation_source"
        object_schemas = {
            row[0]
            for query in (
                "SELECT schema_name FROM duckdb_tables() WHERE database_name=? AND NOT internal",
                "SELECT schema_name FROM duckdb_views() WHERE database_name=? AND NOT internal",
                "SELECT schema_name FROM duckdb_sequences() WHERE database_name=? AND NOT temporary",
            )
            for row in connection.execute(query, [database]).fetchall()
        }
        for schema in sorted(object_schemas - {"main"}):
            connection.execute(f"CREATE SCHEMA {_identifier(schema)}")
        sequences = connection.execute(
            "SELECT schema_name, sequence_name, min_value, max_value, increment_by, "
            "cycle, sql FROM duckdb_sequences() "
            "WHERE database_name=? AND NOT temporary ORDER BY schema_name, sequence_name",
            [database],
        ).fetchall()
        for schema, name, minimum, maximum, increment, cycle, sql in sequences:
            qualified_sequence = _qualified(schema, name)
            start_match = re.search(r"\bSTART\s+(-?\d+)\b", sql)
            if start_match is None:
                raise SnapshotError(f"sequence next value is unavailable: {schema}.{name}")
            next_value = int(start_match.group(1))
            connection.execute(
                f"CREATE SEQUENCE {qualified_sequence} INCREMENT BY {increment} "
                f"MINVALUE {minimum} MAXVALUE {maximum} START {next_value} "
                f"{'CYCLE' if cycle else 'NO CYCLE'}"
            )
        tables = connection.execute(
            "SELECT schema_name, table_name, sql FROM duckdb_tables() "
            "WHERE database_name=? AND NOT internal AND NOT temporary "
            "ORDER BY schema_name, table_name", [database],
        ).fetchall()
        for schema, table, sql in tables:
            connection.execute(sql)
            if f"{schema}.{table}" not in cold_specs:
                connection.execute(
                    f"INSERT INTO {_qualified(schema, table)} SELECT * FROM "
                    f"{_qualified(schema, table, database=database)}"
                )
        for qualified_name, spec in cold_specs.items():
            connection.execute(f"DROP TABLE {_qualified(spec['schema'], spec['table'])}")
            paths = [
                str(destination.parent / record["path"])
                for record in parts if record["table"] == qualified_name
            ]
            relation = _empty_relation(spec) if not paths else (
                "SELECT * FROM read_parquet(["
                + ", ".join(backup_database._sql_string(path) for path in paths)
                + "])"
            )
            connection.execute(
                f"CREATE VIEW {_qualified(spec['schema'], spec['table'])} AS {relation}"
            )
        indexes = connection.execute(
            "SELECT table_name, sql FROM duckdb_indexes() WHERE database_name=? "
            "ORDER BY schema_name, index_name", [database],
        ).fetchall()
        cold_names = {spec["table"] for spec in cold_specs.values()}
        for table, sql in indexes:
            if table not in cold_names:
                connection.execute(sql)
        views = connection.execute(
            "SELECT sql FROM duckdb_views() WHERE database_name=? AND NOT internal "
            "ORDER BY schema_name, view_name", [database],
        ).fetchall()
        for (sql,) in views:
            connection.execute(sql)
        connection.execute("DETACH generation_source")
        connection.execute("CHECKPOINT")
    except duckdb.Error as exc:
        raise SnapshotError(f"hot generation build failed: {exc}") from exc
    finally:
        connection.close()
    os.chmod(destination, 0o400)
    _sync_file(destination)


def _verify_semantic_equality(capture: Path, hot: Path, row_counts: dict[str, int]) -> None:
    connection = duckdb.connect()
    try:
        connection.execute(
            f"ATTACH {backup_database._sql_string(str(capture))} AS original (READ_ONLY)"
        )
        connection.execute(
            f"ATTACH {backup_database._sql_string(str(hot))} AS generation (READ_ONLY)"
        )
        for qualified_name in sorted(row_counts):
            schema, table = qualified_name.split(".", 1)
            original = _qualified(schema, table, database="original")
            generation = _qualified(schema, table, database="generation")
            missing = connection.execute(
                f"SELECT COUNT(*) FROM ((SELECT * FROM {original}) EXCEPT ALL "
                f"(SELECT * FROM {generation}))"
            ).fetchone()[0]
            extra = connection.execute(
                f"SELECT COUNT(*) FROM ((SELECT * FROM {generation}) EXCEPT ALL "
                f"(SELECT * FROM {original}))"
            ).fetchone()[0]
            if missing or extra:
                raise SnapshotError(f"generation differs from source table: {qualified_name}")
    except duckdb.Error as exc:
        raise SnapshotError(f"generation equality verification failed: {exc}") from exc
    finally:
        connection.close()


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


def _restore_latest(directory: Path, previous: str | None) -> None:
    latest = directory / LATEST_NAME
    if previous is None:
        latest.unlink(missing_ok=True)
        _sync_directory(directory)
        return
    target = directory / previous
    if not target.is_file() or target.is_symlink():
        raise SnapshotError("cannot restore the previous generation pointer")
    temporary = directory / f".{LATEST_NAME}.{secrets.token_hex(8)}.rollback"
    try:
        os.symlink(previous, temporary)
        os.replace(temporary, latest)
        _sync_directory(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _reachable_payloads(directory: Path) -> set[Path]:
    reachable: set[Path] = set()
    for manifest_path in directory.glob("market-*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if manifest.get("manifest_schema_version") != 2:
            continue
        for record in manifest.get("parts", []):
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                reachable.add(directory / record["path"])
        for records in manifest.get("cohort", {}).values():
            if isinstance(records, dict):
                for record in records.values():
                    if isinstance(record, dict) and isinstance(record.get("path"), str):
                        reachable.add(directory / record["path"])
    return reachable


def _prune_unreachable_payloads(directory: Path) -> None:
    if not _PUBLICATION_LOCK_HELD.get():
        with _publication_window(directory):
            _prune_unreachable_payloads(directory)
        return
    reachable = _reachable_payloads(directory)
    for root_name in ("parts", "blobs"):
        root = directory / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file() and not path.is_symlink() and path not in reachable:
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass


def _retain_newest(directory: Path) -> None:
    snapshots = sorted(
        path for path in directory.glob("market-*.duckdb")
        if path.name != LATEST_NAME and not path.is_symlink()
    )
    for old in snapshots[:-KEEP_SNAPSHOTS]:
        pin_path = directory / "pins" / f"{old.stem}.lock"
        _mkdir_durable(directory, pin_path.parent)
        with pin_path.open("a+b") as pin:
            try:
                fcntl.flock(pin.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
        pin_path.unlink(missing_ok=True)
    _prune_unreachable_payloads(directory)
    _sync_directory(directory)


def publish_snapshot(
    repo_root: Path,
    source: Path,
    *,
    now: datetime | None = None,
    held_locks: frozenset[str] = frozenset(),
    min_age_minutes: float | None = None,
) -> dict:
    """Publish a verified hot/cold generation and retain two unpinned generations."""
    repo_root = repo_root.resolve()
    source = source.resolve(strict=True)
    directory = snapshot_directory(source)
    directory.mkdir(parents=True, exist_ok=True)
    with _publication_window(directory):
        return _publish_locked(
            repo_root, source, directory, now=now, held_locks=held_locks,
            min_age_minutes=min_age_minutes,
        )


def _publish_locked(
    repo_root: Path,
    source: Path,
    directory: Path,
    *,
    now: datetime | None,
    held_locks: frozenset[str],
    min_age_minutes: float | None,
) -> dict:
    checked_at = datetime.now(timezone.utc)
    started = time.monotonic()
    previous_pin = None
    try:
        previous_pin = pin_latest_generation(source)
    except GenerationError:
        pass
    if min_age_minutes is not None:
        if not math.isfinite(min_age_minutes) or min_age_minutes < 0:
            if previous_pin is not None:
                previous_pin.close()
            raise SnapshotError("minimum snapshot age must be a non-negative number")
        if previous_pin is not None and previous_pin.info.as_of > checked_at - timedelta(
            minutes=min_age_minutes
        ):
            latest = previous_pin.info
            previous_pin.close()
            age_minutes = max(0.0, (checked_at - latest.as_of).total_seconds() / 60)
            return {
                "status": "skipped",
                "reason": (
                    f"latest snapshot is {age_minutes:.1f} minutes old; "
                    f"minimum age is {min_age_minutes:g} minutes"
                ),
                "snapshot": latest.path.name,
                "as_of": latest.as_of.isoformat(),
            }
    previous_target = None
    try:
        previous_target = os.readlink(directory / LATEST_NAME)
    except OSError:
        pass
    destination = _unique_destination(directory, now or datetime.now(timezone.utc))
    temporary = directory / f".{destination.name}.{secrets.token_hex(8)}.tmp"
    manifest_path = destination.with_suffix(".json")
    published = pointer_advanced = False
    try:
        lock_started = time.monotonic()
        with backup_database._exclusive_backup_window(repo_root, skip_locks=held_locks):
            source_connection = duckdb.connect(str(source), read_only=True)
            try:
                source_database = source_connection.execute(
                    "SELECT current_database()"
                ).fetchone()[0]
                snapshot = backup_database.database_snapshot(
                    source_connection, source_database,
                )
                schema_identity = engine_db.require_compatible_database_schema(source_connection)
                captured_cohort = _capture_cohort(repo_root, snapshot)
                previous_parts = () if previous_pin is None else previous_pin.info.parts
                parts, cold_specs, cold_metrics = _install_cold_parts(
                    source_connection, directory, previous_parts,
                )
                _build_hot_database(source, temporary, parts, cold_specs)
                _verify_semantic_equality(source, temporary, snapshot["row_counts"])
                as_of = datetime.now(timezone.utc)
            finally:
                source_connection.close()
        writer_lock_seconds = time.monotonic() - lock_started
        cohort = _install_cohort(directory, captured_cohort)
        body = {
            "manifest_schema_version": 2,
            "generation_id": destination.stem,
            "snapshot": destination.name,
            "source_database": str(source.relative_to(repo_root)),
            "source_data_commit": _data_commit(repo_root),
            "as_of": as_of.isoformat(),
            **schema_identity,
            "hot_database": {
                "path": destination.name,
                "size_bytes": temporary.stat().st_size,
                "sha256": _sha256(temporary),
            },
            "row_counts": snapshot["row_counts"],
            "source_snapshot": snapshot,
            "parts": parts,
            "cold_tables": cold_specs,
            "cohort": cohort,
            "metrics": {
                "wall_seconds": time.monotonic() - started,
                "writer_lock_seconds": writer_lock_seconds,
                "hot_size_bytes": temporary.stat().st_size,
                "cold_part_bytes": sum(record["size_bytes"] for record in parts),
                "new_cold_part_bytes": cold_metrics["new_bytes"],
                "cold_bytes_read": cold_metrics["read_bytes"],
                "cold_bytes_serialized": cold_metrics["serialized_bytes"],
                "cold_copy_operations": cold_metrics["copy_operations"],
            },
        }
        manifest = {**body, "manifest_sha256": backup_database.canonical_sha256(body)}
        os.replace(temporary, destination)
        _write_manifest(manifest_path, manifest)
        _sync_directory(directory)
        _swap_latest(directory, destination)
        pointer_advanced = True
        final_pin = pin_latest_generation(source)
        try:
            if final_pin.info.generation_id != destination.stem:
                raise SnapshotError("published pointer did not resolve to the new generation")
        finally:
            final_pin.close()
        published = True
        if previous_pin is not None:
            previous_pin.close()
            previous_pin = None
        _retain_newest(directory)
        return manifest
    except (
        OSError, ValueError, GenerationError, backup_database.BackupError,
        engine_db.SchemaMigrationRequired,
    ) as exc:
        if pointer_advanced:
            _restore_latest(directory, previous_target)
        raise SnapshotError(str(exc)) from exc
    finally:
        if previous_pin is not None:
            previous_pin.close()
        temporary.unlink(missing_ok=True)
        if not published:
            destination.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            _prune_unreachable_payloads(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--min-age-minutes",
        type=float,
        default=None,
        metavar="N",
        help="skip successfully when the latest snapshot is newer than N minutes",
    )
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
            repo_root,
            source,
            held_locks=frozenset(args.held_lock),
            min_age_minutes=args.min_age_minutes,
        )
    except SnapshotError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    if result.get("status") == "skipped":
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps({"status": "published", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
