"""DuckDB storage layer for the trading engine.

One connection helper, one schema initializer, and a price upsert that never
stores a fabricated bar (rows with a NaN close are dropped).
"""
from __future__ import annotations

import math
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "store" / "market.duckdb"

# Substrings DuckDB uses when the single-writer on-disk lock is contended.
# Duplicated (not imported) from server/db.py's _LOCK_MARKERS: server already
# does `from lib import db`, so importing back would be a cycle. Keep in sync.
_LOCK_MARKERS = (
    "could not set lock on file",
    "conflicting lock is held",
    "already open",
    "being used",
)
# Total seconds to keep retrying a locked open before re-raising (env-tunable so
# tests can set it tiny). ~12 tries x 5s ≈ 60s covers a brief nightly overlap.
_LOCK_WAIT_DEFAULT_S = 60.0
_LOCK_RETRY_S = 5.0


def _is_lock_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _LOCK_MARKERS)


def connect(path: str | Path = DEFAULT_DB) -> duckdb.DuckDBPyConnection:
    """Open (creating parent dirs) a DuckDB connection.

    On a lock conflict (another process holds the single-writer lock — e.g. a
    still-draining farm or an overlapping nightly) retry over a bounded window
    (TRADING_ENGINE_LOCK_WAIT_S, default 60s) instead of failing immediately.
    After the window the original exception is re-raised.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wait_s = float(os.environ.get("TRADING_ENGINE_LOCK_WAIT_S", _LOCK_WAIT_DEFAULT_S))
    # ceil so the window is at least covered: 60s/5s -> 12 tries, 6s/5s -> 2.
    tries = max(1, math.ceil(wait_s / _LOCK_RETRY_S)) if wait_s > 0 else 1
    for attempt in range(1, tries + 1):
        try:
            return duckdb.connect(str(path))
        except Exception as exc:  # duckdb.IOException et al.
            if not _is_lock_error(exc) or attempt >= tries:
                raise
            print(f"[db] store locked (attempt {attempt}/{tries}) — "
                  f"retrying in {_LOCK_RETRY_S:.0f}s")
            time.sleep(_LOCK_RETRY_S)


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


def init_mining_schema(con: duckdb.DuckDBPyConnection) -> None:
    """M4 §12.2 additions: the append-only, point-in-time `fundamentals`
    (weekly snapshot) and `earnings_calendar` (daily) tables.

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every statement is CREATE TABLE IF NOT EXISTS so it is safe to run against
    the live single-writer DB and first-run on the real store just works.

    Both tables are keyed by (ticker, ..., as_of) with as_of = the pull date, so
    a re-run on the same day is a no-op (see insert_fundamentals / insert_earnings
    anti-joins) and a past snapshot is NEVER updated — point-in-time discipline.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals (
            ticker             VARCHAR NOT NULL,
            as_of              DATE    NOT NULL,
            market_cap         DOUBLE,
            trailing_pe        DOUBLE,
            forward_pe         DOUBLE,
            price_to_book      DOUBLE,
            price_to_sales     DOUBLE,
            enterprise_value   DOUBLE,
            ev_to_ebitda       DOUBLE,
            ev_to_revenue      DOUBLE,
            ebitda             DOUBLE,
            trailing_eps       DOUBLE,
            forward_eps        DOUBLE,
            profit_margins     DOUBLE,
            dividend_yield     DOUBLE,
            beta               DOUBLE,
            shares_outstanding DOUBLE,
            sector             VARCHAR,
            industry           VARCHAR,
            quote_type         VARCHAR,
            currency           VARCHAR,
            source             VARCHAR DEFAULT 'yfinance',
            fetched_at         TIMESTAMP,
            PRIMARY KEY (ticker, as_of)
        )
        """
    )
    # Earnings dates are forward-looking estimates that move; every daily pull is
    # its own as_of-stamped snapshot so a gate lookup uses the LATEST snapshot per
    # ticker. is_estimate = the source returned a date window (not a confirmed day).
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            ticker        VARCHAR NOT NULL,
            earnings_date DATE    NOT NULL,
            as_of         DATE    NOT NULL,
            is_estimate   BOOLEAN,
            source        VARCHAR DEFAULT 'yfinance',
            fetched_at    TIMESTAMP,
            PRIMARY KEY (ticker, earnings_date, as_of)
        )
        """
    )


