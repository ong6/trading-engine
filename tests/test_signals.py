"""Signal collection keeps external waits outside DuckDB writer leases."""
from __future__ import annotations

from datetime import date

import pytest

from engine import signals
from engine.lib import db


def test_connection_narrowed_external_source_releases_db(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    con = db.connect(db_path)
    db.init_schema(con)
    db.init_queue_schema(con)
    con.close()

    observed: list[int] = []

    def fetch_while_reading(con_arg, mode):
        assert con_arg is None
        assert mode == "incremental"
        reader = db.connect(db_path, read_only=True, wait_s=0)
        try:
            observed.append(
                reader.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
            )
        finally:
            reader.close()
        return [("test_series", date(2026, 9, 8), 1.25)]

    monkeypatch.setattr(signals, "SOURCES", {"external": fetch_while_reading})
    monkeypatch.setattr(signals, "DB_READ_SOURCES", frozenset())
    monkeypatch.setattr(signals.rsc, "dir_size_gb", lambda _path: 0.0)

    result = signals.run_connection_narrowed(
        {"mode": "incremental"},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
    )

    assert observed == [0]
    assert result["rows_inserted"] == 1
    check = db.connect(db_path, read_only=True)
    try:
        assert check.execute(
            "SELECT series, obs_date, value FROM macro_signals"
        ).fetchall() == [("test_series", date(2026, 9, 8), 1.25)]
    finally:
        check.close()


def test_connection_narrowed_db_source_gets_read_only_lease(monkeypatch, tmp_path):
    db_path = tmp_path / "market.duckdb"
    observed: list[int] = []

    def fetch_from_db(con, mode):
        assert mode == "incremental"
        observed.append(con.execute("SELECT COUNT(*) FROM prices").fetchone()[0])
        return [("breadth_test", date(2026, 9, 8), 50.0)]

    monkeypatch.setattr(signals, "SOURCES", {"breadth": fetch_from_db})
    monkeypatch.setattr(signals, "DB_READ_SOURCES", frozenset({"breadth"}))
    monkeypatch.setattr(signals.rsc, "dir_size_gb", lambda _path: 0.0)

    result = signals.run_connection_narrowed(
        {"only": "breadth"},
        db_path=db_path,
        meta_path=tmp_path / "meta.json",
    )

    assert observed == [0]
    assert result["rows_inserted"] == 1


def test_breadth_unregisters_temporary_universe_when_calculation_fails(con, monkeypatch):
    con.execute(
        "CREATE TABLE universe_snapshot "
        "(snapshot_date DATE, ticker VARCHAR, liquid BOOLEAN)"
    )
    con.execute(
        "INSERT INTO universe_snapshot VALUES (DATE '2026-09-11', 'SPY', TRUE)"
    )
    con.execute(
        "INSERT INTO prices "
        "(ticker, date, open, high, low, close, volume) "
        "VALUES ('SPY', DATE '2026-09-11', 100, 101, 99, 100, 1000000)"
    )
    monkeypatch.setattr(
        signals,
        "_breadth_chunk",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("injected breadth failure")),
    )

    with pytest.raises(RuntimeError, match="injected breadth failure"):
        signals.src_breadth(con, "incremental")

    assert "_sig_universe" not in {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
