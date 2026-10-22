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
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib import resources, store_limits
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.lib.snapshots import (
    COLD_APPEND_FRONTIERS,
    COLD_TABLE_LAYOUTS,
    KEEP_PREVIOUS_SNAPSHOTS,
    LATEST_NAME,
    GenerationError,
    pin_latest_generation,
    query_fingerprint,
    retention_plan,
    snapshot_directory,
    source_storage_identity,
    table_logical_sha256,
)
from tools import backup_database

COLD_TABLES = COLD_TABLE_LAYOUTS
_PUBLICATION_LOCK_HELD: ContextVar[bool] = ContextVar(
    "generation_publication_lock_held", default=False,
)


# Every DuckDB connection publication opens is capped and spills to the snapshot directory;
# DuckDB's default (80% of host memory) let the first 12 GB generation reach 24 GB RSS.
PUBLISH_MEMORY_LIMIT = "4GB"
CAPTURE_LOCK_WAIT_S = 30.0
PUBLISH_THREADS = 4
SPILL_DIRECTORY = ".spill"


def _bounded(connection: duckdb.DuckDBPyConnection, directory: Path):
    connection.execute(f"SET memory_limit='{PUBLISH_MEMORY_LIMIT}'")
    connection.execute(f"SET threads={PUBLISH_THREADS}")
    connection.execute(
        f"SET temp_directory={backup_database._sql_string(str(directory / SPILL_DIRECTORY))}"
    )
    return connection


class SnapshotError(RuntimeError):
    """The snapshot could not be published without disturbing the prior one."""


class PublicationBusy(SnapshotError):
    """A publish-on-change run found a publication or producer already running."""


@contextmanager
def _publication_window(directory: Path, *, blocking: bool = True):
    """Serialize install, pointer publication, verification, and garbage collection."""
    lock_path = directory / ".generation-publish.lock"
    created = not lock_path.exists()
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if created:
            _sync_directory(directory)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SnapshotError("generation publication lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise PublicationBusy("another publication is running") from exc
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
        append_key = COLD_APPEND_FRONTIERS.get(qualified_name)
        append_frontier = None
        if append_key is not None:
            append_frontier = connection.execute(
                f"SELECT MAX({_identifier(append_key)}) FROM "
                f"{_qualified(schema, table)}"
            ).fetchone()[0]
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
            "append_key": append_key,
            "append_frontier": append_frontier,
        }
    return specs


def _partition_where(spec: dict, partition: str) -> str:
    column = _identifier(spec["availability_column"])
    if partition == "__null__":
        return f"{column} IS NULL"
    return f"CAST({column} AS DATE) = DATE {backup_database._sql_string(partition)}"


def _partition_fingerprint(
    connection: duckdb.DuckDBPyConnection, spec: dict, where: str,
) -> tuple[str, int, int, list | None, list | None]:
    table = _qualified(spec["schema"], spec["table"])
    return query_fingerprint(
        connection, f"SELECT * FROM {table} WHERE {where}",
        order_by=tuple(spec["key_columns"]),
        key_columns=tuple(spec["key_columns"]),
    )


def _partitions(
    connection: duckdb.DuckDBPyConnection, spec: dict,
) -> list[str]:
    table = _qualified(spec["schema"], spec["table"])
    column = _identifier(spec["availability_column"])
    return [
        str(row[0]) for row in connection.execute(
            f"SELECT DISTINCT COALESCE(CAST(CAST({column} AS DATE) AS VARCHAR), "
            f"'__null__') FROM {table} ORDER BY 1"
        ).fetchall()
    ]