# Columns the fundamentals miner supplies (order-independent; as_of/source/
# fetched_at are stamped by insert_fundamentals). Kept next to the schema so the
# two never drift.
_FUNDAMENTAL_COLS = [
    "ticker", "market_cap", "trailing_pe", "forward_pe", "price_to_book",
    "price_to_sales", "enterprise_value", "ev_to_ebitda", "ev_to_revenue",
    "ebitda", "trailing_eps", "forward_eps", "profit_margins", "dividend_yield",
    "beta", "shares_outstanding", "sector", "industry", "quote_type", "currency",
]


def insert_fundamentals(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                        as_of: date | None = None) -> int:
    """Append-only, point-in-time insert into `fundamentals` via anti-join.

    df carries one row per ticker with any subset of _FUNDAMENTAL_COLS present;
    missing columns are stored as NULL (never fabricated). Only (ticker, as_of)
    keys not already stored are inserted — an existing snapshot is NEVER updated.
    as_of defaults to today (UTC). Returns rows inserted.
    """
    if df is None or df.empty:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()

    df = df.copy()
    for col in _FUNDAMENTAL_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[_FUNDAMENTAL_COLS]
    df = df.drop_duplicates(subset=["ticker"])
    if df.empty:
        return 0

    df["as_of"] = as_of
    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    insert_cols = _FUNDAMENTAL_COLS + ["as_of", "source", "fetched_at"]
    before = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    con.register("_incoming_fund", df)
    select_list = ", ".join(f"i.{c}" for c in insert_cols)
    con.execute(
        f"""
        INSERT INTO fundamentals ({', '.join(insert_cols)})
        SELECT {select_list}
        FROM _incoming_fund i
        LEFT JOIN fundamentals f
               ON f.ticker = i.ticker AND f.as_of = i.as_of
        WHERE f.ticker IS NULL
        """
    )
    con.unregister("_incoming_fund")
    after = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    return after - before


def insert_earnings(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                    as_of: date | None = None) -> int:
    """Append-only insert into `earnings_calendar` via anti-join.

    df columns: ticker, earnings_date, is_estimate. as_of defaults to today
    (UTC). Only (ticker, earnings_date, as_of) keys not already stored are
    inserted — existing rows are NEVER touched. Rows with a NaT earnings_date are
    dropped (never store a fabricated date). Returns rows inserted.
    """
    cols = ["ticker", "earnings_date", "is_estimate"]
    if df is None or df.empty:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()

    df = df[[c for c in cols if c in df.columns]].copy()
    for col in cols:
        if col not in df.columns:
            df[col] = None
    df = df.dropna(subset=["earnings_date"])
    df = df.drop_duplicates(subset=["ticker", "earnings_date"])
    if df.empty:
        return 0

    df["as_of"] = as_of
    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    before = con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone()[0]
    con.register("_incoming_earn", df)
    con.execute(
        """
        INSERT INTO earnings_calendar
            (ticker, earnings_date, is_estimate, as_of, source, fetched_at)
        SELECT i.ticker, i.earnings_date, i.is_estimate, i.as_of, i.source, i.fetched_at
        FROM _incoming_earn i
        LEFT JOIN earnings_calendar e
               ON e.ticker = i.ticker AND e.earnings_date = i.earnings_date
              AND e.as_of = i.as_of
        WHERE e.ticker IS NULL
        """
    )
    con.unregister("_incoming_earn")
    after = con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone()[0]
    return after - before


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
