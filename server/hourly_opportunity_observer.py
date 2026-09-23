"""Bounded hourly/four-hour P9 quote and headline observations; never trades."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import duckdb

from engine import bitemporal_facts
from engine.lib import db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from . import (
    agent_evaluation,
    agent_model_client,
    daily_opportunity_news,
    intraday_source,
)
from .daily_opportunity_runner import _model_input, _validate_output
from .file_utils import read_bytes

REGISTRATION = REPO_ROOT / "server" / "agent-cadence-registration.json"
MAX_QUOTES = 5
LOCK_PATH = REPO_ROOT / ".hourly-opportunity.lock"


def _variants() -> dict[str, dict]:
    payload = json.loads(read_bytes(REGISTRATION, label="agent cadence registration"))
    return {item["id"]: item for item in payload["variants"]}


def _capture_quotes(
    tickers: list[tuple[str, str]], *, database: Path, observed_at: datetime,
    fetch=intraday_source._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[list[dict], list[dict]]:
    """Retain exact responses before admitting bounded quotes to a prompt."""
    quotes, failures = [], []
    for ticker, provider_ticker in tickers[:MAX_QUOTES]:
        try:
            request = intraday_source.request_identity(provider_ticker)
            endpoint = intraday_source.endpoint_url(provider_ticker)
            response = fetch(provider_ticker, observed_at)
            try:
                bars = intraday_source.parse(ticker, provider_ticker, response)
            except intraday_source.IntradaySourceError as exc:
                write_con = db.connect(database, wait_s=0)
                try:
                    bitemporal_facts.init_schema(write_con)
                    receipt = bitemporal_facts.record_receipt(
                        write_con, source="yfinance", dataset="intraday_quote",
                        endpoint=endpoint, request=request, requested_at=response.requested_at,
                        received_at=response.received_at, http_status=response.status_code,
                        content_type=response.content_type or "application/octet-stream",
                        body=response.body, license_class="provider-terms-research",
                    )
                finally:
                    write_con.close()
                failures.append({"ticker": ticker, "reason": str(exc)[:200],
                                 "receipt_sha256": receipt["receipt_sha256"]})
                continue
            write_con = db.connect(database, wait_s=0)
            try:
                bitemporal_facts.init_schema(write_con)
                retained = bitemporal_facts.record_intraday_quote_batch(
                    write_con, source="yfinance", endpoint=endpoint,
                    request=request, requested_at=response.requested_at,
                    received_at=response.received_at, content_type=response.content_type,
                    body=response.body, quotes=bars,
                    interval=intraday_source.INTERVAL,
                    source_version=intraday_source.source_version(),
                    license_class="provider-terms-research",
                    ingested_at=clock(),
                )
            finally:
                write_con.close()
            bars = sorted(bars, key=lambda item: item["event_at"])
            if len(bars) < 2:
                failures.append({
                    "ticker": ticker,
                    "reason": "intraday response has fewer than two usable bars",
                    "receipt_sha256": retained["receipt_sha256"],
                })
                continue
            last, prior = bars[-1], bars[-2]
            body = {
                "ticker": ticker, "observed_at": response.received_at.isoformat(),
                "event_at": last["event_at"].isoformat(), "last": last["close"],
                "change_5m": last["close"] / prior["close"] - 1,
                "last_volume": last["volume"],
                "receipt_sha256": retained["receipt_sha256"],
            }
            quotes.append({**body, "evidence_id": canonical_sha256(body)})
        except (
            intraday_source.IntradaySourceError, bitemporal_facts.FactError,
            db.DBBusyError, duckdb.Error, OSError, ValueError,
        ) as exc:
            failures.append({"ticker": ticker, "reason": str(exc)[:200]})
    return quotes, failures


def _observe(
    variant_id: str, *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate=agent_model_client.generate_opportunity_json, fetch_news=daily_opportunity_news._fetch,
    fetch_quote=intraday_source._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    variant = _variants().get(variant_id)
    if variant is None or variant["execution_authority"] != "none":
        raise ValueError("observation variant is invalid")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    target = REPO_ROOT / "logs" / f"{variant_id}.jsonl"
    window_hour = observed.hour if variant["cadence"] == "hourly" else observed.hour // 4 * 4
    window = f"{observed.date().isoformat()}T{window_hour:02d}"
    existing = target.read_text().splitlines() if target.exists() else []
    prior = next((json.loads(line) for line in existing if json.loads(line).get("window") == window), None)
    if prior is not None:
        write_con = db.connect(database, wait_s=0)
        try:
            with db.transaction(write_con):
                agent_evaluation.init_schema(write_con)
                trace = agent_evaluation.replay_artifact_trace(
                    prior, source_identifier=f"{target.name}:{window}"
                )
                agent_evaluation.record_trace(write_con, trace)
                agent_evaluation.label_mature(
                    write_con, labeled_at=clock()
                )
        finally:
            write_con.close()
        return {"status": "completed", "variant_id": variant_id,
                "quote_count": len(prior["quotes"]),
                "headline_count": len(prior["headlines"]),
                "assessment_count": len(prior["assessments"]),
                "execution_authority": "none", "replayed": True,
                "artifact_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    con = db.connect(database, read_only=True, wait_s=0)
    try:
        market_date = db.latest_operational_market_date(con)
        if market_date is None:
            raise ValueError("no breadth-qualified market date")
        from engine.daily_opportunities import detect

        bundle = detect(con, market_date, limit=variant["candidate_limit"])
        tickers = [item["ticker"] for item in bundle["candidates"]]
        provider_tickers = dict(con.execute(
            "SELECT ticker,COALESCE(NULLIF(yf_ticker,''),ticker) FROM universe "
            f"WHERE ticker IN ({','.join(['?'] * len(tickers))})", tickers,
        ).fetchall()) if tickers else {}
    finally:
        con.close()
    quotes, quote_failures = _capture_quotes(
        [(ticker, provider_tickers.get(ticker, ticker)) for ticker in tickers],
        database=database, observed_at=observed, fetch=fetch_quote, clock=clock,
    )
    news = daily_opportunity_news.capture(["SPY", *tickers], now=observed, fetch=fetch_news)
    for candidate in bundle["candidates"]:
        quote = next((item for item in quotes if item["ticker"] == candidate["ticker"]), None)
        candidate["intraday_observation"] = quote
    model_input, allowed = _model_input(bundle, news, [])
    for ticker, values in allowed.items():
        quote = next((item for item in quotes if item["ticker"] == ticker), None)
        if quote is not None:
            values.add(quote["evidence_id"])
    model_input["task"] = variant["prompt_role"]
    model_input["variant_id"] = variant_id
    model_input["execution_authority"] = "none"
    model_input["allowed_evidence_ids"] = sorted(set().union(*allowed.values()) if allowed else set())
    information_cutoff_at = clock()
    generation_started = time.monotonic()
    response = generate(model_input)
    latency_ms = (time.monotonic() - generation_started) * 1000
    assessments = _validate_output(response.output, bundle, allowed, set())
    artifact = {
        "schema_version": 1, "variant_id": variant_id, "cadence": variant["cadence"],
        "prompt_role": variant["prompt_role"], "observed_at": observed.isoformat(),
        "market_date": market_date.isoformat(), "quotes": quotes,
        "quote_failures": quote_failures,
        "news_status": news["status"], "headlines": news["observations"],
        "news_receipts": [
            {key: value for key, value in receipt.items() if key != "response_body"}
            | {"response_body_hex": receipt["response_body"].hex()}
            for receipt in news["receipts"]
        ],
        "assessments": assessments, "model": response.model,
        "model_version": response.model_version, "response_id": response.response_id,
        "usage": response.usage,
        "completed_at": clock().isoformat(),
        "information_cutoff_at": information_cutoff_at.isoformat(),
        "latency_ms": latency_ms,
        "model_input": model_input,
        "model_response": {
            "output": response.output, "response_id": response.response_id,
            "model": response.model, "model_version": response.model_version,
            "request_sha256": response.request_sha256,
            "instructions_sha256": agent_model_client.identity(role="opportunity")[
                "instructions_sha256"
            ],
            "toolset_sha256": agent_model_client.identity(role="opportunity")[
                "toolset_sha256"
            ],
            "model_catalog_entry_sha256": response.model_catalog_entry_sha256,
            "proxy_source_sha256": response.proxy_source_sha256,
            "traecli_runtime": response.traecli_runtime,
            "upstream_model_family": response.upstream_model_family,
            "upstream_request_id": response.upstream_request_id,
            "usage": response.usage,
        },
        "execution_authority": "none",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    artifact["window"] = window
    artifact["observation_sha256"] = canonical_sha256(artifact)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n")
    write_con = db.connect(database, wait_s=0)
    try:
        with db.transaction(write_con):
            agent_evaluation.init_schema(write_con)
            agent_evaluation.record_trace(
                write_con,
                agent_evaluation.artifact_trace(
                    artifact, source_identifier=f"{target.name}:{window}",
                    latency_ms=latency_ms,
                ),
            )
            agent_evaluation.label_mature(
                write_con, labeled_at=clock()
            )
    finally:
        write_con.close()
    return {"status": "completed", "variant_id": variant_id,
            "quote_count": len(quotes), "headline_count": len(news["observations"]),
            "assessment_count": len(assessments),
            "execution_authority": "none", "replayed": False,
            "artifact_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def observe(
    variant_id: str, *, database: Path = DEFAULT_DB, now: datetime | None = None,
    generate=agent_model_client.generate_opportunity_json, fetch_news=daily_opportunity_news._fetch,
    fetch_quote=intraday_source._fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    with advisory_file_lock(LOCK_PATH):
        return _observe(variant_id, database=database, now=now, generate=generate,
                        fetch_news=fetch_news, fetch_quote=fetch_quote, clock=clock)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant_id", choices=("hourly_market_watch_v1", "four_hour_opportunity_review_v1"))
    args = parser.parse_args()
    print(json.dumps(observe(args.variant_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
