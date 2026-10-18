"""Ordered, recovery-gated migrations for the operational DuckDB catalog.

Normal producer initializers may create missing objects in a fresh database,
but they must not upgrade an existing object. An initialized database becomes
operational only after this module records its exact catalog as schema ID 0.
Subsequent schema changes are immutable modules in :mod:`engine.migrations`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine import migrations as migration_registry
from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

MIGRATION_TABLE = migration_registry.MIGRATION_TABLE
MIGRATION_MODULES = migration_registry.MIGRATION_MODULES
CURRENT_SCHEMA_ID = migration_registry.CURRENT_SCHEMA_ID
MINIMUM_SCHEMA_ID = migration_registry.MINIMUM_SCHEMA_ID
Migration = migration_registry.Migration
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
EMPTY_RECOVERY_SHA256 = hashlib.sha256(b"").hexdigest()


class SchemaMigrationError(RuntimeError):
    """The database schema cannot be identified or safely migrated."""


def migrations() -> tuple[Migration, ...]:
    try:
        return migration_registry.migrations()
    except migration_registry.SchemaIdentityError as exc:
        raise SchemaMigrationError(str(exc)) from exc


def _database_name(con: duckdb.DuckDBPyConnection) -> str:
    return migration_registry.database_name(con)


def catalog(con: duckdb.DuckDBPyConnection) -> dict:
    """Return the stable catalog, excluding the migration ledger itself."""
    return migration_registry.catalog(con)


def catalog_sha256(con: duckdb.DuckDBPyConnection) -> str:
    return migration_registry.catalog_sha256(con)


def _records(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    try:
        return migration_registry.records(con)
    except migration_registry.SchemaIdentityError as exc:
        raise SchemaMigrationError(str(exc)) from exc


def schema_id(con: duckdb.DuckDBPyConnection) -> int | None:
    try:
        return migration_registry.schema_id(con)
    except migration_registry.SchemaIdentityError as exc:
        raise SchemaMigrationError(str(exc)) from exc


def require_compatible_schema(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum: int = MINIMUM_SCHEMA_ID,
    maximum: int = CURRENT_SCHEMA_ID,
) -> dict:
    """Return the verified schema identity or refuse an unversioned/drifted DB."""
    try:
        return migration_registry.require_compatible_schema(
            con, minimum=minimum, maximum=maximum,
        )
    except migration_registry.SchemaIdentityError as exc:
        raise SchemaMigrationError(str(exc)) from exc


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
    backup_bundle: Path | None,
    *,
    expected_backup_manifest_sha256: str,
    expected_source_commit: str,
    expected_pre_catalog_sha256: str,
    repo_root: Path = REPO_ROOT,
    fresh_empty: bool = False,
    target_schema_id: int = CURRENT_SCHEMA_ID,
) -> dict:
    """Apply every pending migration after exact source/catalog/backup checks."""
    from tools import backup_database  # avoids an engine import cycle at startup

    for label, value, pattern in (
        ("source commit", expected_source_commit, _GIT_SHA),
        ("pre-migration catalog", expected_pre_catalog_sha256, _SHA256),
    ):
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise SchemaMigrationError(f"expected {label} identity is invalid")
    repo_root = repo_root.resolve(strict=True)
    database = database.resolve(strict=True)
    if type(target_schema_id) is not int or not 0 <= target_schema_id <= CURRENT_SCHEMA_ID:
        raise SchemaMigrationError("target schema ID is invalid")
    if _source_commit(repo_root) != expected_source_commit:
        raise SchemaMigrationError("migration source commit does not match")
    verified = None
    if fresh_empty:
        if backup_bundle is not None or expected_backup_manifest_sha256 != EMPTY_RECOVERY_SHA256:
            raise SchemaMigrationError("fresh-empty bootstrap must not name a recovery bundle")
    else:
        if (
            backup_bundle is None
            or not isinstance(expected_backup_manifest_sha256, str)
            or _SHA256.fullmatch(expected_backup_manifest_sha256) is None
        ):
            raise SchemaMigrationError("expected backup manifest identity is invalid")
        try:
            verified = backup_database.verify_backup(backup_bundle)
        except (backup_database.BackupError, OSError) as exc:
            raise SchemaMigrationError(str(exc)) from exc
        if verified["manifest_sha256"] != expected_backup_manifest_sha256:
            raise SchemaMigrationError("verified recovery bundle identity does not match")
        if verified["source_database"] != _source_location(repo_root, database):
            raise SchemaMigrationError("verified recovery bundle names a different database")

    with backup_database._exclusive_backup_window(repo_root), engine_db.schema_change_authority():
        con = engine_db.connect(database, wait_s=0)
        try:
            existing = _records(con)
            if existing and int(existing[-1][0]) >= target_schema_id:
                identity = require_compatible_schema(con, maximum=target_schema_id)
                return {"status": "current", **identity, "applied": []}
            before_catalog = catalog_sha256(con)
            if before_catalog != expected_pre_catalog_sha256:
                raise SchemaMigrationError("pre-migration catalog identity does not match")
            if fresh_empty:
                if any(catalog(con).values()):
                    raise SchemaMigrationError("fresh-empty bootstrap database is not empty")
            else:
                before_snapshot = backup_database.database_snapshot(con, _database_name(con))
                if canonical_sha256(before_snapshot) != verified["database_snapshot_sha256"]:
                    raise SchemaMigrationError("verified recovery bundle is stale")
            pending = migrations()[len(existing):target_schema_id + 1]
            with engine_db.transaction(con):
                if not existing:
                    _create_ledger(con)
                applied: list[int] = []
                for migration in pending:
                    pre_hash = catalog_sha256(con)
                    bootstrap = getattr(migration.module, "bootstrap", None)
                    expected_post = getattr(migration.module, "EXPECTED_CATALOG_SHA256", None)
                    if migration.migration_id == 0 and pre_hash != expected_post:
                        if bootstrap is None:
                            raise SchemaMigrationError("baseline migration cannot bootstrap catalog")
                        bootstrap(con)
                    for statement in migration.statements:
                        con.execute(statement)
                    post_hash = catalog_sha256(con)
                    if expected_post is not None and post_hash != expected_post:
                        raise SchemaMigrationError(
                            f"migration {migration.migration_id:04d} produced an unexpected catalog"
                        )
                    con.execute(
                        f"INSERT INTO {MIGRATION_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [migration.migration_id, migration.sha256, expected_source_commit,
                         datetime.now(timezone.utc), pre_hash, post_hash,
                         expected_backup_manifest_sha256],
                    )
                    applied.append(migration.migration_id)
                identity = require_compatible_schema(con, maximum=target_schema_id)
        except (duckdb.Error, ValueError) as exc:
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
    apply_parser.add_argument("backup_bundle", type=Path, nargs="?")
    apply_parser.add_argument(
        "--backup-manifest-sha256", default=EMPTY_RECOVERY_SHA256,
    )
    apply_parser.add_argument("--fresh-empty", action="store_true")
    apply_parser.add_argument("--target-schema-id", type=int, default=CURRENT_SCHEMA_ID)
    apply_parser.add_argument("--source-commit", required=True)
    apply_parser.add_argument("--pre-catalog-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            with engine_db.schema_change_authority():
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
                fresh_empty=args.fresh_empty,
                target_schema_id=args.target_schema_id,
            )
    except (OSError, SchemaMigrationError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
