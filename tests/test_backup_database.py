"""Transactional local database backup and restore verification."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from engine import p15_evaluation, schema_migrations
from engine.lib import db as engine_db
from sim import schema as sim_schema
from tools import backup_database, publish_snapshot


def test_bundle_tree_identity_follows_only_its_opened_root(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "data").write_text("retained")
    (root / "child-link").symlink_to(root / "data")
    descriptor = tmp_path / "descriptor"
    descriptor.symlink_to(root, target_is_directory=True)
    identity = backup_database._bundle_tree_identity(descriptor)
    value = root.stat()
    assert identity["."] == (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                             value.st_mtime_ns, value.st_ctime_ns)
    assert stat.S_ISLNK(identity["child-link"][2])


def _source_database(path: Path, *, generation: bool = False) -> None:
    connection = duckdb.connect(str(path))
    if generation:
        schema_migrations.migrations()[0].module.bootstrap(connection)
        connection.execute(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume,first_fetched_at) "
            "VALUES ('SPY','2026-09-10',1,1,1,1,1000,'2026-09-10'),"
            "('QQQ','2026-09-09',1,1,1,1,1000,'2026-09-09')"
        )
        connection.execute(
            "INSERT INTO jobs (id,state) VALUES (1,'done'),(2,'failed')"
        )
        connection.execute(
            "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,"
            "initial_cash,execution_profile) VALUES "
            "('paper','Paper','spy_benchmark','{}','2026-01-01',TRUE,100,100,'baseline_v1')"
        )
        connection.execute(
            "INSERT INTO sim_equity (portfolio_id,date,equity,cash,n_positions) "
            "VALUES ('paper','2026-09-10',100,100,0)"
        )
        connection.execute(
            "INSERT INTO screen_results "
            "(run_date,ticker,passes_template,new_today,universe_policy) VALUES "
            "('2026-09-10','SPY',TRUE,TRUE,'all'),"
            "('2026-09-10','QQQ',FALSE,FALSE,'all')"
        )
        connection.close()
        return
    connection.execute("BEGIN TRANSACTION")
    connection.execute("CREATE TABLE prices (date DATE, ticker VARCHAR, volume BIGINT)")
    connection.execute(
        "INSERT INTO prices VALUES ('2026-09-10', 'SPY', 1000), ('2026-09-09', 'QQQ', 1000)"
    )
    connection.execute("CREATE TABLE jobs (id INTEGER, state VARCHAR)")
    connection.execute("INSERT INTO jobs VALUES (1, 'done'), (2, 'failed')")
    connection.execute(
        "CREATE TABLE portfolios (id VARCHAR, name VARCHAR, strategy VARCHAR, config VARCHAR, "
        "created DATE, active BOOLEAN, cash DOUBLE, initial_cash DOUBLE, "
        "execution_profile VARCHAR)"
    )
    connection.execute(
        "INSERT INTO portfolios VALUES "
        "('paper', 'Paper', 'spy_benchmark', '{}', '2026-01-01', TRUE, 100, 100, "
        "'baseline_v1')"
    )
    for table in ("sim_orders", "sim_fills"):
        connection.execute(f"CREATE TABLE {table} (id INTEGER)")
    connection.execute(
        "CREATE TABLE sim_equity (portfolio_id VARCHAR, date DATE, equity DOUBLE, "
        "cash DOUBLE, n_positions INTEGER)"
    )
    connection.execute("INSERT INTO sim_equity VALUES ('paper', '2026-09-10', 100, 100, 0)")
    connection.execute(
        "CREATE TABLE sim_positions (portfolio_id VARCHAR, ticker VARCHAR, qty DOUBLE)"
    )
    connection.execute(
        "CREATE TABLE screen_results (run_date DATE, ticker VARCHAR, passes_template BOOLEAN, "
        "new_today BOOLEAN, universe_policy VARCHAR)"
    )
    connection.execute(
        "INSERT INTO screen_results VALUES "
        "('2026-09-10', 'SPY', TRUE, TRUE, 'all'), "
        "('2026-09-10', 'QQQ', FALSE, FALSE, 'all')"
    )
    connection.execute("CREATE INDEX jobs_state_idx ON jobs(state)")
    connection.execute("COMMIT")
    connection.close()


def _stamp_schema(database: Path) -> None:
    connection = duckdb.connect(str(database))
    catalog_hash = schema_migrations.catalog_sha256(connection)
    migration = schema_migrations.migrations()[0]
    assert catalog_hash == migration.module.EXPECTED_CATALOG_SHA256
    connection.execute(
        "CREATE TABLE schema_migrations (migration_id INTEGER PRIMARY KEY, "
        "migration_sha256 VARCHAR, source_commit VARCHAR, applied_at TIMESTAMPTZ, "
        "pre_catalog_sha256 VARCHAR, post_catalog_sha256 VARCHAR, "
        "recovery_manifest_sha256 VARCHAR)"
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (0, ?, ?, now(), ?, ?, ?)",
        [migration.sha256, "a" * 40, catalog_hash, catalog_hash, "b" * 64],
    )
    connection.close()


def _repo(tmp_path: Path, *, generation: bool = False) -> tuple[Path, Path]:
    root = tmp_path / "repo's copy"
    root.mkdir()
    source = root / "store" / "market.duckdb"
    source.parent.mkdir()
    _source_database(source, generation=generation)
    for relative in backup_database.EVIDENCE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"path": relative}) + "\n")
    operational = {
        "data/_meta.json": json.dumps(
            {
                "screen_date": "2026-09-10",
                "regime": "risk-on",
                "screened": 2,
                "passing_count": 1,
                "new_today_count": 1,
                "universe_policy": "all",
            }
        )
        + "\n",
        "logs/friday-postflight.json": '{"status":"fixture"}\n',
        "data/screens/latest.md": (
            "# Screen — 2026-09-10  (universe: 2 · passing: 1 · new today: 1 · "
            "regime: risk-on · policy: all)\n"
        ),
        "data/screens/2026-09-10.md": (
            "# Screen — 2026-09-10  (universe: 2 · passing: 1 · new today: 1 · "
            "regime: risk-on · policy: all)\n"
        ),
        "data/screens/2026-09-10.csv": "ticker,passes_template\nSPY,true\nQQQ,false\n",
        "data/reports/league.md": (
            "# Paper League — 2026-09-10\n\n"
            "| # | Portfolio | Inception | Equity | Total ret | vs SPY | Max DD | "
            "Open | Fills | Last 5d |\n"
            "|---|---|---|---|---|---|---|---|---|---|\n"
            "| 1 | Paper | 2026-01-01 | $100 | +0.00% | · | +0.00% | 0 | 0 | · |\n"
        ),
        "data/reports/league.csv": (
            "portfolio_id,date,equity\npaper,2026-09-10,100.0\n"
        ),
    }
    for relative, content in operational.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root, source


def _rewrite_manifest(destination: Path, update) -> None:
    manifest = destination / backup_database.MANIFEST_FILENAME
    payload = json.loads(manifest.read_text())
    payload.pop("manifest_sha256")
    update(payload)
    payload["manifest_sha256"] = backup_database.canonical_sha256(payload)
    manifest.write_text(json.dumps(payload))


def _rehash_artifact(destination: Path, relative: str) -> None:
    artifact = destination / "evidence" / relative

    def update(payload):
        record = payload["operational_artifacts"][relative]
        record["size_bytes"] = artifact.stat().st_size
        record["sha256"] = backup_database._sha256(artifact)

    _rewrite_manifest(destination, update)


@pytest.fixture(autouse=True)
def release_summary(monkeypatch):
    monkeypatch.setattr(
        backup_database,
        "_release_summary",
        lambda *_args: {
            "status": "non-releasable",
            "release_eligible": False,
            "manifest_sha256": "a" * 64,
            "git_sha": "b" * 40,
            "working_tree_sha256": "c" * 64,
            "research_runtime": {"sha256": "d" * 64, "file_count": 1},
        },
    )


def test_create_and_verify_transactional_bundle(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"

    created = backup_database.create_backup(root, source, destination)
    verified = backup_database.verify_backup(destination)

    assert created == verified
    assert created["status"] == "ok"
    assert created["table_count"] == 8
    assert len(created["database_snapshot_sha256"]) == 64
    assert created["source_database"] == {
        "kind": "repository-relative",
        "path": "store/market.duckdb",
    }
    assert created["evidence_file_count"] == len(backup_database.EVIDENCE_FILES)
    assert created["operational_artifact_count"] == 7
    assert created["operational_control_count"] == 0
    manifest = json.loads((destination / backup_database.MANIFEST_FILENAME).read_text())
    assert manifest["schema_version"] == 3
    assert manifest["operational_controls"] == {}
    for relative in backup_database._operational_files("2026-09-10"):
        source_file = root / relative
        bundled = destination / "evidence" / relative
        assert bundled.read_bytes() == source_file.read_bytes()
        assert stat.S_IMODE(bundled.stat().st_mode) == 0o600
    for directory in (path for path in destination.rglob("*") if path.is_dir()):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((destination / backup_database.DATABASE_FILENAME).stat().st_mode) == 0o600
    assert stat.S_IMODE((destination / backup_database.MANIFEST_FILENAME).stat().st_mode) == 0o600
    connection = duckdb.connect(
        str(destination / backup_database.DATABASE_FILENAME), read_only=True
    )
    assert connection.execute("SELECT ticker FROM prices ORDER BY date").fetchall() == [
        ("QQQ",),
        ("SPY",),
    ]
    connection.close()


def test_create_copies_file_bytes_instead_of_a_logical_database_copy(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    monkeypatch.setattr(
        backup_database, "_copy_database",
        lambda *_args: (_ for _ in ()).throw(AssertionError("COPY FROM DATABASE used")),
    )

    created = backup_database.create_backup(root, source, destination)

    assert created["status"] == "ok"
    assert (destination / backup_database.DATABASE_FILENAME).read_bytes() == (
        source.read_bytes()
    )


def test_create_replays_a_pending_wal_into_the_copied_file(tmp_path):
    root, source = _repo(tmp_path)
    writer = (
        "import duckdb, os, sys\n"
        "c = duckdb.connect(sys.argv[1])\n"
        "c.execute(\"SET checkpoint_threshold='1TB'\")\n"
        "c.execute(\"INSERT INTO prices VALUES ('2026-09-01','IWM',5)\")\n"
        "os._exit(0)\n"
    )
    subprocess.run([sys.executable, "-c", writer, str(source)], check=True)
    assert source.with_name(f"{source.name}.wal").is_file()
    destination = tmp_path / "outside" / "snapshot"

    created = backup_database.create_backup(root, source, destination)

    assert created == backup_database.verify_backup(destination)
    assert sorted(path.name for path in destination.iterdir()) == sorted([
        backup_database.DATABASE_FILENAME, "evidence", backup_database.MANIFEST_FILENAME,
    ])
    connection = duckdb.connect(
        str(destination / backup_database.DATABASE_FILENAME), read_only=True
    )
    assert connection.execute("SELECT ticker FROM prices ORDER BY date").fetchall() == [
        ("IWM",), ("QQQ",), ("SPY",),
    ]
    connection.close()


def test_create_uses_fresh_latest_snapshot_instead_of_live_store(tmp_path, monkeypatch):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    _stamp_schema(source)
    published = publish_snapshot.publish_snapshot(root, source)
    destination = tmp_path / "outside" / "snapshot"

    backup_database.create_backup(root, source, destination)

    manifest = json.loads((destination / backup_database.MANIFEST_FILENAME).read_text())
    assert manifest["source_database"] == {
        "kind": "repository-relative",
        "path": "store/market.duckdb",
    }
    assert manifest["schema_version"] == 4
    assert manifest["generation"]["manifest_sha256"] == published["manifest_sha256"]


def test_initializer_edit_after_migration_keeps_writers_publish_and_backup_open(
    tmp_path, monkeypatch,
):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    _stamp_schema(source)
    original = Path.read_bytes
    edited = {"db.py", "schema.py", "job_resolutions.py", "agent_store.py"}

    def later_commit(path):  # a comment-only edit to initializer modules after deploy
        content = original(path)
        return content + b"\n# later edit\n" if path.name in edited else content

    monkeypatch.setattr(Path, "read_bytes", later_commit)

    con = engine_db.connect(source, wait_s=0)
    try:
        con.execute("INSERT INTO jobs (id,state) VALUES (9,'done')")
    finally:
        con.close()
    published = publish_snapshot.publish_snapshot(root, source)
    created = backup_database.create_backup(root, source, tmp_path / "outside" / "bundle")

    assert published["row_counts"]["main.jobs"] == 3
    assert created["status"] == "ok"


def test_generation_backup_checks_primary_schema_and_restores_cold_rows(
    tmp_path, monkeypatch,
):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    connection = duckdb.connect(str(source))
    connection.execute(
        "INSERT INTO intraday_prices VALUES "
        "('SPY','2026-09-10 14:30:00','1m',1,2,1,2,10,'fixture','2026-09-10')"
    )
    connection.close()
    _stamp_schema(source)
    published = publish_snapshot.publish_snapshot(root, source)
    destination = tmp_path / "outside" / "generation-backup"
    with duckdb.connect(str(source), read_only=True) as primary:
        primary_rows = primary.execute(
            "SELECT * FROM intraday_prices ORDER BY ticker, ts, interval"
        ).fetchall()
        primary_snapshot = backup_database.database_snapshot(
            primary, primary.execute("SELECT current_database()").fetchone()[0]
        )
    created = backup_database.create_backup(root, source, destination)

    restored = duckdb.connect(
        str(destination / backup_database.DATABASE_FILENAME), read_only=True
    )
    try:
        assert restored.execute(
            "SELECT * FROM intraday_prices ORDER BY ticker, ts, interval"
        ).fetchall() == primary_rows
        restored_snapshot = backup_database.database_snapshot(
            restored, restored.execute("SELECT current_database()").fetchone()[0]
        )
    finally:
        restored.close()
    assert restored_snapshot == primary_snapshot
    assert created["status"] == "ok"
    manifest = json.loads((destination / backup_database.MANIFEST_FILENAME).read_text())
    assert manifest["generation"]["manifest_sha256"] == published["manifest_sha256"]


def test_versioned_database_without_generation_refuses_primary_fallback(tmp_path):
    root, source = _repo(tmp_path, generation=True)
    _stamp_schema(source)

    with pytest.raises(backup_database.BackupError, match="no valid published generation"):
        backup_database.create_backup(
            root, source, tmp_path / "outside" / "missing-generation",
        )


def test_generation_backup_refuses_commit_retained_in_held_writer_wal(
    tmp_path, monkeypatch,
):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    _stamp_schema(source)
    publish_snapshot.publish_snapshot(root, source)
    destination = tmp_path / "outside" / "stale-generation"
    writer = duckdb.connect(str(source))
    try:
        writer.execute("UPDATE prices SET volume=999 WHERE ticker='SPY'")
        assert source.with_name(f"{source.name}.wal").is_file()
        with pytest.raises(backup_database.BackupError, match="live primary schema"):
            backup_database.create_backup(root, source, destination)
    finally:
        writer.close()

    assert not destination.exists()


def _alternate_relation(con, factory, tmp_path):
    if factory == "from_df":
        return con.from_df(pd.DataFrame({"id": [1]}))
    if factory == "values":
        return con.values([1])
    path = tmp_path / "relation.csv"
    path.write_text("id\n1\n")
    return con.read_csv(str(path))


@pytest.mark.parametrize("factory", ["from_df", "values", "read_csv"])
def test_backup_refuses_live_catalog_drift_from_alternate_relation_factory(
    tmp_path, monkeypatch, capsys, factory,
):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    _stamp_schema(source)
    publish_snapshot.publish_snapshot(root, source)
    writer = engine_db.connect(source)
    try:
        _alternate_relation(writer, factory, tmp_path).create(f"bypass_{factory}")
    finally:
        writer.close()
    destination = tmp_path / "outside" / f"catalog-drift-{factory}"

    status = backup_database.main([
        "--repo-root", str(root), "create", str(destination), "--source", str(source),
    ])

    output = json.loads(capsys.readouterr().out)
    assert status == 1
    assert output["status"] == "failed"
    assert "catalog changed outside" in output["reason"]
    assert not destination.exists()


def test_remote_restore_interface_binds_generation_and_full_restore_checks():
    interface = backup_database.REMOTE_RESTORE_INTERFACE
    assert interface["rpo"] == {"config_key": "rpo_hours", "default": 24, "minimum": 1}
    assert interface["input_manifest_schema_version"] == 4
    assert "remote_commit" in interface["required_restore_receipt_fields"]
    assert "generation_manifest_sha256" in interface["required_restore_receipt_fields"]
    assert "semantic_health_sha256" in interface["required_restore_receipt_fields"]
    assert "full logical checksum" in interface["partition_contract"]["restore"]
    assert "no new timer" in interface["scheduler"]
    assert callable(backup_database.write_remote_restore_plan)
    assert callable(backup_database.remote_restore_drill)


def test_remote_restore_drill_fetches_exact_commit_and_cleans_databases(
    tmp_path, monkeypatch,
):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    _stamp_schema(source)
    publish_snapshot.publish_snapshot(root, source)
    bundle = tmp_path / "bundle"
    backup_database.create_backup(root, source, bundle)
    remote = tmp_path / "remote"
    remote.mkdir()
    shutil.copytree(bundle, remote / "engine-bundle")
    research = remote / "research.duckdb"
    con = duckdb.connect(str(research))
    con.execute("CREATE TABLE facts (id INTEGER, value VARCHAR)")
    con.execute("INSERT INTO facts VALUES (1, 'verified')")
    con.close()
    plan = backup_database.write_remote_restore_plan(
        remote, remote / "engine-bundle", [research],
    )
    assert plan["research_databases"][0]["sha256"] == backup_database._sha256(research)
    subprocess.run(("git", "init", "-q"), cwd=remote, check=True)
    subprocess.run(("git", "add", "."), cwd=remote, check=True)
    subprocess.run(
        ("git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "backup fixture"),
        cwd=remote, check=True,
    )
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=remote, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    scratch = tmp_path / "scratch"
    receipt_path = tmp_path / "receipt.json"

    receipt = backup_database.remote_restore_drill(
        remote.resolve().as_uri(), commit, receipt_path, scratch_parent=scratch,
    )

    assert receipt["remote_commit"] == commit
    assert json.loads(receipt_path.read_text()) == receipt
    assert list(scratch.iterdir()) == []


def test_sequence_state_survives_generations_restore_and_next_migration(
    tmp_path, monkeypatch,
):
    root, source = _repo(tmp_path, generation=True)
    monkeypatch.setattr(backup_database, "MIN_FREE_BYTES", 0)
    _stamp_schema(source)
    for offset in range(2):
        con = duckdb.connect(str(source))
        order_id = sim_schema.next_order_id(con)
        con.execute(
            "INSERT INTO sim_orders (id,status) VALUES (?, 'pending')", [order_id]
        )
        con.close()
        publish_snapshot.publish_snapshot(root, source, now=datetime(
            2026, 10, 2, 12, 0, offset, tzinfo=timezone.utc,
        ))
    destination = tmp_path / "outside" / "generation-backup"
    created = backup_database.create_backup(root, source, destination)
    restored_path = destination / backup_database.DATABASE_FILENAME
    restored = duckdb.connect(str(restored_path))
    try:
        assert schema_migrations.require_compatible_schema(restored)["database_schema_id"] == 0
        assert sim_schema.next_order_id(restored) == 3
    finally:
        restored.close()

    monkeypatch.setattr(schema_migrations, "_source_commit", lambda _root: "a" * 40)
    con = duckdb.connect(str(source), read_only=True)
    expected_pre = schema_migrations.catalog_sha256(con)
    con.close()
    migrated = schema_migrations.apply(
        source,
        destination,
        expected_backup_manifest_sha256=created["manifest_sha256"],
        expected_source_commit="a" * 40,
        expected_pre_catalog_sha256=expected_pre,
        repo_root=root,
        target_schema_id=1,
    )
    assert migrated["applied"] == [1]


def test_backup_restores_persisted_p15_look_with_external_anchor(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    configured_data = tmp_path / "configured-data"
    shutil.copytree(root / "data", configured_data)
    relative_anchor = "data/reports/agent-eval/p15-look-anchors.jsonl"
    anchor_path = configured_data / "reports/agent-eval/p15-look-anchors.jsonl"
    anchor_path.unlink(missing_ok=True)
    now = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    days = [p15_evaluation.ORIGIN_EPOCH]
    while len(days) < 60:
        days.append(p15_evaluation.nyse.next_session(days[-1]))
    scored = [{"origin_index": index, "status": "scored", "reason": None,
               "skip_reason": None, "delta_ic": 0.2 + (index % 3) * 0.01,
               "model_ic": 0.3, "baseline_ic": 0.09, "pair_count": 40,
               "evaluated_at": now.isoformat(), "market_date": days[index].isoformat()}
              for index in range(60)]
    registration_sha = "a" * 64
    connection = engine_db.connect(source)
    p15_evaluation.persist_reached_looks(
        connection, scored, registration_sha, evaluated_at=now,
        anchor_path=anchor_path,
    )
    with engine_db.transaction(connection):
        p15_evaluation.publish_pending_look_anchors(
            connection, registration_sha, anchor_path=anchor_path,
        )
    connection.close()

    backup_database.create_backup(
        root, source, destination, data_dir=configured_data,
    )

    bundled_anchor = destination / "evidence" / relative_anchor
    assert bundled_anchor.read_bytes() == anchor_path.read_bytes()
    restored = engine_db.connect(
        destination / backup_database.DATABASE_FILENAME, read_only=True,
    )
    assert p15_evaluation.load_retained_looks(
        restored, scored, registration_sha, anchor_path=bundled_anchor,
    )[0]["look"] == 60
    restored.close()


def test_create_preserves_incomplete_nonreleasable_source_identity(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    monkeypatch.setattr(
        backup_database,
        "_release_summary",
        lambda *_args: {
            "status": "non-releasable",
            "release_eligible": False,
            "manifest_sha256": "a" * 64,
            "git_sha": None,
            "working_tree_sha256": None,
            "research_runtime": {"sha256": None, "file_count": 1},
        },
    )

    assert backup_database.create_backup(root, source, destination)["status"] == "ok"
    assert backup_database.verify_backup(destination)["status"] == "ok"


def test_optional_agent_shadow_control_is_hashed_when_present(tmp_path):
    root, source = _repo(tmp_path)
    control = root / "store" / "agent-shadow-control.json"
    control.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": False,
                "registration_sha256": "a" * 64,
                "reason": "disabled for recovery",
                "updated_at": "2026-09-13T12:00:00Z",
            }
        )
        + "\n"
    )
    destination = tmp_path / "outside" / "snapshot"

    created = backup_database.create_backup(root, source, destination)
    manifest = json.loads((destination / backup_database.MANIFEST_FILENAME).read_text())

    assert created["operational_control_count"] == 1
    assert set(manifest["operational_controls"]) == {
        "store/agent-shadow-control.json"
    }
    assert (
        destination / "evidence" / "store" / "agent-shadow-control.json"
    ).read_bytes() == control.read_bytes()
    assert backup_database.verify_backup(destination)["operational_control_count"] == 1


def test_create_refuses_to_overwrite_existing_destination(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    destination.mkdir(parents=True)
    marker = destination / "keep"
    marker.write_text("untouched")

    with pytest.raises(backup_database.BackupError, match="refusing to overwrite"):
        backup_database.create_backup(root, source, destination)

    assert marker.read_text() == "untouched"


def test_create_refuses_dangling_destination_symlink(tmp_path):
    root, source = _repo(tmp_path)
    parent = tmp_path / "outside"
    parent.mkdir()
    destination = parent / "snapshot"
    target = parent / "missing-target"
    destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(backup_database.BackupError, match="refusing to overwrite"):
        backup_database.create_backup(root, source, destination)

    assert destination.is_symlink()
    assert not target.exists()


def test_create_does_not_replace_destination_created_during_backup(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    original_publish = backup_database._publish_no_replace

    def create_destination_then_publish(parent_fd, temporary_name, destination_name):
        os.mkdir(destination_name, dir_fd=parent_fd)
        created_inode.append(os.stat(destination_name, dir_fd=parent_fd).st_ino)
        original_publish(parent_fd, temporary_name, destination_name)

    created_inode = []
    monkeypatch.setattr(
        backup_database,
        "_publish_no_replace",
        create_destination_then_publish,
    )

    with pytest.raises(backup_database.BackupError, match="refusing to overwrite"):
        backup_database.create_backup(root, source, destination)

    assert destination.is_dir()
    assert destination.stat().st_ino == created_inode[0]
    assert list(destination.iterdir()) == []
    assert not any(path.name.startswith(".snapshot.") for path in destination.parent.iterdir())


def test_create_does_not_follow_destination_symlink_inserted_during_resolution(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    redirected = tmp_path / "redirected"
    original_mkdir = backup_database.Path.mkdir
    inserted = False

    def mkdir_then_link(path, *args, **kwargs):
        nonlocal inserted
        result = original_mkdir(path, *args, **kwargs)
        if path == destination.parent and not inserted:
            inserted = True
            destination.symlink_to(redirected, target_is_directory=True)
        return result

    monkeypatch.setattr(backup_database.Path, "mkdir", mkdir_then_link)

    with pytest.raises(backup_database.BackupError, match="refusing to overwrite"):
        backup_database.create_backup(root, source, destination)

    assert inserted is True
    assert destination.is_symlink()
    assert not redirected.exists()


def test_create_syncs_verified_bundle_before_publish_and_parent_after(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    events = []
    original_publish = backup_database._publish_no_replace

    def sync_bundle(bundle, bundle_fd):
        assert os.fstat(bundle_fd).st_ino == bundle.stat().st_ino
        assert backup_database._verify_backup_at_descriptor(bundle_fd)["status"] == "ok"
        events.append(("bundle", bundle))

    def publish(parent_fd, temporary_name, destination_name):
        events.append(("publish", destination_name))
        original_publish(parent_fd, temporary_name, destination_name)

    def sync_directory_fd(parent_fd, *, label):
        events.append(("parent", os.fstat(parent_fd).st_ino, label))

    monkeypatch.setattr(backup_database, "_sync_bundle", sync_bundle)
    monkeypatch.setattr(backup_database, "_publish_no_replace", publish)
    monkeypatch.setattr(backup_database, "_sync_directory_fd", sync_directory_fd)

    assert backup_database.create_backup(root, source, destination)["status"] == "ok"
    assert [event[0] for event in events] == ["bundle", "publish", "parent"]
    assert events[-1] == (
        "parent",
        destination.parent.stat().st_ino,
        "backup parent directory",
    )


def test_create_cleans_temporary_bundle_after_sync_failure(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    monkeypatch.setattr(
        backup_database,
        "_sync_bundle",
        lambda *_args: (_ for _ in ()).throw(backup_database.BackupError("sync failed")),
    )

    with pytest.raises(backup_database.BackupError, match="sync failed"):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_create_preserves_published_bundle_when_parent_sync_fails(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    original_sync_directory_fd = backup_database._sync_directory_fd

    def fail_parent_sync(parent_fd, *, label):
        if label == "backup parent directory":
            raise backup_database.BackupError("parent sync failed")
        original_sync_directory_fd(parent_fd, label=label)

    monkeypatch.setattr(backup_database, "_sync_directory_fd", fail_parent_sync)

    with pytest.raises(backup_database.BackupError, match="parent sync failed"):
        backup_database.create_backup(root, source, destination)

    assert destination.is_dir()
    assert backup_database.verify_backup(destination)["status"] == "ok"
    assert not any(path.name.startswith(".snapshot.") for path in destination.parent.iterdir())


def test_create_rejects_replaced_destination_parent_without_publishing_into_replacement(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    parent = tmp_path / "outside"
    destination = parent / "snapshot"
    displaced = tmp_path / "outside-original"
    original_copy_database = backup_database._copy_database_file

    def replace_parent_after_copy(source_path, database, wal=None):
        snapshot = original_copy_database(source_path, database, wal)
        parent.rename(displaced)
        parent.mkdir()
        return snapshot

    monkeypatch.setattr(backup_database, "_copy_database_file", replace_parent_after_copy)

    with pytest.raises(
        backup_database.BackupError, match="destination parent changed during backup"
    ):
        backup_database.create_backup(root, source, destination)

    assert list(parent.iterdir()) == []
    assert not (parent / "snapshot").exists()
    assert not (displaced / "snapshot").exists()
    assert list(displaced.iterdir()) == []


def test_create_preserves_anchored_bundle_if_parent_is_replaced_during_publish(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    parent = tmp_path / "outside"
    destination = parent / "snapshot"
    displaced = tmp_path / "outside-original"
    original_publish = backup_database._publish_no_replace

    def replace_parent_then_publish(parent_fd, temporary_name, destination_name):
        parent.rename(displaced)
        parent.mkdir()
        original_publish(parent_fd, temporary_name, destination_name)

    monkeypatch.setattr(
        backup_database, "_publish_no_replace", replace_parent_then_publish
    )

    with pytest.raises(
        backup_database.BackupError, match="destination parent changed after publication"
    ):
        backup_database.create_backup(root, source, destination)

    assert list(parent.iterdir()) == []
    assert not (parent / "snapshot").exists()
    published = displaced / "snapshot"
    assert published.is_dir()
    assert backup_database.verify_backup(published)["status"] == "ok"
    assert not any(path.name.startswith(".snapshot.") for path in displaced.iterdir())


def test_create_rejects_replaced_temporary_bundle_without_publishing_or_deleting_it(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    parent = tmp_path / "outside"
    destination = parent / "snapshot"
    displaced = parent / "displaced-temporary"
    original_copy_database = backup_database._copy_database_file

    def replace_temporary_after_copy(source_path, database, wal=None):
        snapshot = original_copy_database(source_path, database, wal)
        temporary = next(parent.glob(".snapshot.*"))
        temporary.rename(displaced)
        temporary.mkdir(mode=0o700)
        (temporary / "keep").write_text("replacement")
        return snapshot

    monkeypatch.setattr(backup_database, "_copy_database_file", replace_temporary_after_copy)

    with pytest.raises(
        backup_database.BackupError, match="temporary backup bundle changed during creation"
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    replacement = next(parent.glob(".snapshot.*"))
    assert (replacement / "keep").read_text() == "replacement"
    assert (displaced / backup_database.DATABASE_FILENAME).is_file()
    assert (displaced / backup_database.MANIFEST_FILENAME).is_file()


def test_create_rejects_source_database_replaced_after_copy(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    displaced = source.with_name("market-original.duckdb")
    original_copy_database = backup_database._copy_database_file

    def replace_source_after_copy(source_read_path, database, wal=None):
        snapshot = original_copy_database(source_read_path, database, wal)
        source.rename(displaced)
        _source_database(source)
        return snapshot

    monkeypatch.setattr(backup_database, "_copy_database_file", replace_source_after_copy)

    with pytest.raises(
        backup_database.BackupError, match="source database changed during backup"
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert source.is_file()
    assert displaced.is_file()
    assert list(destination.parent.iterdir()) == []


def test_create_rejects_source_database_metadata_changed_after_copy(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    original_copy_database = backup_database._copy_database_file

    def touch_source_after_copy(source_read_path, database, wal=None):
        snapshot = original_copy_database(source_read_path, database, wal)
        source.touch()
        return snapshot

    monkeypatch.setattr(backup_database, "_copy_database_file", touch_source_after_copy)

    with pytest.raises(
        backup_database.BackupError, match="source database changed during backup"
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_create_preserves_published_bundle_if_source_is_replaced_during_publish(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    displaced = source.with_name("market-original.duckdb")
    original_publish = backup_database._publish_no_replace

    def replace_source_then_publish(parent_fd, temporary_name, destination_name):
        source.rename(displaced)
        _source_database(source)
        original_publish(parent_fd, temporary_name, destination_name)

    monkeypatch.setattr(
        backup_database, "_publish_no_replace", replace_source_then_publish
    )

    with pytest.raises(
        backup_database.BackupError, match="source database changed during backup"
    ):
        backup_database.create_backup(root, source, destination)

    assert destination.is_dir()
    assert backup_database.verify_backup(destination)["status"] == "ok"
    assert source.is_file()
    assert displaced.is_file()
    assert not any(path.name.startswith(".snapshot.") for path in destination.parent.iterdir())


def test_source_database_open_rejects_symlinked_canonical_parent(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    original_relative_directory_fd = backup_database._relative_directory_fd

    def replace_parent_before_secure_traversal(path, parts, *, create):
        if path == Path(source.anchor) and parts == source.relative_to(path).parts[:-1]:
            external = tmp_path / "source-parent-original"
            source.parent.rename(external)
            source.parent.symlink_to(external, target_is_directory=True)
        return original_relative_directory_fd(path, parts, create=create)

    monkeypatch.setattr(
        backup_database, "_relative_directory_fd", replace_parent_before_secure_traversal
    )

    with pytest.raises(
        backup_database.BackupError,
        match="relative path parent must be a non-symlinked directory",
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_create_rejects_source_parent_replaced_with_symlink_after_copy(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    displaced = tmp_path / "store-original"
    original_copy_database = backup_database._copy_database_file

    def replace_source_parent_after_copy(source_read_path, database, wal=None):
        snapshot = original_copy_database(source_read_path, database, wal)
        source.parent.rename(displaced)
        source.parent.symlink_to(displaced, target_is_directory=True)
        return snapshot

    monkeypatch.setattr(
        backup_database, "_copy_database_file", replace_source_parent_after_copy
    )

    with pytest.raises(
        backup_database.BackupError, match="source database changed during backup"
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert source.parent.is_symlink()
    assert (displaced / source.name).is_file()
    assert list(destination.parent.iterdir()) == []


def test_create_cleans_temporary_bundle_after_copy_failure(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    parent = tmp_path / "backups"
    destination = parent / "snapshot"
    monkeypatch.setattr(
        backup_database,
        "_copy_database_file",
        lambda *_args: (_ for _ in ()).throw(backup_database.BackupError("copy failed")),
    )

    with pytest.raises(backup_database.BackupError, match="copy failed"):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert list(parent.iterdir()) == []


def test_create_cleans_temporary_bundle_after_keyboard_interrupt(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    parent = tmp_path / "backups"
    destination = parent / "snapshot"
    monkeypatch.setattr(
        backup_database,
        "_copy_database_file",
        lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert list(parent.iterdir()) == []


def test_create_cleans_temporary_bundle_when_descriptor_path_is_unavailable(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    parent = tmp_path / "backups"
    destination = parent / "snapshot"
    monkeypatch.setattr(
        backup_database,
        "_descriptor_path",
        lambda *_args: (_ for _ in ()).throw(
            backup_database.BackupError("directory descriptor path is unavailable")
        ),
    )

    with pytest.raises(
        backup_database.BackupError, match="descriptor path is unavailable"
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()
    assert list(parent.iterdir()) == []


def test_create_rejects_evidence_below_symlinked_directory(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    monkeypatch.setattr(
        backup_database,
        "LOCK_FILES",
        tuple(relative for relative in backup_database.LOCK_FILES if "/" not in relative),
    )
    external = tmp_path / "external-data"
    (root / "data").replace(external)
    (root / "data").symlink_to(external, target_is_directory=True)
    destination = tmp_path / "outside" / "snapshot"

    with pytest.raises(
        backup_database.BackupError,
        match="relative path parent must be a non-symlinked directory",
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()


def test_create_rejects_operational_artifact_below_symlinked_directory(tmp_path):
    root, source = _repo(tmp_path)
    external = tmp_path / "external-logs"
    (root / "logs").replace(external)
    (root / "logs").symlink_to(external, target_is_directory=True)
    destination = tmp_path / "outside" / "snapshot"

    with pytest.raises(
        backup_database.BackupError,
        match="relative path parent must be a non-symlinked directory",
    ):
        backup_database.create_backup(root, source, destination)

    assert not destination.exists()


@pytest.mark.parametrize("node_type", ["symlink", "directory", "fifo"])
def test_create_rejects_nonregular_evidence_source(tmp_path, node_type):
    root, source = _repo(tmp_path)
    relative = backup_database.EVIDENCE_FILES[0]
    evidence = root / relative
    evidence.unlink()
    if node_type == "symlink":
        external = tmp_path / "external-evidence"
        external.write_text("outside")
        evidence.symlink_to(external)
    elif node_type == "directory":
        evidence.mkdir()
    else:
        os.mkfifo(evidence)

    with pytest.raises(backup_database.BackupError, match="required prospective evidence"):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert not (tmp_path / "outside" / "snapshot").exists()


def test_create_rejects_oversized_evidence_source(tmp_path):
    root, source = _repo(tmp_path)
    relative = backup_database.EVIDENCE_FILES[0]
    (root / relative).write_bytes(b"x" * (backup_database.MAX_OPERATIONAL_FILE_BYTES + 1))

    with pytest.raises(backup_database.BackupError, match="prospective evidence exceeds"):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert not (tmp_path / "outside" / "snapshot").exists()


def _metadata_bytes(root: Path, size: int) -> bytes:
    content = (root / "data/_meta.json").read_bytes()
    assert len(content) < size
    return content + b" " * (size - len(content))


@pytest.mark.parametrize("size", [1_048_577, 8 * 1024 * 1024])
def test_backup_preserves_full_metadata_through_eight_mib(tmp_path, size):
    from server.meta_snapshot import MAX_META_SNAPSHOT_BYTES

    root, source = _repo(tmp_path)
    content = _metadata_bytes(root, size)
    (root / "data/_meta.json").write_bytes(content)
    destination = tmp_path / "outside" / "snapshot"

    created = backup_database.create_backup(root, source, destination)
    assert backup_database.verify_backup(destination) == created
    assert (destination / "evidence/data/_meta.json").read_bytes() == content
    assert backup_database.MAX_META_SNAPSHOT_BYTES == MAX_META_SNAPSHOT_BYTES


@pytest.mark.parametrize("phase", ["create", "verify"])
def test_backup_refuses_metadata_above_eight_mib(tmp_path, phase):
    root, source = _repo(tmp_path)
    content = _metadata_bytes(root, 8 * 1024 * 1024 + 1)
    destination = tmp_path / "outside" / "snapshot"
    if phase == "verify":
        backup_database.create_backup(root, source, destination)
        (destination / "evidence/data/_meta.json").write_bytes(content)
        _rehash_artifact(destination, "data/_meta.json")
    else:
        (root / "data/_meta.json").write_bytes(content)

    with pytest.raises(backup_database.BackupError, match="exceeds 8388608 bytes"):
        if phase == "verify":
            backup_database.verify_backup(destination)
        else:
            backup_database.create_backup(root, source, destination)
    assert destination.exists() is (phase == "verify")


@pytest.mark.parametrize("relative", ["logs/friday-postflight.json", "logs/_meta.json"])
def test_metadata_allowance_does_not_widen_other_artifacts(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 1_048_577)
    with pytest.raises(backup_database.BackupError, match="exceeds 1048576 bytes"):
        backup_database._read_source_file(tmp_path, relative, "operational artifact")


def test_metadata_descriptor_read_stops_at_eight_mib_plus_one(tmp_path, monkeypatch):
    path = tmp_path / "data/_meta.json"
    path.parent.mkdir()
    path.write_bytes(b"x" * (8 * 1024 * 1024 + 100))
    original_read = backup_database.os.read
    total_read = 0

    def counted_read(descriptor, size):
        nonlocal total_read
        assert size <= 64 * 1024
        chunk = original_read(descriptor, size)
        total_read += len(chunk)
        return chunk

    monkeypatch.setattr(backup_database.os, "read", counted_read)
    with pytest.raises(backup_database.BackupError, match="exceeds 8388608 bytes"):
        backup_database._read_source_file(tmp_path, "data/_meta.json", "operational artifact")
    assert total_read == 8 * 1024 * 1024 + 1


@pytest.mark.parametrize("operation", ["modify", "replace"])
def test_large_metadata_keeps_descriptor_stability_checks(tmp_path, monkeypatch, operation):
    root, _ = _repo(tmp_path)
    path = root / "data/_meta.json"
    path.write_bytes(_metadata_bytes(root, 1_048_577))
    original_read = backup_database.os.read
    changed = False

    def read_then_change(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            if operation == "modify":
                with path.open("ab") as stream:
                    stream.write(b" ")
            else:
                replacement = path.with_suffix(".replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.replace(path)
        return chunk

    monkeypatch.setattr(backup_database.os, "read", read_then_change)
    with pytest.raises(backup_database.BackupError, match="changed during backup"):
        backup_database._read_source_file(root, "data/_meta.json", "operational artifact")
    assert changed


@pytest.mark.parametrize("operation", ["modify", "replace"])
def test_create_rejects_evidence_changed_during_descriptor_read(
    tmp_path, monkeypatch, operation
):
    root, source = _repo(tmp_path)
    relative = backup_database.EVIDENCE_FILES[0]
    evidence = root / relative
    evidence_inode = evidence.stat().st_ino
    original_read = backup_database.os.read
    changed = False

    def read_then_change(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed and backup_database.os.fstat(descriptor).st_ino == evidence_inode:
            changed = True
            if operation == "modify":
                with evidence.open("ab") as handle:
                    handle.write(b"changed")
            else:
                replacement = evidence.with_suffix(".replacement")
                replacement.write_text("replacement")
                replacement.replace(evidence)
        return chunk

    monkeypatch.setattr(backup_database.os, "read", read_then_change)

    with pytest.raises(backup_database.BackupError, match="evidence changed during backup"):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert changed is True
    assert not (tmp_path / "outside" / "snapshot").exists()


def test_verify_rejects_database_tampering(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    with (destination / backup_database.DATABASE_FILENAME).open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(backup_database.BackupError, match="database file integrity"):
        backup_database.verify_backup(destination)


def test_verify_rejects_symlinked_database(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    database = destination / backup_database.DATABASE_FILENAME
    linked_database = tmp_path / "linked-market.duckdb"
    database.replace(linked_database)
    database.symlink_to(linked_database)

    with pytest.raises(backup_database.BackupError, match="database.*symlink"):
        backup_database.verify_backup(destination)


def test_verify_rejects_symlinked_manifest(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    manifest = destination / backup_database.MANIFEST_FILENAME
    linked_manifest = tmp_path / "linked-manifest.json"
    manifest.replace(linked_manifest)
    manifest.symlink_to(linked_manifest)

    with pytest.raises(backup_database.BackupError, match="manifest.*symlink"):
        backup_database.verify_backup(destination)


def test_verify_rejects_evidence_tampering(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    relative = backup_database.EVIDENCE_FILES[0]
    evidence = destination / "evidence" / relative
    evidence.write_text("changed")

    with pytest.raises(backup_database.BackupError, match="prospective evidence integrity"):
        backup_database.verify_backup(destination)


def test_verify_rejects_symlinked_evidence_inside_bundle(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    relative = backup_database.EVIDENCE_FILES[0]
    evidence = destination / "evidence" / relative
    linked_evidence = destination / "linked-evidence.json"
    evidence.replace(linked_evidence)
    evidence.symlink_to(linked_evidence)

    with pytest.raises(backup_database.BackupError, match="evidence.*symlinks"):
        backup_database.verify_backup(destination)


def test_verify_rejects_symlinked_bundle(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    alias = tmp_path / "bundle-alias"
    alias.symlink_to(destination, target_is_directory=True)

    with pytest.raises(backup_database.BackupError, match="bundle.*symlink"):
        backup_database.verify_backup(alias)


def test_verify_rejects_symlinked_bundle_parent(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    alias_parent = tmp_path / "outside-alias"
    alias_parent.symlink_to(destination.parent, target_is_directory=True)

    with pytest.raises(
        backup_database.BackupError,
        match="relative path parent must be a non-symlinked directory",
    ):
        backup_database.verify_backup(alias_parent / destination.name)


def test_verify_rejects_bundle_replaced_during_verification(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    replacement = destination.with_name("replacement")
    displaced = destination.with_name("displaced")
    shutil.copytree(destination, replacement)
    original_load_manifest = backup_database._load_manifest
    replaced = False

    def load_then_replace(bundle):
        nonlocal replaced
        result = original_load_manifest(bundle)
        if not replaced:
            replaced = True
            destination.replace(displaced)
            replacement.replace(destination)
        return result

    monkeypatch.setattr(backup_database, "_load_manifest", load_then_replace)

    with pytest.raises(
        backup_database.BackupError, match="bundle changed during verification"
    ):
        backup_database.verify_backup(destination)

    assert replaced is True
    assert destination.is_dir()
    assert displaced.is_dir()


def test_verify_rejects_nested_file_replaced_during_verification(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    artifact = destination / "evidence" / "data" / "_meta.json"
    replacement = tmp_path / "replacement-meta.json"
    displaced = tmp_path / "displaced-meta.json"
    shutil.copy2(artifact, replacement)
    original_verify_evidence = backup_database._verify_evidence
    replaced = False

    def verify_then_replace(bundle, manifest):
        nonlocal replaced
        result = original_verify_evidence(bundle, manifest)
        if not replaced:
            replaced = True
            artifact.replace(displaced)
            replacement.replace(artifact)
        return result

    monkeypatch.setattr(backup_database, "_verify_evidence", verify_then_replace)

    with pytest.raises(
        backup_database.BackupError, match="bundle changed during verification"
    ):
        backup_database.verify_backup(destination)

    assert replaced is True
    assert artifact.is_file()
    assert displaced.is_file()


def test_verify_rejects_nested_file_replaced_and_restored_during_verification(
    tmp_path, monkeypatch
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    artifact = destination / "evidence" / "data" / "_meta.json"
    replacement = tmp_path / "replacement-meta.json"
    displaced = tmp_path / "displaced-meta.json"
    replacement.write_text(artifact.read_text().replace("{", '{"transient":true,', 1))
    replacement.chmod(0o600)
    original_verify_consistency = backup_database._verify_operational_consistency
    replaced = False

    def verify_with_transient_replacement(bundle, manifest):
        nonlocal replaced
        replaced = True
        artifact.replace(displaced)
        replacement.replace(artifact)
        try:
            original_verify_consistency(bundle, manifest)
        finally:
            artifact.replace(replacement)
            displaced.replace(artifact)

    monkeypatch.setattr(
        backup_database,
        "_verify_operational_consistency",
        verify_with_transient_replacement,
    )

    with pytest.raises(
        backup_database.BackupError, match="bundle changed during verification"
    ):
        backup_database.verify_backup(destination)

    assert replaced is True
    assert json.loads(artifact.read_text()).get("transient") is None


def test_verify_rejects_bundle_parent_replaced_with_symlink(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    parent = tmp_path / "outside"
    destination = parent / "snapshot"
    backup_database.create_backup(root, source, destination)
    displaced_parent = tmp_path / "displaced-outside"
    original_load_manifest = backup_database._load_manifest
    replaced = False

    def load_then_replace(bundle):
        nonlocal replaced
        result = original_load_manifest(bundle)
        if not replaced:
            replaced = True
            parent.replace(displaced_parent)
            parent.symlink_to(displaced_parent, target_is_directory=True)
        return result

    monkeypatch.setattr(backup_database, "_load_manifest", load_then_replace)

    with pytest.raises(
        backup_database.BackupError, match="bundle changed during verification"
    ):
        backup_database.verify_backup(destination)

    assert replaced is True
    assert destination.samefile(displaced_parent / "snapshot")


@pytest.mark.parametrize(
    "relative",
    [
        None,
        backup_database.MANIFEST_FILENAME,
        backup_database.DATABASE_FILENAME,
        "evidence",
        "evidence/data",
        "evidence/data/reports",
        f"evidence/{backup_database.EVIDENCE_FILES[0]}",
        "evidence/data/_meta.json",
    ],
)
def test_verify_rejects_nonprivate_bundle_content(tmp_path, relative):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    target = destination if relative is None else destination / relative
    target.chmod(0o755 if target.is_dir() else 0o644)

    with pytest.raises(backup_database.BackupError, match="owner-only"):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize("node_type", ["file", "directory", "fifo", "symlink"])
def test_verify_rejects_unmanifested_bundle_node(tmp_path, node_type):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    unexpected = destination / "unexpected"
    if node_type == "file":
        unexpected.write_text("unexpected")
        unexpected.chmod(0o600)
    elif node_type == "directory":
        unexpected.mkdir(mode=0o700)
    elif node_type == "fifo":
        os.mkfifo(unexpected, mode=0o600)
    else:
        unexpected.symlink_to(destination / backup_database.DATABASE_FILENAME)

    with pytest.raises(backup_database.BackupError, match="backup tree.*unexpected"):
        backup_database.verify_backup(destination)


def test_verify_wraps_missing_bundle_as_backup_error(tmp_path):
    missing = tmp_path / "missing-bundle"

    with pytest.raises(backup_database.BackupError, match="missing or unreadable"):
        backup_database.verify_backup(missing)


def test_verify_rejects_manifest_tampering(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    manifest = destination / backup_database.MANIFEST_FILENAME
    payload = json.loads(manifest.read_text())
    payload["database"]["size_bytes"] += 1
    manifest.write_text(json.dumps(payload))

    with pytest.raises(backup_database.BackupError, match="manifest hash"):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize(
    ("update", "message"),
    [
        (lambda payload: payload.update(unexpected=True), "unexpected or missing fields"),
        (lambda payload: payload.pop("created_at"), "unexpected or missing fields"),
        (lambda payload: payload.update(created_at="2026-09-11T12:00:00"), "must be UTC"),
        (
            lambda payload: payload.update(created_at="2026-09-11 12:00:00+00:00"),
            "timestamp is not canonical",
        ),
        (
            lambda payload: payload.update(created_at="2026-09-11T12:00:00+0000"),
            "timestamp is not canonical",
        ),
        (
            lambda payload: payload.update(created_at="2026-09-11T12:00:00Z"),
            "timestamp is not canonical",
        ),
        (
            lambda payload: payload.update(created_at="2026-09-11T12:00:00.123+00:00"),
            "timestamp is not canonical",
        ),
        (
            lambda payload: payload.update(
                created_at="2026-09-11T12:00:00.1234567+00:00"
            ),
            "timestamp is not canonical",
        ),
        (
            lambda payload: payload.update(
                created_at="2026-09-11T12:00:00.000000+00:00"
            ),
            "timestamp is not canonical",
        ),
        (
            lambda payload: payload.update(
                source_database={"kind": "repository-relative", "path": "../market.duckdb"}
            ),
            "source database path is invalid",
        ),
        (
            lambda payload: payload.update(
                source_database={
                    "kind": "repository-relative",
                    "path": "./store/market.duckdb",
                }
            ),
            "source database path is invalid",
        ),
        (
            lambda payload: payload.update(
                source_database={
                    "kind": "repository-relative",
                    "path": "store//market.duckdb",
                }
            ),
            "source database path is invalid",
        ),
        (
            lambda payload: payload.update(
                source_database={"kind": "repository-relative", "path": "."}
            ),
            "source database path is invalid",
        ),
        (
            lambda payload: payload["release_identity"].pop("git_sha"),
            "release identity is invalid",
        ),
        (
            lambda payload: payload["release_identity"].update(release_eligible=True),
            "eligibility is inconsistent",
        ),
        (
            lambda payload: payload["release_identity"].update(git_sha="not-a-git-sha"),
            "git_sha is invalid",
        ),
        (
            lambda payload: payload["release_identity"].update(
                status="release-candidate", release_eligible=True, git_sha=None
            ),
            "git_sha is invalid",
        ),
        (
            lambda payload: payload["release_identity"]["research_runtime"].update(
                file_count=True
            ),
            "research file count is invalid",
        ),
    ],
)
def test_verify_rejects_malformed_recovery_metadata(tmp_path, update, message):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    _rewrite_manifest(destination, update)

    with pytest.raises(backup_database.BackupError, match=message):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize(
    "created_at",
    ["2026-09-11T12:00:00+00:00", "2026-09-11T12:00:00.123456+00:00"],
)
def test_verify_accepts_canonical_creation_timestamps(tmp_path, created_at):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    _rewrite_manifest(
        destination, lambda payload: payload.update(created_at=created_at)
    )

    assert backup_database.verify_backup(destination)["status"] == "ok"


@pytest.mark.parametrize(
    "source",
    [
        {"kind": "external", "path": None},
        {"kind": "repository-relative", "path": "store/market.duckdb"},
    ],
)
def test_source_database_location_accepts_producer_forms(source):
    backup_database._validate_source_database(source)


@pytest.mark.parametrize(
        ("update", "message"),
    [
        (lambda payload: payload.update(schema_version=True), "unsupported.*schema"),
        (lambda payload: payload.update(schema_version=5), "unsupported.*schema"),
        (
            lambda payload: payload["database"].update(size_bytes=True),
            "database size_bytes.*non-negative integer",
        ),
        (
            lambda payload: payload["database"].update(size_bytes=1.5),
            "database size_bytes.*non-negative integer",
        ),
        (
            lambda payload: payload["database"].update(size_bytes=-1),
            "database size_bytes.*non-negative integer",
        ),
        (
            lambda payload: payload["database"].update(sha256=None),
            "database hash is invalid",
        ),
        (
            lambda payload: payload["database"].update(filename=1),
            "database filename is invalid",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(extra=0),
            "snapshot has unexpected or missing fields",
        ),
        (
            lambda payload: payload["database"]["snapshot"].pop("table_count"),
            "snapshot has unexpected or missing fields",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(table_count=True),
            "snapshot table_count.*non-negative integer",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(view_count=1.5),
            "snapshot view_count.*non-negative integer",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(index_count=-1),
            "snapshot index_count.*non-negative integer",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(
                active_portfolio_count=True
            ),
            "snapshot active_portfolio_count.*non-negative integer",
        ),
        (
            lambda payload: payload["database"]["snapshot"]["row_counts"].update(
                {"main.prices": True}
            ),
            "snapshot row_counts is invalid",
        ),
        (
            lambda payload: payload["database"]["snapshot"]["job_states"].update(
                done=-1
            ),
            "snapshot job_states is invalid",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(
                latest_price_date="2026-02-30"
            ),
            "latest price date is invalid",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(
                schema_sha256="invalid"
            ),
            "snapshot schema hash is invalid",
        ),
        (
            lambda payload: payload["database"]["snapshot"].update(
                active_portfolios_sha256=False
            ),
            "active-portfolios hash is invalid",
        ),
        (
            lambda payload: payload["prospective_evidence"][
                backup_database.EVIDENCE_FILES[0]
            ].update(size_bytes=True),
            "evidence size_bytes.*non-negative integer",
        ),
        (
            lambda payload: payload["prospective_evidence"][
                backup_database.EVIDENCE_FILES[0]
            ].update(size_bytes=-1),
            "evidence size_bytes.*non-negative integer",
        ),
        (
            lambda payload: payload["prospective_evidence"][
                backup_database.EVIDENCE_FILES[0]
            ].update(sha256=1),
            "evidence hash is invalid",
        ),
        (
            lambda payload: payload["operational_artifacts"]["data/_meta.json"].update(
                size_bytes=True
            ),
            "operational artifacts size_bytes.*non-negative integer",
        ),
        (
            lambda payload: payload["operational_artifacts"]["data/_meta.json"].update(
                sha256=None
            ),
            "operational artifacts hash is invalid",
        ),
    ],
)
def test_verify_rejects_malformed_database_and_evidence_metadata(
    tmp_path, update, message
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    _rewrite_manifest(destination, update)

    with pytest.raises(backup_database.BackupError, match=message):
        backup_database.verify_backup(destination)


def test_verify_accepts_schema_v1_snapshot_without_operational_artifacts(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    _rewrite_manifest(
        destination,
        lambda payload: (
            payload.update(schema_version=1),
            payload.pop("operational_artifacts"),
            payload.pop("operational_controls"),
            payload["database"]["snapshot"].pop("index_count"),
                payload["database"]["snapshot"].pop("sequence_state"),
                payload["database"]["snapshot"].pop("table_sha256"),
        ),
    )

    for relative in backup_database._operational_files("2026-09-10"):
        (destination / "evidence" / relative).unlink()
    (destination / "evidence/logs").rmdir()
    (destination / "evidence/data/screens").rmdir()
    verified = backup_database.verify_backup(destination)
    assert verified["status"] == "ok"
    assert verified["operational_artifact_count"] == 0
    assert verified["operational_control_count"] == 0


def test_verify_accepts_schema_v2_snapshot_without_operational_controls(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    _rewrite_manifest(
        destination,
        lambda payload: (
            payload.update(schema_version=2),
            payload.pop("operational_controls"),
        ),
    )

    verified = backup_database.verify_backup(destination)

    assert verified["status"] == "ok"
    assert verified["operational_artifact_count"] == 7
    assert verified["operational_control_count"] == 0


def test_verify_rejects_operational_artifact_tampering(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    (destination / "evidence" / "data/_meta.json").write_text("changed")

    with pytest.raises(backup_database.BackupError, match="operational artifact integrity"):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize(
    ("relative", "replacement"),
    [
        (
            "data/_meta.json",
            json.dumps(
                {
                    "screen_date": "2026-09-10",
                    "regime": "risk-on",
                    "screened": 3,
                    "passing_count": 1,
                    "new_today_count": 1,
                    "universe_policy": "all",
                }
            )
            + "\n",
        ),
        (
            "data/reports/league.csv",
            "portfolio_id,date,equity\npaper,2026-09-10,999.0\n",
        ),
    ],
)
def test_verify_rejects_rehashed_operational_artifact_database_mismatch(
    tmp_path, relative, replacement
):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    artifact = destination / "evidence" / relative
    artifact.write_text(replacement)
    _rehash_artifact(destination, relative)

    with pytest.raises(backup_database.BackupError, match="do not match backup database"):
        backup_database.verify_backup(destination)


def test_verify_rejects_symlinked_operational_artifact(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    artifact = destination / "evidence" / "data/_meta.json"
    linked = destination / "linked-meta.json"
    artifact.replace(linked)
    artifact.symlink_to(linked)

    with pytest.raises(backup_database.BackupError, match="operational artifact.*symlinks"):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize("operation", ["missing", "unexpected"])
def test_verify_requires_exact_operational_artifact_entries(tmp_path, operation):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)

    def update(payload):
        artifacts = payload["operational_artifacts"]
        if operation == "missing":
            artifacts.pop("data/_meta.json")
        else:
            artifacts["data/unexpected.json"] = artifacts["data/_meta.json"].copy()

    _rewrite_manifest(destination, update)

    with pytest.raises(backup_database.BackupError, match="unexpected or missing entries"):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize("bundle_path", ["evidence/data/wrong.json", "../outside.json"])
def test_verify_rejects_wrong_operational_artifact_path(tmp_path, bundle_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    _rewrite_manifest(
        destination,
        lambda payload: payload["operational_artifacts"]["data/_meta.json"].update(
            bundle_path=bundle_path
        ),
    )

    with pytest.raises(backup_database.BackupError, match="operational artifacts path is invalid"):
        backup_database.verify_backup(destination)


def test_verify_rejects_unmanifested_evidence_file(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    extra = destination / "evidence" / "unexpected.txt"
    extra.write_text("unexpected")
    extra.chmod(0o600)

    with pytest.raises(backup_database.BackupError, match="backup tree.*unexpected"):
        backup_database.verify_backup(destination)


def test_verify_rejects_unmanifested_special_evidence_node(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    os.mkfifo(destination / "evidence" / "unexpected.fifo", mode=0o600)

    with pytest.raises(backup_database.BackupError, match="backup tree.*unexpected"):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize(
    ("bundle_path", "message"),
    [
        ("../outside.json", "path is invalid"),
        ("/tmp/outside.json", "path is invalid"),
    ],
)
def test_verify_rejects_evidence_paths_outside_bundle(tmp_path, bundle_path, message):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    relative = backup_database.EVIDENCE_FILES[0]
    _rewrite_manifest(
        destination,
        lambda payload: payload["prospective_evidence"][relative].update(
            bundle_path=bundle_path
        ),
    )

    with pytest.raises(backup_database.BackupError, match=message):
        backup_database.verify_backup(destination)


@pytest.mark.parametrize("operation", ["missing", "unexpected"])
def test_verify_requires_exact_evidence_entries(tmp_path, operation):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    relative = backup_database.EVIDENCE_FILES[0]

    def update(payload):
        evidence = payload["prospective_evidence"]
        if operation == "missing":
            evidence.pop(relative)
        else:
            evidence["unexpected.json"] = evidence[relative].copy()

    _rewrite_manifest(destination, update)

    with pytest.raises(backup_database.BackupError, match="unexpected or missing"):
        backup_database.verify_backup(destination)


def test_verify_requires_exact_evidence_record_fields(tmp_path):
    root, source = _repo(tmp_path)
    destination = tmp_path / "outside" / "snapshot"
    backup_database.create_backup(root, source, destination)
    relative = backup_database.EVIDENCE_FILES[0]
    _rewrite_manifest(
        destination,
        lambda payload: payload["prospective_evidence"][relative].update(extra="value"),
    )

    with pytest.raises(backup_database.BackupError, match="manifest is invalid"):
        backup_database.verify_backup(destination)


def test_missing_required_table_fails_closed(tmp_path):
    root, source = _repo(tmp_path)
    connection = duckdb.connect(str(source))
    connection.execute("DROP TABLE sim_fills")
    connection.close()

    with pytest.raises(backup_database.BackupError, match="sim_fills"):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")


def test_create_refuses_destination_inside_repository(tmp_path):
    root, source = _repo(tmp_path)

    with pytest.raises(backup_database.BackupError, match="outside the repository"):
        backup_database.create_backup(root, source, root / "backups" / "snapshot")


@pytest.mark.parametrize("relative", [backup_database.LOCK_FILES[0], "data/_meta.json.lock"])
def test_create_refuses_while_a_writer_lock_is_held(tmp_path, relative):
    root, source = _repo(tmp_path)
    lock_path = root / relative
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(backup_database.BackupError, match="active process holds"):
            backup_database.create_backup(
                root, source, tmp_path / "outside" / "snapshot"
            )

    assert not (tmp_path / "outside" / "snapshot").exists()


@pytest.mark.parametrize("node_type", ["symlink", "directory", "fifo"])
def test_create_rejects_unsafe_lock_node(tmp_path, node_type):
    root, source = _repo(tmp_path)
    relative = backup_database.LOCK_FILES[0]
    lock_path = root / relative
    if node_type == "symlink":
        external = tmp_path / "external-lock"
        external.touch()
        lock_path.symlink_to(external)
    elif node_type == "directory":
        lock_path.mkdir()
    else:
        os.mkfifo(lock_path)

    with pytest.raises(backup_database.BackupError, match="lock path must be a regular file"):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert not (tmp_path / "outside" / "snapshot").exists()


def test_create_rejects_symlinked_lock_parent(tmp_path):
    root, source = _repo(tmp_path)
    external = tmp_path / "external-data"
    (root / "data").replace(external)
    (root / "data").symlink_to(external, target_is_directory=True)

    with pytest.raises(
        backup_database.BackupError,
        match="relative path parent must be a non-symlinked directory",
    ):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert not (tmp_path / "outside" / "snapshot").exists()


def test_create_rejects_nondirectory_lock_parent(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    monkeypatch.setattr(backup_database, "LOCK_FILES", ("unsafe/snapshot.lock",))
    (root / "unsafe").write_text("not a directory")

    with pytest.raises(
        backup_database.BackupError,
        match="relative path parent must be a non-symlinked directory",
    ):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert not (tmp_path / "outside" / "snapshot").exists()


def test_create_fails_closed_without_secure_path_flags(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    monkeypatch.delattr(backup_database.os, "O_NOFOLLOW")

    with pytest.raises(backup_database.BackupError, match="secure.*unavailable"):
        backup_database.create_backup(root, source, tmp_path / "outside" / "snapshot")

    assert not (tmp_path / "outside" / "snapshot").exists()


def test_sql_string_escapes_quotes_and_rejects_nul():
    assert backup_database._sql_string("a'b") == "'a''b'"
    with pytest.raises(backup_database.BackupError, match="NUL"):
        backup_database._sql_string("a\x00b")
