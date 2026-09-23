"""Vendor-neutral append-only bitemporal fact and raw-source receipt contract."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256

SCHEMA_VERSION = 1
MAX_RAW_BYTES = 2_000_000


class FactError(ValueError):
    """A source receipt or bitemporal fact is malformed or inconsistent."""


def _utc(value: datetime, field: str) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise FactError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _text(value: object, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or not value.isprintable():
        raise FactError(f"{field} is invalid")
    return value


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE IF NOT EXISTS source_response_receipts (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, source VARCHAR NOT NULL,
        dataset VARCHAR NOT NULL, endpoint VARCHAR NOT NULL, request_payload VARCHAR NOT NULL,
        request_sha256 VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL,
        received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL,
        content_type VARCHAR NOT NULL, response_size_bytes BIGINT NOT NULL,
        response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL,
        license_class VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL UNIQUE)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS bitemporal_facts (
        id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, entity_id VARCHAR NOT NULL,
        security_id VARCHAR, fact_type VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL,
        published_at TIMESTAMP, available_at TIMESTAMP NOT NULL, ingested_at TIMESTAMP NOT NULL,
        revision INTEGER NOT NULL, normalized_payload VARCHAR NOT NULL,
        normalized_sha256 VARCHAR NOT NULL, source VARCHAR NOT NULL,
        source_version VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL,
        previous_fact_sha256 VARCHAR, fact_sha256 VARCHAR NOT NULL UNIQUE,
        UNIQUE(entity_id, fact_type, event_at, revision))"""
    )


def record_receipt(
    con: duckdb.DuckDBPyConnection, *, source: str, dataset: str, endpoint: str,
    request: dict, requested_at: datetime, received_at: datetime, http_status: int,
    content_type: str, body: bytes, license_class: str,
) -> dict:
    if not isinstance(body, bytes) or not body or len(body) > MAX_RAW_BYTES:
        raise FactError("source response body is invalid")
    requested, received = _utc(requested_at, "requested_at"), _utc(received_at, "received_at")
    if requested > received:
        raise FactError("source response times are inconsistent")
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
    response_sha = hashlib.sha256(body).hexdigest()
    identity = {
        "schema_version": SCHEMA_VERSION, "source": _text(source, "source"),
        "dataset": _text(dataset, "dataset"), "endpoint": _text(endpoint, "endpoint", 2048),
        "request_sha256": hashlib.sha256(request_json.encode()).hexdigest(),
        "requested_at": requested.isoformat(), "received_at": received.isoformat(),
        "http_status": int(http_status), "content_type": _text(content_type, "content_type"),
        "response_size_bytes": len(body), "response_sha256": response_sha,
        "license_class": _text(license_class, "license_class"),
    }
    receipt_sha = canonical_sha256(identity)
    existing = con.execute(
        "SELECT id,response_sha256 FROM source_response_receipts WHERE receipt_sha256=?",
        [receipt_sha],
    ).fetchone()
    if existing is not None:
        if existing[1] != response_sha:
            raise FactError("source receipt replay differs")
        return {**identity, "id": int(existing[0]), "receipt_sha256": receipt_sha, "replayed": True}
    receipt_id = int(con.execute(
        "SELECT COALESCE(MAX(id),0)+1 FROM source_response_receipts"
    ).fetchone()[0])
    con.execute(
        "INSERT INTO source_response_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [receipt_id, SCHEMA_VERSION, source, dataset, endpoint, request_json,
         identity["request_sha256"], requested, received, int(http_status), content_type,
         len(body), response_sha, body, license_class, receipt_sha],
    )
    return {**identity, "id": receipt_id, "receipt_sha256": receipt_sha, "replayed": False}


