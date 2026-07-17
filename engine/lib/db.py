"""DuckDB storage layer for the trading engine.

One connection helper, one schema initializer, and a price upsert that never
stores a fabricated bar (rows with a NaN close are dropped).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "store" / "market.duckdb"


def connect(path: str | Path = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    """Open (creating parent dirs) a DuckDB connection."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables IF NOT EXISTS. Safe to call on every run."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            ticker     VARCHAR NOT NULL,
            date       DATE    NOT NULL,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     BIGINT,
            source     VARCHAR DEFAULT 'yfinance',
            fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe (
            ticker        VARCHAR PRIMARY KEY,
            yf_ticker     VARCHAR,
            name          VARCHAR,
            exchange      VARCHAR,
            etf           BOOLEAN,
            member        VARCHAR,
            added         DATE,
            active        BOOLEAN DEFAULT TRUE,
            liquid        BOOLEAN DEFAULT FALSE,
            backfill_done BOOLEAN DEFAULT FALSE
        )
        """
    )
    # Append-only point-in-time record of the universe as filed each day.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_snapshot (
            snapshot_date DATE,
            ticker        VARCHAR,
            name          VARCHAR,
            exchange      VARCHAR,
            etf           BOOLEAN,
            member        VARCHAR,
            active        BOOLEAN,
            liquid        BOOLEAN,
            PRIMARY KEY (snapshot_date, ticker)
        )
        """
    )
    # Populated by the screener in M1 — created now so the schema is stable.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_results (
            run_date        DATE,
            ticker          VARCHAR,
            close           DOUBLE,
            rs_rank         INTEGER,
            template_score  INTEGER,
            passes_template BOOLEAN,
            dist_50d        DOUBLE,
            dist_200d       DOUBLE,
            off_52w_low     DOUBLE,
            off_52w_high    DOUBLE,
            base_tight      BOOLEAN,
            vol_dryup       BOOLEAN,
            new_today       BOOLEAN,
            PRIMARY KEY (run_date, ticker)
        )
        """
    )
    # Minimal job bookkeeping — backfill uses this for progress/resumability.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id         INTEGER PRIMARY KEY,
            kind       VARCHAR,
            params     VARCHAR,
            state      VARCHAR DEFAULT 'queued',
            progress   VARCHAR,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )


def init_queue_schema(con: duckdb.DuckDBPyConnection) -> None:
    """M4 additions: extend the minimal `jobs` table with the §12.7 queue
    columns and create the append-only `intraday_prices` table.

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every statement is ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS so
    it is safe to run against the live single-writer DB. Assumes `jobs` already
    exists (call init_schema first).
    """
    # Extend jobs in place — backward compatible with the backfill rows already
    # present (they simply get priority=100, mem_mb=0, last_error=NULL).
    for ddl in (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority   INTEGER DEFAULT 100",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS mem_mb     INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_error VARCHAR",
    ):
        con.execute(ddl)

    # Intraday archive: append-only, UTC timestamps. The (ticker, ts, interval)
    # primary key + the anti-join insert together guarantee we never update or
    # overwrite a captured bar.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS intraday_prices (
            ticker   VARCHAR   NOT NULL,
            ts       TIMESTAMP NOT NULL,
            interval VARCHAR   NOT NULL,
            open     DOUBLE,
            high     DOUBLE,
            low      DOUBLE,
            close    DOUBLE,
            volume   BIGINT,
            source   VARCHAR DEFAULT 'yfinance',
            as_of    DATE,
            PRIMARY KEY (ticker, ts, interval)
        )
        """
    )


def insert_intraday(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Append-only insert into intraday_prices via anti-join.

    df must have columns: ticker, ts, interval, open, high, low, close, volume.
    ts must already be UTC (tz-naive). Only (ticker, ts, interval) keys not
    already stored are inserted — existing rows are NEVER touched. Rows with a
    NaN close are dropped (never store a fabricated bar). Returns rows inserted.
    """
    cols = ["ticker", "ts", "interval", "open", "high", "low", "close", "volume"]
    if df is None or df.empty:
        return 0

    df = df[cols].copy()
    df = df.dropna(subset=["close"])
    # Guard the primary key against dupes within a single incoming batch.
    df = df.drop_duplicates(subset=["ticker", "ts", "interval"])
    if df.empty:
        return 0

    df["source"] = "yfinance"
    df["as_of"] = datetime.now(timezone.utc).date()

    before = con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    con.register("_incoming_intraday", df)
    con.execute(
        """
        INSERT INTO intraday_prices
            (ticker, ts, interval, open, high, low, close, volume, source, as_of)
        SELECT i.ticker, i.ts, i.interval, i.open, i.high, i.low, i.close,
               i.volume, i.source, i.as_of
        FROM _incoming_intraday i
        LEFT JOIN intraday_prices p
               ON p.ticker = i.ticker AND p.ts = i.ts AND p.interval = i.interval
        WHERE p.ticker IS NULL
        """
    )
    con.unregister("_incoming_intraday")
    after = con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    return after - before


def upsert_prices(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE price bars.

    df must have columns: ticker, date, open, high, low, close, volume.
    Rows with a NaN close are dropped — we never store an empty/fabricated bar.
    Returns the number of rows written.
    """
    cols = ["ticker", "date", "open", "high", "low", "close", "volume"]
    if df is None or df.empty:
        return 0

    df = df[cols].copy()
    df = df.dropna(subset=["close"])
    if df.empty:
        return 0

    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    con.register("_incoming_prices", df)
    con.execute(
        """
        INSERT OR REPLACE INTO prices
            (ticker, date, open, high, low, close, volume, source, fetched_at)
        SELECT ticker, date, open, high, low, close, volume, source, fetched_at
        FROM _incoming_prices
        """
    )
    con.unregister("_incoming_prices")
    return len(df)