def _frontier_reusable_partitions(
    connection: duckdb.DuckDBPyConnection,
    spec: dict,
    previous_spec: dict | None,
    current_partitions: set[str],
) -> set[str]:
    """Return partitions unchanged by rows beyond a durable monotonic-key frontier."""
    if previous_spec is None:
        return set()
    append_key = spec["append_key"]
    previous_frontier = previous_spec.get("append_frontier")
    current_frontier = spec["append_frontier"]
    if (
        append_key is None
        or previous_spec.get("append_key") != append_key
        or type(previous_frontier) is not int
        or type(current_frontier) is not int
        or current_frontier < previous_frontier
    ):
        return set()
    table = _qualified(spec["schema"], spec["table"])
    column = _identifier(spec["availability_column"])
    key = _identifier(append_key)
    changed = {
        str(row[0]) for row in connection.execute(
            f"SELECT DISTINCT COALESCE(CAST(CAST({column} AS DATE) AS VARCHAR), "
            f"'__null__') FROM {table} WHERE {key}>? ORDER BY 1",
            [previous_frontier],
        ).fetchall()
    }
    previous_partitions = {
        str(record["partition"])
        for record in previous_spec.get("parts", ())
    }
    return current_partitions & previous_partitions - changed


def _verify_append_only_prefix(
    connection: duckdb.DuckDBPyConnection,
    previous_info,
    row_counts: dict[str, int],
    cold_specs: dict[str, dict],
) -> None:
    """Refuse removal, replacement, or insertion behind a published cold frontier."""
    if previous_info is None:
        return
    alias = "previous_generation"
    connection.execute(
        f"ATTACH {backup_database._sql_string(str(previous_info.path))} "
        f"AS {alias} (READ_ONLY)"
    )
    try:
        for qualified_name, spec in sorted(cold_specs.items()):
            previous_count = previous_info.row_counts.get(qualified_name)
            current_count = row_counts.get(qualified_name)
            if (
                type(previous_count) is not int
                or type(current_count) is not int
                or current_count < previous_count
            ):
                raise SnapshotError(
                    f"cold table cardinality regressed below published frontier: {qualified_name}"
                )
            schema, table = qualified_name.split(".", 1)
            previous = _qualified(schema, table, database=alias)
            current = _qualified(schema, table)
            append_key = spec["append_key"]
            frontier = previous_info.cold_tables.get(qualified_name, {}).get(
                "append_frontier"
            )
            if append_key is None:
                missing = connection.execute(
                    f"SELECT COUNT(*) FROM ((SELECT * FROM {previous}) EXCEPT ALL "
                    f"(SELECT * FROM {current}))"
                ).fetchone()[0]
                extra = 0
            elif type(frontier) is int:
                key = _identifier(append_key)
                missing = connection.execute(
                    f"SELECT COUNT(*) FROM ((SELECT * FROM {previous} WHERE {key}<=?) "
                    f"EXCEPT ALL (SELECT * FROM {current} WHERE {key}<=?))",
                    [frontier, frontier],
                ).fetchone()[0]
                extra = connection.execute(
                    f"SELECT COUNT(*) FROM ((SELECT * FROM {current} WHERE {key}<=?) "
                    f"EXCEPT ALL (SELECT * FROM {previous} WHERE {key}<=?))",
                    [frontier, frontier],
                ).fetchone()[0]
            else:
                if previous_count:
                    raise SnapshotError(
                        f"cold table append frontier is unavailable: {qualified_name}"
                    )
                missing = extra = 0
            if missing or extra:
                raise SnapshotError(
                    f"cold table changed at or below published frontier: {qualified_name}"
                )
    except duckdb.Error as exc:
        raise SnapshotError(f"cold append-only verification failed: {exc}") from exc
    finally:
        try:
            connection.execute(f"DETACH {alias}")
        except duckdb.Error:
            pass


