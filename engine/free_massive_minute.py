"""Frozen-universe parsing and storage for Massive's free minute aggregates."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from engine import free_sources
from engine.lib import db
from engine.lib.settings import REPO_ROOT
from sim import nyse

SOURCE = "massive_minute_aggregates"
BENCHMARKS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
MAX_PAGE_RESULTS = 50_000
SESSIONS_PER_CHUNK = 50
MIN_MDV60 = 1_000_000
MAX_MDV60 = 5_000_000


def _configured_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def default_database() -> Path:
    return _configured_path(
        "TRADING_ENGINE_MASSIVE_MINUTE_DB",
        Path.home() / "trading-engine/store/pit/massive-minute.duckdb",
    )


def default_data_dir() -> Path:
    return _configured_path(
        "TRADING_ENGINE_MASSIVE_MINUTE_DIR",
        Path.home() / "trading-engine/store/pit/massive-minute",
    )


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS massive_minute_bars (
        ticker VARCHAR NOT NULL, ts_utc TIMESTAMP NOT NULL,
        o DOUBLE NOT NULL, h DOUBLE NOT NULL, l DOUBLE NOT NULL, c DOUBLE NOT NULL,
        v DOUBLE NOT NULL, vw DOUBLE, n BIGINT, session VARCHAR NOT NULL,
        source_sha256 VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
        PRIMARY KEY(ticker, ts_utc))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS massive_minute_chunks (
        manifest_sha256 VARCHAR NOT NULL, ticker VARCHAR NOT NULL,
        start_date DATE NOT NULL, end_date DATE NOT NULL,
        page_count INTEGER NOT NULL, row_count BIGINT NOT NULL, loaded_at TIMESTAMP NOT NULL,
        PRIMARY KEY(manifest_sha256, ticker, start_date, end_date))"""
    )


def session_close(day: date) -> time:
    early = ((day.month, day.day) in {(7, 3), (12, 24)}
             or day.month == 11 and day.weekday() == 4 and 23 <= day.day <= 29)
    return time(13) if early else time(16)


def session_tag(ts_utc: datetime) -> str:
    if not isinstance(ts_utc, datetime) or ts_utc.utcoffset() is None:
        raise free_sources.FreeSourceError("Massive minute timestamp must be timezone-aware")
    local = ts_utc.astimezone(NEW_YORK)
    if not nyse.is_session(local.date()):
        raise free_sources.FreeSourceError("Massive minute bar is outside an NYSE session date")
    local_time = local.timetz().replace(tzinfo=None)
    if local_time < time(9, 30):
        return "pre"
    if local_time < session_close(local.date()):
        return "regular"
    return "post"


def _number(raw: object, field: str, *, positive: bool = True) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise free_sources.FreeSourceError(f"Massive minute {field} is invalid")
    value = float(raw)
    if not math.isfinite(value) or (positive and value <= 0) or (not positive and value < 0):
        raise free_sources.FreeSourceError(f"Massive minute {field} is invalid")
    return value


