"""Admission and exact-response persistence for optional market-data sources."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import duckdb

from engine import bitemporal_facts
from engine.lib import db
from engine.lib.provenance import canonical_sha256

ALPACA = "alpaca_iex"
TRADINGVIEW = "tradingview_unofficial"
ALPACA_TERMS_ACCEPTANCE = "alpaca-market-data-terms-reviewed-2026-09-24"

SOURCES = {
    ALPACA: {
        "provider": "Alpaca", "product": "Market Data API Basic / IEX",
        "venue_scope": "IEX single-exchange", "consolidated": False,
        "delay_class": "provider-reported realtime",
        "credential_envs": ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
        "terms_env": "TRADING_ENGINE_ALPACA_DATA_TERMS_ACCEPTED",
        "terms_acceptance": ALPACA_TERMS_ACCEPTANCE,
        "terms_url": "https://alpaca.markets/disclosures",
        "license_class": "account-terms-internal-nondisplay-research",
        "realtime_authority": "research_cross_check_only",
        "historical_authority": "retrieval_time_staging_only",
    },
    TRADINGVIEW: {
        "provider": "TradingView via Mathieu2301/TradingView-API",
        "product": "anonymous websocket quote/chart protocol",
        "venue_scope": "resolved-provider-dependent",
        "consolidated": False, "delay_class": "anonymous-entitlement-dependent",
        "credential_envs": (), "terms_env": None, "terms_acceptance": None,
        "terms_url": "https://www.tradingview.com/policies/",
        "license_class": "owner-asserted-nondisplay-rights-internal-research",
        "realtime_authority": "research_cross_check_only",
        "historical_authority": "retrieval_time_research_only",
    },
}


INSERT_ROWS_PER_STATEMENT = 500
_FACT_VALUES = "(" + ",".join("?" * 17) + ")"


class MarketDataError(ValueError):
    """A source is not admitted or its observation cannot be retained safely."""


@dataclass(frozen=True)
class SourceResponse:
    body: bytes
    content_type: str
    status_code: int
    requested_at: datetime
    received_at: datetime


def source_status(source_id: str, environ: Mapping[str, str] | None = None) -> dict:
    if source_id not in SOURCES:
        raise MarketDataError("market-data source is not registered")
    policy = SOURCES[source_id]
    public = {key: value for key, value in policy.items() if key != "credential_envs"}
    public.update(source_id=source_id, execution_authority="none",
                  operational_price_mutation=False, raw_redistribution=False)
    if policy.get("blocked_reason"):
        return {**public, "status": "blocked", "reason": policy["blocked_reason"]}
    values = os.environ if environ is None else environ
    if policy["terms_env"] is not None and values.get(policy["terms_env"]) != policy["terms_acceptance"]:
        return {**public, "status": "unavailable",
                "reason": "provider data terms have not been explicitly accepted"}
    missing = [name for name in policy["credential_envs"] if not values.get(name)]
    if missing:
        return {**public, "status": "unavailable",
                "reason": "provider credentials are unavailable"}
    return {**public, "status": "admitted", "reason": None}


def public_statuses(environ: Mapping[str, str] | None = None) -> list[dict]:
    return [source_status(source_id, environ) for source_id in sorted(SOURCES)]


def _require_admitted(source_id: str, environ: Mapping[str, str] | None) -> dict:
    status = source_status(source_id, environ)
    if status["status"] != "admitted":
        raise MarketDataError(f"{source_id} is {status['status']}: {status['reason']}")
    return status


def retain_response(
    con: duckdb.DuckDBPyConnection, *, source_id: str, dataset: str, endpoint: str,
    request: dict, response: SourceResponse, environ: Mapping[str, str] | None = None,
) -> dict:
    policy = _require_admitted(source_id, environ)
    database = con.execute("PRAGMA database_list").fetchone()[2]
    if database and database != ":memory:":
        path = Path(database)
        if (not path.is_file() or path.stat().st_uid != os.getuid()
                or stat.S_IMODE(path.stat().st_mode) != 0o600):
            raise MarketDataError("market-data database must be an owner-only regular file")
    bitemporal_facts.init_schema(con)
    with db.transaction(con):
        return bitemporal_facts.record_receipt(
            con, source=source_id, dataset=dataset, endpoint=endpoint, request=request,
            requested_at=response.requested_at, received_at=response.received_at,
            http_status=response.status_code,
            content_type=response.content_type or "application/octet-stream",
            body=response.body, license_class=policy["license_class"],
        )


def retain_observations(
    con: duckdb.DuckDBPyConnection, *, source_id: str, receipt_sha256: str,
    receipt_dataset: str, received_at: datetime, observations: list[dict],
    fact_type: str, source_version: str,
    environ: Mapping[str, str] | None = None, ingested_at: datetime | None = None,
) -> list[dict]:
    policy = _require_admitted(source_id, environ)
    receipt = con.execute(
        "SELECT source,dataset,received_at FROM source_response_receipts WHERE receipt_sha256=?",
        [receipt_sha256],
    ).fetchone()
    expected_received = received_at.astimezone(timezone.utc).replace(tzinfo=None)
    if receipt != (source_id, receipt_dataset, expected_received):
        raise MarketDataError("observation receipt source or dataset does not match")
    ingested = datetime.now(timezone.utc) if ingested_at is None else ingested_at
    with db.transaction(con):
        if _batchable(con, observations):
            return _retain_batch(con, policy, source_id, receipt_sha256, received_at,
                                 observations, fact_type, source_version, ingested)
        return [_retain_one(con, policy, source_id, receipt_sha256, received_at,
                            observation, fact_type, source_version, ingested)
                for observation in observations]


def _payload(policy: dict, source_id: str, observation: dict) -> dict:
    if not isinstance(observation, dict) or set(observation) != {"ticker", "event_at", "payload"}:
        raise MarketDataError("normalized market-data observation shape is invalid")
    return {**observation["payload"], "source_id": source_id,
            "venue_scope": policy["venue_scope"],
            "consolidated": policy["consolidated"],
            "execution_authority": "none"}


def _retain_one(con, policy, source_id, receipt_sha256, received_at, observation,
                fact_type, source_version, ingested) -> dict:
    """One observation through the per-row queries (inputs the batch cannot key)."""
    payload = _payload(policy, source_id, observation)
    prior = con.execute(
        "SELECT fact_sha256,revision FROM bitemporal_facts WHERE entity_id=? "
        "AND fact_type=? AND event_at=? AND normalized_sha256=? AND source=? "
        "AND source_version=? AND receipt_sha256=? ORDER BY revision DESC LIMIT 1",
        [observation["ticker"], fact_type, observation["event_at"],
         canonical_sha256(payload), source_id, source_version, receipt_sha256],
    ).fetchone()
    if prior is not None:
        return {"fact_sha256": prior[0], "revision": int(prior[1]), "replayed": True}
    return bitemporal_facts.record_fact(
        con, entity_id=observation["ticker"], security_id=observation["ticker"],
        fact_type=fact_type, event_at=observation["event_at"], published_at=None,
        available_at=received_at, ingested_at=ingested, payload=payload,
        source=source_id, source_version=source_version, receipt_sha256=receipt_sha256,
    )


def _batchable(con: duckdb.DuckDBPyConnection, observations: list) -> bool:
    """True when every lookup key is a string ticker and an aware datetime on a UTC session,
    so prefetched rows compare exactly as the per-row parameters do."""
    return bool(observations) and all(
        isinstance(item, dict) and isinstance(item.get("ticker"), str)
        and type(item.get("event_at")) is datetime and item["event_at"].utcoffset() is not None
        for item in observations
    ) and con.execute("SELECT current_setting('TimeZone')").fetchone()[0] == "UTC"


def _retain_batch(con, policy, source_id, receipt_sha256, received_at, observations,
                  fact_type, source_version, ingested) -> list[dict]:
    """``_retain_one`` for each observation in order, with two lookups and one insert.

    Prior and latest revisions are read once for the batch's tickers and event range,
    then updated as each new revision is assigned, so every observation sees exactly
    the rows its per-row queries would have seen. Ids stay ``MAX(id)+1`` in order.
    """
    keyed = [item["event_at"].astimezone(timezone.utc).replace(tzinfo=None)
             for item in observations]
    tickers = sorted({item["ticker"] for item in observations})
    marks = ",".join("?" for _ in tickers)
    prior = {
        (row[0], row[1], row[2]): (row[4], int(row[3]))
        for row in con.execute(
            "SELECT entity_id,event_at,normalized_sha256,revision,fact_sha256 "
            "FROM bitemporal_facts WHERE fact_type=? AND source=? AND source_version=? "
            f"AND receipt_sha256=? AND entity_id IN ({marks}) "
            "QUALIFY revision=MAX(revision) OVER (PARTITION BY entity_id,event_at,normalized_sha256)",
            [fact_type, source_id, source_version, receipt_sha256, *tickers],
        ).fetchall()
    }
    latest = {
        (row[0], row[1]): (int(row[2]), row[3], row[4])
        for row in con.execute(
            "SELECT entity_id,event_at,revision,normalized_sha256,fact_sha256 "
            f"FROM bitemporal_facts WHERE fact_type=? AND entity_id IN ({marks}) "
            "AND event_at>=? AND event_at<=? "
            "QUALIFY revision=MAX(revision) OVER (PARTITION BY entity_id,event_at)",
            [fact_type, *tickers, min(keyed), max(keyed)],
        ).fetchall()
    }
    receipt_checked, next_id, rows, retained = False, None, [], []
    for observation, event_key in zip(observations, keyed, strict=True):
        payload = _payload(policy, source_id, observation)
        ticker, normalized_sha = observation["ticker"], canonical_sha256(payload)
        found = prior.get((ticker, event_key, normalized_sha))
        if found is not None:
            retained.append({"fact_sha256": found[0], "revision": found[1], "replayed": True})
            continue
        event, published, available, ingested_time = bitemporal_facts.validated_fact_times(
            entity_id=ticker, fact_type=fact_type, source=source_id,
            source_version=source_version, event_at=observation["event_at"],
            published_at=None, available_at=received_at, ingested_at=ingested,
        )
        if not receipt_checked:
            bitemporal_facts.require_receipt(con, receipt_sha256)
            receipt_checked = True
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        current = latest.get((ticker, event))
        if current is not None and current[1] == normalized_sha:
            retained.append({"fact_sha256": current[2], "revision": current[0],
                             "replayed": True})
            continue
        revision = 1 if current is None else current[0] + 1
        if next_id is None:
            next_id = int(con.execute(
                "SELECT COALESCE(MAX(id),0)+1 FROM bitemporal_facts").fetchone()[0])
        row = bitemporal_facts.fact_row(
            fact_id=next_id + len(rows), entity_id=ticker, security_id=ticker,
            fact_type=fact_type, event=event, published=published, available=available,
            ingested=ingested_time, revision=revision, normalized=normalized,
            normalized_sha=normalized_sha, source=source_id, source_version=source_version,
            receipt_sha256=receipt_sha256, previous=None if current is None else current[2],
        )
        rows.append(row)
        latest[(ticker, event)] = (revision, normalized_sha, row[-1])
        prior[(ticker, event, normalized_sha)] = (row[-1], revision)
        retained.append({"fact_sha256": row[-1], "revision": revision, "replayed": False})
    for first in range(0, len(rows), INSERT_ROWS_PER_STATEMENT):
        part = rows[first:first + INSERT_ROWS_PER_STATEMENT]
        # One multi-row VALUES statement; executemany binds and runs each row separately.
        con.execute("INSERT INTO bitemporal_facts VALUES " + ",".join([_FACT_VALUES] * len(part)),
                    [value for row in part for value in row])
    return retained


def evidence(observation: dict, receipt_sha256: str, status: dict) -> dict:
    body = {**observation["payload"], "ticker": observation["ticker"],
            "event_at": observation["event_at"].astimezone(timezone.utc).isoformat(),
            "received_at": observation["received_at"].astimezone(timezone.utc).isoformat(),
            "source_id": status["source_id"], "product": status["product"],
            "venue_scope": status["venue_scope"], "consolidated": status["consolidated"],
            "delay_class": status["delay_class"], "receipt_sha256": receipt_sha256,
            "research_only": True, "execution_authority": "none"}
    return {**body, "evidence_id": canonical_sha256(body)}
