"""Atomic read-only database snapshot publication and discovery."""
from __future__ import annotations

import json
import os
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


def test_failed_publication_preserves_previous_latest(tmp_path, monkeypatch):
    root, source = _repo(tmp_path)
    first = publish_snapshot.publish_snapshot(root, source, now=NOW)
    latest = source.parent / "snapshots" / snapshots.LATEST_NAME

    monkeypatch.setattr(
        backup_database,
        "_copy_database",
        lambda *_args: (_ for _ in ()).throw(backup_database.BackupError("copy failed")),
    )
    with pytest.raises(publish_snapshot.SnapshotError, match="copy failed"):
        publish_snapshot.publish_snapshot(root, source, now=NOW + timedelta(seconds=1))

    assert os.readlink(latest) == first["snapshot"]
    assert len([path for path in latest.parent.glob("market-*.duckdb") if not path.is_symlink()]) == 1


def test_latest_snapshot_requires_publication_after_database_write(tmp_path):
    root, source = _repo(tmp_path)
    manifest = publish_snapshot.publish_snapshot(root, source, now=NOW)

    assert snapshots.latest_snapshot(source, newer_than_database=True) is not None
    future = datetime.fromisoformat(manifest["as_of"]) + timedelta(seconds=1)
    os.utime(source, ns=(int(future.timestamp() * 1e9),) * 2)

    assert snapshots.latest_snapshot(source) is not None
    assert snapshots.latest_snapshot(source, newer_than_database=True) is None
