"""Production account entry points attach isolated data stores read-only."""
from __future__ import annotations

from pathlib import Path

import duckdb

from engine.accounts.sources import production_sources


def _database(path: Path, statement: str) -> None:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(statement)
    finally:
        connection.close()


def test_production_sources_attach_daily_minute_and_short_tables(con, tmp_path):
    daily = tmp_path / "daily.duckdb"
    minute = tmp_path / "minute.duckdb"
    short = tmp_path / "short.duckdb"
    _database(
        daily,
        "CREATE TABLE free_daily_bars (date DATE,ticker VARCHAR,o DOUBLE,h DOUBLE,"
        "l DOUBLE,c DOUBLE,volume DOUBLE,vwap DOUBLE,source VARCHAR,"
        "fetched_at TIMESTAMP,source_sha256 VARCHAR)",
    )
    _database(
        minute,
        "CREATE TABLE massive_minute_bars (ticker VARCHAR,ts_utc TIMESTAMP,o DOUBLE,"
        "h DOUBLE,l DOUBLE,c DOUBLE,v DOUBLE,vw DOUBLE,n BIGINT,session VARCHAR,"
        "source_sha256 VARCHAR,fetched_at TIMESTAMP)",
    )
    short_con = duckdb.connect(str(short))
    short_con.execute(
        "CREATE TABLE regsho_threshold "
        "(ticker VARCHAR,session_date DATE,publication_date DATE)"
    )
    short_con.execute(
        "CREATE TABLE finra_short_interest "
        "(ticker VARCHAR,settlement_date DATE,days_to_cover DOUBLE,publication_date DATE)"
    )
    short_con.close()
    environ = {
        "TRADING_ENGINE_FREE_SOURCES_DB": str(daily),
        "TRADING_ENGINE_MASSIVE_MINUTE_DB": str(minute),
        "TRADING_ENGINE_SHORT_DATA_DB": str(short),
    }

    with production_sources(con, environ=environ) as attached_short:
        assert attached_short is con
        names = {
            row[0] for row in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN ('free_daily_bars','massive_minute_bars',"
                "'regsho_threshold','finra_short_interest')"
            ).fetchall()
        }
        assert names == {
            "free_daily_bars", "massive_minute_bars",
            "regsho_threshold", "finra_short_interest",
        }

    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name='free_daily_bars'"
    ).fetchone() == (0,)
