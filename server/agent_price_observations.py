"""Append-only normalized daily-price observations for agent decisions."""

from __future__ import annotations

import argparse
import math
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB
from sim.strategies.configs import config_by_id

SOURCE_NAME = "yfinance"
SOURCE_ADAPTER = "yfinance.download"
SOURCE_ADAPTER_VERSION = "auto_adjust_false_v1"
OBSERVATION_SCHEMA_VERSION = 1
CLASSIFICATIONS = frozenset(
    {"baseline_snapshot", "unchanged_observation", "value_revision"}
)


class ObservationError(ValueError):
    """A price row cannot be retained as an immutable normalized observation."""


def _utc(value: datetime, field: str) -> datetime:
    if type(value) is not datetime:
        raise ObservationError(f"{field} is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _library_version() -> str:
    try:
        value = version("yfinance")
    except PackageNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise ObservationError("yfinance version is unavailable") from exc
    if not value or len(value) > 64 or not value.isprintable():
        raise ObservationError("yfinance version is invalid")
    return value


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the append-only observation ledger without changing `prices`."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_daily_price_observations (
            id                          BIGINT PRIMARY KEY,
            schema_version              INTEGER NOT NULL,
            ticker                      VARCHAR NOT NULL,
            market_date                 DATE NOT NULL,
            open                        DOUBLE NOT NULL,
            high                        DOUBLE NOT NULL,
            low                         DOUBLE NOT NULL,
            close                       DOUBLE NOT NULL,
            volume                      BIGINT NOT NULL,
            source                      VARCHAR NOT NULL,
            source_fetched_at           TIMESTAMP NOT NULL,
            observed_at                 TIMESTAMP NOT NULL,
            source_adapter              VARCHAR NOT NULL,
            source_adapter_version      VARCHAR NOT NULL,
            source_library_version      VARCHAR NOT NULL,
            normalized_sha256           VARCHAR NOT NULL,
            value_sha256                VARCHAR NOT NULL,
            observation_sequence        INTEGER NOT NULL,
            value_revision              INTEGER NOT NULL,
            classification              VARCHAR NOT NULL,
            previous_observation_sha256 VARCHAR,
            observation_sha256          VARCHAR NOT NULL UNIQUE,
            UNIQUE (ticker, market_date, observation_sequence)
        )
        """
    )


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservationError(f"price {field} is invalid")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ObservationError(f"price {field} is not positive and finite")
    return result


def _volume(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or not float(value).is_integer()
    ):
        raise ObservationError("price volume is invalid")
    return int(value)


def _normalized(
    row: tuple,
    *,
    observed_at: datetime,
) -> tuple[dict, dict, datetime]:
    ticker, market_date, open_price, high, low, close, volume, source, fetched_at = row
    if (
        not isinstance(ticker, str)
        or not ticker
        or ticker != ticker.upper()
        or len(ticker) > 32
        or not ticker.isprintable()
        or type(market_date) is not date
        or source != SOURCE_NAME
    ):
        raise ObservationError("price observation identity is invalid")
    source_fetched_at = _utc(fetched_at, "source fetched_at")
    if source_fetched_at.date() < market_date:
        raise ObservationError("price source ingestion precedes market date")
    if _utc(observed_at, "observation time") < source_fetched_at:
        raise ObservationError("price observation precedes source ingestion")
    open_value = _number(open_price, "open")
    high_value = _number(high, "high")
    low_value = _number(low, "low")
    close_value = _number(close, "close")
    volume_value = _volume(volume)
    if low_value > min(open_value, high_value, close_value) or high_value < max(
        open_value, low_value, close_value
    ):
        raise ObservationError("price OHLC values are inconsistent")
    normalized = {
        "ticker": ticker,
        "market_date": market_date.isoformat(),
        "open": open_value,
        "high": high_value,
        "low": low_value,
        "close": close_value,
        "volume": volume_value,
        "source": source,
        "latest_ingested_at": _timestamp(source_fetched_at),
    }
    value = {
        key: normalized[key]
        for key in ("ticker", "market_date", "open", "high", "low", "close", "volume", "source")
    }
    return normalized, value, source_fetched_at


def _next_id(con: duckdb.DuckDBPyConnection) -> int:
    return int(
        con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM agent_daily_price_observations"
        ).fetchone()[0]
    )


def _capture_rows(
    con: duckdb.DuckDBPyConnection,
    rows: list[tuple],
    *,
    observed_at: datetime,
) -> dict:
    """Append changed provider observations. The caller owns the transaction."""
    observed_at = _utc(observed_at, "observation time")
    library_version = _library_version()
    prepared = []
    seen = set()
    for row in rows:
        normalized, value, source_fetched_at = _normalized(
            row, observed_at=observed_at
        )
        key = (normalized["ticker"], date.fromisoformat(normalized["market_date"]))
        if key in seen:
            raise ObservationError("price capture contains a duplicate ticker/date")
        seen.add(key)
        prepared.append((row, normalized, value, source_fetched_at))

    inserted = 0
    baseline = 0
    unchanged = 0
    revisions = 0
    next_id = _next_id(con)
    for row, normalized, value, source_fetched_at in prepared:
        ticker, market_date = row[0], row[1]
        latest = con.execute(
            "SELECT source_fetched_at, normalized_sha256, value_sha256, "
            "observation_sequence, value_revision, observation_sha256 "
            "FROM agent_daily_price_observations "
            "WHERE ticker = ? AND market_date = ? "
            "ORDER BY observation_sequence DESC LIMIT 1",
            [ticker, market_date],
        ).fetchone()
        normalized_sha256 = canonical_sha256(normalized)
        value_sha256 = canonical_sha256(value)
        if (
            latest is not None
            and _utc(latest[0], "stored source fetched_at") == source_fetched_at
            and latest[1] == normalized_sha256
        ):
            continue
        if latest is None:
            sequence = 1
            revision = 1
            classification = "baseline_snapshot"
            previous = None
            baseline += 1
        else:
            if source_fetched_at < _utc(
                latest[0], "stored source fetched_at"
            ):
                raise ObservationError("price source ingestion moved backward")
            sequence = int(latest[3]) + 1
            previous = latest[5]
            if value_sha256 == latest[2]:
                revision = int(latest[4])
                classification = "unchanged_observation"
                unchanged += 1
            else:
                revision = int(latest[4]) + 1
                classification = "value_revision"
                revisions += 1
        identity = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "ticker": ticker,
            "market_date": market_date.isoformat(),
            "normalized_sha256": normalized_sha256,
            "value_sha256": value_sha256,
            "source_fetched_at": _timestamp(source_fetched_at),
            "observed_at": _timestamp(observed_at),
            "source_adapter": SOURCE_ADAPTER,
            "source_adapter_version": SOURCE_ADAPTER_VERSION,
            "source_library_version": library_version,
            "observation_sequence": sequence,
            "value_revision": revision,
            "classification": classification,
            "previous_observation_sha256": previous,
        }
        observation_sha256 = canonical_sha256(identity)
        con.execute(
            "INSERT INTO agent_daily_price_observations ("
            "id, schema_version, ticker, market_date, open, high, low, close, "
            "volume, source, source_fetched_at, observed_at, source_adapter, "
            "source_adapter_version, source_library_version, normalized_sha256, "
            "value_sha256, observation_sequence, value_revision, classification, "
            "previous_observation_sha256, observation_sha256"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                next_id,
                OBSERVATION_SCHEMA_VERSION,
                ticker,
                market_date,
                normalized["open"],
                normalized["high"],
                normalized["low"],
                normalized["close"],
                normalized["volume"],
                normalized["source"],
                source_fetched_at,
                observed_at,
                SOURCE_ADAPTER,
                SOURCE_ADAPTER_VERSION,
                library_version,
                normalized_sha256,
                value_sha256,
                sequence,
                revision,
                classification,
                previous,
                observation_sha256,
            ],
        )
        next_id += 1
        inserted += 1
    return {
        "selected_rows": len(rows),
        "inserted_observations": inserted,
        "baseline_snapshots": baseline,
        "unchanged_observations": unchanged,
        "value_revisions": revisions,
    }


def _strategy_scope(strategy_id: str) -> tuple[list[str], int]:
    try:
        config = config_by_id(strategy_id)
    except KeyError as exc:
        raise ObservationError("strategy is unavailable") from exc
    params = config.get("params")
    if not isinstance(params, dict):
        raise ObservationError("strategy parameters are invalid")
    tickers = set()
    for field in ("assets", "sectors"):
        values = params.get(field, [])
        if isinstance(values, list):
            tickers.update(value for value in values if isinstance(value, str))
    for field in ("cash_proxy", "ticker"):
        value = params.get(field)
        if isinstance(value, str):
            tickers.add(value)
    raw_lookbacks = params.get("lookbacks")
    if raw_lookbacks is None:
        raw_lookbacks = [params.get("lookback")]
    lookbacks = [
        value
        for value in raw_lookbacks
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    if not tickers or not lookbacks or len(lookbacks) != len(raw_lookbacks):
        raise ObservationError("strategy price scope is invalid")
    return sorted(tickers), max(lookbacks) + 1


def capture_strategy_scope(
    con: duckdb.DuckDBPyConnection,
    strategy_id: str,
    market_date: date,
    *,
    observed_at: datetime | None = None,
) -> dict:
    """Capture exactly the price history that can enter one strategy context."""
    if type(market_date) is not date:
        raise ObservationError("market date is invalid")
    tickers, required = _strategy_scope(strategy_id)
    rows = []
    for ticker in tickers:
        rows.extend(
            con.execute(
                "SELECT ticker, date, open, high, low, close, volume, source, fetched_at "
                "FROM prices WHERE ticker = ? AND date <= ? "
                "ORDER BY date DESC LIMIT ?",
                [ticker, market_date, required],
            ).fetchall()
        )
    captured_at = observed_at or datetime.now(timezone.utc)
    init_schema(con)
    with engine_db.transaction(con):
        result = _capture_rows(con, rows, observed_at=captured_at)
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "market_date": market_date.isoformat(),
        "required_tickers": tickers,
        "required_rows_per_ticker": required,
        "observed_at": _timestamp(captured_at),
        **result,
    }


def observation_for_price_row(
    con: duckdb.DuckDBPyConnection,
    row: tuple,
) -> dict | None:
    """Return and verify the immutable observation matching one current row."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_daily_price_observations'"
    ).fetchone()
    if exists is None:
        return None
    ticker, market_date, open_price, high, low, close, volume, source, fetched_at = row
    match = con.execute(
        "SELECT schema_version, open, high, low, close, volume, source, "
        "source_fetched_at, observed_at, source_adapter, source_adapter_version, "
        "source_library_version, normalized_sha256, value_sha256, "
        "observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256 "
        "FROM agent_daily_price_observations "
        "WHERE ticker = ? AND market_date = ? AND open = ? AND high = ? AND low = ? "
        "AND close = ? AND volume = ? AND source = ? AND source_fetched_at = ? "
        "ORDER BY observation_sequence DESC LIMIT 1",
        [
            ticker,
            market_date,
            open_price,
            high,
            low,
            close,
            volume,
            source,
            fetched_at,
        ],
    ).fetchone()
    if match is None:
        return None
    observed_at = _utc(match[8], "stored observation time")
    normalized, value, source_fetched_at = _normalized(
        row, observed_at=observed_at
    )
    identity = {
        "schema_version": match[0],
        "ticker": ticker,
        "market_date": market_date.isoformat(),
        "normalized_sha256": match[12],
        "value_sha256": match[13],
        "source_fetched_at": _timestamp(source_fetched_at),
        "observed_at": _timestamp(observed_at),
        "source_adapter": match[9],
        "source_adapter_version": match[10],
        "source_library_version": match[11],
        "observation_sequence": match[14],
        "value_revision": match[15],
        "classification": match[16],
        "previous_observation_sha256": match[17],
    }
    if (
        match[0] != OBSERVATION_SCHEMA_VERSION
        or match[9] != SOURCE_ADAPTER
        or match[10] != SOURCE_ADAPTER_VERSION
        or match[16] not in CLASSIFICATIONS
        or canonical_sha256(normalized) != match[12]
        or canonical_sha256(value) != match[13]
        or canonical_sha256(identity) != match[18]
    ):
        raise ObservationError("stored price observation identity is invalid")
    return {
        **identity,
        "source_library_version": match[11],
        "observation_sha256": match[18],
        "normalized": normalized,
    }


