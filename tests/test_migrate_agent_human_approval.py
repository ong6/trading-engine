"""The human-approval migration is backup-gated, scoped, and rollback-safe."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import broker_human_paper_approval_store
from tools import backup_database, migrate_agent_human_approval


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
        migrate_agent_human_approval.backup_database,
        "verify_backup",
        lambda _path: verified,
    )
    return root, database, verified


def test_migration_creates_only_empty_human_approval_table(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    before = _snapshot(database)

    result = migrate_agent_human_approval.migrate(
        database,
        tmp_path / "backup",
        verified["manifest_sha256"],
        repo_root=root,
    )

    after = _snapshot(database)
    assert result["status"] == "human_approval_schema_installed"
    assert result["created_table"] == broker_human_paper_approval_store.TABLE
    assert result["retained_table"] is None
    assert result["approval_observation_count"] == 0
    assert result["trust_source_loader_implemented"] is False
    assert result["human_order_approval_granted"] is False
    assert result["production_authority_consumption_implemented"] is False
    assert result["paper_order_route"] == "absent"
    assert result["submission_authority"] == "none"
    assert after["table_count"] == before["table_count"] + 1
    assert after["active_portfolios_sha256"] == before["active_portfolios_sha256"]
    assert after["row_counts"] == {
        **before["row_counts"],
        f"main.{broker_human_paper_approval_store.TABLE}": 0,
    }


def test_migration_is_idempotent_with_fresh_matching_backup(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    migrate_agent_human_approval.migrate(
        database,
        tmp_path / "backup",
        verified["manifest_sha256"],
        repo_root=root,
    )
    current = _snapshot(database)
    current_backup = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_human_approval.backup_database,
        "verify_backup",
        lambda _path: current_backup,
    )

    result = migrate_agent_human_approval.migrate(
        database,
        tmp_path / "backup-2",
        current_backup["manifest_sha256"],
        repo_root=root,
    )

    assert result["created_table"] is None
    assert result["retained_table"] == broker_human_paper_approval_store.TABLE
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
            migrate_agent_human_approval.backup_database,
            "verify_backup",
            lambda _path: supplied,
        )

    with pytest.raises(
        migrate_agent_human_approval.HumanApprovalMigrationError,
        match=message,
    ):
        migrate_agent_human_approval.migrate(
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
    assert broker_human_paper_approval_store.TABLE not in tables


def test_migration_rejects_incompatible_existing_schema(tmp_path, monkeypatch):
    root, database, _verified = _setup(tmp_path, monkeypatch)
    con = duckdb.connect(str(database))
    con.execute(
        f"CREATE TABLE {broker_human_paper_approval_store.TABLE} "
        "(observation_sequence VARCHAR)"
    )
    con.close()
    current = _snapshot(database)
    verified = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_human_approval.backup_database,
        "verify_backup",
        lambda _path: verified,
    )

    with pytest.raises(
        migrate_agent_human_approval.HumanApprovalMigrationError,
        match="existing human approval schema is incompatible",
    ):
        migrate_agent_human_approval.migrate(
            database,
            tmp_path / "backup",
            verified["manifest_sha256"],
            repo_root=root,
        )


def test_migration_rejects_nonempty_existing_ledger(tmp_path, monkeypatch):
    root, database, _verified = _setup(tmp_path, monkeypatch)
    con = duckdb.connect(str(database))
    broker_human_paper_approval_store.init_schema(con)
    values = [1] + [
        f"value-{index}"
        for index in range(1, len(broker_human_paper_approval_store._COLUMNS))
    ]
    values[-1] = "f" * 64
    con.execute(
        f"INSERT INTO {broker_human_paper_approval_store.TABLE} VALUES "
        f"({', '.join('?' for _ in broker_human_paper_approval_store._COLUMNS)})",
        values,
    )
    con.close()
    current = _snapshot(database)
    verified = _verified_backup(root, database, current)
    monkeypatch.setattr(
        migrate_agent_human_approval.backup_database,
        "verify_backup",
        lambda _path: verified,
    )

    with pytest.raises(
        migrate_agent_human_approval.HumanApprovalMigrationError,
        match="must be empty",
    ):
        migrate_agent_human_approval.migrate(
            database,
            tmp_path / "backup",
            verified["manifest_sha256"],
            repo_root=root,
        )


def test_post_migration_scope_failure_rolls_back(tmp_path, monkeypatch):
    root, database, verified = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        migrate_agent_human_approval,
        "_require_scoped_change",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            migrate_agent_human_approval.HumanApprovalMigrationError(
                "forced scope failure"
            )
        ),
    )

    with pytest.raises(
        migrate_agent_human_approval.HumanApprovalMigrationError,
        match="forced scope failure",
    ):
        migrate_agent_human_approval.migrate(
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
    assert broker_human_paper_approval_store.TABLE not in tables
