#!/usr/bin/env python3
"""Refresh held, pending, and explicitly watched names outside the liquid universe."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb

from engine import collect
from engine.lib import db
from engine.lib.settings import DEFAULT_DB


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the account-managed watch list without requiring account tables."""
    con.execute(
        """CREATE TABLE IF NOT EXISTS account_watch (
        portfolio_id VARCHAR NOT NULL,
        ticker VARCHAR NOT NULL,
        PRIMARY KEY (portfolio_id, ticker))"""
    )


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?",
            [table],
        ).fetchone()[0]
    )


def incremental_universe(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Return provider-to-canonical names needed by daily price collection.

    Missing account/simulator tables are normal on older or minimal stores. Names
    absent from ``universe`` cannot be resolved to a provider symbol and are omitted.
    """
    tickers = {
        row[0]
        for row in con.execute(
            "SELECT ticker FROM universe WHERE liquid = TRUE"
        ).fetchall()
    }
    if _table_exists(con, "portfolios") and _table_exists(con, "sim_positions"):
        tickers.update(
            row[0]
            for row in con.execute(
                """SELECT DISTINCT p.ticker
                FROM sim_positions p
                JOIN portfolios pf ON pf.id = p.portfolio_id
                WHERE pf.active = TRUE AND p.qty <> 0"""
            ).fetchall()
        )
    if _table_exists(con, "sim_orders"):
        tickers.update(
            row[0]
            for row in con.execute(
                "SELECT DISTINCT ticker FROM sim_orders WHERE status = 'pending'"
            ).fetchall()
        )
    if _table_exists(con, "account_watch"):
        tickers.update(
            row[0]
            for row in con.execute("SELECT DISTINCT ticker FROM account_watch").fetchall()
        )
    if not tickers:
        return {}
    rows = con.execute(
        """SELECT ticker, yf_ticker
        FROM universe
        WHERE ticker IN (SELECT UNNEST(?)) AND yf_ticker IS NOT NULL
        ORDER BY ticker""",
        [sorted(tickers)],
    ).fetchall()
    return {provider: ticker for ticker, provider in rows}


def supplemental_universe(
    con: duckdb.DuckDBPyConnection, limit: int | None = None
) -> dict[str, str]:
    """Return watched account names not already covered by the liquid pull."""
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    all_names = incremental_universe(con)
    liquid = {
        row[0]
        for row in con.execute(
            "SELECT yf_ticker FROM universe WHERE liquid = TRUE AND yf_ticker IS NOT NULL"
        ).fetchall()
    }
    rows = [(provider, ticker) for provider, ticker in all_names.items() if provider not in liquid]
    if limit is not None:
        rows = rows[:limit]
    return dict(rows)


def mode_incremental(
    database: str | Path = DEFAULT_DB, *, force: bool = False, limit: int | None = None
) -> tuple[int, int]:
    """Pull recent bars for account names omitted by the frozen liquid collector."""
    today = collect.datetime.now(collect.timezone.utc).date()
    if not force and not collect._is_trading_day(today):
        return 0, 0
    con = db.connect(database)
    try:
        init_schema(con)
        names = supplemental_universe(con, limit)
    finally:
        con.close()
    providers = list(names)
    got_all: set[str] = set()
    for batch in collect._batches(providers, 200):
        sub_map = {provider: names[provider] for provider in batch}
        raw = collect._download(batch, period="5d", start=None)
        frame, got = collect._extract_long(raw, sub_map)
        collect._upsert_batch(database, frame)
        got_all |= got
        time.sleep(2)
    return len(providers), len(providers) - len(got_all)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    requested, failed = mode_incremental(
        args.database, force=args.force, limit=args.limit
    )
    print(json.dumps({"requested": requested, "failed": failed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