def parse_page(body: bytes, *, ticker: str, start: date, end: date) -> tuple[list[dict], str | None]:
    """Validate one ascending aggregate page and tag each bar by NYSE session."""
    if (free_sources.MASSIVE_TICKER.fullmatch(ticker) is None or start > end
            or not isinstance(body, bytes) or not 0 < len(body) <= free_sources.MAX_RESPONSE_BYTES):
        raise free_sources.FreeSourceError("Massive minute request identity is invalid")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise free_sources.FreeSourceError("Massive minute response is not valid JSON") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(payload, dict) and payload.get("status") == "OK" and results is None:
        results = []
    count = payload.get("resultsCount") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or payload.get("status") != "OK"
            or payload.get("adjusted") is not True or payload.get("ticker") != ticker
            or not isinstance(results, list) or len(results) > MAX_PAGE_RESULTS
            or (count is not None and (isinstance(count, bool) or count != len(results)))):
        raise free_sources.FreeSourceError("Massive minute response envelope is invalid")
    next_url = payload.get("next_url")
    if next_url is not None and (not isinstance(next_url, str) or not next_url):
        raise free_sources.FreeSourceError("Massive minute next_url is invalid")
    rows, previous = [], None
    for item in results:
        if not isinstance(item, dict):
            raise free_sources.FreeSourceError("Massive minute bar shape is invalid")
        raw_ts = item.get("t")
        if isinstance(raw_ts, bool) or not isinstance(raw_ts, int) or raw_ts % 60_000:
            raise free_sources.FreeSourceError("Massive minute timestamp is invalid")
        try:
            observed = datetime.fromtimestamp(raw_ts / 1000, timezone.utc)
        except (OSError, OverflowError, ValueError) as exc:
            raise free_sources.FreeSourceError("Massive minute timestamp is invalid") from exc
        local_date = observed.astimezone(NEW_YORK).date()
        if local_date < start or local_date > end or (previous is not None and observed <= previous):
            raise free_sources.FreeSourceError("Massive minute timestamps are out of range or order")
        o, high, low, close = (
            _number(item.get("o"), "open"), _number(item.get("h"), "high"),
            _number(item.get("l"), "low"), _number(item.get("c"), "close"),
        )
        volume = _number(item.get("v"), "volume", positive=False)
        raw_vw, raw_n = item.get("vw"), item.get("n")
        vwap = None if raw_vw is None else _number(raw_vw, "vwap")
        if raw_n is not None and (isinstance(raw_n, bool) or not isinstance(raw_n, int) or raw_n < 0):
            raise free_sources.FreeSourceError("Massive minute transaction count is invalid")
        if low > min(o, high, close) or high < max(o, low, close):
            raise free_sources.FreeSourceError("Massive minute OHLC relationship is invalid")
        rows.append({
            "ticker": ticker, "ts_utc": observed, "o": o, "h": high, "l": low, "c": close,
            "v": volume, "vw": vwap, "n": raw_n, "session": session_tag(observed),
        })
        previous = observed
    return rows, next_url


def load_chunk(
    con: duckdb.DuckDBPyConnection, pages: Iterable[tuple[bytes, datetime]], *,
    manifest_sha256: str, ticker: str, start: date, end: date,
) -> dict:
    if free_sources.SHA256.fullmatch(manifest_sha256) is None:
        raise free_sources.FreeSourceError("Massive minute manifest identity is invalid")
    init_schema(con)
    existing = con.execute(
        """SELECT page_count,row_count FROM massive_minute_chunks
        WHERE manifest_sha256=? AND ticker=? AND start_date=? AND end_date=?""",
        [manifest_sha256, ticker, start, end],
    ).fetchone()
    if existing is not None:
        return {"ticker": ticker, "start": start.isoformat(), "end": end.isoformat(),
                "row_count": existing[1], "inserted": 0, "resumed": True}
    materialized = list(pages)
    parsed: list[dict] = []
    for body, fetched_at in materialized:
        if fetched_at.utcoffset() is None:
            raise free_sources.FreeSourceError("Massive minute fetched_at must be timezone-aware")
        rows, _ = parse_page(body, ticker=ticker, start=start, end=end)
        source_sha = hashlib.sha256(body).hexdigest()
        fetched = fetched_at.astimezone(timezone.utc).replace(tzinfo=None)
        parsed.extend({**row, "source_sha256": source_sha, "fetched_at": fetched} for row in rows)
    timestamps = [row["ts_utc"] for row in parsed]
    if len(timestamps) != len(set(timestamps)):
        raise free_sources.FreeSourceError("Massive minute pages overlap")
    before = int(con.execute(
        "SELECT COUNT(*) FROM massive_minute_bars WHERE ticker=?", [ticker]
    ).fetchone()[0])
    with db.transaction(con):
        if parsed:
            con.executemany(
                """INSERT OR IGNORE INTO massive_minute_bars VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [[row["ticker"], row["ts_utc"].replace(tzinfo=None), row["o"], row["h"],
                  row["l"], row["c"], row["v"], row["vw"], row["n"], row["session"],
                  row["source_sha256"], row["fetched_at"]] for row in parsed],
            )
        con.execute(
            """INSERT INTO massive_minute_chunks VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [manifest_sha256, ticker, start, end, len(materialized), len(parsed),
             datetime.now(timezone.utc).replace(tzinfo=None)],
        )
    after = int(con.execute(
        "SELECT COUNT(*) FROM massive_minute_bars WHERE ticker=?", [ticker]
    ).fetchone()[0])
    return {"ticker": ticker, "start": start.isoformat(), "end": end.isoformat(),
            "row_count": len(parsed), "inserted": after - before, "resumed": False}


