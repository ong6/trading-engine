"""Append exact-date EOD fetch outcomes used by P15 missing-bar labels."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb

from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from sim import nyse

SOURCE = "yfinance"


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS price_fetch_attempts (
        id BIGINT PRIMARY KEY, ticker VARCHAR NOT NULL, market_date DATE NOT NULL,
        attempted_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, status VARCHAR NOT NULL,
        attempt_sha256 VARCHAR NOT NULL UNIQUE)"""
    )


def record(
    con: duckdb.DuckDBPyConnection, *, market_date: date, attempted_at: datetime,
    requested_count: int, failed_count: int,
) -> dict:
    """Record outcomes only after a complete all-liquid incremental collection."""
    if attempted_at.utcoffset() is None or not nyse.is_session(market_date):
        raise ValueError("price fetch attempt timestamp or market date is invalid")
    init_schema(con)
    tickers = [row[0] for row in con.execute(
        "SELECT ticker FROM universe WHERE liquid=TRUE ORDER BY ticker"
    ).fetchall()]
    if failed_count or requested_count != len(tickers):
        return {
            "status": "withheld", "market_date": market_date.isoformat(),
            "reason": "collection_incomplete", "attempt_count": 0,
            "present_count": 0, "missing_count": 0,
        }
    present = {row[0] for row in con.execute(
        f"SELECT ticker FROM prices WHERE date=? AND ticker IN "
        "(SELECT ticker FROM universe WHERE liquid=TRUE) "
        f"AND {REAL_BAR_SQL} ORDER BY ticker",
        [market_date],
    ).fetchall()}
    next_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM price_fetch_attempts"
    ).fetchone()[0])
    attempted = attempted_at.astimezone(timezone.utc)
    rows = []
    for offset, ticker in enumerate(tickers):
        status = "present" if ticker in present else "missing"
        identity = {
            "ticker": ticker, "market_date": market_date.isoformat(),
            "attempted_at": attempted.isoformat(), "source": SOURCE, "status": status,
        }
        rows.append([
            next_id + offset, ticker, market_date, attempted.replace(tzinfo=None),
            SOURCE, status, canonical_sha256(identity),
        ])
    if rows:
        con.executemany(
            "INSERT INTO price_fetch_attempts VALUES (?,?,?,?,?,?,?)", rows,
        )
    return {
        "status": "complete", "market_date": market_date.isoformat(),
        "attempt_count": len(rows), "present_count": len(present & set(tickers)),
        "missing_count": len(set(tickers) - present),
    }
