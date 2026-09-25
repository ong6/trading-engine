"""Credential-gated Alpaca IEX quote and historical-bar source."""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode

import requests

from engine.lib import db
from engine.lib.settings import DEFAULT_DB

from . import market_data_sources, tradingview_source

SOURCE_ID = market_data_sources.ALPACA
SOURCE_VERSION = "alpaca_market_data_v2"
ENDPOINT = "https://data.alpaca.markets/v2/stocks"
MAX_RESPONSE_BYTES = 2_000_000
MAX_REALTIME_AGE = timedelta(minutes=15)
MAX_HISTORY_DAYS = 366
SYMBOL = re.compile(r"^[A-Z0-9.-]{1,16}$")
VENUE = re.compile(r"^[A-Za-z0-9._-]{1,16}$")
MAX_PRICE = 100_000_000.0


class OfficialSourceError(ValueError):
    """The official source response is unavailable or invalid."""


def _symbol(value: str) -> str:
    if not isinstance(value, str) or SYMBOL.fullmatch(value) is None:
        raise OfficialSourceError("Alpaca symbol is invalid")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise OfficialSourceError("Alpaca timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfficialSourceError("Alpaca timestamp is invalid") from exc
    if parsed.utcoffset() is None:
        raise OfficialSourceError("Alpaca timestamp is invalid")
    return parsed.astimezone(timezone.utc)


def _number(value: object, field: str, *, positive: bool = True, maximum: float = MAX_PRICE) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OfficialSourceError(f"Alpaca {field} is invalid")
    result = float(value)
    if not math.isfinite(result) or result > maximum or (positive and result <= 0):
        raise OfficialSourceError(f"Alpaca {field} is invalid")
    return result


def _request(path: str, query: dict, environ: Mapping[str, str] | None = None):
    values = os.environ if environ is None else environ
    market_data_sources._require_admitted(SOURCE_ID, values)
    requested_at = datetime.now(timezone.utc)
    try:
        response = requests.get(
            f"{ENDPOINT}/{path}", params=query, timeout=20, stream=True,
            allow_redirects=False, headers={
                "APCA-API-KEY-ID": values["APCA_API_KEY_ID"],
                "APCA-API-SECRET-KEY": values["APCA_API_SECRET_KEY"],
                "User-Agent": "trading-engine-research/1"},
        )
        declared = response.headers.get("content-length")
        if declared is not None and int(declared) > MAX_RESPONSE_BYTES:
            raise OfficialSourceError("Alpaca response size is invalid")
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise OfficialSourceError("Alpaca response size is invalid")
    except (OSError, requests.RequestException, ValueError) as exc:
        if isinstance(exc, OfficialSourceError):
            raise
        raise OfficialSourceError("Alpaca request failed") from exc
    received_at = datetime.now(timezone.utc)
    return market_data_sources.SourceResponse(
        body=bytes(body), content_type=response.headers.get("content-type", ""),
        status_code=int(response.status_code), requested_at=requested_at, received_at=received_at,
    )


def realtime_request(symbol: str) -> tuple[str, dict]:
    symbol = _symbol(symbol)
    query = {"symbols": symbol, "feed": "iex"}
    return f"{ENDPOINT}/snapshots?{urlencode(query)}", query


def history_request(symbol: str, start: date, end: date) -> tuple[str, dict]:
    symbol = _symbol(symbol)
    if not isinstance(start, date) or not isinstance(end, date) or not start <= end:
        raise OfficialSourceError("historical range is invalid")
    if (end - start).days > MAX_HISTORY_DAYS:
        raise OfficialSourceError("historical range exceeds the bounded capture window")
    query = {"timeframe": "1Day", "start": start.isoformat(),
             "end": end.isoformat(), "feed": "iex",
             "adjustment": "raw", "limit": 1000}
    return f"{ENDPOINT}/{symbol}/bars?{urlencode(query)}", query


def _payload(response: market_data_sources.SourceResponse) -> dict:
    if (response.status_code != 200
            or response.content_type.split(";", 1)[0].lower() != "application/json"
            or not response.body or len(response.body) > MAX_RESPONSE_BYTES):
        raise OfficialSourceError("Alpaca response metadata is invalid")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise OfficialSourceError("Alpaca response JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise OfficialSourceError("Alpaca response shape is invalid")
    return payload


def parse_realtime(symbol: str, response: market_data_sources.SourceResponse) -> dict:
    symbol = _symbol(symbol)
    try:
        snapshot = _payload(response)["snapshots"][symbol]
        trade, quote = snapshot["latestTrade"], snapshot["latestQuote"]
        event_at = _timestamp(trade["t"])
        quote_at = _timestamp(quote["t"])
        price, bid, ask = (_number(trade["p"], "trade price"),
                           _number(quote["bp"], "bid"), _number(quote["ap"], "ask"))
        venue, bid_venue, ask_venue = trade["x"], quote["bx"], quote["ax"]
    except (KeyError, TypeError) as exc:
        raise OfficialSourceError("Alpaca realtime response shape is invalid") from exc
    received = response.received_at.astimezone(timezone.utc)
    if (max(event_at, quote_at) > received
            or received - min(event_at, quote_at) > MAX_REALTIME_AGE):
        raise OfficialSourceError("Alpaca realtime quote is stale or future-dated")
    if (bid > ask or ask / bid > 2
            or any(not isinstance(item, str) or VENUE.fullmatch(item) is None
                   for item in (venue, bid_venue, ask_venue))):
        raise OfficialSourceError("Alpaca realtime venue or spread is invalid")
    return {"ticker": symbol, "event_at": event_at, "received_at": received,
            "payload": {"price": price, "bid": bid, "ask": ask,
                        "quote_at": quote_at.isoformat(),
                        "trade_age_ms": (received - event_at).total_seconds() * 1000,
                        "quote_age_ms": (received - quote_at).total_seconds() * 1000,
                        "trade_venue_code": venue,
                        "quote_venue_codes": f"{bid_venue}:{ask_venue}",
                        "feed": "iex"}}


def parse_history(symbol: str, start: date, end: date,
                  response: market_data_sources.SourceResponse) -> list[dict]:
    symbol = _symbol(symbol)
    payload = _payload(response)
    if payload.get("symbol") != symbol or payload.get("next_page_token") is not None:
        raise OfficialSourceError("Alpaca historical response is incomplete or mismatched")
    bars = payload.get("bars")
    if not isinstance(bars, list) or len(bars) > 1000:
        raise OfficialSourceError("Alpaca historical bars are invalid")
    result, seen = [], set()
    for bar in bars:
        try:
            event_at = _timestamp(bar["t"])
            o = _number(bar["o"], "open")
            h = _number(bar["h"], "high")
            low = _number(bar["l"], "low")
            close = _number(bar["c"], "close")
            volume = _number(bar["v"], "volume", positive=False, maximum=10**15)
        except (KeyError, TypeError) as exc:
            raise OfficialSourceError("Alpaca historical bar shape is invalid") from exc
        if (event_at in seen or event_at > response.received_at.astimezone(timezone.utc)
                or not start <= event_at.date() <= end):
            raise OfficialSourceError("Alpaca historical timestamp is invalid")
        if low > min(o, h, close) or h < max(o, low, close) or volume < 0:
            raise OfficialSourceError("Alpaca historical OHLCV is invalid")
        seen.add(event_at)
        result.append({"ticker": symbol, "event_at": event_at,
                       "payload": {"open": o, "high": h, "low": low,
                                   "close": close, "volume": volume,
                                   "feed": "iex", "adjustment": "raw",
                                   "historical_authority": "retrieval_time_staging_only"}})
    return result


def capture_realtime(symbol: str, *, database: Path = DEFAULT_DB, observed_at: datetime | None = None,
                     fetch: Callable | None = None, environ: Mapping[str, str] | None = None) -> dict:
    status = market_data_sources.source_status(SOURCE_ID, environ)
    if status["status"] != "admitted":
        return status
    endpoint, request = realtime_request(symbol)
    response = (fetch or (lambda s, n: _request("snapshots", request, environ)))(
        symbol, observed_at or datetime.now(timezone.utc))
    con = db.connect(database, wait_s=0)
    try:
        receipt = market_data_sources.retain_response(
            con, source_id=SOURCE_ID, dataset="realtime_snapshot", endpoint=endpoint,
            request=request, response=response, environ=environ)
        observation = parse_realtime(symbol, response)
        market_data_sources.retain_observations(
            con, source_id=SOURCE_ID, receipt_sha256=receipt["receipt_sha256"],
            receipt_dataset="realtime_snapshot", received_at=response.received_at,
            observations=[{k: observation[k] for k in
            ("ticker", "event_at", "payload")}], fact_type="market.quote.realtime",
            source_version=SOURCE_VERSION, environ=environ)
    finally:
        con.close()
    return {**status, "status": "complete", "observation":
            market_data_sources.evidence(observation, receipt["receipt_sha256"], status)}


def capture_realtime_many(symbols: list[str], *, database: Path = DEFAULT_DB,
                          observed_at: datetime | None = None, fetch: Callable | None = None,
                          environ=None) -> list[dict]:
    """Capture up to five symbols with one official snapshot request."""
    status = market_data_sources.source_status(SOURCE_ID, environ)
    if status["status"] != "admitted":
        return []
    symbols = [_symbol(item) for item in symbols[:5]]
    if not symbols:
        return []
    request = {"symbols": ",".join(symbols), "feed": "iex"}
    endpoint = f"{ENDPOINT}/snapshots?{urlencode(request)}"
    response = (fetch or (lambda items, now: _request("snapshots", request, environ)))(
        symbols, observed_at or datetime.now(timezone.utc))
    con = db.connect(database, wait_s=0)
    try:
        receipt = market_data_sources.retain_response(
            con, source_id=SOURCE_ID, dataset="realtime_snapshot", endpoint=endpoint,
            request=request, response=response, environ=environ)
        observations = [parse_realtime(symbol, response) for symbol in symbols]
        market_data_sources.retain_observations(
            con, source_id=SOURCE_ID, receipt_sha256=receipt["receipt_sha256"],
            receipt_dataset="realtime_snapshot", received_at=response.received_at,
            observations=[{k: item[k] for k in
            ("ticker", "event_at", "payload")} for item in observations],
            fact_type="market.quote.realtime", source_version=SOURCE_VERSION, environ=environ)
    finally:
        con.close()
    return [market_data_sources.evidence(item, receipt["receipt_sha256"], status)
            for item in observations]


def capture_history(symbol: str, start: date, end: date, *, database: Path = DEFAULT_DB,
                    fetch: Callable | None = None, environ: Mapping[str, str] | None = None) -> dict:
    status = market_data_sources.source_status(SOURCE_ID, environ)
    if status["status"] != "admitted":
        return status
    endpoint, request = history_request(symbol, start, end)
    response = (fetch or (lambda s, a, b: _request(f"{s}/bars", request, environ)))(
        symbol, start, end)
    con = db.connect(database, wait_s=0)
    try:
        receipt = market_data_sources.retain_response(
            con, source_id=SOURCE_ID, dataset="historical_daily_bars", endpoint=endpoint,
            request=request, response=response, environ=environ)
        observations = parse_history(symbol, start, end, response)
        facts = market_data_sources.retain_observations(
            con, source_id=SOURCE_ID, receipt_sha256=receipt["receipt_sha256"],
            receipt_dataset="historical_daily_bars", received_at=response.received_at,
            observations=observations,
            fact_type="market.ohlcv.1d.retrieved", source_version=SOURCE_VERSION, environ=environ)
    finally:
        con.close()
    return {**status, "status": "complete", "receipt_sha256": receipt["receipt_sha256"],
            "fact_count": len(facts), "historical_authority": "retrieval_time_staging_only"}


def capture_tradingview_realtime(
    provider_symbol: str, *, database: Path = DEFAULT_DB, observed_at: datetime | None = None,
    fetch: tradingview_source.Fetch = tradingview_source._fetch,
) -> dict:
    status = market_data_sources.source_status(market_data_sources.TRADINGVIEW)
    transcript = fetch(provider_symbol, mode="realtime")
    response = market_data_sources.SourceResponse(
        transcript.body, "application/json", 200,
        transcript.requested_at, transcript.received_at)
    request = {"provider_symbol": provider_symbol, "mode": "realtime",
               "protocol_version": tradingview_source.SOURCE_VERSION}
    con = db.connect(database, wait_s=0)
    try:
        receipt = market_data_sources.retain_response(
            con, source_id=market_data_sources.TRADINGVIEW, dataset="realtime_snapshot",
            endpoint=tradingview_source.ENDPOINT, request=request, response=response)
        observation = tradingview_source.parse_realtime(provider_symbol, transcript)
        market_data_sources.retain_observations(
            con, source_id=market_data_sources.TRADINGVIEW,
            receipt_sha256=receipt["receipt_sha256"], receipt_dataset="realtime_snapshot",
            received_at=transcript.received_at, observations=[{k: observation[k] for k in
            ("ticker", "event_at", "payload")}], fact_type="market.quote.realtime",
            source_version=tradingview_source.SOURCE_VERSION)
    finally:
        con.close()
    return {**status, "status": "complete", "observation":
            market_data_sources.evidence(observation, receipt["receipt_sha256"], status)}


def capture_tradingview_many(
    symbols: list[str], *, database: Path = DEFAULT_DB, observed_at: datetime | None = None,
) -> list[dict]:
    observations = [capture_tradingview_realtime(
        symbol, database=database, observed_at=observed_at)["observation"]
        for symbol in symbols[:5]]
    return [item for item in observations if item.get("fresh") is True]


def capture_tradingview_history(
    provider_symbol: str, start: date, end: date, *, database: Path = DEFAULT_DB,
    fetch: tradingview_source.Fetch = tradingview_source._fetch,
) -> dict:
    if not isinstance(start, date) or not isinstance(end, date) or not start <= end:
        raise OfficialSourceError("TradingView historical range is invalid")
    if (end - start).days > tradingview_source.MAX_HISTORY_DAYS:
        raise OfficialSourceError("TradingView historical range exceeds the bounded window")
    trading_days = (end - start).days + 10
    bars = min(tradingview_source.MAX_HISTORY_BARS, max(10, trading_days))
    reference = int(datetime.combine(end + timedelta(days=1), datetime.min.time(),
                                     timezone.utc).timestamp())
    transcript = fetch(provider_symbol, mode="history", bars=bars, reference=reference)
    response = market_data_sources.SourceResponse(
        transcript.body, "application/json", 200,
        transcript.requested_at, transcript.received_at)
    request = {"provider_symbol": provider_symbol, "mode": "history",
               "start": start.isoformat(), "end": end.isoformat(), "bars": bars,
               "reference": reference,
               "timeframe": "1D", "adjustment": "splits",
               "protocol_version": tradingview_source.SOURCE_VERSION}
    con = db.connect(database, wait_s=0)
    try:
        receipt = market_data_sources.retain_response(
            con, source_id=market_data_sources.TRADINGVIEW, dataset="historical_daily_bars",
            endpoint=tradingview_source.ENDPOINT, request=request, response=response)
        try:
            observations = tradingview_source.parse_history(provider_symbol, start, end, transcript)
        except tradingview_source.TradingViewSourceError as exc:
            if str(exc) != "TradingView history range has no bars":
                raise
            observations = []
        facts = market_data_sources.retain_observations(
            con, source_id=market_data_sources.TRADINGVIEW,
            receipt_sha256=receipt["receipt_sha256"], receipt_dataset="historical_daily_bars",
            received_at=transcript.received_at, observations=observations,
            fact_type="market.ohlcv.1d.retrieved",
            source_version=tradingview_source.SOURCE_VERSION)
    finally:
        con.close()
    return {"status": "complete" if facts else "empty",
            "source_id": market_data_sources.TRADINGVIEW,
            "receipt_sha256": receipt["receipt_sha256"], "fact_count": len(facts),
            "historical_authority": "retrieval_time_research_only"}