def _install_cold_parts(
    connection: duckdb.DuckDBPyConnection,
    directory: Path,
    previous_parts: tuple[dict, ...],
    previous_cold_tables: dict[str, dict],
    specs: dict[str, dict],
) -> tuple[list[dict], dict[str, dict], dict[str, int]]:
    installed: list[dict] = []
    metrics = {
        "new_bytes": 0, "read_bytes": 0, "serialized_bytes": 0,
        "copy_operations": 0, "frontier_reused_parts": 0,
    }
    previous = {
        (record["table"], record["partition"]): record for record in previous_parts
        if "fingerprint_sha256" in record
    }
    for qualified_name, spec in specs.items():
        table = _qualified(spec["schema"], spec["table"])
        order = ", ".join(_identifier(name) for name in spec["key_columns"])
        partitions = _partitions(connection, spec)
        previous_spec = previous_cold_tables.get(qualified_name)
        if previous_spec is not None:
            previous_spec = {
                **previous_spec,
                "parts": tuple(
                    record for record in previous_parts
                    if record["table"] == qualified_name
                ),
            }
        reusable = _frontier_reusable_partitions(
            connection, spec, previous_spec, set(partitions),
        )
        for partition in partitions:
            where = _partition_where(spec, partition)
            prior = previous.get((qualified_name, partition))
            if prior is not None and partition in reusable:
                prior_path = directory / prior["path"]
                if (
                    prior_path.is_file()
                    and not prior_path.is_symlink()
                    and prior_path.stat().st_size == prior["size_bytes"]
                    and _sha256(prior_path) == prior["sha256"]
                ):
                    installed.append(dict(prior))
                    metrics["frontier_reused_parts"] += 1
                    continue
            fingerprint, row_count, bytes_read, key_min, key_max = _partition_fingerprint(
                connection, spec, where,
            )
            metrics["read_bytes"] += bytes_read
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


def _generation_table_hashes(
    connection: duckdb.DuckDBPyConnection,
    database: str,
    row_counts: dict[str, int],
    cold_specs: dict[str, dict],
    parts: list[dict],
) -> dict[str, str]:
    hashes = {}
    for qualified_name in sorted(row_counts):
        if qualified_name in cold_specs:
            records = [
                {
                    "partition": record["partition"],
                    "row_count": record["row_count"],
                    "fingerprint_sha256": record["fingerprint_sha256"],
                }
                for record in parts if record["table"] == qualified_name
            ]
            hashes[qualified_name] = backup_database.canonical_sha256(records)
        else:
            schema, table = qualified_name.split(".", 1)
            hashes[qualified_name] = table_logical_sha256(
                connection, database, schema, table,
            )
    return hashes


def _empty_relation(spec: dict) -> str:
    columns = ", ".join(
        f"CAST(NULL AS {column['type']}) AS {_identifier(column['name'])}"
        for column in spec["columns"]
    )
    return f"SELECT {columns} WHERE FALSE"


def _open_capture_handle(source: Path, wait_s: float) -> duckdb.DuckDBPyConnection:
    """Open the primary read-only, waiting out a short writer (an API POST) for a while."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return duckdb.connect(str(source), read_only=True)
        except duckdb.Error as exc:
            if not engine_db.is_lock_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.1)  # API writes last milliseconds: take the first gap between them


def _copy_capture(source: Path, capture: Path) -> None:
    """Copy the primary's bytes (and a pending WAL, replayed into the copy) for the build."""
    shutil.copyfile(source, capture)
    os.chmod(capture, 0o600)
    wal = source.with_name(f"{source.name}.wal")
    if wal.exists():
        copied_wal = capture.with_name(f"{capture.name}.wal")
        shutil.copyfile(wal, copied_wal)
        replay = duckdb.connect(str(capture))
        try:
            replay.execute("CHECKPOINT")
        finally:
            replay.close()
        if copied_wal.exists():
            raise SnapshotError("captured copy's WAL was not checkpointed")


def _build_hot_database(
    capture: Path, destination: Path, parts: list[dict], cold_specs: dict[str, dict],
) -> None:
    connection = _bounded(duckdb.connect(str(destination)), destination.parent)
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


def _verify_semantic_equality(
    capture: Path, hot: Path, row_counts: dict[str, int], cold_tables: set[str],
) -> dict[str, float | int]:
    started = time.monotonic()
    connection = _bounded(duckdb.connect(), hot.parent)
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
    return {
        "seconds": time.monotonic() - started,
        "rows": sum(row_counts[name] for name in cold_tables),
    }


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


def _retain_newest(directory: Path, keep_previous: int = KEEP_PREVIOUS_SNAPSHOTS) -> None:
    """Delete generations outside the latest-plus-``keep_previous`` plan, sparing pinned ones."""
    if not _PUBLICATION_LOCK_HELD.get():
        with _publication_window(directory):
            _retain_newest(directory, keep_previous)
        return
    for old in retention_plan(directory, keep_previous).delete:
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


