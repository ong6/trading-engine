"""Ordered, recovery-gated migrations for the operational DuckDB catalog.

Normal producer initializers may create missing objects in a fresh database,
but they must not upgrade an existing object. An initialized database becomes
operational only after this module records its exact catalog as schema ID 0.
Subsequent schema changes are immutable modules in :mod:`engine.migrations`.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

MIGRATION_TABLE = "schema_migrations"
MIGRATION_MODULES = ("engine.migrations.0000_post_r15_baseline",)
CURRENT_SCHEMA_ID = len(MIGRATION_MODULES) - 1
MINIMUM_SCHEMA_ID = 0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class SchemaMigrationError(RuntimeError):
    """The database schema cannot be identified or safely migrated."""


@dataclass(frozen=True)
class Migration:
    migration_id: int
    description: str
    sha256: str
    statements: tuple[str, ...]


def _module_migration(name: str) -> Migration:
    module: ModuleType = importlib.import_module(name)
    source = Path(module.__file__ or "").read_bytes()
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
        raise SchemaMigrationError(f"invalid migration module: {name}")
    return Migration(
        migration_id=migration_id,
        description=description,
        sha256=hashlib.sha256(source).hexdigest(),
        statements=statements,
    )


def migrations() -> tuple[Migration, ...]:
    loaded = tuple(_module_migration(name) for name in MIGRATION_MODULES)
    if tuple(item.migration_id for item in loaded) != tuple(range(len(loaded))):
        raise SchemaMigrationError("migration IDs must be contiguous from zero")
    return loaded


def _database_name(con: duckdb.DuckDBPyConnection) -> str:
    return str(con.execute("SELECT current_database()").fetchone()[0])


def catalog(con: duckdb.DuckDBPyConnection) -> dict:
    """Return the stable catalog, excluding the migration ledger itself."""
    return engine_db.database_catalog(con)


def catalog_sha256(con: duckdb.DuckDBPyConnection) -> str:
    return engine_db.database_catalog_sha256(con)


def _has_migration_table(con: duckdb.DuckDBPyConnection) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?",
        [MIGRATION_TABLE],
    ).fetchone() is not None


def _records(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    if not _has_migration_table(con):
        return []
    try:
        return con.execute(
            f"SELECT migration_id, migration_sha256, source_commit, "
            f"pre_catalog_sha256, post_catalog_sha256, recovery_manifest_sha256 "
            f"FROM {MIGRATION_TABLE} ORDER BY migration_id"
        ).fetchall()
    except duckdb.Error as exc:
        raise SchemaMigrationError("schema migration ledger has an invalid shape") from exc


def schema_id(con: duckdb.DuckDBPyConnection) -> int | None:
    records = _records(con)
    return None if not records else int(records[-1][0])


def require_compatible_schema(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum: int = MINIMUM_SCHEMA_ID,
    maximum: int = CURRENT_SCHEMA_ID,
) -> dict:
    """Return the verified schema identity or refuse an unversioned/drifted DB."""
    expected = migrations()
    records = _records(con)
    if not records:
        raise SchemaMigrationError("database has no recorded operational schema migration")
    ids = tuple(int(row[0]) for row in records)
    if ids != tuple(range(len(records))) or ids[-1] >= len(expected):
        raise SchemaMigrationError("database migration history is not supported")
    for row, migration in zip(records, expected, strict=False):
        if row[1] != migration.sha256:
            raise SchemaMigrationError(
                f"database migration {migration.migration_id:04d} hash does not match source"
            )
        for value in row[3:]:
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise SchemaMigrationError("database migration history contains an invalid hash")
    current = ids[-1]
    if not minimum <= current <= maximum:
        raise SchemaMigrationError(
            f"database schema ID {current} is outside supported range {minimum}..{maximum}"
        )
    actual_catalog = catalog_sha256(con)
    if records[-1][4] != actual_catalog:
        raise SchemaMigrationError("database catalog changed outside the migration sequence")
    return {"database_schema_id": current, "catalog_sha256": actual_catalog}


def plan(con: duckdb.DuckDBPyConnection) -> dict:
    """Describe the exact current catalog and pending ordered migrations."""
    records = _records(con)
    loaded = migrations()
    if records:
        require_compatible_schema(con, maximum=CURRENT_SCHEMA_ID)
    pending = loaded[len(records):]
    return {
        "status": "current" if not pending else "planned",
        "database_schema_id": None if not records else int(records[-1][0]),
        "expected_pre_catalog_sha256": catalog_sha256(con),
        "pending": [
            {
                "migration_id": migration.migration_id,
                "migration_sha256": migration.sha256,
                "description": migration.description,
                "statement_count": len(migration.statements),
            }
            for migration in pending
        ],
    }


def _source_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True,
        check=False,
    )
    value = result.stdout.strip()
    if result.returncode or _GIT_SHA.fullmatch(value) is None:
        raise SchemaMigrationError("migration source commit is unavailable")
    return value


def _source_location(repo_root: Path, database: Path) -> dict:
    try:
        relative = database.resolve(strict=True).relative_to(repo_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SchemaMigrationError(
            "migration database must be an existing repository-relative file"
        ) from exc
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _create_ledger(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""CREATE TABLE {MIGRATION_TABLE} (
        migration_id INTEGER PRIMARY KEY,
        migration_sha256 VARCHAR NOT NULL,
        source_commit VARCHAR NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL,
        pre_catalog_sha256 VARCHAR NOT NULL,
        post_catalog_sha256 VARCHAR NOT NULL,
        recovery_manifest_sha256 VARCHAR NOT NULL)"""
    )