def tier_universe(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    """Return exact-ticker Tiingo Stock listings ever in the USD 1--5M MDV60 tier."""
    return con.execute(
        """WITH session_index AS (
            SELECT date, ROW_NUMBER() OVER (ORDER BY date) AS session_no
            FROM (SELECT DISTINCT date FROM free_daily_bars)
        ), canonical AS (
            SELECT b.date,b.ticker,b.c,b.volume,b.vwap
            FROM free_daily_bars b
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY b.date,b.ticker ORDER BY b.fetched_at DESC,b.source_sha256 DESC
            )=1
        ), rolling AS (
            SELECT b.date,b.ticker,
                MEDIAN(COALESCE(b.vwap,b.c)*b.volume) OVER (
                    PARTITION BY b.ticker ORDER BY s.session_no
                    RANGE BETWEEN 60 PRECEDING AND 1 PRECEDING
                ) AS mdv60
            FROM canonical b JOIN session_index s USING(date)
        )
        SELECT r.ticker,COUNT(*) AS tier_sessions
        FROM rolling r
        WHERE r.mdv60 BETWEEN ? AND ?
          AND EXISTS (
            SELECT 1 FROM free_security_master m
            WHERE m.asset_type='Stock' AND m.price_currency='USD' AND m.ticker=r.ticker
              AND r.date>=m.start_date AND (m.end_date IS NULL OR r.date<=m.end_date)
          )
        GROUP BY r.ticker ORDER BY tier_sessions DESC,r.ticker""",
        [MIN_MDV60, MAX_MDV60],
    ).fetchall()


def capture_chunks(start: date, end: date) -> list[tuple[date, date]]:
    sessions, current = [], start
    while current <= end:
        if nyse.is_session(current):
            sessions.append(current)
        current += timedelta(days=1)
    if not sessions:
        raise free_sources.FreeSourceError("Massive minute window has no NYSE sessions")
    return [(batch[0], batch[-1]) for offset in range(0, len(sessions), SESSIONS_PER_CHUNK)
            if (batch := sessions[offset:offset + SESSIONS_PER_CHUNK])]


def manifest_payload(
    con: duckdb.DuckDBPyConnection, *, created_at: datetime, start: date, end: date,
    priority_tickers: set[str] | None = None,
) -> dict:
    priority_tickers = priority_tickers or set()
    frequencies = dict(tier_universe(con))
    tickers = set(frequencies) | set(BENCHMARKS)
    invalid = [ticker for ticker in tickers if free_sources.MASSIVE_TICKER.fullmatch(ticker) is None]
    if invalid:
        raise free_sources.FreeSourceError("Massive minute universe contains an invalid ticker")
    def order(ticker: str) -> tuple:
        if ticker in BENCHMARKS:
            return (0, BENCHMARKS.index(ticker), ticker)
        if ticker in priority_tickers:
            return (1, -frequencies.get(ticker, 0), ticker)
        return (2, -frequencies.get(ticker, 0), ticker)
    ordered = sorted(tickers, key=order)
    chunks = [{"start": first.isoformat(), "end": last.isoformat()}
              for first, last in capture_chunks(start, end)]
    payload = {
        "schema_version": 1,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "chunk_sessions": SESSIONS_PER_CHUNK,
        "chunks": chunks,
        "ticker_count": len(ordered),
        "requests_estimate": len(ordered) * len(chunks),
        "runtime_at_five_per_minute_hours": len(ordered) * len(chunks) / 5 / 60,
        "tickers": [{"ticker": ticker, "tier_sessions": frequencies.get(ticker, 0),
                     "priority": "benchmark" if ticker in BENCHMARKS else
                     "holdout" if ticker in priority_tickers else "tier_frequency"}
                    for ticker in ordered],
    }
    identity = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**payload, "manifest_sha256": identity}
