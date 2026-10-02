"""Atomic read-only database snapshot publication and discovery."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from engine.lib import snapshots
from tools import backup_database, publish_snapshot

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def _database(path: Path) -> None:
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
    con.close()


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    source = root / "store" / "market.duckdb"
    source.parent.mkdir(parents=True)
    _database(source)
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
    assert manifest["size_bytes"] == latest.resolve().stat().st_size
    assert len(manifest["sha256"]) == 64
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

    def copy_database(source_path, destination_path):
        calls.append((source_path, destination_path))
        publish_snapshot.shutil.copyfile(source_path, destination_path)
        return {"row_counts": {"main.prices": 1}}

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
    assert manifest["row_counts"] == {"main.prices": 1}


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
