"""Append-only exact Nasdaq responses and independently derived price facts.

This is evidence for data review, not a second operational price feed. Capture
never updates ``prices``, quarantine state, proposals, orders, or authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import duckdb

from engine import verify_prices
from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB
from sim.strategies.configs import config_by_id

SOURCE_NAME = "nasdaq"
ENDPOINT = verify_prices.API_URL
ENDPOINT_API_VERSION = "nasdaq_quote_historical_v1"
SOURCE_ADAPTER = "engine.verify_prices.parse_nasdaq_history"
SOURCE_ADAPTER_VERSION = "exact_response_v1"
RECEIPT_SCHEMA_VERSION = 1
OBSERVATION_SCHEMA_VERSION = 1
DEFAULT_SESSIONS = 5
MAX_RESPONSE_BYTES = 2_000_000
MAX_CONTENT_TYPE_CHARS = 128
CLASSIFICATIONS = frozenset(
    {"baseline_source_observation", "unchanged_source_observation", "source_value_revision"}
)
RECEIPT_TABLE = "agent_independent_price_responses"
OBSERVATION_TABLE = "agent_independent_price_observations"
_RECEIPT_COLUMNS = (
    ("id", "BIGINT"),
    ("schema_version", "INTEGER"),
    ("source", "VARCHAR"),
    ("endpoint", "VARCHAR"),
    ("endpoint_api_version", "VARCHAR"),
    ("ticker", "VARCHAR"),
    ("asset_class", "VARCHAR"),
    ("period_start", "DATE"),
    ("period_end_inclusive", "DATE"),
    ("request_sha256", "VARCHAR"),
    ("requested_at", "TIMESTAMP"),
    ("received_at", "TIMESTAMP"),
    ("http_status", "INTEGER"),
    ("content_type", "VARCHAR"),
    ("source_library_version", "VARCHAR"),
    ("response_size_bytes", "BIGINT"),
    ("response_sha256", "VARCHAR"),
    ("response_body", "BLOB"),
    ("source_row_count", "INTEGER"),
    ("parse_error_count", "INTEGER"),
    ("incomplete_row_count", "INTEGER"),
    ("receipt_sha256", "VARCHAR"),
)
_OBSERVATION_COLUMNS = (
    ("id", "BIGINT"),
    ("schema_version", "INTEGER"),
    ("ticker", "VARCHAR"),
    ("market_date", "DATE"),
    ("normalized_payload", "VARCHAR"),
    ("normalized_sha256", "VARCHAR"),
    ("value_sha256", "VARCHAR"),
    ("source_fetched_at", "TIMESTAMP"),
    ("observed_at", "TIMESTAMP"),
    ("source_adapter", "VARCHAR"),
    ("source_adapter_version", "VARCHAR"),
    ("source_library_version", "VARCHAR"),
    ("observation_sequence", "INTEGER"),
    ("value_revision", "INTEGER"),
    ("classification", "VARCHAR"),
    ("previous_observation_sha256", "VARCHAR"),
    ("receipt_sha256", "VARCHAR"),
    ("response_sha256", "VARCHAR"),
    ("observation_sha256", "VARCHAR"),
)

Fetch = Callable[
    [str, str, date, date],
    verify_prices.NasdaqResponse,
]


class IndependentPriceEvidenceError(RuntimeError):
    """Independent price evidence cannot be safely captured or verified."""


def _utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime:
        raise IndependentPriceEvidenceError(f"{label} is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc)


def _timestamp(value: datetime, label: str = "timestamp") -> str:
    return _utc(value, label).isoformat().replace("+00:00", "Z")


def _requests_version() -> str:
    try:
        result = version("requests")
    except PackageNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise IndependentPriceEvidenceError("requests version is unavailable") from exc
    if not result or len(result) > 64 or not result.isprintable():
        raise IndependentPriceEvidenceError("requests version is invalid")
    return result


def _response_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _request_identity(
    ticker: str,
    asset_class: str,
    period_start: date,
    period_end: date,
) -> dict:
    return {
        "endpoint": ENDPOINT,
        "ticker": ticker,
        "asset_class": asset_class,
        "period_start": period_start.isoformat(),
        "period_end_inclusive": period_end.isoformat(),
    }


def _fetch(
    ticker: str,
    asset_class: str,
    period_start: date,
    period_end: date,
) -> verify_prices.NasdaqResponse:
    return verify_prices.fetch_nasdaq_response(
        ticker,
        assetclass=asset_class,
        start=period_start,
        end=period_end,
    )


def _number(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise IndependentPriceEvidenceError(f"{label} is invalid")
    return float(value)


def _volume(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or not float(value).is_integer()
    ):
        raise IndependentPriceEvidenceError("independent price volume is invalid")
    return int(value)


def _facts(ticker: str, response: verify_prices.NasdaqResponse) -> tuple[list[dict], dict]:
    try:
        parsed = verify_prices.parse_nasdaq_history(ticker, response)
    except verify_prices.SourceError as exc:
        raise IndependentPriceEvidenceError(
            f"independent response body is invalid: {exc}"
        ) from exc
    returned = str(parsed["symbol"]).replace("/", ".").replace("-", ".").upper()
    requested = ticker.replace("-", ".").upper()
    if returned != requested:
        raise IndependentPriceEvidenceError("independent source returned another symbol")
    facts = []
    incomplete = 0
    for market_date, bar in sorted(parsed["bars"].items()):
        if any(bar.get(field) is None for field in ("open", "high", "low", "close", "volume")):
            incomplete += 1
            continue
        open_price = _number(bar["open"], "independent price open")
        high = _number(bar["high"], "independent price high")
        low = _number(bar["low"], "independent price low")
        close = _number(bar["close"], "independent price close")
        volume = _volume(bar["volume"])
        if low > min(open_price, high, close) or high < max(open_price, low, close):
            raise IndependentPriceEvidenceError("independent price OHLC is invalid")
        value = {
            "ticker": ticker,
            "market_date": market_date.isoformat(),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "source": SOURCE_NAME,
        }
        facts.append(
            {
                "ticker": ticker,
                "market_date": market_date,
                "value": value,
                "value_sha256": canonical_sha256(value),
            }
        )
    diagnostics = {
        "source_row_count": int(parsed["rows"]),
        "parse_error_count": len(parsed["parse_errors"]),
        "incomplete_row_count": incomplete,
    }
    return facts, diagnostics


def _receipt(
    *,
    ticker: str,
    asset_class: str,
    period_start: date,
    period_end: date,
    requested_at: datetime,
    response: verify_prices.NasdaqResponse,
) -> tuple[dict, list[dict]]:
    if (
        not isinstance(ticker, str)
        or not ticker
        or ticker != ticker.upper()
        or len(ticker) > 32
        or not ticker.isprintable()
        or asset_class not in {"etf", "stocks"}
        or type(period_start) is not date
        or type(period_end) is not date
        or period_start > period_end
        or not isinstance(response, verify_prices.NasdaqResponse)
    ):
        raise IndependentPriceEvidenceError(
            "independent response identity is invalid"
        )
    requested_at = _utc(requested_at, "independent request time")
    received_at = _utc(response.received_at, "independent response time")
    body = bytes(response.body)
    if received_at < requested_at:
        raise IndependentPriceEvidenceError("independent response precedes request")
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise IndependentPriceEvidenceError("independent response size is invalid")
    if response.status_code != 200:
        raise IndependentPriceEvidenceError(
            f"independent source returned HTTP {response.status_code}"
        )
    content_type = response.content_type.strip()
    if (
        not content_type.lower().startswith("application/json")
        or len(content_type) > MAX_CONTENT_TYPE_CHARS
        or not content_type.isprintable()
    ):
        raise IndependentPriceEvidenceError("independent response content type is invalid")
    facts, diagnostics = _facts(ticker, response)
    if any(
        fact["market_date"] < period_start or fact["market_date"] > period_end
        for fact in facts
    ):
        raise IndependentPriceEvidenceError(
            "independent response facts exceed request scope"
        )
    request_sha256 = canonical_sha256(
        _request_identity(ticker, asset_class, period_start, period_end)
    )
    identity = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "endpoint": ENDPOINT,
        "endpoint_api_version": ENDPOINT_API_VERSION,
        "ticker": ticker,
        "asset_class": asset_class,
        "period_start": period_start.isoformat(),
        "period_end_inclusive": period_end.isoformat(),
        "request_sha256": request_sha256,
        "requested_at": _timestamp(requested_at),
        "received_at": _timestamp(received_at),
        "http_status": response.status_code,
        "content_type": content_type,
        "source_library_version": _requests_version(),
        "response_size_bytes": len(body),
        "response_sha256": _response_sha256(body),
        **diagnostics,
    }
    admitted_facts = (
        facts
        if diagnostics["parse_error_count"] == 0
        and diagnostics["incomplete_row_count"] == 0
        else []
    )
    return (
        {**identity, "receipt_sha256": canonical_sha256(identity)},
        admitted_facts,
    )


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create only the two append-only independent-evidence ledgers."""
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RECEIPT_TABLE} (
            id                       BIGINT PRIMARY KEY,
            schema_version           INTEGER NOT NULL,
            source                   VARCHAR NOT NULL,
            endpoint                 VARCHAR NOT NULL,
            endpoint_api_version     VARCHAR NOT NULL,
            ticker                   VARCHAR NOT NULL,
            asset_class              VARCHAR NOT NULL,
            period_start             DATE NOT NULL,
            period_end_inclusive     DATE NOT NULL,
            request_sha256           VARCHAR NOT NULL,
            requested_at             TIMESTAMP NOT NULL,
            received_at              TIMESTAMP NOT NULL,
            http_status              INTEGER NOT NULL,
            content_type             VARCHAR NOT NULL,
            source_library_version   VARCHAR NOT NULL,
            response_size_bytes      BIGINT NOT NULL,
            response_sha256          VARCHAR NOT NULL,
            response_body            BLOB NOT NULL,
            source_row_count         INTEGER NOT NULL,
            parse_error_count        INTEGER NOT NULL,
            incomplete_row_count     INTEGER NOT NULL,
            receipt_sha256           VARCHAR NOT NULL UNIQUE
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OBSERVATION_TABLE} (
            id                          BIGINT PRIMARY KEY,
            schema_version              INTEGER NOT NULL,
            ticker                      VARCHAR NOT NULL,
            market_date                 DATE NOT NULL,
            normalized_payload          VARCHAR NOT NULL,
            normalized_sha256           VARCHAR NOT NULL,
            value_sha256                VARCHAR NOT NULL,
            source_fetched_at            TIMESTAMP NOT NULL,
            observed_at                 TIMESTAMP NOT NULL,
            source_adapter              VARCHAR NOT NULL,
            source_adapter_version      VARCHAR NOT NULL,
            source_library_version      VARCHAR NOT NULL,
            observation_sequence        INTEGER NOT NULL,
            value_revision              INTEGER NOT NULL,
            classification              VARCHAR NOT NULL,
            previous_observation_sha256 VARCHAR,
            receipt_sha256              VARCHAR NOT NULL,
            response_sha256             VARCHAR NOT NULL,
            observation_sha256          VARCHAR NOT NULL UNIQUE,
            UNIQUE (ticker, market_date, observation_sequence),
            UNIQUE (receipt_sha256, ticker, market_date)
        )
        """
    )
    _verify_schema(con)


def _verify_schema(con: duckdb.DuckDBPyConnection) -> None:
    for table, expected in (
        (RECEIPT_TABLE, _RECEIPT_COLUMNS),
        (OBSERVATION_TABLE, _OBSERVATION_COLUMNS),
    ):
        actual = tuple(
            (row[0], row[1])
            for row in con.execute(f"DESCRIBE {table}").fetchall()
        )
        if actual != expected:
            raise IndependentPriceEvidenceError(
                "independent evidence schema is invalid"
            )


def _persist(
    con: duckdb.DuckDBPyConnection,
    receipt: dict,
    body: bytes,
    facts: list[dict],
) -> dict:
    """Atomically append one receipt and its complete derived fact set."""
    init_schema(con)
    with engine_db.transaction(con):
        exists = con.execute(
            f"SELECT * FROM {RECEIPT_TABLE} WHERE receipt_sha256 = ?",
            [receipt["receipt_sha256"]],
        ).fetchone()
        if exists is not None:
            stored, stored_body = _stored_receipt(exists)
            response = verify_prices.NasdaqResponse(
                stored_body,
                stored["content_type"],
                stored["http_status"],
                datetime.fromisoformat(
                    stored["received_at"].replace("Z", "+00:00")
                ),
            )
            extracted, diagnostics = _facts(stored["ticker"], response)
            expected_facts = (
                extracted
                if diagnostics["parse_error_count"] == 0
                and diagnostics["incomplete_row_count"] == 0
                else []
            )
            retained = {
                (row[0], row[1], row[2])
                for row in con.execute(
                    f"SELECT ticker, market_date, value_sha256 "
                    f"FROM {OBSERVATION_TABLE} WHERE receipt_sha256 = ?",
                    [receipt["receipt_sha256"]],
                ).fetchall()
            }
            expected = {
                (fact["ticker"], fact["market_date"], fact["value_sha256"])
                for fact in expected_facts
            }
            if (
                stored["receipt_sha256"] != receipt["receipt_sha256"]
                or stored_body != body
                or retained != expected
            ):
                raise IndependentPriceEvidenceError(
                    "independent response replay conflicts with retained evidence"
                )
            return {
                "inserted_responses": 0,
                "inserted_observations": 0,
                "exact_replay": True,
            }
        receipt_id = int(
            con.execute(
                f"SELECT COALESCE(MAX(id), 0) + 1 FROM {RECEIPT_TABLE}"
            ).fetchone()[0]
        )
        con.execute(
            f"INSERT INTO {RECEIPT_TABLE} VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                receipt_id,
                receipt["schema_version"],
                receipt["source"],
                receipt["endpoint"],
                receipt["endpoint_api_version"],
                receipt["ticker"],
                receipt["asset_class"],
                date.fromisoformat(receipt["period_start"]),
                date.fromisoformat(receipt["period_end_inclusive"]),
                receipt["request_sha256"],
                datetime.fromisoformat(receipt["requested_at"].replace("Z", "+00:00")),
                datetime.fromisoformat(receipt["received_at"].replace("Z", "+00:00")),
                receipt["http_status"],
                receipt["content_type"],
                receipt["source_library_version"],
                receipt["response_size_bytes"],
                receipt["response_sha256"],
                body,
                receipt["source_row_count"],
                receipt["parse_error_count"],
                receipt["incomplete_row_count"],
                receipt["receipt_sha256"],
            ],
        )
        next_id = int(
            con.execute(
                f"SELECT COALESCE(MAX(id), 0) + 1 FROM {OBSERVATION_TABLE}"
            ).fetchone()[0]
        )
        for fact in facts:
            latest = con.execute(
                f"SELECT observation_sequence, value_revision, value_sha256, "
                f"observation_sha256 FROM {OBSERVATION_TABLE} "
                "WHERE ticker = ? AND market_date = ? "
                "ORDER BY observation_sequence DESC LIMIT 1",
                [fact["ticker"], fact["market_date"]],
            ).fetchone()
            if latest is None:
                sequence = revision = 1
                classification = "baseline_source_observation"
                previous = None
            else:
                sequence = int(latest[0]) + 1
                previous = latest[3]
                if latest[2] == fact["value_sha256"]:
                    revision = int(latest[1])
                    classification = "unchanged_source_observation"
                else:
                    revision = int(latest[1]) + 1
                    classification = "source_value_revision"
            normalized = {
                **fact["value"],
                "latest_received_at": receipt["received_at"],
            }
            normalized_sha256 = canonical_sha256(normalized)
            identity = {
                "schema_version": OBSERVATION_SCHEMA_VERSION,
                "ticker": fact["ticker"],
                "market_date": fact["market_date"].isoformat(),
                "normalized_sha256": normalized_sha256,
                "value_sha256": fact["value_sha256"],
                "source_fetched_at": receipt["received_at"],
                "observed_at": receipt["received_at"],
                "source_adapter": SOURCE_ADAPTER,
                "source_adapter_version": SOURCE_ADAPTER_VERSION,
                "source_library_version": receipt["source_library_version"],
                "observation_sequence": sequence,
                "value_revision": revision,
                "classification": classification,
                "previous_observation_sha256": previous,
                "receipt_sha256": receipt["receipt_sha256"],
                "response_sha256": receipt["response_sha256"],
            }
            observation_sha256 = canonical_sha256(identity)
            con.execute(
                f"INSERT INTO {OBSERVATION_TABLE} VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    next_id,
                    OBSERVATION_SCHEMA_VERSION,
                    fact["ticker"],
                    fact["market_date"],
                    json.dumps(
                        normalized,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                    normalized_sha256,
                    fact["value_sha256"],
                    datetime.fromisoformat(
                        receipt["received_at"].replace("Z", "+00:00")
                    ),
                    datetime.fromisoformat(
                        receipt["received_at"].replace("Z", "+00:00")
                    ),
                    SOURCE_ADAPTER,
                    SOURCE_ADAPTER_VERSION,
                    receipt["source_library_version"],
                    sequence,
                    revision,
                    classification,
                    previous,
                    receipt["receipt_sha256"],
                    receipt["response_sha256"],
                    observation_sha256,
                ],
            )
            next_id += 1
    return {
        "inserted_responses": 1,
        "inserted_observations": len(facts),
        "exact_replay": False,
    }


def _strategy_scope(
    con: duckdb.DuckDBPyConnection,
    strategy_id: str,
    market_date: date,
    sessions: int,
) -> list[tuple[str, str, date, date]]:
    if type(market_date) is not date or isinstance(sessions, bool) or sessions < 1 or sessions > 60:
        raise IndependentPriceEvidenceError("independent capture scope is invalid")
    try:
        params = config_by_id(strategy_id)["params"]
    except (KeyError, TypeError) as exc:
        raise IndependentPriceEvidenceError("strategy is unavailable") from exc
    tickers = set()
    for field in ("assets", "sectors"):
        values = params.get(field, [])
        if isinstance(values, list):
            tickers.update(value for value in values if isinstance(value, str))
    for field in ("cash_proxy", "ticker"):
        value = params.get(field)
        if isinstance(value, str):
            tickers.add(value)
    if not tickers:
        raise IndependentPriceEvidenceError("strategy ticker scope is empty")
    start = market_date - timedelta(days=sessions * 2 + 12)
    result = []
    for ticker in sorted(tickers):
        rows = con.execute(
            "SELECT etf FROM universe WHERE ticker = ?", [ticker]
        ).fetchall()
        if len(rows) != 1 or type(rows[0][0]) is not bool:
            raise IndependentPriceEvidenceError(
                f"independent asset class is unavailable for {ticker}"
            )
        result.append((ticker, "etf" if rows[0][0] else "stocks", start, market_date))
    return result


def capture(
    database: Path,
    strategy_id: str,
    market_date: date,
    *,
    sessions: int = DEFAULT_SESSIONS,
    fetch: Fetch = _fetch,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """Fetch outside DuckDB locks, then append each exact validated response."""
    con = engine_db.connect(database, read_only=True)
    try:
        scope = _strategy_scope(con, strategy_id, market_date, sessions)
    finally:
        con.close()
    totals = {"inserted_responses": 0, "inserted_observations": 0}
    for ticker, asset_class, start, end in scope:
        requested_at = (now or (lambda: datetime.now(timezone.utc)))()
        response = fetch(ticker, asset_class, start, end)
        receipt, facts = _receipt(
            ticker=ticker,
            asset_class=asset_class,
            period_start=start,
            period_end=end,
            requested_at=requested_at,
            response=response,
        )
        con = engine_db.connect(database)
        try:
            result = _persist(con, receipt, response.body, facts)
        finally:
            con.close()
        totals["inserted_responses"] += result["inserted_responses"]
        totals["inserted_observations"] += result["inserted_observations"]
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "market_date": market_date.isoformat(),
        "sessions": sessions,
        "required_tickers": [item[0] for item in scope],
        "selected_responses": len(scope),
        **totals,
        "operational_price_mutation": False,
        "quarantine_mutation": False,
        "execution_authority": "none",
    }


def _stored_receipt(row: tuple) -> tuple[dict, bytes]:
    body = bytes(row[17])
    identity = {
        "schema_version": row[1],
        "source": row[2],
        "endpoint": row[3],
        "endpoint_api_version": row[4],
        "ticker": row[5],
        "asset_class": row[6],
        "period_start": row[7].isoformat(),
        "period_end_inclusive": row[8].isoformat(),
        "request_sha256": row[9],
        "requested_at": _timestamp(row[10], "stored request time"),
        "received_at": _timestamp(row[11], "stored response time"),
        "http_status": row[12],
        "content_type": row[13],
        "source_library_version": row[14],
        "response_size_bytes": row[15],
        "response_sha256": row[16],
        "source_row_count": row[18],
        "parse_error_count": row[19],
        "incomplete_row_count": row[20],
    }
    response = verify_prices.NasdaqResponse(body, row[13], row[12], _utc(row[11], "stored response time"))
    facts, diagnostics = _facts(row[5], response)
    if (
        row[1] != RECEIPT_SCHEMA_VERSION
        or row[2] != SOURCE_NAME
        or row[3] != ENDPOINT
        or row[4] != ENDPOINT_API_VERSION
        or not isinstance(row[5], str)
        or not row[5]
        or row[5] != row[5].upper()
        or len(row[5]) > 32
        or not row[5].isprintable()
        or row[6] not in {"etf", "stocks"}
        or row[7] > row[8]
        or any(
            fact["market_date"] < row[7] or fact["market_date"] > row[8]
            for fact in facts
        )
        or row[9] != canonical_sha256(_request_identity(row[5], row[6], row[7], row[8]))
        or _utc(row[11], "stored response time") < _utc(row[10], "stored request time")
        or row[12] != 200
        or not row[13].lower().startswith("application/json")
        or len(row[13]) > MAX_CONTENT_TYPE_CHARS
        or not row[13].isprintable()
        or not isinstance(row[14], str)
        or not row[14]
        or len(row[14]) > 64
        or not row[14].isprintable()
        or not body
        or len(body) > MAX_RESPONSE_BYTES
        or row[15] != len(body)
        or row[16] != _response_sha256(body)
        or diagnostics
        != {
            "source_row_count": row[18],
            "parse_error_count": row[19],
            "incomplete_row_count": row[20],
        }
        or row[21] != canonical_sha256(identity)
    ):
        raise IndependentPriceEvidenceError("stored independent response is invalid")
    return {**identity, "receipt_sha256": row[21]}, body


def _stored_observation(
    con: duckdb.DuckDBPyConnection,
    row: tuple,
    *,
    receipt_cache: dict[str, tuple[tuple, set[tuple]]] | None = None,
) -> dict:
    try:
        normalized = json.loads(row[4])
    except (TypeError, ValueError) as exc:
        raise IndependentPriceEvidenceError("stored independent observation is invalid") from exc
    value_fields = {"ticker", "market_date", "open", "high", "low", "close", "volume", "source"}
    if not isinstance(normalized, dict) or set(normalized) != {*value_fields, "latest_received_at"}:
        raise IndependentPriceEvidenceError("stored independent observation is invalid")
    value = {field: normalized[field] for field in value_fields}
    cached = None if receipt_cache is None else receipt_cache.get(row[16])
    if cached is None:
        receipt_row = con.execute(
            f"SELECT * FROM {RECEIPT_TABLE} WHERE receipt_sha256 = ?", [row[16]]
        ).fetchone()
        if receipt_row is None:
            raise IndependentPriceEvidenceError("stored independent observation is invalid")
        receipt, body = _stored_receipt(receipt_row)
        response = verify_prices.NasdaqResponse(
            body,
            receipt["content_type"],
            receipt["http_status"],
            datetime.fromisoformat(receipt["received_at"].replace("Z", "+00:00")),
        )
        extracted = {
            (fact["ticker"], fact["market_date"], fact["value_sha256"])
            for fact in _facts(receipt["ticker"], response)[0]
        }
        if receipt_cache is not None:
            receipt_cache[row[16]] = (receipt_row, extracted)
    else:
        receipt_row, extracted = cached
        receipt, _body = _stored_receipt(receipt_row)
    identity = {
        "schema_version": row[1],
        "ticker": row[2],
        "market_date": row[3].isoformat(),
        "normalized_sha256": row[5],
        "value_sha256": row[6],
        "source_fetched_at": _timestamp(row[7]),
        "observed_at": _timestamp(row[8]),
        "source_adapter": row[9],
        "source_adapter_version": row[10],
        "source_library_version": row[11],
        "observation_sequence": row[12],
        "value_revision": row[13],
        "classification": row[14],
        "previous_observation_sha256": row[15],
        "receipt_sha256": row[16],
        "response_sha256": row[17],
    }
    if (
        row[1] != OBSERVATION_SCHEMA_VERSION
        or normalized["ticker"] != row[2]
        or normalized["market_date"] != row[3].isoformat()
        or normalized["source"] != SOURCE_NAME
        or normalized["latest_received_at"] != _timestamp(row[7])
        or row[7] != row[8]
        or row[9] != SOURCE_ADAPTER
        or row[10] != SOURCE_ADAPTER_VERSION
        or row[11] != receipt["source_library_version"]
        or row[14] not in CLASSIFICATIONS
        or row[16] != receipt_row[21]
        or row[17] != receipt_row[16]
        or canonical_sha256(normalized) != row[5]
        or canonical_sha256(value) != row[6]
        or (row[2], row[3], row[6]) not in extracted
        or canonical_sha256(identity) != row[18]
    ):
        raise IndependentPriceEvidenceError("stored independent observation is invalid")
    return {**identity, "observation_sha256": row[18], "value": value}


def _verify(con: duckdb.DuckDBPyConnection) -> dict:
    _verify_schema(con)
    receipt_rows = con.execute(f"SELECT * FROM {RECEIPT_TABLE} ORDER BY id").fetchall()
    expected_by_receipt = {}
    for row in receipt_rows:
        receipt, body = _stored_receipt(row)
        response = verify_prices.NasdaqResponse(
            body,
            receipt["content_type"],
            receipt["http_status"],
            datetime.fromisoformat(
                receipt["received_at"].replace("Z", "+00:00")
            ),
        )
        facts, diagnostics = _facts(receipt["ticker"], response)
        expected_by_receipt[receipt["receipt_sha256"]] = (
            {
                (fact["ticker"], fact["market_date"], fact["value_sha256"])
                for fact in facts
            }
            if diagnostics["parse_error_count"] == 0
            and diagnostics["incomplete_row_count"] == 0
            else set()
        )
    rows = con.execute(
        f"SELECT * FROM {OBSERVATION_TABLE} "
        "ORDER BY ticker, market_date, observation_sequence"
    ).fetchall()
    previous_by_key: dict[tuple, tuple] = {}
    actual_by_receipt = {
        receipt_sha256: set() for receipt_sha256 in expected_by_receipt
    }
    receipt_cache = {}
    classifications = {name: 0 for name in sorted(CLASSIFICATIONS)}
    for row in rows:
        _stored_observation(con, row, receipt_cache=receipt_cache)
        key = (row[2], row[3])
        previous = previous_by_key.get(key)
        if previous is None:
            expected = (1, 1, "baseline_source_observation", None)
        elif row[6] == previous[2]:
            expected = (
                previous[0] + 1,
                previous[1],
                "unchanged_source_observation",
                previous[3],
            )
        else:
            expected = (
                previous[0] + 1,
                previous[1] + 1,
                "source_value_revision",
                previous[3],
            )
        if (row[12], row[13], row[14], row[15]) != expected:
            raise IndependentPriceEvidenceError(
                "stored independent observation chain is invalid"
            )
        classifications[row[14]] += 1
        actual_by_receipt[row[16]].add((row[2], row[3], row[6]))
        previous_by_key[key] = (row[12], row[13], row[6], row[18])
    if actual_by_receipt != expected_by_receipt:
        raise IndependentPriceEvidenceError(
            "stored independent response fact set is incomplete"
        )
    return {
        "response_count": len(receipt_rows),
        "observation_count": len(rows),
        "classification_counts": classifications,
    }


def evidence_for_fact(
    con: duckdb.DuckDBPyConnection,
    *,
    ticker: str,
    market_date: date,
) -> dict | None:
    """Return the newest independently re-derived exact-response fact."""
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN (?, ?)",
            [RECEIPT_TABLE, OBSERVATION_TABLE],
        ).fetchall()
    }
    if tables != {RECEIPT_TABLE, OBSERVATION_TABLE}:
        return None
    _verify(con)
    row = con.execute(
        f"SELECT * FROM {OBSERVATION_TABLE} "
        "WHERE ticker = ? AND market_date = ? "
        "ORDER BY observation_sequence DESC LIMIT 1",
        [ticker, market_date],
    ).fetchone()
    if row is None:
        return None
    evidence = _stored_observation(con, row)
    confirmations = con.execute(
        f"SELECT COUNT(*) FROM {OBSERVATION_TABLE} "
        "WHERE ticker = ? AND market_date = ? AND value_sha256 = ?",
        [ticker, market_date, evidence["value_sha256"]],
    ).fetchone()[0]
    return {
        **evidence,
        "matching_response_count": int(confirmations),
        "raw_response_body_retained": True,
        "source_publication_time_available": False,
        "provider_dataset_version": None,
        "operational_price_mutation": False,
        "quarantine_mutation": False,
        "execution_authority": "none",
    }


def status(con: duckdb.DuckDBPyConnection) -> dict:
    """Return aggregate verified coverage without exposing response bodies."""
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN (?, ?)",
            [RECEIPT_TABLE, OBSERVATION_TABLE],
        ).fetchall()
    }
    empty = {
        "schema_version": 1,
        "status": "not_initialized" if not tables else "invalid",
        "response_count": 0,
        "observation_count": 0,
        "ticker_count": 0,
        "first_received_at": None,
        "last_received_at": None,
        "response_bytes": 0,
        "source_row_count": 0,
        "parse_error_count": 0,
        "incomplete_row_count": 0,
        "classification_counts": {name: 0 for name in sorted(CLASSIFICATIONS)},
        "raw_response_bodies_retained": False,
        "source_publication_time_available": False,
        "provider_dataset_version": None,
        "operational_price_mutation": False,
        "quarantine_mutation": False,
        "execution_authority": "none",
    }
    if not tables:
        return empty
    if tables != {RECEIPT_TABLE, OBSERVATION_TABLE}:
        raise IndependentPriceEvidenceError("independent evidence schema is incomplete")
    verified = _verify(con)
    summary = con.execute(
        f"SELECT COUNT(DISTINCT ticker), MIN(received_at), MAX(received_at), "
        f"COALESCE(SUM(response_size_bytes), 0), "
        f"COALESCE(SUM(source_row_count), 0), "
        f"COALESCE(SUM(parse_error_count), 0), "
        f"COALESCE(SUM(incomplete_row_count), 0) FROM {RECEIPT_TABLE}"
    ).fetchone()
    return {
        **empty,
        **verified,
        "status": "capturing" if verified["response_count"] else "initialized_empty",
        "ticker_count": int(summary[0]),
        "first_received_at": None if summary[1] is None else _timestamp(summary[1]),
        "last_received_at": None if summary[2] is None else _timestamp(summary[2]),
        "response_bytes": int(summary[3]),
        "source_row_count": int(summary[4]),
        "parse_error_count": int(summary[5]),
        "incomplete_row_count": int(summary[6]),
        "raw_response_bodies_retained": bool(verified["response_count"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "status"))
    parser.add_argument("--strategy", default="dual_momentum")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if args.command == "capture":
        con = engine_db.connect(args.db, read_only=True)
        try:
            market_date = engine_db.latest_operational_market_date(con)
        finally:
            con.close()
        if market_date is None:
            raise IndependentPriceEvidenceError("no breadth-qualified market date")
        result = capture(
            args.db,
            args.strategy,
            market_date,
            sessions=args.sessions,
        )
    else:
        con = engine_db.connect(args.db, read_only=True)
        try:
            result = status(con)
        finally:
            con.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
