"""Append-only normalized corporate-action observations for agent decisions."""

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
SOURCE_ADAPTER = "yfinance.actions"
SOURCE_ADAPTER_VERSION = "corporate_actions_v1"
OBSERVATION_SCHEMA_VERSION = 1
KINDS = frozenset({"dividend", "split"})
CLASSIFICATIONS = frozenset(
    {"baseline_snapshot", "unchanged_observation", "value_revision"}
)


class ObservationError(ValueError):
    """A corporate-action row cannot be retained as an immutable observation."""


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
    """Create the append-only ledger without changing `corporate_actions`."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_corporate_action_observations (
            id                          BIGINT PRIMARY KEY,
            schema_version              INTEGER NOT NULL,
            ticker                      VARCHAR NOT NULL,
            ex_date                     DATE NOT NULL,
            kind                        VARCHAR NOT NULL,
            value                       DOUBLE NOT NULL,
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
            UNIQUE (ticker, ex_date, kind, observation_sequence)
        )
        """
    )


def _normalized(row: tuple, *, observed_at: datetime) -> tuple[dict, dict, datetime]:
    ticker, ex_date, kind, value, source, fetched_at = row
    if (
        not isinstance(ticker, str)
        or not ticker
        or ticker != ticker.upper()
        or len(ticker) > 32
        or not ticker.isprintable()
        or type(ex_date) is not date
        or kind not in KINDS
        or source != SOURCE_NAME
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ObservationError("corporate-action observation is invalid")
    source_fetched_at = _utc(fetched_at, "source fetched_at")
    if source_fetched_at.date() < ex_date:
        raise ObservationError("corporate-action ingestion precedes ex-date")
    if _utc(observed_at, "observation time") < source_fetched_at:
        raise ObservationError("corporate-action observation precedes source ingestion")
    normalized = {
        "ticker": ticker,
        "ex_date": ex_date.isoformat(),
        "kind": kind,
        "value": float(value),
        "source": source,
        "latest_ingested_at": _timestamp(source_fetched_at),
    }
    value_record = {
        key: normalized[key]
        for key in ("ticker", "ex_date", "kind", "value", "source")
    }
    return normalized, value_record, source_fetched_at


def _next_id(con: duckdb.DuckDBPyConnection) -> int:
    return int(
        con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 "
            "FROM agent_corporate_action_observations"
        ).fetchone()[0]
    )


def _capture_rows(
    con: duckdb.DuckDBPyConnection,
    rows: list[tuple],
    *,
    observed_at: datetime,
) -> dict:
    """Append changed normalized observations. The caller owns the transaction."""
    observed_at = _utc(observed_at, "observation time")
    library_version = _library_version()
    prepared = []
    seen = set()
    for row in rows:
        normalized, value_record, source_fetched_at = _normalized(
            row, observed_at=observed_at
        )
        key = (row[0], row[1], row[2])
        if key in seen:
            raise ObservationError("capture contains a duplicate action key")
        seen.add(key)
        prepared.append((row, normalized, value_record, source_fetched_at))

    inserted = baseline = unchanged = revisions = 0
    next_id = _next_id(con)
    for row, normalized, value_record, source_fetched_at in prepared:
        ticker, ex_date, kind = row[:3]
        latest = con.execute(
            "SELECT source_fetched_at, normalized_sha256, value_sha256, "
            "observation_sequence, value_revision, observation_sha256 "
            "FROM agent_corporate_action_observations "
            "WHERE ticker = ? AND ex_date = ? AND kind = ? "
            "ORDER BY observation_sequence DESC LIMIT 1",
            [ticker, ex_date, kind],
        ).fetchone()
        normalized_sha256 = canonical_sha256(normalized)
        value_sha256 = canonical_sha256(value_record)
        if (
            latest is not None
            and _utc(latest[0], "stored source fetched_at") == source_fetched_at
            and latest[1] == normalized_sha256
        ):
            continue
        if latest is None:
            sequence, revision = 1, 1
            classification, previous = "baseline_snapshot", None
            baseline += 1
        else:
            if source_fetched_at < _utc(latest[0], "stored source fetched_at"):
                raise ObservationError("corporate-action ingestion moved backward")
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
            "ex_date": ex_date.isoformat(),
            "kind": kind,
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
            "INSERT INTO agent_corporate_action_observations ("
            "id, schema_version, ticker, ex_date, kind, value, source, "
            "source_fetched_at, observed_at, source_adapter, "
            "source_adapter_version, source_library_version, normalized_sha256, "
            "value_sha256, observation_sequence, value_revision, classification, "
            "previous_observation_sha256, observation_sha256"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                next_id,
                OBSERVATION_SCHEMA_VERSION,
                ticker,
                ex_date,
                kind,
                normalized["value"],
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
        params = config_by_id(strategy_id)["params"]
    except (KeyError, TypeError) as exc:
        raise ObservationError("strategy is unavailable") from exc
    tickers = set()
    for field in ("assets", "sectors"):
        values = params.get(field, [])
        if isinstance(values, list):
            tickers.update(value for value in values if isinstance(value, str))
    for field in ("cash_proxy", "ticker"):
        value = params.get(field)
        if isinstance(value, str):
            tickers.add(value)
    raw = params.get("lookbacks")
    raw = [params.get("lookback")] if raw is None else raw
    lookbacks = [
        value for value in raw if isinstance(value, int) and not isinstance(value, bool)
    ]
    if not tickers or not lookbacks or len(lookbacks) != len(raw):
        raise ObservationError("strategy corporate-action scope is invalid")
    return sorted(tickers), max(lookbacks) + 1


