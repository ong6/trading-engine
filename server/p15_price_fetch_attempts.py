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
        """CREATE TABLE IF NOT EXISTS p15_price_fetch_batches (
        id BIGINT PRIMARY KEY, market_date DATE NOT NULL, attempted_at TIMESTAMP NOT NULL,
        source VARCHAR NOT NULL, requested_count INTEGER NOT NULL,
        failed_count INTEGER NOT NULL, present_count INTEGER NOT NULL,
        missing_count INTEGER NOT NULL, batch_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS price_fetch_attempts (
        id BIGINT PRIMARY KEY, ticker VARCHAR NOT NULL, market_date DATE NOT NULL,
        attempted_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, status VARCHAR NOT NULL,
        batch_sha256 VARCHAR NOT NULL, attempt_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(batch_sha256,ticker))"""
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
    missing = sorted(set(tickers) - present)
    batch_identity = {
        "market_date": market_date.isoformat(), "attempted_at": attempted.isoformat(),
        "source": SOURCE, "requested_count": requested_count, "failed_count": failed_count,
        "present_count": len(present & set(tickers)), "missing_count": len(missing),
        "missing_tickers": missing,
    }
    batch_sha = canonical_sha256(batch_identity)
    batch_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM p15_price_fetch_batches"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO p15_price_fetch_batches VALUES (?,?,?,?,?,?,?,?,?)",
        [batch_id, market_date, attempted.replace(tzinfo=None), SOURCE,
         requested_count, failed_count, len(present & set(tickers)), len(missing), batch_sha],
    )
    rows = []
    for offset, ticker in enumerate(missing):
        status = "missing"
        identity = {
            "ticker": ticker, "market_date": market_date.isoformat(),
            "attempted_at": attempted.isoformat(), "source": SOURCE, "status": status,
            "batch_sha256": batch_sha,
        }
        rows.append([
            next_id + offset, ticker, market_date, attempted.replace(tzinfo=None),
            SOURCE, status, batch_sha, canonical_sha256(identity),
        ])
    if rows:
        con.executemany(
            "INSERT INTO price_fetch_attempts VALUES (?,?,?,?,?,?,?,?)", rows,
        )
    return {
        "status": "complete", "market_date": market_date.isoformat(),
        "attempt_count": requested_count, "present_count": len(present & set(tickers)),
        "missing_count": len(missing),
    }


def validate(con: duckdb.DuckDBPyConnection, error_type) -> None:
    """Replay every batch and row identity that can confirm a missing label."""
    present = [
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", [name]
        ).fetchone()[0] > 0
        for name in ("p15_price_fetch_batches", "price_fetch_attempts")
    ]
    if not any(present):
        return
    if not all(present):
        raise error_type("P15 price fetch attempt schema is incomplete")
    for batch in con.execute(
        "SELECT market_date,attempted_at,source,requested_count,failed_count,"
        "present_count,missing_count,batch_sha256 "
        "FROM p15_price_fetch_batches ORDER BY id"
    ).fetchall():
        (market_date, attempted_at, source, requested, failed,
         present_count, missing_count, batch_sha) = batch
        attempts = con.execute(
            "SELECT ticker,status,attempt_sha256 FROM price_fetch_attempts "
            "WHERE batch_sha256=? ORDER BY ticker", [batch_sha],
        ).fetchall()
        tickers = [row[0] for row in attempts]
        batch_identity = {
            "market_date": market_date.isoformat(),
            "attempted_at": attempted_at.replace(tzinfo=timezone.utc).isoformat(),
            "source": source, "requested_count": requested, "failed_count": failed,
            "present_count": present_count, "missing_count": missing_count,
            "missing_tickers": tickers,
        }
        if (failed != 0 or requested != present_count + missing_count
                or missing_count != len(attempts) or len(tickers) != len(set(tickers))) \
                or canonical_sha256(batch_identity) != batch_sha:
            raise error_type("P15 price fetch batch evidence differs")
        for ticker, status, attempt_sha in attempts:
            identity = {
                "ticker": ticker, "market_date": market_date.isoformat(),
                "attempted_at": attempted_at.replace(tzinfo=timezone.utc).isoformat(),
                "source": source, "status": status, "batch_sha256": batch_sha,
            }
            had_bar = con.execute(
                f"SELECT 1 FROM prices WHERE ticker=? AND date=? "
                f"AND fetched_at<=? AND {REAL_BAR_SQL} LIMIT 1",
                [ticker, market_date, attempted_at],
            ).fetchone() is not None
            if status != "missing" or had_bar \
                    or canonical_sha256(identity) != attempt_sha:
                raise error_type("P15 price fetch attempt evidence differs")
    orphans = int(con.execute(
        "SELECT COUNT(*) FROM price_fetch_attempts a LEFT JOIN p15_price_fetch_batches b "
        "ON b.batch_sha256=a.batch_sha256 WHERE b.batch_sha256 IS NULL"
    ).fetchone()[0])
    if orphans:
        raise error_type("P15 price fetch attempt evidence differs")
