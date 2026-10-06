"""Parse and store bounded Massive option-contract and daily-bar captures."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from engine import free_sources
from engine.lib.settings import REPO_ROOT

CONTRACT_SOURCE = "massive_option_contracts"
DAILY_SOURCE = "massive_option_daily"
OCC = re.compile(r"^[A-Z0-9.]{1,6}[0-9]{6}[CP][0-9]{8}$")
MAX_CONTRACT_RESULTS = 1_000
MAX_DAILY_RESULTS = 64


def _configured_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def default_database() -> Path:
    return _configured_path(
        "TRADING_ENGINE_MASSIVE_OPTIONS_DB", REPO_ROOT / "store/pit/options.duckdb"
    )


def default_data_dir() -> Path:
    return _configured_path(
        "TRADING_ENGINE_MASSIVE_OPTIONS_DIR", REPO_ROOT / "store/pit/options"
    )


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS option_contracts (
        as_of DATE NOT NULL, occ VARCHAR NOT NULL, underlying VARCHAR NOT NULL,
        expiry DATE NOT NULL, strike DOUBLE NOT NULL, "right" VARCHAR NOT NULL,
        exercise_style VARCHAR, shares_per_contract INTEGER, cfi VARCHAR,
        primary_exchange VARCHAR, source_sha256 VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL, PRIMARY KEY(as_of, occ))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS option_daily_bars (
        occ VARCHAR NOT NULL, date DATE NOT NULL,
        o DOUBLE, h DOUBLE, l DOUBLE, c DOUBLE, v DOUBLE, vw DOUBLE, n BIGINT,
        source VARCHAR NOT NULL, source_sha256 VARCHAR NOT NULL,
        fetched_at TIMESTAMP NOT NULL, PRIMARY KEY(occ, date))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS option_capture_receipts (
        request_key VARCHAR PRIMARY KEY, url VARCHAR, http_status INTEGER,
        source_sha256 VARCHAR, fetched_at TIMESTAMP, row_count BIGINT)"""
    )


def _body(payload: bytes, label: str) -> dict:
    if not isinstance(payload, bytes) or not 0 < len(payload) <= free_sources.MAX_RESPONSE_BYTES:
        raise free_sources.FreeSourceError(f"Massive option {label} response size is invalid")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise free_sources.FreeSourceError(
            f"Massive option {label} response is not valid JSON"
        ) from exc
    if not isinstance(decoded, dict) or decoded.get("status") != "OK":
        raise free_sources.FreeSourceError(f"Massive option {label} response status is invalid")
    return decoded


def _source_sha(body: bytes, expected: str | None) -> str:
    actual = hashlib.sha256(body).hexdigest()
    if expected is not None and actual != expected:
        raise free_sources.FreeSourceError("Massive option cached response hash is invalid")
    return actual


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise free_sources.FreeSourceError("Massive option fetched_at must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise free_sources.FreeSourceError(f"Massive option {field} is invalid")
    return value


def _number(value: object, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise free_sources.FreeSourceError(f"Massive option {field} is invalid")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or (not allow_zero and parsed == 0):
        raise free_sources.FreeSourceError(f"Massive option {field} is invalid")
    return parsed


def _occ_identity(raw: object) -> tuple[str, str, date, str, float]:
    ticker = raw[2:] if isinstance(raw, str) and raw.startswith("O:") else raw
    if not isinstance(ticker, str) or OCC.fullmatch(ticker) is None:
        raise free_sources.FreeSourceError("Massive OCC ticker is invalid")
    root, suffix = ticker[:-15], ticker[-15:]
    try:
        expiry = datetime.strptime(suffix[:6], "%y%m%d").date()
    except ValueError as exc:
        raise free_sources.FreeSourceError("Massive OCC expiry is invalid") from exc
    return ticker, root, expiry, suffix[6], int(suffix[7:]) / 1000.0


def parse_contracts_page(
    body: bytes, *, underlying: str, expiry_min: date, expiry_max: date,
    strike_min: float, strike_max: float,
) -> tuple[list[dict], str | None]:
    payload = _body(body, "contracts")
    results = payload.get("results", [])
    next_url = payload.get("next_url")
    if (
        not isinstance(results, list)
        or len(results) > MAX_CONTRACT_RESULTS
        or (next_url is not None and (not isinstance(next_url, str) or not next_url))
    ):
        raise free_sources.FreeSourceError("Massive option contracts envelope is invalid")
    rows = []
    for item in results:
        if not isinstance(item, dict):
            raise free_sources.FreeSourceError("Massive option contract row shape is invalid")
        occ, root, occ_expiry, occ_right, occ_strike = _occ_identity(item.get("ticker"))
        try:
            expiry = date.fromisoformat(item.get("expiration_date"))
        except (TypeError, ValueError) as exc:
            raise free_sources.FreeSourceError("Massive option expiry is invalid") from exc
        right = {"call": "C", "put": "P"}.get(item.get("contract_type"))
        strike = _number(item.get("strike_price"), "strike")
        shares = item.get("shares_per_contract")
        if (
            item.get("underlying_ticker") != underlying
            or root != underlying
            or right is None
            or expiry != occ_expiry
            or right != occ_right
            or abs(strike - occ_strike) > 1e-9
            or not expiry_min <= expiry <= expiry_max
            or not strike_min <= strike <= strike_max
            or isinstance(shares, bool)
            or not isinstance(shares, int)
            or shares <= 0
        ):
            raise free_sources.FreeSourceError("Massive option contract identity is invalid")
        rows.append({
            "occ": occ, "underlying": underlying, "expiry": expiry, "strike": strike,
            "right": right,
            "exercise_style": _optional_text(item.get("exercise_style"), "exercise style"),
            "shares_per_contract": shares,
            "cfi": _optional_text(item.get("cfi"), "CFI"),
            "primary_exchange": _optional_text(
                item.get("primary_exchange"), "primary exchange"
            ),
        })
    return rows, next_url


def load_contracts_page(
    con: duckdb.DuckDBPyConnection, body: bytes, *, as_of: date, underlying: str,
    expiry_min: date, expiry_max: date, strike_min: float, strike_max: float,
    fetched_at: datetime, expected_sha256: str | None = None,
) -> dict:
    source_sha = _source_sha(body, expected_sha256)
    rows, next_url = parse_contracts_page(
        body, underlying=underlying, expiry_min=expiry_min, expiry_max=expiry_max,
        strike_min=strike_min, strike_max=strike_max,
    )
    fetched = _utc_naive(fetched_at)
    init_schema(con)
    before = con.execute(
        "SELECT COUNT(*) FROM option_contracts WHERE as_of=?", [as_of]
    ).fetchone()[0]
    con.executemany(
        "INSERT OR IGNORE INTO option_contracts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [[
            as_of, row["occ"], row["underlying"], row["expiry"], row["strike"],
            row["right"], row["exercise_style"], row["shares_per_contract"], row["cfi"],
            row["primary_exchange"], source_sha, fetched,
        ] for row in rows],
    )
    after = con.execute(
        "SELECT COUNT(*) FROM option_contracts WHERE as_of=?", [as_of]
    ).fetchone()[0]
    return {"row_count": len(rows), "inserted": after - before, "next_url": next_url}


