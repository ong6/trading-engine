"""Atomic read-only database snapshot publication and discovery."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from engine import schema_migrations
from engine.lib import snapshots
from tools import backup_database, publish_snapshot

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def _database(path: Path, *, cold: bool = False) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE prices (date DATE, ticker VARCHAR, volume BIGINT)")
    con.execute("INSERT INTO prices VALUES ('2026-10-01', 'SPY', 1)")
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
    if cold:
        con.execute(
            "CREATE TABLE intraday_prices (ticker VARCHAR, ts TIMESTAMP, interval VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, "
            "source VARCHAR, as_of DATE, PRIMARY KEY(ticker, ts, interval))"
        )
        con.execute(
            "INSERT INTO intraday_prices VALUES "
            "('SPY','2026-10-01 14:30:00','1m',1,2,1,2,10,'fixture','2026-10-01')"
        )
        con.execute(
            "CREATE TABLE source_response_receipts (id BIGINT PRIMARY KEY, "
            "received_at TIMESTAMP NOT NULL, response_body BLOB NOT NULL)"
        )
        con.execute(
            "INSERT INTO source_response_receipts VALUES "
            "(1, '2026-10-01 12:00:00', from_base64('AAEC'))"
        )
        con.execute(
            "CREATE TABLE bitemporal_facts (id BIGINT PRIMARY KEY, event_at TIMESTAMP, "
            "available_at TIMESTAMP, ingested_at TIMESTAMP NOT NULL, revision INTEGER, "
            "payload VARCHAR)"
        )
        con.execute(
            "INSERT INTO bitemporal_facts VALUES "
            "(1, '2020-01-01', '2026-10-01', '2026-10-01', 1, 'old event')"
        )
        con.execute("CREATE TABLE duplicate_events (value INTEGER)")
        con.execute("INSERT INTO duplicate_events VALUES (7), (7)")
        con.execute("INSERT INTO jobs VALUES (1, 'running')")
    catalog_hash = schema_migrations.catalog_sha256(con)
    migration = schema_migrations.migrations()[0]
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


def test_publish_uses_file_copy_fast_path_without_wal(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    copied = []
    events = []
    original_copyfile = publish_snapshot.shutil.copyfile
    original_invariants = publish_snapshot._database_invariants
    original_window = backup_database._exclusive_backup_window

    @contextmanager
    def window(*args, **kwargs):
        events.append("lock-enter")
        with original_window(*args, **kwargs):
            yield
        events.append("lock-exit")

    def copyfile(source_path, destination_path):
        events.append("file-copy")
        copied.append((source_path, destination_path))
        return original_copyfile(source_path, destination_path)

    def invariants(path, alias):
        events.append(alias)
        return original_invariants(path, alias)

    monkeypatch.setattr(backup_database, "_exclusive_backup_window", window)
    monkeypatch.setattr(publish_snapshot.shutil, "copyfile", copyfile)
    monkeypatch.setattr(publish_snapshot, "_database_invariants", invariants)
    monkeypatch.setattr(
        backup_database,
        "_copy_database",
        lambda *_args: (_ for _ in ()).throw(AssertionError("COPY fallback used")),
    )

    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)

    assert len(copied) == 1
    assert manifest["row_counts"]["main.prices"] == 1
    assert events == [
        "lock-enter",
        "snapshot_source",
        "file-copy",
        "lock-exit",
        "snapshot_copy",
    ]


def test_publish_falls_back_to_duckdb_copy_when_wal_exists(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    source.with_name(f"{source.name}.wal").touch()
    calls = []
    original_copy_database = backup_database._copy_database

    def copy_database(source_path, destination_path):
        calls.append((source_path, destination_path))
        return original_copy_database(source_path, destination_path)

    monkeypatch.setattr(backup_database, "_copy_database", copy_database)
    monkeypatch.setattr(
        publish_snapshot,
        "_copy_file_durable",
        lambda *_args: (_ for _ in ()).throw(AssertionError("fast path used")),
    )
    monkeypatch.setattr(
        publish_snapshot,
        "_database_invariants",
        lambda *_args: (_ for _ in ()).throw(AssertionError("fast verification used")),
    )

    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)

    assert len(calls) == 1
    assert manifest["row_counts"]["main.prices"] == 1


def test_fast_path_invariant_mismatch_discards_copy(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    original_invariants = publish_snapshot._database_invariants

    def mismatched(path, alias):
        result = original_invariants(path, alias)
        if alias == "snapshot_copy":
            result = {**result, "table_count": result["table_count"] + 1}
        return result

    monkeypatch.setattr(publish_snapshot, "_database_invariants", mismatched)

    with pytest.raises(publish_snapshot.SnapshotError, match="invariants do not match"):
        publish_snapshot.publish_snapshot(root, source, now=NOW)

    directory = source.parent / "snapshots"
    assert not (directory / snapshots.LATEST_NAME).exists()
    assert list(directory.iterdir()) == []


def test_failed_publication_preserves_previous_latest(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    latest = source.parent / "snapshots" / snapshots.LATEST_NAME

    monkeypatch.setattr(
        publish_snapshot,
        "_copy_file_durable",
        lambda *_args: (_ for _ in ()).throw(OSError("copy failed")),
    )
    with pytest.raises(publish_snapshot.SnapshotError, match="copy failed"):
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
    first_info = snapshots.latest_snapshot(source)
    assert first_info is not None
    assert first_info.manifest_schema_version == 2
    assert {record["table"] for record in first_info.parts} == {
        "main.intraday_prices", "main.bitemporal_facts", "main.source_response_receipts",
    }
    first_part_paths = {record["path"] for record in first_info.parts}
    with duckdb.connect(str(first_info.path), read_only=True) as con:
        assert con.execute("SELECT response_body FROM source_response_receipts").fetchone() == (
            b"\x00\x01\x02",
        )
        assert con.execute("SELECT COUNT(*) FROM duplicate_events").fetchone() == (2,)

    pin = snapshots.pin_latest_generation(source)
    writer = duckdb.connect(str(source))
    writer.execute(
        "INSERT INTO bitemporal_facts VALUES "
        "(2, '2019-01-01', '2026-10-02', '2026-10-02', 2, 'late old event')"
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
            assert con.execute("SELECT COUNT(*) FROM duplicate_events").fetchone() == (2,)
    finally:
        latest.close()
    pin.close()
    publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=3))
    assert not first_info.path.exists()


def test_generation_pin_refuses_a_corrupt_cold_part(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)
    part = source.parent / "snapshots" / manifest["parts"][0]["path"]
    part.chmod(0o600)
    part.write_bytes(part.read_bytes() + b"corrupt")

    with pytest.raises(snapshots.GenerationError, match="no valid published generation"):
        snapshots.pin_latest_generation(source)


def test_eight_generation_readers_do_not_contend_with_primary_writer(tmp_path):
    root, source = _repo(tmp_path, cold=True)
    publish_snapshot.publish_snapshot(root, source, now=NOW)
    writer = duckdb.connect(str(source))

    def read_generation(_index):
        pin = snapshots.pin_latest_generation(source)
        try:
            with duckdb.connect(str(pin.info.path), read_only=True) as con:
                return con.execute(
                    "SELECT COUNT(*), MIN(event_at) FROM bitemporal_facts"
                ).fetchone()
        finally:
            pin.close()

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
        "(2, '2019-01-01', '2026-10-02', '2026-10-02', 2, 'late')"
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
    payload["database_schema_id"] = 1
    payload["manifest_sha256"] = backup_database.canonical_sha256(payload)
    manifest_path.write_text(json.dumps(payload))

    assert snapshots.latest_snapshot(source) is None
