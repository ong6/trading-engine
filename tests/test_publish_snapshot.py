"""Atomic read-only database snapshot publication and discovery."""
from __future__ import annotations

import inspect
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from engine import schema_migrations
from engine.lib import db as engine_db
from engine.lib import snapshots
from tools import backup_database, publish_snapshot

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def test_publisher_has_no_whole_primary_copy_path():
    source = inspect.getsource(publish_snapshot)
    assert "backup_database._copy_database(source" not in source


def _database(path: Path, *, cold: bool = False) -> None:
    con = duckdb.connect(str(path))
    migration = schema_migrations.migrations()[0]
    migration.module.bootstrap(con)
    con.execute(
        "INSERT INTO prices (ticker,date,open,high,low,close,volume,first_fetched_at) "
        "VALUES ('SPY','2026-10-01',1,1,1,1,1,'2026-10-01')"
    )
    if cold:
        con.execute(
            "INSERT INTO intraday_prices VALUES "
            "('SPY','2026-10-01 14:30:00','1m',1,2,1,2,10,'fixture','2026-10-01')"
        )
        con.execute(
            "INSERT INTO source_response_receipts VALUES "
            "(1,1,'fixture','fixture','fixture','{}',?,TIMESTAMP '2026-10-01 11:00:00',"
            "TIMESTAMP '2026-10-01 12:00:00',200,'application/json',3,?,"
            "from_base64('AAEC'),'internal',?)",
            ["a" * 64, "b" * 64, "c" * 64],
        )
        con.execute(
            "INSERT INTO bitemporal_facts VALUES "
            "(1,1,'SPY','SPY','fixture',TIMESTAMP '2020-01-01',NULL,"
            "TIMESTAMP '2026-10-01',TIMESTAMP '2026-10-01',1,'{}',?,"
            "'fixture','v1',?,NULL,?)",
            ["d" * 64, "c" * 64, "e" * 64],
        )
        con.execute(
            "INSERT INTO actions_fetch_log VALUES "
            "('DUP','2026-10-01',0,0,'empty','fixture','2026-10-01'),"
            "('DUP','2026-10-01',0,0,'empty','fixture','2026-10-01')"
        )
        con.execute("INSERT INTO jobs (id,state) VALUES (1, 'running')")
    catalog_hash = schema_migrations.catalog_sha256(con)
    assert catalog_hash == migration.module.EXPECTED_CATALOG_SHA256
    con.execute(
        "CREATE TABLE schema_migrations (migration_id INTEGER PRIMARY KEY, "
        "migration_sha256 VARCHAR, source_commit VARCHAR, applied_at TIMESTAMPTZ, "
        "pre_catalog_sha256 VARCHAR, post_catalog_sha256 VARCHAR, "
        "recovery_manifest_sha256 VARCHAR)"
    )
    con.execute(
        "INSERT INTO schema_migrations VALUES (0, ?, ?, now(), ?, ?, ?)",
        [migration.sha256, "a" * 40, catalog_hash, catalog_hash, "b" * 64],
    )
    con.close()


def _cohort(root: Path) -> None:
    relatives = set(backup_database.EVIDENCE_FILES)
    relatives.update(backup_database._operational_files("2026-10-01"))
    for relative in relatives:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"path": relative}) + "\n")


def _repo(tmp_path: Path, *, cold: bool = False) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    source = root / "store" / "market.duckdb"
    source.parent.mkdir(parents=True)
    _database(source, cold=cold)
    _cohort(root)
    return root, source


def test_publish_is_atomic_retains_two_and_records_manifest(tmp_path):
    root, source = _repo(tmp_path)
    manifests = [
        publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=index))
        for index in range(3)
    ]
    directory = source.parent / "snapshots"
    files = sorted(
        path for path in directory.glob("market-*.duckdb") if not path.is_symlink()
    )

    assert len(files) == 2
    latest = directory / snapshots.LATEST_NAME
    assert latest.is_symlink() and os.readlink(latest) == manifests[-1]["snapshot"]
    manifest = json.loads(latest.resolve().with_suffix(".json").read_text())
    assert manifest == manifests[-1]
    assert manifest["row_counts"]["main.prices"] == 1
    assert manifest["hot_database"]["size_bytes"] == latest.resolve().stat().st_size
    assert len(manifest["hot_database"]["sha256"]) == 64
    assert manifest["database_schema_id"] == 0
    con = duckdb.connect(str(latest.resolve()), read_only=True)
    assert con.execute("SELECT ticker FROM prices").fetchone() == ("SPY",)
    con.close()


