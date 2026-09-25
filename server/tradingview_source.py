"""Anonymous TradingView WebSocket quote/chart adapter with exact transcripts."""
from __future__ import annotations

import json
import math
import re
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from . import market_data_sources

SOURCE_ID = market_data_sources.TRADINGVIEW
SOURCE_VERSION = "mathieu2301-protocol-5baea86c"
ENDPOINT = "wss://data.tradingview.com/socket.io/websocket?from=chart&type=chart"
ORIGIN = "https://www.tradingview.com"
MAX_TRANSCRIPT_BYTES = 2_000_000
MAX_HISTORY_BARS = 500
MAX_HISTORY_DAYS = 550
MAX_REALTIME_AGE = timedelta(minutes=15)
MAX_OBSERVATION_AGE = timedelta(days=4)
SYMBOL = re.compile(r"^[A-Z0-9._-]{1,24}:[A-Z0-9.-]{1,32}$")
VENUE = re.compile(r"^[A-Za-z0-9 ._/-]{1,64}$")


class TradingViewSourceError(ValueError):
    """A TradingView transcript or normalized observation is invalid."""


@dataclass(frozen=True)
class Transcript:
    body: bytes
    requested_at: datetime
    received_at: datetime


def _packet(method: str, params: list) -> str:
    payload = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def parse_frames(raw: str) -> list[dict | int]:
    frames = []
    position = 0
    while position < len(raw):
        if not raw.startswith("~m~", position):
            raise TradingViewSourceError("TradingView frame prefix is invalid")
        size_end = raw.find("~m~", position + 3)
        if size_end < 0:
            raise TradingViewSourceError("TradingView frame length is incomplete")
        try:
            size = int(raw[position + 3:size_end])
        except ValueError as exc:
            raise TradingViewSourceError("TradingView frame length is invalid") from exc
        start, end = size_end + 3, size_end + 3 + size
        if end > len(raw):
            raise TradingViewSourceError("TradingView frame payload is incomplete")
        value = raw[start:end]
        if value.startswith("~h~"):
            try:
                frames.append(int(value[3:]))
            except ValueError as exc:
                raise TradingViewSourceError("TradingView heartbeat is invalid") from exc
        else:
            try:
                packet = json.loads(value)
            except ValueError as exc:
                raise TradingViewSourceError("TradingView frame JSON is invalid") from exc
            if not isinstance(packet, dict):
                raise TradingViewSourceError("TradingView packet shape is invalid")
            frames.append(packet)
        position = end
    return frames


def _symbol(value: str) -> str:
    if not isinstance(value, str) or SYMBOL.fullmatch(value) is None:
        raise TradingViewSourceError("TradingView symbol is invalid")
    return value


