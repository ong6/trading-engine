"""Store limits: free-space reserve for writes, backups and snapshots; DuckDB connection limits."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from engine.lib import store_limits

GIB = store_limits.GIB
Usage = namedtuple("Usage", "total used free")


def _usage(free_gib: float):
    return lambda _path: Usage(500 * GIB, 0, int(free_gib * GIB))


def test_refuses_before_the_reserve_with_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv(store_limits.MIN_FREE_ENV, raising=False)
    target = tmp_path / "store" / "snapshots" / "market-new.duckdb"

    report = store_limits.require_free_space(target, purpose="publish a snapshot",
                                           need_bytes=12 * GIB, disk_usage=_usage(22.5))
    assert report["path"] == str(tmp_path)
    assert report["reserve_bytes"] == 10 * GIB

    with pytest.raises(store_limits.DiskSpaceError) as refused:
        store_limits.require_free_space(target, purpose="publish a snapshot",
                                      need_bytes=12 * GIB, disk_usage=_usage(21.9))
    message = str(refused.value)
    assert message.startswith("refusing publish a snapshot: 21.9 GiB free")
    assert "needs 12.0 GiB plus the 10.0 GiB reserve" in message


def test_reserve_is_configurable_and_validated(tmp_path, monkeypatch):
    monkeypatch.setenv(store_limits.MIN_FREE_ENV, "0")
    store_limits.require_free_space(tmp_path, purpose="x", disk_usage=_usage(0.1))
    monkeypatch.setenv(store_limits.MIN_FREE_ENV, "50")
    with pytest.raises(store_limits.DiskSpaceError, match="50.0 GiB reserve"):
        store_limits.require_free_space(tmp_path, purpose="x", disk_usage=_usage(49))
    for bad in ("-1", "lots"):
        monkeypatch.setenv(store_limits.MIN_FREE_ENV, bad)
        with pytest.raises(store_limits.DiskSpaceError, match=store_limits.MIN_FREE_ENV):
            store_limits.reserve_bytes()


def test_only_the_checkout_store_tree_is_guarded_for_writers(tmp_path):
    assert store_limits.store_path_guarded(store_limits.STORE_ROOT / "market.duckdb")
    assert store_limits.store_path_guarded(store_limits.STORE_ROOT / "pit" / "free-sources.duckdb")
    assert not store_limits.store_path_guarded(tmp_path / "store" / "market.duckdb")
    assert not store_limits.store_path_guarded(Path("/") / "elsewhere.duckdb")


def test_a_store_path_through_a_symlinked_home_is_still_guarded(tmp_path, monkeypatch):
    real_home = tmp_path / "volume" / "home"
    store = real_home / "trading-engine" / "store"
    (store / "pit").mkdir(parents=True)
    link_home = tmp_path / "home"
    link_home.symlink_to(real_home)
    monkeypatch.setattr(store_limits, "STORE_ROOT", store)

    assert store_limits.store_path_guarded(link_home / "trading-engine/store/market.duckdb")
    assert store_limits.store_path_guarded(link_home / "trading-engine/store/pit/new.duckdb")
    monkeypatch.setattr(store_limits, "STORE_ROOT", link_home / "trading-engine" / "store")
    assert store_limits.store_path_guarded(store / "pit" / "massive-minute.duckdb")
    assert not store_limits.store_path_guarded(link_home / "trading-engine" / "scratch.duckdb")


def test_file_bytes_counts_the_wal(tmp_path):
    database = tmp_path / "x.duckdb"
    assert store_limits.file_bytes(database) == 0
    database.write_bytes(b"a" * 10)
    Path(f"{database}.wal").write_bytes(b"b" * 5)
    assert store_limits.file_bytes(database) == 15


def test_duckdb_limits_default_by_role_and_follow_the_environment(monkeypatch):
    monkeypatch.delenv(store_limits.DUCKDB_THREADS_ENV, raising=False)
    monkeypatch.delenv(store_limits.DUCKDB_MEMORY_ENV, raising=False)
    assert store_limits.duckdb_limits(True) == store_limits.DUCKDB_READER_LIMITS
    assert store_limits.duckdb_limits(False) == store_limits.DUCKDB_WRITER_LIMITS
    monkeypatch.setenv(store_limits.DUCKDB_THREADS_ENV, "2")
    monkeypatch.setenv(store_limits.DUCKDB_MEMORY_ENV, "1GB")
    assert store_limits.duckdb_limits(False) == (2, "1GB")
    for name, bad in ((store_limits.DUCKDB_THREADS_ENV, "0"), (store_limits.DUCKDB_MEMORY_ENV, "x'")):
        monkeypatch.setenv(name, bad)
        with pytest.raises(ValueError):
            store_limits.duckdb_limits(True)
        monkeypatch.setenv(name, "2" if name == store_limits.DUCKDB_THREADS_ENV else "1GB")