def capture_strategy_scope(
    con: duckdb.DuckDBPyConnection,
    strategy_id: str,
    market_date: date,
    *,
    observed_at: datetime | None = None,
) -> dict:
    """Capture actions that can enter one registered strategy context."""
    if type(market_date) is not date:
        raise ObservationError("market date is invalid")
    tickers, required = _strategy_scope(strategy_id)
    source_exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'corporate_actions'"
    ).fetchone()
    starts = []
    rows = []
    for ticker in tickers:
        row = con.execute(
            "SELECT MIN(date) FROM (SELECT date FROM prices "
            "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?)",
            [ticker, market_date, required],
        ).fetchone()
        if row is None or row[0] is None:
            continue
        starts.append(row[0])
        if source_exists is not None:
            rows.extend(
                con.execute(
                    "SELECT ticker, ex_date, kind, value, source, fetched_at "
                    "FROM corporate_actions WHERE ticker = ? "
                    "AND ex_date >= ? AND ex_date <= ? ORDER BY ex_date, kind",
                    [ticker, row[0], market_date],
                ).fetchall()
            )
    start = min(starts) if starts else market_date
    captured_at = observed_at or datetime.now(timezone.utc)
    init_schema(con)
    with engine_db.transaction(con):
        result = _capture_rows(con, rows, observed_at=captured_at)
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "market_date": market_date.isoformat(),
        "scope_start_date": start.isoformat(),
        "required_tickers": tickers,
        "observed_at": _timestamp(captured_at),
        **result,
    }