@pytest.mark.parametrize("wal", [False, True])
def test_publish_never_copies_the_whole_primary(tmp_path, monkeypatch, wal):
    root, source = _repo(tmp_path)
    if wal:
        source.with_name(f"{source.name}.wal").touch()
    monkeypatch.setattr(
        backup_database,
        "_copy_database",
        lambda *_args: (_ for _ in ()).throw(AssertionError("whole database copy used")),
    )

    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)

    assert manifest["row_counts"]["main.prices"] == 1


def test_semantic_mismatch_discards_generation(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    monkeypatch.setattr(
        publish_snapshot, "_verify_semantic_equality",
        lambda *_args: (_ for _ in ()).throw(
            publish_snapshot.SnapshotError("generation differs from source")
        ),
    )

    with pytest.raises(publish_snapshot.SnapshotError, match="differs from source"):
        publish_snapshot.publish_snapshot(root, source, now=NOW)

    directory = source.parent / "snapshots"
    assert not (directory / snapshots.LATEST_NAME).exists()
    assert not list(directory.glob("market-*.duckdb"))
    assert not list(directory.glob("market-*.json"))


def test_failed_publication_preserves_previous_latest(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    latest = source.parent / "snapshots" / snapshots.LATEST_NAME

    monkeypatch.setattr(
        publish_snapshot,
        "_build_hot_database",
        lambda *_args: (_ for _ in ()).throw(OSError("hot build failed")),
    )
    with pytest.raises(publish_snapshot.SnapshotError, match="hot build failed"):
        publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))

    assert os.readlink(latest) == first["snapshot"]
    assert len([path for path in latest.parent.glob("market-*.duckdb") if not path.is_symlink()]) == 1


def test_min_age_skip_is_successful_and_logged(tmp_path, monkeypatch, capsys):
    root, source = _repo(tmp_path)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    monkeypatch.setattr(
        publish_snapshot,
        "_unique_destination",
        lambda *_args: (_ for _ in ()).throw(AssertionError("copy was not skipped")),
    )

    status = publish_snapshot.main([
        "--repo-root", str(root),
        "--source", str(source),
        "--min-age-minutes", "120",
    ])

    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert output["status"] == "skipped"
    assert output["snapshot"] == first["snapshot"]
    assert "minimum age is 120 minutes" in output["reason"]


def test_latest_snapshot_requires_publication_after_database_write(tmp_path):
    root, source = _repo(tmp_path)
    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)

    assert snapshots.latest_snapshot(source, newer_than_database=True) is not None
    future = datetime.fromisoformat(manifest["as_of"]) + timedelta(seconds=1)
    os.utime(source, ns=(int(future.timestamp() * 1e9),) * 2)

    assert snapshots.latest_snapshot(source) is not None
    assert snapshots.latest_snapshot(source, newer_than_database=True) is None


def test_delta_generations_preserve_rows_share_parts_and_respect_reader_pins(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    publish_snapshot.publish_snapshot(root, source, now=NOW)
    pin = snapshots.pin_latest_generation(source)
    first_info = pin.info
    assert first_info.manifest_schema_version == 2
    assert {record["table"] for record in first_info.parts} == {
        "main.intraday_prices", "main.bitemporal_facts", "main.source_response_receipts",
    }
    first_part_paths = {record["path"] for record in first_info.parts}
    with duckdb.connect(str(first_info.path), read_only=True) as con:
        assert con.execute("SELECT response_body FROM source_response_receipts").fetchone() == (
            b"\x00\x01\x02",
        )
        assert con.execute(
            "SELECT COUNT(*) FROM actions_fetch_log WHERE ticker='DUP'"
        ).fetchone() == (2,)

    writer = duckdb.connect(str(source))
    writer.execute(
        "INSERT INTO bitemporal_facts VALUES "
        "(2,1,'SPY','SPY','fixture',TIMESTAMP '2019-01-01',NULL,"
        "TIMESTAMP '2026-10-02',TIMESTAMP '2026-10-02',2,'{}',?,"
        "'fixture','v1',?, ?, ?)",
        ["f" * 64, "c" * 64, "e" * 64, "1" * 64],
    )
    writer.execute("UPDATE prices SET volume=NULL")
    writer.execute("DELETE FROM jobs WHERE id=1")
    writer.close()
    second = publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))
    third = publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=2))

    assert first_info.path.exists(), "a pinned old generation must survive retention"
    second_part_paths = {record["path"] for record in second["parts"]}
    assert first_part_paths & second_part_paths
    assert len({record["partition"] for record in second["parts"]
                if record["table"] == "main.bitemporal_facts"}) == 2
    assert second["metrics"]["cold_copy_operations"] == 2
    assert third["metrics"]["cold_copy_operations"] == 1
    assert third["metrics"]["cold_frontier_reused_parts"] == 3
    assert third["metrics"]["cold_bytes_read"] > 0
    assert third["metrics"]["cold_bytes_serialized"] > 0
    assert third["metrics"]["cold_verification_rows"] == 4
    assert third["metrics"]["cold_verification_seconds"] >= 0
    assert all(record["key_min"] and record["key_max"] for record in third["parts"])
    latest = snapshots.pin_latest_generation(source)
    try:
        assert latest.info.generation_id == Path(third["snapshot"]).stem
        with duckdb.connect(str(latest.info.path), read_only=True) as con:
            assert con.execute(
                "SELECT event_at, revision FROM bitemporal_facts ORDER BY id"
            ).fetchall() == [
                (datetime(2020, 1, 1), 1),
                (datetime(2019, 1, 1), 2),
            ]
            assert con.execute("SELECT volume FROM prices").fetchone() == (None,)
            assert con.execute("SELECT COUNT(*) FROM jobs").fetchone() == (0,)
            assert con.execute(
                "SELECT COUNT(*) FROM actions_fetch_log WHERE ticker='DUP'"
            ).fetchone() == (2,)
    finally:
        latest.close()
    pin.close()
    publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=3))
    assert not first_info.path.exists()