def _verify_ledger(con: duckdb.DuckDBPyConnection) -> None:
    previous_by_key: dict[tuple[str, date], tuple[int, int, str, str]] = {}
    rows = con.execute(
        "SELECT ticker, market_date, open, high, low, close, volume, source, "
        "source_fetched_at, observed_at, source_adapter, source_adapter_version, "
        "source_library_version, normalized_sha256, value_sha256, "
        "observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256, schema_version "
        "FROM agent_daily_price_observations "
        "ORDER BY ticker, market_date, observation_sequence"
    ).fetchall()
    for row in rows:
        price_row = (*row[:8], row[8])
        observed_at = _utc(row[9], "stored observation time")
        normalized, value, source_fetched_at = _normalized(
            price_row, observed_at=observed_at
        )
        key = (row[0], row[1])
        previous = previous_by_key.get(key)
        expected_sequence = 1 if previous is None else previous[0] + 1
        expected_previous = None if previous is None else previous[3]
        if previous is None:
            expected_revision = 1
            expected_classification = "baseline_snapshot"
        elif row[14] == previous[2]:
            expected_revision = previous[1]
            expected_classification = "unchanged_observation"
        else:
            expected_revision = previous[1] + 1
            expected_classification = "value_revision"
        identity = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "ticker": row[0],
            "market_date": row[1].isoformat(),
            "normalized_sha256": row[13],
            "value_sha256": row[14],
            "source_fetched_at": _timestamp(source_fetched_at),
            "observed_at": _timestamp(observed_at),
            "source_adapter": row[10],
            "source_adapter_version": row[11],
            "source_library_version": row[12],
            "observation_sequence": row[15],
            "value_revision": row[16],
            "classification": row[17],
            "previous_observation_sha256": row[18],
        }
        if (
            row[20] != OBSERVATION_SCHEMA_VERSION
            or row[10] != SOURCE_ADAPTER
            or row[11] != SOURCE_ADAPTER_VERSION
            or row[15] != expected_sequence
            or row[16] != expected_revision
            or row[17] != expected_classification
            or row[18] != expected_previous
            or canonical_sha256(normalized) != row[13]
            or canonical_sha256(value) != row[14]
            or canonical_sha256(identity) != row[19]
        ):
            raise ObservationError("stored price observation ledger is invalid")
        previous_by_key[key] = (row[15], row[16], row[14], row[19])


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Return bounded revision-ledger coverage without exposing full price rows."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_daily_price_observations'"
    ).fetchone()
    if exists is None:
        return {
            "schema_version": 1,
            "status": "not_initialized",
            "observation_count": 0,
            "ticker_count": 0,
            "first_market_date": None,
            "last_market_date": None,
            "first_observed_at": None,
            "last_observed_at": None,
            "classification_counts": {
                name: 0 for name in sorted(CLASSIFICATIONS)
            },
            "raw_retained": False,
            "point_in_time_scope": "normalized_observations_after_capture_only",
            "execution_authority": "none",
        }
    _verify_ledger(con)
    row = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(market_date), "
        "MAX(market_date), MIN(observed_at), MAX(observed_at) "
        "FROM agent_daily_price_observations"
    ).fetchone()
    counts = {name: 0 for name in sorted(CLASSIFICATIONS)}
    for classification, count in con.execute(
        "SELECT classification, COUNT(*) FROM agent_daily_price_observations "
        "GROUP BY classification"
    ).fetchall():
        if classification not in CLASSIFICATIONS:
            raise ObservationError("stored price observation classification is invalid")
        counts[classification] = int(count)
    return {
        "schema_version": 1,
        "status": "capturing" if row[0] else "initialized_empty",
        "observation_count": int(row[0]),
        "ticker_count": int(row[1]),
        "first_market_date": None if row[2] is None else row[2].isoformat(),
        "last_market_date": None if row[3] is None else row[3].isoformat(),
        "first_observed_at": None if row[4] is None else _timestamp(row[4]),
        "last_observed_at": None if row[5] is None else _timestamp(row[5]),
        "classification_counts": counts,
        "raw_retained": False,
        "point_in_time_scope": "normalized_observations_after_capture_only",
        "execution_authority": "none",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "status"))
    parser.add_argument("--strategy", default="dual_momentum")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    con = engine_db.connect(args.db, read_only=args.command == "status")
    try:
        if args.command == "capture":
            market_date = engine_db.latest_operational_market_date(con)
            if market_date is None:
                raise ObservationError("no breadth-qualified market date")
            result = capture_strategy_scope(con, args.strategy, market_date)
        else:
            result = status(con)
    finally:
        con.close()
    import json

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