def apply(
    database: Path,
    backup_bundle: Path,
    *,
    expected_backup_manifest_sha256: str,
    expected_source_commit: str,
    expected_pre_catalog_sha256: str,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Apply every pending migration after exact source/catalog/backup checks."""
    from tools import backup_database  # avoids an engine import cycle at startup

    for label, value, pattern in (
        ("backup manifest", expected_backup_manifest_sha256, _SHA256),
        ("source commit", expected_source_commit, _GIT_SHA),
        ("pre-migration catalog", expected_pre_catalog_sha256, _SHA256),
    ):
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise SchemaMigrationError(f"expected {label} identity is invalid")
    repo_root = repo_root.resolve(strict=True)
    database = database.resolve(strict=True)
    if _source_commit(repo_root) != expected_source_commit:
        raise SchemaMigrationError("migration source commit does not match")
    try:
        verified = backup_database.verify_backup(backup_bundle)
    except (backup_database.BackupError, OSError) as exc:
        raise SchemaMigrationError(str(exc)) from exc
    if verified["manifest_sha256"] != expected_backup_manifest_sha256:
        raise SchemaMigrationError("verified recovery bundle identity does not match")
    if verified["source_database"] != _source_location(repo_root, database):
        raise SchemaMigrationError("verified recovery bundle names a different database")

    with backup_database._exclusive_backup_window(repo_root):
        con = engine_db.connect(database, wait_s=0)
        try:
            existing = _records(con)
            if existing:
                identity = require_compatible_schema(con)
                return {"status": "current", **identity, "applied": []}
            before_catalog = catalog_sha256(con)
            if before_catalog != expected_pre_catalog_sha256:
                raise SchemaMigrationError("pre-migration catalog identity does not match")
            before_snapshot = backup_database.database_snapshot(con, _database_name(con))
            if canonical_sha256(before_snapshot) != verified["database_snapshot_sha256"]:
                raise SchemaMigrationError("verified recovery bundle is stale")
            pending = migrations()
            with engine_db.transaction(con):
                _create_ledger(con)
                applied: list[int] = []
                for migration in pending:
                    pre_hash = catalog_sha256(con)
                    for statement in migration.statements:
                        con.execute(statement)
                    post_hash = catalog_sha256(con)
                    con.execute(
                        f"INSERT INTO {MIGRATION_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [migration.migration_id, migration.sha256, expected_source_commit,
                         datetime.now(timezone.utc), pre_hash, post_hash,
                         expected_backup_manifest_sha256],
                    )
                    applied.append(migration.migration_id)
                identity = require_compatible_schema(con)
        except duckdb.Error as exc:
            raise SchemaMigrationError(f"schema migration failed: {exc}") from exc
        finally:
            con.close()
    return {"status": "applied", **identity, "applied": applied}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("backup_bundle", type=Path)
    apply_parser.add_argument("--backup-manifest-sha256", required=True)
    apply_parser.add_argument("--source-commit", required=True)
    apply_parser.add_argument("--pre-catalog-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            con = engine_db.connect(args.database, read_only=True, wait_s=0)
            try:
                result = plan(con)
            finally:
                con.close()
        else:
            result = apply(
                args.database, args.backup_bundle,
                expected_backup_manifest_sha256=args.backup_manifest_sha256,
                expected_source_commit=args.source_commit,
                expected_pre_catalog_sha256=args.pre_catalog_sha256,
                repo_root=args.repo_root,
            )
    except (OSError, SchemaMigrationError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
