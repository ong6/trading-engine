#!/usr/bin/env python3
"""Measure Tiingo master coverage against a consistent operational-store copy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from engine.free_sources import default_database

MASTER_EXCHANGE = """CASE exchange
    WHEN 'AMEX' THEN 'NYSE AMERICAN' WHEN 'NYSE MKT' THEN 'NYSE AMERICAN'
    WHEN 'ARCA' THEN 'NYSE ARCA' WHEN 'BATS' THEN 'CBOE'
    ELSE exchange END"""
STORE_EXCHANGE = """CASE u.exchange
    WHEN 'Q' THEN 'NASDAQ' WHEN 'N' THEN 'NYSE' WHEN 'A' THEN 'NYSE AMERICAN'
    WHEN 'P' THEN 'NYSE ARCA' WHEN 'Z' THEN 'CBOE' WHEN 'V' THEN 'IEX'
    WHEN 'F' THEN 'OTC' ELSE COALESCE(NULLIF(u.exchange, ''), 'UNKNOWN') END"""


def _sql_string(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _dict_rows(columns: tuple[str, ...], rows: list[tuple]) -> list[dict]:
    return [dict(zip(columns, row, strict=True)) for row in rows]


def audit(free_database: Path, store_copy: Path) -> dict:
    if not free_database.is_file() or not store_copy.is_file():
        raise ValueError("both the free-source database and store copy must be regular files")
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH {_sql_string(free_database)} AS free_store (READ_ONLY)")
        con.execute(f"ATTACH {_sql_string(store_copy)} AS live_copy (READ_ONLY)")
        con.execute(
            f"""CREATE TEMP VIEW latest_master AS
            SELECT *, {MASTER_EXCHANGE} AS audit_exchange
            FROM free_store.free_security_master
            WHERE source_sha256=(
                SELECT source_sha256 FROM free_store.free_security_master
                ORDER BY fetched_at DESC, source_sha256 DESC LIMIT 1)"""
        )
        con.execute(
            """CREATE TEMP VIEW audit_years AS
            SELECT CAST(year AS INTEGER) AS year FROM range(2010, 2027) AS t(year)"""
        )
        con.execute(
            """CREATE TEMP VIEW master_year AS
            SELECT DISTINCT y.year, m.audit_exchange AS exchange, m.ticker
            FROM audit_years y JOIN latest_master m
              ON m.start_date <= make_date(y.year, 12, 31)
             AND (m.end_date IS NULL OR m.end_date >= make_date(y.year, 1, 1))"""
        )
        con.execute(
            """CREATE TEMP VIEW store_year AS
            SELECT DISTINCT CAST(EXTRACT(year FROM p.date) AS INTEGER) AS year, p.ticker
            FROM live_copy.prices p JOIN live_copy.universe u USING(ticker)
            WHERE COALESCE(u.etf, FALSE)=FALSE
              AND p.date BETWEEN DATE '2010-01-01' AND DATE '2026-12-31'"""
        )
        master_exchange = con.execute(
            """SELECT m.year, m.exchange, COUNT(*) AS master,
               COUNT(s.ticker) AS matched, COUNT(*)-COUNT(s.ticker) AS master_only
            FROM master_year m LEFT JOIN store_year s USING(year, ticker)
            GROUP BY m.year, m.exchange ORDER BY m.year, m.exchange"""
        ).fetchall()
        store_only = con.execute(
            f"""SELECT s.year, {STORE_EXCHANGE} AS exchange, COUNT(*) AS store_only
            FROM store_year s
            LEFT JOIN (SELECT DISTINCT year,ticker FROM master_year) m USING(year,ticker)
            LEFT JOIN live_copy.universe u USING(ticker)
            WHERE m.ticker IS NULL GROUP BY s.year, exchange ORDER BY s.year, exchange"""
        ).fetchall()
        by_key = {
            (year, exchange): {"year": year, "exchange": exchange, "master": master,
                               "matched": matched, "master_only": master_only, "store_only": 0}
            for year, exchange, master, matched, master_only in master_exchange
        }
        for year, exchange, count in store_only:
            by_key.setdefault(
                (year, exchange),
                {"year": year, "exchange": exchange, "master": 0, "matched": 0,
                 "master_only": 0, "store_only": 0},
            )["store_only"] = count
        totals = con.execute(
            """WITH m AS (SELECT DISTINCT year,ticker FROM master_year),
            joined AS (SELECT COALESCE(m.year,s.year) AS year, m.ticker AS mt, s.ticker AS st
              FROM m FULL OUTER JOIN store_year s USING(year,ticker))
            SELECT year, COUNT(mt) AS master, COUNT(st) AS store,
              COUNT(*) FILTER (WHERE mt IS NOT NULL AND st IS NOT NULL) AS matched,
              COUNT(*) FILTER (WHERE mt IS NOT NULL AND st IS NULL) AS master_only,
              COUNT(*) FILTER (WHERE mt IS NULL AND st IS NOT NULL) AS store_only
            FROM joined GROUP BY year ORDER BY year"""
        ).fetchall()
        delistings = con.execute(
            """SELECT CAST(EXTRACT(year FROM end_date) AS INTEGER) AS year,
              COUNT(*) AS intervals, COUNT(DISTINCT ticker) AS tickers,
              COUNT(DISTINCT ticker) FILTER (WHERE EXISTS(
                SELECT 1 FROM live_copy.prices p WHERE p.ticker=latest_master.ticker)) AS with_bars
            FROM latest_master WHERE end_date BETWEEN DATE '2010-01-01' AND DATE '2026-12-31'
            GROUP BY year ORDER BY year"""
        ).fetchall()
        summary_row = con.execute(
            """SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(start_date), MAX(end_date),
              COUNT(*) FILTER (WHERE end_date IS NULL),
              COUNT(DISTINCT ticker) FILTER (WHERE POSITION('-P-' IN ticker)>0)
            FROM latest_master"""
        ).fetchone()
        reused = con.execute(
            """SELECT COUNT(*) FROM (
              SELECT ticker FROM (
                SELECT DISTINCT ticker,start_date,end_date FROM latest_master)
              GROUP BY ticker HAVING COUNT(*)>1)"""
        ).fetchone()[0]
        exchanges = con.execute(
            """SELECT audit_exchange, COUNT(*), COUNT(DISTINCT ticker)
            FROM latest_master GROUP BY audit_exchange ORDER BY audit_exchange"""
        ).fetchall()
    finally:
        con.close()
    return {
        "master": {
            "rows": summary_row[0], "tickers": summary_row[1],
            "start": summary_row[2].isoformat(), "latest_end": summary_row[3].isoformat(),
            "open_intervals": summary_row[4], "odd_p_tickers": summary_row[5],
            "reused_tickers": reused,
            "exchanges": _dict_rows(("exchange", "rows", "tickers"), exchanges),
        },
        "yearly_exchange": [by_key[key] for key in sorted(by_key)],
        "yearly_totals": _dict_rows(
            ("year", "master", "store", "matched", "master_only", "store_only"), totals
        ),
        "delistings": _dict_rows(("year", "intervals", "tickers", "with_bars"), delistings),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--free-database", type=Path, default=default_database())
    parser.add_argument("--store-copy", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.free_database, args.store_copy)
    except (ValueError, duckdb.Error) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "complete", **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
