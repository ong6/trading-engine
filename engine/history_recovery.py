"""Explicit full-history maintenance outside the frozen forward collector.

Only a currently pending, active liquid symbol can be repaired. Fetches finish
before opening a writer; the transaction rechecks identity and all stored bars.
Existing prices and failed jobs are never overwritten. The JSON result retains
provider metadata and normalized coverage evidence, not raw HTTP response bytes.
"""
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from engine import collect
from engine.free_massive_minute import session_close
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from sim import nyse


class HistoryRefused(ValueError):
    """The listing identity, coverage, prices or current binding are unproven."""


def _provider_clock(value, zone) -> datetime:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise HistoryRefused("provider timestamp lacks timezone")
        return value.astimezone(zone)
    if type(value) not in (int, float):
        raise HistoryRefused("provider timestamp is invalid")
    return datetime.fromtimestamp(value, zone)


def _listing_interval(metadata: Mapping) -> tuple[date, date]:
    zone = ZoneInfo(metadata["exchangeTimezoneName"])
    first = _provider_clock(metadata["firstTradeDate"], zone).date()
    latest = _provider_clock(metadata["regularMarketTime"], zone)
    last = latest.date()
    if not nyse.is_session(last) or latest.timetz().replace(tzinfo=None) < session_close(last):
        last -= timedelta(days=1)
        while not nyse.is_session(last):
            last -= timedelta(days=1)
    if first > last or first.year < 2000 or not nyse.is_session(first):
        raise HistoryRefused("unsupported or invalid provider listing interval")
    return first, last


def _validate_frame(frame: pd.DataFrame, first: date, last: date) -> None:
    expected, day = set(), first
    while day <= last:
        if nyse.is_session(day):
            expected.add(day)
        day += timedelta(days=1)
    actual = set(frame["date"]) if not frame.empty else set()
    if actual != expected or len(frame) != len(expected):
        raise HistoryRefused("explicit history does not cover every declared listing session")
    for row in frame.itertuples(index=False):
        values = (row.open, row.high, row.low, row.close)
        if (any(not math.isfinite(value) or value <= 0 for value in values)
                or row.low > min(row.open, row.close) or row.high < max(row.open, row.close)
                or not math.isfinite(row.volume) or row.volume < 0
                or row.volume != int(row.volume)):
            raise HistoryRefused("explicit history has invalid OHLCV")


def fetch_history(ticker: str, provider_ticker: str, is_etf: bool) -> tuple[pd.DataFrame, dict]:
    """Return complete verified listing history without touching a database."""
    source = yf.Ticker(provider_ticker)
    metadata = source.get_history_metadata()
    quote_type = "ETF" if is_etf else "EQUITY"
    if (not isinstance(metadata, Mapping) or metadata.get("symbol") != provider_ticker
            or metadata.get("currency") != "USD" or metadata.get("instrumentType") != quote_type):
        raise HistoryRefused("provider security identity/currency/instrument missing or different")
    first, last = _listing_interval(metadata)
    raw = source.history(start=first.isoformat(), end=(last + timedelta(days=1)).isoformat(),
                         period=None, auto_adjust=False, actions=False, raise_errors=True)
    frame, _ = collect._extract_long(raw, {provider_ticker: ticker})
    _validate_frame(frame, first, last)
    frame = frame.sort_values("date").reset_index(drop=True)
    rows = [{**row, "date": row["date"].isoformat()} for row in frame.to_dict("records")]
    evidence = {
        "ticker": ticker, "provider_ticker": provider_ticker, "currency": "USD",
        "instrument_type": quote_type, "first_session": first.isoformat(),
        "last_session": last.isoformat(), "exchange_timezone": metadata["exchangeTimezoneName"],
        "fetched_at": datetime.now(timezone.utc).isoformat(), "bars": rows,
    }
    return frame, {**evidence, "sha256": canonical_sha256(evidence)}


def _binding(con, ticker: str) -> tuple:
    row = con.execute("SELECT yf_ticker,name,exchange,etf,added,active,liquid,backfill_done "
                      "FROM universe WHERE ticker=?", [ticker]).fetchone()
    if (row is None or not row[0] or type(row[3]) is not bool
            or row[5:] != (True, True, False)):
        raise HistoryRefused("symbol must have an explicit active liquid pending universe binding")
    return row


def _missing_rows(con, ticker: str, frame: pd.DataFrame) -> list[tuple]:
    expected = {row.date: (row.open, row.high, row.low, row.close, row.volume)
                for row in frame.itertuples(index=False)}
    stored = con.execute("SELECT date,open,high,low,close,volume,source FROM prices "
                         "WHERE ticker=? ORDER BY date", [ticker]).fetchall()
    for day, *values in stored:
        if day not in expected:
            raise HistoryRefused("stored dates conflict with current listing; possible reused ticker")
        if values[-1] != "yfinance" or tuple(values[:-1]) != expected[day]:
            raise HistoryRefused("stored OHLCV/source differs from fetched history; no overwrite allowed")
    existing = {row[0] for row in stored}
    return [(ticker, day, *values) for day, values in expected.items() if day not in existing]


def recover(db_path: str | Path, ticker: str, *, fetch=fetch_history) -> dict:
    """Repair one explicit pending name; retain its result as operator evidence."""
    con = db.connect(db_path, read_only=True)
    try:
        binding = _binding(con, ticker)
    finally:
        con.close()
    frame, evidence = fetch(ticker, binding[0], binding[3])
    con = db.connect(db_path)
    try:
        with db.transaction(con):
            if _binding(con, ticker) != binding:
                raise HistoryRefused("universe binding changed during provider request")
            missing = _missing_rows(con, ticker, frame)
            if missing:
                con.executemany("INSERT INTO prices(ticker,date,open,high,low,close,volume,source,fetched_at) "
                                "VALUES (?,?,?,?,?,?,?,'yfinance',CURRENT_TIMESTAMP)", missing)
            con.execute("UPDATE universe SET backfill_done=TRUE WHERE ticker=?", [ticker])
    finally:
        con.close()
    return {"status": "complete", "ticker": ticker, "inserted_rows": len(missing),
            "existing_rows_unchanged": len(frame) - len(missing), "evidence": evidence}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(db.DEFAULT_DB))
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.db, args.ticker), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
