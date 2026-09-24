"""Admission and exact-response persistence for optional market-data sources."""
from __future__ import annotations

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
        "product": "unofficial websocket protocol", "venue_scope": "provider-dependent",
        "consolidated": False, "delay_class": "entitlement-dependent",
        "credential_envs": (), "terms_env": None,
        "terms_url": "https://www.tradingview.com/policies/",
        "license_class": "not-admitted-for-nondisplay",
        "realtime_authority": "none", "historical_authority": "none",
        "blocked_reason": "current terms prohibit automated non-display market-data use",
    },
}


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
    if values.get(policy["terms_env"]) != policy["terms_acceptance"]:
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
    retained = []
    with db.transaction(con):
        for observation in observations:
            if set(observation) != {"ticker", "event_at", "payload"}:
                raise MarketDataError("normalized market-data observation shape is invalid")
            payload = {**observation["payload"], "source_id": source_id,
                       "venue_scope": policy["venue_scope"],
                       "consolidated": policy["consolidated"],
                       "execution_authority": "none"}
            prior = con.execute(
                "SELECT fact_sha256,revision FROM bitemporal_facts WHERE entity_id=? "
                "AND fact_type=? AND event_at=? AND normalized_sha256=? AND source=? "
                "AND source_version=? AND receipt_sha256=? ORDER BY revision DESC LIMIT 1",
                [observation["ticker"], fact_type, observation["event_at"],
                 canonical_sha256(payload), source_id, source_version, receipt_sha256],
            ).fetchone()
            if prior is not None:
                retained.append({"fact_sha256": prior[0], "revision": int(prior[1]),
                                 "replayed": True})
                continue
            retained.append(bitemporal_facts.record_fact(
                con, entity_id=observation["ticker"], security_id=observation["ticker"],
                fact_type=fact_type, event_at=observation["event_at"], published_at=None,
                available_at=received_at, ingested_at=ingested, payload=payload,
                source=source_id, source_version=source_version, receipt_sha256=receipt_sha256,
            ))
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