def parse_daily_bars_page(
    body: bytes, *, occ: str, start: date, end: date,
) -> tuple[list[dict], str | None]:
    payload = _body(body, "daily bars")
    results = payload.get("results", [])
    next_url = payload.get("next_url")
    if (
        payload.get("adjusted") is not True
        or payload.get("ticker") != f"O:{occ}"
        or not isinstance(results, list)
        or len(results) > MAX_DAILY_RESULTS
        or (next_url is not None and (not isinstance(next_url, str) or not next_url))
    ):
        raise free_sources.FreeSourceError("Massive option daily-bars envelope is invalid")
    rows, previous = [], None
    for item in results:
        if not isinstance(item, dict):
            raise free_sources.FreeSourceError("Massive option daily bar shape is invalid")
        raw_ts = item.get("t")
        if isinstance(raw_ts, bool) or not isinstance(raw_ts, int):
            raise free_sources.FreeSourceError("Massive option daily timestamp is invalid")
        try:
            observed = datetime.fromtimestamp(raw_ts / 1000, timezone.utc).date()
        except (OSError, OverflowError, ValueError) as exc:
            raise free_sources.FreeSourceError("Massive option daily timestamp is invalid") from exc
        if not start <= observed <= end or (previous is not None and observed <= previous):
            raise free_sources.FreeSourceError("Massive option daily dates are out of range or order")
        o = _number(item.get("o"), "open")
        high = _number(item.get("h"), "high")
        low = _number(item.get("l"), "low")
        close = _number(item.get("c"), "close")
        volume = _number(item.get("v"), "volume", allow_zero=True)
        vwap = None if item.get("vw") is None else _number(item.get("vw"), "VWAP")
        count = item.get("n")
        if (
            low > min(o, high, close)
            or high < max(o, low, close)
            or (count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ))
        ):
            raise free_sources.FreeSourceError("Massive option daily bar is invalid")
        rows.append({
            "date": observed, "o": o, "h": high, "l": low, "c": close,
            "v": volume, "vw": vwap, "n": count,
        })
        previous = observed
    return rows, next_url


def load_daily_bars_page(
    con: duckdb.DuckDBPyConnection, body: bytes, *, occ: str, start: date, end: date,
    fetched_at: datetime, expected_sha256: str | None = None,
) -> dict:
    source_sha = _source_sha(body, expected_sha256)
    rows, next_url = parse_daily_bars_page(body, occ=occ, start=start, end=end)
    fetched = _utc_naive(fetched_at)
    init_schema(con)
    before = con.execute(
        "SELECT COUNT(*) FROM option_daily_bars WHERE occ=?", [occ]
    ).fetchone()[0]
    con.executemany(
        "INSERT OR IGNORE INTO option_daily_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [[
            occ, row["date"], row["o"], row["h"], row["l"], row["c"], row["v"],
            row["vw"], row["n"], DAILY_SOURCE, source_sha, fetched,
        ] for row in rows],
    )
    after = con.execute(
        "SELECT COUNT(*) FROM option_daily_bars WHERE occ=?", [occ]
    ).fetchone()[0]
    return {"row_count": len(rows), "inserted": after - before, "next_url": next_url}


def record_receipt(
    con: duckdb.DuckDBPyConnection, *, request_key: str, url: str,
    source_sha256: str, fetched_at: datetime, row_count: int,
) -> None:
    init_schema(con)
    con.execute(
        "INSERT OR IGNORE INTO option_capture_receipts VALUES (?, ?, 200, ?, ?, ?)",
        [request_key, url, source_sha256, _utc_naive(fetched_at), row_count],
    )
