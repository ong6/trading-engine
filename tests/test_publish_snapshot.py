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


def test_publish_is_atomic_retains_latest_plus_one_and_records_manifest(tmp_path):
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


def _fake_snapshot(directory: Path, stamp: str, *, size: int = 8, manifest: bool = True,
                   recorded_size: int | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"market-{stamp}.duckdb"
    path.write_bytes(b"x" * size)
    if manifest:
        path.with_suffix(".json").write_text(json.dumps({
            "schema_version": 1,
            "snapshot": path.name,
            "source_database": "store/market.duckdb",
            "source_data_commit": None,
            "as_of": NOW.isoformat(),
            "size_bytes": size if recorded_size is None else recorded_size,
            "sha256": "0" * 64,
            "row_counts": {"main.prices": 1},
        }))
    return path


def _point_latest(directory: Path, snapshot: Path) -> None:
    os.symlink(snapshot.name, directory / snapshots.LATEST_NAME)


def test_retention_skips_unverified_copies_when_counting_previous(tmp_path):
    directory = tmp_path / "store" / "snapshots"
    verified = _fake_snapshot(directory, "20261001T000000000000Z")
    truncated = _fake_snapshot(directory, "20261002T000000000000Z", recorded_size=99)
    orphan = _fake_snapshot(directory, "20261003T000000000000Z", manifest=False)
    latest = _fake_snapshot(directory, "20261004T000000000000Z")
    _point_latest(directory, latest)

    publish_snapshot._retain_newest(directory)

    assert verified.exists() and latest.exists()
    assert not truncated.exists() and not truncated.with_suffix(".json").exists()
    assert not orphan.exists()
    assert os.readlink(directory / snapshots.LATEST_NAME) == latest.name


def test_retention_never_deletes_the_snapshot_market_latest_names(tmp_path):
    directory = tmp_path / "store" / "snapshots"
    oldest = _fake_snapshot(directory, "20261001T000000000000Z")
    previous = _fake_snapshot(directory, "20261002T000000000000Z")
    # market-latest names an unverified copy that is older than a newer file
    # (a publication in flight); both stay, with one verified previous copy.
    latest = _fake_snapshot(directory, "20261003T000000000000Z", recorded_size=1)
    in_flight = _fake_snapshot(directory, "20261004T000000000000Z", manifest=False)
    _point_latest(directory, latest)

    plan = snapshots.retention_plan(directory, keep_previous=1)

    assert plan.latest == latest
    assert plan.keep == (previous, latest, in_flight)
    assert plan.delete == (oldest,)
    publish_snapshot._retain_newest(directory, keep_previous=0)
    assert sorted(path.name for path in directory.glob("market-2*.duckdb")) == [
        latest.name, in_flight.name,
    ]


def test_retention_deletes_nothing_without_a_valid_latest(tmp_path):
    directory = tmp_path / "store" / "snapshots"
    first = _fake_snapshot(directory, "20261001T000000000000Z")
    second = _fake_snapshot(directory, "20261002T000000000000Z")
    third = _fake_snapshot(directory, "20261003T000000000000Z")

    publish_snapshot._retain_newest(directory)
    assert first.exists() and second.exists() and third.exists()

    os.symlink("../market.duckdb", directory / snapshots.LATEST_NAME)
    assert snapshots.retention_plan(directory).delete == ()


def test_retention_orders_same_microsecond_suffixes_after_the_base_name(tmp_path):
    directory = tmp_path / "store" / "snapshots"
    base = _fake_snapshot(directory, "20261001T000000000000Z")
    suffixed = _fake_snapshot(directory, "20261001T000000000000Z-1")
    newest = _fake_snapshot(directory, "20261001T000000000001Z")
    _point_latest(directory, newest)

    plan = snapshots.retention_plan(directory, keep_previous=1)

    assert plan.keep == (suffixed, newest) and plan.delete == (base,)


def test_retention_dry_run_lists_without_publishing_deleting_or_opening(
    tmp_path, monkeypatch, capsys,
):
    root = tmp_path / "repo"
    source = root / "store" / "market.duckdb"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"d" * 32)
    directory = source.parent / "snapshots"
    oldest = _fake_snapshot(directory, "20261001T000000000000Z", size=16)
    previous = _fake_snapshot(directory, "20261002T000000000000Z", size=16)
    latest = _fake_snapshot(directory, "20261003T000000000000Z", size=16)
    _point_latest(directory, latest)
    monkeypatch.setattr(
        publish_snapshot.duckdb, "connect",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("database opened")),
    )
    monkeypatch.setattr(
        publish_snapshot, "_unique_destination",
        lambda *_args: (_ for _ in ()).throw(AssertionError("publication attempted")),
    )

    status = publish_snapshot.main([
        "--repo-root", str(root), "--source", str(source), "--retention-dry-run",
    ])

    output = json.loads(capsys.readouterr().out)
    assert status == 0 and output["status"] == "dry-run"
    assert output["latest"] == latest.name
    assert [item["snapshot"] for item in output["keep"]] == [previous.name, latest.name]
    assert output["delete"] == [
        {"snapshot": oldest.name, "size_bytes": 16, "verified": True},
    ]
    assert output["snapshot_soft_cap_gb"] == publish_snapshot.resources.SNAPSHOT_SOFT_GB
    assert output["store_soft_cap_gb"] == publish_snapshot.resources.STORE_SOFT_GB
    assert {"snapshots_gb", "store_gb_excluding_snapshots"} <= output.keys()
    assert oldest.exists() and previous.exists()