@pytest.mark.parametrize("mutation", ["update", "delete-insert"])
def test_same_count_cold_correction_never_publishes_stale_parts(tmp_path, mutation):
    root, source = _repo(tmp_path, cold=True)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    writer = duckdb.connect(str(source))
    try:
        if mutation == "update":
            writer.execute(
                "UPDATE bitemporal_facts SET revision=9, "
                "normalized_payload='{\"corrected\":true}' WHERE id=1"
            )
        else:
            row = list(writer.execute(
                "SELECT * FROM bitemporal_facts WHERE id=1"
            ).fetchone())
            row[9] = 9
            row[10] = '{"corrected":true}'
            writer.execute("DELETE FROM bitemporal_facts WHERE id=1")
            writer.execute(
                "INSERT INTO bitemporal_facts VALUES " + "(" + ",".join("?" for _ in row) + ")",
                row,
            )
    finally:
        writer.close()

    with pytest.raises(publish_snapshot.SnapshotError, match="differs from source table"):
        publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))

    with snapshots.pin_latest_generation(source) as info:
        assert info.generation_id == Path(first["snapshot"]).stem
        with duckdb.connect(str(info.path), read_only=True) as con:
            assert con.execute(
                "SELECT revision,normalized_payload FROM bitemporal_facts WHERE id=1"
            ).fetchone() == (1, "{}")


def test_non_frontier_cold_partition_is_rebuilt_after_same_count_update(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    publish_snapshot.publish_snapshot(root, source, now=NOW)
    writer = duckdb.connect(str(source))
    writer.execute("UPDATE intraday_prices SET volume=999 WHERE ticker='SPY'")
    writer.close()

    second = publish_snapshot.publish_snapshot(
        root, source, now=NOW + timedelta(seconds=1),
    )

    assert second["metrics"]["cold_copy_operations"] >= 1
    with snapshots.pin_latest_generation(source) as info:
        with duckdb.connect(str(info.path), read_only=True) as con:
            assert con.execute(
                "SELECT volume FROM intraday_prices WHERE ticker='SPY'"
            ).fetchone() == (999,)


def test_generation_pin_refuses_a_corrupt_cold_part(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)
    part = source.parent / "snapshots" / manifest["parts"][0]["path"]
    part.chmod(0o600)
    part.write_bytes(part.read_bytes() + b"corrupt")

    with pytest.raises(snapshots.GenerationError, match="no valid published generation"):
        snapshots.pin_latest_generation(source)


def test_eight_generation_readers_do_not_contend_with_primary_writer(tmp_path, monkeypatch):
    root, source = _repo(tmp_path, cold=True)
    publish_snapshot.publish_snapshot(root, source, now=NOW)
    writer = duckdb.connect(str(source))
    monkeypatch.setattr(engine_db.settings, "DEFAULT_DB", source)

    def read_generation(_index):
        with engine_db.connect(source, read_only=True, wait_s=0) as con:
            return con.execute(
                "SELECT COUNT(*), MIN(event_at) FROM bitemporal_facts"
            ).fetchone()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(read_generation, range(8))) == [
                (1, datetime(2020, 1, 1))
            ] * 8
    finally:
        writer.close()


