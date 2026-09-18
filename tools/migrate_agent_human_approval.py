#!/usr/bin/env python3
"""Install only the empty human-paper approval ledger after backup verification."""

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
from server import broker_human_paper_approval_store
from tools import backup_database

SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
TABLE = broker_human_paper_approval_store.TABLE


class HumanApprovalMigrationError(RuntimeError):
    """The guarded human-approval schema migration could not be applied."""


def _database_location(repo_root: Path, database: Path) -> dict:
    try:
        relative = database.resolve(strict=True).relative_to(
            repo_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise HumanApprovalMigrationError(
            "migration database must be an existing repository-relative file"
        ) from exc
    return {"kind": "repository-relative", "path": relative.as_posix()}


def _current_snapshot(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database.database_snapshot(con, database_name)


def _catalog(con: duckdb.DuckDBPyConnection) -> dict:
    database_name = con.execute("SELECT current_database()").fetchone()[0]
    return backup_database._catalog_rows(con, database_name)


def _catalog_without_approval(catalog: dict) -> dict:
    return {
        "tables": [row for row in catalog["tables"] if row[1] != TABLE],
        "views": list(catalog["views"]),
        "indexes": [row for row in catalog["indexes"] if row[2] != TABLE],
    }


def _schema_status(con: duckdb.DuckDBPyConnection) -> str:
    try:
        return broker_human_paper_approval_store._schema(con)
    except (
        broker_human_paper_approval_store.HumanPaperApprovalStoreError
    ) as exc:
        raise HumanApprovalMigrationError(
            "existing human approval schema is incompatible"
        ) from exc


def _require_scoped_change(
    before: dict,
    after: dict,
    *,
    table_missing: bool,
    before_catalog: dict,
    after_catalog: dict,
) -> None:
    expected_row_counts = {
        **before["row_counts"],
        f"main.{TABLE}": 0,
    }
    unchanged_fields = (
        "latest_price_date",
        "job_states",
        "active_portfolio_count",
        "active_portfolios_sha256",
        "view_count",
    )
    if (
        after["table_count"] != before["table_count"] + int(table_missing)
        or after["row_counts"] != expected_row_counts
        or any(after[field] != before[field] for field in unchanged_fields)
        or _catalog_without_approval(after_catalog)
        != _catalog_without_approval(before_catalog)
    ):
        raise HumanApprovalMigrationError(
            "human approval migration changed state outside its schema scope"
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
        raise HumanApprovalMigrationError(
            "expected backup manifest SHA-256 is invalid"
        )
    try:
        verified = backup_database.verify_backup(backup_bundle)
    except (backup_database.BackupError, OSError) as exc:
        raise HumanApprovalMigrationError(str(exc)) from exc
    if verified["manifest_sha256"] != expected_manifest_sha256:
        raise HumanApprovalMigrationError(
            "verified backup manifest identity does not match"
        )
    if verified["source_database"] != expected_location:
        raise HumanApprovalMigrationError(
            "verified backup names a different source database"
        )
    return verified


def _install(
    con: duckdb.DuckDBPyConnection,
    verified_backup: dict,
) -> tuple[dict, dict, bool]:
    before = _current_snapshot(con)
    if canonical_sha256(before) != verified_backup["database_snapshot_sha256"]:
        raise HumanApprovalMigrationError(
            "verified backup does not match the current database snapshot"
        )
    before_catalog = _catalog(con)
    before_status = _schema_status(con)
    table_missing = before_status == "missing"
    if not table_missing and con.execute(
        f"SELECT COUNT(*) FROM {TABLE}"
    ).fetchone()[0]:
        raise HumanApprovalMigrationError(
            "human approval ledger must be empty during schema migration"
        )
    try:
        with engine_db.transaction(con):
            broker_human_paper_approval_store.init_schema(con)
            if _schema_status(con) != "pass":
                raise HumanApprovalMigrationError(
                    "human approval schema failed post-migration verification"
                )
            if con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]:
                raise HumanApprovalMigrationError(
                    "human approval migration created or retained unexpected rows"
                )
            after = _current_snapshot(con)
            _require_scoped_change(
                before,
                after,
                table_missing=table_missing,
                before_catalog=before_catalog,
                after_catalog=_catalog(con),
            )
    except duckdb.Error as exc:
        raise HumanApprovalMigrationError(
            "human approval schema migration failed"
        ) from exc
    return before, after, table_missing


def migrate(
    database: Path,
    backup_bundle: Path,
    expected_manifest_sha256: str,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict:
    """Install only an empty, non-authorizing human-approval evidence ledger."""
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
        raise HumanApprovalMigrationError(
            "migration database is unavailable"
        ) from exc
    try:
        before, after, table_missing = _install(con, verified_backup)
    finally:
        con.close()

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "human_approval_schema_installed",
        "database": expected_location,
        "backup_manifest_sha256": expected_manifest_sha256,
        "before_snapshot_sha256": canonical_sha256(before),
        "after_snapshot_sha256": canonical_sha256(after),
        "created_table": TABLE if table_missing else None,
        "retained_table": None if table_missing else TABLE,
        "approval_observation_count": 0,
        "trust_source_loader_implemented": False,
        "human_order_approval_granted": False,
        "production_authority_consumption_implemented": False,
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
    except (HumanApprovalMigrationError, OSError) as exc:
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
