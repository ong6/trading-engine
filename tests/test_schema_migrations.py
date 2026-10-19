"""Operational schema migrations are explicit, ordered, and recovery-gated."""
from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from engine import schema_migrations
from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from tools import backup_database

SOURCE_COMMIT = "a" * 40
BACKUP_MANIFEST = "b" * 64
HISTORICAL_FIXTURES = {
    "pre-v2": (
        "schema_catalog_pre_v2.json", "63e5b3ba7476cd280737924ec3fb6a2a812e2afe",
        "3ea2d60e7c575d4e4e249f3d13ae3ede031a9c5eabf8e7d8b56c6b6205ef6fba",
    ),
    "v2": (
        "schema_catalog_v2.json", "f37ee65d0072c18f29f096b9de7011215ee0a526",
        "62bf42557342666325c3b7ee19bf0fb15c564df4c6516be93eb0cf974cbb6034",
    ),
    "r15": (
        "schema_catalog_r15.json", "c3f5c0b13e8107b9e9e68c8afeca0a7e4701f85b",
        "dcd1a8ea73f4136bc935f37d506b16b0d65f7928c88788c96a0f2bde809165b7",
    ),
}


def _database(path: Path, shape: str = "r15") -> None:
    fixture_name, source_commit, catalog_sha256 = HISTORICAL_FIXTURES[shape]
    fixture = json.loads((Path(__file__).parent / "fixtures" / fixture_name).read_text())
    assert fixture["format"] == "duckdb-zlib-base64-v1"
    assert fixture["source_commit"] == source_commit
    assert fixture["catalog_sha256"] == catalog_sha256
    path.write_bytes(zlib.decompress(base64.b64decode(fixture["payload"], validate=True)))
    con = duckdb.connect(str(path))
    assert schema_migrations.catalog_sha256(con) == fixture["catalog_sha256"]
    price_columns = {
        row[0] for row in con.execute(
            "SELECT column_name FROM duckdb_columns() WHERE table_name='prices'"
        ).fetchall()
    }
    if "first_fetched_at" in price_columns:
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume,first_fetched_at) "
            "VALUES ('SPY','2026-10-16',1,1,1,1,100,'2026-10-16')"
        )
    else:
        con.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES ('SPY','2026-10-16',1,1,1,1,100)"
        )
    if shape == "v2":
        con.execute(
            "INSERT INTO portfolios VALUES "
            "('legacy','Legacy','legacy','{}','2026-01-01',TRUE,100,100,"
            "'baseline_v1','account','legacy_cost','margin','private','halted',"
            "'massive_daily')"
        )
        con.execute(
            "INSERT INTO sim_fill_fees VALUES "
            "(7,'legacy_cost',1,2,3,4,5,6,7,8,9)"
        )
    con.close()


