#!/usr/bin/env python3
"""Install empty automatic-paper authority evidence stores after backup verification."""

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
from server import (
    broker_paper_consumption_store,
    broker_paper_startup_store,
)
from tools import backup_database

SCHEMA_VERSION = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
TABLES = (
    broker_paper_startup_store.RETENTION_TABLE,
    broker_paper_consumption_store.RISK_EVIDENCE_TABLE,
)


class PaperAuthorityStoreMigrationError(RuntimeError):
    """The guarded paper-authority store migration could not be applied."""


def _database_location(repo_root: Path, database: Path) -> dict:
    try:
        relative = database.resolve(strict=True).relative_to(
            repo_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise PaperAuthorityStoreMigrationError(
            "migration database must be an existing repository-relative file"
        ) from exc
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _current_snapshot(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database.database_snapshot(con, database_name)


def _catalog(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database._catalog_rows(con, database_name)


def _catalog_without_authority_store(catalog: dict) -> dict:
    return {
        "tables": [row for row in catalog["tables"] if row[1] not in TABLES],
        "views": list(catalog["views"]),
        "indexes": [row for row in catalog["indexes"] if row[2] not in TABLES],
    }


def _schema_status(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, str]:
    try:
        retained_schema = broker_paper_startup_store._table_schema(con)
        risk_schema = broker_paper_consumption_store._table_schema(
            con,
            broker_paper_consumption_store.RISK_EVIDENCE_TABLE,
        )
    except (
        broker_paper_consumption_store.PaperConsumptionStoreError,
        broker_paper_startup_store.PaperAuthorityStartupStoreError,
    ) as exc:
        raise PaperAuthorityStoreMigrationError(
            "existing paper authority store schema is incompatible"
        ) from exc
    expected = {
        broker_paper_startup_store.RETENTION_TABLE: (
            retained_schema,
            broker_paper_startup_store.RETENTION_SCHEMA,
        ),
        broker_paper_consumption_store.RISK_EVIDENCE_TABLE: (
            risk_schema,
            broker_paper_consumption_store.RISK_EVIDENCE_SCHEMA,
        ),
    }
    if any(actual not in {None, wanted} for actual, wanted in expected.values()):
        raise PaperAuthorityStoreMigrationError(
            "existing paper authority store schema is incompatible"
        )
    return {
        table: "missing" if actual is None else "pass"
        for table, (actual, _wanted) in expected.items()
    }


def _create_empty_schema(con: duckdb.DuckDBPyConnection) -> None:
    columns = ", ".join(
        (
            f"{name} {kind}"
            if name == "prior_global_row_sha256"
            else f"{name} {kind} NOT NULL"
        )
        for name, kind in broker_paper_startup_store.RETENTION_COLUMNS
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS "
        f"{broker_paper_startup_store.RETENTION_TABLE} ({columns})"
    )
    risk_columns = ", ".join(
        (
            f"{name} {kind} PRIMARY KEY"
            if name == "idempotency_key"
            else f"{name} {kind} UNIQUE NOT NULL"
            if name == "evaluation_sha256"
            else f"{name} {kind} NOT NULL"
        )
        for name, kind in broker_paper_consumption_store.RISK_EVIDENCE_COLUMNS
    )
    con.execute(
        f"CREATE TABLE IF NOT EXISTS "
        f"{broker_paper_consumption_store.RISK_EVIDENCE_TABLE} "
        f"({risk_columns})"
    )


def _require_scoped_change(
    before: dict,
    after: dict,
    *,
    missing_tables: tuple[str, ...],
    before_catalog: dict,
    after_catalog: dict,
) -> None:
    expected_row_counts = {
        **before["row_counts"],
        **{f"main.{table}": 0 for table in TABLES},
    }
    unchanged_fields = (
        "latest_price_date",
        "job_states",
        "active_portfolio_count",
        "active_portfolios_sha256",
        "view_count",
    )
    if (
        after["table_count"] != before["table_count"] + len(missing_tables)
        or after["row_counts"] != expected_row_counts
        or any(after[field] != before[field] for field in unchanged_fields)
        or _catalog_without_authority_store(after_catalog)
        != _catalog_without_authority_store(before_catalog)
    ):
        raise PaperAuthorityStoreMigrationError(
            "paper authority store migration changed state outside its schema scope"
        )


def _verify_backup_binding(
    backup_bundle: Path,
    expected_manifest_sha256: str,
    expected_location: dict,
) -> dict:
    if (
        not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
    ):
        raise PaperAuthorityStoreMigrationError(
            "expected backup manifest SHA-256 is invalid"
        )
    try:
        verified = backup_database.verify_backup(backup_bundle)
    except (backup_database.BackupError, OSError) as exc:
        raise PaperAuthorityStoreMigrationError(str(exc)) from exc
    if verified["manifest_sha256"] != expected_manifest_sha256:
        raise PaperAuthorityStoreMigrationError(
            "verified backup manifest identity does not match"
        )
    if verified["source_database"] != expected_location:
        raise PaperAuthorityStoreMigrationError(
            "verified backup names a different source database"
        )
    return verified


def _install(
    con: duckdb.DuckDBPyConnection,
    verified_backup: dict,
) -> tuple[dict, dict, tuple[str, ...]]:
    before = _current_snapshot(con)
    if canonical_sha256(before) != verified_backup["database_snapshot_sha256"]:
        raise PaperAuthorityStoreMigrationError(
            "verified backup does not match the current database snapshot"
        )
    before_catalog = _catalog(con)
    before_status = _schema_status(con)
    missing_tables = tuple(
        table for table, status in before_status.items() if status == "missing"
    )
    if any(
        status == "pass"
        and con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table, status in before_status.items()
    ):
        raise PaperAuthorityStoreMigrationError(
            "paper authority stores must be empty during schema migration"
        )
    try:
        with engine_db.transaction(con):
            _create_empty_schema(con)
            if any(
                status != "pass"
                for status in _schema_status(con).values()
            ):
                raise PaperAuthorityStoreMigrationError(
                    "paper authority store failed post-migration verification"
                )
            if any(
                con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in TABLES
            ):
                raise PaperAuthorityStoreMigrationError(
                    "paper authority migration created or retained unexpected rows"
                )
            after = _current_snapshot(con)
            _require_scoped_change(
                before,
                after,
                missing_tables=missing_tables,
                before_catalog=before_catalog,
                after_catalog=_catalog(con),
            )
    except duckdb.Error as exc:
        raise PaperAuthorityStoreMigrationError(
            "paper authority store migration failed"
        ) from exc
    return before, after, missing_tables


def migrate(
    database: Path,
    backup_bundle: Path,
    expected_manifest_sha256: str,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Install only empty, non-authorizing automatic-paper evidence tables."""
    database = database.resolve(strict=True)
    expected_location = _database_location(repo_root, database)
    verified_backup = _verify_backup_binding(
        backup_bundle,
        expected_manifest_sha256,
        expected_location,
    )
    try:
        con = engine_db.connect(database, wait_s=0)
    except (duckdb.Error, OSError) as exc:
        raise PaperAuthorityStoreMigrationError(
            "migration database is unavailable"
        ) from exc
    try:
        before, after, missing_tables = _install(con, verified_backup)
    finally:
        con.close()

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "paper_authority_store_schema_installed",
        "database": expected_location,
        "backup_manifest_sha256": expected_manifest_sha256,
        "before_snapshot_sha256": canonical_sha256(before),
        "after_snapshot_sha256": canonical_sha256(after),
        "created_tables": list(missing_tables),
        "retained_tables": [
            table for table in TABLES if table not in missing_tables
        ],
        "retained_event_count": 0,
        "retained_risk_evaluation_count": 0,
        "activation_writer_implemented": True,
        "atomic_pre_call_writer_implemented": True,
        "runtime_activation_implemented": False,
        "adapter_integration_implemented": False,
        "paper_order_route": "absent",
        "submission_authority": "none",
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
    except (PaperAuthorityStoreMigrationError, OSError) as exc:
        print(
            json.dumps(
                {"status": "failed", "reason": str(exc)},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
