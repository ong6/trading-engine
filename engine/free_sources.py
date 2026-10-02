"""Isolated parsing and storage for P3's free survivor-data sources."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import zipfile
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db
from engine.lib.settings import REPO_ROOT

TIINGO_SOURCE = "tiingo_supported_tickers"
MASSIVE_SOURCE = "massive_grouped_daily"
TIINGO_COLUMNS = (
    "ticker", "exchange", "assetType", "priceCurrency", "startDate", "endDate"
)
US_STOCK_EXCHANGES = frozenset({
    "AMEX", "ARCA", "BATS", "CBOE", "IEX", "NASDAQ", "NYSE", "NYSE ARCA", "NYSE MKT",
    "NYSE NAT",
})
MAX_ARCHIVE_BYTES = 64_000_000
MAX_UNCOMPRESSED_BYTES = 128_000_000
MAX_RESPONSE_BYTES = 32_000_000
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MASSIVE_TICKER = re.compile(r"^[A-Z0-9][A-Za-z0-9./^-]{0,31}$")  # lowercase marks preferreds/warrants


class FreeSourceError(ValueError):
    """A free-source response or local artifact violates the Phase 0 contract."""


def _configured_path(environ: Mapping[str, str], name: str, default: Path) -> Path:
    raw = environ.get(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def default_database(environ: Mapping[str, str] = os.environ) -> Path:
    return _configured_path(
        environ, "TRADING_ENGINE_FREE_SOURCES_DB", REPO_ROOT / "store/pit/free-sources.duckdb"
    )


def default_data_dir(environ: Mapping[str, str] = os.environ) -> Path:
    return _configured_path(
        environ, "TRADING_ENGINE_FREE_SOURCES_DIR", REPO_ROOT / "store/pit/free-sources"
    )


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS free_security_master (
        source VARCHAR NOT NULL, source_sha256 VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
        source_row BIGINT NOT NULL, ticker VARCHAR NOT NULL, exchange VARCHAR NOT NULL,
        asset_type VARCHAR NOT NULL, price_currency VARCHAR NOT NULL,
        start_date DATE NOT NULL, end_date DATE,
        PRIMARY KEY(source_sha256, source_row))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS free_daily_bars (
        date DATE NOT NULL, ticker VARCHAR NOT NULL,
        o DOUBLE NOT NULL, h DOUBLE NOT NULL, l DOUBLE NOT NULL, c DOUBLE NOT NULL,
        volume DOUBLE NOT NULL, vwap DOUBLE, source VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL, source_sha256 VARCHAR NOT NULL,
        PRIMARY KEY(source_sha256, date, ticker))"""
    )
    # Fractional-share trading makes consolidated volume non-integer; widen older tables.
    volume_type = con.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='free_daily_bars' AND column_name='volume'"
    ).fetchone()
    if volume_type and volume_type[0] != "DOUBLE":
        con.execute("ALTER TABLE free_daily_bars ALTER volume TYPE DOUBLE")
    con.execute(
        """CREATE TABLE IF NOT EXISTS free_daily_bars_rejected (
        date DATE NOT NULL, row_index BIGINT NOT NULL, ticker VARCHAR, reason VARCHAR NOT NULL,
        raw_item VARCHAR NOT NULL, source VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
        source_sha256 VARCHAR NOT NULL, PRIMARY KEY(source_sha256, row_index))"""
    )


