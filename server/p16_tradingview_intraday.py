"""Versioned TradingView five-minute capture for inert P16 fill research."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from datetime import time as clock
from zoneinfo import ZoneInfo

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from . import tradingview_source as tv

SOURCE_VERSION = "p16-tradingview-chart-5m-v1"
RESOLUTION = "5"
# Noon retries still need the 09:30 opening bars in the returned history.
BAR_COUNT = 40
_NEW_YORK = ZoneInfo("America/New_York")


def request_identity(symbol: str) -> dict:
    tv._symbol(symbol)
    return {
        "symbol": symbol,
        "resolution": RESOLUTION,
        "bar_count": BAR_COUNT,
        "session": "regular",
        "adjustment": "splits",
    }


def commands(symbol: str, session_id: str) -> list[tuple[str, list]]:
    """Return the exact chart commands; daily-history commands stay untouched."""
    request = request_identity(symbol)
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        raise tv.TradingViewSourceError("P16 chart session is invalid")
    resolved = "=" + json.dumps(
        {"symbol": symbol, "adjustment": request["adjustment"],
         "session": request["session"]}, separators=(",", ":"),
    )
    return [
        ("set_auth_token", ["unauthorized_user_token"]),
        ("chart_create_session", [session_id]),
        ("resolve_symbol", [session_id, "ser_1", resolved]),
        ("create_series", [session_id, "$prices", "s1", "ser_1",
                           RESOLUTION, BAR_COUNT]),
    ]


def _receive_packets(socket, message: str, transcript: dict, complete: bool) -> bool:
    for packet in tv.parse_frames(message):
        if isinstance(packet, int):
            payload = f"~h~{packet}"
            heartbeat = f"~m~{len(payload)}~m~{payload}"
            socket.send(heartbeat)
            transcript["sent"].append(heartbeat)
        elif packet.get("m") == "protocol_error":
            raise tv.TradingViewSourceError("TradingView protocol error")
        elif packet.get("m") == "series_completed":
            complete = True
    return complete


def fetch(symbol: str, *, timeout: float = 15.0) -> tv.Transcript:
    """Fetch one bounded exact transcript. No caller is scheduled before W9."""
    session_id = "cs_p16fills"
    requested = datetime.now(timezone.utc)
    transcript = {
        "schema_version": 1,
        "mode": "p16_history_5m",
        "source_version": SOURCE_VERSION,
        "endpoint": tv.ENDPOINT,
        "request": request_identity(symbol),
        "sent": [],
        "received": [],
    }
    size, deadline = 0, time.monotonic() + timeout
    try:
        with connect(
            tv.ENDPOINT, origin=tv.ORIGIN, open_timeout=10, close_timeout=2,
            additional_headers={"User-Agent": "trading-engine-research/1"},
        ) as socket:
            for method, params in commands(symbol, session_id):
                message = tv._packet(method, params)
                size += len(message.encode())
                if size > tv.MAX_TRANSCRIPT_BYTES:
                    raise tv.TradingViewSourceError("TradingView transcript is too large")
                socket.send(message)
                transcript["sent"].append(message)
            complete = False
            while time.monotonic() < deadline and not complete:
                message = socket.recv(timeout=max(0.1, deadline - time.monotonic()))
                if not isinstance(message, str):
                    raise tv.TradingViewSourceError("TradingView returned a binary frame")
                size += len(message.encode())
                if size > tv.MAX_TRANSCRIPT_BYTES:
                    raise tv.TradingViewSourceError("TradingView transcript is too large")
                transcript["received"].append(message)
                complete = _receive_packets(socket, message, transcript, complete)
            if not complete:
                raise tv.TradingViewSourceError("TradingView request timed out")
    except (OSError, TimeoutError, WebSocketException) as exc:
        raise tv.TradingViewSourceError("TradingView request failed") from exc
    body = json.dumps(transcript, sort_keys=True, separators=(",", ":")).encode()
    if len(body) > tv.MAX_TRANSCRIPT_BYTES:
        raise tv.TradingViewSourceError("TradingView transcript is too large")
    return tv.Transcript(body, requested, datetime.now(timezone.utc))


def parse(symbol: str, session_date: date, transcript: tv.Transcript) -> dict:
    """Extract exactly the first three regular-session bars, stamped by start."""
    request = request_identity(symbol)
    try:
        envelope = json.loads(transcript.body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise tv.TradingViewSourceError("P16 transcript JSON is invalid") from exc
    if (envelope.get("mode") != "p16_history_5m"
            or envelope.get("source_version") != SOURCE_VERSION
            or envelope.get("request") != request):
        raise tv.TradingViewSourceError("P16 transcript request identity differs")
    resolved, rows = tv._history_rows(transcript)
    provider = resolved.get("source_id") or resolved.get("provider_id") or "unknown"
    venue = resolved.get("exchange") or resolved.get("listed_exchange") or "unknown"
    expected = [datetime.combine(session_date, clock(9, 30 + 5 * index), _NEW_YORK)
                .astimezone(timezone.utc) for index in range(3)]
    observed = {}
    for row in rows:
        try:
            values = row["v"]
            started = datetime.fromtimestamp(int(values[0]), timezone.utc)
            prices = [tv._number(value, "OHLC") for value in values[1:5]]
            volume = tv._number(values[5], "volume", zero=True)
        except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
            raise tv.TradingViewSourceError("P16 five-minute bar is invalid") from exc
        if started not in expected:
            continue
        if started in observed or prices[2] > min(prices) or prices[1] < max(prices):
            raise tv.TradingViewSourceError("P16 five-minute OHLCV is invalid")
        observed[started] = {
            "start_at": started, "open": prices[0], "high": prices[1],
            "low": prices[2], "close": prices[3], "volume": volume,
            "vwap_value": None, "vwap_kind": None, "volume_scope": "bar",
        }
    return {
        "source": tv.SOURCE_ID, "source_version": SOURCE_VERSION,
        "venue": venue, "provider": provider, "currency": "USD",
        "adjustment": "splits", "resolution": RESOLUTION,
        "regular_session": True, "requested_range": BAR_COUNT,
        "bars": [observed[item] for item in expected if item in observed],
        "missing_starts": [item.isoformat() for item in expected if item not in observed],
    }