def _number(value: object, field: str, *, zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TradingViewSourceError(f"TradingView {field} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not zero and result == 0) or result > 10**15:
        raise TradingViewSourceError(f"TradingView {field} is invalid")
    return result


def _commands(
    symbol: str, *, mode: str, bars: int = 0, reference: int | None = None,
) -> list[tuple[str, list]]:
    symbol = _symbol(symbol)
    session = ("qs_" if mode == "realtime" else "cs_") + secrets.token_hex(6)
    commands = [("set_auth_token", ["unauthorized_user_token"])]
    if mode == "realtime":
        key = "=" + json.dumps({"session": "regular", "symbol": symbol},
                                separators=(",", ":"))
        commands += [("quote_create_session", [session]),
                     ("quote_set_fields", [session, "lp", "lp_time", "bid", "ask",
                                             "volume", "exchange", "provider_id",
                                             "current_session", "status"]),
                     ("quote_add_symbols", [session, key])]
    else:
        resolved = "=" + json.dumps(
            {"symbol": symbol, "adjustment": "splits", "session": "regular"},
            separators=(",", ":"))
        count = bars if reference is None else ["bar_count", reference, bars]
        commands += [("chart_create_session", [session]),
                     ("resolve_symbol", [session, "ser_1", resolved]),
                     ("create_series", [session, "$prices", "s1", "ser_1", "D", count])]
    return commands


def _handle_packets(socket, transcript: dict, message: str, mode: str, transcript_bytes: int) -> tuple[int, bool]:
    done = False
    for packet in parse_frames(message):
        if isinstance(packet, int):
            value = f"~h~{packet}"
            heartbeat = f"~m~{len(value)}~m~{value}"
            transcript_bytes += len(heartbeat.encode())
            if transcript_bytes > MAX_TRANSCRIPT_BYTES:
                raise TradingViewSourceError("TradingView transcript is too large")
            socket.send(heartbeat)
            transcript["sent"].append(heartbeat)
        elif packet.get("m") == "protocol_error":
            raise TradingViewSourceError("TradingView protocol error")
        elif mode == "realtime" and packet.get("m") == "quote_completed":
            done = True
        elif mode == "history" and packet.get("m") == "series_completed":
            done = True
    return transcript_bytes, done


def _fetch(
    symbol: str, *, mode: str, bars: int = 0, reference: int | None = None,
    timeout: float = 15.0,
) -> Transcript:
    commands = _commands(symbol, mode=mode, bars=bars, reference=reference)
    requested = datetime.now(timezone.utc)
    transcript = {"schema_version": 1, "endpoint": ENDPOINT, "mode": mode,
                  "symbol": symbol, "sent": [], "received": []}
    transcript_bytes = 0
    deadline = time.monotonic() + timeout
    try:
        with connect(ENDPOINT, origin=ORIGIN, open_timeout=10, close_timeout=2,
                     additional_headers={"User-Agent": "trading-engine-research/1"}) as socket:
            for method, params in commands:
                message = _packet(method, params)
                transcript_bytes += len(message.encode())
                if transcript_bytes > MAX_TRANSCRIPT_BYTES:
                    raise TradingViewSourceError("TradingView transcript is too large")
                socket.send(message)
                transcript["sent"].append(message)
            done = False
            while time.monotonic() < deadline and not done:
                message = socket.recv(timeout=max(0.1, deadline - time.monotonic()))
                if not isinstance(message, str):
                    raise TradingViewSourceError("TradingView returned a binary frame")
                transcript_bytes += len(message.encode())
                if transcript_bytes > MAX_TRANSCRIPT_BYTES:
                    raise TradingViewSourceError("TradingView transcript is too large")
                transcript["received"].append(message)
                transcript_bytes, done = _handle_packets(
                    socket, transcript, message, mode, transcript_bytes,
                )
            if not done:
                raise TradingViewSourceError("TradingView request timed out")
    except (OSError, TimeoutError, WebSocketException) as exc:
        raise TradingViewSourceError("TradingView request failed") from exc
    body = json.dumps(transcript, sort_keys=True, separators=(",", ":")).encode()
    if len(body) > MAX_TRANSCRIPT_BYTES:
        raise TradingViewSourceError("TradingView transcript is too large")
    return Transcript(body, requested, datetime.now(timezone.utc))


def packets(transcript: Transcript) -> list[dict]:
    try:
        payload = json.loads(transcript.body)
        received = payload["received"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TradingViewSourceError("TradingView transcript JSON is invalid") from exc
    if not isinstance(received, list) or not all(isinstance(item, str) for item in received):
        raise TradingViewSourceError("TradingView transcript shape is invalid")
    return [packet for raw in received for packet in parse_frames(raw) if isinstance(packet, dict)]


def parse_realtime(symbol: str, transcript: Transcript) -> dict:
    symbol = _symbol(symbol)
    values = {}
    completed = False
    key = "=" + json.dumps({"session": "regular", "symbol": symbol},
                            separators=(",", ":"))
    for packet in packets(transcript):
        if packet.get("m") == "qsd":
            try:
                item = packet["p"][1]
                if item["n"] == key and item["s"] == "ok":
                    values.update(item["v"])
            except (IndexError, KeyError, TypeError) as exc:
                raise TradingViewSourceError("TradingView quote shape is invalid") from exc
        elif packet.get("m") == "quote_completed":
            completed = True
    try:
        event_at = datetime.fromtimestamp(int(values["lp_time"]), timezone.utc)
        price = _number(values["lp"], "last price")
        raw_bid, raw_ask = values.get("bid"), values.get("ask")
        bid = None if raw_bid in (None, 0) else _number(raw_bid, "bid")
        ask = None if raw_ask in (None, 0) else _number(raw_ask, "ask")
        volume = _number(values["volume"], "volume", zero=True)
        exchange, provider = values["exchange"], values["provider_id"]
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise TradingViewSourceError("TradingView quote is incomplete") from exc
    received = transcript.received_at.astimezone(timezone.utc)
    age = received - event_at
    if (not completed or event_at > received or age > MAX_OBSERVATION_AGE
            or (bid is None) != (ask is None) or (bid is not None and bid > ask)):
        raise TradingViewSourceError("TradingView quote is stale or invalid")
    if any(not isinstance(item, str) or VENUE.fullmatch(item) is None for item in (exchange, provider)):
        raise TradingViewSourceError("TradingView venue metadata is invalid")
    return {"ticker": symbol.split(":", 1)[1], "event_at": event_at,
            "received_at": received, "payload": {"price": price, "bid": bid, "ask": ask,
            "volume": volume, "spread_available": bid is not None,
            "fresh": age <= MAX_REALTIME_AGE, "age_ms": age.total_seconds() * 1000,
            "resolved_exchange": exchange, "provider_id": provider,
            "requested_symbol": symbol, "feed": "tradingview_anonymous"}}


def _history_rows(transcript: Transcript) -> tuple[dict, list]:
    resolved = {}
    rows = []
    complete = False
    for packet in packets(transcript):
        if packet.get("m") == "symbol_resolved":
            try:
                resolved = packet["p"][2]
            except (IndexError, TypeError) as exc:
                raise TradingViewSourceError("symbol metadata invalid") from exc
        elif packet.get("m") == "timescale_update":
            try:
                rows.extend(packet["p"][1]["$prices"]["s"])
            except (IndexError, KeyError, TypeError):
                pass
        elif packet.get("m") == "series_completed":
            complete = True
    if not complete or not isinstance(resolved, dict):
        raise TradingViewSourceError("TradingView history is incomplete")
    return resolved, rows


def parse_history(symbol: str, start: date, end: date, transcript: Transcript) -> list[dict]:
    _symbol(symbol)
    resolved, rows = _history_rows(transcript)
    provider = resolved.get("source_id") or resolved.get("provider_id") or "unknown"
    exchange = resolved.get("exchange") or resolved.get("listed_exchange") or "unknown"
    if any(not isinstance(item, str) or VENUE.fullmatch(item) is None for item in (provider, exchange)):
        raise TradingViewSourceError("TradingView history metadata is invalid")
    result, seen = [], set()
    for row in rows:
        try:
            values = row["v"]
            event_at = datetime.fromtimestamp(int(values[0]), timezone.utc)
            o, high, low, close = [_number(value, "OHLC") for value in (values[1], values[2], values[3], values[4])]
            volume = _number(values[5], "volume", zero=True)
        except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
            raise TradingViewSourceError("TradingView history bar is invalid") from exc
        if not start <= event_at.date() <= end:
            continue
        if event_at in seen or low > min(o, high, close) or high < max(o, low, close):
            raise TradingViewSourceError("TradingView history OHLCV is invalid")
        seen.add(event_at)
        result.append({"ticker": symbol.split(":", 1)[1], "event_at": event_at,
            "payload": {"open": o, "high": high, "low": low, "close": close,
            "volume": volume, "requested_symbol": symbol, "resolved_exchange": exchange,
            "provider_id": provider, "adjustment": "splits",
            "historical_authority": "retrieval_time_research"}})
    if not result:
        raise TradingViewSourceError("TradingView history range has no bars")
    return result


Fetch = Callable[..., Transcript]