def observation_for_action_row(
    con: duckdb.DuckDBPyConnection, row: tuple
) -> dict | None:
    """Return and verify the latest immutable observation matching one cache row."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_corporate_action_observations'"
    ).fetchone()
    if exists is None:
        return None
    ticker, ex_date, kind, value, source, fetched_at = row
    match = con.execute(
        "SELECT schema_version, observed_at, source_adapter, "
        "source_adapter_version, source_library_version, normalized_sha256, "
        "value_sha256, observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256 "
        "FROM agent_corporate_action_observations "
        "WHERE ticker = ? AND ex_date = ? AND kind = ? AND value = ? "
        "AND source = ? AND source_fetched_at = ? "
        "ORDER BY observation_sequence DESC LIMIT 1",
        [ticker, ex_date, kind, value, source, fetched_at],
    ).fetchone()
    if match is None:
        return None
    observed_at = _utc(match[1], "stored observation time")
    normalized, value_record, source_fetched_at = _normalized(
        row, observed_at=observed_at
    )
    identity = {
        "schema_version": match[0],
        "ticker": ticker,
        "ex_date": ex_date.isoformat(),
        "kind": kind,
        "normalized_sha256": match[5],
        "value_sha256": match[6],
        "source_fetched_at": _timestamp(source_fetched_at),
        "observed_at": _timestamp(observed_at),
        "source_adapter": match[2],
        "source_adapter_version": match[3],
        "source_library_version": match[4],
        "observation_sequence": match[7],
        "value_revision": match[8],
        "classification": match[9],
        "previous_observation_sha256": match[10],
    }
    if (
        match[0] != OBSERVATION_SCHEMA_VERSION
        or match[2] != SOURCE_ADAPTER
        or match[3] != SOURCE_ADAPTER_VERSION
        or match[9] not in CLASSIFICATIONS
        or canonical_sha256(normalized) != match[5]
        or canonical_sha256(value_record) != match[6]
        or canonical_sha256(identity) != match[11]
    ):
        raise ObservationError("stored corporate-action observation identity is invalid")
    return {
        **identity,
        "source_library_version": match[4],
        "observation_sha256": match[11],
        "normalized": normalized,
    }


def _verify_ledger(con: duckdb.DuckDBPyConnection) -> None:
    previous_by_key: dict[tuple[str, date, str], tuple[int, int, str, str]] = {}
    rows = con.execute(
        "SELECT ticker, ex_date, kind, value, source, source_fetched_at, "
        "observed_at, source_adapter, source_adapter_version, "
        "source_library_version, normalized_sha256, value_sha256, "
        "observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256, schema_version "
        "FROM agent_corporate_action_observations "
        "ORDER BY ticker, ex_date, kind, observation_sequence"
    ).fetchall()
    for row in rows:
        action_row = (*row[:5], row[5])
        observed_at = _utc(row[6], "stored observation time")
        normalized, value_record, source_fetched_at = _normalized(
            action_row, observed_at=observed_at
        )
        key = (row[0], row[1], row[2])
        previous = previous_by_key.get(key)
        expected_sequence = 1 if previous is None else previous[0] + 1
        expected_previous = None if previous is None else previous[3]
        expected_revision = 1 if previous is None else previous[1]
        expected_classification = "baseline_snapshot"
        if previous is not None:
            if row[11] == previous[2]:
                expected_classification = "unchanged_observation"
            else:
                expected_revision += 1
                expected_classification = "value_revision"
        identity = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "ticker": row[0],
            "ex_date": row[1].isoformat(),
            "kind": row[2],
            "normalized_sha256": row[10],
            "value_sha256": row[11],
            "source_fetched_at": _timestamp(source_fetched_at),
            "observed_at": _timestamp(observed_at),
            "source_adapter": row[7],
            "source_adapter_version": row[8],
            "source_library_version": row[9],
            "observation_sequence": row[12],
            "value_revision": row[13],
            "classification": row[14],
            "previous_observation_sha256": row[15],
        }
        if (
            row[17] != OBSERVATION_SCHEMA_VERSION
            or row[7] != SOURCE_ADAPTER
            or row[8] != SOURCE_ADAPTER_VERSION
            or row[12] != expected_sequence
            or row[13] != expected_revision
            or row[14] != expected_classification
            or row[15] != expected_previous
            or canonical_sha256(normalized) != row[10]
            or canonical_sha256(value_record) != row[11]
            or canonical_sha256(identity) != row[16]
        ):
            raise ObservationError("stored corporate-action observation ledger is invalid")
        previous_by_key[key] = (row[12], row[13], row[11], row[16])


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Return bounded ledger coverage without exposing action rows."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_corporate_action_observations'"
    ).fetchone()
    empty = {
        "schema_version": 1,
        "status": "not_initialized",
        "observation_count": 0,
        "ticker_count": 0,
        "first_ex_date": None,
        "last_ex_date": None,
        "first_observed_at": None,
        "last_observed_at": None,
        "kind_counts": {name: 0 for name in sorted(KINDS)},
        "classification_counts": {
            name: 0 for name in sorted(CLASSIFICATIONS)
        },
        "raw_retained": False,
        "point_in_time_scope": "normalized_observations_after_capture_only",
        "execution_authority": "none",
    }
    if exists is None:
        return empty
    _verify_ledger(con)
    row = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(ex_date), MAX(ex_date), "
        "MIN(observed_at), MAX(observed_at) "
        "FROM agent_corporate_action_observations"
    ).fetchone()
    kinds = {name: 0 for name in sorted(KINDS)}
    classifications = {name: 0 for name in sorted(CLASSIFICATIONS)}
    for kind, count in con.execute(
        "SELECT kind, COUNT(*) FROM agent_corporate_action_observations GROUP BY kind"
    ).fetchall():
        if kind not in KINDS:
            raise ObservationError("stored corporate-action kind is invalid")
        kinds[kind] = int(count)
    for classification, count in con.execute(
        "SELECT classification, COUNT(*) "
        "FROM agent_corporate_action_observations GROUP BY classification"
    ).fetchall():
        if classification not in CLASSIFICATIONS:
            raise ObservationError("stored corporate-action classification is invalid")
        classifications[classification] = int(count)
    return {
        **empty,
        "status": "capturing" if row[0] else "initialized_empty",
        "observation_count": int(row[0]),
        "ticker_count": int(row[1]),
        "first_ex_date": None if row[2] is None else row[2].isoformat(),
        "last_ex_date": None if row[3] is None else row[3].isoformat(),
        "first_observed_at": None if row[4] is None else _timestamp(row[4]),
        "last_observed_at": None if row[5] is None else _timestamp(row[5]),
        "kind_counts": kinds,
        "classification_counts": classifications,
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