def retention_listing(
    source: Path, keep_previous: int = KEEP_PREVIOUS_SNAPSHOTS,
) -> dict:
    """Describe retention and disk accounting without deleting or opening a database."""
    directory = snapshot_directory(source)
    plan = retention_plan(directory, keep_previous)
    unverified = set(plan.unverified)

    def describe(path: Path) -> dict:
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        return {"snapshot": path.name, "size_bytes": size, "verified": path not in unverified}

    store_dir = Path(source).absolute().parent
    live_gb = resources.live_store_gb(store_dir)
    snapshot_gb = resources.snapshots_gb(store_dir)
    return {
        "status": "dry-run",
        "keep_previous": keep_previous,
        "latest": plan.latest.name if plan.latest is not None else None,
        "keep": [describe(path) for path in plan.keep],
        "delete": [describe(path) for path in plan.delete],
        "store_gb_excluding_snapshots": round(live_gb, 2),
        "store_soft_cap_gb": resources.STORE_SOFT_GB,
        "snapshots_gb": round(snapshot_gb, 2),
        "snapshot_soft_cap_gb": resources.SNAPSHOT_SOFT_GB,
    }


def publish_snapshot(
    repo_root: Path,
    source: Path,
    *,
    now: datetime | None = None,
    held_locks: frozenset[str] = frozenset(),
    min_age_minutes: float | None = None,
    if_changed: bool = False,
) -> dict:
    """Publish a verified hot/cold generation; retain latest plus one verified generation.

    ``if_changed`` is the publish-on-change timer's mode: it skips successfully when the
    newest generation was captured from the primary's current bytes, and never waits for
    a running publication or producer (it skips instead), so it cannot delay one.
    """
    repo_root = repo_root.resolve()
    source = source.resolve(strict=True)
    directory = snapshot_directory(source)
    _mkdir_durable(source.parent, directory)
    if if_changed:
        unchanged = _unchanged_generation(source)
        if unchanged is not None:
            return unchanged
    try:
        with _publication_window(directory, blocking=not if_changed):
            return _publish_locked(
                repo_root, source, directory, now=now, held_locks=held_locks,
                min_age_minutes=min_age_minutes,
                capture_wait_s=0.0 if if_changed else CAPTURE_LOCK_WAIT_S,
            )
    except PublicationBusy as exc:
        if not if_changed:
            raise
        return {"status": "skipped", "reason": str(exc)}
    except SnapshotError as exc:
        # A cooperating producer holds its lock, or a writer (an API POST, a unit without
        # the legacy locks) has the primary open: try again at the next timer slot.
        if if_changed and ("active process holds" in str(exc) or engine_db.is_lock_error(exc)):
            return {"status": "skipped", "reason": f"producer active: {exc}"}
        raise


def _unchanged_generation(source: Path) -> dict | None:
    try:
        pin = pin_latest_generation(source)
    except GenerationError:
        return None
    try:
        if pin.info.source_storage_identity != source_storage_identity(source):
            return None
        return {
            "status": "skipped",
            "reason": "the newest generation was captured from the primary's current bytes",
            "snapshot": pin.info.path.name,
            "as_of": pin.info.as_of.isoformat(),
        }
    finally:
        pin.close()


