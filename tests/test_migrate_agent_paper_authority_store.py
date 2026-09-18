"""The paper-authority store migration is backup-gated and rollback-safe."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    broker_paper_consumption_store,
    broker_paper_startup_store,
)
from tools import backup_database, migrate_agent_paper_authority_store


def _database(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE prices (date DATE, ticker VARCHAR, volume BIGINT)")
    con.execute("INSERT INTO prices VALUES (DATE '2026-09-11', 'SPY', 1000)")
    con.execute("CREATE TABLE jobs (id INTEGER, state VARCHAR)")
    con.execute("INSERT INTO jobs VALUES (1, 'done')")
    con.execute(
        "CREATE TABLE portfolios ("
        "id VARCHAR PRIMARY KEY, name VARCHAR, strategy VARCHAR, config VARCHAR, "
        "created DATE, active BOOLEAN, cash DOUBLE, initial_cash DOUBLE, "
        "execution_profile VARCHAR)"
    )
    con.execute(
        "INSERT INTO portfolios VALUES "
        "('dual_momentum', 'Dual Momentum', 'dual_momentum', '{}', "
        "DATE '2026-01-01', TRUE, 39000, 39000, 'baseline_v1')"
    )
    con.execute(
        "CREATE TABLE sim_orders ("
        "id BIGINT PRIMARY KEY, portfolio_id VARCHAR, ticker VARCHAR, side VARCHAR, "
        "qty DOUBLE, signal_date DATE, status VARCHAR, reject_reason VARCHAR)"
    )
    con.execute(
        "CREATE TABLE sim_fills ("
        "order_id BIGINT, portfolio_id VARCHAR, ticker VARCHAR, side VARCHAR, "
        "qty DOUBLE, fill_date DATE, open_px DOUBLE, fill_px DOUBLE, "
        "slippage_bps DOUBLE, cost_bps DOUBLE)"
    )
    con.execute(
        "CREATE TABLE sim_equity ("
        "portfolio_id VARCHAR, date DATE, equity DOUBLE, cash DOUBLE, "
        "n_positions INTEGER, PRIMARY KEY (portfolio_id, date))"
    )
    con.close()


def _snapshot(path: Path) -> dict:
    con = duckdb.connect(str(path), read_only=True)
    try:
        name = con.execute("SELECT current_database()").fetchone()[0]
        return backup_database.database_snapshot(con, name)
    finally:
        con.close()


def _verified_backup(root: Path, database: Path, snapshot: dict) -> dict:
    return {
        "status": "ok",
        "bundle": str(root.parent / "backup"),
        "manifest_sha256": "a" * 64,
        "database_sha256": "b" * 64,
        "database_size_bytes": database.stat().st_size,
        "database_snapshot_sha256": canonical_sha256(snapshot),
        "source_database": {
            "kind": "repository-relative",
            "path": database.relative_to(root).as_posix(),
        },
        "table_count": snapshot["table_count"],
        "evidence_file_count": 0,
        "operational_artifact_count": 0,
        "operational_control_count": 0,
    }


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict]:
    root = tmp_path / "repo"
    database = root / "store" / "market.duckdb"
    database.parent.mkdir(parents=True)
    _database(database)
    snapshot = _snapshot(database)
    verified = _verified_backup(root, database, snapshot)
    monkeypatch.setattr(
        migrate_agent_paper_authority_store.backup_database,
        "verify_backup",
        lambda _path: verified,
    )
    return root, database, verified


def test_migration_creates_only_empty_paper_authority_store(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    before = _snapshot(database)

    result = migrate_agent_paper_authority_store.migrate(
        database,
        tmp_path / "backup",
        verified["manifest_sha256"],
        repo_root=root,
    )

    after = _snapshot(database)
    assert result["status"] == "paper_authority_store_schema_installed"
    assert result["created_tables"] == [
        broker_paper_startup_store.RETENTION_TABLE,
        broker_paper_consumption_store.RISK_EVIDENCE_TABLE,
    ]
    assert result["retained_tables"] == []
    assert result["retained_event_count"] == 0
    assert result["retained_risk_evaluation_count"] == 0
    assert result["activation_writer_implemented"] is True
    assert result["atomic_pre_call_writer_implemented"] is True
    assert result["runtime_activation_implemented"] is False
    assert result["adapter_integration_implemented"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    assert after["table_count"] == before["table_count"] + 2
    assert after["active_portfolios_sha256"] == before["active_portfolios_sha256"]
    assert after["row_counts"] == {
        **before["row_counts"],
        f"main.{broker_paper_startup_store.RETENTION_TABLE}": 0,
        f"main.{broker_paper_consumption_store.RISK_EVIDENCE_TABLE}": 0,
    }


def test_migration_is_idempotent_with_fresh_matching_backup(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    migrate_agent_paper_authority_store.migrate(
        database,
        tmp_path / "backup",
        verified["manifest_sha256"],
        repo_root=root,
    )
    current = _snapshot(database)
    current_backup = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_paper_authority_store.backup_database,
        "verify_backup",
        lambda _path: current_backup,
    )

    result = migrate_agent_paper_authority_store.migrate(
        database,
        tmp_path / "backup-2",
        current_backup["manifest_sha256"],
        repo_root=root,
    )

    assert result["created_tables"] == []
    assert result["retained_tables"] == [
        broker_paper_startup_store.RETENTION_TABLE,
        broker_paper_consumption_store.RISK_EVIDENCE_TABLE,
    ]
    assert _snapshot(database) == current


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("manifest_sha256", "b" * 64, "manifest identity"),
        (
            "source_database",
            {"kind": "repository-relative", "path": "store/other.duckdb"},
            "different source database",
        ),
        ("database_snapshot_sha256", "c" * 64, "does not match"),
    ],
)
def test_migration_rejects_wrong_or_stale_backup(
    tmp_path,
    monkeypatch,
    field,
    value,
    message,
):
    root, database, verified = _setup(tmp_path, monkeypatch)
    supplied = dict(verified)
    if field == "manifest_sha256":
        expected_manifest = value
    else:
        supplied[field] = value
        expected_manifest = verified["manifest_sha256"]
        monkeypatch.setattr(
            migrate_agent_paper_authority_store.backup_database,
            "verify_backup",
            lambda _path: supplied,
        )

    with pytest.raises(
        migrate_agent_paper_authority_store.PaperAuthorityStoreMigrationError,
        match=message,
    ):
        migrate_agent_paper_authority_store.migrate(
            database,
            tmp_path / "backup",
            expected_manifest,
            repo_root=root,
        )

    con = duckdb.connect(str(database), read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    finally:
        con.close()
    assert broker_paper_startup_store.RETENTION_TABLE not in tables
    assert broker_paper_consumption_store.RISK_EVIDENCE_TABLE not in tables


def test_migration_rejects_incompatible_existing_schema(tmp_path, monkeypatch):
    root, database, _verified = _setup(tmp_path, monkeypatch)
    con = duckdb.connect(str(database))
    con.execute(
        f"CREATE TABLE {broker_paper_startup_store.RETENTION_TABLE} "
        "(global_sequence VARCHAR)"
    )
    con.close()
    current = _snapshot(database)
    verified = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_paper_authority_store.backup_database,
        "verify_backup",
        lambda _path: verified,
    )

    with pytest.raises(
        migrate_agent_paper_authority_store.PaperAuthorityStoreMigrationError,
        match="existing paper authority store schema is incompatible",
    ):
        migrate_agent_paper_authority_store.migrate(
            database,
            tmp_path / "backup",
            verified["manifest_sha256"],
            repo_root=root,
        )


def test_migration_rejects_incompatible_risk_evidence_schema(
    tmp_path,
    monkeypatch,
):
    root, database, _verified = _setup(tmp_path, monkeypatch)
    con = duckdb.connect(str(database))
    con.execute(
        f"CREATE TABLE {broker_paper_consumption_store.RISK_EVIDENCE_TABLE} "
        "(idempotency_key BIGINT)"
    )
    con.close()
    current = _snapshot(database)
    verified = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_paper_authority_store.backup_database,
        "verify_backup",
        lambda _path: verified,
    )

    with pytest.raises(
        migrate_agent_paper_authority_store.PaperAuthorityStoreMigrationError,
        match="existing paper authority store schema is incompatible",
    ):
        migrate_agent_paper_authority_store.migrate(
            database,
            tmp_path / "backup",
            verified["manifest_sha256"],
            repo_root=root,
        )


def test_migration_rejects_nonempty_existing_store(tmp_path, monkeypatch):
    root, database, _verified = _setup(tmp_path, monkeypatch)
    con = duckdb.connect(str(database))
    migrate_agent_paper_authority_store._create_empty_schema(con)
    values = []
    for name, kind in broker_paper_startup_store.RETENTION_COLUMNS:
        if name == "prior_global_row_sha256":
            values.append(None)
        elif kind in {"BIGINT", "INTEGER"}:
            values.append(1)
        else:
            values.append("value")
    con.execute(
        f"INSERT INTO {broker_paper_startup_store.RETENTION_TABLE} VALUES "
        f"({', '.join('?' for _ in values)})",
        values,
    )
    con.close()
    current = _snapshot(database)
    verified = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_paper_authority_store.backup_database,
        "verify_backup",
        lambda _path: verified,
    )

    with pytest.raises(
        migrate_agent_paper_authority_store.PaperAuthorityStoreMigrationError,
        match="must be empty",
    ):
        migrate_agent_paper_authority_store.migrate(
            database,
            tmp_path / "backup",
            verified["manifest_sha256"],
            repo_root=root,
        )


def test_post_migration_scope_failure_rolls_back(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        migrate_agent_paper_authority_store,
        "_require_scoped_change",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            migrate_agent_paper_authority_store.PaperAuthorityStoreMigrationError(
                "forced scope failure"
            )
        ),
    )

    with pytest.raises(
        migrate_agent_paper_authority_store.PaperAuthorityStoreMigrationError,
        match="forced scope failure",
    ):
        migrate_agent_paper_authority_store.migrate(
            database,
            tmp_path / "backup",
            verified["manifest_sha256"],
            repo_root=root,
        )

    con = duckdb.connect(str(database), read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    finally:
        con.close()
    assert broker_paper_startup_store.RETENTION_TABLE not in tables
    assert broker_paper_consumption_store.RISK_EVIDENCE_TABLE not in tables
