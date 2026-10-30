"""API database connections fail closed on transient DuckDB contention."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from engine import schema_migrations
from engine.lib.db import DBBusyError
from server import db


def test_different_connection_configuration_is_busy(monkeypatch):
    def conflict(*args, **kwargs):
        raise duckdb.ConnectionException(
            "Can't open a connection to same database file with a different configuration "
            "than existing connections"
        )

    monkeypatch.setattr(db.engine_db, "connect", conflict)

    with pytest.raises(DBBusyError, match="different configuration"):
        db.write_con()


def test_unrelated_connection_failure_is_not_mislabeled_busy(monkeypatch):
    def broken(*args, **kwargs):
        raise duckdb.ConnectionException("corrupt database header")

    monkeypatch.setattr(db.engine_db, "connect", broken)
    monkeypatch.setattr(
        db,
        "pin_latest_generation",
        lambda *_args, **_kwargs: SimpleNamespace(
            info=SimpleNamespace(path="generation.duckdb"), close=lambda: None,
        ),
    )

    with pytest.raises(duckdb.ConnectionException, match="corrupt database header"):
        db.read_con()


def test_missing_generation_never_opens_unversioned_primary(tmp_path, monkeypatch):
    database = tmp_path / "legacy.duckdb"
    duckdb.connect(str(database)).close()
    monkeypatch.setattr(db, "DEFAULT_DB", database)
    opened = []
    monkeypatch.setattr(
        db.engine_db, "connect", lambda *_args, **_kwargs: opened.append(True),
    )

    with pytest.raises(DBBusyError, match="no valid published generation"):
        db.read_con()
    assert opened == []


def test_versioned_store_without_generation_fails_closed(tmp_path, monkeypatch):
    database = tmp_path / "versioned.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE marker (id INTEGER)")
    catalog_hash = schema_migrations.catalog_sha256(connection)
    migration = schema_migrations.migrations()[0]
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
    monkeypatch.setattr(db, "DEFAULT_DB", Path(database))

    with pytest.raises(DBBusyError, match="no valid published generation"):
        db.read_con()


def test_newest_generation_is_served_and_flagged_never_refused(monkeypatch, tmp_path):
    calls = []
    connection = SimpleNamespace(close=lambda: None)
    primary = tmp_path / "market.duckdb"
    primary.write_bytes(b"primary")
    monkeypatch.setattr(db, "DEFAULT_DB", primary)
    captured = db.source_storage_identity(primary)

    def pin(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            info=SimpleNamespace(
                path=Path("generation.duckdb"),
                as_of=datetime.now(timezone.utc) - timedelta(hours=4),
                generation_id="market-20261019T000000000000Z",
                source_storage_identity=captured,
            ),
            close=lambda: None,
        )

    monkeypatch.setattr(db, "pin_latest_generation", pin)
    monkeypatch.setattr(db.engine_db, "connect", lambda *_args, **_kwargs: connection)

    with db.response_data_source() as state:
        db.read_con().close()
        board = state["generation"]
    primary.write_bytes(b"primary after an unpublished write")
    with db.response_data_source() as state, db.require_fresh_evidence_snapshot():
        db.read_con().close()
        evidence = state["generation"]

    assert calls == [{}, {}]  # no freshness refusal for either dataset
    assert board["generation_id"] == "market-20261019T000000000000Z"
    # four hours old (past the evidence budget) but identical to the primary: not stale
    assert (board["stale"], board["pending_publication"]) == (False, False)
    assert (evidence["stale"], evidence["pending_publication"]) == (True, True)
    assert evidence["budget_seconds"] == db.DATASET_GENERATION_MAX_AGE["evidence"].seconds


def test_only_a_missing_generation_refuses(monkeypatch):
    monkeypatch.setattr(
        db, "pin_latest_generation",
        lambda *_a, **_k: (_ for _ in ()).throw(db.GenerationError("no valid published generation")),
    )
    with pytest.raises(db.DBBusyError, match="no valid published generation"):
        db.read_con()




def test_api_write_waits_out_a_short_publication_lock(monkeypatch, tmp_path):
    import threading
    import time

    primary = tmp_path / "market.duckdb"
    duckdb.connect(str(primary)).close()
    monkeypatch.setattr(db, "DEFAULT_DB", primary)
    monkeypatch.setattr(db, "API_WRITE_WAIT_S", 10.0)
    reader = duckdb.connect(str(primary), read_only=True)  # a publication's capture handle
    threading.Timer(1.0, reader.close).start()
    started = time.monotonic()

    con = db.write_con()
    con.close()

    assert 0.5 < time.monotonic() - started < 10
