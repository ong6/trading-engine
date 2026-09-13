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
