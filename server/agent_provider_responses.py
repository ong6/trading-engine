"""Append-only exact provider-response receipts for bounded agent market data."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.settings import DEFAULT_DB
from sim.strategies.configs import config_by_id

SOURCE_NAME = "yfinance"
ENDPOINT = "https://query2.finance.yahoo.com/v8/finance/chart"
ENDPOINT_API_VERSION = "yahoo_finance_chart_v8"
INTERVAL = "1d"
EVENTS = "div,splits"
RESPONSE_SCHEMA_VERSION = 1
LINK_SCHEMA_VERSION = 1
SOURCE_OBSERVATION_SCHEMA_VERSION = 1
SOURCE_OBSERVATION_ADAPTER = "yahoo_finance.chart_v8"
SOURCE_OBSERVATION_ADAPTER_VERSION = "exact_response_v1"
MAX_RESPONSE_BYTES = 2_000_000
MAX_CONTENT_TYPE_CHARS = 128
PROVIDER_TICKER = re.compile(r"^[A-Za-z0-9.^=-]{1,32}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderResponseError(RuntimeError):
    """A provider response cannot be safely retained or verified."""


@dataclass(frozen=True)
class Response:
    body: bytes
    content_type: str
    status_code: int
    received_at: datetime


Fetch = Callable[[str, date, date], Response]


def _utc(value: datetime, field: str) -> datetime:
    if type(value) is not datetime:
        raise ProviderResponseError(f"{field} is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _library_version() -> str:
    try:
        value = version("yfinance")
    except PackageNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise ProviderResponseError("yfinance version is unavailable") from exc
    if not value or len(value) > 64 or not value.isprintable():
        raise ProviderResponseError("yfinance version is invalid")
    return value


def _epoch(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=timezone.utc).timestamp())


def _request_identity(provider_ticker: str, start: date, end: date) -> dict:
    return {
        "endpoint": ENDPOINT,
        "provider_ticker": provider_ticker,
        "period1": _epoch(start),
        "period2": _epoch(end),
        "interval": INTERVAL,
        "events": EVENTS,
        "include_adjusted_close": True,
    }


def _response_sha256(body: bytes) -> str:
    import hashlib

    return hashlib.sha256(body).hexdigest()


def _fetch(provider_ticker: str, start: date, end: date) -> Response:
    """Fetch through yfinance's cookie/crumb-aware session without model access."""
    if PROVIDER_TICKER.fullmatch(provider_ticker) is None:
        raise ProviderResponseError("provider ticker is invalid")
    try:
        from yfinance.data import YfData

        request = _request_identity(provider_ticker, start, end)
        response = YfData().get(
            f"{ENDPOINT}/{quote(provider_ticker, safe='')}",
            params={
                "period1": request["period1"],
                "period2": request["period2"],
                "interval": INTERVAL,
                "events": EVENTS,
                "includeAdjustedClose": "true",
            },
            timeout=30,
        )
        received_at = datetime.now(timezone.utc)
        body = bytes(response.content)
        content_type = response.headers.get("content-type", "")
        status_code = int(response.status_code)
    except Exception as exc:
        raise ProviderResponseError("provider response request failed") from exc
    return Response(body, content_type, status_code, received_at)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_provider_responses (
            id                       BIGINT PRIMARY KEY,
            schema_version           INTEGER NOT NULL,
            source                   VARCHAR NOT NULL,
            endpoint                 VARCHAR NOT NULL,
            endpoint_api_version     VARCHAR NOT NULL,
            ticker                   VARCHAR NOT NULL,
            provider_ticker          VARCHAR NOT NULL,
            period_start             DATE NOT NULL,
            period_end_exclusive     DATE NOT NULL,
            interval                 VARCHAR NOT NULL,
            events                   VARCHAR NOT NULL,
            request_sha256           VARCHAR NOT NULL,
            requested_at             TIMESTAMP NOT NULL,
            received_at              TIMESTAMP NOT NULL,
            http_status              INTEGER NOT NULL,
            content_type             VARCHAR NOT NULL,
            source_library_version   VARCHAR NOT NULL,
            response_size_bytes      BIGINT NOT NULL,
            response_sha256          VARCHAR NOT NULL,
            response_body            BLOB NOT NULL,
            receipt_sha256           VARCHAR NOT NULL UNIQUE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_provider_response_links (
            schema_version      INTEGER NOT NULL,
            receipt_sha256      VARCHAR NOT NULL,
            response_sha256     VARCHAR NOT NULL,
            dataset             VARCHAR NOT NULL,
            ticker              VARCHAR NOT NULL,
            fact_date           DATE NOT NULL,
            kind                VARCHAR NOT NULL,
            value_sha256        VARCHAR NOT NULL,
            observation_sha256  VARCHAR NOT NULL,
            linked_at           TIMESTAMP NOT NULL,
            link_sha256         VARCHAR NOT NULL UNIQUE,
            UNIQUE (receipt_sha256, observation_sha256)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_provider_source_observations (
            id                          BIGINT PRIMARY KEY,
            schema_version              INTEGER NOT NULL,
            dataset                     VARCHAR NOT NULL,
            ticker                      VARCHAR NOT NULL,
            fact_date                   DATE NOT NULL,
            kind                        VARCHAR NOT NULL,
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
            UNIQUE (
                dataset, ticker, fact_date, kind, observation_sequence
            )
        )
        """
    )


def _provider_ticker(con: duckdb.DuckDBPyConnection, ticker: str) -> str:
    universe = con.execute(
        "SELECT yf_ticker FROM universe WHERE ticker = ?", [ticker]
    ).fetchone()
    provider_ticker = ticker if universe is None or not universe[0] else universe[0]
    if (
        not isinstance(provider_ticker, str)
        or PROVIDER_TICKER.fullmatch(provider_ticker) is None
    ):
        raise ProviderResponseError("provider ticker is invalid")
    return provider_ticker


def _strategy_scope(
    con: duckdb.DuckDBPyConnection, strategy_id: str, market_date: date
) -> list[tuple[str, str, date, date]]:
    try:
        params = config_by_id(strategy_id)["params"]
    except (KeyError, TypeError) as exc:
        raise ProviderResponseError("strategy is unavailable") from exc
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
        raise ProviderResponseError("strategy provider-response scope is invalid")
    required = max(lookbacks) + 1
    result = []
    for ticker in sorted(tickers):
        row = con.execute(
            "SELECT MIN(date) FROM (SELECT date FROM prices "
            "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?)",
            [ticker, market_date, required],
        ).fetchone()
        if row is None or row[0] is None:
            continue
        result.append(
            (ticker, _provider_ticker(con, ticker), row[0], market_date + timedelta(days=1))
        )
    if not result:
        raise ProviderResponseError("strategy provider-response scope is empty")
    return result


def _response_result(body: bytes, provider_ticker: str) -> dict:
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise ProviderResponseError("provider response size is invalid")
    try:
        payload = json.loads(body)
        chart = payload["chart"]
        results = chart["result"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ProviderResponseError("provider response JSON is invalid") from exc
    if (
        not isinstance(chart, dict)
        or chart.get("error") is not None
        or not isinstance(results, list)
        or len(results) != 1
        or not isinstance(results[0], dict)
        or results[0].get("meta", {}).get("symbol") != provider_ticker
    ):
        raise ProviderResponseError("provider response result is invalid")
    return results[0]


def _event_date(timestamp: object, zone: ZoneInfo) -> date:
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ProviderResponseError("provider event timestamp is invalid")
    return datetime.fromtimestamp(timestamp, zone).date()


def _finite_positive(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderResponseError("provider numeric value is invalid")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ProviderResponseError("provider numeric value is invalid")
    return result


def _facts(body: bytes, ticker: str, provider_ticker: str) -> list[dict]:
    result = _response_result(body, provider_ticker)
    try:
        timezone_name = result["meta"]["exchangeTimezoneName"]
        zone = ZoneInfo(timezone_name)
        timestamps = result["timestamp"]
        quote_rows = result["indicators"]["quote"]
    except (KeyError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ProviderResponseError("provider response series is invalid") from exc
    if (
        not isinstance(timestamps, list)
        or not isinstance(quote_rows, list)
        or len(quote_rows) != 1
        or not isinstance(quote_rows[0], dict)
    ):
        raise ProviderResponseError("provider response series is invalid")
    quote_values = quote_rows[0]
    fields = ("open", "high", "low", "close", "volume")
    if any(
        not isinstance(quote_values.get(field), list)
        or len(quote_values[field]) != len(timestamps)
        for field in fields
    ):
        raise ProviderResponseError("provider response quote arrays are invalid")

    facts = []
    seen = set()
    for index, timestamp in enumerate(timestamps):
        values = [quote_values[field][index] for field in fields]
        if any(value is None for value in values):
            continue
        market_date = _event_date(timestamp, zone)
        open_price, high, low, close, volume = values
        open_value = _finite_positive(open_price)
        high_value = _finite_positive(high)
        low_value = _finite_positive(low)
        close_value = _finite_positive(close)
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not math.isfinite(volume)
            or volume < 0
            or not float(volume).is_integer()
            or low_value > min(open_value, high_value, close_value)
            or high_value < max(open_value, low_value, close_value)
        ):
            raise ProviderResponseError("provider response OHLCV is invalid")
        value_record = {
            "ticker": ticker,
            "market_date": market_date.isoformat(),
            "open": open_value,
            "high": high_value,
            "low": low_value,
            "close": close_value,
            "volume": int(volume),
            "source": SOURCE_NAME,
        }
        key = ("daily_price", ticker, market_date, "daily_price")
        if key in seen:
            raise ProviderResponseError("provider response contains duplicate facts")
        seen.add(key)
        facts.append(
            {
                "dataset": "daily_price",
                "ticker": ticker,
                "fact_date": market_date,
                "kind": "daily_price",
                "value_sha256": canonical_sha256(value_record),
                "value": value_record,
            }
        )

    events = result.get("events", {})
    if events is None:
        events = {}
    if not isinstance(events, dict):
        raise ProviderResponseError("provider response events are invalid")
    for category, kind in (("dividends", "dividend"), ("splits", "split")):
        values = events.get(category, {})
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise ProviderResponseError("provider response events are invalid")
        for event in values.values():
            if not isinstance(event, dict):
                raise ProviderResponseError("provider response event is invalid")
            event_date = _event_date(event.get("date"), zone)
            if kind == "dividend":
                value = _finite_positive(event.get("amount"))
            else:
                numerator = _finite_positive(event.get("numerator"))
                denominator = _finite_positive(event.get("denominator"))
                value = numerator / denominator
            value_record = {
                "ticker": ticker,
                "ex_date": event_date.isoformat(),
                "kind": kind,
                "value": value,
                "source": SOURCE_NAME,
            }
            key = ("corporate_action", ticker, event_date, kind)
            if key in seen:
                raise ProviderResponseError("provider response contains duplicate facts")
            seen.add(key)
            facts.append(
                {
                    "dataset": "corporate_action",
                    "ticker": ticker,
                    "fact_date": event_date,
                    "kind": kind,
                    "value_sha256": canonical_sha256(value_record),
                    "value": value_record,
                }
            )
    return facts


def _source_normalized(fact: dict, received_at: datetime) -> dict:
    normalized = {
        **fact["value"],
        "latest_ingested_at": _timestamp(received_at),
    }
    if canonical_sha256(fact["value"]) != fact["value_sha256"]:
        raise ProviderResponseError("provider response fact identity is invalid")
    return normalized


def _source_observation(
    con: duckdb.DuckDBPyConnection,
    receipt: dict,
    fact: dict,
    *,
    receipt_cache: dict | None = None,
) -> tuple[dict, bool]:
    """Return the exact-response observation for a fact, inserting a revision if new."""
    latest = con.execute(
        "SELECT observation_sequence, value_revision, value_sha256, "
        "observation_sha256 FROM agent_provider_source_observations "
        "WHERE dataset = ? AND ticker = ? AND fact_date = ? AND kind = ? "
        "ORDER BY observation_sequence DESC LIMIT 1",
        [
            fact["dataset"],
            fact["ticker"],
            fact["fact_date"],
            fact["kind"],
        ],
    ).fetchone()
    if latest is not None and latest[2] == fact["value_sha256"]:
        row = con.execute(
            "SELECT * FROM agent_provider_source_observations "
            "WHERE observation_sha256 = ?",
            [latest[3]],
        ).fetchone()
        if row is None:
            raise ProviderResponseError("stored source observation is invalid")
        return _stored_source_observation(
            con, row, receipt_cache=receipt_cache
        ), False

    sequence = 1 if latest is None else int(latest[0]) + 1
    revision = 1 if latest is None else int(latest[1]) + 1
    classification = (
        "baseline_source_observation"
        if latest is None
        else "source_value_revision"
    )
    previous = None if latest is None else latest[3]
    received_at = datetime.fromisoformat(
        receipt["received_at"].replace("Z", "+00:00")
    )
    observed_at = received_at
    normalized = _source_normalized(fact, received_at)
    normalized_sha256 = canonical_sha256(normalized)
    identity = {
        "schema_version": SOURCE_OBSERVATION_SCHEMA_VERSION,
        "dataset": fact["dataset"],
        "ticker": fact["ticker"],
        "fact_date": fact["fact_date"].isoformat(),
        "kind": fact["kind"],
        "normalized_sha256": normalized_sha256,
        "value_sha256": fact["value_sha256"],
        "source_fetched_at": receipt["received_at"],
        "observed_at": _timestamp(observed_at),
        "source_adapter": SOURCE_OBSERVATION_ADAPTER,
        "source_adapter_version": SOURCE_OBSERVATION_ADAPTER_VERSION,
        "source_library_version": receipt["source_library_version"],
        "observation_sequence": sequence,
        "value_revision": revision,
        "classification": classification,
        "previous_observation_sha256": previous,
        "receipt_sha256": receipt["receipt_sha256"],
        "response_sha256": receipt["response_sha256"],
    }
    observation_sha256 = canonical_sha256(identity)
    next_id = int(
        con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 "
            "FROM agent_provider_source_observations"
        ).fetchone()[0]
    )
    con.execute(
        "INSERT INTO agent_provider_source_observations VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            next_id,
            SOURCE_OBSERVATION_SCHEMA_VERSION,
            fact["dataset"],
            fact["ticker"],
            fact["fact_date"],
            fact["kind"],
            json.dumps(normalized, sort_keys=True, separators=(",", ":")),
            normalized_sha256,
            fact["value_sha256"],
            received_at,
            observed_at,
            SOURCE_OBSERVATION_ADAPTER,
            SOURCE_OBSERVATION_ADAPTER_VERSION,
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
    row = con.execute(
        "SELECT * FROM agent_provider_source_observations "
        "WHERE observation_sha256 = ?",
        [observation_sha256],
    ).fetchone()
    if row is None:
        raise ProviderResponseError("source observation insert failed")
    return _stored_source_observation(
        con, row, receipt_cache=receipt_cache
    ), True


def _receipt(
    *,
    ticker: str,
    provider_ticker: str,
    start: date,
    end: date,
    requested_at: datetime,
    response: Response,
) -> tuple[dict, list[dict]]:
    requested_at = _utc(requested_at, "request time")
    received_at = _utc(response.received_at, "response receipt time")
    if (
        received_at < requested_at
        or response.status_code != 200
        or not isinstance(response.content_type, str)
        or not response.content_type.lower().startswith("application/json")
        or len(response.content_type) > MAX_CONTENT_TYPE_CHARS
    ):
        raise ProviderResponseError("provider response metadata is invalid")
    facts = _facts(response.body, ticker, provider_ticker)
    if (
        not any(fact["dataset"] == "daily_price" for fact in facts)
        or any(
            fact["fact_date"] < start or fact["fact_date"] >= end
            for fact in facts
        )
    ):
        raise ProviderResponseError("provider response facts exceed request scope")
    request_sha256 = canonical_sha256(
        _request_identity(provider_ticker, start, end)
    )
    response_sha256 = _response_sha256(response.body)
    identity = {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "endpoint": ENDPOINT,
        "endpoint_api_version": ENDPOINT_API_VERSION,
        "ticker": ticker,
        "provider_ticker": provider_ticker,
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "interval": INTERVAL,
        "events": EVENTS,
        "request_sha256": request_sha256,
        "requested_at": _timestamp(requested_at),
        "received_at": _timestamp(received_at),
        "http_status": response.status_code,
        "content_type": response.content_type,
        "source_library_version": _library_version(),
        "response_size_bytes": len(response.body),
        "response_sha256": response_sha256,
    }
    return {**identity, "receipt_sha256": canonical_sha256(identity)}, facts


def _matching_observation(
    con: duckdb.DuckDBPyConnection, fact: dict
) -> str | None:
    if fact["dataset"] == "daily_price":
        table = con.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'agent_daily_price_observations'"
        ).fetchone()
        if table is None:
            return None
        row = con.execute(
            "SELECT observation_sha256 FROM agent_daily_price_observations "
            "WHERE ticker = ? AND market_date = ? AND value_sha256 = ? "
            "ORDER BY observation_sequence DESC LIMIT 1",
            [fact["ticker"], fact["fact_date"], fact["value_sha256"]],
        ).fetchone()
    else:
        table = con.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'agent_corporate_action_observations'"
        ).fetchone()
        if table is None:
            return None
        row = con.execute(
            "SELECT observation_sha256 "
            "FROM agent_corporate_action_observations "
            "WHERE ticker = ? AND ex_date = ? AND kind = ? "
            "AND value_sha256 = ? ORDER BY observation_sequence DESC LIMIT 1",
            [
                fact["ticker"],
                fact["fact_date"],
                fact["kind"],
                fact["value_sha256"],
            ],
        ).fetchone()
    return None if row is None else row[0]


def _observation_matches(
    con: duckdb.DuckDBPyConnection,
    fact: dict,
    observation_sha256: str,
) -> bool:
    if not isinstance(observation_sha256, str) or SHA256.fullmatch(
        observation_sha256
    ) is None:
        return False
    if fact["dataset"] == "daily_price":
        table = "agent_daily_price_observations"
        date_column = "market_date"
        parameters = [
            observation_sha256,
            fact["ticker"],
            fact["fact_date"],
            fact["value_sha256"],
        ]
        kind_clause = ""
    else:
        table = "agent_corporate_action_observations"
        date_column = "ex_date"
        parameters = [
            observation_sha256,
            fact["ticker"],
            fact["fact_date"],
            fact["kind"],
            fact["value_sha256"],
        ]
        kind_clause = "AND kind = ? "
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    if exists is None:
        return False
    row = con.execute(
        f"SELECT 1 FROM {table} WHERE observation_sha256 = ? AND ticker = ? "
        f"AND {date_column} = ? {kind_clause}AND value_sha256 = ?",
        parameters,
    ).fetchone()
    return row is not None


def _persist(
    con: duckdb.DuckDBPyConnection,
    captures: list[tuple[dict, bytes, list[dict]]],
) -> dict:
    init_schema(con)
    next_id = int(
        con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM agent_provider_responses"
        ).fetchone()[0]
    )
    inserted_responses = linked_facts = extracted_facts = 0
    inserted_source_observations = 0
    source_receipt_cache = {}
    with engine_db.transaction(con):
        for receipt, body, facts in captures:
            extracted_facts += len(facts)
            exists = con.execute(
                "SELECT receipt_sha256, received_at "
                "FROM agent_provider_responses "
                "WHERE receipt_sha256 = ?",
                [receipt["receipt_sha256"]],
            ).fetchone()
            receipt_sha256 = receipt["receipt_sha256"]
            if exists is None:
                con.execute(
                    "INSERT INTO agent_provider_responses VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        next_id,
                        receipt["schema_version"],
                        receipt["source"],
                        receipt["endpoint"],
                        receipt["endpoint_api_version"],
                        receipt["ticker"],
                        receipt["provider_ticker"],
                        date.fromisoformat(receipt["period_start"]),
                        date.fromisoformat(receipt["period_end_exclusive"]),
                        receipt["interval"],
                        receipt["events"],
                        receipt["request_sha256"],
                        datetime.fromisoformat(
                            receipt["requested_at"].replace("Z", "+00:00")
                        ),
                        datetime.fromisoformat(
                            receipt["received_at"].replace("Z", "+00:00")
                        ),
                        receipt["http_status"],
                        receipt["content_type"],
                        receipt["source_library_version"],
                        receipt["response_size_bytes"],
                        receipt["response_sha256"],
                        body,
                        receipt_sha256,
                    ],
                )
                next_id += 1
                inserted_responses += 1
                linked_at = receipt["received_at"]
            else:
                receipt_sha256 = exists[0]
                linked_at = _timestamp(exists[1])
            for fact in facts:
                if exists is None:
                    _source, inserted = _source_observation(
                        con,
                        receipt,
                        fact,
                        receipt_cache=source_receipt_cache,
                    )
                    inserted_source_observations += int(inserted)
                observation_sha256 = _matching_observation(con, fact)
                if observation_sha256 is None:
                    continue
                link_identity = {
                    "schema_version": LINK_SCHEMA_VERSION,
                    "receipt_sha256": receipt_sha256,
                    "response_sha256": receipt["response_sha256"],
                    "dataset": fact["dataset"],
                    "ticker": fact["ticker"],
                    "fact_date": fact["fact_date"].isoformat(),
                    "kind": fact["kind"],
                    "value_sha256": fact["value_sha256"],
                    "observation_sha256": observation_sha256,
                    "linked_at": linked_at,
                    "relationship": "later_exact_value_corroboration",
                }
                link_sha256 = canonical_sha256(link_identity)
                before = con.execute(
                    "SELECT 1 FROM agent_provider_response_links "
                    "WHERE receipt_sha256 = ? AND observation_sha256 = ?",
                    [receipt_sha256, observation_sha256],
                ).fetchone()
                if before is not None:
                    continue
                con.execute(
                    "INSERT INTO agent_provider_response_links VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        LINK_SCHEMA_VERSION,
                        receipt_sha256,
                        receipt["response_sha256"],
                        fact["dataset"],
                        fact["ticker"],
                        fact["fact_date"],
                        fact["kind"],
                        fact["value_sha256"],
                        observation_sha256,
                        datetime.fromisoformat(
                            linked_at.replace("Z", "+00:00")
                        ),
                        link_sha256,
                    ],
                )
                linked_facts += 1
    return {
        "selected_responses": len(captures),
        "inserted_responses": inserted_responses,
        "extracted_facts": extracted_facts,
        "linked_observations": linked_facts,
        "inserted_source_observations": inserted_source_observations,
    }


def capture(
    database: Path,
    strategy_id: str,
    market_date: date,
    *,
    fetch: Fetch = _fetch,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """Fetch without a writer lease, then atomically retain validated receipts."""
    con = engine_db.connect(database, read_only=True)
    try:
        scope = _strategy_scope(con, strategy_id, market_date)
    finally:
        con.close()
    totals = {
        "selected_responses": 0,
        "inserted_responses": 0,
        "extracted_facts": 0,
        "linked_observations": 0,
        "inserted_source_observations": 0,
    }
    for ticker, provider_ticker, start, end in scope:
        requested_at = (now or (lambda: datetime.now(timezone.utc)))()
        response = fetch(provider_ticker, start, end)
        receipt, facts = _receipt(
            ticker=ticker,
            provider_ticker=provider_ticker,
            start=start,
            end=end,
            requested_at=requested_at,
            response=response,
        )
        con = engine_db.connect(database)
        try:
            result = _persist(con, [(receipt, response.body, facts)])
        finally:
            con.close()
        for field in totals:
            totals[field] += result[field]
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "market_date": market_date.isoformat(),
        "required_tickers": [item[0] for item in scope],
        **totals,
    }


def _stored_receipt(row: tuple) -> tuple[dict, bytes]:
    body = bytes(row[19])
    identity = {
        "schema_version": row[1],
        "source": row[2],
        "endpoint": row[3],
        "endpoint_api_version": row[4],
        "ticker": row[5],
        "provider_ticker": row[6],
        "period_start": row[7].isoformat(),
        "period_end_exclusive": row[8].isoformat(),
        "interval": row[9],
        "events": row[10],
        "request_sha256": row[11],
        "requested_at": _timestamp(row[12]),
        "received_at": _timestamp(row[13]),
        "http_status": row[14],
        "content_type": row[15],
        "source_library_version": row[16],
        "response_size_bytes": row[17],
        "response_sha256": row[18],
    }
    if (
        row[1] != RESPONSE_SCHEMA_VERSION
        or row[2] != SOURCE_NAME
        or row[3] != ENDPOINT
        or row[4] != ENDPOINT_API_VERSION
        or row[9] != INTERVAL
        or row[10] != EVENTS
        or row[14] != 200
        or not row[15].lower().startswith("application/json")
        or row[17] != len(body)
        or row[18] != _response_sha256(body)
        or row[20] != canonical_sha256(identity)
        or row[11]
        != canonical_sha256(_request_identity(row[6], row[7], row[8]))
        or _utc(row[13], "stored response receipt time")
        < _utc(row[12], "stored request time")
    ):
        raise ProviderResponseError("stored provider response receipt is invalid")
    _facts(body, row[5], row[6])
    return identity, body


def _normalized_source_value(row: tuple) -> tuple[dict, dict]:
    try:
        normalized = json.loads(row[6])
    except (TypeError, ValueError) as exc:
        raise ProviderResponseError("stored source observation is invalid") from exc
    if not isinstance(normalized, dict):
        raise ProviderResponseError("stored source observation is invalid")
    if row[2] == "daily_price":
        value_fields = (
            "ticker",
            "market_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        )
    elif row[2] == "corporate_action":
        value_fields = ("ticker", "ex_date", "kind", "value", "source")
    else:
        raise ProviderResponseError("stored source observation is invalid")
    if set(normalized) != {*value_fields, "latest_ingested_at"}:
        raise ProviderResponseError("stored source observation is invalid")
    return normalized, {field: normalized[field] for field in value_fields}


def _stored_source_observation(
    con: duckdb.DuckDBPyConnection,
    row: tuple,
    *,
    receipt_cache: dict | None = None,
) -> dict:
    normalized, value = _normalized_source_value(row)
    try:
        source_fetched_at = _timestamp(row[9])
        observed_at = _timestamp(row[10])
    except (TypeError, ValueError) as exc:
        raise ProviderResponseError("stored source observation is invalid") from exc
    identity = {
        "schema_version": row[1],
        "dataset": row[2],
        "ticker": row[3],
        "fact_date": row[4].isoformat(),
        "kind": row[5],
        "normalized_sha256": row[7],
        "value_sha256": row[8],
        "source_fetched_at": source_fetched_at,
        "observed_at": observed_at,
        "source_adapter": row[11],
        "source_adapter_version": row[12],
        "source_library_version": row[13],
        "observation_sequence": row[14],
        "value_revision": row[15],
        "classification": row[16],
        "previous_observation_sha256": row[17],
        "receipt_sha256": row[18],
        "response_sha256": row[19],
    }
    cached = None if receipt_cache is None else receipt_cache.get(row[18])
    if cached is None:
        receipt = con.execute(
            "SELECT * FROM agent_provider_responses WHERE receipt_sha256 = ?",
            [row[18]],
        ).fetchone()
        if receipt is None:
            raise ProviderResponseError("stored source observation is invalid")
        _receipt_identity, body = _stored_receipt(receipt)
        extracted = {
            (
                item["dataset"],
                item["ticker"],
                item["fact_date"],
                item["kind"],
                item["value_sha256"],
            )
            for item in _facts(body, receipt[5], receipt[6])
        }
        if receipt_cache is not None:
            receipt_cache[row[18]] = (receipt, extracted)
    else:
        receipt, extracted = cached
    if (
        row[1] != SOURCE_OBSERVATION_SCHEMA_VERSION
        or row[3] != normalized["ticker"]
        or (
            row[2] == "daily_price"
            and (
                row[4].isoformat() != normalized["market_date"]
                or row[5] != "daily_price"
            )
        )
        or (
            row[2] == "corporate_action"
            and (
                row[4].isoformat() != normalized["ex_date"]
                or row[5] != normalized["kind"]
            )
        )
        or normalized["source"] != SOURCE_NAME
        or normalized["latest_ingested_at"] != source_fetched_at
        or row[11] != SOURCE_OBSERVATION_ADAPTER
        or row[12] != SOURCE_OBSERVATION_ADAPTER_VERSION
        or row[13] != receipt[16]
        or row[16]
        not in {"baseline_source_observation", "source_value_revision"}
        or row[18] != receipt[20]
        or row[19] != receipt[18]
        or _utc(row[9], "source observation receipt time")
        != _utc(receipt[13], "stored receipt time")
        or _utc(row[10], "source observation time")
        < _utc(row[9], "source observation receipt time")
        or canonical_sha256(normalized) != row[7]
        or canonical_sha256(value) != row[8]
        or (row[2], row[3], row[4], row[5], row[8]) not in extracted
        or canonical_sha256(identity) != row[20]
    ):
        raise ProviderResponseError("stored source observation is invalid")
    return {
        **identity,
        "observation_sha256": row[20],
        "normalized": normalized,
    }


def source_observation_for_fact(
    con: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
    value_sha256: str,
) -> dict | None:
    """Return the newest exact-response observation matching one selected fact."""
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_source_observations'"
    ).fetchone()
    if exists is None:
        return None
    row = con.execute(
        "SELECT * FROM agent_provider_source_observations "
        "WHERE dataset = ? AND ticker = ? AND fact_date = ? AND kind = ? "
        "AND value_sha256 = ? ORDER BY observation_sequence DESC LIMIT 1",
        [dataset, ticker, fact_date, kind, value_sha256],
    ).fetchone()
    return None if row is None else _stored_source_observation(con, row)


def evidence_for_observation(
    con: duckdb.DuckDBPyConnection,
    observation_sha256: str,
) -> dict | None:
    """Return the newest verified exact-response link for one observation."""
    if (
        not isinstance(observation_sha256, str)
        or SHA256.fullmatch(observation_sha256) is None
    ):
        raise ProviderResponseError("observation identity is invalid")
    source_table = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_source_observations'"
    ).fetchone()
    if source_table is not None:
        source_row = con.execute(
            "SELECT * FROM agent_provider_source_observations "
            "WHERE observation_sha256 = ?",
            [observation_sha256],
        ).fetchone()
        if source_row is not None:
            source = _stored_source_observation(con, source_row)
            return {
                "schema_version": LINK_SCHEMA_VERSION,
                "relationship": "exact_response_source_observation",
                "receipt_sha256": source["receipt_sha256"],
                "response_sha256": source["response_sha256"],
                "response_size_bytes": con.execute(
                    "SELECT response_size_bytes FROM agent_provider_responses "
                    "WHERE receipt_sha256 = ?",
                    [source["receipt_sha256"]],
                ).fetchone()[0],
                "received_at": source["observed_at"],
                "endpoint_api_version": ENDPOINT_API_VERSION,
                "source_library_version": source["source_library_version"],
                "observation_sha256": observation_sha256,
                "value_sha256": source["value_sha256"],
                "raw_response_body_retained": True,
            }
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN "
            "('agent_provider_responses', 'agent_provider_response_links')"
        ).fetchall()
    }
    if tables != {
        "agent_provider_responses",
        "agent_provider_response_links",
    }:
        return None
    link = con.execute(
        "SELECT schema_version, receipt_sha256, response_sha256, dataset, "
        "ticker, fact_date, kind, value_sha256, observation_sha256, "
        "linked_at, link_sha256 FROM agent_provider_response_links "
        "WHERE observation_sha256 = ? ORDER BY linked_at DESC, link_sha256 DESC "
        "LIMIT 1",
        [observation_sha256],
    ).fetchone()
    if link is None:
        return None
    receipt = con.execute(
        "SELECT * FROM agent_provider_responses WHERE receipt_sha256 = ?",
        [link[1]],
    ).fetchone()
    if receipt is None:
        raise ProviderResponseError("stored provider response link is invalid")
    receipt_identity, body = _stored_receipt(receipt)
    fact = {
        "dataset": link[3],
        "ticker": link[4],
        "fact_date": link[5],
        "kind": link[6],
        "value_sha256": link[7],
    }
    link_identity = {
        "schema_version": link[0],
        "receipt_sha256": link[1],
        "response_sha256": link[2],
        "dataset": link[3],
        "ticker": link[4],
        "fact_date": link[5].isoformat(),
        "kind": link[6],
        "value_sha256": link[7],
        "observation_sha256": link[8],
        "linked_at": _timestamp(link[9]),
        "relationship": "later_exact_value_corroboration",
    }
    extracted = {
        (
            item["dataset"],
            item["ticker"],
            item["fact_date"],
            item["kind"],
            item["value_sha256"],
        )
        for item in _facts(body, receipt[5], receipt[6])
    }
    if (
        link[0] != LINK_SCHEMA_VERSION
        or link[1] != receipt[20]
        or link[2] != receipt[18]
        or link[8] != observation_sha256
        or _utc(link[9], "stored link time")
        != _utc(receipt[13], "stored receipt time")
        or (
            fact["dataset"],
            fact["ticker"],
            fact["fact_date"],
            fact["kind"],
            fact["value_sha256"],
        )
        not in extracted
        or not _observation_matches(con, fact, observation_sha256)
        or canonical_sha256(link_identity) != link[10]
    ):
        raise ProviderResponseError("stored provider response link is invalid")
    return {
        "schema_version": LINK_SCHEMA_VERSION,
        "relationship": "later_exact_value_corroboration",
        "receipt_sha256": receipt[20],
        "response_sha256": receipt[18],
        "response_size_bytes": receipt[17],
        "received_at": _timestamp(receipt[13]),
        "endpoint_api_version": receipt[4],
        "source_library_version": receipt[16],
        "observation_sha256": observation_sha256,
        "value_sha256": link[7],
        "raw_response_body_retained": True,
    }


def _verify(con: duckdb.DuckDBPyConnection) -> dict:
    rows = con.execute(
        "SELECT * FROM agent_provider_responses ORDER BY id"
    ).fetchall()
    facts_by_receipt = {}
    receipt_metadata = {}
    prior_actions_by_ticker = {}
    action_snapshot_count = 0
    action_set_change_count = 0
    action_addition_count = 0
    action_removal_count = 0
    for row in rows:
        _identity, body = _stored_receipt(row)
        facts = _facts(body, row[5], row[6])
        facts_by_receipt[row[20]] = {
            (
                fact["dataset"],
                fact["ticker"],
                fact["fact_date"],
                fact["kind"],
                fact["value_sha256"],
            )
            for fact in facts
        }
        receipt_metadata[row[20]] = (row[18], row[13])
        actions = {
            (
                fact["ticker"],
                fact["fact_date"],
                fact["kind"],
                fact["value_sha256"],
            )
            for fact in facts
            if fact["dataset"] == "corporate_action"
        }
        scope = (row[7], row[8])
        previous = prior_actions_by_ticker.get(row[5])
        if previous is not None:
            previous_scope, previous_actions = previous
            overlap_start = max(scope[0], previous_scope[0])
            overlap_end = min(scope[1], previous_scope[1])
            if overlap_start >= overlap_end:
                raise ProviderResponseError(
                    "consecutive provider response scopes do not overlap"
                )
            comparable_previous = {
                action
                for action in previous_actions
                if overlap_start <= action[1] < overlap_end
            }
            comparable_actions = {
                action
                for action in actions
                if overlap_start <= action[1] < overlap_end
            }
        else:
            comparable_previous = actions
            comparable_actions = actions
        if comparable_actions != comparable_previous:
            action_set_change_count += 1
            action_addition_count += len(
                comparable_actions - comparable_previous
            )
            action_removal_count += len(
                comparable_previous - comparable_actions
            )
        prior_actions_by_ticker[row[5]] = (scope, actions)
        action_snapshot_count += 1
    links = con.execute(
        "SELECT schema_version, receipt_sha256, response_sha256, dataset, "
        "ticker, fact_date, kind, value_sha256, observation_sha256, "
        "linked_at, link_sha256 FROM agent_provider_response_links "
        "ORDER BY receipt_sha256, observation_sha256"
    ).fetchall()
    table_names = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN "
            "('agent_daily_price_observations', "
            "'agent_corporate_action_observations')"
        ).fetchall()
    }
    price_observations = (
        {
            (row[0], row[1], row[2], row[3])
            for row in con.execute(
                "SELECT observation_sha256, ticker, market_date, value_sha256 "
                "FROM agent_daily_price_observations"
            ).fetchall()
        }
        if "agent_daily_price_observations" in table_names
        else set()
    )
    action_observations = (
        {
            (row[0], row[1], row[2], row[3], row[4])
            for row in con.execute(
                "SELECT observation_sha256, ticker, ex_date, kind, value_sha256 "
                "FROM agent_corporate_action_observations"
            ).fetchall()
        }
        if "agent_corporate_action_observations" in table_names
        else set()
    )
    for row in links:
        fact = (row[3], row[4], row[5], row[6], row[7])
        identity = {
            "schema_version": row[0],
            "receipt_sha256": row[1],
            "response_sha256": row[2],
            "dataset": row[3],
            "ticker": row[4],
            "fact_date": row[5].isoformat(),
            "kind": row[6],
            "value_sha256": row[7],
            "observation_sha256": row[8],
            "linked_at": _timestamp(row[9]),
            "relationship": "later_exact_value_corroboration",
        }
        receipt = receipt_metadata.get(row[1])
        observation_matches = (
            (row[8], row[4], row[5], row[7]) in price_observations
            if row[3] == "daily_price"
            else (row[8], row[4], row[5], row[6], row[7])
            in action_observations
        )
        if (
            row[0] != LINK_SCHEMA_VERSION
            or receipt is None
            or receipt[0] != row[2]
            or _utc(receipt[1], "stored receipt time")
            != _utc(row[9], "stored link time")
            or fact not in facts_by_receipt.get(row[1], set())
            or not observation_matches
            or canonical_sha256(identity) != row[10]
        ):
            raise ProviderResponseError("stored provider response link is invalid")
    source_table = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_source_observations'"
    ).fetchone()
    source_rows = (
        []
        if source_table is None
        else con.execute(
            "SELECT * FROM agent_provider_source_observations "
            "ORDER BY dataset, ticker, fact_date, kind, observation_sequence"
        ).fetchall()
    )
    previous_by_key = {}
    source_receipt_cache = {}
    for row in source_rows:
        _stored_source_observation(
            con, row, receipt_cache=source_receipt_cache
        )
        key = (row[2], row[3], row[4], row[5])
        previous = previous_by_key.get(key)
        if (
            row[14] != (1 if previous is None else previous[0] + 1)
            or row[15] != (1 if previous is None else previous[1] + 1)
            or row[16]
            != (
                "baseline_source_observation"
                if previous is None
                else "source_value_revision"
            )
            or row[17] != (None if previous is None else previous[2])
            or (previous is not None and row[8] == previous[3])
        ):
            raise ProviderResponseError(
                "stored source observation revision chain is invalid"
            )
        previous_by_key[key] = (row[14], row[15], row[20], row[8])
    return {
        "extracted_fact_count": sum(
            len(facts) for facts in facts_by_receipt.values()
        ),
        "action_snapshot_count": action_snapshot_count,
        "action_set_change_count": action_set_change_count,
        "action_addition_count": action_addition_count,
        "action_removal_count": action_removal_count,
        "source_observation_count": len(source_rows),
    }


def _cache_value_sha256(
    con: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
    available_tables: set[str],
) -> str | None:
    """Hash one current cache fact in the exact shape emitted by ``_facts``."""
    if dataset == "daily_price":
        if "prices" not in available_tables:
            return None
        rows = con.execute(
            "SELECT ticker, date, open, high, low, close, volume, source "
            "FROM prices WHERE ticker = ? AND date = ?",
            [ticker, fact_date],
        ).fetchall()
        if len(rows) > 1:
            raise ProviderResponseError("current price cache key is ambiguous")
        if not rows:
            return None
        row = rows[0]
        value = {
            "ticker": row[0],
            "market_date": row[1].isoformat(),
            "open": row[2],
            "high": row[3],
            "low": row[4],
            "close": row[5],
            "volume": row[6],
            "source": row[7],
        }
    elif dataset == "corporate_action":
        if "corporate_actions" not in available_tables:
            return None
        rows = con.execute(
            "SELECT ticker, ex_date, kind, value, source "
            "FROM corporate_actions "
            "WHERE ticker = ? AND ex_date = ? AND kind = ?",
            [ticker, fact_date, kind],
        ).fetchall()
        if len(rows) > 1:
            raise ProviderResponseError(
                "current corporate-action cache key is ambiguous"
            )
        if not rows:
            return None
        row = rows[0]
        value = {
            "ticker": row[0],
            "ex_date": row[1].isoformat(),
            "kind": row[2],
            "value": row[3],
            "source": row[4],
        }
    else:  # Protected by source-ledger verification.
        raise ProviderResponseError("stored source observation is invalid")
    return canonical_sha256(value)


def _cache_alignment(con: duckdb.DuckDBPyConnection) -> dict:
    """Compare newest exact-source facts with cache values without exposing either."""
    source_table = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_source_observations'"
    ).fetchone()
    latest = (
        []
        if source_table is None
        else con.execute(
            "SELECT dataset, ticker, fact_date, kind, value_sha256, "
            "source_fetched_at FROM ("
            "SELECT dataset, ticker, fact_date, kind, value_sha256, "
            "source_fetched_at, ROW_NUMBER() OVER ("
            "PARTITION BY dataset, ticker, fact_date, kind "
            "ORDER BY observation_sequence DESC"
            ") AS newest FROM agent_provider_source_observations"
            ") WHERE newest = 1 ORDER BY dataset, ticker, fact_date, kind"
        ).fetchall()
    )
    available_tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('prices', 'corporate_actions')"
        ).fetchall()
    }
    latest_receipt_by_value = {}
    for ticker, provider_ticker, received_at, body in con.execute(
        "SELECT ticker, provider_ticker, received_at, response_body "
        "FROM agent_provider_responses ORDER BY received_at, id"
    ).fetchall():
        for fact in _facts(bytes(body), ticker, provider_ticker):
            key = (
                fact["dataset"],
                fact["ticker"],
                fact["fact_date"],
                fact["kind"],
                fact["value_sha256"],
            )
            latest_receipt_by_value[key] = received_at
    aligned = 0
    mismatches = {"corporate_action": 0, "daily_price": 0}
    missing = 0
    affected_tickers = set()
    mismatch_dates = []
    mismatch_receipts = []
    for dataset, ticker, fact_date, kind, value_sha256, fetched_at in latest:
        cache_sha256 = _cache_value_sha256(
            con,
            dataset=dataset,
            ticker=ticker,
            fact_date=fact_date,
            kind=kind,
            available_tables=available_tables,
        )
        if cache_sha256 is None:
            missing += 1
            affected_tickers.add(ticker)
        elif cache_sha256 == value_sha256:
            aligned += 1
        else:
            mismatches[dataset] += 1
            affected_tickers.add(ticker)
            mismatch_dates.append(fact_date)
            mismatch_receipts.append(
                latest_receipt_by_value.get(
                    (dataset, ticker, fact_date, kind, value_sha256),
                    fetched_at,
                )
            )
    mismatch_count = sum(mismatches.values())
    if mismatch_count and missing:
        alignment_status = "current_cache_drift_and_missing_rows_detected"
    elif mismatch_count:
        alignment_status = "current_cache_value_drift_detected"
    elif missing:
        alignment_status = "current_cache_rows_missing"
    elif latest:
        alignment_status = "current_cache_aligned"
    else:
        alignment_status = "no_source_observations"
    return {
        "cache_alignment_status": alignment_status,
        "cache_alignment_relationship": (
            "newest_exact_source_observation_vs_current_operational_cache"
        ),
        "cache_comparable_source_fact_count": len(latest),
        "cache_aligned_fact_count": aligned,
        "cache_mismatched_fact_count": mismatch_count,
        "missing_cache_fact_count": missing,
        "cache_mismatches_by_dataset": mismatches,
        "cache_alignment_affected_ticker_count": len(affected_tickers),
        "earliest_cache_mismatch_fact_date": (
            None if not mismatch_dates else min(mismatch_dates).isoformat()
        ),
        "latest_cache_mismatch_fact_date": (
            None if not mismatch_dates else max(mismatch_dates).isoformat()
        ),
        "latest_cache_mismatch_receipt_at": (
            None
            if not mismatch_receipts
            else _timestamp(max(mismatch_receipts))
        ),
        "cache_mutation_implemented": False,
    }


def status(con: duckdb.DuckDBPyConnection) -> dict:
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_responses'"
    ).fetchone()
    empty = {
        "schema_version": 2,
        "status": "not_initialized",
        "response_count": 0,
        "ticker_count": 0,
        "response_bytes": 0,
        "extracted_fact_count": 0,
        "link_count": 0,
        "linked_observation_count": 0,
        "source_observation_count": 0,
        "action_snapshot_count": 0,
        "action_set_change_count": 0,
        "action_addition_count": 0,
        "action_removal_count": 0,
        "first_received_at": None,
        "last_received_at": None,
        "source": SOURCE_NAME,
        "endpoint_api_version": ENDPOINT_API_VERSION,
        "raw_response_bodies_retained": False,
        "link_relationship": "later_exact_value_corroboration",
        "source_observation_relationship": "exact_response_source_observation",
        "source_publication_time_available": False,
        "cache_alignment_status": "no_source_observations",
        "cache_alignment_relationship": (
            "newest_exact_source_observation_vs_current_operational_cache"
        ),
        "cache_comparable_source_fact_count": 0,
        "cache_aligned_fact_count": 0,
        "cache_mismatched_fact_count": 0,
        "missing_cache_fact_count": 0,
        "cache_mismatches_by_dataset": {
            "corporate_action": 0,
            "daily_price": 0,
        },
        "cache_alignment_affected_ticker_count": 0,
        "earliest_cache_mismatch_fact_date": None,
        "latest_cache_mismatch_fact_date": None,
        "latest_cache_mismatch_receipt_at": None,
        "cache_mutation_implemented": False,
        "execution_authority": "none",
    }
    if exists is None:
        return empty
    verification = _verify(con)
    alignment = _cache_alignment(con)
    row = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT ticker), "
        "COALESCE(SUM(response_size_bytes), 0), "
        "MIN(received_at), MAX(received_at) FROM agent_provider_responses"
    ).fetchone()
    linked = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT observation_sha256) "
        "FROM agent_provider_response_links"
    ).fetchone()
    return {
        **empty,
        "status": "capturing" if row[0] else "initialized_empty",
        "response_count": int(row[0]),
        "ticker_count": int(row[1]),
        "response_bytes": int(row[2]),
        **verification,
        **alignment,
        "link_count": int(linked[0]),
        "linked_observation_count": int(linked[1]),
        "first_received_at": None if row[3] is None else _timestamp(row[3]),
        "last_received_at": None if row[4] is None else _timestamp(row[4]),
        "raw_response_bodies_retained": bool(row[0]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "status"))
    parser.add_argument("--strategy", default="dual_momentum")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if args.command == "capture":
        con = engine_db.connect(args.db, read_only=True)
        try:
            market_date = engine_db.latest_operational_market_date(con)
        finally:
            con.close()
        if market_date is None:
            raise ProviderResponseError("no breadth-qualified market date")
        result = capture(args.db, args.strategy, market_date)
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
