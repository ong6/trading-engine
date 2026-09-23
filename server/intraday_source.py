"""Exact-response Yahoo chart adapter for bounded agent intraday context."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Callable
from urllib.parse import quote

ENDPOINT = "https://query2.finance.yahoo.com/v8/finance/chart"
ENDPOINT_API_VERSION = "yahoo_finance_chart_v8"
INTERVAL = "5m"
RANGE = "2d"
EVENTS = "div,splits"
MAX_RESPONSE_BYTES = 2_000_000
PROVIDER_TICKER = re.compile(r"^[A-Za-z0-9.^=-]{1,32}$")


class IntradaySourceError(RuntimeError):
    """An intraday response cannot be retained or normalized safely."""


@dataclass(frozen=True)
class Response:
    body: bytes
    content_type: str
    status_code: int
    requested_at: datetime
    received_at: datetime


Fetch = Callable[[str, datetime], Response]


def source_version() -> str:
    try:
        value = version("yfinance")
    except PackageNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise IntradaySourceError("yfinance version is unavailable") from exc
    if not value or len(value) > 64 or not value.isprintable():
        raise IntradaySourceError("yfinance version is invalid")
    return value


def request_identity(provider_ticker: str) -> dict:
    if PROVIDER_TICKER.fullmatch(provider_ticker) is None:
        raise IntradaySourceError("provider ticker is invalid")
    return {
        "provider_ticker": provider_ticker, "range": RANGE, "interval": INTERVAL,
        "events": EVENTS, "includePrePost": False,
    }


def endpoint_url(provider_ticker: str) -> str:
    request_identity(provider_ticker)
    return f"{ENDPOINT}/{quote(provider_ticker, safe='')}"


def _fetch(provider_ticker: str, _observed_at: datetime) -> Response:
    request = request_identity(provider_ticker)
    try:
        from yfinance.data import YfData

        requested_at = datetime.now(timezone.utc)
        response = YfData().get(
            endpoint_url(provider_ticker),
            params={key: value for key, value in request.items() if key != "provider_ticker"},
            timeout=20,
        )
        received_at = datetime.now(timezone.utc)
        return Response(
            bytes(response.content), response.headers.get("content-type", ""),
            int(response.status_code), requested_at, received_at,
        )
    except Exception as exc:
        raise IntradaySourceError("intraday request failed") from exc


def _utc(value: datetime, field: str) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise IntradaySourceError(f"{field} is invalid")
    return value.astimezone(timezone.utc)


def _price(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IntradaySourceError("intraday price is invalid")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise IntradaySourceError("intraday price is invalid")
    return number


def parse(ticker: str, provider_ticker: str, response: Response) -> list[dict]:
    """Normalize complete OHLCV bars from one exact chart response."""
    requested = _utc(response.requested_at, "request timestamp")
    received = _utc(response.received_at, "receipt timestamp")
    content_type = response.content_type.split(";", 1)[0].strip().lower()
    if requested > received or response.status_code != 200 or content_type != "application/json":
        raise IntradaySourceError("intraday response metadata is invalid")
    if not response.body or len(response.body) > MAX_RESPONSE_BYTES:
        raise IntradaySourceError("intraday response size is invalid")
    try:
        chart = json.loads(response.body)["chart"]
        result = chart["result"][0]
        timestamps = result["timestamp"]
        values = result["indicators"]["quote"][0]
    except (IndexError, KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise IntradaySourceError("intraday response JSON is invalid") from exc
    fields = ("open", "high", "low", "close", "volume")
    if (
        not isinstance(chart, dict) or chart.get("error") is not None
        or result.get("meta", {}).get("symbol") != provider_ticker
        or not isinstance(timestamps, list) or not isinstance(values, dict)
        or any(not isinstance(values.get(field), list)
               or len(values[field]) != len(timestamps) for field in fields)
    ):
        raise IntradaySourceError("intraday response shape is invalid")
    bars, seen = [], set()
    for index, epoch in enumerate(timestamps):
        row = [values[field][index] for field in fields]
        if any(value is None for value in row):
            continue
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            raise IntradaySourceError("intraday event timestamp is invalid")
        event_at = datetime.fromtimestamp(epoch, timezone.utc)
        if event_at > received or event_at in seen:
            raise IntradaySourceError("intraday event timestamp is invalid")
        seen.add(event_at)
        open_price, high, low, close = map(_price, row[:4])
        volume = row[4]
        if (
            isinstance(volume, bool) or not isinstance(volume, (int, float))
            or not math.isfinite(volume) or volume < 0 or not float(volume).is_integer()
            or low > min(open_price, high, close) or high < max(open_price, low, close)
        ):
            raise IntradaySourceError("intraday OHLCV is invalid")
        bars.append({
            "ticker": ticker, "event_at": event_at, "open": open_price,
            "high": high, "low": low, "close": close, "volume": int(volume),
        })
    if not bars:
        raise IntradaySourceError("intraday response has no usable bars")
    return bars


def capture(
    ticker: str, provider_ticker: str, observed_at: datetime, fetch: Fetch = _fetch,
) -> dict:
    request = request_identity(provider_ticker)
    response = fetch(provider_ticker, observed_at)
    return {"endpoint": endpoint_url(provider_ticker),
            "request": request, "response": response,
            "quotes": parse(ticker, provider_ticker, response)}
