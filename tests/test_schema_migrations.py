"""Operational schema migrations are explicit, ordered, and recovery-gated."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from engine import schema_migrations
from engine.lib.provenance import canonical_sha256
from tools import backup_database

SOURCE_COMMIT = "a" * 40
BACKUP_MANIFEST = "b" * 64


def _database(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE prices (date DATE, ticker VARCHAR, volume BIGINT)")
    con.execute("INSERT INTO prices VALUES ('2026-10-16', 'SPY', 100)")
    con.execute("CREATE TABLE jobs (id INTEGER, state VARCHAR)")
    con.execute(
        "CREATE TABLE portfolios (id VARCHAR, name VARCHAR, strategy VARCHAR, "
        "config VARCHAR, created DATE, active BOOLEAN, cash DOUBLE, initial_cash DOUBLE, "
        "execution_profile VARCHAR)"
    )
    con.execute("CREATE TABLE sim_orders (id INTEGER)")
    con.execute("CREATE TABLE sim_fills (id INTEGER)")
    con.execute(
        "CREATE TABLE sim_equity (portfolio_id VARCHAR, date DATE, equity DOUBLE, "
        "cash DOUBLE, n_positions INTEGER)"
    )
    con.close()


def _prepare(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict, str]:
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    _database(database)
    con = duckdb.connect(str(database), read_only=True)
    try:
        expected_catalog = schema_migrations.catalog_sha256(con)
        snapshot_sha = canonical_sha256(
            backup_database.database_snapshot(con, con.execute(
                "SELECT current_database()"
            ).fetchone()[0])
        )
    finally:
        con.close()
    verified = {
        "manifest_sha256": BACKUP_MANIFEST,
        "database_snapshot_sha256": snapshot_sha,
        "source_database": {
            "kind": "repository-relative",
            "path": "store/market.duckdb",
        },
    }
    monkeypatch.setattr(schema_migrations, "_source_commit", lambda _root: SOURCE_COMMIT)
    monkeypatch.setattr(backup_database, "verify_backup", lambda _bundle: verified)
    return root, database, verified, expected_catalog


def _apply(root: Path, database: Path, expected_catalog: str) -> dict:
    return schema_migrations.apply(
        database,
        root / "verified-bundle",
        expected_backup_manifest_sha256=BACKUP_MANIFEST,
        expected_source_commit=SOURCE_COMMIT,
        expected_pre_catalog_sha256=expected_catalog,
        repo_root=root,
    )


def test_baseline_plan_apply_and_idempotency(tmp_path, monkeypatch):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    con = duckdb.connect(str(database), read_only=True)
    try:
        planned = schema_migrations.plan(con)
    finally:
        con.close()
    assert planned["status"] == "planned"
    assert planned["expected_pre_catalog_sha256"] == expected_catalog
    assert [item["migration_id"] for item in planned["pending"]] == [0]

    applied = _apply(root, database, expected_catalog)
    again = _apply(root, database, expected_catalog)

    assert applied == {
        "status": "applied",
        "database_schema_id": 0,
        "catalog_sha256": expected_catalog,
        "applied": [0],
    }
    assert again == {
        "status": "current",
        "database_schema_id": 0,
        "catalog_sha256": expected_catalog,
        "applied": [],
    }
    con = duckdb.connect(str(database), read_only=True)
    try:
        record = con.execute(
            "SELECT migration_id, source_commit, pre_catalog_sha256, "
            "post_catalog_sha256, recovery_manifest_sha256 FROM schema_migrations"
        ).fetchone()
    finally:
        con.close()
    assert record == (
        0, SOURCE_COMMIT, expected_catalog, expected_catalog, BACKUP_MANIFEST,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_source_commit", "c" * 40, "source commit does not match"),
        ("expected_backup_manifest_sha256", "c" * 64, "bundle identity does not match"),
        ("expected_pre_catalog_sha256", "c" * 64, "catalog identity does not match"),
    ],
)
def test_apply_refuses_wrong_source_backup_or_catalog(
    tmp_path, monkeypatch, field, value, message,
):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    kwargs = {
        "expected_backup_manifest_sha256": BACKUP_MANIFEST,
        "expected_source_commit": SOURCE_COMMIT,
        "expected_pre_catalog_sha256": expected_catalog,
        "repo_root": root,
    }
    kwargs[field] = value

    with pytest.raises(schema_migrations.SchemaMigrationError, match=message):
        schema_migrations.apply(database, root / "bundle", **kwargs)

    con = duckdb.connect(str(database), read_only=True)
    try:
        assert schema_migrations.schema_id(con) is None
    finally:
        con.close()


def test_apply_refuses_stale_recovery_bundle(tmp_path, monkeypatch):
    root, database, verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    verified["database_snapshot_sha256"] = "c" * 64

    with pytest.raises(schema_migrations.SchemaMigrationError, match="bundle is stale"):
        _apply(root, database, expected_catalog)


def test_interrupted_statement_rolls_back_ledger_and_catalog(tmp_path, monkeypatch):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    migration = schema_migrations.Migration(
        migration_id=0,
        description="interruption fixture",
        sha256="d" * 64,
        statements=("CREATE TABLE migration_probe (id INTEGER)", "invalid SQL"),
    )
    monkeypatch.setattr(schema_migrations, "migrations", lambda: (migration,))

    with pytest.raises(schema_migrations.SchemaMigrationError, match="migration failed"):
        _apply(root, database, expected_catalog)

    con = duckdb.connect(str(database), read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        assert "schema_migrations" not in tables
        assert "migration_probe" not in tables
        assert schema_migrations.catalog_sha256(con) == expected_catalog
    finally:
        con.close()


def test_compatibility_rejects_catalog_drift_and_migration_hash_drift(
    tmp_path, monkeypatch,
):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    _apply(root, database, expected_catalog)
    con = duckdb.connect(str(database))
    try:
        con.execute("CREATE TABLE unrecorded_change (id INTEGER)")
        with pytest.raises(schema_migrations.SchemaMigrationError, match="outside"):
            schema_migrations.require_compatible_schema(con)
        con.execute("DROP TABLE unrecorded_change")
        con.execute("UPDATE schema_migrations SET migration_sha256=?", ["e" * 64])
        with pytest.raises(schema_migrations.SchemaMigrationError, match="hash does not match"):
            schema_migrations.require_compatible_schema(con)
    finally:
        con.close()
