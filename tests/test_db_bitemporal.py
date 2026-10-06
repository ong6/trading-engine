"""Price refreshes retain the first point-in-time availability stamp."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pandas as pd

from engine.lib import db


def _frame(close: float) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "ticker": "XYZ", "date": date(2026, 10, 5), "open": 10.0,
            "high": 12.0, "low": 9.0, "close": close, "volume": 1000,
        }]
    )


def test_price_upsert_preserves_first_fetch_and_moves_latest(monkeypatch):
    first = datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc)
    second = datetime(2026, 10, 6, 22, 30, tzinfo=timezone.utc)
    instants = iter((first, second))

    class Clock:
        @staticmethod
        def now(_timezone):
            return next(instants)

    con = duckdb.connect()
    try:
        db.init_schema(con)
        monkeypatch.setattr(db, "datetime", Clock)
        assert db.upsert_prices(con, _frame(10.5)) == 1
        assert db.upsert_prices(con, _frame(11.5)) == 1
        stored = con.execute(
            "SELECT close, fetched_at, first_fetched_at FROM prices"
        ).fetchone()
    finally:
        con.close()

    assert stored == (
        11.5,
        second.replace(tzinfo=None),
        first.replace(tzinfo=None),
    )


def test_schema_adds_first_fetch_column_to_an_existing_prices_table():
    con = duckdb.connect()
    try:
        con.execute(
            """CREATE TABLE prices (
            ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT, source VARCHAR, fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, date))"""
        )
        db.init_schema(con)
        columns = {
            row[0] for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='prices'"
            ).fetchall()
        }
    finally:
        con.close()

    assert "first_fetched_at" in columns


def test_upsert_remains_compatible_with_a_minimal_legacy_prices_fixture():
    con = duckdb.connect()
    try:
        con.execute(
            """CREATE TABLE prices (
            ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT, source VARCHAR, fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, date))"""
        )
        assert db.upsert_prices(con, _frame(10.5)) == 1
        assert con.execute("SELECT close FROM prices").fetchone() == (10.5,)
    finally:
        con.close()
