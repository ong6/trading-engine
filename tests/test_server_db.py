"""API database connections fail closed on transient DuckDB contention."""

from datetime import datetime, timezone
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


def test_dataset_freshness_and_generation_identity_are_forwarded(monkeypatch):
    calls = []
    connection = SimpleNamespace(close=lambda: None)

    def pin(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            info=SimpleNamespace(
                path=Path("generation.duckdb"),
                as_of=datetime(2026, 10, 19, tzinfo=timezone.utc),
                generation_id="market-20261019T000000000000Z",
            ),
            close=lambda: None,
        )

    monkeypatch.setattr(db, "pin_latest_generation", pin)
    monkeypatch.setattr(db.engine_db, "connect", lambda *_args, **_kwargs: connection)

    with db.response_data_source() as state:
        db.read_con().close()
        assert state["generation_id"] == "market-20261019T000000000000Z"
    with db.require_fresh_evidence_snapshot():
        db.read_con().close()

    assert calls[0] == {
        "newer_than_database": False,
        "max_age": db.DATASET_GENERATION_MAX_AGE["board"],
    }
    assert calls[1] == {
        "newer_than_database": True,
        "max_age": db.DATASET_GENERATION_MAX_AGE["evidence"],
    }
