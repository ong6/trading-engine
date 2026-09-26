"""Append exact-date EOD fetch outcomes used by P15 missing-bar labels."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB
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
) -> dict:
    """Record the outcome after the nightly collector attempted every liquid ticker."""
    if attempted_at.utcoffset() is None or not nyse.is_session(market_date):
        raise ValueError("price fetch attempt timestamp or market date is invalid")
    init_schema(con)
    tickers = [row[0] for row in con.execute(
        "SELECT ticker FROM universe WHERE liquid=TRUE ORDER BY ticker"
    ).fetchall()]
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


def run_database(
    database: Path = DEFAULT_DB, *, now: datetime | None = None,
) -> dict:
    attempted = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    market_date = attempted.date()
    if not nyse.is_session(market_date):
        return {"status": "not_session", "market_date": market_date.isoformat()}
    con = db.connect(database)
    try:
        with db.transaction(con):
            return record(con, market_date=market_date, attempted_at=attempted)
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    print(json.dumps(run_database(args.database), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