def test_failed_pointer_swap_keeps_prior_generation_and_prunes_new_parts(
    tmp_path, monkeypatch,
):
    root, source = _repo(tmp_path, cold=True)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    first_parts = {record["path"] for record in first["parts"]}
    con = duckdb.connect(str(source))
    con.execute(
        "INSERT INTO bitemporal_facts VALUES "
        "(2,1,'SPY','SPY','fixture',TIMESTAMP '2019-01-01',NULL,"
        "TIMESTAMP '2026-10-02',TIMESTAMP '2026-10-02',2,'{}',?,"
        "'fixture','v1',?, ?, ?)",
        ["f" * 64, "c" * 64, "e" * 64, "1" * 64],
    )
    con.close()
    monkeypatch.setattr(
        publish_snapshot,
        "_swap_latest",
        lambda *_args: (_ for _ in ()).throw(OSError("pointer swap failed")),
    )

    with pytest.raises(publish_snapshot.SnapshotError, match="pointer swap failed"):
        publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))

    info = snapshots.latest_snapshot(source)
    assert info is not None and info.generation_id == Path(first["snapshot"]).stem
    remaining_parts = {
        path.relative_to(source.parent / "snapshots").as_posix()
        for path in (source.parent / "snapshots" / "parts").rglob("*.parquet")
    }
    assert remaining_parts == first_parts


def test_reader_refuses_generation_from_newer_database_schema(tmp_path):
    root, source = _repo(tmp_path)
    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)
    manifest_path = source.parent / "snapshots" / Path(manifest["snapshot"]).with_suffix(".json")
    payload = json.loads(manifest_path.read_text())
    payload.pop("manifest_sha256")
    payload["database_schema_id"] = 2
    payload["manifest_sha256"] = backup_database.canonical_sha256(payload)
    manifest_path.write_text(json.dumps(payload))

    assert snapshots.latest_snapshot(source) is None


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("migration_sha256", "f" * 64, "hash does not match source"),
        ("source_commit", "not-a-git-commit", "source commit is invalid"),
    ],
)
def test_publisher_uses_exact_shared_schema_verifier(
    tmp_path, column, value, message,
):
    root, source = _repo(tmp_path)
    con = duckdb.connect(str(source))
    con.execute(f"UPDATE schema_migrations SET {column}=?", [value])
    con.close()

    with pytest.raises(publish_snapshot.SnapshotError, match=message):
        publish_snapshot.publish_snapshot(root, source, now=NOW)


def test_corrupt_recent_generation_is_republished_not_throttled(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    part = source.parent / "snapshots" / first["parts"][0]["path"]
    content = bytearray(part.read_bytes())
    content[len(content) // 2] ^= 1
    part.chmod(0o600)
    part.write_bytes(content)

    replacement = publish_snapshot.publish_snapshot(
        root, source, now=NOW + timedelta(seconds=1), min_age_minutes=120,
    )

    assert replacement.get("status") != "skipped"
    with snapshots.pin_latest_generation(source) as info:
        assert info.generation_id == Path(replacement["snapshot"]).stem


def test_publication_and_failure_pruning_are_serialized(tmp_path, monkeypatch):
    root, source = _repo(tmp_path, cold=True)
    reached_manifest = threading.Event()
    release_manifest = threading.Event()
    second_started = threading.Event()
    original_write = publish_snapshot._write_manifest
    original_build = publish_snapshot._build_hot_database

    def paused_write(path, manifest):
        if threading.current_thread().name == "publisher-a":
            reached_manifest.set()
            assert release_manifest.wait(10)
        return original_write(path, manifest)

    def failing_second(*args, **kwargs):
        if threading.current_thread().name == "publisher-b":
            raise OSError("second publisher failed")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(publish_snapshot, "_write_manifest", paused_write)
    monkeypatch.setattr(publish_snapshot, "_build_hot_database", failing_second)
    results = {}

    def run_a():
        results["a"] = publish_snapshot.publish_snapshot(root, source, now=NOW)

    def run_b():
        second_started.set()
        try:
            publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))
        except publish_snapshot.SnapshotError as exc:
            results["b"] = str(exc)

    first_thread = threading.Thread(target=run_a, name="publisher-a")
    second_thread = threading.Thread(target=run_b, name="publisher-b")
    first_thread.start()
    assert reached_manifest.wait(10)
    second_thread.start()
    assert second_started.wait(10)
    second_thread.join(0.1)
    assert second_thread.is_alive(), "second publisher did not wait for publication lock"
    release_manifest.set()
    first_thread.join(20)
    second_thread.join(20)

    assert results["b"] == "second publisher failed"
    with snapshots.pin_latest_generation(source) as info:
        assert info.generation_id == Path(results["a"]["snapshot"]).stem


