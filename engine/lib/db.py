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
