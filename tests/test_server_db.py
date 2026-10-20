"""API database connections fail closed on transient DuckDB contention."""

import duckdb
import pytest

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

    with pytest.raises(duckdb.ConnectionException, match="corrupt database header"):
        db.read_con()


def test_slow_route_reads_a_current_snapshot_before_the_primary(monkeypatch, tmp_path):
    # Minutes-long status reads held the primary's lock past the pre-open writer's retry.
    from datetime import datetime, timezone
    from types import SimpleNamespace

    snapshot = SimpleNamespace(path=tmp_path / "snap.duckdb",
                               as_of=datetime(2024, 7, 17, 13, tzinfo=timezone.utc))
    requested, opened = [], []
    monkeypatch.setattr(db, "latest_snapshot", lambda path, *, newer_than_database: (
        requested.append(newer_than_database) or snapshot
    ))
    monkeypatch.setattr(db.engine_db, "connect", lambda path, **kwargs: (
        opened.append(path) or f"connection:{path.name}"
    ))

    with db.response_data_source() as state, db.prefer_current_snapshot():
        assert db.read_con() == "connection:snap.duckdb"
    assert requested == [True] and opened == [snapshot.path]
    assert state == {"source": "snapshot", "snapshot_as_of": snapshot.as_of.isoformat()}

    monkeypatch.setattr(db, "latest_snapshot", lambda path, *, newer_than_database: None)
    with db.response_data_source() as state, db.prefer_current_snapshot():
        assert db.read_con() == f"connection:{db.db_path().name}"
    assert state["source"] == "primary"
    assert db.read_con() == f"connection:{db.db_path().name}"