def _prepare(
    tmp_path: Path, monkeypatch, *, shape: str = "r15",
) -> tuple[Path, Path, dict, str]:
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    _database(database, shape)
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
    assert [item["migration_id"] for item in planned["pending"]] == [0, 1]

    applied = _apply(root, database, expected_catalog)
    again = _apply(root, database, expected_catalog)

    assert applied == {
        "status": "applied",
        "database_schema_id": 1,
        "catalog_sha256": schema_migrations.migrations()[0].module.EXPECTED_CATALOG_SHA256,
        "applied": [0, 1],
    }
    assert again == {
        "status": "current",
        "database_schema_id": 1,
        "catalog_sha256": schema_migrations.migrations()[0].module.EXPECTED_CATALOG_SHA256,
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
        0, SOURCE_COMMIT, expected_catalog,
        schema_migrations.migrations()[0].module.EXPECTED_CATALOG_SHA256,
        BACKUP_MANIFEST,
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


def test_same_count_value_change_makes_recovery_bundle_stale(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE prices (date DATE, ticker VARCHAR, volume BIGINT)")
    con.execute("INSERT INTO prices VALUES ('2026-10-16','SPY',100)")
    con.execute("CREATE TABLE jobs (id INTEGER, state VARCHAR)")
    con.execute(
        "CREATE TABLE portfolios (id VARCHAR,name VARCHAR,strategy VARCHAR,config VARCHAR,"
        "created DATE,active BOOLEAN,cash DOUBLE,initial_cash DOUBLE,execution_profile VARCHAR)"
    )
    con.execute("CREATE TABLE sim_orders (id INTEGER)")
    con.execute("CREATE TABLE sim_fills (id INTEGER)")
    con.execute(
        "CREATE TABLE sim_equity (portfolio_id VARCHAR,date DATE,equity DOUBLE,cash DOUBLE,"
        "n_positions INTEGER)"
    )
    con.execute("CREATE TABLE arbitrary_facts (id INTEGER, value VARCHAR)")
    con.execute("INSERT INTO arbitrary_facts VALUES (1,'before')")
    expected_pre = schema_migrations.catalog_sha256(con)
    before = canonical_sha256(
        backup_database.database_snapshot(
            con, con.execute("SELECT current_database()").fetchone()[0],
        )
    )
    con.execute("UPDATE arbitrary_facts SET value='after' WHERE id=1")
    con.close()
    monkeypatch.setattr(schema_migrations, "_source_commit", lambda _root: SOURCE_COMMIT)
    monkeypatch.setattr(
        backup_database, "verify_backup", lambda _bundle: {
            "manifest_sha256": BACKUP_MANIFEST,
            "database_snapshot_sha256": before,
            "source_database": {"kind": "repository-relative", "path": "store/market.duckdb"},
        },
    )

    with pytest.raises(schema_migrations.SchemaMigrationError, match="bundle is stale"):
        _apply(root, database, expected_pre)


def test_interrupted_statement_rolls_back_ledger_and_catalog(tmp_path, monkeypatch):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    migration = schema_migrations.Migration(
        migration_id=0,
        description="interruption fixture",
        sha256="d" * 64,
        statements=("CREATE TABLE migration_probe (id INTEGER)", "invalid SQL"),
        module=SimpleNamespace(EXPECTED_CATALOG_SHA256=expected_catalog),
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


@pytest.mark.parametrize("shape", ["pre-v2", "v2", "r15"])
def test_supported_deployed_shapes_reach_exact_baseline(tmp_path, monkeypatch, shape):
    root, database, _verified, expected_catalog = _prepare(
        tmp_path, monkeypatch, shape=shape,
    )

    result = _apply(root, database, expected_catalog)

    con = duckdb.connect(str(database), read_only=True)
    try:
        migration = schema_migrations.migrations()[0]
        catalog = schema_migrations.catalog(con)
        assert schema_migrations.catalog_sha256(con) == migration.module.EXPECTED_CATALOG_SHA256
        assert {row[1] for row in catalog["tables"]} == migration.module.EXPECTED_TABLES
        assert {row[1] for row in catalog["views"]} == migration.module.EXPECTED_VIEWS
        assert {row[1] for row in catalog["sequences"]} == migration.module.EXPECTED_SEQUENCES
        if shape == "v2":
            assert con.execute(
                "SELECT engine,cost_profile,account_type,visibility,status,price_source "
                "FROM portfolio_accounts WHERE portfolio_id='legacy'"
            ).fetchone() == (
                "account", "legacy_cost", "margin", "private", "halted", "massive_daily",
            )
            assert con.execute(
                "SELECT cat_fee,total_usd FROM sim_fill_fees WHERE order_id=7"
            ).fetchone() == (None, 9)
    finally:
        con.close()
    assert result["database_schema_id"] == 1


def test_fresh_empty_bootstrap_reaches_exact_baseline(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    duckdb.connect(str(database)).close()
    monkeypatch.setattr(schema_migrations, "_source_commit", lambda _root: SOURCE_COMMIT)
    con = duckdb.connect(str(database), read_only=True)
    try:
        expected_pre = schema_migrations.catalog_sha256(con)
    finally:
        con.close()

    result = schema_migrations.apply(
        database, None,
        expected_backup_manifest_sha256=schema_migrations.EMPTY_RECOVERY_SHA256,
        expected_source_commit=SOURCE_COMMIT,
        expected_pre_catalog_sha256=expected_pre,
        repo_root=root,
        fresh_empty=True,
    )

    assert result["catalog_sha256"] == (
        schema_migrations.migrations()[0].module.EXPECTED_CATALOG_SHA256
    )


def test_baseline_rejects_arbitrary_backed_up_catalog(tmp_path, monkeypatch):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE definitely_not_the_r15_catalog (id INTEGER)")
    con.close()
    # Make the supplied pre-identity and backup agree with the arbitrary shape.
    con = duckdb.connect(str(database), read_only=True)
    expected_catalog = schema_migrations.catalog_sha256(con)
    snapshot_sha = canonical_sha256(
        backup_database.database_snapshot(
            con, con.execute("SELECT current_database()").fetchone()[0],
        )
    )
    con.close()
    monkeypatch.setattr(
        backup_database, "verify_backup", lambda _bundle: {
            "manifest_sha256": BACKUP_MANIFEST,
            "database_snapshot_sha256": snapshot_sha,
            "source_database": {"kind": "repository-relative", "path": "store/market.duckdb"},
        },
    )

    with pytest.raises(schema_migrations.SchemaMigrationError, match="not a supported"):
        _apply(root, database, expected_catalog)


def test_baseline_rejects_matching_ad_hoc_catalog_without_fixture_helpers(
    tmp_path, monkeypatch,
):
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE prices (date DATE,ticker VARCHAR,volume BIGINT)")
    con.execute("INSERT INTO prices VALUES ('2026-10-16','SPY',100)")
    con.execute("CREATE TABLE jobs (id INTEGER,state VARCHAR)")
    con.execute(
        "CREATE TABLE portfolios (id VARCHAR,name VARCHAR,strategy VARCHAR,config VARCHAR,"
        "created DATE,active BOOLEAN,cash DOUBLE,initial_cash DOUBLE,execution_profile VARCHAR)"
    )
    con.execute("CREATE TABLE sim_orders (id INTEGER)")
    con.execute("CREATE TABLE sim_fills (id INTEGER)")
    con.execute(
        "CREATE TABLE sim_equity (portfolio_id VARCHAR,date DATE,equity DOUBLE,cash DOUBLE,"
        "n_positions INTEGER)"
    )
    con.execute("CREATE TABLE definitely_not_the_r15_catalog (id INTEGER)")
    expected_pre = schema_migrations.catalog_sha256(con)
    snapshot_sha = canonical_sha256(
        backup_database.database_snapshot(
            con, con.execute("SELECT current_database()").fetchone()[0],
        )
    )
    con.close()
    monkeypatch.setattr(schema_migrations, "_source_commit", lambda _root: SOURCE_COMMIT)
    monkeypatch.setattr(
        backup_database, "verify_backup", lambda _bundle: {
            "manifest_sha256": BACKUP_MANIFEST,
            "database_snapshot_sha256": snapshot_sha,
            "source_database": {"kind": "repository-relative", "path": "store/market.duckdb"},
        },
    )

    with pytest.raises(schema_migrations.SchemaMigrationError, match="not a supported"):
        _apply(root, database, expected_pre)


def test_baseline_rejects_synthetic_current_initializer_prefix(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    con = duckdb.connect(str(database))
    migration = schema_migrations.migrations()[0]
    for module_name, function_name in migration.module.BOOTSTRAP_CALLS[:7]:
        module = __import__(module_name, fromlist=[function_name])
        getattr(module, function_name)(con)
    expected_pre = schema_migrations.catalog_sha256(con)
    snapshot_sha = canonical_sha256(
        backup_database.database_snapshot(
            con, con.execute("SELECT current_database()").fetchone()[0],
        )
    )
    con.close()
    monkeypatch.setattr(schema_migrations, "_source_commit", lambda _root: SOURCE_COMMIT)
    monkeypatch.setattr(
        backup_database, "verify_backup", lambda _bundle: {
            "manifest_sha256": BACKUP_MANIFEST,
            "database_snapshot_sha256": snapshot_sha,
            "source_database": {"kind": "repository-relative", "path": "store/market.duckdb"},
        },
    )

    with pytest.raises(schema_migrations.SchemaMigrationError, match="not a supported"):
        _apply(root, database, expected_pre)


def test_versioned_connection_turns_runtime_initializers_into_assertions(
    tmp_path, monkeypatch,
):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    _apply(root, database, expected_catalog)
    con = engine_db.connect(database)
    try:
        before = schema_migrations.catalog_sha256(con)
        schema_migrations.migrations()[0].module.bootstrap(con)
        assert schema_migrations.catalog_sha256(con) == before
        con.execute(
            "INSERT INTO portfolios (id,name,active,cash,initial_cash,execution_profile) "
            "VALUES ('legacy-null','legacy-null',TRUE,1,NULL,NULL)"
        )
        from sim.schema import init_sim_schema
        with pytest.raises(engine_db.SchemaMigrationRequired, match="backfill"):
            init_sim_schema(con)
        assert con.execute(
            "SELECT initial_cash,execution_profile FROM portfolios WHERE id='legacy-null'"
        ).fetchone() == (None, None)
        with pytest.raises(engine_db.SchemaMigrationRequired, match="append-only"):
            con.execute("UPDATE bitemporal_facts SET revision=revision+1")
    finally:
        con.close()


def test_versioned_connection_rejects_unledgered_sequence_ddl(tmp_path):
    database = tmp_path / "versioned.duckdb"
    con = duckdb.connect(str(database))
    con.execute(
        "CREATE TABLE schema_migrations (migration_id INTEGER PRIMARY KEY, "
        "migration_sha256 VARCHAR, source_commit VARCHAR, applied_at TIMESTAMPTZ, "
        "pre_catalog_sha256 VARCHAR, post_catalog_sha256 VARCHAR, "
        "recovery_manifest_sha256 VARCHAR)"
    )
    con.close()

    raw = duckdb.connect(str(database))
    guarded = engine_db.GuardedConnection(raw, versioned=True)
    try:
        with pytest.raises(engine_db.SchemaMigrationRequired, match="explicit migration"):
            guarded.execute("CREATE SEQUENCE runtime_probe START 1")
        assert guarded.execute(
            "SELECT 1 FROM duckdb_sequences() WHERE sequence_name='runtime_probe'"
        ).fetchone() is None
    finally:
        guarded.close()


def test_versioned_connection_rejects_changed_view_definition(tmp_path):
    database = tmp_path / "versioned.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE schema_migrations (migration_id INTEGER)")
    con.execute("CREATE VIEW runtime_view AS SELECT 1 AS value")
    con.close()

    raw = duckdb.connect(str(database))
    guarded = engine_db.GuardedConnection(raw, versioned=True)
    try:
        with pytest.raises(engine_db.SchemaMigrationRequired, match="view definition"):
            guarded.execute("CREATE OR REPLACE VIEW runtime_view AS SELECT 2 AS value")
        assert guarded.execute("SELECT value FROM runtime_view").fetchone() == (1,)
    finally:
        guarded.close()


@pytest.mark.parametrize(
    "attempt",
    [
        lambda con: con.executemany("CREATE TABLE bypass_many (id INTEGER)", [()]),
        lambda con: con.sql("CREATE TABLE bypass_sql (id INTEGER)"),
        lambda con: con.from_query("CREATE TABLE bypass_query (id INTEGER)"),
        lambda con: con.execute("SELECT 1; CREATE TABLE bypass_multi (id INTEGER)"),
        lambda con: con.cursor().execute("CREATE TABLE bypass_cursor (id INTEGER)"),
        lambda con: con.duplicate().execute("CREATE TABLE bypass_duplicate (id INTEGER)"),
        lambda con: con.sql("SELECT 1").create("bypass_relation"),
        lambda con: con.execute("CREATE SCHEMA bypass_schema"),
    ],
)
def test_versioned_connection_blocks_every_persistent_ddl_surface(tmp_path, attempt):
    database = tmp_path / "versioned.duckdb"
    raw = duckdb.connect(str(database))
    raw.execute("CREATE TABLE schema_migrations (migration_id INTEGER)")
    guarded = engine_db.GuardedConnection(raw, versioned=True)
    try:
        with pytest.raises(engine_db.SchemaMigrationRequired, match="explicit migration"):
            attempt(guarded)
        assert guarded.execute(
            "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name LIKE 'bypass_%'"
        ).fetchone() == (0,)
    finally:
        guarded.close()


def test_baseline_hash_binds_runtime_initializer_source(monkeypatch):
    before = schema_migrations.migrations()[0].sha256
    original = Path.read_bytes

    def changed_dependency(path):
        content = original(path)
        if path.name == "bitemporal_facts.py":
            return content + b"\n# changed dependency\n"
        return content

    monkeypatch.setattr(Path, "read_bytes", changed_dependency)

    assert schema_migrations.migrations()[0].sha256 != before


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("migration_sha256", "f" * 64, "hash does not match"),
        ("source_commit", "not-a-git-commit", "source commit is invalid"),
    ],
)
def test_one_shared_runtime_verifier_rejects_false_ledger_identity(
    tmp_path, monkeypatch, column, value, message,
):
    root, database, _verified, expected_catalog = _prepare(tmp_path, monkeypatch)
    _apply(root, database, expected_catalog)
    con = duckdb.connect(str(database))
    try:
        con.execute(f"UPDATE schema_migrations SET {column}=?", [value])
        with pytest.raises(schema_migrations.SchemaMigrationError, match=message):
            schema_migrations.require_compatible_schema(con)
        with pytest.raises(engine_db.SchemaMigrationRequired, match=message):
            engine_db.require_compatible_database_schema(con)
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
