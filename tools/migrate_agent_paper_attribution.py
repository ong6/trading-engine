#!/usr/bin/env python3
"""Install only the empty agent paper-attribution ledgers after backup verification."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from server import agent_paper_attribution, agent_paper_book_preflight
from tools import backup_database

SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ATTRIBUTION_TABLES = (
    agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
    agent_paper_attribution.ORDER_ATTRIBUTION_TABLE,
)


class AttributionMigrationError(RuntimeError):
    """The guarded attribution-schema migration could not be applied."""


def _database_location(repo_root: Path, database: Path) -> dict:
    try:
        relative = database.resolve(strict=True).relative_to(repo_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise AttributionMigrationError(
            "migration database must be an existing repository-relative file"
        ) from exc
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _current_snapshot(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database.database_snapshot(con, database_name)


def _catalog(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database._catalog_rows(con, database_name)


def _catalog_without_attribution(catalog: dict) -> dict:
    return {
        "tables": [
            row for row in catalog["tables"] if row[1] not in ATTRIBUTION_TABLES
        ],
        "views": list(catalog["views"]),
        "indexes": [
            row for row in catalog["indexes"] if row[2] not in ATTRIBUTION_TABLES
        ],
    }


def _schema_status(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    return {
        table: agent_paper_book_preflight._schema(con, table)
        for table in ATTRIBUTION_TABLES
    }


def _table_counts(
    con: duckdb.DuckDBPyConnection,
    tables: tuple[str, ...],
) -> dict[str, int]:
    return {
        table: int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def _require_scoped_change(
    before: dict,
    after: dict,
    before_schema: dict[str, dict],
    before_catalog: dict,
    after_catalog: dict,
) -> None:
    expected_row_counts = dict(before["row_counts"])
    expected_row_counts.update(
        {f"main.{table}": 0 for table in ATTRIBUTION_TABLES}
    )
    unchanged_fields = (
        "latest_price_date",
        "job_states",
        "active_portfolio_count",
        "active_portfolios_sha256",
        "view_count",
    )
    if (
        after["table_count"]
        != before["table_count"]
        + sum(
            status["status"] == "missing"
            for status in before_schema.values()
        )
        or after["row_counts"] != expected_row_counts
        or any(after[field] != before[field] for field in unchanged_fields)
        or _catalog_without_attribution(after_catalog)
        != _catalog_without_attribution(before_catalog)
    ):
        raise AttributionMigrationError(
            "attribution migration changed state outside its schema scope"
        )


def _verified_migration_backup(
    database: Path,
    backup_bundle: Path,
    expected_manifest_sha256: str,
    repo_root: Path,
) -> tuple[Path, dict, dict]:
    if (
        not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
    ):
        raise AttributionMigrationError("expected backup manifest SHA-256 is invalid")
    database = database.resolve(strict=True)
    expected_location = _database_location(repo_root, database)
    try:
        verified_backup = backup_database.verify_backup(backup_bundle)
    except (backup_database.BackupError, OSError) as exc:
        raise AttributionMigrationError(str(exc)) from exc
    if verified_backup["manifest_sha256"] != expected_manifest_sha256:
        raise AttributionMigrationError(
            "verified backup manifest identity does not match"
        )
    if verified_backup["source_database"] != expected_location:
        raise AttributionMigrationError(
            "verified backup names a different source database"
        )
    return database, expected_location, verified_backup


def migrate(
    database: Path,
    backup_bundle: Path,
    expected_manifest_sha256: str,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Apply the two-table schema-only migration after a matching verified backup."""
    database, expected_location, verified_backup = _verified_migration_backup(
        database, backup_bundle, expected_manifest_sha256, repo_root
    )

    try:
        con = engine_db.connect(database, wait_s=0)
    except (duckdb.Error, OSError) as exc:
        raise AttributionMigrationError("migration database is unavailable") from exc
    try:
        before = _current_snapshot(con)
        before_catalog = _catalog(con)
        if canonical_sha256(before) != verified_backup["database_snapshot_sha256"]:
            raise AttributionMigrationError(
                "verified backup does not match the current database snapshot"
            )
        before_schema = _schema_status(con)
        invalid = sorted(
            table
            for table, status in before_schema.items()
            if status["status"] == "invalid"
        )
        if invalid:
            raise AttributionMigrationError(
                "existing attribution schema is incompatible: " + ", ".join(invalid)
            )
        existing_tables = tuple(
            table
            for table, status in before_schema.items()
            if status["status"] == "pass"
        )
        existing_counts = _table_counts(con, existing_tables)
        try:
            with engine_db.transaction(con):
                agent_paper_attribution.init_schema(con)
                after_schema = _schema_status(con)
                if any(
                    status["status"] != "pass"
                    for status in after_schema.values()
                ):
                    raise AttributionMigrationError(
                        "attribution schema failed post-migration verification"
                    )
                if any(_table_counts(con, ATTRIBUTION_TABLES).values()):
                    raise AttributionMigrationError(
                        "attribution migration created or retained unexpected rows"
                    )
                if _table_counts(con, existing_tables) != existing_counts:
                    raise AttributionMigrationError(
                        "attribution migration changed existing attribution rows"
                    )
                after = _current_snapshot(con)
                after_catalog = _catalog(con)
                _require_scoped_change(
                    before,
                    after,
                    before_schema,
                    before_catalog,
                    after_catalog,
                )
        except duckdb.Error as exc:
            raise AttributionMigrationError(
                "attribution schema migration failed"
            ) from exc
    finally:
        con.close()

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "attribution_schema_installed",
        "database": expected_location,
        "backup_manifest_sha256": expected_manifest_sha256,
        "before_snapshot_sha256": canonical_sha256(before),
        "after_snapshot_sha256": canonical_sha256(after),
        "created_tables": sorted(
            table
            for table, status in before_schema.items()
            if status["status"] == "missing"
        ),
        "retained_tables": sorted(existing_tables),
        "attribution_row_counts": {
            table: after["row_counts"][f"main.{table}"]
            for table in ATTRIBUTION_TABLES
        },
        "portfolio_created": False,
        "equity_created": False,
        "order_created": False,
        "scheduler_integration_implemented": False,
        "order_route_implemented": False,
        "initialization_authority": "none",
        "execution_authority": "none",
    }
    return {**body, "migration_sha256": canonical_sha256(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_bundle", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        result = migrate(
            args.database,
            args.backup_bundle,
            args.manifest_sha256,
            repo_root=args.repo_root,
        )
    except (AttributionMigrationError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