def _utc_naive(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise FreeSourceError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _iso_date(raw: object, field: str, *, optional: bool = False) -> date | None:
    if optional and raw == "":
        return None
    if not isinstance(raw, str):
        raise FreeSourceError(f"{field} is invalid")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise FreeSourceError(f"{field} is invalid") from exc
    if parsed.isoformat() != raw:
        raise FreeSourceError(f"{field} is not canonical")
    return parsed


def parse_tiingo_archive(body: bytes) -> list[dict]:
    """Return the USD Stock rows on named US exchanges from one exact Tiingo ZIP."""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_ARCHIVE_BYTES:
        raise FreeSourceError("Tiingo archive size is invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1:
                raise FreeSourceError("Tiingo archive must contain one file")
            member = members[0]
            path = Path(member.filename)
            if (path.is_absolute() or ".." in path.parts or member.flag_bits & 0x1
                    or member.file_size > MAX_UNCOMPRESSED_BYTES):
                raise FreeSourceError("Tiingo archive member is unsafe")
            raw = archive.read(member)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise FreeSourceError("Tiingo archive is unreadable") from exc
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise FreeSourceError("Tiingo archive expands beyond the size limit")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict")))
    except UnicodeDecodeError as exc:
        raise FreeSourceError("Tiingo CSV is not UTF-8") from exc
    if tuple(reader.fieldnames or ()) != TIINGO_COLUMNS:
        raise FreeSourceError("Tiingo CSV columns are invalid")
    rows = []
    for source_row, raw_row in enumerate(reader, 2):
        if set(raw_row) != set(TIINGO_COLUMNS) or any(value is None for value in raw_row.values()):
            raise FreeSourceError(f"Tiingo row {source_row} shape is invalid")
        exchange = raw_row["exchange"].strip().upper()
        if (raw_row["assetType"].strip() != "Stock"
                or raw_row["priceCurrency"].strip().upper() != "USD"
                or exchange not in US_STOCK_EXCHANGES):
            continue
        ticker = raw_row["ticker"].strip().upper()
        if not ticker or len(ticker) > 64 or not ticker.isprintable():
            raise FreeSourceError(f"Tiingo row {source_row} ticker is invalid")
        start = _iso_date(raw_row["startDate"].strip(), f"Tiingo row {source_row} startDate")
        end = _iso_date(
            raw_row["endDate"].strip(), f"Tiingo row {source_row} endDate", optional=True
        )
        if end is not None and start > end:
            raise FreeSourceError(f"Tiingo row {source_row} interval is invalid")
        rows.append({
            "source_row": source_row, "ticker": ticker, "exchange": exchange,
            "asset_type": "Stock", "price_currency": "USD",
            "start_date": start, "end_date": end,
        })
    if not rows:
        raise FreeSourceError("Tiingo archive has no admitted US Stock rows")
    return rows


def load_security_master(
    con: duckdb.DuckDBPyConnection, body: bytes, *, fetched_at: datetime,
) -> dict:
    rows = parse_tiingo_archive(body)
    source_sha = hashlib.sha256(body).hexdigest()
    fetched = _utc_naive(fetched_at, "fetched_at")
    init_schema(con)
    before = int(con.execute(
        "SELECT COUNT(*) FROM free_security_master WHERE source_sha256=?", [source_sha]
    ).fetchone()[0])
    with db.transaction(con):
        con.executemany(
            """INSERT OR IGNORE INTO free_security_master VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [[TIINGO_SOURCE, source_sha, fetched, row["source_row"], row["ticker"],
              row["exchange"], row["asset_type"], row["price_currency"],
              row["start_date"], row["end_date"]] for row in rows],
        )
    stored = int(con.execute(
        "SELECT COUNT(*) FROM free_security_master WHERE source_sha256=?", [source_sha]
    ).fetchone()[0])
    if stored != len(rows):
        raise FreeSourceError("stored Tiingo batch differs from the source archive")
    return {
        "source": TIINGO_SOURCE, "source_sha256": source_sha, "row_count": len(rows),
        "inserted": stored - before, "replayed": before == stored,
    }


def _number(raw: object, field: str, *, positive: bool = True) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise FreeSourceError(f"Massive {field} is invalid")
    value = float(raw)
    if not math.isfinite(value) or (positive and value <= 0) or (not positive and value < 0):
        raise FreeSourceError(f"Massive {field} is invalid")
    return value


def _massive_reject(index: int, item: object, reason: str) -> dict:
    ticker = item.get("T") if isinstance(item, dict) else None
    return {"row_index": index, "ticker": ticker if isinstance(ticker, str) else None,
            "reason": reason,
            "raw_item": json.dumps(item, sort_keys=True, separators=(",", ":"))}


MASSIVE_MAX_REJECTED_SHARE = 0.05


def parse_massive_grouped_daily_with_rejects(
    body: bytes, session_date: date,
) -> tuple[list[dict], list[dict]]:
    """Validate a recorded adjusted grouped-daily response without network access.

    The envelope is all-or-nothing. Individual bars that fail validation are returned as
    rejects with a reason instead of failing the date, because real consolidated data carries
    a few malformed prints; more than MASSIVE_MAX_REJECTED_SHARE rejects fails the date.
    """
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_RESPONSE_BYTES:
        raise FreeSourceError("Massive response size is invalid")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise FreeSourceError("Massive response is not valid JSON") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    count = payload.get("resultsCount") if isinstance(payload, dict) else None
    if isinstance(payload, dict) and payload.get("status") == "OK" and count == 0 \
            and results is None:
        results = []
    if (payload.get("status") != "OK" or payload.get("adjusted") is not True
            or isinstance(count, bool) or not isinstance(count, int) or count < 0
            or not isinstance(results, list) or count != len(results)):
        raise FreeSourceError("Massive response envelope is invalid")
    parsed, rejected, seen = [], [], set()
    for index, item in enumerate(results):
        ticker = item.get("T") if isinstance(item, dict) else None

        if not isinstance(item, dict):
            rejected.append(_massive_reject(index, item, "shape"))
            continue
        timestamp = item.get("t")
        if not isinstance(ticker, str) or MASSIVE_TICKER.fullmatch(ticker) is None:
            rejected.append(_massive_reject(index, item, "ticker_format"))
            continue
        if ticker in seen:
            rejected.append(_massive_reject(index, item, "duplicate_ticker"))
            continue
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            rejected.append(_massive_reject(index, item, "timestamp"))
            continue
        try:
            event_date = datetime.fromtimestamp(timestamp / 1000, timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            rejected.append(_massive_reject(index, item, "timestamp"))
            continue
        if event_date != session_date:
            rejected.append(_massive_reject(index, item, "date_mismatch"))
            continue
        try:
            o, high, low, close = (
                _number(item.get("o"), "open"), _number(item.get("h"), "high"),
                _number(item.get("l"), "low"), _number(item.get("c"), "close"),
            )
            volume_value = _number(item.get("v"), "volume", positive=False)
            raw_vwap = item.get("vw")
            vwap = None if raw_vwap is None else _number(raw_vwap, "vwap")
        except FreeSourceError:
            rejected.append(_massive_reject(index, item, "number"))
            continue
        if low > min(o, high, close) or high < max(o, low, close):
            rejected.append(_massive_reject(index, item, "ohlc_relationship"))
            continue
        parsed.append({
            "date": session_date, "ticker": ticker, "o": o, "h": high, "l": low,
            "c": close, "volume": volume_value, "vwap": vwap,
        })
        seen.add(ticker)
    if results and len(rejected) > MASSIVE_MAX_REJECTED_SHARE * len(results):
        raise FreeSourceError(
            f"Massive rejected {len(rejected)} of {len(results)} bars, above the "
            f"{MASSIVE_MAX_REJECTED_SHARE:.0%} limit"
        )
    return parsed, rejected


def parse_massive_grouped_daily(body: bytes, session_date: date) -> list[dict]:
    """Return the accepted bars of a recorded grouped-daily response."""
    return parse_massive_grouped_daily_with_rejects(body, session_date)[0]


def load_daily_bars(
    con: duckdb.DuckDBPyConnection, body: bytes, *, session_date: date, fetched_at: datetime,
) -> dict:
    rows, rejected = parse_massive_grouped_daily_with_rejects(body, session_date)
    source_sha = hashlib.sha256(body).hexdigest()
    fetched = _utc_naive(fetched_at, "fetched_at")
    init_schema(con)
    before = int(con.execute(
        "SELECT COUNT(*) FROM free_daily_bars WHERE source_sha256=?", [source_sha]
    ).fetchone()[0])
    with db.transaction(con):
        if rows:
            con.executemany(
                """INSERT OR IGNORE INTO free_daily_bars VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [[row["date"], row["ticker"], row["o"], row["h"], row["l"], row["c"],
                  row["volume"], row["vwap"], MASSIVE_SOURCE, fetched, source_sha]
                 for row in rows],
            )
        if rejected:
            con.executemany(
                """INSERT OR IGNORE INTO free_daily_bars_rejected VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)""",
                [[session_date, item["row_index"], item["ticker"], item["reason"],
                  item["raw_item"], MASSIVE_SOURCE, fetched, source_sha]
                 for item in rejected],
            )
    stored = int(con.execute(
        "SELECT COUNT(*) FROM free_daily_bars WHERE source_sha256=?", [source_sha]
    ).fetchone()[0])
    if stored != len(rows):
        raise FreeSourceError("stored Massive batch differs from the recorded response")
    return {
        "source": MASSIVE_SOURCE, "source_sha256": source_sha, "date": session_date.isoformat(),
        "row_count": len(rows), "inserted": stored - before, "replayed": before == stored,
        "rejected": len(rejected),
    }