def record_fact(
    con: duckdb.DuckDBPyConnection, *, entity_id: str, security_id: str | None,
    fact_type: str, event_at: datetime, published_at: datetime | None,
    available_at: datetime, ingested_at: datetime, payload: dict, source: str,
    source_version: str, receipt_sha256: str,
) -> dict:
    event, available, ingested = (
        _utc(event_at, "event_at"), _utc(available_at, "available_at"),
        _utc(ingested_at, "ingested_at"),
    )
    published = None if published_at is None else _utc(published_at, "published_at")
    if event > available or (published is not None and (event > published or published > available)):
        raise FactError("fact event/publication/availability times are inconsistent")
    if available > ingested:
        raise FactError("fact availability is after ingestion")
    if con.execute(
        "SELECT 1 FROM source_response_receipts WHERE receipt_sha256=?", [receipt_sha256]
    ).fetchone() is None:
        raise FactError("fact source receipt is unavailable")
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    normalized_sha = canonical_sha256(payload)
    latest = con.execute(
        "SELECT revision,normalized_sha256,fact_sha256 FROM bitemporal_facts "
        "WHERE entity_id=? AND fact_type=? AND event_at=? ORDER BY revision DESC LIMIT 1",
        [entity_id, fact_type, event],
    ).fetchone()
    if latest is not None and latest[1] == normalized_sha:
        return {"fact_sha256": latest[2], "revision": int(latest[0]), "replayed": True}
    revision = 1 if latest is None else int(latest[0]) + 1
    previous = None if latest is None else latest[2]
    identity = {
        "schema_version": SCHEMA_VERSION, "entity_id": _text(entity_id, "entity_id"),
        "security_id": security_id, "fact_type": _text(fact_type, "fact_type"),
        "event_at": event.isoformat(), "published_at": None if published is None else published.isoformat(),
        "available_at": available.isoformat(), "ingested_at": ingested.isoformat(),
        "revision": revision, "normalized_sha256": normalized_sha,
        "source": _text(source, "source"), "source_version": _text(source_version, "source_version"),
        "receipt_sha256": receipt_sha256, "previous_fact_sha256": previous,
    }
    fact_sha = canonical_sha256(identity)
    fact_id = int(con.execute("SELECT COALESCE(MAX(id),0)+1 FROM bitemporal_facts").fetchone()[0])
    con.execute(
        "INSERT INTO bitemporal_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [fact_id, SCHEMA_VERSION, entity_id, security_id, fact_type, event, published, available,
         ingested, revision, normalized, normalized_sha, source, source_version, receipt_sha256,
         previous, fact_sha],
    )
    return {"fact_sha256": fact_sha, "revision": revision, "replayed": False}


def record_intraday_quote_batch(
    con: duckdb.DuckDBPyConnection, *, source: str, endpoint: str, request: dict,
    requested_at: datetime, received_at: datetime, content_type: str, body: bytes,
    quotes: list[dict], source_version: str, license_class: str,
) -> dict:
    """Atomically retain one raw response and normalized quote facts."""
    seen = set()
    for quote in quotes:
        if not isinstance(quote, dict) or set(quote) != {
            "ticker", "event_at", "open", "high", "low", "close", "volume"
        }:
            raise FactError("intraday quote shape is invalid")
        ticker, event_at = quote["ticker"], quote["event_at"]
        if not isinstance(ticker, str) or (ticker, event_at) in seen:
            raise FactError("intraday quote identity is invalid or duplicated")
        seen.add((ticker, event_at))
    with engine_db.transaction(con):
        receipt = record_receipt(
            con, source=source, dataset="intraday_quote", endpoint=endpoint,
            request=request, requested_at=requested_at, received_at=received_at,
            http_status=200, content_type=content_type, body=body,
            license_class=license_class,
        )
        facts = []
        for quote in quotes:
            facts.append(record_fact(
                con, entity_id=quote["ticker"], security_id=quote["ticker"],
                fact_type="intraday.ohlcv", event_at=quote["event_at"], published_at=None,
                available_at=received_at, ingested_at=received_at,
                payload={key: quote[key] for key in ("open", "high", "low", "close", "volume")},
                source=source, source_version=source_version,
                receipt_sha256=receipt["receipt_sha256"],
            ))
    return {"receipt_sha256": receipt["receipt_sha256"], "fact_count": len(facts),
            "fact_sha256s": [item["fact_sha256"] for item in facts],
            "replayed": receipt["replayed"] and all(item["replayed"] for item in facts)}