def test_new_payload_directory_chain_is_synced_before_pointer(tmp_path, monkeypatch):
    root, source = _repo(tmp_path, cold=True)
    synced = []
    original_sync = publish_snapshot._sync_directory

    def recording_sync(path):
        snapshots_root = source.parent / "snapshots"
        synced.append(
            path.relative_to(snapshots_root).as_posix()
            if path.is_relative_to(snapshots_root)
            else "parent"
        )
        original_sync(path)

    monkeypatch.setattr(publish_snapshot, "_sync_directory", recording_sync)
    publish_snapshot.publish_snapshot(root, source, now=NOW)

    assert "parts" in synced
    assert "parts/intraday_prices" in synced
    assert "blobs" in synced
    assert any(value.startswith("blobs/") for value in synced)
    assert synced[-1] == "."


@pytest.mark.parametrize("failure", ["part-directory", "blob-prefix"])
def test_directory_fsync_failure_never_advances_pointer(tmp_path, monkeypatch, failure):
    root, source = _repo(tmp_path, cold=failure == "part-directory")
    original_sync = publish_snapshot._sync_directory

    def failing_sync(path):
        snapshots_root = source.parent / "snapshots"
        relative = (
            path.relative_to(snapshots_root)
            if path.is_relative_to(snapshots_root)
            else Path("parent")
        )
        is_part = failure == "part-directory" and path.name == "intraday_prices"
        is_blob = (
            failure == "blob-prefix"
            and len(relative.parts) == 2
            and relative.parts[0] == "blobs"
        )
        if is_part or is_blob:
            raise OSError(f"{failure} fsync failed")
        original_sync(path)

    monkeypatch.setattr(publish_snapshot, "_sync_directory", failing_sync)

    with pytest.raises(publish_snapshot.SnapshotError, match="fsync failed"):
        publish_snapshot.publish_snapshot(root, source, now=NOW)
    assert not (source.parent / "snapshots" / snapshots.LATEST_NAME).exists()


def test_metadata_resolver_holds_generation_pin_for_direct_snapshot_reader(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    resolved = snapshots.latest_snapshot(source)
    assert resolved is not None and resolved._lifetime_pin is not None

    publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))
    publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=2))
    first_path = source.parent / "snapshots" / first["snapshot"]
    assert first_path.exists()

    resolved._lifetime_pin.close()
    publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=3))
    assert not first_path.exists()


def test_crash_orphan_never_displaces_a_valid_rollback_generation(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    valid = []
    for offset in range(2):
        path = directory / f"market-20261002T12000{offset}000000Z.duckdb"
        path.write_bytes(f"valid-{offset}".encode())
        manifest = {
            "schema_version": 1,
            "snapshot": path.name,
            "source_database": "store/market.duckdb",
            "source_data_commit": None,
            "as_of": (NOW + timedelta(seconds=offset)).isoformat(),
            "size_bytes": path.stat().st_size,
            "sha256": publish_snapshot._sha256(path),
            "row_counts": {},
        }
        path.with_suffix(".json").write_text(json.dumps(manifest))
        valid.append(path)
    second_path = valid[-1]
    orphan = directory / "market-20261002T120001500000Z.duckdb"
    orphan.write_bytes(b"crash orphan")

    current = directory / "market-20261002T120002000000Z.duckdb"
    current.write_bytes(b"current")
    current.with_suffix(".json").write_text(json.dumps({
        "schema_version": 1,
        "snapshot": current.name,
        "source_database": "store/market.duckdb",
        "source_data_commit": None,
        "as_of": (NOW + timedelta(seconds=2)).isoformat(),
        "size_bytes": current.stat().st_size,
        "sha256": publish_snapshot._sha256(current),
        "row_counts": {},
    }))
    publish_snapshot._retain_newest(directory)

    assert second_path.exists()
    assert not orphan.exists()
    assert len([
        path for path in directory.glob("market-*.duckdb") if not path.is_symlink()
    ]) == 2