def _publish_locked(
    repo_root: Path,
    source: Path,
    directory: Path,
    *,
    now: datetime | None,
    held_locks: frozenset[str],
    min_age_minutes: float | None,
    capture_wait_s: float = CAPTURE_LOCK_WAIT_S,
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
            try:
                fresh_pin = pin_latest_generation(source, newer_than_database=True)
            except GenerationError:
                pass
            else:
                latest = fresh_pin.info
                fresh_pin.close()
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
    capture = directory / f".capture-{destination.stem}.{secrets.token_hex(8)}.duckdb"
    try:
        lock_started = time.monotonic()
        with backup_database._exclusive_backup_window(repo_root, skip_locks=held_locks):
            # Checked inside the window, so a backup cannot spend the same free space. The
            # capture copies the primary, and a generation rewrites the hot part and appends
            # cold parts: twice the database size is the conservative bound.
            try:
                store_limits.require_free_space(
                    directory, purpose="publish a store snapshot",
                    need_bytes=2 * store_limits.file_bytes(source),
                )
            except store_limits.DiskSpaceError as exc:
                raise SnapshotError(str(exc)) from exc
            # The capture window: producer locks plus a read-only handle that keeps API
            # writers out only while the file bytes are copied (seconds, not the build).
            source_connection = _bounded(
                _open_capture_handle(source, capture_wait_s), directory,
            )
            try:
                source_database = source_connection.execute(
                    "SELECT current_database()"
                ).fetchone()[0]
                snapshot = backup_database.database_snapshot(
                    source_connection, source_database, include_content=False,
                )
                schema_identity = engine_db.require_compatible_database_schema(source_connection)
                captured_cohort = _capture_cohort(repo_root, snapshot)
                _copy_capture(source, capture)
                # Identify the primary while the handle still excludes writers (finding 4).
                storage_identity = source_storage_identity(source)
                as_of = datetime.now(timezone.utc)
            finally:
                source_connection.close()
        writer_lock_seconds = time.monotonic() - lock_started
        capture_connection = _bounded(
            duckdb.connect(str(capture), read_only=True), directory,
        )
        try:
            capture_database = capture_connection.execute(
                "SELECT current_database()"
            ).fetchone()[0]
            if backup_database.database_snapshot(
                capture_connection, capture_database, include_content=False,
            ) != snapshot:
                raise SnapshotError("captured copy differs from the primary it copied")
            previous_parts = () if previous_pin is None else previous_pin.info.parts
            previous_cold_tables = (
                {} if previous_pin is None else previous_pin.info.cold_tables
            )
            cold_specs = _cold_specs(capture_connection)
            _verify_append_only_prefix(
                capture_connection,
                None if previous_pin is None else previous_pin.info,
                snapshot["row_counts"],
                cold_specs,
            )
            parts, cold_specs, cold_metrics = _install_cold_parts(
                capture_connection, directory, previous_parts, previous_cold_tables,
                cold_specs,
            )
            snapshot["table_sha256"] = _generation_table_hashes(
                capture_connection, capture_database, snapshot["row_counts"],
                cold_specs, parts,
            )
        finally:
            capture_connection.close()
        _build_hot_database(capture, temporary, parts, cold_specs)
        equality_metrics = _verify_semantic_equality(
            capture, temporary, snapshot["row_counts"], set(cold_specs),
        )
        cohort = _install_cohort(directory, captured_cohort)
        body = {
            "manifest_schema_version": 2,
            "duckdb_version": duckdb.__version__,
            "generation_id": destination.stem,
            "snapshot": destination.name,
            "source_database": str(source.relative_to(repo_root)),
            "source_data_commit": _data_commit(repo_root),
            "source_storage_identity": storage_identity,
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
                "cold_frontier_reused_parts": cold_metrics["frontier_reused_parts"],
                "cold_verification_rows": equality_metrics["rows"],
                "cold_verification_seconds": equality_metrics["seconds"],
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
        OSError, ValueError, duckdb.Error, GenerationError, backup_database.BackupError,
        engine_db.SchemaMigrationRequired,
    ) as exc:
        if pointer_advanced:
            _restore_latest(directory, previous_target)
        raise SnapshotError(str(exc)) from exc
    finally:
        if previous_pin is not None:
            previous_pin.close()
        temporary.unlink(missing_ok=True)
        capture.unlink(missing_ok=True)
        capture.with_name(f"{capture.name}.wal").unlink(missing_ok=True)
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
        "--retention-dry-run",
        action="store_true",
        help="list what retention would keep and delete, and the disk accounting; "
        "publishes and deletes nothing",
    )
    parser.add_argument(
        "--if-changed",
        action="store_true",
        help="publish-on-change: skip when the newest generation matches the primary, or "
        "when a publication or producer is running",
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
    if args.retention_dry_run:
        print(json.dumps(retention_listing(source), sort_keys=True))
        return 0
    try:
        result = publish_snapshot(
            repo_root,
            source,
            held_locks=frozenset(args.held_lock),
            min_age_minutes=args.min_age_minutes,
            if_changed=args.if_changed,
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
